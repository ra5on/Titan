"""System-disk growth exposes no caller-selected disk and requires live admin access."""
import unittest

from titan.core import Error
from titan.demo import Demo
from test_lifecycle_http import HTTPFixture


REVISION = "a" * 64
ARGUMENTS = {"expected_revision": REVISION, "confirmation": "ERWEITERN"}


class SystemDiskHTTPTests(HTTPFixture, unittest.TestCase):
    def test_status_is_private_uncached_and_does_not_allow_target_selection(self):
        for actor, expected in ((None, 401), ("reader", 403)):
            self.assertEqual(self.request("/api/system-disk", actor=actor)[0], expected)
        self.agent.call.assert_not_called()
        self.agent.call.return_value = {"supported": True, "revision": REVISION}
        status, value, headers = self.json_request("/api/system-disk")
        self.assertEqual(status, 200)
        self.assertEqual(value["revision"], REVISION)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.agent.call.assert_called_once_with("system_disk")
        self.agent.call.reset_mock()
        self.assertEqual(self.request("/api/system-disk?disk=/dev/sdb")[0], 400)
        self.agent.call.assert_not_called()

    def test_growth_requires_admin_csrf_and_strict_revision_confirmation(self):
        body = {"operation": "system_disk_grow", "arguments": ARGUMENTS}
        for actor, csrf, expected in ((None, None, 401), ("reader", None, 403), ("admin", "wrong", 403)):
            self.assertEqual(self.request("/api/actions", body, actor=actor, csrf=csrf)[0], expected)
        invalid = [{}, {"confirmation": "ERWEITERN"}, {**ARGUMENTS, "disk": "/dev/sdb"},
                   {**ARGUMENTS, "expected_revision": None}, {**ARGUMENTS, "expected_revision": "old"},
                   {**ARGUMENTS, "confirmation": "yes"}]
        for arguments in invalid:
            self.assertEqual(self.request("/api/actions", {**body, "arguments": arguments})[0], 400)
        self.agent.call.assert_not_called()

    def test_job_dispatch_retains_actor_audit_and_only_expected_arguments(self):
        status, response, _ = self.json_request("/api/actions", {"operation": "system_disk_grow", "arguments": ARGUMENTS})
        self.assertEqual(status, 202)
        job = self.wait_job(response["job"])
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["username"], "admin")
        self.agent.call.assert_called_once_with("system_disk_grow", **ARGUMENTS)

    def test_queued_action_rechecks_revoked_administrator(self):
        self.app.store.create_user("secondadmin", "secondadmin-original-password", "admin", "secondadmin")
        self.app.store.update_user("admin", enabled=False)
        with self.assertRaises(Error) as caught:
            self.app.admin_action("admin", "system_disk_grow", ARGUMENTS)
        self.assertEqual(caught.exception.status, 403)
        self.agent.call.assert_not_called()


class SystemDiskDemoTests(unittest.TestCase):
    def test_demo_growth_is_memory_only_idempotent_and_rejects_stale_revision(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            demo = Demo(Path(directory))
            before = demo.call("system_disk")
            result = demo.call("system_disk_grow", expected_revision=before["revision"], confirmation="ERWEITERN")
            self.assertTrue(result["simulation"])
            self.assertGreater(result["after"]["filesystem_size"], before["filesystem_size"])
            self.assertEqual(result["after"]["filesystem_used"], before["filesystem_used"])
            with self.assertRaises(Error):
                demo.call("system_disk_grow", expected_revision=before["revision"], confirmation="ERWEITERN")
            repeat = demo.call("system_disk_grow", expected_revision=result["after"]["revision"], confirmation="ERWEITERN")
            self.assertFalse(repeat["changed"])
            demo._temporary.cleanup()

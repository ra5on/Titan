from http.server import ThreadingHTTPServer
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock

from titan.core import Error
from titan.server import Application, Handler


class ManagementHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(self.temp.name)
        self.app.store.setup("admin", "admin-original-password")
        self.app.store.create_user("reader", "reader-original-password", "user", "reader")
        self.agent = Mock()
        self.agent.call.return_value = {"ok": True}
        self.app.agent = self.agent
        self.app.users.agent = self.agent
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.app = self.app
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.tokens = {name: self.app.store.login(name, f"{name}-original-password") for name in ("admin", "reader")}

    def test_storage_locations_requires_admin_and_dispatches_read_operation(self):
        self.agent.call.return_value = {"items": [], "programs": [], "warnings": []}
        status, data = self.request("/api/storage-locations", actor="reader")
        self.assertEqual(status, 403)
        self.agent.call.assert_not_called()
        status, data = self.request("/api/storage-locations")
        self.assertEqual(status, 200)
        self.assertEqual(data["items"], [])
        self.agent.call.assert_called_once_with("storage_locations")

    def tearDown(self):
        deadline = time.monotonic() + 3
        while any(job["status"] in ("queued", "running") for job in self.app.store.jobs()) and time.monotonic() < deadline:
            time.sleep(.01)
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def request(self, path, body=None, actor="admin", csrf=None):
        token, expected_csrf = self.tokens[actor]
        headers = {"Cookie": f"titan_session={token}", "X-CSRF-Token": expected_csrf if csrf is None else csrf,
                   "Content-Type": "application/json"}
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as response:
            return response.code, json.loads(response.read())

    def wait_job(self, job):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = next(item for item in self.app.store.jobs() if item["id"] == job)
            if current["status"] in ("completed", "failed"):
                return current
            time.sleep(.01)
        self.fail("Job did not finish")

    def test_normal_user_cannot_change_other_accounts_or_manage_backups(self):
        for path, body in (("/api/users/update", {"name": "admin", "role": "user"}),
                           ("/api/users/update", {"name": "reader", "display_name": "Selbst"}),
                           ("/api/actions", {"operation": "share_user_permission", "arguments": {"name": "docs", "user": "reader", "permission": "write"}}),
                           ("/api/users/remove", {"name": "admin", "confirmation": "admin"}),
                           ("/api/backup/settings", {}), ("/api/monitoring/ack", {"id": "x"})):
            self.assertEqual(self.request(path, body, actor="reader")[0], 403)
        self.agent.call.assert_not_called()

    def test_personal_share_patch_dispatches_only_target_identity(self):
        args = {"name": "docs", "user": "reader", "permission": "read"}
        status, result = self.request("/api/actions", {"operation": "share_user_permission", "arguments": args})
        self.assertEqual(status, 202)
        self.assertEqual(self.wait_job(result["job"])["status"], "completed")
        self.agent.call.assert_called_once_with("share_user_permission", **args)

    def test_personal_share_patch_rejects_bad_shape_and_requires_csrf(self):
        valid = {"name": "docs", "user": "reader", "permission": "read"}
        for arguments in ({"name": "docs", "user": "reader"}, {**valid, "writers": ["reader"]},
                          {**valid, "permission": "root"}, {**valid, "user": "../../root"}):
            self.assertEqual(self.request("/api/actions", {"operation": "share_user_permission", "arguments": arguments})[0], 400)
        self.assertEqual(self.request("/api/actions", {"operation": "share_user_permission", "arguments": valid}, csrf="invalid")[0], 403)
        self.assertEqual(self.app.store.jobs(), [])
        self.agent.call.assert_not_called()

    def test_profile_fields_create_update_and_list_without_smb_changes(self):
        status, result = self.request("/api/users", {"name": "lena", "password": "lena-original-password",
                                                    "role": "user", "display_name": "Léna", "description": "Fotos"})
        self.assertEqual(status, 202)
        self.assertEqual(self.wait_job(result["job"])["status"], "completed")
        self.agent.call.assert_called_once_with("account_create", name="lena", password="lena-original-password")
        self.agent.call.reset_mock()
        status, result = self.request("/api/users/update", {"name": "lena", "description": "Dokumente"})
        self.assertEqual(status, 202)
        self.assertEqual(self.wait_job(result["job"])["status"], "completed")
        self.agent.call.assert_not_called()
        self.agent.call.return_value = []
        status, result = self.request("/api/users")
        self.assertEqual(status, 200)
        row = next(item for item in result["web"] if item["name"] == "lena")
        self.assertEqual((row["display_name"], row["description"]), ("Léna", "Dokumente"))
        self.assertEqual((row["system_user"], row["role"]), ("lena", "user"))
        self.assertNotIn("password", row)

    def test_invalid_profiles_are_rejected_without_jobs_or_host_calls(self):
        for profile in ({"display_name": None}, {"description": "bad\ntext"}, {"display_name": "x" * 97},
                        {"description": "x" * 257}):
            self.assertEqual(self.request("/api/users/update", {"name": "reader", **profile})[0], 400)
            self.assertEqual(self.request("/api/users", {"name": "lena", "password": "lena-original-password",
                                                        "role": "user", **profile})[0], 400)
        self.assertEqual(self.app.store.jobs(), [])
        self.agent.call.assert_not_called()

    def test_profile_updates_require_csrf_and_recheck_queued_admin(self):
        self.assertEqual(self.request("/api/users/update", {"name": "reader", "display_name": "Rejected"}, csrf="invalid")[0], 403)
        self.app.store.create_user("second", "second-long-password", "admin", "second")
        pending = []
        self.app.jobs.submit = lambda actor, action, function, **kwargs: pending.append(function) or {"job": "pending"}
        self.assertEqual(self.request("/api/users/update", {"name": "reader", "display_name": "Rejected"})[0], 202)
        self.app.store.update_user("admin", role="user")
        with self.assertRaises(Error) as error:
            pending[0]()
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(self.app.store.user_record("reader")["display_name"], "")
        self.agent.call.assert_not_called()

    def test_new_management_mutations_require_csrf(self):
        for path, body in (("/api/users/update", {"name": "reader", "enabled": False}),
                           ("/api/users/remove", {"name": "reader", "confirmation": "reader"}),
                           ("/api/password", {"current_password": "reader-original-password", "password": "reader-changed-password"}),
                           ("/api/backup/settings", {}), ("/api/monitoring/ack", {"id": "x"})):
            self.assertEqual(self.request(path, body, csrf="invalid")[0], 403)
        self.agent.call.assert_not_called()

    def test_normal_user_changes_own_password_and_old_session_expires(self):
        status, result = self.request("/api/password", {"current_password": "reader-original-password", "password": "reader-changed-password"}, actor="reader")
        self.assertEqual(status, 202)
        job = self.wait_job(result["job"])
        self.assertEqual(job["status"], "completed")
        self.assertNotIn("reader-changed-password", json.dumps(self.app.store.jobs()))
        self.assertEqual(self.request("/api/jobs", actor="reader")[0], 401)
        self.app.store.login("reader", "reader-changed-password")

    def test_account_block_revokes_web_access_and_dispatches_smb_block(self):
        status, result = self.request("/api/users/update", {"name": "reader", "enabled": False})
        self.assertEqual(status, 202)
        self.assertEqual(self.wait_job(result["job"])["status"], "completed")
        self.assertEqual(self.request("/api/jobs", actor="reader")[0], 401)
        self.agent.call.assert_called_once_with("account_update", name="reader", enabled=False)

    def test_admin_deletes_user_and_revokes_access(self):
        status, result = self.request("/api/users/remove", {"name": "reader", "confirmation": "reader"})
        self.assertEqual(status, 202)
        job = self.wait_job(result["job"])
        self.assertEqual(job["status"], "completed")
        self.assertTrue(job["result"]["data_retained"])
        self.assertEqual(self.request("/api/jobs", actor="reader")[0], 401)
        self.assertEqual([item["name"] for item in self.app.store.users()], ["admin"])
        self.agent.call.assert_called_once_with("account_remove", name="reader")

    def test_removed_uid_reserves_are_hidden_from_user_and_permission_choices(self):
        self.agent.call.return_value = [{"name": "reader", "uid": 2000, "enabled": True},
                                      {"name": "deleted", "uid": 2001, "enabled": False, "removed": True}]
        status, result = self.request("/api/users")
        self.assertEqual(status, 200)
        self.assertEqual([item["name"] for item in result["system"]], ["reader"])

    def test_delete_requires_exact_body_and_confirmation(self):
        for body in ({"name": "reader"}, {"name": "reader", "confirmation": "wrong"},
                     {"name": "reader", "confirmation": "reader", "delete_data": True}):
            self.assertEqual(self.request("/api/users/remove", body)[0], 400)
        self.agent.call.assert_not_called()

    def test_self_delete_is_rejected_even_with_another_admin(self):
        self.app.store.create_user("second", "second-long-password", "admin", "second")
        self.assertEqual(self.request("/api/users/remove", {"name": "admin", "confirmation": "admin"})[0], 409)
        self.agent.call.assert_not_called()

    def test_failed_host_delete_keeps_blocked_user_for_retry(self):
        self.agent.call.side_effect = Error("SMB nicht erreichbar", 503)
        status, result = self.request("/api/users/remove", {"name": "reader", "confirmation": "reader"})
        self.assertEqual(status, 202)
        self.assertEqual(self.wait_job(result["job"])["status"], "failed")
        self.assertEqual(self.request("/api/jobs", actor="reader")[0], 401)
        self.assertFalse(self.app.store.user_record("reader")["enabled"])
        self.agent.call.side_effect = None
        status, result = self.request("/api/users/remove", {"name": "reader", "confirmation": "reader"})
        self.assertEqual(status, 202)
        self.assertEqual(self.wait_job(result["job"])["status"], "completed")

    def test_queued_delete_rechecks_admin_role_before_host_cleanup(self):
        self.app.store.create_user("second", "second-long-password", "admin", "second")
        pending = []
        self.app.jobs.submit = lambda actor, action, function, **kwargs: pending.append(function) or {"job": "pending"}
        self.assertEqual(self.request("/api/users/remove", {"name": "reader", "confirmation": "reader"})[0], 202)
        self.app.store.update_user("admin", role="user")
        with self.assertRaises(Error) as error:
            pending[0]()
        self.assertEqual(error.exception.status, 403)
        self.assertTrue(self.app.store.user_record("reader")["enabled"])
        self.agent.call.assert_not_called()

    def test_last_admin_and_self_block_are_rejected_before_host_calls(self):
        for change in ({"role": "user"}, {"enabled": False}):
            self.assertEqual(self.request("/api/users/update", {"name": "admin", **change})[0], 409)
        self.agent.call.assert_not_called()

    def test_injected_file_root_and_user_are_rejected(self):
        for extra in ({"root": "/etc"}, {"destination_root": "/etc"}, {"user": "root"}):
            status, _ = self.request("/api/files", {"share": "docs", "path": "file", "action": "copy", "destination": "new", **extra})
            self.assertEqual(status, 400)
        self.agent.call.assert_not_called()

    def test_trash_pagination_and_search_reach_restricted_agent(self):
        status, _ = self.request("/api/files", {"share": "docs", "action": "trash_list", "offset": 200,
                                               "limit": 200, "search": "invoice"}, actor="reader")
        self.assertEqual(status, 200)
        self.agent.call.assert_called_once_with("file", share="docs", action="trash_list", offset=200,
                                               limit=200, search="invoice", user="reader")

    def test_queued_privileged_job_rechecks_role(self):
        self.app.store.create_user("second", "second-long-password", "admin", "second")
        self.app.store.update_user("admin", role="user")
        with self.assertRaises(Error):
            self.app.admin_action("admin", "share_remove", {"name": "docs"})
        self.agent.call.assert_not_called()


if __name__ == "__main__":
    unittest.main()

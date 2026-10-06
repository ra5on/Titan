from contextlib import ExitStack

import copy

import json

from pathlib import Path

import tempfile

import threading

import unittest

from unittest.mock import Mock, patch

from titan import updates

from titan.core import Error, OperationCoordinator

from titan.demo import Demo

from titan.host import Host

from titan.server import Application

from test_lifecycle_http import HTTPFixture

CURRENT = "sha256:" + "a" * 64

PREVIOUS = "sha256:" + "b" * 64

class ScheduledStateTests(unittest.TestCase):
    def test_systemd_schedule_is_read_only_and_missing_schedule_is_none(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scheduled"
            with patch.object(updates, "SHUTDOWN_SCHEDULE", path):
                self.assertIsNone(updates.scheduled_reboot())
                path.write_text("USEC=2000000060000000\nMODE=reboot\nWARN_WALL=1\n")
                self.assertEqual(updates.scheduled_reboot(), {"at": 2000000060, "mode": "reboot"})
                path.write_text("MODE=reboot\n")
                with self.assertRaises(Error): updates.scheduled_reboot()

    def test_scheduled_reboot_blocks_new_mutations_but_live_state_stays_readable(self):
        host = Host.__new__(Host)
        host.directory = Path(tempfile.gettempdir()) / "titan-rollback-no-config-restore"
        host.lock, host.account_lock = threading.RLock(), threading.RLock()
        host.operation_coordinator = OperationCoordinator()
        host.op_vm_action = Mock()
        host.op_system_updates = Mock(return_value={"reboot_scheduled": True})
        with patch.object(updates, "scheduled_reboot", return_value={"at": 2000000060, "mode": "reboot"}):
            with self.assertRaises(Error) as caught: host.dispatch("vm_action", vm="id", action="start")
            self.assertEqual(caught.exception.status, 409)
            host.op_vm_action.assert_not_called()
            self.assertTrue(host.dispatch("system_updates")["reboot_scheduled"])



    def test_demo_rollback_and_reboot_are_simulation_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            demo = Demo(Path(temporary))
            self.addCleanup(demo._temporary.cleanup)
            with patch("titan.host.run") as command:
                prior = demo.call("system_updates")["rollback"]["digest"]
                self.assertTrue(demo.call("update_rollback", repository="ra5on/Titan", expected_digest=prior, confirmation="ROLLBACK")["simulation"])
                with self.assertRaises(Error):
                    demo.call("system_reboot", repository="ra5on/Titan", expected_digest=prior, confirmation="NEUSTART")
                for vm in demo.vms: vm["state"] = "shut off"
                self.assertTrue(demo.call("system_reboot", repository="ra5on/Titan", expected_digest=prior, confirmation="NEUSTART")["simulation"])
                command.assert_not_called()

class SystemActionHTTPTests(HTTPFixture, unittest.TestCase):
    def test_live_system_status_is_uncached_admin_only_and_no_mutation(self):
        for actor, code in ((None, 401), ("reader", 403)):
            self.assertEqual(self.request("/api/updates/system", actor=actor)[0], code)
        self.agent.call.assert_not_called()
        self.app.store.set_config("update", {"rollback": "stale"})
        self.agent.call.return_value = {"rollback":{"digest":PREVIOUS}}
        status, result, _ = self.json_request("/api/updates/system")
        self.assertEqual(status, 200)
        self.assertEqual(result["rollback"]["digest"], PREVIOUS)
        self.agent.call.assert_called_once_with("system_updates")
        self.assertEqual(self.request("/api/updates/system?cached=1")[0], 400)

    def test_admin_csrf_origin_and_exact_explicit_confirmation_required(self):
        for operation, confirmation in (("update_rollback", "ROLLBACK"), ("system_reboot", "NEUSTART")):
            body = {"operation": operation, "arguments": {"expected_digest": PREVIOUS, "confirmation": confirmation}}
            self.assertEqual(self.request("/api/actions", body, actor="reader")[0], 403)
            self.assertEqual(self.request("/api/actions", body, csrf="wrong")[0], 403)
            self.assertEqual(self.request("/api/actions", body, headers={"Origin": "https://foreign.example"})[0], 403)
            for arguments in ({"expected_digest": PREVIOUS}, {"expected_digest": PREVIOUS, "confirmation": "yes"},
                              {**body["arguments"], "force": True}, {**body["arguments"], "expected_digest": "latest"}):
                self.assertEqual(self.request("/api/actions", {**body, "arguments": arguments})[0], 400)
        self.agent.call.assert_not_called()

    def test_authorized_job_uses_current_repository_and_is_audited(self):
        for operation, confirmation in (("update_rollback", "ROLLBACK"), ("system_reboot", "NEUSTART")):
            arguments = {"expected_digest": PREVIOUS, "confirmation": confirmation}
            status, result, _ = self.json_request("/api/actions", {"operation": operation, "arguments": arguments})
            self.assertEqual(status, 202)
            self.assertEqual(self.wait_job(result["job"])["status"], "completed")
            self.agent.call.assert_any_call(operation, repository="ra5on/Titan", **arguments)
            self.assertTrue(any(item["action"] == operation for item in self.app.store.logs()))

    def test_queued_system_action_rechecks_revoked_admin(self):
        self.app.store.create_user("second", "second-long-password", "admin", "second")
        self.app.store.update_user("admin", role="user")
        for operation, confirmation in (("update_rollback", "ROLLBACK"), ("system_reboot", "NEUSTART")):
            with self.assertRaises(Error) as caught:
                self.app.admin_action("admin", operation, {"expected_digest": PREVIOUS, "confirmation": confirmation})
            self.assertEqual(caught.exception.status, 403)
        self.agent.call.assert_not_called()

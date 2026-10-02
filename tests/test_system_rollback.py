"""Existing signed OS deployments, explicit rollback, and delayed reboot safety."""
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from titan import updates
from titan.core import Error
from titan.demo import Demo
from titan.host import Host
from titan.server import Application
from test_lifecycle_http import HTTPFixture


REPO = "ghcr.io/ra5on/titan"
CURRENT = "sha256:" + "a" * 64
PREVIOUS = "sha256:" + "b" * 64
INFO = {"format": updates.FORMAT, "platform": "ucore-hci", "architecture": "x86_64",
        "version": "0.4.2", "release_stage": "alpha", "image_repository": REPO}


def deployment(digest, version):
    return {"image": REPO + "@" + digest, "digest": digest, "version": version, "incompatible": False}


def state():
    booted, previous = deployment(CURRENT, "0.4.2"), deployment(PREVIOUS, "0.4.1")
    return {"booted": booted, "rollback": previous, "staged": None, "rollback_queued": False,
            "reboot_required": False, "reboot_scheduled": False, "next_boot": copy.deepcopy(booted)}


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.before = state()
        self.after = {**copy.deepcopy(self.before), "rollback_queued": True, "reboot_required": True,
                      "next_boot": copy.deepcopy(self.before["rollback"])}
        self.stack.enter_context(patch.object(updates, "image_info", return_value=dict(INFO)))
        self.status = self.stack.enter_context(patch.object(updates, "system_status", side_effect=[self.before, self.before, self.after]))
        self.verify = self.stack.enter_context(patch.object(updates, "authenticate_deployment", return_value=REPO + "@" + PREVIOUS))
        self.backup = self.stack.enter_context(patch.object(updates, "backup_configuration", return_value="/backup/config.sqlite3"))
        self.command = self.stack.enter_context(patch("titan.host.run", return_value=""))

    def rollback(self):
        return updates.rollback("ra5on/Titan", PREVIOUS, "ROLLBACK", "/config.sqlite3")

    def test_exact_existing_authenticated_deployment_is_queued_without_reboot(self):
        result = self.rollback()
        self.verify.assert_called_once_with("ra5on/Titan", self.before["rollback"], INFO)
        self.backup.assert_called_once_with("/config.sqlite3")
        self.command.assert_called_once_with(["bootc", "rollback"], timeout=120)
        self.assertTrue(result["rollback_queued"])
        self.assertFalse(result["automatic_reboot"])
        self.assertIn("/etc", result["message"])

    def test_missing_pending_same_or_incompatible_deployment_never_mutates(self):
        variants = [{"rollback": None}, {"reboot_required": True}, {"reboot_scheduled": True},
                    {"rollback": deployment(CURRENT, "0.4.2")},
                    {"rollback": {**deployment(PREVIOUS, "0.4.1"), "incompatible": True}},
                    {"booted": {**deployment(CURRENT, "0.4.2"), "incompatible": True}}]
        for variant in variants:
            with self.subTest(variant=variant):
                self.status.side_effect = [{**state(), **variant}]
                with self.assertRaises(Error) as caught:
                    self.rollback()
                self.assertEqual(caught.exception.status, 409)
                self.command.assert_not_called()
                self.backup.assert_not_called()
                self.verify.assert_not_called()

    def test_mismatched_expected_digest_rejects_stale_browser(self):
        with self.assertRaises(Error) as caught:
            updates.rollback("ra5on/Titan", CURRENT, "ROLLBACK", "/config.sqlite3")
        self.assertEqual(caught.exception.status, 409)
        self.command.assert_not_called()
        self.verify.assert_not_called()

    def test_authentication_or_configuration_backup_failure_blocks_boot_entry_change(self):
        self.verify.side_effect = Error("Signature invalid")
        with self.assertRaises(Error): self.rollback()
        self.backup.assert_not_called()
        self.command.assert_not_called()
        self.verify.side_effect = None
        self.status.side_effect = [self.before]
        self.backup.side_effect = Error("Database unavailable")
        with self.assertRaises(Error): self.rollback()
        self.command.assert_not_called()

    def test_external_bootc_change_during_authentication_is_rechecked(self):
        fresh = {**copy.deepcopy(self.before), "rollback": deployment("sha256:" + "c" * 64, "0.4.0")}
        self.status.side_effect = [self.before, fresh]
        with self.assertRaises(Error) as caught: self.rollback()
        self.assertEqual(caught.exception.status, 409)
        self.command.assert_not_called()

    def test_successful_process_with_wrong_queue_cannot_report_success(self):
        for result in ({**self.after, "rollback_queued": False},
                       {**self.after, "staged": deployment(CURRENT, "0.4.2")},
                       {**self.after, "rollback": deployment("sha256:" + "c" * 64, "0.4.0")},
                       {**self.after, "booted": deployment("sha256:" + "c" * 64, "0.4.0")}):
            with self.subTest(result=result):
                self.status.side_effect = [self.before, self.before, result]
                with self.assertRaises(Error) as caught: self.rollback()
                self.assertEqual(caught.exception.status, 503)

    def test_wrong_confirmation_rejects_before_any_status_or_command(self):
        with self.assertRaises(Error):
            updates.rollback("ra5on/Titan", PREVIOUS, "yes", "/config.sqlite3")
        self.status.assert_not_called()
        self.command.assert_not_called()


class RollbackAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.release = {"tag_name": "v0.4.1", "name": "Titan 0.4.1 Alpha", "prerelease": True}
        self.manifest = {"format": updates.FORMAT, "platform": "ucore-hci", "architecture": "x86_64",
                         "version": "0.4.1", "release_stage": "alpha", "image": REPO + "@" + PREVIOUS,
                         "boot_test": "passed", "runtime_test": "passed"}
        self.fetch = self.stack.enter_context(patch.object(updates, "fetch", side_effect=lambda *a: json.dumps(self.release).encode()))
        self.stack.enter_context(patch.object(updates, "read_token", return_value=None))
        self.verified = self.stack.enter_context(patch.object(updates, "verified_release", return_value=(self.manifest, {})))
        self.policy = self.stack.enter_context(patch.object(updates, "verify_container_policy"))

    def test_prior_digest_authenticated_by_signed_manifest_including_initial_install(self):
        target = deployment(PREVIOUS, "0.4.1")
        target["image"] = REPO + ":v0.4.1"
        self.assertEqual(updates.authenticate_deployment("ra5on/Titan", target, INFO), REPO + "@" + PREVIOUS)
        self.fetch.assert_called_once_with("https://api.github.com/repos/ra5on/Titan/releases/tags/v0.4.1", None)
        self.policy.assert_called_once_with(INFO)

    def test_valid_signature_for_other_digest_version_stage_or_failed_runtime_is_rejected(self):
        for changes in ({"image": REPO + "@" + CURRENT}, {"version": "0.4.0"},
                        {"release_stage": "stable"}, {"runtime_test": "failed"}, {"image": "ghcr.io/attacker/titan@" + PREVIOUS}):
            with self.subTest(changes=changes):
                manifest = {**self.manifest, **changes}
                self.verified.return_value = manifest, {}
                with self.assertRaises(Error):
                    updates.authenticate_deployment("ra5on/Titan", deployment(PREVIOUS, "0.4.1"), INFO)
                self.policy.assert_not_called()

    def test_foreign_invalid_or_incompatible_target_is_rejected_without_network(self):
        for changes in ({"image": REPO + "-fake:v0.4.1"}, {"image": REPO + "@" + CURRENT},
                        {"version": "Fedora44"}, {"incompatible": True}, {"digest": "short"}):
            with self.subTest(changes=changes), self.assertRaises(Error):
                updates.authenticate_deployment("ra5on/Titan", {**deployment(PREVIOUS, "0.4.1"), **changes}, INFO)
            self.fetch.assert_not_called()

    def test_changed_container_signature_policy_blocks_rollback(self):
        self.policy.side_effect = Error("Policy relaxed")
        with self.assertRaises(Error):
            updates.authenticate_deployment("ra5on/Titan", deployment(PREVIOUS, "0.4.1"), INFO)


class RebootTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.before = state()
        self.stack.enter_context(patch.object(updates, "image_info", return_value=dict(INFO)))
        self.status = self.stack.enter_context(patch.object(updates, "system_status", side_effect=[self.before, self.before]))
        self.verify = self.stack.enter_context(patch.object(updates, "authenticate_deployment"))
        self.backup = self.stack.enter_context(patch.object(updates, "backup_configuration", return_value="/backup/config.sqlite3"))
        self.command = self.stack.enter_context(patch("titan.host.run", return_value=""))
        self.scheduled = self.stack.enter_context(patch.object(updates, "scheduled_reboot", return_value={"at": 2000000060, "mode": "reboot"}))

    def reboot(self):
        return updates.reboot("ra5on/Titan", self.before["next_boot"]["digest"], "NEUSTART", "/config.sqlite3")

    def test_regular_reboot_is_delayed_and_returns_schedule_and_backup(self):
        result = self.reboot()
        self.assertEqual(result["delay_seconds"], 60)
        self.assertTrue(result["reboot_scheduled"])
        self.assertFalse(result["automatic_reboot"])
        self.command.assert_any_call(["virsh", "list", "--name"], timeout=30)
        self.command.assert_any_call(["shutdown", "-r", "+1", "Titan: ausdrücklich bestätigter Systemneustart"], timeout=30)
        self.verify.assert_not_called()
        self.backup.assert_called_once()

    def test_every_active_libvirt_guest_blocks_reboot_and_is_named(self):
        self.command.return_value = "titan-linux\nexternal-domain\n"
        with self.assertRaises(Error) as caught: self.reboot()
        self.assertEqual(caught.exception.status, 409)
        self.assertIn("titan-linux", str(caught.exception))
        self.assertIn("external-domain", str(caught.exception))
        self.backup.assert_not_called()
        self.assertEqual(self.command.call_count, 1)

    def test_missing_libvirt_status_cannot_be_treated_as_no_guests(self):
        self.command.side_effect = Error("libvirt unreachable", 503)
        with self.assertRaises(Error): self.reboot()
        self.backup.assert_not_called()
        self.assertEqual(self.command.call_count, 1)

    def test_pending_update_or_rollback_is_authenticated_before_activation(self):
        self.before.update(rollback_queued=True, reboot_required=True, next_boot=self.before["rollback"])
        self.reboot()
        self.verify.assert_called_once_with("ra5on/Titan", self.before["rollback"], INFO)

    def test_stale_digest_changed_status_and_existing_schedule_block_reboot(self):
        with self.assertRaises(Error):
            updates.reboot("ra5on/Titan", PREVIOUS, "NEUSTART", "/config.sqlite3")
        self.command.assert_not_called()
        self.status.side_effect = [{**state(), "reboot_scheduled": True}]
        with self.assertRaises(Error): self.reboot()
        self.command.assert_not_called()
        fresh = {**state(), "next_boot": deployment(PREVIOUS, "0.4.1")}
        self.status.side_effect = [state(), fresh]
        with self.assertRaises(Error): self.reboot()
        self.assertEqual(self.command.call_count, 1)

    def test_systemd_must_confirm_schedule(self):
        for scheduled in (None, {"at": 2000000060, "mode": "poweroff"}):
            with self.subTest(scheduled=scheduled):
                self.status.side_effect = [self.before, self.before]
                self.scheduled.return_value = scheduled
                with self.assertRaises(Error) as caught: self.reboot()
                self.assertEqual(caught.exception.status, 503)


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
        host.op_vm_action = Mock()
        host.op_system_updates = Mock(return_value={"reboot_scheduled": True})
        with patch.object(updates, "scheduled_reboot", return_value={"at": 2000000060, "mode": "reboot"}):
            with self.assertRaises(Error) as caught: host.dispatch("vm_action", vm="id", action="start")
            self.assertEqual(caught.exception.status, 409)
            host.op_vm_action.assert_not_called()
            self.assertTrue(host.dispatch("system_updates")["reboot_scheduled"])

    def test_first_install_has_clear_unavailable_rollback_reason(self):
        first = {**state(), "rollback": None}
        available, reason = updates.rollback_availability(first, INFO)
        self.assertFalse(available)
        self.assertIn("ersten Installation", reason)

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
        self.agent.call.return_value = state()
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


if __name__ == "__main__": unittest.main()

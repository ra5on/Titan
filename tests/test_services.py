import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from titan.core import Error, Jobs, Store
from titan.host import Host
from titan.rpc import AgentClient


class ServiceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.host = Host(self.temp.name, self.temp.name, self.temp.name)
        self.host._backups = Mock()
        self.host._monitor = Mock()

    def tearDown(self):
        self.temp.cleanup()

    def test_backup_routes_never_return_configuration_hashes(self):
        self.host._backups.list.return_value = [{"id": "b-test", "type": "shares"}]
        self.host._backups.state.return_value = {"last": {"ok": True}}
        self.host._backups.read_config.return_value = {"password": "private-hash"}
        result = self.host.dispatch("backups")
        self.assertEqual(result["items"][0]["id"], "b-test")
        self.host._backups.read_config.assert_not_called()
        self.assertNotIn("private-hash", str(result))

    def test_restore_routes_forward_only_explicit_arguments(self):
        self.host.dispatch("backup_restore", backup="b-test", share="docs", name="restored")
        self.host._backups.restore.assert_called_once_with("b-test", "docs", "restored")
        self.host.dispatch("backup_config_restore", backup="b-test", confirmation="b-test")
        self.host._backups.restore_config.assert_called_once_with("b-test", "b-test")
        self.host.dispatch("backup_save_settings", target="/mnt/backup", auto_backup=True)
        self.host._backups.save_settings.assert_called_once_with({"target": "/mnt/backup", "auto_backup": True})

    def test_status_uses_active_services_instead_of_installed_binaries(self):
        details = {"docker": {"installed": True, "active": False, "state": "failed"}}
        with patch.object(self.host, "service_status", return_value=details):
            result = self.host.op_status()
        self.assertFalse(result["services"]["docker"])
        self.assertEqual(result["service_details"], details)

    def test_status_does_not_wait_behind_long_running_backup(self):
        finished = threading.Event()
        with patch.object(self.host, "op_status", return_value={"ok": True}), self.host.lock:
            worker = threading.Thread(target=lambda: (self.host.dispatch("status"), finished.set()))
            worker.start()
            self.assertTrue(finished.wait(1), "Status waited for the backup lock")
        worker.join(1)

    def test_status_preserves_hardware_metrics_when_volume_inventory_fails(self):
        with patch.object(self.host, "service_status", return_value={}), \
                patch.object(self.host.volume_manager, "records", side_effect=Error("Datenträger nicht lesbar")):
            result = self.host.op_status()
        self.assertIsInstance(result["memory_total"], int)
        self.assertEqual(result["storage"], {"total": None, "used": None})
        self.assertIn("Datenträger nicht lesbar", result["storage_error"])

    def test_rpc_waits_for_queued_mutation_without_false_deadline_failure(self):
        with patch("titan.rpc.socket.socket") as socket_factory, patch("titan.rpc.send"), patch("titan.rpc.receive", return_value={"result": {"ok": True}}):
            stream = socket_factory.return_value.__enter__.return_value
            self.assertEqual(AgentClient().call("share_remove", name="docs"), {"ok": True})
            self.assertEqual([item.args for item in stream.settimeout.call_args_list], [(900,), (None,)])

    def test_security_job_runs_when_regular_queue_is_full(self):
        store = Store(self.temp.name)
        jobs = Jobs(store)
        started, release, revoked = threading.Event(), threading.Event(), threading.Event()
        def long_backup():
            started.set()
            release.wait(3)
        try:
            jobs.submit("admin", "backup_create", long_backup)
            self.assertTrue(started.wait(1))
            for _ in range(3):
                jobs.submit("admin", "backup_create", lambda: None)
            with self.assertRaises(Error):
                jobs.submit("admin", "backup_create", lambda: None)
            jobs.submit("admin", "user_update", lambda: revoked.set(), security=True)
            self.assertTrue(revoked.wait(1), "Account revocation waited behind the backup queue")
        finally:
            release.set()
            deadline = time.monotonic() + 3
            while any(item["status"] in ("queued", "running") for item in store.jobs()) and time.monotonic() < deadline:
                time.sleep(.01)

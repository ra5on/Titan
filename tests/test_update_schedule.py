"""Queued updates honor the current maintenance window and account status."""
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from titan.core import Error
from titan.server import Application


class CurrentUpdatePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.app = Application(self.temporary.name, demo=True)
        self.addCleanup(self.app.agent._temporary.cleanup)
        self.app.agent = Mock()
        self.app.save_settings({"installation": "automatic", "window_day": 6, "window_hour": 3})

    def test_queued_automatic_install_is_rejected_after_window_passes(self):
        with patch("titan.server.time.localtime", return_value=SimpleNamespace(tm_wday=6, tm_hour=4)):
            with self.assertRaises(Error) as error:
                self.app.install_update("system", "v1.0.0", automatic=True)
        self.assertEqual(error.exception.status, 409)
        self.app.agent.call.assert_not_called()

    def test_queued_automatic_install_is_rejected_after_schedule_changes(self):
        queued = lambda: self.app.install_update("system", "v1.0.0", automatic=True)
        self.app.save_settings({"window_day": 0, "window_hour": 8})
        with patch("titan.server.time.localtime", return_value=SimpleNamespace(tm_wday=6, tm_hour=3)):
            with self.assertRaises(Error):
                queued()
        self.app.agent.call.assert_not_called()

    def test_automatic_install_proceeds_in_current_window(self):
        with patch("titan.server.time.localtime", return_value=SimpleNamespace(tm_wday=6, tm_hour=3)):
            self.app.install_update("system", "v1.0.0", automatic=True)
        self.app.agent.call.assert_called_once_with("update_install", repository="ra5on/Titan",
                                                    channel="stable", expected_version="v1.0.0")

    def test_manual_admin_install_does_not_require_maintenance_window(self):
        with patch("titan.server.time.localtime", return_value=SimpleNamespace(tm_wday=1, tm_hour=10)):
            self.app.install_update("demo", "v1.0.0")
        self.app.agent.call.assert_called_once()

    def test_admin_revoked_while_settings_waits_cannot_change_channel(self):
        self.app.store.create_user("second", "second-long-password", "admin", "second")
        attempted = threading.Event()
        lock = self.app.update_lock
        errors = []

        class ObservedLock:
            def __enter__(self):
                attempted.set()
                lock.acquire()
            def __exit__(self, *args):
                lock.release()

        self.app.update_lock = ObservedLock()
        def save():
            try:
                self.app.save_settings({"channel": "alpha"}, actor="demo")
            except Exception as exc:
                errors.append(exc)
        lock.acquire()
        worker = threading.Thread(target=save)
        worker.start()
        try:
            self.assertTrue(attempted.wait(2))
            self.app.store.update_user("demo", role="user")
        finally:
            lock.release()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], Error)
        self.assertEqual(errors[0].status, 403)
        self.assertEqual(self.app.store.settings()["channel"], "stable")


if __name__ == "__main__":
    unittest.main()

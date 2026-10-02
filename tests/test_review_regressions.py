"""Regressions for queued maintenance requests and transactional account creation."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from titan.core import Error, Store
from titan.host import Host


class WaitingLock:
    """Expose the point after dispatch admission and before actual lock acquisition."""
    def __init__(self):
        self.lock = threading.RLock()
        self.waiting = threading.Event()

    def __enter__(self):
        self.waiting.set()
        self.lock.acquire()
        return self

    def __exit__(self, *args):
        self.lock.release()


class ReviewRegressionTests(unittest.TestCase):
    def test_waiting_host_requests_recheck_maintenance_after_acquiring_lock(self):
        for operation, selected_lock in (("test_mutation", "lock"), ("account_update", "account_lock")):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                host = Host(directory)
                gate = WaitingLock()
                setattr(host, selected_lock, gate)
                mutations, errors = [], []
                setattr(host, "op_" + operation, lambda: mutations.append("must not execute"))
                gate.lock.acquire()
                def request():
                    try:
                        host.dispatch(operation)
                    except Exception as exc:
                        errors.append(exc)
                worker = threading.Thread(target=request, daemon=True)
                worker.start()
                try:
                    self.assertTrue(gate.waiting.wait(2), "RPC did not reach the locked dispatch boundary")
                    # Initial admission already succeeded. A restore is scheduled
                    # while this request is waiting on an earlier long operation.
                    (Path(directory) / "config-restore.lock").write_text("scheduled restore")
                finally:
                    gate.lock.release()
                    worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(mutations, [])
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], Error)
                self.assertEqual(errors[0].status, 503)

    def test_create_user_callback_sees_uncommitted_row_and_failure_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            observed = []
            def rejected_host_creation():
                with closing(sqlite3.connect(store.path)) as independent:
                    observed.append(independent.execute("SELECT COUNT(*) FROM users WHERE name='newuser'").fetchone()[0])
                raise Error("Managed SMB account could not be created")
            with self.assertRaises(Error):
                store.create_user("newuser", "long-enough-password", "user", "newuser",
                                  before_commit=rejected_host_creation)
            self.assertEqual(observed, [0])
            self.assertEqual(store.users(), [])
            with closing(sqlite3.connect(store.path)) as independent:
                self.assertEqual(independent.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)

    def test_create_user_commits_only_after_successful_host_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            observed = []
            def successful_host_creation():
                with closing(sqlite3.connect(store.path)) as independent:
                    observed.append(independent.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            store.create_user("newuser", "long-enough-password", "user", "newuser",
                              before_commit=successful_host_creation)
            self.assertEqual(observed, [0])
            with closing(sqlite3.connect(store.path)) as independent:
                self.assertEqual(independent.execute("SELECT name,role,system_user FROM users").fetchone(),
                                 ("newuser", "user", "newuser"))


if __name__ == "__main__":
    unittest.main()

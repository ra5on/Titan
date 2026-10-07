"""Long maintenance must not freeze status, browsing or account revocation."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from titan.core import configuration_lock
from titan.host import Host


class OperationCoordinatorSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.host = Host(root / 'agent', root / 'data', root / 'vms', root / 'smb.conf')
        self.release = threading.Event()
        self.threads, self.errors = [], []
        self.addCleanup(self.close_threads)
        scheduled = patch('titan.updates.scheduled_reboot', return_value=None)
        scheduled.start()
        self.addCleanup(scheduled.stop)

    def close_threads(self):
        self.release.set()
        for thread in self.threads:
            thread.join(3)
        self.assertTrue(all(not thread.is_alive() for thread in self.threads), 'A dispatcher deadlock remained after cleanup.')
        self.assertEqual(self.errors, [])

    def launch(self, operation, **arguments):
        def work():
            try:
                self.host.dispatch(operation, **arguments)
            except Exception as exc:
                self.errors.append(exc)
        thread = threading.Thread(target=work, daemon=True)
        self.threads.append(thread)
        thread.start()
        return thread

    def slow(self, operation, **arguments):
        active = threading.Event()
        def work(**unused):
            active.set()
            self.release.wait(5)
            return {'ok': True}
        setattr(self.host, 'op_' + operation, work)
        self.launch(operation, **arguments)
        self.assertTrue(active.wait(1), 'The long operation did not start.')

    def probes(self):
        flags = {key: threading.Event() for key in ('status', 'update_progress', 'file', 'account_set_enabled')}
        for operation, flag in flags.items():
            setattr(self.host, 'op_' + operation, lambda done=flag, **unused: done.set())
        self.launch('status')
        self.launch('update_progress')
        self.launch('file', user='reader', share='docs', action='list')
        self.launch('account_set_enabled', name='reader', enabled=False)
        return flags

    def test_active_exclusive_backup_keeps_status_progress_files_and_revocation_live(self):
        self.slow('test_long_backup')
        try:
            flags = self.probes()
            for operation, flag in flags.items():
                self.assertTrue(flag.wait(1), operation + ' was frozen behind exclusive maintenance.')
            self.assertFalse(self.release.is_set(), 'The long backup must still be active.')
        finally:
            self.release.set()

    def test_queued_exclusive_maintenance_does_not_freeze_fast_read_or_security_lane(self):
        self.slow('app_install', app='titan-cloudflared')
        exclusive = threading.Event()
        self.host.op_test_maintenance = lambda: exclusive.set()
        self.launch('test_maintenance')
        with self.host.operation_coordinator.condition:
            self.assertTrue(self.host.operation_coordinator.condition.wait_for(
                lambda: self.host.operation_coordinator.waiting_writers > 0, timeout=1))
        try:
            flags = self.probes()
            for operation, flag in flags.items():
                self.assertTrue(flag.wait(1), operation + ' waited for an unrelated queued maintenance writer.')
            self.assertFalse(exclusive.is_set())
        finally:
            self.release.set()
        self.assertTrue(exclusive.wait(1))

    def test_web_configuration_flock_and_agent_snapshot_do_not_invert_account_lock_order(self):
        web = Path(self.temporary.name) / 'web'
        web.mkdir()
        snapshot_waiting, account_done, backup_done = (threading.Event() for _ in range(3))
        def snapshot():
            snapshot_waiting.set()
            with configuration_lock(web), self.host.account_lock:
                backup_done.set()
        self.host.op_test_snapshot = snapshot
        self.host.op_account_update = lambda **unused: account_done.set()
        # The web worker owns this cross-process flock before its account RPC.
        # A configuration snapshot is already admitted as exclusive agent work.
        with configuration_lock(web):
            self.launch('test_snapshot')
            self.assertTrue(snapshot_waiting.wait(1))
            self.launch('account_update', name='reader', enabled=False)
            self.assertTrue(account_done.wait(1), 'Account RPC waited for the snapshot which is waiting for its web configuration flock.')
            self.assertFalse(backup_done.is_set())
        self.assertTrue(backup_done.wait(1))


if __name__ == '__main__': unittest.main()

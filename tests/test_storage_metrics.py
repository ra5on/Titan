import tempfile
import unittest
from unittest.mock import patch
from titan.host import Host


class StorageMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.host = Host(self.temp.name, self.temp.name, self.temp.name)

    def test_zfs_root_capacity_uses_available_and_counts_each_pool_once(self):
        details = {'zfs': {'configured': True, 'active': True}}
        with patch.object(self.host, 'service_status', return_value=details), \
                patch('titan.host.run', return_value='tank\t200\t800\narchive\t50\t450') as command:
            storage = self.host.op_status()['storage']
        self.assertEqual(storage, {'total': 1500, 'used': 250, 'scope': 'data'})
        self.assertIn('0', command.call_args.args[0])

    def test_zfs_unavailable_never_falls_back_to_system_disk(self):
        with patch.object(self.host, 'service_status', return_value={'zfs': {'configured': True, 'active': False}}), \
                patch('titan.host.run', return_value=''), patch('titan.host.shutil.disk_usage') as usage:
            status = self.host.op_status()
        self.assertEqual(status['storage'], {'total': None, 'used': None})
        self.assertIn('ZFS', status['storage_error'])
        usage.assert_not_called()

    def test_zfs_and_ext4_are_combined_without_double_counting_children(self):
        with patch.object(self.host, 'service_status', return_value={'zfs': {'active': True}}), \
                patch.object(self.host.volume_manager, 'records', return_value=[{}]), \
                patch.object(self.host.volume_manager, 'inventory', return_value={'volumes': [{'mounted': True, 'total': 500, 'used': 20}]}), \
                patch('titan.host.run', return_value='tank\t200\t800'):
            self.assertEqual(self.host.op_status()['storage'], {'total': 1500, 'used': 220, 'scope': 'data'})

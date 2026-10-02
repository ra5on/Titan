import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from titan.core import Error
from titan.locations import locations


class LocationTests(unittest.TestCase):
    def host(self):
        return SimpleNamespace(share_root=Path('/var/srv/titan'), vm_root=Path('/var/lib/libvirt/images/titan'),
                               op_shares=lambda: [{'name': 'Fotos', 'path': '/var/mnt/data/Fotos'}])

    def collect(self, mounts, validator=None):
        validator = validator or Mock()
        with patch('titan.locations.Backups', return_value=validator), patch.object(Path, 'is_dir', return_value=True), \
                patch.object(Path, 'resolve', lambda self: self), patch('titan.locations.shutil.which', side_effect=lambda value, **kwargs: '/usr/bin/python3' if value == 'python3' else None):
            result = locations(self.host(), lambda args: json.dumps({'filesystems': mounts}))
        return result, validator

    def test_only_writable_mounted_external_locations_offered_for_backups(self):
        result, validator = self.collect([{'target': '/var/media/usb', 'fstype': 'ext4', 'options': 'rw'},
                                         {'target': '/var/mnt/readonly', 'options': 'ro'},
                                         {'target': '/', 'options': 'rw'}, {'target': 'relative', 'options': 'rw'}])
        self.assertEqual([item['path'] for item in result['items'] if item['backup_eligible']], ['/var/media/usb'])
        validator.validate_target.assert_called_once_with('/var/media/usb')
        self.assertEqual(result['programs'], [{'path': '/usr/bin/python3', 'label': 'Python 3'}])

    def test_mount_validation_rejection_never_offers_unsafe_backup(self):
        validator = Mock(); validator.validate_target.side_effect = Error('Quelle und Ziel überlappen')
        result, _ = self.collect([{'target': '/var/mnt/data', 'fstype': 'xfs', 'options': 'rw'}], validator)
        self.assertFalse(any(item['backup_eligible'] for item in result['items']))
        self.assertTrue(any(item['path'] == '/var/mnt/data' for item in result['items']))

    def test_duplicates_and_missing_directories_are_not_invented(self):
        result, _ = self.collect([{'target': '/var/media/usb', 'options': 'rw'}] * 2)
        self.assertEqual(sum(item['path'] == '/var/media/usb' for item in result['items']), 1)
        with patch('titan.locations.Backups'), patch.object(Path, 'is_dir', return_value=False):
            result = locations(self.host(), lambda args: '{}')
        self.assertEqual(result['items'], [])

    def test_mount_lookup_failure_is_reported_without_external_targets(self):
        with patch('titan.locations.Backups'), patch.object(Path, 'is_dir', return_value=True):
            result = locations(self.host(), lambda args: 'invalid')
        self.assertTrue(result['warnings'])
        self.assertFalse(any(item['backup_eligible'] for item in result['items']))


if __name__ == '__main__':
    unittest.main()

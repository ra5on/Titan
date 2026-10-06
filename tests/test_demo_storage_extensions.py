from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from titan.core import Error
from titan.demo import Demo
from titan.demo_storage_services import DemoStorageMixin, OPERATIONS


class DemoStorageExtensionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.demo = Demo(self.root)
        # Supports both the parent's eventual integrated Demo and this mixin's
        # isolated contract without mutating the production demo file here.
        for name in dir(DemoStorageMixin):
            if name.startswith('op_') or name == '_storage_helpers':
                if not hasattr(self.demo, name):
                    setattr(self.demo, name, types.MethodType(getattr(DemoStorageMixin, name), self.demo))
        original = self.demo.call
        self.demo.call = lambda operation, **args: getattr(self.demo, 'op_' + operation)(**args) if operation in OPERATIONS else original(operation, **args)

    def tearDown(self):
        self.demo._temporary.cleanup()
        self.tmp.cleanup()

    def test_backup_browse_selection_restore_actual_demo_content_and_parent_selection(self):
        self.demo.call('backup_save_settings', target='/var/media/demo-backup', include_config=False)
        result = self.demo.call('backup_create')
        backup = result['backup']['id']
        top = self.demo.call('backup_browse', backup=backup)
        self.assertEqual([item['name'] for item in top['items']], ['dokumente'])
        inside = self.demo.call('backup_browse', backup=backup, path='dokumente')
        self.assertTrue(any(item['name'] == 'Willkommen.txt' for item in inside['items']))
        response = self.demo.call('backup_restore_selection', backup=backup, paths=['dokumente/Willkommen.txt'], share='dokumente', name='restored')
        self.assertEqual((self.root / 'restored/dokumente/Willkommen.txt').read_text(), (self.root / 'Willkommen.txt').read_text())
        self.assertFalse((self.root / 'restored/dokumente/Dokumente').exists())
        with self.assertRaises(Error):
            self.demo.call('backup_browse', backup=backup, path='../etc')
        with self.assertRaises(Error):
            self.demo.call('backup_restore_selection', backup=backup, paths=['config'], share='dokumente', name='invalid')
        self.assertFalse((self.root / 'invalid').exists())

    def test_smarthost_and_smtp_never_called_in_demo(self):
        with patch('subprocess.run', side_effect=AssertionError('Host subprocess forbidden')), patch('smtplib.SMTP', side_effect=AssertionError('SMTP forbidden')), patch('smtplib.SMTP_SSL', side_effect=AssertionError('SMTP forbidden')):
            self.demo.call('smart_test', disk='/dev/sda', test='long')
            job = self.demo.call('storage_maintenance_save', type='smart', target='/dev/sda')
            self.assertEqual(self.demo.call('storage_maintenance')['jobs'][0]['id'], job['id'])
            self.demo.call('storage_maintenance_remove', id=job['id'])
            self.demo.call('notification_save_settings', host='smtp.example.org', sender='nas@example.org', recipients=['owner@example.org'], password='fake')
            settings = self.demo.call('notification_settings')
            self.assertNotIn('password', settings)
            self.assertTrue(settings['password_set'])
            self.assertIn('Demo', self.demo.call('notification_test')['message'])
        self.assertFalse((self.root / 'notification-credentials.json').exists())

    def test_snapshot_recovery_display_preserves_live_dataset_and_protects_dependency(self):
        self.demo.call('snapshot_create', dataset='tank/dokumente', name='point')
        original = dict(self.demo.datasets[0])
        result = self.demo.call('snapshot_restore', snapshot='tank/dokumente@point', name='restored')
        self.assertEqual(self.demo.datasets[0], original)
        self.assertEqual(result['dataset'], 'tank/dokumente/restored')
        with self.assertRaises(Error):
            self.demo.call('snapshot_remove', snapshot='tank/dokumente@point', confirmed=True)
        with self.assertRaises(Error):
            self.demo.call('snapshot_restore', snapshot='tank/dokumente@point', name='../bad')


if __name__ == '__main__':
    unittest.main()

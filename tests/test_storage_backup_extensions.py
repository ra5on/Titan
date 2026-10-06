import datetime
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests import test_backups as backup_fixtures
from titan.core import Error, atomic_json
from titan.storage_maintenance import StorageMaintenance
from titan.notification_delivery import NotificationDelivery
from titan.telemetry import Telemetry
from titan.monitoring import Monitor


class BackupSelectionTests(unittest.TestCase):
    setUp = backup_fixtures.BackupTests.setUp
    tearDown = backup_fixtures.BackupTests.tearDown

    def test_browse_only_public_files_and_pagination(self):
        backup = self.backups.create()
        top = self.backups.browse(backup['id'])
        self.assertEqual([item['name'] for item in top['items']], ['data'])
        listing = self.backups.browse(backup['id'], 'data', limit=1)
        self.assertEqual(listing['total'], 2)
        self.assertEqual(listing['items'][0]['name'], 'nested')
        self.assertEqual(self.backups.browse(backup['id'], 'data', offset=1, limit=1)['items'][0]['name'], 'hello.txt')
        nested = self.backups.browse(backup['id'], 'data/nested')
        self.assertEqual(nested['items'][0]['path'], 'data/nested/other.txt')
        self.assertTrue(nested['verified'])
        for path in ('config', 'config/config.json', '../config', '/etc', 'data/hello.txt', 'data/missing'):
            with self.subTest(path=path), self.assertRaises(Error):
                self.backups.browse(backup['id'], path)

    def test_single_file_and_subtree_restore_real_content_acl_and_no_overwrite(self):
        backup = self.backups.create()
        with patch.object(self.host, 'share_acl_transaction', wraps=self.host.share_acl_transaction) as acl:
            result = self.backups.restore_selection(backup['id'], ['data/hello.txt'], 'data', 'one-file')
            self.assertEqual(acl.call_args.args[0]['path'], result['path'])
        destination = Path(result['path']) / 'data'
        self.assertEqual((destination / 'hello.txt').read_text(), 'valuable file')
        self.assertFalse((destination / 'nested').exists())
        self.backups.restore_selection(backup['id'], ['data/nested'], 'data', 'subtree')
        self.assertEqual((self.host.share_root / 'data/subtree/data/nested/other.txt').read_text(), 'nested value')
        with self.assertRaises(Error):
            self.backups.restore_selection(backup['id'], ['data/nested'], 'data', 'one-file')
        self.assertEqual((self.host.share_root / 'data/hello.txt').read_text(), 'valuable file')

    def test_invalid_selection_and_corrupt_archive_leave_no_destination(self):
        backup = self.backups.create(include_config=False)
        for paths in ([], [None], [['data']], ['data/missing'], ['config/config.json'], ['data/../etc'], ['data/hello.txt', 'data/hello.txt']):
            with self.subTest(paths=paths), self.assertRaises(Error):
                self.backups.restore_selection(backup['id'], paths, 'data', 'bad-selection')
            self.assertFalse((self.host.share_root / 'data/bad-selection').exists())
        archive = self.backups.namespace() / backup['id'] / 'archive.tar.gz'
        with archive.open('r+b') as stream:
            stream.seek(25)
            stream.write(b'corrupt')
        with self.assertRaises(Error):
            self.backups.restore_selection(backup['id'], ['data/hello.txt'], 'data', 'corrupt')
        self.assertFalse((self.host.share_root / 'data/corrupt').exists())

    def test_mount_loss_and_acl_failure_keep_restore_private(self):
        backup = self.backups.create(include_config=False)
        with patch.object(self.host.storage_locations, 'required_path', side_effect=Error('Volume fehlt', 503)):
            with self.assertRaises(Error):
                self.backups.restore_selection(backup['id'], ['data/hello.txt'], 'data', 'offline')
        self.assertFalse((self.host.share_root / 'data/offline').exists())
        with patch.object(self.host, 'share_acl_transaction', side_effect=Error('ACL failure')):
            with self.assertRaises(Error):
                self.backups.restore_selection(backup['id'], ['data/hello.txt'], 'data', 'private')
        self.assertEqual((self.host.share_root / 'data/private').stat().st_mode & 0o777, 0o700)

    def test_identity_and_two_factor_config_export_preserves_live_state_without_pending_or_codes(self):
        from titan.identity import empty_policy
        from titan.security import Security, totp
        import time
        policy = empty_policy()
        self.store.set_config('identity', policy)
        self.host.save('identity', {**policy, 'users': {'internal-linux-mapping': 'not-exported'}})
        self.host.save('identity-baseline', {'data': {'name': 'data', 'readers': [], 'writers': ['titan-files']}})
        self.host.save('identity-homes', {})
        self.host.save('identity-quotas', {})
        security = Security(self.store)
        enrollment = security.begin('admin', 'long-enough-password')
        enabled = security.confirm('admin', 'long-enough-password', totp(enrollment['secret'], int(time.time() // 30)))
        backup = self.backups.create()
        data = self.backups.read_config(backup['id'])
        self.assertEqual(data['identity']['policy'], policy)
        self.assertEqual(data['identity']['baseline']['data']['writers'], ['titan-files'])
        factor = data['security']['factors'][0]
        self.assertEqual(factor['secret'], enrollment['secret'])
        self.assertEqual(factor['enabled'], 1)
        self.assertNotIn('pending', factor)
        self.assertEqual(len(data['security']['recoveries']), len(enabled['recovery_codes']))
        self.assertFalse(any(code in json.dumps(data) for code in enabled['recovery_codes']))
        browsing = json.dumps(self.backups.browse(backup['id']))
        self.assertNotIn(enrollment['secret'], browsing)
        self.assertNotIn('config.json', browsing)

    def test_smtp_secret_is_not_in_config_json_export_or_file_listing(self):
        self.host.save('notification-settings', {'host': 'smtp.example.org'})
        self.host.save('notification-credentials', {'password': 'never-export-smtp-secret'})
        backup = self.backups.create()
        config = self.backups.read_config(backup['id'])
        self.assertNotIn('never-export-smtp-secret', json.dumps(config))
        self.assertNotIn('notification-credentials', json.dumps(self.backups.browse(backup['id'])))
        export = Path(self.backups.export_config(backup['id'])['path'])
        self.assertNotIn('never-export-smtp-secret', (export / 'config.json').read_text())

    def test_destination_link_is_rejected_without_outside_write(self):
        backup = self.backups.create(include_config=False)
        outside = self.root / 'outside'
        outside.mkdir()
        (self.host.share_root / 'data/linked').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(Error):
            self.backups.restore_selection(backup['id'], ['data/hello.txt'], 'data', 'linked')
        self.assertEqual(list(outside.iterdir()), [])


class StorageMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.host = SimpleNamespace(share_root=self.root, monitor=None)
        self.host.load = lambda key, default: json.loads((self.root / (key + '.json')).read_text()) if (self.root / (key + '.json')).exists() else default
        self.host.save = lambda key, value: atomic_json(self.root / (key + '.json'), value)
        self.storage = {'disks': [{'type': 'disk', 'name': '/dev/sda'}, {'type': 'part', 'name': '/dev/sda1'}],
                        'pools': [{'name': 'tank'}], 'datasets': [{'name': 'tank/data', 'mountpoint': str(self.data)}]}
        self.host.op_storage = lambda: self.storage
        self.rows = 'tank/data@manual\t10\t100\n'
        self.run = Mock(side_effect=lambda args, **kw: self.rows if args[:2] == ['zfs', 'list'] else '{}')
        self.manager = StorageMaintenance(self.host, self.run)

    def tearDown(self):
        self.tmp.cleanup()

    def test_actual_smart_test_only_recognized_whole_disk_and_safe_types(self):
        self.manager.smart_test('/dev/sda', 'long')
        self.run.assert_called_once_with(['smartctl', '-t', 'long', '-j', '/dev/sda'], timeout=30)
        for disk, mode in (('/etc/shadow', 'short'), ('/dev/sda1', 'short'), ('/dev/sda', 'conveyance'), ('--scan', 'short')):
            with self.subTest(disk=disk, mode=mode), self.assertRaises(Error):
                self.manager.smart_test(disk, mode)

    def test_snapshot_restore_creates_clone_and_original_remains(self):
        result = self.manager.restore_snapshot('tank/data@manual', 'restored')
        self.assertEqual(result['dataset'], 'tank/data/restored')
        commands = [call.args[0] for call in self.run.call_args_list]
        self.assertIn(['zfs', 'clone', '-o', 'mountpoint=' + str(self.data / 'restored'), 'tank/data@manual', 'tank/data/restored'], commands)
        self.assertFalse(any('-r' in args or 'rollback' in args for args in commands))
        for snapshot, name in (('tank/data@missing', 'valid'), ('tank/data@manual', '../bad')):
            with self.assertRaises(Error):
                self.manager.restore_snapshot(snapshot, name)
        (self.data / 'taken').mkdir()
        with self.assertRaises(Error):
            self.manager.restore_snapshot('tank/data@manual', 'taken')

    def test_snapshot_delete_explicit_yes_no_and_no_recursive_flags(self):
        with self.assertRaises(Error):
            self.manager.remove_snapshot('tank/data@manual')
        self.manager.remove_snapshot('tank/data@manual', True)
        self.assertEqual(self.run.call_args.args[0], ['zfs', 'destroy', 'tank/data@manual'])
        with self.assertRaises(Error):
            self.manager.remove_snapshot('tank/data@manual', 'yes')

    def test_snapshot_restore_outside_or_symlink_mountpoint_refused(self):
        self.storage['datasets'][0]['mountpoint'] = '/etc'
        with self.assertRaises(Error):
            self.manager.restore_snapshot('tank/data@manual', 'bad')
        link = self.root / 'link'
        link.symlink_to(self.data, target_is_directory=True)
        self.storage['datasets'][0]['mountpoint'] = str(link)
        with self.assertRaises(Error):
            self.manager.restore_snapshot('tank/data@manual', 'bad')
        self.assertFalse(any(call.args[0][:2] == ['zfs', 'clone'] for call in self.run.call_args_list))

    def test_settings_validation_and_daily_weekly_once_even_on_failure(self):
        job = self.manager.save_job(type='scrub', target='tank', interval='weekly', window_day=6, window_hour=3)
        sunday = datetime.datetime(2026, 10, 4, 3).timestamp()
        self.assertEqual(self.manager.scheduled(sunday - 3600)['runs'], [])
        self.assertTrue(self.manager.scheduled(sunday)['runs'][0]['ok'])
        self.assertEqual(self.manager.scheduled(sunday)['runs'], [])
        self.manager.save_job(**{**job, 'enabled': False})
        self.assertEqual(self.manager.scheduled(sunday + 7*86400)['runs'], [])
        self.manager.remove_job(job['id'])
        self.assertEqual(self.manager.settings()['jobs'], [])
        for value in ({'type': 'snapshot', 'target': 'unknown'}, {'type': 'smart', 'target': '/etc'},
                      {'type': [], 'target': 'tank'}, {'type': 'scrub', 'target': [], 'test': 'short'}):
            with self.assertRaises(Error):
                self.manager.save_job(**value)
        failed = self.manager.save_job(type='scrub', target='tank', interval='daily', window_hour=0)
        with patch.object(self.manager, '_execute', side_effect=Error('Missing disk')):
            self.assertFalse(self.manager.scheduled(sunday)['runs'][0]['ok'])
            self.assertEqual(self.manager.scheduled(sunday)['runs'], [])

    def test_retention_only_same_schedule_no_recursive_destroy(self):
        job = self.manager.save_job(type='snapshot', target='tank/data', interval='daily', retention=1)
        prefix = 'titan-auto-' + job['id'][2:] + '-'
        self.rows += 'tank/data@' + prefix + 'old\t0\t1\t' + job['id'] + '\n'
        self.rows += 'tank/data@' + prefix + 'manual\t0\t1\t-\n'
        self.rows += 'tank/data@titan-auto-other-old\t0\t1\n'
        def runner(args, **kw):
            if args[:2] == ['zfs', 'snapshot']:
                self.rows += args[-1] + '\t0\t10000\t' + job['id'] + '\n'
            return self.rows if args[:2] == ['zfs', 'list'] else '{}'
        self.run.side_effect = runner
        result = self.manager._execute(job, 10000)
        removed = [call.args[0] for call in self.run.call_args_list if call.args[0][:2] == ['zfs', 'destroy']]
        self.assertEqual(removed, [['zfs', 'destroy', 'tank/data@' + prefix + 'old']])
        self.assertNotIn('manual', result['removed'])

    def test_retention_dependency_reports_warning_without_forcing_deletion(self):
        self.host.monitor = Mock()
        job = self.manager.save_job(type='snapshot', target='tank/data', interval='daily', window_hour=0)
        with patch.object(self.manager, '_execute', return_value={'ok': True, 'retention_blocked': ['tank/data@old']}):
            result = self.manager.scheduled(datetime.datetime(2026, 10, 4, 3).timestamp())
        self.assertTrue(result['runs'][0]['ok'])
        self.host.monitor.report.assert_called_once()
        self.assertEqual(self.host.monitor.report.call_args.args[-1], 'warning')
        self.host.monitor.clear.assert_not_called()

    def test_ext4_xfs_has_no_snapshot_choices(self):
        self.storage['pools'], self.storage['datasets'] = [], []
        self.assertEqual(self.manager.snapshots(), [])
        with self.assertRaises(Error):
            self.manager.save_job(type='snapshot', target='tank/data')


class NotificationDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.host = SimpleNamespace()
        self.host.load = lambda key, default: json.loads((self.root / (key + '.json')).read_text()) if (self.root / (key + '.json')).exists() else default
        self.host.save = lambda key, value: atomic_json(self.root / (key + '.json'), value)
        self.manager = NotificationDelivery(self.host)
        self.manager.save_settings(enabled=True, host='smtp.example.org', sender='nas@example.org',
                                   recipients=['owner@example.org'], username='nas', password='private-secret')

    def tearDown(self):
        self.tmp.cleanup()

    def test_monitored_priority_escalation_reopens_acknowledged_warning_and_routes(self):
        monitor = Monitor(self.host, Mock())
        with patch.object(NotificationDelivery, 'deliver', return_value={}):
            monitor.report('pool:tank', 'Pool warning', 'Check pool', 'warning')
            original = monitor.get()['alerts'][0]
            monitor.acknowledge(original['id'])
            monitor.report('pool:tank', 'Pool warning', 'Still warning', 'warning')
            self.assertTrue(monitor.get()['alerts'][0]['acknowledged'])
            monitor.report('pool:tank', 'Pool failed', 'Critical error', 'critical')
            failure = monitor.get()['alerts'][0]
            self.assertFalse(failure['acknowledged'])
            self.assertEqual(failure['route'], 'storage')
            self.assertEqual(failure['episode'], 1)
            monitor.clear('pool:tank')
            resolved = monitor.get()['alerts'][0]
            self.assertFalse(resolved['active'])
            self.assertIn('resolved_at', resolved)
            monitor.report('pool:tank', 'Again', 'New failure', 'error')
            self.assertEqual(monitor.get()['alerts'][0]['episode'], 2)

    def test_secret_never_in_public_settings_blank_keeps_and_clear_removes(self):
        settings = self.manager.settings()
        self.assertNotIn('password', settings)
        self.assertTrue(settings['password_set'])
        self.assertEqual((self.root / 'notification-credentials.json').stat().st_mode & 0o777, 0o600)
        self.manager.save_settings(password='')
        self.assertEqual(self.host.load('notification-credentials', {})['password'], 'private-secret')
        self.manager.save_settings(clear_password=True)
        self.assertFalse(self.manager.settings()['password_set'])

    def test_validation_header_injection_plaintext_tls_and_unknown_options(self):
        for value in ({'sender': 'x@example.org\r\nBcc: bad@example.org'}, {'host': 'smtp://evil'}, {'tls': 'plain'},
                      {'port': 0}, {'sender': None}, {'recipients': [None]}, {'enabled': 'true'}, {'minimum_severity': []}, {'extra': 1}):
            with self.subTest(value=value), self.assertRaises(Error):
                self.manager.save_settings(**value)

    def test_failed_settings_write_rolls_back_credentials_and_multiple_managers_share_lock(self):
        second = NotificationDelivery(self.host)
        self.assertIs(second.lock, self.manager.lock)
        previous = self.manager.settings()
        save = self.host.save
        first = True
        def failing(key, value):
            nonlocal first
            if key == 'notification-settings' and first:
                first = False
                raise OSError('disk full')
            return save(key, value)
        with patch.object(self.host, 'save', side_effect=failing), self.assertRaises(Error):
            self.manager.save_settings(password='new-secret', host='other.example.org')
        self.assertEqual(self.manager.settings(), previous)
        self.assertEqual(self.host.load('notification-credentials', {})['password'], 'private-secret')

    def test_real_smtp_boundary_always_tls_and_secret_error_redacted(self):
        smtp = Mock()
        smtp.__enter__ = Mock(return_value=smtp)
        smtp.__exit__ = Mock(return_value=False)
        smtp.send_message.return_value = {}
        with patch('titan.notification_delivery.smtplib.SMTP', return_value=smtp):
            self.assertTrue(self.manager.test()['ok'])
        self.assertTrue(smtp.starttls.called)
        smtp.login.assert_called_once_with('nas', 'private-secret')
        self.manager.save_settings(tls='tls', port=465)
        with patch('titan.notification_delivery.smtplib.SMTP_SSL', side_effect=OSError('private-secret rejected')):
            with self.assertRaises(Error) as failure:
                self.manager.test()
        self.assertNotIn('private-secret', str(failure.exception))

    def test_alert_episodes_priorities_and_throttle_send_only_changes(self):
        alert = {'id': 'a', 'episode': 1, 'title': 'Disk failure', 'detail': 'Check /dev/sda', 'severity': 'warning', 'active': True, 'route': 'storage'}
        with patch.object(self.manager, '_send') as send, patch('titan.notification_delivery.time.time', return_value=1000):
            self.manager.deliver([alert])
            self.manager.deliver([alert])
            self.assertEqual(send.call_count, 1)
            alert['severity'] = 'error'
            self.manager.deliver([alert])
            self.assertEqual(send.call_count, 1, 'five-minute batch throttle')
        with patch.object(self.manager, '_send') as send, patch('titan.notification_delivery.time.time', return_value=1400):
            self.manager.deliver([alert])
            self.assertEqual(send.call_count, 1)
            alert['active'] = False
            self.manager.deliver([alert])
            self.assertEqual(send.call_count, 1)
        alert.update(active=True, episode=2)
        with patch.object(self.manager, '_send') as send, patch('titan.notification_delivery.time.time', return_value=1800):
            self.manager.deliver([alert])
            self.assertEqual(send.call_count, 1)

    def test_mail_failure_retries_later_and_disabled_does_not_send(self):
        alert = {'id': 'a', 'title': 'Failure', 'severity': 'error', 'active': True}
        with patch.object(self.manager, '_send', side_effect=Error('TLS failure')) as send, patch('titan.notification_delivery.time.time', return_value=1000):
            result = self.manager.deliver([alert])
            self.assertEqual(result['pending'], 1)
            self.manager.deliver([alert])
            self.assertEqual(send.call_count, 1)
        with patch.object(self.manager, '_send') as send, patch('titan.notification_delivery.time.time', return_value=1400):
            self.assertEqual(self.manager.deliver([alert])['pending'], 0)
            self.assertEqual(send.call_count, 1)
        self.manager.save_settings(enabled=False)
        with patch.object(self.manager, '_send') as send:
            self.manager.deliver([alert])
            send.assert_not_called()


class IOTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.proc, self.sys = self.root / 'proc', self.root / 'sys'
        (self.proc / 'net').mkdir(parents=True)
        (self.sys / 'class/block/sda1').mkdir(parents=True)
        (self.sys / 'class/block/sda1/partition').write_text('1')
        (self.proc / 'stat').write_text('cpu 1 0 1 8 0 0 0 0\ncpu0 1 0 1 8 0 0 0 0\n')
        (self.proc / 'meminfo').write_text('MemTotal: 100 kB\nMemAvailable: 50 kB\nMemFree: 20 kB\n')
        self.manager = Telemetry(self.proc, self.sys)
        self.counters(1000, 500, 20, 10)

    def tearDown(self):
        self.tmp.cleanup()

    def counters(self, receive, transmit, read, written):
        def nic(name, rx, tx):
            return name+': '+str(rx)+' 0 0 0 0 0 0 0 '+str(tx)+' 0 0 0 0 0 0 0\n'
        (self.proc / 'net/dev').write_text('header\n'+nic('eth0',receive,transmit)+nic('lo',100000,100000)+nic('veth-123',100000,100000))
        (self.proc / 'diskstats').write_text(f'8 0 sda 1 0 {read} 0 1 0 {written} 0 0 0 0\n8 1 sda1 1 0 1000000 0 1 0 1000000 0 0 0 0\n7 0 loop0 1 0 1000000 0 1 0 1000000 0 0 0 0\n')

    def test_kernel_counter_deltas_exclude_loopback_bridge_and_partitions(self):
        with patch('titan.telemetry.time.monotonic', return_value=0):
            first = self.manager.sample()
        self.assertIsNone(first['network_receive_bps'])
        self.assertIsNone(first['disk_read_bps'])
        self.counters(2000, 1000, 40, 30)
        with patch('titan.telemetry.time.monotonic', return_value=5):
            second = self.manager.sample()
        self.assertEqual(second['network_receive_bps'], 200)
        self.assertEqual(second['network_transmit_bps'], 100)
        self.assertEqual(second['disk_read_bps'], 20*512/5)
        self.assertEqual(second['disk_write_bps'], 20*512/5)
        self.assertEqual([item['name'] for item in second['disk_devices']], ['sda'])
        self.assertEqual(second['status_history'][-1]['network_receive_bps'], 200)

    def test_resets_and_unreadable_counters_never_fabricate_zero(self):
        with patch('titan.telemetry.time.monotonic', return_value=0):
            self.manager.sample()
        self.counters(1, 1, 1, 1)
        with patch('titan.telemetry.time.monotonic', return_value=5):
            reset = self.manager.sample()
        self.assertIsNone(reset['network_receive_bps'])
        self.assertIsNone(reset['disk_read_bps'])
        (self.proc / 'net/dev').unlink()
        with patch('titan.telemetry.time.monotonic', return_value=10):
            missing = self.manager.sample()
        self.assertIn('network', missing['telemetry_errors'])
        self.assertEqual(missing['network_interfaces'], [])


if __name__ == '__main__':
    unittest.main()

import copy
import datetime
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from titan.backups import Backups, digest_file
from titan.backup_authorization import allowed_manifest, safe_settings, authorize
from titan.catalog import APPS, compose
from titan.core import Error, atomic_json, job_resources
from titan.app_management import AppMixin
from tests.test_backups import FakeHost


APP = 'backup-test-app'
RECIPE = {'name': 'Test database', 'image': 'example.test/db:1', 'port': 8080, 'mount': '/data',
          'memory': '512m', 'install_schema': [{'key': 'password', 'type': 'password', 'label': 'Password',
          'min_length': 4, 'max_length': 128, 'required': True, 'env': 'DB_PASSWORD'}]}


class AppBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.host = FakeHost(self.root)
        self.target = self.root / 'external'
        self.target.mkdir()
        self.control = self.host.directory / 'apps' / APP
        self.control.mkdir(parents=True)
        self.config = self.host.share_root / 'app-config'
        self.data = self.host.share_root / 'app-data'
        self.config.mkdir(mode=0o750)
        self.data.mkdir(mode=0o770)
        (self.config / 'database').mkdir(mode=0o700)
        (self.config / 'database' / 'data.db').write_bytes(b'consistent database')
        (self.config / 'database' / 'data.db').chmod(0o600)
        (self.config / 'credential.txt').write_text('saved-credential')
        (self.config / 'credential.txt').chmod(0o640)
        (self.data / 'document.txt').write_text('original user data')
        self.registry = patch.dict(APPS, {APP: copy.deepcopy(RECIPE)})
        self.registry.start()
        self.owner = patch('titan.host.pwd.getpwnam', return_value=SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid()))
        self.owner.start()
        self.record = {'id': APP, 'name': 'Test database', 'data': str(self.data), 'port': 8088,
                       'config_path': str(self.config), 'network': None}
        self.host.save('apps', [self.record])
        atomic_json(self.control / 'options.json', {'password': 'secret-before'})
        atomic_json(self.control / 'compose.json', self.definition())
        self.members = {APP: {'Id': 'a' * 64, 'Image': 'sha256:' + '1' * 64, 'State': {'Status': 'running'}}}
        self.original_member = copy.deepcopy(self.members[APP])
        self.local_image = self.original_member['Image']
        self.host.managed_app = lambda app: copy.deepcopy(self.host.load('apps', [])[0])
        self.host.app_storage_ready = Mock()
        self.host._app_config_path = lambda app, record: self.config
        self.host._app_options = lambda app: json.loads((self.control / 'options.json').read_text())
        self.host._app_container_rows = lambda: list(self.members.values())
        self.host._app_container = lambda app, record, rows, options, service_key: self.members.get(service_key)
        self.host._app_patch_record = Mock(side_effect=self.patch_record)
        self.host._app_stop_or_remove = Mock(side_effect=lambda *args, **kwargs: self.members.clear())
        self.host.docker = Mock(side_effect=self.docker)
        self.run = Mock(side_effect=self.command)
        self.backups = Backups(self.host, self.run, self.root / 'no-web-db')
        info = self.target.stat()
        self.backups._target_identity = info.st_dev, info.st_ino
        self.target_patch = patch.object(self.backups, 'validate_target', return_value=self.target)
        self.target_patch.start()
        self.backups.save_settings({'target': str(self.target), 'shares': [], 'include_config': False,
                                    'apps': [APP], 'app_data': []})

    def tearDown(self):
        self.target_patch.stop()
        self.owner.stop()
        self.registry.stop()
        self.temporary.cleanup()

    def definition(self):
        options = json.loads((self.control / 'options.json').read_text())
        return compose(APP, str(self.control), os.getuid(), os.getgid(), 8088, str(self.data), options, config_path=str(self.config))

    def patch_record(self, app, updates):
        records = self.host.load('apps', [])
        records[0].update(updates)
        self.host.save('apps', records)

    def docker(self, app, command, *args):
        if command == 'stop':
            for member in self.members.values():
                member['State'] = {'Status': 'exited'}
        if command == 'create':
            self.members[APP] = {**copy.deepcopy(self.original_member), 'State': {'Status': 'created'}}
        return ''

    def command(self, args, **kwargs):
        if args[:4] == ['docker', 'inspect', '--type', 'image']:
            return json.dumps([{'Id': self.local_image} for ref in args[4:]])
        if args[:2] == ['docker', 'start']:
            for member in self.members.values():
                if member['Id'] in args[2:]:
                    member['State'] = {'Status': 'running'}
        return ''

    def stop(self):
        for member in self.members.values():
            member['State'] = {'Status': 'exited'}

    def restore(self, backup, **kwargs):
        return self.backups.apps.restore(backup['id'], APP, backup['id'], **kwargs)

    def rewrite(self, backup, extra=None, drop=None):
        archive = self.backups.namespace() / backup['id'] / 'archive.tar.gz'
        contents = []
        with tarfile.open(archive, 'r:gz') as source:
            for member in source:
                if drop and member.name == drop:
                    continue
                contents.append((member, source.extractfile(member).read() if member.isfile() else None))
        if extra:
            contents.append(extra)
        with tarfile.open(archive, 'w:gz') as target:
            for member, data in contents:
                target.addfile(member, io.BytesIO(data) if data is not None else None)
        manifest = self.backups.namespace() / backup['id'] / 'manifest.json'
        value = json.loads(manifest.read_text())
        value.update(entries=len(contents), unpacked_bytes=sum(member.size for member, _ in contents),
                     bytes=archive.stat().st_size, sha256=digest_file(archive))
        atomic_json(manifest, value)

    def test_cold_snapshot_roundtrip_preserves_credentials_modes_and_previous_data(self):
        self.backups.save_settings({'app_data': [APP]})
        backup = self.backups.create()
        self.assertEqual(backup['type'], 'bundle')
        self.assertEqual(backup['apps'], [APP])
        self.assertEqual(self.members[APP]['State']['Status'], 'running')
        self.host.docker.assert_called_once_with(APP, 'stop')
        self.run.assert_any_call(['docker', 'start', 'a' * 64], timeout=180)
        self.assertNotIn('secret-before', json.dumps(backup))
        with tarfile.open(self.backups.namespace() / backup['id'] / 'archive.tar.gz') as archive:
            self.assertEqual(archive.getmember('apps/' + APP + '/config/database/data.db').mode, 0o600)
        (self.config / 'database' / 'data.db').write_bytes(b'new database')
        (self.data / 'document.txt').write_text('new user data')
        atomic_json(self.control / 'options.json', {'password': 'different-secret'})
        atomic_json(self.control / 'compose.json', self.definition())
        self.stop()
        result = self.restore(backup, include_data=True)
        self.assertTrue(result['kept_stopped'])
        self.assertEqual(self.members[APP]['State']['Status'], 'created')
        self.assertEqual((self.config / 'database' / 'data.db').read_bytes(), b'consistent database')
        self.assertEqual((self.config / 'database' / 'data.db').stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.config / 'database').stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o750)
        self.assertEqual((self.config / 'credential.txt').stat().st_uid, os.getuid())
        self.assertEqual((self.data / 'document.txt').read_text(), 'original user data')
        self.assertEqual(json.loads((self.control / 'options.json').read_text())['password'], 'secret-before')
        recovery = Path(result['recovery'])
        self.assertEqual((recovery / 'options.json').stat().st_mode & 0o777, 0o600)
        previous = json.loads((recovery / 'recovery.json').read_text())['paths']
        self.assertEqual((Path(previous[0]['previous']) / 'database' / 'data.db').read_bytes(), b'new database')
        self.assertEqual((Path(previous[1]['previous']) / 'document.txt').read_text(), 'new user data')
        self.assertFalse((self.control / 'restore-pending.json').exists())

    def test_partial_package_backup_only_restarts_previously_running_members(self):
        definition = json.loads((self.control / 'compose.json').read_text())
        definition['services']['db'] = copy.deepcopy(definition['services'][APP])
        atomic_json(self.control / 'compose.json', definition)
        self.members['db'] = {'Id': 'b' * 64, 'Image': 'sha256:' + '2' * 64, 'State': {'Status': 'exited'}}
        self.backups.create()
        self.run.assert_called_once_with(['docker', 'start', 'a' * 64], timeout=180)
        self.assertEqual(self.members['db']['State']['Status'], 'exited')

    def test_paused_package_blocks_backup_before_any_stop(self):
        self.members[APP]['State'] = {'Status': 'paused'}
        with self.assertRaisesRegex(Error, 'Pausierte'):
            self.backups.create()
        self.host.docker.assert_not_called()
        self.assertEqual(self.backups.list(), [])

    def test_no_implicit_user_data_or_secret_browsing_and_no_implicit_apps_for_delegates(self):
        backup = self.backups.create()
        self.assertEqual(backup['app_data'], [])
        self.assertEqual(self.backups.browse(backup['id'])['items'], [])
        (self.data / 'document.txt').write_text('keep these new files')
        self.stop()
        self.restore(backup)
        self.assertEqual((self.data / 'document.txt').read_text(), 'keep these new files')
        self.assertFalse(allowed_manifest(backup, {'data'}))
        settings = safe_settings(self.backups.settings(), set())
        self.assertEqual(settings['apps'], [])
        with self.assertRaises(Error):
            authorize('backup_create', {'shares': ['data'], 'include_config': False, 'apps': [APP]}, 'reader', [])
        shares = self.backups.create(shares=['data'], include_config=False)
        self.assertEqual(shares['type'], 'shares')
        self.assertNotIn('apps', shares)

    def test_restore_requires_stopped_app_confirmation_and_same_image(self):
        backup = self.backups.create()
        for confirmation, data in (('wrong', False), (backup['id'], 'yes')):
            with self.assertRaises(Error):
                self.backups.apps.restore(backup['id'], APP, confirmation, data)
        with self.assertRaisesRegex(Error, 'stoppen'):
            self.restore(backup)
        self.stop()
        self.members[APP]['Image'] = 'sha256:' + '2' * 64
        with self.assertRaisesRegex(Error, 'Versionswechsel'):
            self.restore(backup)
        self.assertEqual(list(self.host.directory.glob('app-restore-recovery-*')), [])
        self.assertEqual((self.config / 'database' / 'data.db').read_bytes(), b'consistent database')
        self.assertIsNone(job_resources('backup_app_restore', {'app': APP}))

    def test_local_mutable_image_tag_drift_is_rejected_before_switch(self):
        backup = self.backups.create()
        self.stop()
        self.local_image = 'sha256:' + '2' * 64
        with self.assertRaisesRegex(Error, 'Versionswechsel'):
            self.restore(backup)
        self.host._app_stop_or_remove.assert_not_called()
        self.assertEqual(list(self.host.directory.glob('app-restore-recovery-*')), [])

    def test_recreated_image_mismatch_rolls_back_with_marker_present_throughout(self):
        backup = self.backups.create()
        (self.config / 'database' / 'data.db').write_bytes(b'current database')
        self.stop()
        creates = 0
        def recreate(app, command, *args):
            nonlocal creates
            if command == 'create':
                self.assertTrue((self.control / 'restore-pending.json').exists())
                self.assertEqual(args, ('--force-recreate', '--pull', 'never'))
                creates += 1
            result = self.docker(app, command, *args)
            if command == 'create' and creates == 1:
                self.members[APP]['Image'] = 'sha256:' + '2' * 64
            return result
        self.host.docker.side_effect = recreate
        with self.assertRaisesRegex(Error, 'Vorheriger Stand wieder eingesetzt'):
            self.restore(backup)
        self.assertEqual((self.config / 'database' / 'data.db').read_bytes(), b'current database')
        self.assertEqual(self.members[APP]['Image'], self.original_member['Image'])
        self.assertFalse((self.control / 'restore-pending.json').exists())

    def test_control_disk_write_failure_does_not_skip_filesystem_rollback(self):
        backup = self.backups.create()
        (self.config / 'database' / 'data.db').write_bytes(b'current database')
        self.stop()
        def no_space(path, value):
            if Path(path) == self.control / 'options.json':
                raise OSError('no space left')
            return atomic_json(path, value)
        with patch('titan.app_backups.atomic_json', side_effect=no_space), self.assertRaisesRegex(Error, 'Rücksetzung unvollständig'):
            self.restore(backup)
        self.assertEqual((self.config / 'database' / 'data.db').read_bytes(), b'current database')
        self.assertTrue((self.control / 'restore-pending.json').exists())
        with self.assertRaisesRegex(Error, 'unterbrochen'):
            AppMixin.managed_app(self.host, APP)

    def test_corrupt_and_malicious_archives_never_change_live_data(self):
        for attack in ('symlink', 'hardlink', 'traversal', 'suid', 'missing-config'):
            with self.subTest(attack=attack):
                backup = self.backups.create()
                member = tarfile.TarInfo('apps/' + APP + '/config/injected')
                data = None
                if attack == 'symlink':
                    member.type, member.linkname = tarfile.SYMTYPE, '/etc/passwd'
                elif attack == 'hardlink':
                    member.type, member.linkname = tarfile.LNKTYPE, 'apps/' + APP + '/app.json'
                elif attack == 'traversal':
                    member.name = '../escape'
                elif attack == 'suid':
                    member.mode, member.size, data = 0o4755, 1, b'x'
                self.rewrite(backup, extra=None if attack == 'missing-config' else (member, data),
                             drop='apps/' + APP + '/config' if attack == 'missing-config' else None)
                self.stop()
                with self.assertRaises(Error):
                    self.restore(backup)
                self.assertFalse((self.config / 'injected').exists())
                self.assertEqual((self.config / 'database' / 'data.db').read_bytes(), b'consistent database')
        self.assertEqual(list(self.host.directory.glob('app-restore-recovery-*')), [])

    def test_failed_recreate_returns_old_data_and_credentials_without_starting(self):
        backup = self.backups.create()
        (self.config / 'database' / 'data.db').write_bytes(b'current database')
        self.stop()
        calls = 0
        def fail_once(app, command, *args):
            nonlocal calls
            if command == 'create':
                calls += 1
                if calls == 1:
                    raise Error('create failed')
            return self.docker(app, command, *args)
        self.host.docker.side_effect = fail_once
        with self.assertRaisesRegex(Error, 'Vorheriger Stand wieder eingesetzt'):
            self.restore(backup)
        self.assertEqual((self.config / 'database' / 'data.db').read_bytes(), b'current database')
        self.assertEqual(self.members[APP]['State']['Status'], 'created')
        self.assertFalse((self.control / 'restore-pending.json').exists())
        self.assertEqual(len(list(self.host.directory.glob('app-restore-recovery-*'))), 1)

    def test_interrupted_restore_marker_blocks_managed_start(self):
        (self.control / 'restore-pending.json').write_text('{}')
        with self.assertRaisesRegex(Error, 'unterbrochen'):
            AppMixin.managed_app(self.host, APP)
        errors = []
        def other_request():
            try:
                AppMixin.managed_app(self.host, APP)
            except Error as error:
                errors.append(str(error))
        with self.backups.apps.trusted_restore(APP):
            thread = threading.Thread(target=other_request)
            thread.start()
            thread.join()
        self.assertEqual(len(errors), 1)
        self.assertIn('unterbrochen', errors[0])

    def test_schedule_uses_selected_apps_and_rejects_invalid_selection(self):
        for value in ({'apps': [], 'app_data': [APP]}, {'apps': ['missing']}, {'apps': [APP, APP]}, {'apps': 'all'}):
            with self.subTest(value=value), self.assertRaises(Error):
                self.backups.save_settings(value)
        self.backups.save_settings({'auto_backup': True, 'window_hour': 0})
        now = datetime.datetime(2026, 10, 7, 3, 0).timestamp()
        result = self.backups.scheduled(now)
        self.assertTrue(result['due'])
        self.assertEqual(result['backup']['apps'], [APP])
        self.assertFalse(self.backups.scheduled(now)['due'])

    def test_backup_failure_restarts_only_previously_running_services_and_keeps_no_archive(self):
        (self.config / 'link').symlink_to('/etc/passwd')
        with self.assertRaises(Error):
            self.backups.create()
        self.assertEqual(self.members[APP]['State']['Status'], 'running')
        self.assertEqual(self.backups.list(), [])
        self.run.assert_any_call(['docker', 'start', 'a' * 64], timeout=180)


if __name__ == '__main__':
    unittest.main()

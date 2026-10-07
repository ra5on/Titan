"""Root authorization and isolated filesystem checks; never launch host root."""
import base64
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from titan.core import Error, Store
from titan.agent import Handler as AgentHandler
from titan.root_access import RootAccessApplicationMixin, RootAccessHTTPMixin, demo_root_file
from titan.security import totp
from titan.system_files import SystemFilesMixin, operate_system
from titan.terminal import TerminalManager
from titan.terminal_host import TerminalMixin
from titan.terminal_http import TerminalApplicationMixin, TerminalHTTPMixin, terminal_owner


PASSWORD = 'test-root-password-12345'
ID = 'a' * 64


class Application(RootAccessApplicationMixin, TerminalApplicationMixin):
    pass


class RootAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application()
        self.app.store = Store(self.temp.name)
        self.app.store.create_user('admin', PASSWORD, 'admin', 'titan-files')
        self.token, _ = self.app.store.login('admin', PASSWORD)
        self.user = self.app.store.session(self.token)
        self.app.demo = False
        self.app.agent = Mock()
        self.app.agent.call.return_value = {'ok': True}
        self.app.stop = threading.Event()
        self.app.initialize_terminals()
        self.app.initialize_root_access()
        self.app._start_terminal_reaper = Mock()

    def tearDown(self):
        self.app.close_all_terminals()
        self.temp.cleanup()

    def enable(self, **body):
        return self.app.enable_root_access(self.user, {'password': PASSWORD, **body}, '192.0.2.1')

    def test_requires_active_admin_and_fresh_password(self):
        self.assertFalse(self.app.root_access_status(self.user)['enabled'])
        with self.assertRaises(Error):
            self.enable(password='incorrect')
        self.assertFalse(self.app.root_access_active(self.user))
        self.assertTrue(self.enable()['enabled'])
        with self.assertRaises(Error):
            self.app.enable_root_access({**self.user, 'role': 'user'}, {'password': PASSWORD})

    def test_bound_to_exact_login_not_other_login_of_same_admin(self):
        self.enable()
        second, _ = self.app.store.login('admin', PASSWORD)
        self.assertFalse(self.app.root_access_active(self.app.store.session(second)))
        self.assertTrue(self.app.root_access_active(self.user))

    def test_password_failures_use_persistent_login_throttling(self):
        for _ in range(5):
            with self.assertRaises(Error):
                self.enable(password='incorrect')
        with self.assertRaises(Error) as denied:
            self.enable()
        self.assertEqual(denied.exception.status, 429)
        self.assertFalse(self.app.root_access_active(self.user))

    def test_enabled_factor_required_and_code_cannot_be_replayed(self):
        secret = 'JBSWY3DPEHPK3PXP'
        with self.app.store.connection() as db:
            db.execute('INSERT INTO second_factors(username,secret,enabled) VALUES (?,?,1)', ('admin', secret))
        self.assertTrue(self.app.root_access_status(self.user)['two_factor_required'])
        with self.assertRaises(Error):
            self.enable()
        code = totp(secret, int(time.time() // 30))
        self.assertTrue(self.enable(otp=code)['enabled'])
        self.app.disable_root_access(self.user)
        with self.assertRaises(Error):
            self.enable(otp=code)

    def test_duration_bounds_and_credentials_never_in_audit(self):
        for value in (True, 0, 31, '15', 1.5):
            with self.subTest(value=value), self.assertRaises(Error):
                self.enable(minutes=value)
        result = self.enable(minutes=5)
        self.assertLessEqual(result['remaining_seconds'], 300)
        with self.app.store.connection() as db:
            audit = json.dumps([dict(row) for row in db.execute('SELECT * FROM audit')])
        self.assertNotIn(PASSWORD, audit)
        self.assertNotIn(self.user['csrf'], audit)
        self.assertIn('root_access_enabled', audit)

    def test_disabling_closes_root_pty_and_keeps_data_terminal(self):
        self.enable()
        self.app.track_terminal(self.user, ID, root_mode=True)
        self.app.track_terminal(self.user, 'b' * 64)
        self.app.disable_root_access(self.user)
        self.app.agent.call.assert_called_with('root_terminal_close', owner=terminal_owner(self.user), id=ID)
        self.assertIn((terminal_owner(self.user), 'b' * 64), self.app.terminal_sessions)
        self.assertFalse(self.app.root_access_active(self.user))

    def test_expiry_and_revocation_close_root_processes(self):
        self.enable()
        self.app.track_terminal(self.user, ID, root_mode=True)
        self.app.root_access_grants[terminal_owner(self.user)]['deadline'] = time.monotonic() - 1
        self.app.reap_root_access()
        self.assertFalse(self.app.root_access_active(self.user))
        self.assertFalse(self.app.terminal_sessions)
        self.enable()
        self.app.track_terminal(self.user, ID, root_mode=True)
        self.app.store.logout(self.token)
        self.app.reap_terminals()
        self.assertFalse(self.app.terminal_sessions)
        self.assertFalse(self.app.root_access_grants)

    def test_grant_does_not_survive_application_restart(self):
        self.enable()
        self.app.initialize_root_access()
        self.assertFalse(self.app.root_access_active(self.user))

    def test_separate_root_route_requires_grant_and_uses_trusted_rpc(self):
        class Handler(RootAccessHTTPMixin, TerminalHTTPMixin):
            pass
        handler = Handler()
        handler.app = self.app
        handler.require_user = Mock(return_value=self.user)
        handler.reply = Mock()
        with self.assertRaises(Error):
            handler.root_access_post('/api/root-terminal', self.user, {'action': 'create'})
        self.app.agent.call.assert_not_called()
        self.enable()
        self.app.agent.call.return_value = {'id': ID}
        handler.root_access_post('/api/root-terminal', self.user, {'action': 'create'})
        self.app.agent.call.assert_called_with('root_terminal_create', owner=terminal_owner(self.user), cols=100, rows=30, deadline=self.app.root_access_grants[terminal_owner(self.user)]['deadline'])
        with self.assertRaises(Error):
            handler.root_access_post('/api/root-terminal', self.user, {'action': 'create', 'user': 'root'})

    def test_default_terminal_cannot_be_promoted_by_constructor_accident(self):
        root = SimpleNamespace(pw_uid=0, pw_gid=0, pw_name='root')
        with patch('titan.terminal.pwd.getpwnam', return_value=root):
            with self.assertRaises(ValueError):
                TerminalManager(user='root')
            with patch('titan.terminal.os.geteuid', return_value=1000), self.assertRaises(ValueError):
                TerminalManager(user='root', allow_root=True)
        with patch('titan.terminal.os.geteuid', return_value=0), self.assertRaises(ValueError):
            TerminalManager()

    def test_disabled_account_role_change_and_session_expiry_revoke_root(self):
        # Each state change is validated against the live database, rather
        # than trusting the role/user object captured when the grant opened.
        for mutation in ('disabled', 'demoted', 'expired'):
            with self.subTest(mutation=mutation):
                with self.app.store.connection() as db:
                    db.execute("UPDATE users SET enabled=1,role='admin' WHERE name='admin'")
                    db.execute('UPDATE sessions SET expires=?', (time.time() + 3600,))
                self.enable()
                self.app.track_terminal(self.user, ID, root_mode=True)
                with self.app.store.connection() as db:
                    if mutation == 'disabled':
                        db.execute("UPDATE users SET enabled=0 WHERE name='admin'")
                    elif mutation == 'demoted':
                        db.execute("UPDATE users SET role='user' WHERE name='admin'")
                    else:
                        db.execute('UPDATE sessions SET expires=?', (time.time() - 1,))
                with self.assertRaises(Error):
                    self.app.require_root_access(self.user)
                self.assertFalse(self.app.terminal_sessions)
                self.assertFalse(self.app.root_access_grants)

    def test_local_data_identity_cannot_reach_root_agent_operations(self):
        # A compromised data shell cannot bypass web reauthentication by
        # calling the agent socket. No socket or actual worker is started.
        for uid, allowed in ((0, True), (992, True), (993, False), (1000, False)):
            for operation in ('root_terminal_create', 'root_system_file'):
                with self.subTest(uid=uid, operation=operation):
                    handler = object.__new__(AgentHandler)
                    handler.request = Mock()
                    handler.request.getsockopt.return_value = struct.pack('3i', 123, uid, 500)
                    handler.server = SimpleNamespace(host=Mock())
                    handler.server.host.dispatch.return_value = {'ok': True}
                    with patch('titan.agent.pwd.getpwnam', return_value=SimpleNamespace(pw_uid=992)), \
                            patch('titan.agent.receive', return_value={'operation': operation, 'arguments': {}}), \
                            patch('titan.agent.send') as send, patch('titan.agent.logging.error'):
                        handler.handle()
                    if allowed:
                        handler.server.host.dispatch.assert_called_once_with(operation)
                        self.assertEqual(send.call_args.args[1], {'result': {'ok': True}})
                    else:
                        handler.server.host.dispatch.assert_not_called()
                        self.assertEqual(send.call_args.args[1]['status'], 403)

    def test_agent_expires_root_lease_even_when_web_reaper_is_unavailable(self):
        # Pure manager state: no process, credentials, PTY or background thread.
        manager = object.__new__(TerminalManager)
        manager.root_mode = True
        manager.idle_ttl, manager.max_ttl = 900, 1800
        manager._lock = threading.RLock()
        manager._terminate = Mock()
        now = time.monotonic()
        session = SimpleNamespace(id=ID, created=now, activity=now,
            deadline=now+5, retiring=False, lock=threading.RLock())
        manager._sessions = {ID: session}
        with patch('titan.terminal.time.monotonic', return_value=now+4):
            manager._sweep()
            manager._terminate.assert_not_called()
        with patch('titan.terminal.time.monotonic', return_value=now+6):
            manager._sweep()
        manager._terminate.assert_called_once_with(session)
        self.assertFalse(manager._sessions)
        with patch('titan.terminal.os.openpty') as pty:
            for deadline in (None, True, float('nan'), float('inf'), now-1, now+2000):
                with self.subTest(deadline=deadline), self.assertRaises(Error):
                    manager.create('admin', deadline=deadline)
            pty.assert_not_called()
        manager.root_mode = False
        with self.assertRaises(Error):
            manager.create('data-user', deadline=now+30)

    def test_root_host_requires_and_forwards_fixed_agent_lease(self):
        host = TerminalMixin()
        host.terminal_lock = threading.Lock()
        fake = Mock()
        with patch('titan.terminal_host.TerminalManager', return_value=fake) as constructor:
            with self.assertRaises(TypeError):
                host.op_root_terminal_create('admin')
            constructor.assert_not_called()
            host.op_root_terminal_create('admin', deadline=123.5, cols=80, rows=24)
            constructor.assert_called_once_with(cwd='/', user='root', allow_root=True, max_ttl=1800, sweep_interval=1)
            fake.create.assert_called_once_with('admin', 80, 24, deadline=123.5)


class RootFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ('etc', 'usr/bin', 'var/srv/titan', 'proc', 'sys', 'dev', 'home/admin'):
            (self.root / name).mkdir(parents=True)
        (self.root / 'etc/hostname').write_text('old-hostname')
        (self.root / 'usr/bin/tool').write_text('immutable')

    def tearDown(self):
        self.temp.cleanup()

    def call(self, action, path='', **args):
        return operate_system(str(self.root), action, path, system_path_root=str(self.root), root_access=True, **args)

    def test_root_can_read_and_edit_ordinary_system_files_in_fixture(self):
        with self.assertRaises(Error):
            operate_system(str(self.root), 'read', 'etc/hostname', system_path_root=str(self.root), allowed_roots=['var/srv/titan'])
        old = self.call('read', 'etc/hostname')
        self.call('write', 'etc/hostname', data=base64.b64encode(b'titan-new').decode(), revision=old['revision'])
        self.assertEqual((self.root / 'etc/hostname').read_text(), 'titan-new')
        self.assertIn('etc', [entry['name'] for entry in self.call('list')['entries']])

    def test_root_still_cannot_write_virtual_paths_or_escape_fixture(self):
        for path in ('proc/file', 'sys/file', 'dev/file', '../escape'):
            with self.subTest(path=path), self.assertRaises(Error):
                self.call('create', path, data='dGVzdA==')
        with self.assertRaises(Error):
            self.call('delete', 'etc', confirmation_path='/etc')
        (self.root / 'proc/kernel-value').write_text('virtual fixture')
        with self.assertRaises(Error):
            self.call('copy', 'proc/kernel-value', destination='etc/copied', destination_system=True)

    def test_root_respects_readonly_mount_without_remounting(self):
        with patch('titan.system_files.os.statvfs', return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
            old = self.call('read', 'usr/bin/tool')
            with self.assertRaises(Error):
                self.call('write', 'usr/bin/tool', data='dGVzdA==', revision=old['revision'])
            self.assertFalse(self.call('list', 'usr/bin')['writable'])
        self.assertEqual((self.root / 'usr/bin/tool').read_text(), 'immutable')

    def test_root_upload_rename_copy_move_are_validated_on_both_ends(self):
        self.call('upload', 'etc/upload.bin', offset=0, data=base64.b64encode(b'first').decode())
        self.call('upload', 'etc/upload.bin', offset=5, data=base64.b64encode(b'-second').decode())
        self.call('rename', 'etc/upload.bin', destination='etc/renamed.bin')
        self.call('copy', 'etc/renamed.bin', destination='home/admin/copied.bin', destination_system=True)
        self.call('move', 'etc/renamed.bin', destination='home/admin/moved.bin', destination_system=True)
        self.assertEqual((self.root / 'home/admin/copied.bin').read_bytes(), b'first-second')
        self.assertEqual((self.root / 'home/admin/moved.bin').read_bytes(), b'first-second')
        self.assertFalse((self.root / 'etc/renamed.bin').exists())
        for action in ('rename', 'copy', 'move'):
            for destination in ('../escaped', 'proc/virtual', 'sys/virtual', 'dev/virtual'):
                with self.subTest(action=action, destination=destination), self.assertRaises(Error):
                    self.call(action, 'home/admin/copied.bin', destination=destination, destination_system=True)
        self.assertEqual((self.root / 'home/admin/copied.bin').read_bytes(), b'first-second')

    def test_root_symlink_escape_and_readonly_destination_are_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            destination = Path(outside) / 'untouched'
            destination.write_bytes(b'preserved')
            (self.root / 'etc/external').symlink_to(outside, target_is_directory=True)
            for action in ('read', 'upload', 'mkdir', 'delete'):
                with self.subTest(action=action), self.assertRaises(Error):
                    self.call(action, 'etc/external/untouched', offset=0, data='eA==')
            for action in ('copy', 'move', 'rename'):
                with self.subTest(action=action), self.assertRaises(Error):
                    self.call(action, 'etc/hostname', destination='etc/external/new', destination_system=True)
            self.assertEqual(destination.read_bytes(), b'preserved')
            self.assertFalse((Path(outside) / 'new').exists())
        original = (self.root / 'etc/hostname').read_bytes()
        with patch('titan.system_files.writable_path', side_effect=lambda root, path, parent_only=False: not path.startswith('usr')):
            for action in ('copy', 'move', 'rename'):
                with self.subTest(action=action), self.assertRaises(Error):
                    self.call(action, 'etc/hostname', destination='usr/bin/replaced', destination_system=True)
        self.assertEqual((self.root / 'etc/hostname').read_bytes(), original)
        self.assertFalse((self.root / 'usr/bin/replaced').exists())

    def test_root_worker_does_not_follow_ancestor_swapped_after_validation(self):
        host = SystemFilesMixin()
        host.system_root = self.root
        host.storage_locations = SimpleNamespace(protected_paths=lambda: [])
        with tempfile.TemporaryDirectory() as outside:
            secret = Path(outside) / 'hostname'
            secret.write_text('external-secret')
            def worker(_command, **kwargs):
                request = json.loads(kwargs['input'])
                (self.root / 'etc').rename(self.root / 'original-etc')
                (self.root / 'etc').symlink_to(outside, target_is_directory=True)
                request.pop('system')
                try:
                    result = operate_system(**request)
                except Exception as error:
                    return SimpleNamespace(stdout=json.dumps({'error': str(error), 'status': getattr(error, 'status', 400)}))
                self.fail('Ancestor swap unexpectedly returned file content: ' + str(result))
            with patch('titan.system_files.subprocess.run', side_effect=worker), self.assertRaises(Error):
                host.op_root_system_file('read', 'etc/hostname')
            self.assertEqual(secret.read_text(), 'external-secret')

    def test_root_rpc_rejects_caller_controlled_worker_flags(self):
        host = SystemFilesMixin()
        host.system_root = self.root
        for key in ('root_access', 'canonicalized', 'root', 'allowed_roots', 'system_path_root', 'user'):
            with self.subTest(key=key), self.assertRaises(Error), patch('titan.system_files.subprocess.run') as worker:
                host.op_root_system_file('read', 'etc/hostname', **{key: '/'})
                worker.assert_not_called()

    def test_demo_root_targets_generated_tree_only(self):
        demo = SimpleNamespace(_system_path=self.root, _share_paths={})
        result = demo_root_file(demo, 'read', 'etc/hostname')
        self.assertEqual(base64.b64decode(result['data']), b'old-hostname')
        with self.assertRaises(Error):
            demo_root_file(demo, 'read', '../../etc/shadow')

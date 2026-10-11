"""Optional host plugins: credentials, transaction recovery and fixed sources."""
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from titan.core import Error
from titan.remote_access import RemoteAccessMixin, validate_remote
from titan.system_plugins import SystemPluginsMixin, UNIT, offer, latest_offer, download, read_owned


def credential():
    return base64.b64encode(json.dumps({'a': 'a' * 32, 't': '2c9069cd-5cf1-470f-9ddd-df156d3f2c57',
        's': base64.b64encode(b'only-a-disposable-test-secret-12345').decode()}).encode()).decode()


class Web:
    def __init__(self):
        self.value = {'revision': 'initial', 'remote': validate_remote(None)}

    def config(self):
        return copy.deepcopy(self.value)

    def save_remote(self, value, revision, **kwargs):
        if revision != self.value['revision']: raise Error('stale', 409)
        self.value = {'revision': revision + 'x', 'remote': copy.deepcopy(value)}


class Host(SystemPluginsMixin, RemoteAccessMixin):
    def __init__(self, directory):
        self.directory = directory
        self.values = {}
        self.web_access = Web()
        self.commands = []
        self.running = False
        self.enabled = False
        self.legacy_running = True
        self.actions = []
        self.op_remote_access_diagnose = Mock(return_value={'connected': True})

    def load(self, key, default): return copy.deepcopy(self.values.get(key, default))
    def save(self, key, value): self.values[key] = copy.deepcopy(value)
    def nvidia_component(self): return {'requested': False, 'available': False, 'card': False}
    def managed_app(self, app): return {'id': app}
    def _app_container(self, app, record): return {'State': {'Running': self.legacy_running}}
    def op_app_action(self, app, action):
        self.actions.append((app, action))
        self.legacy_running = action == 'start'

    def command(self, args, **kwargs):
        self.commands.append(args)
        verb = args[1]
        if verb == 'is-active': return 'active' if self.running else 'inactive'
        if verb == 'is-enabled': return 'enabled' if self.enabled else 'disabled'
        if verb in ('start', 'stop'): self.running = verb == 'start'
        if verb in ('enable', 'disable'):
            self.enabled = verb == 'enable'
            if '--now' in args: self.running = self.enabled
        return ''


class PluginTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.binary_root = self.root / 'plugins'
        self.unit = self.root / 'systemd' / 'unit.service'
        directory = self.root / 'agent'; directory.mkdir(mode=0o700)
        self.host = Host(directory)
        self.enterContext(patch('titan.system_plugins.ROOT', self.binary_root))
        self.enterContext(patch('titan.system_plugins.UNIT_PATH', self.unit))
        self.enterContext(patch('titan.system_plugins.platform.machine', return_value='x86_64'))
        self.ready = self.enterContext(patch('titan.system_plugins.connected', return_value=True))
        self.download = self.enterContext(patch('titan.system_plugins.download', side_effect=lambda candidate, path: path.write_bytes(b'new-binary')))

    def act(self, action='install', **options):
        return self.host.op_plugin_action('cloudflare', action, self.host._plugin_revision(), options or None,
                                          confirmation='cloudflare' if action == 'remove' else None)

    def install(self, **options):
        return self.act(token=credential(), public_origin='https://nas.example.org', **options)

    def test_install_sets_restricted_local_target_and_keeps_secret_out_of_status(self):
        result = self.install()
        self.assertTrue(result['connected'])
        remote = self.host.web_access.config()['remote']
        self.assertEqual(remote['connector'], 'plugin-cloudflare')
        self.assertEqual(remote['service_url'], 'http://127.0.0.1:5102')
        self.assertEqual(remote['sources'], [])
        private = self.host.directory / 'cloudflare-plugin-token'
        self.assertEqual(private.read_text(), credential())
        self.assertEqual(private.stat().st_mode & 0o777, 0o600)
        unit = self.unit.read_text()
        self.assertIn('--token-file %d/tunnel-token', unit)
        self.assertIn('DynamicUser=yes', unit)
        public = json.dumps([self.host.op_plugins(), self.host.op_remote_access(), self.host.commands, result]) + unit
        self.assertNotIn(credential(), public)
        self.assertTrue(self.host.enabled)
        self.assertTrue(self.host.running)

    def test_download_failure_leaves_existing_stopped_service_and_files_untouched(self):
        self.install()
        self.host.running = False; self.host.enabled = False
        self.host.commands.clear()
        before = self.host._plugin_state()
        self.download.side_effect = Error('untrusted output ' + credential())
        with self.assertRaises(Error) as error: self.act('update')
        self.assertNotIn(credential(), str(error.exception))
        self.assertFalse(self.host.running)
        self.assertFalse(self.host.enabled)
        self.assertEqual((self.binary_root / 'cloudflared').read_bytes(), b'new-binary')
        self.assertEqual(self.host._plugin_state(), before)
        self.assertTrue(all(command[1].startswith('is-') for command in self.host.commands))

    def test_readiness_failure_restores_binary_token_and_stopped_service(self):
        self.install()
        (self.binary_root / 'cloudflared').write_bytes(b'old-binary')
        self.host.running = False; self.host.enabled = False
        before = self.host.web_access.config()
        self.ready.return_value = False
        with patch('titan.system_plugins.time.monotonic', side_effect=[0, 30]):
            with self.assertRaises(Error): self.act('update')
        self.assertEqual((self.binary_root / 'cloudflared').read_bytes(), b'old-binary')
        self.assertEqual(self.host.web_access.config(), before)
        self.assertFalse(self.host.running)
        self.assertFalse(self.host.enabled)
        self.assertEqual((self.host.directory / 'cloudflare-plugin-token').read_text(), credential())

    def test_first_install_failure_removes_new_files_and_never_uses_stale_backup(self):
        self.binary_root.mkdir()
        (self.binary_root / 'cloudflared.previous').write_bytes(b'stale')
        self.ready.return_value = False
        with patch('titan.system_plugins.time.monotonic', side_effect=[0, 30]):
            with self.assertRaises(Error): self.install()
        self.assertFalse((self.binary_root / 'cloudflared').exists())
        self.assertFalse((self.host.directory / 'cloudflare-plugin-token').exists())
        self.assertFalse(self.unit.exists())
        self.assertFalse(self.host.enabled)
        self.assertFalse(self.host._cloudflare_installed())

    def test_docker_migration_is_explicit_and_old_runner_stops_only_after_connection(self):
        self.host.values['apps'] = [{'id': 'titan-cloudflared'}]
        with self.assertRaises(Error): self.install()
        self.download.assert_not_called()
        self.assertTrue(self.host.legacy_running)
        self.install(replace_docker=True)
        self.assertEqual(self.host.actions, [('titan-cloudflared', 'stop')])
        self.assertFalse(self.host.legacy_running)
        self.assertEqual(self.host._remote_setup_status()['connector'], 'plugin-cloudflare')

    def test_final_save_failure_restores_remote_and_legacy_runner(self):
        self.host.values['apps'] = [{'id': 'titan-cloudflared'}]
        initial = self.host.web_access.config()['remote']
        save = self.host.save
        def fail_once(key, value):
            if value.get('cloudflare', {}).get('installed'):
                raise OSError('disk full')
            return save(key, value)
        self.host.save = fail_once
        with self.assertRaises(Error): self.install(replace_docker=True)
        self.assertEqual(self.host.web_access.config()['remote'], initial)
        self.assertTrue(self.host.legacy_running)
        self.assertFalse(self.host._cloudflare_installed())

    def test_public_probe_failure_does_not_undo_connected_service(self):
        self.host.op_remote_access_diagnose.side_effect = OSError('DNS failure')
        result = self.install()
        self.assertFalse(result['connected'])
        self.assertTrue(self.host.running)
        self.assertIn('HTTP und 127.0.0.1:5102', result['message'])

    def test_remove_requires_confirmation_then_removes_only_owned_files(self):
        self.install()
        neighbor = self.binary_root / 'unrelated'; neighbor.write_text('keep')
        with self.assertRaises(Error):
            self.host.op_plugin_action('cloudflare', 'remove', self.host._plugin_revision())
        self.act('remove')
        self.assertFalse(self.host.web_access.config()['remote']['enabled'])
        self.assertFalse(self.unit.exists())
        self.assertFalse((self.host.directory / 'cloudflare-plugin-token').exists())
        self.assertEqual(neighbor.read_text(), 'keep')

    def test_state_revision_and_fixed_registry_reject_unreviewed_actions(self):
        for plugin, action, revision in [('unknown', 'install', self.host._plugin_revision()),
                                         ('cloudflare', 'exec', self.host._plugin_revision()), ('cloudflare', 'install', 'old')]:
            with self.assertRaises(Error): self.host.op_plugin_action(plugin, action, revision)
        self.download.assert_not_called()

    def test_private_file_symlinks_and_other_user_access_are_rejected(self):
        private = self.host.directory / 'cloudflare-plugin-token'
        private.symlink_to(self.root / 'outside')
        with self.assertRaises(Error): self.install()
        private.unlink(); private.write_text(credential()); private.chmod(0o644)
        with self.assertRaises(Error): self.install()
        self.download.assert_not_called()

    def test_agent_restart_keeps_stopped_plugin_stopped_and_checks_persistent_binary(self):
        self.install()
        state = self.host._plugin_state()
        state['cloudflare']['sha256'] = hashlib.sha256(b'new-binary').hexdigest()
        self.host.save('system-plugins', state)
        self.host.running = False; self.host.commands.clear()
        self.host.op_plugins_restore()
        self.assertEqual(self.host.commands, [])
        self.unit.unlink()
        self.host.op_plugins_restore()
        self.assertTrue(self.host.running)
        (self.binary_root / 'cloudflared').write_bytes(b'tampered')
        with self.assertRaises(Error): self.host.op_plugins_restore()

    def test_nvidia_license_and_helper_allowlist(self):
        with patch('titan.components.run_plugin_component', return_value={'ok': True, 'version': '1'}) as helper:
            for action in ('install', 'update'):
                with self.assertRaises(Error): self.host.op_plugin_action('nvidia', action, self.host._plugin_revision())
                helper.assert_not_called()
            self.host.op_plugin_action('nvidia', 'install', self.host._plugin_revision(), {'accept_license': True})
            helper.assert_called_once_with(self.host, 'install')
            with self.assertRaises(Error): self.host.op_plugin_action('nvidia', 'start', self.host._plugin_revision())


class OffersTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('titan.system_plugins.platform.machine', return_value='x86_64'))

    def test_only_stable_canonical_vendor_assets_with_digest_are_accepted(self):
        good = offer()
        release = {'tag_name': good['version'], 'draft': False, 'prerelease': False,
                   'assets': [{'name': 'cloudflared-linux-amd64', 'digest': 'sha256:' + good['sha256'], 'browser_download_url': good['url']}]}
        def response(value): return io.BytesIO(json.dumps(value).encode())
        with patch('urllib.request.urlopen', return_value=response(release)):
            self.assertEqual(latest_offer(), good)
        for changes in ({'prerelease': True}, {'draft': True}, {'tag_name': '../../other'}, {'assets': [{**release['assets'][0], 'digest': None}]}, {'assets': [{**release['assets'][0], 'browser_download_url': 'https://other.example/binary'}]}):
            with patch('urllib.request.urlopen', return_value=response({**release, **changes})), self.assertRaises(Error): latest_offer()

    def test_download_checks_contents_and_rejects_corrupt_payload_before_install(self):
        data = b'x' * (1024 * 1024)
        good = offer(digest=hashlib.sha256(data).hexdigest())
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'owned'; directory.mkdir()
            target = directory / 'binary'
            response = io.BytesIO(data); response.geturl = lambda: good['url']
            with patch('urllib.request.urlopen', return_value=response): download(good, target)
            self.assertEqual(read_owned(target), data)
            target.unlink()
            response = io.BytesIO(data); response.geturl = lambda: good['url']
            with patch('urllib.request.urlopen', return_value=response), self.assertRaises(Error): download(offer(), target)
            self.assertFalse(target.exists())

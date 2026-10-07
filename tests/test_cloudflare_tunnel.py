"""Direct-token setup, private runner inputs, recovery and public readiness."""
import base64
import contextlib
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from titan.app_management import AppMixin
from titan.app_packages import PACKAGES, prepare_options
from titan.catalog import compose, published_ports, validate_options
from titan.cloudflare_tunnel import CONNECTOR, METRICS_PORT, connector_ready, prepare_runtime, validate_token
from titan.core import Error, atomic_json
from titan.remote_access import RemoteAccessMixin, validate_remote
from titan.web_access import WebAccess, allowed_origins, initial_config


def token(secret=b'test-secret-with-enough-entropy-123', **updates):
    value = {'a': 'a' * 32, 't': '2c9069cd-5cf1-470f-9ddd-df156d3f2c57',
             's': base64.b64encode(secret).decode(), **updates}
    return base64.b64encode(json.dumps(value).encode()).decode()


class Storage:
    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(mode=0o755)

    @contextlib.contextmanager
    def fd(self, storage, **kwargs):
        descriptor = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            yield descriptor, {'path': str(self.path)}
        finally:
            os.close(descriptor)


class TunnelHost(RemoteAccessMixin):
    """Real private files/Caddy generator; only the Docker daemon is simulated."""
    _app_options = AppMixin._app_options

    def __init__(self, directory):
        self.directory = Path(directory)
        self.app_config_lock = threading.RLock()
        self.storage_locations = Storage(self.directory / 'app-data')
        self.container = None
        self.actions, self.phases, self.commands, self.firewalls = [], [], [], []
        self.component = {'available': True}
        self.fail_start = False
        self.fail_proxy = False
        self.web_access = WebAccess(self.directory / 'web', run=self.run,
            schedule=lambda delay, callback: callback(),
            firewall=lambda ports: {'available': False},
            remote_firewall=lambda value: self.firewalls.append(copy.deepcopy(value)))
        self.web_access.config()
        self.op_remote_access_diagnose = Mock(return_value={'connected': True})
        def diagnose():
            result = {**self.op_remote_access_diagnose.return_value, 'revision': self.web_access.config()['revision']}
            self.save('remote-diagnosis', result)
            return result
        self.op_remote_access_diagnose.side_effect = diagnose

    def run(self, argv, **kwargs):
        self.commands.append(argv)
        if self.fail_proxy and argv[0] == 'systemctl':
            self.fail_proxy = False
            raise Error('disposable proxy restart failure')
        return ''

    def load(self, key, default):
        path = self.directory / (key + '.json')
        return json.loads(path.read_text()) if path.exists() else copy.deepcopy(default)

    def save(self, key, value):
        if key == 'remote-tunnel-setup':
            self.phases.append(copy.deepcopy(value))
        atomic_json(self.directory / (key + '.json'), value)

    def _app_config_path(self, app, record):
        return Path(record['config_path'])

    def managed_app(self, app):
        return next(row for row in self.load('apps', []) if row['id'] == app)

    def _app_container(self, app, record):
        return self.container if app == CONNECTOR else None

    def docker_component(self):
        return self.component

    def op_component_install(self, component):
        self.actions.append(('component', component))
        self.component = {'available': True}

    def op_app_install(self, app, port, options, network, storage_id):
        self.actions.append(('install', app, port, network, storage_id))
        control = self.directory / 'apps' / app
        config = self.storage_locations.path / app / 'config'
        config.parent.mkdir(mode=0o755)
        config.mkdir(mode=0o755)
        (config / 'credentials').mkdir(mode=0o755)
        record = {'id': app, 'name': PACKAGES[app]['name'], 'network': network,
                  'storage_id': storage_id, 'config_path': str(config), 'port': port}
        atomic_json(control / 'options.json', validate_options(app, prepare_options(app, options)))
        definition = compose(app, str(control), os.geteuid(), os.getegid(), port,
            str(config.parent / 'data'), self._app_options(app), network, config_path=str(config))
        atomic_json(control / 'compose.json', definition)
        self.save('apps', [*self.load('apps', []), record])
        prepare_runtime(self, record)
        self.container = {'Id': 'a' * 64, 'HostConfig': {'NetworkMode': network['mode']},
                          'State': {'Running': True, 'Status': 'running', 'Pid': 12345}}
        return {'ok': True}

    def op_app_action(self, app, action):
        self.actions.append((action, app))
        if action in ('start', 'restart'):
            prepare_runtime(self, self.managed_app(app))
            if self.fail_start:
                self.fail_start = False
                raise Error('untrusted error ' + self._app_options(app)['tunnel_token'])
            self.container['State'].update(Running=True, Status='running')
        elif action == 'stop':
            self.container['State'].update(Running=False, Status='exited')
        return {'ok': True}


class TokenTests(unittest.TestCase):
    def test_standard_upstream_envelope_and_optional_empty_endpoint(self):
        for value in (token(), token(e='')):
            self.assertEqual(validate_token(value), value)

    def test_no_shell_commands_api_tokens_whitespace_or_invalid_envelopes(self):
        bad = [None, {}, '', 'cloudflared service install ' + token(), token() + '\n',
               'Bearer ' + token(), 'x' * 4097, token(a='wrong'), token(t='00000000-0000-0000-0000-000000000000'),
               token(t='2c9069cd5cf1470f9ddddf156d3f2c57'), token(secret=b'short'), token(s='not base64'),
               token(e='attacker.example'), token(extra='unexpected')]
        for value in bad:
            with self.subTest(value=str(value)[:20]), self.assertRaises(Error) as error:
                validate_token(value)
            if isinstance(value, str) and len(value) > 40:
                self.assertNotIn(value, str(error.exception))

    def test_runner_definition_has_no_secret_env_shell_or_published_ports(self):
        credential = token()
        options = validate_options(CONNECTOR, prepare_options(CONNECTOR, {'tunnel_token': credential}))
        definition = compose(CONNECTOR, '/agent/apps/' + CONNECTOR, 1000, 1000, 0, '/nas/data', options, {'mode': 'host'})
        service = definition['services'][CONNECTOR]
        self.assertNotIn(credential, json.dumps(definition))
        self.assertEqual(service['command'], ['tunnel', '--no-autoupdate', '--metrics', '127.0.0.1:5103', 'run', '--token-file', '/etc/cloudflared/token'])
        self.assertEqual(service['environment'], {})
        self.assertEqual(service['network_mode'], 'host')
        self.assertEqual(service.get('ports', []), [])
        self.assertEqual(published_ports(CONNECTOR, 0, options, host_mode=True), [])
        self.assertEqual(service['cap_drop'], ['ALL'])
        self.assertEqual(service['security_opt'], ['no-new-privileges:true'])
        self.assertTrue(service['read_only'])
        self.assertTrue(service['volumes'][0]['read_only'])
        self.assertFalse(service['volumes'][0]['bind']['create_host_path'])
        self.assertIn('@sha256:', service['image'])
        self.assertIs(PACKAGES[CONNECTOR]['web_available'], False)


class TunnelSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.host = TunnelHost(self.temp.name)
        self.initial = self.host.web_access.config()
        self.credential = token()
        self.ready = self.enterContext(patch('titan.cloudflare_tunnel.connector_ready', return_value=True))
        self.enterContext(patch('titan.remote_access.time.sleep'))
        self.run = self.enterContext(patch('titan.host.run', return_value=''))

    def setup(self, address='https://nas.example.com'):
        return self.host.op_remote_access_tunnel(self.credential, address, self.host.web_access.config()['revision'])

    def token_file(self):
        return self.host.storage_locations.path / CONNECTOR / 'config' / 'credentials' / 'token'

    def assert_no_public_token(self, result=None):
        public = {'result': result, 'phases': self.host.phases, 'status': self.host.op_remote_access(),
                  'commands': self.host.commands, 'actions': self.host.actions}
        self.assertNotIn(self.credential, json.dumps(public))

    def test_new_setup_installs_host_runner_and_enables_restricted_proxy_without_changing_lan(self):
        result = self.setup()
        self.assertTrue(result['ok'])
        self.assertEqual(result['setup']['phase'], 'ready')
        self.assertTrue(result['setup']['cloudflare_connected'])
        self.assertFalse(result['setup']['running'])
        self.assertEqual(result['remote']['connector'], CONNECTOR)
        self.assertEqual(result['remote']['service_url'], 'http://127.0.0.1:5102')
        self.assertEqual(result['remote']['sources'], [])
        self.assertEqual(self.host.actions, [('install', CONNECTOR, 0, {'mode': 'host'}, 'system')])
        current = self.host.web_access.config()
        self.assertEqual(current['settings'], self.initial['settings'])
        self.assertEqual(current['host'], self.initial['host'])
        self.assertEqual(allowed_origins(current), {'https://titan.local', 'https://nas.example.com'})
        caddy = (self.host.web_access.directory / 'Caddyfile').read_text()
        self.assertIn('bind 127.0.0.1', caddy)
        self.assertIn('host nas.example.com', caddy)
        self.assertIn('respond 403', caddy)
        self.assertEqual([row['phase'] for row in self.host.phases], ['preparing', 'installing', 'connecting', 'configuring', 'checking', 'ready'])
        self.assert_no_public_token(result)

    def test_empty_domain_starts_connector_but_does_not_enable_proxy_or_change_origins(self):
        before = self.host.web_access.path.read_bytes()
        result = self.setup('')
        self.assertTrue(result['setup']['needs_domain'])
        self.assertEqual(result['setup']['phase'], 'needs_domain')
        self.assertTrue(result['setup']['cloudflare_connected'])
        self.assertFalse(result['remote']['enabled'])
        self.assertEqual(before, self.host.web_access.path.read_bytes())
        self.assertFalse((self.host.web_access.directory / 'Caddyfile').exists())
        self.host.op_remote_access_diagnose.assert_not_called()
        self.assert_no_public_token(result)

    def test_unconfirmed_public_route_is_reported_separately_from_connected_runner(self):
        self.host.op_remote_access_diagnose.return_value = {'connected': False}
        result = self.setup()
        self.assertTrue(result['ok'])
        self.assertEqual(result['setup']['phase'], 'needs_route')
        self.assertTrue(result['remote']['enabled'])
        self.assertTrue(result['setup']['cloudflare_connected'])
        self.assertFalse(result['setup']['needs_domain'])

    def test_saved_domain_app_urls_and_existing_bigbear_credentials_are_preserved(self):
        old = {'id': 'bigbear-cloudflared', 'name': 'Existing Cloudflared'}
        self.host.save('apps', [old])
        legacy_options = self.host.directory / 'apps' / old['id'] / 'options.json'
        atomic_json(legacy_options, {'password': 'existing-private-password', 'other': 'keep'})
        config = self.host.web_access.config()
        config['remote'] = {**validate_remote(None), 'public_origin': 'https://saved.example.com',
            'app_urls': {'bigbear-cloudflared': 'https://app.example.com'}}
        atomic_json(self.host.web_access.path, config, mode=0o644)
        before = legacy_options.read_bytes()
        result = self.setup('')
        self.assertEqual(result['remote']['public_origin'], 'https://saved.example.com')
        self.assertEqual(result['remote']['app_urls'], config['remote']['app_urls'])
        self.assertEqual(legacy_options.read_bytes(), before)
        self.assertEqual(self.host.load('apps', [])[0], old)

    def test_token_rotation_keeps_advanced_network_and_restores_old_token_on_start_failure(self):
        self.setup()
        previous = self.token_file().read_text()
        config_before = self.host.web_access.config()
        self.credential = token(b'replacement-secret-with-enough-entropy')
        self.host.fail_start = True
        with self.assertRaisesRegex(Error, 'Bisheriger Token') as error:
            self.setup()
        self.assertNotIn(self.credential, str(error.exception))
        self.assertEqual(self.token_file().read_text(), previous)
        self.assertEqual(self.host._app_options(CONNECTOR)['tunnel_token'], previous)
        self.assertTrue(self.host.container['State']['Running'])
        self.assertEqual(self.host.web_access.config(), config_before)
        self.assertEqual(self.host.phases[-1]['phase'], 'failed')
        self.assert_no_public_token()

    def test_successful_rotation_updates_private_token_and_reuses_single_app(self):
        self.setup()
        self.credential = token(b'new-secret-with-enough-entropy-123456')
        result = self.setup()
        self.assertEqual(self.token_file().read_text(), self.credential)
        self.assertEqual(len(self.host.load('apps', [])), 1)
        self.assertIn(('restart', CONNECTOR), self.host.actions)
        self.assertEqual(result['setup']['phase'], 'ready')
        self.assert_no_public_token(result)

    def test_connection_timeout_stops_fresh_runner_and_keeps_local_config(self):
        self.ready.return_value = False
        self.enterContext(patch('titan.remote_access.time.monotonic', side_effect=[0, 30]))
        before = self.host.web_access.path.read_bytes()
        with self.assertRaisesRegex(Error, '7844'):
            self.setup()
        self.assertEqual(self.host.web_access.path.read_bytes(), before)
        self.assertFalse(self.host.container['State']['Running'])
        self.assertIn(('stop', CONNECTOR), self.host.actions)
        self.assertEqual(self.host.phases[-1]['phase'], 'failed')
        self.assert_no_public_token()

    def test_proxy_restart_failure_preserves_lan_and_stops_fresh_runner(self):
        self.host.fail_proxy = True
        with self.assertRaisesRegex(Error, 'Proxy'):
            self.setup()
        config = self.host.web_access.config()
        self.assertEqual(config['settings'], self.initial['settings'])
        self.assertEqual(config['host'], self.initial['host'])
        self.assertFalse(validate_remote(config.get('remote'))['enabled'])
        self.assertFalse(self.host.container['State']['Running'])
        self.assertEqual(allowed_origins(config), {'https://titan.local'})
        self.assert_no_public_token()

    def test_setup_waits_for_slow_activation_and_does_not_report_success_before_late_rollback(self):
        started, release = threading.Event(), threading.Event()
        failures = []
        count = 0
        def restart():
            nonlocal count
            count += 1
            if count == 1:
                started.set()
                if not release.wait(3):
                    raise Error('test activation release missing')
                raise Error('late disposable proxy failure')
        def schedule(delay, callback):
            timer = threading.Timer(.01, callback)
            timer.daemon = True
            timer.start()
            return timer
        # An asynchronous production-shaped scheduler is essential here. A
        # synchronous callback stub would conceal the old fixed-sleep race.
        self.host.web_access.schedule = schedule
        self.host.web_access._restart = restart
        def setup():
            try:
                self.setup()
            except Error as error:
                failures.append(error)
        thread = threading.Thread(target=setup, daemon=True)
        thread.start()
        try:
            self.assertTrue(started.wait(2))
            self.assertTrue(thread.is_alive())
            self.assertEqual(self.host.load('remote-tunnel-setup', {})['phase'], 'configuring')
            self.assertTrue(self.host.load('remote-tunnel-setup', {})['running'])
            self.host.op_remote_access_diagnose.assert_not_called()
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(failures), 1)
        self.assertEqual(self.host.load('remote-tunnel-setup', {})['phase'], 'failed')
        self.assertFalse(validate_remote(self.host.web_access.config().get('remote'))['enabled'])
        self.assertFalse(self.host.container['State']['Running'])
        self.assertEqual(self.host.web_access.config()['settings'], self.initial['settings'])
        self.assert_no_public_token()

    def test_stale_revision_bad_token_pending_change_and_bad_domain_have_no_side_effects(self):
        config = self.host.web_access.config()
        for arguments in ((self.credential, '', 'stale'), ('bad-token', '', config['revision']),
                (self.credential, 'https://user:password@nas.example.com', config['revision'])):
            with self.subTest(arguments=arguments[1:]), self.assertRaises(Error):
                self.host.op_remote_access_tunnel(*arguments)
        config['pending'] = {'previous': copy.deepcopy(config), 'deadline': 1234}
        atomic_json(self.host.web_access.path, config, mode=0o644)
        with self.assertRaises(Error):
            self.host.op_remote_access_tunnel(self.credential, '', config['revision'])
        self.assertEqual(self.host.actions, [])
        self.assertEqual(self.host.phases, [])

    def test_unavailable_docker_is_repaired_before_install_and_busy_metrics_port_blocks(self):
        self.host.component = {'available': False}
        self.setup()
        self.assertEqual(self.host.actions[0], ('component', 'docker'))
        self.assertEqual(self.run.call_args_list[0].args[0], ['ss', '-H', '-ltn', 'sport = :5103'])

    def test_occupied_metrics_port_leaves_existing_local_config_and_apps_untouched(self):
        self.run.return_value = 'LISTEN 127.0.0.1:5103'
        before = self.host.web_access.path.read_bytes()
        with self.assertRaisesRegex(Error, '5103'):
            self.setup()
        self.assertEqual(self.host.actions, [])
        self.assertEqual(self.host.load('apps', []), [])
        self.assertEqual(self.host.web_access.path.read_bytes(), before)

    def test_initial_status_write_failure_always_releases_active_flag_without_touching_apps(self):
        save = self.host.save
        failed = False
        def first_write_fails(key, value):
            nonlocal failed
            if key == 'remote-tunnel-setup' and not failed:
                failed = True
                raise OSError('disposable disk full')
            return save(key, value)
        self.host.save = first_write_fails
        with self.assertRaises(Error):
            self.setup()
        self.assertFalse(self.host._remote_setup_active)
        self.assertEqual(self.host.actions, [])

    def test_finishing_domain_then_regular_diagnosis_advances_pending_setup(self):
        self.setup('')
        value = self.host.op_remote_access_apply(True, 'https://nas.example.com', CONNECTOR, {},
            self.host.web_access.config()['revision'])
        self.assertFalse(value['setup']['needs_domain'])
        self.assertEqual(value['setup']['phase'], 'needs_route')
        with patch('titan.remote_access.probe_public', return_value={'ok': True, 'message': 'reachable'}):
            RemoteAccessMixin.op_remote_access_diagnose(self.host)
        self.assertEqual(self.host.op_remote_access()['setup']['phase'], 'ready')

    def test_ready_state_tracks_connection_disable_other_connector_and_fresh_revision(self):
        self.setup()
        self.ready.return_value = False
        value = self.host.op_remote_access()['setup']
        self.assertEqual(value['phase'], 'disconnected')
        self.assertTrue(value['connector_running'])
        self.assertFalse(value['cloudflare_connected'])
        self.ready.return_value = True
        config = self.host.web_access.config()
        for change in ({'enabled': False}, {'connector': ''}):
            current = {**config, 'remote': {**config['remote'], **change}}
            atomic_json(self.host.web_access.path, current, mode=0o644)
            self.assertEqual(self.host.op_remote_access()['setup']['phase'], 'disabled')
        config['revision'] = 'new-revision'
        atomic_json(self.host.web_access.path, config, mode=0o644)
        self.assertEqual(self.host.op_remote_access()['setup']['phase'], 'needs_route')

    def test_diagnosis_exception_rolls_back_remote_and_restores_previous_credential(self):
        self.setup()
        previous = self.host.web_access.config()['remote']
        old_token = self.token_file().read_text()
        self.credential = token(b'replacement-secret-for-late-rollback')
        self.host.op_remote_access_diagnose.side_effect = Error('untrusted ' + self.credential)
        with self.assertRaisesRegex(Error, 'abschließende') as error:
            self.setup('https://new.example.com')
        self.assertNotIn(self.credential, str(error.exception))
        self.assertEqual(self.host.web_access.config()['remote'], previous)
        self.assertEqual(self.token_file().read_text(), old_token)
        self.assertTrue(self.host.container['State']['Running'])

    def test_proxy_failure_during_same_domain_rotation_is_not_success_despite_equal_remote_values(self):
        self.setup()
        before = self.host.web_access.config()['remote']
        old_token = self.token_file().read_text()
        self.credential = token(b'replacement-secret-for-same-domain')
        self.host.fail_proxy = True
        self.host.op_remote_access_diagnose.reset_mock()
        with self.assertRaisesRegex(Error, 'Proxy'):
            self.setup()
        self.host.op_remote_access_diagnose.assert_not_called()
        self.assertEqual(self.host.web_access.config()['remote'], before)
        self.assertEqual(self.token_file().read_text(), old_token)
        self.assertEqual(self.host.phases[-1]['phase'], 'failed')
        self.assertTrue(self.host.container['State']['Running'])

    def test_failed_final_rollback_activation_is_reported_and_still_restores_old_token(self):
        self.setup()
        old_token = self.token_file().read_text()
        original_save = self.host.web_access.save_remote
        saves = 0
        def fail_second_activation(*args, **kwargs):
            nonlocal saves
            saves += 1
            if saves == 2:
                self.host.fail_proxy = True
            return original_save(*args, **kwargs)
        self.host.web_access.save_remote = fail_second_activation
        self.host.op_remote_access_diagnose.side_effect = Error('disposable final diagnosis failed')
        self.credential = token(b'replacement-secret-for-failed-rollback')
        with self.assertRaisesRegex(Error, 'Wiederherstellung.*unvollständig'):
            self.setup('https://new.example.com')
        self.assertEqual(self.token_file().read_text(), old_token)
        self.assertTrue(self.host.container['State']['Running'])
        # Failed rollback activation restored its own previous config. This
        # state must not be misreported as the originally requested recovery.
        self.assertEqual(self.host.web_access.config()['remote']['public_origin'], 'https://new.example.com')
        self.assertEqual(self.host.phases[-1]['phase'], 'failed')

    def test_rotation_preserves_selected_bridge_and_uses_observed_gateway(self):
        self.setup()
        records = self.host.load('apps', [])
        records[0]['network'] = {'mode': 'bridge', 'name': 'selected-private-bridge'}
        self.host.save('apps', records)
        self.host.container['HostConfig']['NetworkMode'] = 'selected-private-bridge'
        self.host.container['NetworkSettings'] = {'Networks': {'selected-private-bridge': {}}}
        self.host._docker_network = Mock(return_value={'Driver': 'bridge', 'Id': 'a' * 64})
        self.host._network_subnets = Mock(return_value=[{'family': 4, 'subnet': '172.30.1.0/24', 'gateway': '172.30.1.1'}])
        self.credential = token(b'replacement-secret-for-private-bridge')
        result = self.setup()
        self.assertEqual(self.host.load('apps', [])[0]['network'], records[0]['network'])
        self.assertEqual(result['remote']['service_url'], 'http://172.30.1.1:5102')
        self.assertEqual(result['remote']['sources'], ['172.30.1.0/24'])
        self.assertEqual(result['setup']['service_url'], 'http://172.30.1.1:5102')
        self.assertEqual(self.host.firewalls[-1]['sources'], ['172.30.1.0/24'])

    def test_stopped_removed_and_interrupted_states_do_not_claim_connected(self):
        self.setup()
        self.host.op_app_action(CONNECTOR, 'stop')
        # A real /ready query always checks Running before opening a socket.
        self.ready.side_effect = lambda container: bool(container and container['State']['Running'])
        result = self.host.op_remote_access()['setup']
        self.assertEqual(result['phase'], 'stopped')
        self.assertFalse(result['connector_running'])
        self.assertFalse(result['cloudflare_connected'])
        self.host.save('apps', [])
        self.assertEqual(self.host.op_remote_access()['setup']['phase'], 'removed')
        self.host._remote_setup_update('connecting', 'connecting', running=True)
        self.host._remote_setup_active = False
        self.assertEqual(self.host.op_remote_access()['setup']['phase'], 'interrupted')
        self.host.save('apps', [{'id': CONNECTOR}])
        self.host.managed_app = Mock(side_effect=Error('missing definition'))
        self.assertEqual(self.host.op_remote_access()['setup']['phase'], 'blocked')


class PrivateTokenFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.host = TunnelHost(self.temp.name)
        self.credential = token()
        self.host.op_app_install(CONNECTOR, 0, {'tunnel_token': self.credential}, {'mode': 'host'}, 'system')
        self.record = self.host.managed_app(CONNECTOR)
        self.config = Path(self.record['config_path'])
        self.private = self.config / 'credentials'
        self.path = self.private / 'token'

    def test_private_permissions_atomic_rotation_and_no_temporary_files(self):
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.private.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o700)
        self.assertEqual(self.path.stat().st_uid, os.geteuid())
        old_inode = self.path.stat().st_ino
        credential = token(b'replacement-token-with-enough-entropy')
        options = self.host._app_options(CONNECTOR)
        atomic_json(self.host.directory / 'apps' / CONNECTOR / 'options.json', {**options, 'tunnel_token': credential})
        prepare_runtime(self.host, self.record)
        self.assertEqual(self.path.read_text(), credential)
        self.assertNotEqual(self.path.stat().st_ino, old_inode)
        self.assertEqual([entry.name for entry in self.private.iterdir()], ['token'])

    def test_token_symlink_hardlink_and_public_file_are_rejected_without_touching_target(self):
        external = self.host.directory / 'external'
        external.write_text('keep me')
        for kind in ('symlink', 'hardlink', 'public'):
            with self.subTest(kind=kind):
                self.path.unlink()
                if kind == 'symlink': self.path.symlink_to(external)
                elif kind == 'hardlink': os.link(external, self.path)
                else: self.path.write_text('unsafe'); self.path.chmod(0o644)
                with self.assertRaises(Error): prepare_runtime(self.host, self.record)
                self.assertEqual(external.read_text(), 'keep me')

    def test_credentials_directory_symlink_and_config_path_mismatch_fail_closed(self):
        self.path.unlink()
        self.private.rmdir()
        external = self.host.directory / 'outside'
        external.mkdir()
        self.private.symlink_to(external, target_is_directory=True)
        with self.assertRaises(Error): prepare_runtime(self.host, self.record)
        self.assertEqual(list(external.iterdir()), [])
        with self.assertRaises(Error): prepare_runtime(self.host, {**self.record, 'config_path': str(external)})

    def test_real_app_prestart_path_prepares_file_before_compose_create_start_restart(self):
        host = self.host
        host.app_storage_ready = Mock()
        host.app_devices_ready = Mock()
        host._app_network_validate = Mock(return_value=({'mode': 'host'}, None))
        host._host_ports_available = Mock()
        host._app_container_rows = Mock(return_value=[])
        host._app_inspected_containers = Mock(return_value=[])
        host._app_private_config_label = Mock()
        host._app_firewall = Mock()
        host.telemetry = Mock()
        calls = []
        def invoke(argv, **kwargs):
            calls.append(argv)
            self.assertEqual(self.path.read_text(), self.credential)
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
            self.assertNotIn(self.credential, json.dumps(argv))
            return ''
        with patch('titan.app_management._run', side_effect=invoke), patch('titan.app_memory.check_start_memory'):
            for action in ('create', 'up', 'restart'):
                with self.subTest(action=action):
                    self.path.unlink()
                    AppMixin._docker(host, CONNECTOR, action)
                    self.assertEqual(self.path.read_text(), self.credential)
        self.assertTrue(any('create' in call for call in calls))


class ConnectorReadinessTests(unittest.TestCase):
    def test_real_http_ready_checks_are_loopback_only_and_do_not_follow_redirects(self):
        class Handler(BaseHTTPRequestHandler):
            status = 200
            paths = []
            def do_GET(self):
                self.paths.append(self.path)
                self.send_response(self.status)
                self.send_header('Location', 'http://192.168.1.1/private')
                self.end_headers()
                self.wfile.write(b'ready')
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        container = {'State': {'Running': True}, 'HostConfig': {'NetworkMode': 'host'}}
        with patch('titan.cloudflare_tunnel.METRICS_PORT', server.server_port):
            self.assertTrue(connector_ready(container))
            Handler.status = 302
            self.assertFalse(connector_ready(container))
            Handler.status = 503
            self.assertFalse(connector_ready(container))
            self.assertFalse(connector_ready({'State': {'Running': False}}))
        self.assertEqual(Handler.paths, ['/ready', '/ready', '/ready'])

    def test_bridge_probe_uses_only_observed_pid_and_fixed_loopback_endpoint(self):
        container = {'State': {'Running': True, 'Pid': 12345}, 'HostConfig': {'NetworkMode': 'bridge'}}
        with patch('titan.host.run', return_value='ready') as run:
            self.assertTrue(connector_ready(container))
            argv = run.call_args.args[0]
            self.assertEqual(argv[:7], ['nsenter', '-t', '12345', '-n', '--', '/usr/bin/python3', '-c'])
            self.assertIn('127.0.0.1', argv[-1])
            self.assertIn(str(METRICS_PORT), argv[-1])
            self.assertNotIn('token', argv[-1])
            run.reset_mock()
            for invalid in (0, -1, True, '1;command'):
                container['State']['Pid'] = invalid
                self.assertFalse(connector_ready(container))
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()

"""Native recipes, real command journals and fail-closed network setup."""
import copy
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch

from titan.app_installation import AppInstallationMixin, NATIVE_STEPS, validate_options
from titan.app_management import AppMixin
from titan.app_packages import PACKAGES, prepare_options
from titan.catalog import compose, validate_options as recipe_options
from titan.core import Error, atomic_json
from titan.native_apps import check_requirements, prepare_tailscale_runtime, tailscale_runtime
from titan.package_center import PackageCenterMixin
from test_cloudflare_tunnel import TunnelHost

KEY = 'tskey-auth-deliberately-invalid-test-key-123456789'


class NativeHost(AppInstallationMixin, TunnelHost):
    _package_services = PackageCenterMixin._package_services
    _package_redact = PackageCenterMixin._package_redact

    def __init__(self, directory):
        super().__init__(directory)
        self.app_storage_ready = Mock()
        self.app_devices_ready = Mock()
        self._app_network_validate = Mock(return_value=({'mode': 'default'}, None))
        self._host_ports_available = Mock()
        self._app_container_rows = Mock(return_value=[])
        self._app_inspected_containers = Mock(return_value=[])
        self._app_private_config_label = Mock()
        self._app_firewall = Mock()
        self.telemetry = Mock()
        self.service_ready = True

    def _app_container(self, app, record, *args, **kwargs):
        return self.container

    def _app_container_summary(self, container, record):
        return {'state': container['State']['Status'], 'health': 'healthy' if self.service_ready else 'unhealthy', 'exit_code': 0}

    def op_package_details(self, app):
        services = self._package_services(app, self.managed_app(app))
        return {'services': services, 'primary_state': services[0]['state'], 'ready': all(row['ready'] for row in services)}

    def op_app_install(self, app, port, options, network, storage_id):
        self.actions.append(('install', app))
        control = self.directory / 'apps' / app
        config = self.storage_locations.path / app / 'config'
        config.parent.mkdir(mode=0o755)
        config.mkdir(mode=0o700)
        record = {'id': app, 'name': PACKAGES[app]['name'], 'network': network, 'storage_id': storage_id, 'config_path': str(config), 'port': port}
        atomic_json(control / 'options.json', recipe_options(app, prepare_options(app, options)))
        atomic_json(control / 'compose.json', compose(app, str(control), os.geteuid(), os.getegid(), port,
            str(config.parent / 'data'), self._app_options(app), network, config_path=str(config)))
        self.save('apps', [*self.load('apps', []), record])
        self.container = {'Id': 'a' * 64, 'State': {'Running': False, 'Status': 'created'}, 'HostConfig': {'NetworkMode': 'default'}}
        return AppMixin._docker(self, app, 'up', '-d')

    def op_app_action(self, app, action):
        self.actions.append((action, app))
        return AppMixin._docker(self, app, 'up', '-d') if action == 'start' else AppMixin._docker(self, app, action)


class RecipeTests(unittest.TestCase):
    def test_immich_has_all_matching_services_private_database_and_safe_8gib_budget(self):
        from titan.app_memory import package_memory_plan, check_install_memory, GIB
        options = recipe_options('titan-immich', prepare_options('titan-immich', {}))
        definition = compose('titan-immich', '/agent/immich', 1000, 1000, 2283, '/data/photos', options)
        services = definition['services']
        self.assertEqual(len(services), 4)
        self.assertIn(':v3.3.0@sha256:', services['titan-immich']['image'])
        self.assertIn(':v3.3.0@sha256:', services['titan-immich-immich-machine-learning']['image'])
        self.assertEqual(services['titan-immich-database']['mem_limit'], '2g')
        self.assertEqual(services['titan-immich-database']['environment']['POSTGRES_PASSWORD'], options['database_password'])
        self.assertTrue(all('@sha256:' in value['image'] for value in services.values()))
        self.assertTrue(all(not value['ports'] for name, value in services.items() if name != 'titan-immich'))
        self.assertEqual(package_memory_plan('titan-immich', options)['startup_limit_bytes'], int(6.25 * GIB))
        budget = check_install_memory('titan-immich', options, containers=[], vms=[], telemetry={'memory_total': 8 * GIB, 'memory_available': int(7.9 * GIB)})
        self.assertTrue(budget['allowed'])
        with self.assertRaises(Error):
            check_install_memory('titan-immich', options, containers=[], vms=[], telemetry={'memory_total': 8 * GIB, 'memory_available': int(7.5 * GIB)})

    def test_immich_rejects_unsupported_cpu_and_network_filesystem_before_writes(self):
        with patch('titan.native_apps.platform.machine', return_value='x86_64'), patch('titan.native_apps.Path.read_text', return_value='flags : sse2 pni\n'):
            with self.assertRaisesRegex(Error, 'x86-64-v2'): check_requirements('titan-immich')
        for filesystem in ('nfs', 'cifs', 'exfat'):
            with self.assertRaisesRegex(Error, 'lokalen Linux-Speicher'): check_requirements('titan-immich', {'filesystem': filesystem})

    def test_tailscale_explicit_private_nonoverlapping_routes_only(self):
        value = validate_options({'auth_key': KEY, 'subnet_routing': 'enabled', 'subnet_routes': '192.168.1.0/24, 10.12.0.0/16', 'nas_address': '192.168.1.10'}, 'titan-tailscale')
        self.assertEqual(value['subnet_routes'], '192.168.1.0/24,10.12.0.0/16')
        for routes in ('', '0.0.0.0/0', '::/0', '8.8.8.0/24', '127.0.0.0/8', '169.254.0.0/16', '192.168.1.1/24', '10.0.0.0/8,10.1.0.0/16', '192.168.1.0/24,192.168.1.0/24'):
            with self.subTest(routes=routes), self.assertRaises(Error):
                validate_options({'auth_key': KEY, 'subnet_routing': 'enabled', 'subnet_routes': routes}, 'titan-tailscale')
        with self.assertRaises(Error): validate_options({'auth_key': KEY, 'subnet_routes': '192.168.1.0/24'}, 'titan-tailscale')
        for address in ('8.8.8.8', '127.0.0.1', '0.0.0.0', 'host.local', '192.168.1.1;id'):
            with self.subTest(address=address), self.assertRaises(Error): validate_options({'auth_key': KEY, 'nas_address': address}, 'titan-tailscale')
        for key in ('tskey-api-1234567890', 'tailscale up --auth-key ' + KEY, KEY + '\n'):
            with self.assertRaises(Error): validate_options({'auth_key': key}, 'titan-tailscale')

    def test_tailscale_is_persistent_userspace_without_host_capabilities_or_auth_env(self):
        options = recipe_options('titan-tailscale', prepare_options('titan-tailscale', {'auth_key': KEY}))
        definition = compose('titan-tailscale', '/agent/tailscale', 1000, 1000, 0, '/data', options)
        service = definition['services']['titan-tailscale']
        self.assertNotIn(KEY, json.dumps(definition))
        self.assertEqual(service['environment']['TS_AUTHKEY'], 'file:/etc/titan-tailscale/authkey')
        self.assertEqual(service['environment']['TS_USERSPACE'], 'true')
        self.assertEqual(service['environment']['TS_ACCEPT_DNS'], 'false')
        self.assertEqual(service['environment']['TS_ROUTES'], '')
        self.assertNotIn('TS_DEST_IP', service['environment'])
        self.assertEqual(service['ports'], [])
        for key in ('privileged', 'cap_add', 'devices', 'network_mode'): self.assertNotIn(key, service)
        self.assertEqual({item['target'] for item in service['volumes']}, {'/var/lib/tailscale', '/etc/titan-tailscale'})
        self.assertTrue(next(item for item in service['volumes'] if item['target'] == '/etc/titan-tailscale')['read_only'])
        options['nas_address'] = '192.168.1.10'
        with_host = compose('titan-tailscale', '/agent/tailscale', 1000, 1000, 0, '/data', options)['services']['titan-tailscale']
        self.assertEqual(with_host['environment']['TS_ROUTES'], '192.168.1.10/32')
        self.assertNotIn('TS_DEST_IP', with_host['environment'])
        options.update(subnet_routing='enabled', subnet_routes='192.168.1.0/24')
        included = compose('titan-tailscale', '/agent/tailscale', 1000, 1000, 0, '/data', options)['services']['titan-tailscale']
        self.assertEqual(included['environment']['TS_ROUTES'], '192.168.1.0/24')

    def test_tailscale_healthy_container_without_control_connection_is_not_connected(self):
        container = {'Id': 'a' * 64, 'State': {'Running': True}}
        with patch('titan.host.run', return_value=json.dumps({'BackendState': 'NeedsLogin', 'TailscaleIPs': ['100.64.1.2'], 'Self': {'Online': False}})):
            self.assertFalse(tailscale_runtime(container)['connected'])
        with patch('titan.host.run', return_value=json.dumps({'BackendState': 'Running', 'TailscaleIPs': ['100.64.1.2'], 'Self': {'Online': True}, 'AuthURL': 'secret', 'Peer': {'private': 'hidden'}})):
            result = tailscale_runtime(container)
            self.assertTrue(result['connected'])
            self.assertEqual(result['routes_approval'], 'not_verified')
            self.assertNotIn('secret', json.dumps(result))
            self.assertNotIn('Peer', result)


class NativeJournalTests(unittest.TestCase):
    def test_all_removed_services_keep_configuration_but_are_not_installed(self):
        self.install('titan-immich')
        options = self.host._app_options('titan-immich')
        self.host.container = None
        current = self.status('titan-immich')
        self.assertTrue(current['configured'])
        self.assertFalse(current['installed'])
        self.assertEqual(current['runtime']['state'], 'missing')
        self.assertTrue(all(row['state'] == 'missing' for row in current['runtime']['services']))
        self.assertEqual(self.host._app_options('titan-immich'), options)

    def test_missing_primary_with_existing_peer_and_unknown_docker_state_stay_registered(self):
        self.install('titan-immich')
        with patch.object(self.host, 'op_package_details', return_value={
                'primary_state': 'missing', 'ready': False, 'services': [
                    {'id': 'titan-immich', 'state': 'missing'},
                    {'id': 'titan-immich-database', 'state': 'exited'}]}):
            self.assertTrue(self.status('titan-immich')['installed'])
        with patch.object(self.host, 'op_package_details', side_effect=Error('Docker unavailable')):
            current = self.status('titan-immich')
        self.assertTrue(current['installed'])
        self.assertEqual(current['runtime']['state'], 'blocked')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.host = NativeHost(temporary.name)
        self.calls = []
        self.fail = ''
        self.enterContext(patch('titan.app_memory.check_start_memory'))
        self.enterContext(patch('titan.native_apps.check_requirements'))
        self.enterContext(patch('titan.host.run', return_value=json.dumps({'BackendState': 'Running', 'TailscaleIPs': ['100.64.1.2'], 'Self': {'Online': True}})))
        self.enterContext(patch('titan.app_management._run', side_effect=self.command))

    def command(self, argv, **kwargs):
        command = argv[6]
        app = json.loads(Path(argv[5]).read_text())['services'].keys().__iter__().__next__()
        journal = self.host._installation_read(app)
        self.calls.append((command, copy.deepcopy(journal)))
        if command == self.fail: raise Error('download failed ' + KEY)
        if command in ('up', 'start'): self.host.container['State'].update(Running=True, Status='running')
        if command == 'stop': self.host.container['State'].update(Running=False, Status='exited')
        return ''

    def status(self, app):
        return self.host.op_app_install_status(app)

    def install(self, app, options=None):
        return self.host.op_app_install_run(app, options or {}, self.status(app)['revision'])

    def test_all_steps_follow_real_commands_and_all_required_service_checks(self):
        for app in ('titan-immich', 'titan-adguard', 'titan-tailscale'):
            with self.subTest(app=app):
                self.calls.clear()
                result = self.install(app, {'auth_key': KEY} if app == 'titan-tailscale' else {})
                self.assertEqual(result['status'], 'completed')
                self.assertEqual([row[0] for row in self.calls], ['config', 'pull', 'create', 'up'])
                self.assertEqual([row['id'] for row in result['steps']], [key for key, _ in NATIVE_STEPS])
                self.assertTrue(all(row['status'] == 'completed' for row in result['steps']))
                self.assertTrue(result['runtime']['ready'])
                self.assertEqual(len(result['runtime']['services']), 4 if app == 'titan-immich' else 1)
                for command, journal in self.calls:
                    if command in ('pull', 'create', 'up'):
                        self.assertEqual(next(row for row in journal['steps'] if row['id'] == ('start' if command == 'up' else command))['status'], 'running')
                self.assertNotIn(KEY, json.dumps(result))
                self.assertFalse(self.host._installation_path(app, private=True).exists())

    def test_failed_pull_resumes_existing_definition_and_generated_database_password(self):
        app = 'titan-immich'
        self.fail = 'pull'
        with self.assertRaises(Error): self.install(app)
        before = self.host._app_options(app)['database_password']
        failed = self.status(app)
        self.assertTrue(failed['resumable'])
        self.assertEqual(next(row for row in failed['steps'] if row['id'] == 'pull')['status'], 'failed')
        private = self.host._installation_path(app, private=True)
        self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o600)
        self.fail = ''
        result = self.host.op_app_install_resume(app, failed['revision'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.host._app_options(app)['database_password'], before)
        self.assertEqual(sum(row == ('install', app) for row in self.host.actions), 1)
        self.assertFalse(private.exists())

    def test_unhealthy_stack_cannot_complete_installation_and_saved_status_remains_historical(self):
        self.host.service_ready = False
        with self.assertRaises(Error): self.install('titan-adguard')
        failed = self.status('titan-adguard')
        self.assertEqual(failed['status'], 'failed')
        self.assertFalse(failed['runtime']['ready'])
        self.assertEqual(next(row for row in failed['steps'] if row['id'] == 'health')['status'], 'failed')
        self.host.service_ready = True
        completed = self.host.op_app_install_resume('titan-adguard', failed['revision'])
        self.assertTrue(completed['runtime']['ready'])
        self.host.service_ready = False
        current = self.status('titan-adguard')
        self.assertEqual(current['status'], 'completed')
        self.assertFalse(current['runtime']['ready'])

    def test_auth_key_is_private_atomic_and_never_in_error_journal_compose_or_command(self):
        self.fail = 'pull'
        with self.assertRaises(Error) as error: self.install('titan-tailscale', {'auth_key': KEY})
        self.assertNotIn(KEY, str(error.exception))
        self.assertNotIn(KEY, self.host._installation_path('titan-tailscale').read_text())
        config = Path(self.host.managed_app('titan-tailscale')['config_path'])
        keyfile = config / 'credentials' / 'authkey'
        self.assertEqual(keyfile.read_text(), KEY)
        self.assertEqual(stat.S_IMODE(keyfile.stat().st_mode), 0o600)
        self.assertNotIn(KEY, (self.host.directory / 'apps/titan-tailscale/compose.json').read_text())
        outside = config / 'outside'
        outside.write_text('keep')
        keyfile.unlink()
        keyfile.symlink_to(outside)
        with self.assertRaises(Error): prepare_tailscale_runtime(self.host, self.host.managed_app('titan-tailscale'))
        self.assertEqual(outside.read_text(), 'keep')

    def test_resume_rejects_changed_saved_options_and_stale_revision_without_reinstall(self):
        self.fail = 'pull'
        with self.assertRaises(Error): self.install('titan-adguard')
        before = self.status('titan-adguard')
        path = self.host.directory / 'apps/titan-adguard/options.json'
        saved = json.loads(path.read_text())
        saved['stack_port_adguard_53_tcp'] = 1053
        atomic_json(path, saved)
        self.fail = ''
        with self.assertRaises(Error): self.host.op_app_install_resume('titan-adguard', before['revision'])
        self.assertEqual(sum(row == ('install', 'titan-adguard') for row in self.host.actions), 1)
        with self.assertRaisesRegex(Error, 'geändert'): self.host.op_app_install_resume('titan-adguard', before['revision'])

    def test_failed_tailscale_auth_can_explicitly_replace_only_key_without_reinstalling(self):
        self.fail = 'pull'
        with self.assertRaises(Error): self.install('titan-tailscale', {'auth_key': KEY, 'hostname': 'private-nas'})
        failed = self.status('titan-tailscale')
        self.assertEqual(failed['configuration']['hostname'], 'private-nas')
        self.assertNotIn('auth_key', failed['configuration'])
        self.fail = ''
        replacement = 'tskey-auth-new-invalid-test-key-123456789'
        result = self.host.op_app_install_run('titan-tailscale', {'auth_key': replacement, 'hostname': 'private-nas'}, failed['revision'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.host._app_options('titan-tailscale')['auth_key'], replacement)
        self.assertEqual(sum(row == ('install', 'titan-tailscale') for row in self.host.actions), 1)
        self.assertIn(('stop', 'titan-tailscale'), self.host.actions)
        self.assertNotIn(replacement, json.dumps(result))


if __name__ == '__main__':
    unittest.main()

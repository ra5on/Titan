"""Native Compose jobs report real commands and safely resume private inputs."""
import copy
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from titan.app_installation import AppInstallationMixin, STEPS
from titan.app_management import AppMixin
from titan.cloudflare_tunnel import CONNECTOR
from titan.core import Error, atomic_json, job_resources
from titan.host import Host
from test_cloudflare_tunnel import TunnelHost, token


class InstallerHost(AppInstallationMixin, TunnelHost):
    """Use the real Compose command path with an isolated Docker transport."""
    def __init__(self, directory):
        super().__init__(directory)
        self.app_storage_ready = Mock()
        self.app_devices_ready = Mock()
        self._app_network_validate = Mock(return_value=({'mode': 'host'}, None))
        self._host_ports_available = Mock()
        self._app_container_rows = Mock(return_value=[])
        self._app_inspected_containers = Mock(return_value=[])
        self._app_private_config_label = Mock()
        self._app_firewall = Mock()
        self.telemetry = Mock()

    def op_app_install(self, *args, **kwargs):
        super().op_app_install(*args, **kwargs)
        self.container['State'].update(Running=False, Status='created')
        return AppMixin._docker(self, CONNECTOR, 'up', '-d')

    def op_app_action(self, app, action):
        if action in ('start', 'restart'):
            self.actions.append((action, app))
            return AppMixin._docker(self, app, 'up' if action == 'start' else 'restart')
        return super().op_app_action(app, action)


class NativeInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.host = InstallerHost(self.temp.name)
        self.credential = token()
        self.calls = []
        self.fail_pull = False
        self.crash_pull = False
        self.ready = self.enterContext(patch('titan.cloudflare_tunnel.connector_ready', return_value=True))
        self.enterContext(patch('titan.host.run', return_value=''))
        self.enterContext(patch('titan.app_memory.check_start_memory'))
        self.transport = self.enterContext(patch('titan.app_management._run', side_effect=self.command))

    def command(self, argv, **kwargs):
        command = argv[6]
        journal = self.host._installation_read(CONNECTOR)
        self.calls.append((command, copy.deepcopy(journal)))
        if command == 'pull':
            if self.crash_pull:
                raise SystemExit('simulated agent termination')
            if self.fail_pull:
                raise Error('upstream private ' + self.credential)
        if command in ('up', 'start', 'restart'):
            self.host.container['State'].update(Running=True, Status='running')
        return ''

    def status(self):
        return self.host.op_app_install_status(CONNECTOR)

    def install(self, address=''):
        return self.host.op_app_install_run(CONNECTOR, {'tunnel_token': self.credential, 'public_origin': address}, self.status()['revision'])

    def test_steps_complete_only_after_real_compose_commands_and_actual_cloudflare_ready(self):
        result = self.install()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([row[0] for row in self.calls], ['config', 'pull', 'create', 'up'])
        for command, journal in self.calls:
            if command in ('pull', 'create', 'up'):
                step = 'start' if command == 'up' else command
                self.assertEqual(next(row['status'] for row in journal['steps'] if row['id'] == step), 'running')
        steps = {row['id']: row for row in result['steps']}
        for key in ('docker', 'files', 'pull', 'create', 'start', 'connection'):
            self.assertEqual(steps[key]['status'], 'completed')
            self.assertIsNotNone(steps[key]['finished_at'])
        self.assertEqual(steps['proxy']['status'], 'pending')
        self.assertEqual(steps['public_check']['status'], 'pending')
        self.assertTrue(result['runtime']['cloudflare_connected'])
        self.assertFalse(result['runtime']['public_ready'])
        self.assertTrue(result['setup']['needs_domain'])
        self.assertFalse(result['resumable'])
        self.assertFalse(self.host._installation_path(CONNECTOR, private=True).exists())
        self.assertNotIn(self.credential, json.dumps(result))
        self.assertNotIn(self.credential, self.host._installation_path(CONNECTOR).read_text())

    def test_public_proxy_steps_finish_after_activation_and_proof_not_merely_container_start(self):
        result = self.install('https://nas.example.com')
        self.assertTrue(result['runtime']['public_ready'])
        self.assertTrue(all(row['status'] == 'completed' for row in result['steps']))
        self.assertEqual(result['setup']['phase'], 'ready')
        self.ready.return_value = False
        current = self.status()
        self.assertEqual(current['status'], 'completed')  # Historical operation.
        self.assertFalse(current['runtime']['cloudflare_connected'])
        self.assertFalse(current['runtime']['public_ready'])
        self.assertEqual(current['setup']['phase'], 'disconnected')

    def test_external_container_removal_reports_configuration_only_without_deleting_secrets(self):
        self.install()
        path = self.host.directory / 'apps' / CONNECTOR / 'options.json'
        before = path.read_bytes()
        self.host.container = None
        current = self.status()
        self.assertFalse(current['installed'])
        self.assertTrue(current['configured'])
        self.assertEqual(current['runtime']['state'], 'missing')
        self.assertEqual(current['status'], 'completed')  # Keep the historical journal.
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self.host.load('apps', [])), 1)
        self.assertNotIn(self.credential, json.dumps(current))

    def test_stopped_container_and_docker_error_do_not_become_an_uninstall(self):
        self.install()
        self.host.container['State'].update(Running=False, Status='exited')
        self.assertTrue(self.status()['installed'])
        self.assertEqual(self.status()['runtime']['state'], 'stopped')
        with patch.object(self.host, '_app_container', side_effect=Error('Docker unavailable')):
            current = self.status()
        self.assertTrue(current['installed'])
        self.assertTrue(current['configured'])
        self.assertEqual(current['runtime']['state'], 'blocked')

    def test_running_container_without_cloudflare_connection_is_failed_and_never_ready(self):
        self.ready.return_value = False
        with patch('titan.remote_access.time.monotonic', side_effect=[0, 30]), self.assertRaises(Error):
            self.install()
        value = self.status()
        self.assertEqual(value['status'], 'failed')
        self.assertEqual(next(row['status'] for row in value['steps'] if row['id'] == 'connection'), 'failed')
        self.assertFalse(value['runtime']['cloudflare_connected'])
        self.assertFalse(value['runtime']['public_ready'])
        self.assertEqual(value['runtime']['state'], 'stopped')

    def test_package_details_do_not_claim_ready_for_an_unconnected_running_cloudflare_container(self):
        from titan.package_center import PackageCenterMixin
        self.install()
        self.host._app_container = Mock(return_value=self.host.container)
        self.host._app_container_summary = Mock(return_value={'state': 'running', 'health': '', 'exit_code': 0})
        self.ready.return_value = False
        services = PackageCenterMixin._package_services(self.host, CONNECTOR, self.host.managed_app(CONNECTOR), [])
        self.assertFalse(services[0]['ready'])
        self.assertIn('Cloudflare-Verbindung', services[0]['warning'])
        self.ready.return_value = True
        services = PackageCenterMixin._package_services(self.host, CONNECTOR, self.host.managed_app(CONNECTOR), [])
        self.assertTrue(services[0]['ready'])

    def test_pull_failure_keeps_private_resume_inputs_without_secret_in_public_journal(self):
        self.fail_pull = True
        with self.assertRaises(Error) as error:
            self.install()
        self.assertNotIn(self.credential, str(error.exception))
        value = self.status()
        self.assertEqual(value['status'], 'failed')
        self.assertTrue(value['resumable'])
        self.assertEqual(next(row['status'] for row in value['steps'] if row['id'] == 'pull'), 'failed')
        self.assertNotIn(self.credential, json.dumps(value))
        self.assertNotIn(self.credential, self.host._installation_path(CONNECTOR).read_text())
        private = self.host._installation_path(CONNECTOR, private=True)
        self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o600)
        self.assertEqual(private.stat().st_uid, os.geteuid())
        self.assertIn(self.credential, private.read_text())
        self.fail_pull = False
        self.calls.clear()
        result = self.host.op_app_install_resume(CONNECTOR, value['revision'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(self.host.load('apps', [])), 1)
        self.assertEqual(sum(action[0] == 'install' for action in self.host.actions), 1)
        self.assertEqual([row[0] for row in self.calls], ['config', 'pull', 'create', 'up'])
        self.assertFalse(private.exists())

    def test_daemon_termination_marks_interrupted_and_resume_rechecks_completed_steps(self):
        self.crash_pull = True
        with self.assertRaises(SystemExit):
            self.install()
        saved = self.host._installation_read(CONNECTOR)
        self.assertEqual(saved['status'], 'running')
        value = self.status()
        self.assertEqual(value['status'], 'interrupted')
        self.assertTrue(value['resumable'])
        self.assertEqual(next(row['status'] for row in value['steps'] if row['id'] == 'pull'), 'failed')
        self.crash_pull = False
        self.calls.clear()
        result = self.host.op_app_install_resume(CONNECTOR, value['revision'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([row[0] for row in self.calls], ['config', 'pull', 'create', 'up'])

    def test_status_stays_available_during_slow_image_pull_and_duplicate_or_stale_job_is_rejected(self):
        entered, release = threading.Event(), threading.Event()
        failures = []
        command = self.command
        def slow(argv, **kwargs):
            if argv[6] == 'pull':
                entered.set()
                self.assertTrue(release.wait(3))
            return command(argv, **kwargs)
        self.transport.side_effect = slow
        original_revision = self.status()['revision']
        def execute():
            try:
                self.host.op_app_install_run(CONNECTOR, {'tunnel_token': self.credential}, original_revision)
            except Exception as error:
                failures.append(error)
        thread = threading.Thread(target=execute, daemon=True)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            value = self.status()
            self.assertEqual(value['status'], 'running')
            self.assertEqual(value['current_step'], 'pull')
            # Status is atomic-file based and does not acquire the slow app lock.
            self.assertFalse(value['resumable'])
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(failures)
        with self.assertRaisesRegex(Error, 'geändert'):
            self.host.op_app_install_run(CONNECTOR, {'tunnel_token': self.credential}, original_revision)

    def test_private_resume_symlinks_hardlinks_and_public_permissions_fail_closed(self):
        self.fail_pull = True
        with self.assertRaises(Error):
            self.install()
        private = self.host._installation_path(CONNECTOR, private=True)
        original = private.read_bytes()
        external = self.host.directory / 'outside.json'
        external.write_bytes(original)
        external.chmod(0o600)
        for mode in ('symlink', 'hardlink', 'public'):
            private.unlink()
            if mode == 'symlink': private.symlink_to(external)
            elif mode == 'hardlink': os.link(external, private)
            else: private.write_bytes(original); private.chmod(0o644)
            self.assertFalse(self.status()['resumable'])
            with self.assertRaisesRegex(Error, 'Private'):
                self.host.op_app_install_resume(CONNECTOR, self.status()['revision'])
            self.assertEqual(external.read_bytes(), original)

    def test_address_job_uses_same_journal_and_preserves_token_and_completed_install_steps(self):
        previous = self.install()
        private = Path(self.host.managed_app(CONNECTOR)['config_path']) / 'credentials' / 'token'
        before = private.read_bytes()
        commands = copy.deepcopy(self.calls)
        result = self.host.op_app_install_address(CONNECTOR, 'https://nas.example.com', previous['revision'])
        self.assertEqual(result['operation'], 'address')
        self.assertTrue(result['runtime']['public_ready'])
        self.assertTrue(all(row['status'] == 'completed' for row in result['steps']))
        self.assertEqual(result['steps'][:6], previous['steps'][:6])
        self.assertEqual(private.read_bytes(), before)
        self.assertEqual(self.calls, commands)

    def test_stale_webconfig_invalidates_revision_and_unapproved_apps_never_create_files(self):
        status = self.status()
        config = self.host.web_access.config()
        config['revision'] = 'changed-web-address'
        atomic_json(self.host.web_access.path, config, mode=0o644)
        with self.assertRaisesRegex(Error, 'geändert'):
            self.host.op_app_install_run(CONNECTOR, {'tunnel_token': self.credential}, status['revision'])
        for app in ('heimdall', 'bigbear:cloudflared-web', '../../outside'):
            with self.assertRaises(Error):
                self.host.op_app_install_run(app, {'tunnel_token': self.credential}, status['revision'])
        self.assertFalse((self.host.directory / 'app-installations').exists())

    def test_docker_failure_before_app_creation_can_resume_from_protected_inputs(self):
        self.host.component = {'available': False}
        self.host.op_component_install = Mock(side_effect=Error('untrusted ' + self.credential))
        with self.assertRaises(Error):
            self.install()
        value = self.status()
        self.assertFalse(value['installed'])
        self.assertTrue(value['resumable'])
        self.assertEqual(next(row['status'] for row in value['steps'] if row['id'] == 'docker'), 'failed')
        self.assertNotIn(self.credential, json.dumps(value))
        self.host.component = {'available': True}
        self.assertEqual(self.host.op_app_install_resume(CONNECTOR, value['revision'])['status'], 'completed')

    def test_corrupt_or_symlinked_journal_and_unprotected_directory_are_rejected(self):
        path = self.host._installation_path(CONNECTOR)
        path.parent.mkdir(mode=0o700)
        path.write_text('{broken')
        with self.assertRaisesRegex(Error, 'beschädigt'):
            self.status()
        external = self.host.directory / 'outside'
        external.write_text('{}')
        path.unlink()
        path.symlink_to(external)
        with self.assertRaises(Error):
            self.status()
        path.unlink()
        path.parent.chmod(0o777)
        with self.assertRaisesRegex(Error, 'nicht geschützt'):
            self.status()

    def test_address_late_proxy_failure_records_failed_step_without_changing_runner_token_or_lan(self):
        previous = self.install()
        before_remote = self.host.web_access.config().get('remote')
        private = Path(self.host.managed_app(CONNECTOR)['config_path']) / 'credentials' / 'token'
        before_token = private.read_bytes()
        self.host.fail_proxy = True
        with self.assertRaises(Error):
            self.host.op_app_install_address(CONNECTOR, 'https://nas.example.com', previous['revision'])
        value = self.status()
        self.assertEqual(value['status'], 'failed')
        self.assertEqual(next(row['status'] for row in value['steps'] if row['id'] == 'proxy'), 'failed')
        self.assertTrue(value['resumable'])
        self.assertEqual(self.host.web_access.config().get('remote'), before_remote)
        self.assertEqual(private.read_bytes(), before_token)
        self.assertTrue(self.host.container['State']['Running'])
        value = self.host.op_app_install_resume(CONNECTOR, value['revision'])
        self.assertEqual(value['status'], 'completed')
        self.assertTrue(value['runtime']['public_ready'])

    def test_root_rpc_whitelist_does_not_trust_recipe_flags_or_snapshots(self):
        host = Host(self.host.directory / 'rpc', self.host.directory / 'shares', self.host.directory / 'vms', self.host.directory / 'samba.conf')
        host.op_app_install = Mock(return_value={'ok': True})
        with self.assertRaises(Error) as error:
            host.dispatch('app_install', app='heimdall', port=8080)
        self.assertEqual(error.exception.status, 403)
        host.op_app_install.assert_not_called()
        host._ci_fixture_ids = {'heimdall'}
        self.assertTrue(host.dispatch('app_install', app='heimdall', port=8080)['ok'])
        host.op_app_install.reset_mock()
        # CI authorization opens the legacy smoke engine only, never the
        # production native API or a secret-bearing resume journal.
        with self.assertRaises(Error) as error:
            host.dispatch('app_install_run', app='heimdall', options={'tunnel_token': self.credential}, expected_revision='initial')
        self.assertEqual(error.exception.status, 404)
        host.op_app_install.assert_not_called()
        self.assertFalse((host.directory / 'app-installations').exists())
        self.assertEqual(job_resources('app_install_resume', {'app': CONNECTOR}), ('app:' + CONNECTOR,))


if __name__ == '__main__':
    unittest.main()

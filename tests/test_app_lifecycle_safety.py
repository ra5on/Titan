"""Realistic Docker inspect layouts and per-object mutation coordination."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from titan.core import Error, Jobs, Store, job_resources
from titan.host import Host
from titan.package_center import definition_digest
from titan.app_memory import limit_bytes
import test_app_management as fixture


class AppLifecycleSafetyTests(unittest.TestCase):
    setUp = fixture.AppManagementTests.setUp
    tearDown = fixture.AppManagementTests.tearDown
    command = fixture.AppManagementTests.command
    make_container = fixture.AppManagementTests.make_container
    install = fixture.AppManagementTests.install
    compose_commands = fixture.AppManagementTests.compose_commands

    def member(self, app, key, state='running'):
        definition = json.loads((self.host.directory / 'apps' / app / 'compose.json').read_text())['services'][key]
        publications = {}
        for value in definition.get('ports', []):
            published, target = value.split(':')
            target = target if '/' in target else target + '/tcp'
            publications[target] = [{'HostIp': '', 'HostPort': published}]
        value = {'Id': hashlib.sha256(key.encode()).hexdigest(), 'Name': '/titan-' + key,
            'Image': 'sha256:' + hashlib.sha256(definition['image'].encode()).hexdigest(),
            'Config': {'Image': definition['image'], 'Labels': {**definition['labels'],
                'com.docker.compose.project': 'titan-' + app, 'com.docker.compose.service': key}},
            'Mounts': [{'Type': 'bind', 'Source': entry['source'], 'Destination': entry['target']} for entry in definition['volumes']],
            'HostConfig': {'Memory':limit_bytes(definition['mem_limit']), 'NetworkMode': 'titan-' + app + '_default', 'PortBindings': publications},
            'NetworkSettings': {'Networks': {'titan-' + app + '_default': {}}},
            'State': {'Status': state, 'Running': state == 'running', 'ExitCode': 0, 'Health': {'Status': 'healthy'}}}
        self.containers[key] = value
        return value

    def legacy_redis(self):
        self.host.op_app_install('titan-nextcloud-office', 18088,
            options={'username': 'admin', 'password': 'PrivatePassword123', 'nas_host': 'nas.local', 'office_mode': 'disabled'})
        app = 'titan-nextcloud-office'
        path = self.host.directory / 'apps' / app / 'compose.json'
        definition = json.loads(path.read_text())
        definition['services'][app + '-redis']['volumes'] = []
        path.write_text(json.dumps(definition))
        self.host._app_patch_record(app, {'definition_digest': definition_digest(definition)})
        redis = self.member(app, app + '-redis')
        volume = 'b' * 64
        redis['Mounts'].append({'Type': 'volume', 'Name': volume, 'Driver': 'local',
            'Source': '/var/lib/docker/volumes/' + volume + '/_data', 'Destination': '/data'})
        base = self.command
        def run(args, **kwargs):
            if args[:4] == ['docker', 'inspect', '--type', 'image']:
                self.calls.append(args)
                return json.dumps([{'Id': redis['Image'], 'Config': {'Volumes': {'/data': {}}}}])
            if args[:3] == ['docker', 'volume', 'inspect']:
                self.calls.append(args)
                return json.dumps([{'Name': volume, 'Driver': 'local', 'Options': None,
                    'Mountpoint': redis['Mounts'][-1]['Source']}])
            return base(args, **kwargs)
        self.runner.side_effect = run
        return app, redis, run

    def test_old_image_declared_anonymous_redis_volume_is_accepted_and_primary_stays_available(self):
        app, redis, _ = self.legacy_redis()
        self.assertEqual(self.host._app_container(app, self.host.managed_app(app), service_key=app + '-redis')['Id'], redis['Id'])
        record = self.host.op_apps()['installed'][0]
        self.assertEqual(record['state'], 'running')
        self.assertTrue(record['web_available'])
        self.assertTrue(next(row for row in record['services'] if row['id'] == app + '-redis')['ready'])

    def test_foreign_anonymous_volume_or_host_bind_cannot_pass_start_guards(self):
        app, redis, run = self.legacy_redis()
        for change in ({'Destination': '/unexpected'}, {'Type': 'bind'}, {'Name': 'user-data'}, {'Driver': 'remote'}):
            original = dict(redis['Mounts'][-1]); redis['Mounts'][-1].update(change)
            with self.assertRaises(Error):
                self.host._app_container(app, self.host.managed_app(app), service_key=app + '-redis')
            redis['Mounts'][-1] = original
        def unsafe(args, **kwargs):
            if args[:3] == ['docker', 'volume', 'inspect']:
                return json.dumps([{'Name': 'b' * 64, 'Driver': 'local', 'Options': {'device': '/etc', 'o': 'bind'},
                    'Mountpoint': redis['Mounts'][-1]['Source']}])
            return run(args, **kwargs)
        self.runner.side_effect = unsafe
        with self.assertRaises(Error): self.host.op_app_action(app, 'start')

    def test_degraded_dependency_keeps_primary_link_but_can_be_stopped_and_uninstalled_safely(self):
        app, redis, _ = self.legacy_redis()
        redis['HostConfig']['Privileged'] = True
        record = self.host.op_apps()['installed'][0]
        self.assertEqual(record['state'], 'running'); self.assertTrue(record['web_available'])
        self.assertFalse(record['package_ready']); self.assertTrue(record['warnings'])
        with self.assertRaises(Error): self.host.op_app_action(app, 'start')
        marker = Path(record['data']) / 'keep.txt'; marker.write_text('keep')
        config = self.host.directory / 'apps' / app / 'options.json'
        before = config.read_bytes()
        self.host.dispatch('app_action', app=app, action='stop')
        self.assertFalse(any(self.host._app_container_active(row) for row in self.containers.values()))
        result = self.host.dispatch('app_action', app=app, action='remove')
        self.assertEqual(result['scope'], 'package'); self.assertEqual(result['state'], 'removed')
        self.assertTrue(result['data_retained']); self.assertEqual(marker.read_text(), 'keep')
        self.assertEqual(config.read_bytes(), before)
        self.assertFalse(any('-v' in call or '--volumes' in call or '--force' in call for call in self.calls))

    def test_package_stop_does_not_operate_foreign_peer_and_does_not_claim_success_if_still_running(self):
        self.install()
        row = self.containers['jellyfin']
        del row['Config']['Labels']['com.docker.compose.project']
        with self.assertRaises(Error): self.host.op_app_action('jellyfin', 'stop')
        self.assertFalse(any(call[:2] == ['docker', 'stop'] for call in self.calls))
        self.make_container()
        def stuck(args, **kwargs):
            if args[:2] == ['docker', 'stop']: return 'accepted'
            return self.command(args, **kwargs)
        self.runner.side_effect = stuck
        with self.assertRaisesRegex(Error, 'noch aktiv'): self.host.op_app_action('jellyfin', 'remove')
        self.assertFalse(any(call[:2] == ['docker', 'rm'] for call in self.calls))

    def test_changed_or_unlimited_managed_memory_rejects_start_but_owned_stop_is_available(self):
        self.install()
        row = self.containers['jellyfin']
        for memory in (0, 1, None, '2147483648', True):
            row['HostConfig']['Memory'] = memory
            with self.assertRaisesRegex(Error, 'RAM-Limit'):
                self.host.op_app_action('jellyfin', 'start')
        result = self.host.op_app_action('jellyfin', 'stop')
        self.assertEqual(result['state'], 'stopped')

    def test_real_manual_start_and_create_budget_blocks_overcommit_on_eight_gib_host(self):
        from titan.app_memory import GIB
        self.install()
        self.containers['jellyfin']['HostConfig']['Memory'] = 6 * GIB
        target = {'Id':'b'*64, 'Name':'/titan-custom-worker', 'Config':{'Labels':{'io.titan.manual':'true'}},
            'State':{'Running':False,'Status':'exited'}, 'HostConfig':{'Memory':2*GIB}}
        self.containers['manual'] = target
        self.calls.clear()
        with patch('titan.app_memory.memory_snapshot', return_value={'memory_total':8*GIB,'memory_available':7*GIB}), \
                patch('titan.app_memory.vm_memory_reservations', return_value=[]):
            with self.assertRaisesRegex(Error, 'passen momentan nicht sicher'):
                self.host.dispatch('docker_container_action', container=target['Id'], action='start')
            with self.assertRaisesRegex(Error, 'passen momentan nicht sicher'):
                self.host.dispatch('docker_container_create', config={'name':'worker-new','image':'nginx:stable','memory_mb':2048})
            self.assertEqual(self.host.dispatch('docker_container_action', container=target['Id'], action='stop')['state'],'exited')
        self.assertFalse(any(call[:2] in (['docker','create'],['docker','start']) for call in self.calls))

    def test_patch_record_merges_against_fresh_list(self):
        self.host.save('apps', [{'id': 'first', 'phase': 'installing'}, {'id': 'second', 'phase': 'installing'}])
        self.host._app_patch_record('first', {'phase': 'ready'})
        self.host._app_patch_record('second', {'phase': 'failed'})
        self.assertEqual({row['id']: row['phase'] for row in self.host.load('apps', [])}, {'first': 'ready', 'second': 'failed'})

    def test_segmented_private_networks_preserve_each_services_exact_topology(self):
        app, redis, _ = self.legacy_redis()
        path = self.host.directory / 'apps' / app / 'compose.json'
        definition = json.loads(path.read_text())
        definition['networks'] = {'front': {'driver': 'bridge'}, 'back': {'driver': 'bridge', 'internal': True}}
        definition['services'][app]['networks'] = {'front': {}, 'back': {}}
        definition['services'][app + '-redis']['networks'] = {'back': {}}
        path.write_text(json.dumps(definition))
        self.host._app_patch_record(app, {'definition_digest': definition_digest(definition)})
        front, back = 'titan-' + app + '_front', 'titan-' + app + '_back'
        primary = self.containers[app]
        primary['HostConfig']['NetworkMode'] = front
        primary['NetworkSettings']['Networks'] = {front: {'NetworkID': 'f' * 64}, back: {'NetworkID': 'b' * 64}}
        redis['HostConfig']['NetworkMode'] = back
        redis['NetworkSettings']['Networks'] = {back: {'NetworkID': 'b' * 64}}
        record = self.host.managed_app(app)
        self.assertEqual(self.host._app_container(app, record)['Id'], primary['Id'])
        self.assertEqual(self.host._app_container(app, record, service_key=app + '-redis')['Id'], redis['Id'])
        # Both expected attachments may be the primary Engine network.
        primary['HostConfig']['NetworkMode'] = back
        self.assertIsNotNone(self.host._app_container(app, record))
        with patch.object(self.host, '_docker_network', return_value={'Id': 'b' * 64}) as inspect:
            primary['HostConfig']['NetworkMode'] = 'b' * 64
            self.assertIsNotNone(self.host._app_container(app, record))
            inspect.assert_called_once_with(back)
        with patch.object(self.host, '_docker_network', return_value={'Id': 'c' * 64}):
            with self.assertRaises(Error): self.host._app_container(app, record)
        primary['HostConfig']['NetworkMode'] = front
        for attached in ({front: {}}, {front: {}, back: {}, 'foreign': {}}, {}):
            primary['NetworkSettings']['Networks'] = attached
            with self.assertRaises(Error): self.host._app_container(app, record)
        primary['NetworkSettings']['Networks'] = {front: {}, back: {}}
        primary['HostConfig']['NetworkMode'] = 'foreign'
        with self.assertRaises(Error): self.host._app_container(app, record)

    def test_app_details_and_saved_failure_never_expose_private_passwords(self):
        app, _, _ = self.legacy_redis()
        secret = self.host._app_options(app)['password']
        self.logs.return_value = 'public log; password=' + secret
        self.containers[app]['State']['Error'] = 'backend rejected ' + secret
        self.host._app_patch_record(app, {'last_error': 'old failure ' + secret})
        details = self.host.op_app_details(app)
        self.assertNotIn(secret, json.dumps(details))
        self.assertIn('[ausgeblendet]', details['logs'])
        self.assertNotIn(secret, json.dumps(self.host.op_apps()))
        self.assertNotIn(secret, json.dumps(self.host.op_package_details(app)))
        self.logs.side_effect = Error('failed reading ' + secret)
        self.assertNotIn(secret, json.dumps(self.host.op_app_details(app)))
        self.host._app_record_result(app, Error('pull failed ' + secret))
        self.assertNotIn(secret, self.host.load('apps', [])[0]['last_error'])

    def test_single_dependency_stop_remove_keeps_primary_running_and_package_registered(self):
        app, redis, _ = self.legacy_redis()
        primary = self.containers[app]['Id']
        result = self.host.dispatch('docker_container_action', container=redis['Id'], action='stop')
        self.assertEqual(result['scope'], 'container'); self.assertEqual(result['state'], 'exited')
        self.assertEqual(self.containers[app]['State']['Status'], 'running')
        result = self.host.dispatch('docker_container_action', container=redis['Id'], action='remove')
        self.assertEqual(result['state'], 'removed')
        self.assertEqual([item['id'] for item in self.host.load('apps', [])], [app])
        self.assertEqual(self.containers[app]['Id'], primary)
        self.assertFalse(self.host.op_apps()['installed'][0]['package_ready'])

    def test_explicit_stop_and_remove_is_graceful_and_retains_data(self):
        self.install()
        row = self.containers['jellyfin']; value = row['Id']
        with self.assertRaises(Error): self.host.op_docker_container_action(value, 'remove')
        result = self.host.op_docker_container_action(value, 'remove', stop_before_remove=True)
        self.assertTrue(result['data_retained']); self.assertEqual(result['state'], 'removed')
        self.assertTrue((self.host.directory / 'apps/jellyfin/options.json').is_file())
        self.assertFalse(any('--force' in call or '-v' in call for call in self.calls))

    def test_removing_last_cloudflare_container_unregisters_only_that_app_and_retains_files(self):
        from test_cloudflare_tunnel import token
        from titan.core import atomic_json
        app = 'titan-cloudflared'
        self.install()
        # The production agent is root; this fixture runs as the developer.
        # Only root ownership changes during recipe preparation are simulated.
        with patch('titan.app_management.os.fchown'):
            self.host._prepare_app_install(app, 0, options={'tunnel_token': token()})
        row = self.member(app, app)
        record = self.host.managed_app(app)
        control = self.host.directory / 'apps' / app
        before = (control / 'options.json').read_bytes()
        data = Path(record['data']) / 'retained.txt'
        data.write_text('user data')
        private = self.host._installation_path(app, private=True)
        private.parent.mkdir(mode=0o700, exist_ok=True)
        atomic_json(private, {'operation': 'install', 'options': {'tunnel_token': token()}})
        result = self.host.dispatch('docker_container_action', container=row['Id'], action='remove', stop_before_remove=True)
        self.assertTrue(result['app_removed'])
        self.assertTrue(result['data_retained'])
        self.assertEqual([item['id'] for item in self.host.load('apps', [])], ['jellyfin'])
        self.assertEqual((control / 'options.json').read_bytes(), before)
        self.assertTrue((control / 'compose.json').is_file())
        self.assertEqual(data.read_text(), 'user data')
        self.assertFalse(private.exists())
        status = self.host.op_app_install_status(app)
        self.assertFalse(status['installed'])
        self.assertFalse(status['configured'])

    def test_removing_primary_with_remaining_dependency_does_not_unregister_stack(self):
        app, redis, _ = self.legacy_redis()
        primary = self.containers[app]['Id']
        result = self.host.dispatch('docker_container_action', container=primary, action='remove', stop_before_remove=True)
        self.assertFalse(result['app_removed'])
        self.assertEqual([item['id'] for item in self.host.load('apps', [])], [app])
        self.assertIn(app + '-redis', self.containers)

    def test_failed_empty_package_inspection_keeps_registration(self):
        self.install()
        with patch.object(self.host, '_app_lifecycle_snapshot', side_effect=Error('Docker unavailable')):
            with self.assertRaises(Error): self.host._app_unregister_if_empty('jellyfin')
        self.assertEqual([item['id'] for item in self.host.load('apps', [])], ['jellyfin'])

    def test_preflight_needs_no_credentials_and_is_read_only_with_truthful_denial(self):
        from titan.app_memory import GIB
        before = sorted(str(path.relative_to(self.root)) for path in self.root.rglob('*'))
        with patch('titan.app_memory.memory_snapshot', return_value={'memory_total':8*GIB, 'memory_available':7*GIB}):
            result = self.host.dispatch('app_memory_preflight', app='titan-nextcloud-office', options={'resource_profile':'balanced', 'office_mode':'disabled'})
            self.assertTrue(result['allowed']); self.assertFalse(result['plan']['office_enabled'])
            result = self.host.dispatch('app_memory_preflight', app='titan-nextcloud-office', options={'resource_profile':'balanced', 'office_mode':'enabled'})
            self.assertFalse(result['allowed']); self.assertTrue(result['plan']['office_enabled'])
        self.assertEqual(before, sorted(str(path.relative_to(self.root)) for path in self.root.rglob('*')))
        self.assertFalse(any(call[:2] in (['docker','pull'],['docker','create'],['docker','start']) for call in self.calls))
        for options in ({'password':'secret'}, {'resource_profile':'invalid'}, {'office_mode':'invalid'}):
            with self.assertRaises(Error): self.host.op_app_memory_preflight('titan-nextcloud-office', options)

    def test_install_denied_before_first_config_write_or_image_pull(self):
        with patch('titan.app_memory.check_install_memory', side_effect=Error('RAM reserve',409)):
            with self.assertRaisesRegex(Error, 'RAM reserve'):
                self.host.op_app_install('titan-nextcloud-office', 18088,
                    options={'username':'admin','password':'PrivatePassword123','nas_host':'nas.local'})
        self.assertFalse((self.host.directory / 'apps/titan-nextcloud-office').exists())
        self.assertEqual(self.host.load('apps', []), [])
        self.assertFalse(any(call[:2] == ['docker','compose'] and '-f' in call for call in self.calls))


class OperationConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.host = Host(base / 'agent', base / 'shares', base / 'vms', base / 'smb.conf')
        # Explicit private test authorization, matching the disposable-image
        # fixture boundary. Production recipes cannot grant this themselves.
        self.host._ci_fixture_ids = {'first'}
        self.release = threading.Event()
        self.threads = []
        self.errors = []

    def tearDown(self):
        self.release.set()
        for thread in self.threads: thread.join(3)
        self.assertFalse(any(thread.is_alive() for thread in self.threads))
        self.temp.cleanup()

    def launch(self, operation, **arguments):
        def work():
            try: self.host.dispatch(operation, **arguments)
            except Exception as exc: self.errors.append(exc)
        thread = threading.Thread(target=work); self.threads.append(thread); thread.start()

    def block_install(self):
        started = threading.Event()
        def operation(**arguments):
            started.set(); self.release.wait(3)
        self.host.op_app_install = operation
        self.launch('app_install', app='first')
        self.assertTrue(started.wait(1))

    def test_install_does_not_block_files_other_app_or_account_revocation_but_same_app_waits(self):
        self.block_install()
        read, other, revoked, same, progress = (threading.Event() for _ in range(5))
        allowed = [True]
        def file_op(**arguments):
            if not allowed[0]: raise Error('Kein Zugriff', 403)
            read.set(); return {'entries': []}
        self.host.op_file = file_op
        def revoke(**arguments): allowed[0] = False; revoked.set()
        self.host.op_account_set_enabled = revoke
        self.host.op_app_action = lambda app, action: same.set() if app == 'first' else other.set()
        self.host.op_app_install_status = lambda app: progress.set()
        self.launch('app_install_status', app='titan-cloudflared')
        self.launch('file', user='reader', share='docs', action='list')
        self.launch('app_action', app='second', action='stop')
        self.launch('app_action', app='first', action='stop')
        self.assertTrue(read.wait(1)); self.assertTrue(other.wait(1)); self.assertTrue(progress.wait(1)); self.assertFalse(same.wait(.05))
        self.launch('account_set_enabled', name='reader', enabled=False)
        self.assertTrue(revoked.wait(1))
        with self.assertRaises(Error): self.host.dispatch('file', user='reader', share='docs', action='list')
        self.release.set(); self.assertTrue(same.wait(1)); self.assertEqual(self.errors, [])

    def test_unknown_mutations_and_config_restore_still_wait_for_install(self):
        self.block_install()
        exclusive = threading.Event()
        self.host.op_pool_create = lambda **arguments: exclusive.set()
        self.launch('pool_create', name='pool')
        self.assertFalse(exclusive.wait(.05))
        self.release.set(); self.assertTrue(exclusive.wait(1))
        (self.host.directory / 'config-restore.lock').write_text('restore')
        with self.assertRaises(Error): self.host.dispatch('admin_file', share='docs', action='list')

    def test_jobs_allow_different_app_lifecycle_but_keep_same_app_queued(self):
        store = Store(self.temp.name); jobs = Jobs(store)
        first, second, same = threading.Event(), threading.Event(), threading.Event()
        def slow(): first.set(); self.release.wait(3); return {'ok': True}
        jobs.submit('admin', 'app_install', slow, resources=job_resources('app_install', {'app': 'first'}))
        self.assertTrue(first.wait(1))
        other = jobs.submit('admin', 'app_action', lambda: second.set(), resources=job_resources('app_action', {'app': 'second', 'action': 'stop'}))
        waiting = jobs.submit('admin', 'app_action', lambda: same.set(), resources=job_resources('app_action', {'app': 'first', 'action': 'stop'}))
        try:
            self.assertTrue(second.wait(1)); self.assertFalse(same.wait(.05))
            row = next(item for item in store.jobs() if item['id'] == waiting['job'])
            self.assertEqual(row['status'], 'queued')
        finally:
            self.release.set()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and any(item['status'] in ('queued','running') for item in store.jobs()): time.sleep(.01)
        self.assertTrue(same.is_set())


if __name__ == '__main__': unittest.main()

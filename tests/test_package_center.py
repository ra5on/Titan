import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from titan.catalog import APPS
from titan.core import Error
from titan.package_center import definition_digest
from titan.app_memory import limit_bytes
import test_app_management as management_fixture


class PackageCenterTests(unittest.TestCase):
    setUp = management_fixture.AppManagementTests.setUp
    tearDown = management_fixture.AppManagementTests.tearDown
    command = management_fixture.AppManagementTests.command
    make_container = management_fixture.AppManagementTests.make_container

    def package(self, app='titan-immich'):
        options = {'username':'admin','password':'PrivatePassword123','nas_host':'nas.local','office_mode':'enabled'} if app == 'titan-nextcloud-office' else {}
        with patch('titan.app_package_setup.provision'):
            self.host.op_app_install(app, APPS[app]['default_port'], options=options)
        return app

    def members(self, app):
        record = self.host.managed_app(app)
        definition = json.loads((self.host.directory / 'apps' / app / 'compose.json').read_text())
        for key, service in definition['services'].items():
            identifier = hashlib.sha256(key.encode()).hexdigest()
            ports = {}
            for publication in service.get('ports', []):
                published, target = publication.split(':')
                if '/' not in target: target += '/tcp'
                ports[target] = [{'HostIp':'','HostPort':published}]
            item = {'Id':identifier, 'Name':'/titan-' + key, 'Config':{'Image':service['image'],'Labels':{**service['labels'],'com.docker.compose.project':'titan-' + app,'com.docker.compose.service':key}},
                    'Mounts':[{'Type':'bind','Source':binding['source'],'Destination':binding['target']} for binding in service['volumes']],
                    'HostConfig':{'Memory':limit_bytes(service['mem_limit']),'NetworkMode':'titan-' + app + '_default','Privileged':False,'PortBindings':ports},
                    'State':{'Status':'exited' if key.endswith('-office-init') else 'running','ExitCode':0,'Health':{'Status':'healthy'}},
                    'RestartCount':0,'NetworkSettings':{'Ports':ports,'Networks':{'titan-' + app + '_default':{'IPAddress':'172.19.0.2','Gateway':'172.19.0.1'}}}}
            self.containers[key] = item
        return self.containers

    def test_details_cover_database_cache_and_main_service_and_hide_secrets(self):
        app = self.package(); self.members(app)
        details = self.host.op_package_details(app)
        self.assertTrue(details['ready'])
        self.assertEqual(details['total_services'], 4)
        self.assertFalse(details['update']['available'])
        secret = self.host._app_options(app)['database_password']
        self.assertNotIn(secret, json.dumps(details))
        self.containers[app + '-database']['State']['Health']['Status'] = 'unhealthy'
        details = self.host.op_package_details(app)
        self.assertFalse(details['ready'])
        self.assertEqual(details['phase'], 'attention')
        self.assertFalse(self.host.op_apps()['installed'][0]['package_ready'])

    def test_one_shot_success_is_ready_even_when_exited(self):
        app = self.package('titan-nextcloud-office'); self.members(app)
        details = self.host.op_package_details(app)
        init = next(item for item in details['services'] if item['one_shot'])
        self.assertTrue(init['ready'])
        self.assertTrue(details['ready'])
        self.containers[app + '-office-init']['State']['ExitCode'] = 1
        self.assertFalse(self.host.op_package_details(app)['ready'])

    def test_explicit_disabling_office_removes_old_owned_members_but_keeps_every_data_directory(self):
        app = self.package('titan-nextcloud-office'); self.members(app)
        self.host.op_app_action(app, 'stop')
        record = self.host.managed_app(app)
        office = self.host.directory / 'apps' / app / 'config/office-data/keep.txt'
        office.parent.mkdir(parents=True, exist_ok=True); office.write_text('saved-office-content')
        data = Path(record['data']) / 'keep.txt'; data.write_text('saved-nextcloud-content')
        result = self.host.op_package_settings(app, record['port'], {'office_mode':'disabled', 'resource_profile':'balanced'})
        self.assertTrue(result['ok'])
        self.assertFalse(any(key.endswith(('-eurooffice','-office-init')) for key in self.containers))
        definition = json.loads((self.host.directory / 'apps' / app / 'compose.json').read_text())
        self.assertEqual(len(definition['services']), 4)
        self.assertEqual(office.read_text(), 'saved-office-content')
        self.assertEqual(data.read_text(), 'saved-nextcloud-content')
        self.assertEqual(self.host._app_options(app)['office_mode'], 'disabled')
        self.host.op_app_action(app, 'start'); self.members(app)
        details = self.host.op_package_details(app)
        self.assertEqual(details['primary_state'], 'running'); self.assertTrue(details['primary_available'])
        self.assertTrue(details['ready']); self.assertEqual(details['total_services'], 4)

    def test_expected_healthcheck_cannot_be_assumed_ready_when_missing(self):
        app = self.package(); self.members(app)
        self.containers[app + '-database']['State'].pop('Health')
        self.assertFalse(self.host.op_package_details(app)['ready'])

    def test_logs_are_service_scoped_and_redact_private_credentials(self):
        app = self.package(); self.members(app)
        secret = self.host._app_options(app)['database_password']
        self.logs.return_value = 'connection postgres://' + secret + '@database\nready'
        result = self.host.op_package_logs(app, app + '-database')
        self.assertNotIn(secret, result['logs'])
        self.assertIn('[ausgeblendet]', result['logs'])
        with self.assertRaises(Error): self.host.op_package_logs(app, 'foreign-container')

    def test_pinned_installed_recipe_remains_manageable_after_catalog_upgrade(self):
        app = self.package(); self.members(app)
        path = self.host.directory / 'apps' / app / 'compose.json'
        installed = path.read_bytes()
        stack = APPS[app]['stack']['services']['immich-server']
        old_image = stack['image']
        try:
            stack['image'] = 'ghcr.io/immich-app/immich-server:v3.2.99'
            self.assertEqual(self.host.managed_app(app)['id'], app)
            self.assertTrue(self.host.op_package_details(app)['update']['available'])
            self.host._app_container(app, self.host.managed_app(app))
            altered = json.loads(installed)
            altered['services'][app]['privileged'] = True
            path.write_text(json.dumps(altered))
            with self.assertRaises(Error): self.host.managed_app(app)
        finally:
            stack['image'] = old_image
            path.write_bytes(installed)

    def test_office_runtime_is_derived_from_verified_container(self):
        app = self.package('titan-nextcloud-office'); self.members(app)
        runtime = self.host.op_app_office_runtime()
        self.assertEqual(runtime['engine_origin'], 'http://172.19.0.2:80')
        self.assertEqual(runtime['bridge_gateway'], '172.19.0.1')
        self.assertEqual(runtime['secret'], self.host._app_options(app)['office_secret'])
        self.containers[app + '-eurooffice']['State']['Health']['Status'] = 'starting'
        with self.assertRaises(Error): self.host.op_app_office_runtime()

    def test_live_or_secret_settings_changes_are_blocked(self):
        app = self.package(); self.members(app)
        with self.assertRaisesRegex(Error, 'gesamte Paket'): self.host.op_package_settings(app, 2284)
        for item in self.containers.values(): item['State']['Status'] = 'exited'
        with self.assertRaisesRegex(Error, 'Konten und Passwörter'): self.host.op_package_settings(app, 2284, {'database_password':'new-password'})

    def test_diagnose_reports_unavailable_data_without_destructive_repair(self):
        app = self.package(); self.members(app)
        with patch.object(self.host, 'app_storage_ready', side_effect=Error('Volume fehlt')):
            result = self.host.op_package_diagnose(app)
            self.assertFalse(result['repair_available'])
            with self.assertRaisesRegex(Error, 'nicht verfügbaren Laufwerke'): self.host.op_package_repair(app)

    def test_approved_recipe_update_has_backup_and_keeps_package_stopped(self):
        app = self.package()
        self.containers[app]['State']['Status'] = 'exited'
        image = APPS[app]['stack']['services']['immich-server']
        previous = image['image']
        try:
            image['image'] = 'ghcr.io/immich-app/immich-server:v3.2.99'
            self.calls.clear()
            result = self.host.op_package_update(app)
            self.assertTrue(result['kept_stopped'])
            self.assertTrue(Path(result['backup']['path']).is_file())
            calls = [call for call in self.calls if call[0] == 'tar' or call[:2] == ['docker','rm'] or call[:2] == ['docker','compose'] and '-f' in call]
            backup = next(index for index, call in enumerate(calls) if call[0] == 'tar')
            remove = next(index for index, call in enumerate(calls) if call[:2] == ['docker','rm'])
            pull = next(index for index, call in enumerate(calls) if call[-1] == 'pull')
            self.assertLess(backup, remove)
            self.assertLess(remove, pull)
            self.assertFalse(any('-v' in call or '--volumes' in call for call in calls))
            record = self.host.managed_app(app)
            definition = json.loads((self.host.directory / 'apps' / app / 'compose.json').read_text())
            self.assertEqual(record['definition_digest'], definition_digest(definition))
            self.assertEqual(definition['services'][app]['image'], image['image'])
            self.assertEqual(self.containers[app]['State']['Status'], 'created')
        finally:
            image['image'] = previous

    def test_stopped_settings_change_recreates_without_starting_or_secret_change(self):
        app = self.package()
        self.containers[app]['State']['Status'] = 'exited'
        previous = self.host._app_options(app)
        self.calls.clear()
        result = self.host.op_package_settings(app, 2284)
        self.assertEqual(self.host.managed_app(app)['port'], 2284)
        self.assertEqual(self.host._app_options(app), previous)
        self.assertEqual(self.containers[app]['State']['Status'], 'created')
        self.assertTrue(Path(result['backup']['path']).exists())
        self.assertFalse(any(call[-1] == 'start' for call in self.calls))


if __name__ == '__main__': unittest.main()

import copy
import json
import unittest
from unittest.mock import Mock, patch

from titan.app_packages import PACKAGES, prepare_options
from titan.app_package_setup import office_settings, provision, validate_host
from titan.catalog import APPS, catalog, compose, published_ports, validate_options
from titan.compose_templates import validate_stack
from titan.core import Error


class PackagesTests(unittest.TestCase):
    def setUp(self):
        waiting = patch('titan.app_package_setup.time.sleep')
        self.waiting = waiting.start()
        self.addCleanup(waiting.stop)

    def options(self, name):
        user = {field['key']: 'UserPassword12345' for field in PACKAGES[name]['install_schema'] if field['type'] == 'password' and not field.get('generated')}
        if name == 'titan-cloudflared':
            import base64
            user['tunnel_token'] = base64.b64encode(json.dumps({'a': 'a' * 32, 't': '2c9069cd-5cf1-470f-9ddd-df156d3f2c57',
                's': base64.b64encode(b'example-secret-for-tests-only-123').decode()}).encode()).decode()
        if name == 'titan-nextcloud-office':
            user['office_mode'] = 'enabled'
        return validate_options(name, prepare_options(name, user))

    def test_retired_packages_are_hidden_but_existing_installs_remain_manageable(self):
        self.assertEqual({item['id'] for item in catalog()['apps']}, {'titan-cloudflared'})
        public = [item for item in catalog(include_legacy=True)['apps'] if item['id'] in PACKAGES]
        self.assertEqual({item['id'] for item in public}, set(PACKAGES))
        self.assertEqual(len(public), len(PACKAGES))
        for item in public:
            self.assertNotIn('stack', item)
            self.assertNotIn('environment', item)
            self.assertTrue(all(not field.get('generated') for field in item['install_schema']))
            self.assertEqual(item['containers'], len(PACKAGES[item['id']]['stack']['services']))
            self.assertTrue(item['first_login']['documentation'].startswith('https://'))
        self.assertIn('nextcloud', APPS)  # Existing deployments keep the old layout.
        self.assertNotIn('nextcloud', {item['id'] for item in public})

    def test_generated_keys_are_unique_and_reused_after_remove_or_retry(self):
        name = 'titan-nextcloud-office'
        first, second = self.options(name), self.options(name)
        self.assertNotEqual(first['database_password'], second['database_password'])
        self.assertNotEqual(first['database_password'], first['office_secret'])
        self.assertEqual(prepare_options(name, {'password': 'DifferentPassword123'}, first)['office_secret'], first['office_secret'])
        self.assertEqual(len(first['database_password']), 64)
        self.assertNotIn(first['database_password'], json.dumps(catalog()))

    def test_dependency_storage_and_credentials_are_connected_and_private(self):
        for name in PACKAGES:
            options = self.options(name)
            result = compose(name, '/agent/apps/' + name, 1000, 1000, PACKAGES[name]['default_port'], '/nas/data', options)
            for key, service in result['services'].items():
                self.assertNotIn('privileged', service)
                self.assertNotIn('network_mode', service)
                for binding in service['volumes']:
                    self.assertFalse(binding['bind']['create_host_path'])
                    self.assertNotIn('docker.sock', binding['source'])
                if key.endswith(('-database', '-redis', '-cron', '-immich-machine-learning')):
                    self.assertFalse(service['ports'])
            if 'database_password' in options:
                primary, db = result['services'][name], result['services'][name + '-database']
                self.assertIn(options['database_password'], primary['environment'].values())
                self.assertEqual(db['environment']['POSTGRES_PASSWORD'], options['database_password'])
                self.assertEqual(primary['depends_on'][name + '-database']['condition'], 'service_healthy')
        services = compose('titan-immich', '/agent/app', 1000, 1000, 2283, '/nas/data', self.options('titan-immich'))['services']
        self.assertEqual(services['titan-immich-database']['shm_size'], '128m')
        self.assertIn('vectorchord', services['titan-immich-database']['image'])

    def test_office_initializes_image_defaults_before_start(self):
        services = compose('titan-nextcloud-office', '/agent/app', 1000, 1000, 8088, '/nas/data', self.options('titan-nextcloud-office'))['services']
        init = services['titan-nextcloud-office-office-init']
        office = services['titan-nextcloud-office-eurooffice']
        self.assertEqual(init['restart'], 'no')
        self.assertEqual(office['depends_on']['titan-nextcloud-office-office-init']['condition'], 'service_completed_successfully')
        self.assertIn('cp -a --update=none /etc/euro-office/documentserver/.', init['command'][0])
        self.assertFalse(init['ports'])

    def test_dns_publications_and_office_port_are_registered(self):
        for name in ('titan-adguard', 'titan-pihole'):
            publications = published_ports(name, 15000, self.options(name))
            self.assertEqual({(p['host'], p['protocol']) for p in publications if p['target'] == 53}, {(53, 'tcp'), (53, 'udp')})
        options = self.options('titan-nextcloud-office')
        self.assertIn(9980, {p['host'] for p in published_ports('titan-nextcloud-office', 8088, options)})
        for name in ('titan-immich', 'titan-nextcloud-office'):
            with self.assertRaises(Error):
                compose(name, '/agent', 1000, 1000, 15000, '/data', self.options(name), {'mode': 'host'})

    def test_limits_are_bounded_and_missing_generated_keys_do_not_get_recreated(self):
        value = copy.deepcopy(PACKAGES['titan-immich']['stack'])
        for bad in ('unlimited', '-1g', '1t', 1, '1g;bad'):
            value['services']['database']['memory'] = bad
            with self.assertRaises(Error): validate_stack(value)
        with self.assertRaises(Error): compose('titan-immich', '/agent', 1000, 1000, 2283, '/data', {})

    def test_office_connection_uses_internal_callbacks_and_valid_public_authority(self):
        options = self.options('titan-nextcloud-office')
        options['nas_host'] = '192.168.10.18'
        values = office_settings(options)
        self.assertEqual(values['DocumentServerUrl'], 'http://192.168.10.18:9980/')
        self.assertEqual(values['DocumentServerInternalUrl'], 'http://eurooffice/')
        self.assertEqual(values['StorageUrl'], 'http://nextcloud/')
        self.assertEqual(values['jwt_secret'], options['office_secret'])
        self.assertEqual(values['jwt_header'], 'AuthorizationJwt')
        self.assertEqual(PACKAGES['titan-nextcloud-office']['stack']['services']['eurooffice']['environment']['JWT_HEADER'], values['jwt_header'])
        options['nas_host'] = 'fd00::1'
        self.assertEqual(office_settings(options)['DocumentServerUrl'], 'http://[fd00::1]:9980/')
        for bad in ('http://nas', 'nas:8080', '../nas', 'nas/path', '-nas', 'nas..lan'):
            with self.assertRaises(Error): validate_host(bad)

    def test_office_setup_retries_without_reinstalling_connector_or_logging_secret(self):
        host = Mock()
        host.managed_app.return_value = {'id': 'titan-nextcloud-office'}
        host._app_container.return_value = {'Id': 'a' * 64}
        host._app_options.return_value = self.options('titan-nextcloud-office')
        host.load.return_value = [{'id': 'titan-nextcloud-office'}]
        run = Mock(return_value='')
        run.side_effect = [json.dumps({'enabled': {'eurooffice': '1'}}), '', '', '']
        provision(host, 'titan-nextcloud-office', run)
        self.assertTrue(host.save.call_args.args[1][0]['package_initialized'])
        self.assertFalse(any('app:install' in call.args[0] for call in run.call_args_list))
        self.assertFalse(any('app:enable' in call.args[0] for call in run.call_args_list))
        key = host._app_options.return_value['office_secret']
        self.assertNotIn(key, json.dumps([call.args for call in run.call_args_list]))
        self.assertIn(key, run.call_args_list[1].kwargs['input'])
        self.waiting.assert_called_once_with(4)
        host.managed_app.return_value['package_initialized'] = True
        run.reset_mock()
        self.waiting.reset_mock()
        provision(host, 'titan-nextcloud-office', run)
        run.assert_not_called()
        self.waiting.assert_not_called()
        host.managed_app.return_value.pop('package_initialized')
        run.side_effect = Error('upstream printed ' + key)
        with self.assertRaises(Error) as caught: provision(host, 'titan-nextcloud-office', run)
        self.assertNotIn(key, str(caught.exception))

    def office_setup_fixture(self):
        host = Mock()
        host.managed_app.return_value = {'id': 'titan-nextcloud-office'}
        host._app_container.return_value = {'Id': 'a' * 64}
        host._app_options.return_value = self.options('titan-nextcloud-office')
        host.load.return_value = [{'id': 'titan-nextcloud-office'}]
        return host

    def test_new_or_disabled_office_app_waits_for_web_cache_before_connection_probe(self):
        for installed, expected in (({'enabled': {}, 'disabled': {}}, 'app:install'),
                                    ({'enabled': {}, 'disabled': {'eurooffice': '1'}}, 'app:enable')):
            with self.subTest(expected=expected):
                host = self.office_setup_fixture()
                elapsed = [0]
                self.waiting.reset_mock()
                self.waiting.side_effect = lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds)
                def command(args, **kwargs):
                    if 'app:list' in args: return json.dumps(installed)
                    if '--check' in args:
                        self.assertGreater(elapsed[0], 3, 'The live web APCu entry must expire before the first download probe.')
                    return ''
                run = Mock(side_effect=command)
                provision(host, 'titan-nextcloud-office', run)
                actions = [call.args[0] for call in run.call_args_list]
                self.assertEqual(sum(expected in args for args in actions), 1)
                self.assertFalse(any('docker' == args[0] and 'restart' in args for args in actions))
                self.assertTrue(host.save.call_args.args[1][0]['package_initialized'])
                self.waiting.assert_called_once_with(4)

    def test_office_web_cache_transient_failure_recovers_without_reinstalling_or_restarting(self):
        host = self.office_setup_fixture()
        checks = [0]
        def command(args, **kwargs):
            if 'app:list' in args: return json.dumps({'enabled': {'eurooffice': '1'}})
            if '--check' in args:
                checks[0] += 1
                if checks[0] == 1: raise Error('Transient cached route returned HTTP 404.')
            return ''
        run = Mock(side_effect=command)
        provision(host, 'titan-nextcloud-office', run)
        self.assertEqual(checks[0], 2)
        self.assertEqual([call.args for call in self.waiting.call_args_list], [(4,), (4,)])
        self.assertFalse(any('app:install' in call.args[0] or 'app:enable' in call.args[0] or 'restart' in call.args[0]
                             for call in run.call_args_list))
        self.assertTrue(host.save.call_args.args[1][0]['package_initialized'])

    def test_permanent_office_connection_failure_is_bounded_and_never_marks_initialized(self):
        host = self.office_setup_fixture()
        checks = [0]
        secret = host._app_options.return_value['office_secret']
        def command(args, **kwargs):
            if 'app:list' in args: return json.dumps({'enabled': {'eurooffice': '1'}})
            if '--check' in args:
                checks[0] += 1
                raise Error('Permanent connection failure with secret ' + secret)
            return ''
        run = Mock(side_effect=command)
        with self.assertRaises(Error) as caught:
            provision(host, 'titan-nextcloud-office', run)
        self.assertEqual(checks[0], 3)
        self.assertEqual([call.args for call in self.waiting.call_args_list], [(4,), (4,), (4,)])
        host.save.assert_not_called()
        self.assertNotIn(secret, str(caught.exception))


if __name__ == '__main__': unittest.main()

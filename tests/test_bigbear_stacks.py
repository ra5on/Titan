import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from titan.bigbear import translate, archive_document, URL
from titan.app_stores import StoreMixin
from titan.catalog import APPS, catalog, compose, validate_options
from titan.core import Error
from titan.store_recipes import recipes
import test_app_management as fixture


def example(version='1'):
    return {'services': {
        'web': {'image': 'example/web:' + version + '@sha256:' + 'a' * 64,
                'ports': ['8088:80'], 'volumes': ['web-data:/data'],
                'environment': {'DB_PASSWORD': 'public-default'},
                'depends_on': {'db': {'condition': 'service_healthy'}}},
        'db': {'image': 'postgres:17', 'volumes': ['db-data:/var/lib/postgresql/data'],
               'environment': {'DB_PASSWORD': 'public-default'},
               'healthcheck': {'test': ['CMD', 'pg_isready']}},
        'cache': {'image': 'redis:7', 'volumes': ['cache-data:/data']}
    }}, {'name': 'Example', 'description': 'Example stack', 'port': '8088'}


def document(version='1'):
    source, meta = example(version)
    return {'schema': 1, 'name': 'BigBear', 'apps': [translate(source, meta, 'example')]}


class BigBearTests(unittest.TestCase):
    def test_metadata_ports_dependencies_and_shared_secrets(self):
        _, values = recipes(document(), URL)
        key, recipe = next(iter(values.items()))
        APPS[key] = recipe
        self.addCleanup(APPS.pop, key, None)
        self.assertEqual(recipe['port'], 80)
        self.assertEqual(recipe['default_port'], 8088)
        self.assertEqual(len(recipe['install_schema']), 1)
        self.assertEqual(recipe['install_schema'][0]['type'], 'password')
        self.assertNotIn('public-default', json.dumps(recipe))
        options = {recipe['install_schema'][0]['key']: 'private$Password'}
        built = compose(key, '/control', 1000, 1000, 8088, '/private/data', options)
        self.assertEqual(len(built['services']), 3)
        self.assertEqual(built['services'][key]['ports'], ['8088:80/tcp'])
        self.assertEqual(built['services'][key]['depends_on'], {key + '-db': {'condition': 'service_healthy'}})
        self.assertEqual(built['services'][key]['environment']['DB_PASSWORD'], 'private$$Password')
        self.assertEqual(built['services'][key + '-db']['environment']['DB_PASSWORD'], 'private$$Password')
        self.assertEqual(built['services'][key + '-db']['volumes'][0]['source'], '/control/config/mount-2')
        self.assertIn(key, {item['id'] for item in catalog()['apps']})

    def test_literal_database_identifiers_stay_paired_with_healthcheck(self):
        source, meta = example()
        source['services']['db']['environment']['POSTGRES_USER'] = 'database-user'
        source['services']['db']['healthcheck']['test'] = ['CMD-SHELL', 'pg_isready -U database-user']
        source['services']['web']['environment']['POSTGRES_USER'] = 'database-user'
        result = translate(source, meta, 'example')
        self.assertEqual(result['stack']['services']['db']['environment']['POSTGRES_USER'], 'database-user')
        self.assertEqual(result['stack']['services']['web']['environment']['POSTGRES_USER'], 'database-user')
        self.assertFalse(any('POSTGRES_USER' in row['label'] for row in result['stack_fields']))

    def test_unsafe_host_options_and_external_networks_are_rejected(self):
        for kind in ('privileged', 'host-mount', 'external-net', 'separate-nets', 'docker-socket'):
            source, meta = example()
            if kind == 'privileged': source['services']['web']['privileged'] = True
            if kind == 'host-mount': source['services']['web']['volumes'] = ['/etc:/host']
            if kind == 'docker-socket': source['services']['web']['volumes'] = ['/var/run/docker.sock:/socket']
            if kind == 'external-net': source['networks'] = {'lan': {'external': True}}
            if kind == 'separate-nets':
                source['services']['web']['networks'] = ['front']
                source['services']['db']['networks'] = ['back']
            with self.subTest(kind=kind), self.assertRaises(Error): translate(source, meta, 'example')

    def test_dns_defaults_preserve_tcp_and_udp_port_53(self):
        source = {'services': {'dns': {'image': 'example/dns:1', 'ports': ['8080:3000', '53:53/tcp', '53:53/udp']}}}
        result = translate(source, {'name': 'DNS', 'port': '8080'}, 'dns')
        _, parsed = recipes({'schema':1,'name':'BigBear','apps':[result]}, URL)
        recipe = next(iter(parsed.values()))
        self.assertEqual([field['default'] for field in recipe['install_schema']], [53, 53])

    def test_archive_uses_metadata_and_reports_unsupported_apps(self):
        source, meta = example()
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('Apps/example/compose.yaml', json.dumps(source))
            archive.writestr('Apps/example/metadata.json', json.dumps(meta))
            archive.writestr('Apps/unsupported/compose.yaml', 'services: &root\n  app: *root')
            archive.writestr('Apps/unsupported/metadata.json', '{}')
        result, skipped = archive_document(output.getvalue())
        self.assertEqual(len(result['apps']), 1)
        self.assertEqual(skipped[0]['name'], 'unsupported')

    def test_refresh_and_disable_keep_installed_recipe_unchanged(self):
        class MemoryHost(StoreMixin):
            def __init__(self): self.rows = {}
            def load(self, key, default): return self.rows.get(key, default)
            def save(self, key, value): self.rows[key] = value
        host = MemoryHost()
        key = next(iter(recipes(document(), URL)[1]))
        self.addCleanup(APPS.pop, key, None)
        with patch.object(host, 'store_document', return_value=(document(), [])):
            host.op_app_store_add(URL, trusted=True)
        host.rows['apps'] = [{'id': key}]
        with patch.object(host, 'store_document', return_value=(document('2'), [])):
            host.op_app_store_refresh('bigbear')
        self.assertIn(':1@', APPS[key]['image'])
        host.op_app_store_toggle('bigbear', False)
        self.assertNotIn(key, {row['id'] for row in host.op_catalog()['apps']})
        self.assertIn(key, {row['id'] for row in host.op_catalog()['installed_recipes']})
        APPS.pop(key)
        host.initialize_app_stores()
        self.assertIn(':1@', APPS[key]['image'])


class BigBearLifecycleTests(unittest.TestCase):
    setUp = fixture.AppManagementTests.setUp
    tearDown = fixture.AppManagementTests.tearDown
    command = fixture.AppManagementTests.command
    make_container = fixture.AppManagementTests.make_container

    def install(self):
        key, recipe = next(iter(recipes(document(), URL)[1].items()))
        APPS[key] = recipe
        self.addCleanup(APPS.pop, key, None)
        options = {recipe['install_schema'][0]['key']: 'PrivatePassword123'}
        with patch('titan.app_package_setup.provision'):
            self.host.op_app_install(key, 8088, options=options)
        return key

    def test_installed_definition_is_pinned_and_package_details_work(self):
        key = self.install()
        record = self.host.managed_app(key)
        self.assertIn('definition_digest', record)
        self.assertIn(key, self.host.load('installed-app-recipes-v1', {}))
        result = self.host.op_package_details(key)
        self.assertEqual(result['total_services'], 3)
        self.assertEqual(result['update']['policy'], 'installed-store-recipe')
        self.assertNotIn('PrivatePassword123', json.dumps(result))

    def test_conflicting_port_is_rejected_before_registering_stack(self):
        key, recipe = next(iter(recipes(document(), URL)[1].items()))
        APPS[key] = recipe
        self.addCleanup(APPS.pop, key, None)
        with self.assertRaises(Error):
            self.host.op_app_install(key, 5000, options={recipe['install_schema'][0]['key']: 'PrivatePassword123'})
        self.assertEqual(self.host.load('apps', []), [])

    def test_remove_keeps_files_and_unregisters_all_stack_services(self):
        key = self.install()
        directory = self.host.directory / 'apps' / key
        result = self.host.op_app_action(key, 'remove')
        self.assertTrue(result['data_retained'])
        self.assertEqual(self.host.load('apps', []), [])
        self.assertTrue((directory / 'compose.json').exists())

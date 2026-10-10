import copy
import io
import json
import stat
import unittest
import zipfile
from unittest.mock import patch

from titan.core import Error
from titan.umbrel_catalog import (URL, archive_inventory, compile_inventory,
                                  fetch_inventory, installation_order, read_yaml)
from titan.catalog import APPS, compose
from titan.store_recipes import recipes

REVISION = 'a' * 40


def package(name='example', dependencies=None):
    return {
        name + '/umbrel-app.yml': json.dumps({'manifestVersion': 1, 'id': name,
            'name': 'Example', 'description': 'Example app', 'port': 8088,
            'dependencies': dependencies or []}),
        name + '/docker-compose.yml': json.dumps({'version': '3.7', 'services': {
            'app_proxy': {'environment': {'APP_HOST': name + '_web_1',
                'APP_PORT': 80, 'PROXY_AUTH_ADD': 'false'}},
            'web': {'image': 'example/web:1', 'user': '1000:1000',
                'volumes': ['${APP_DATA_DIR}/data:/data']}}}),
        name + '/data/.gitkeep': '',
    }


def archive(files=None, extra=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as result:
        for path, value in (files or package()).items():
            result.writestr('repo-' + REVISION + '/' + path, value)
        if extra:
            extra(result)
    return output.getvalue()


class CatalogTests(unittest.TestCase):
    def test_pinned_archive_compiles_into_actual_private_compose(self):
        inventory = archive_inventory(archive(), REVISION)
        document, blocked = compile_inventory(inventory)
        self.assertEqual(blocked, [])
        _, parsed = recipes(document, URL)
        key, recipe = next(iter(parsed.items()))
        APPS[key] = recipe
        self.addCleanup(APPS.pop, key, None)
        built = compose(key, '/control', 1000, 1000, 8088, '/public', {}, config_path='/private/app')
        service = built['services'][key]
        self.assertEqual(service['image'], 'example/web:1')
        self.assertEqual(service['ports'], ['8088:80/tcp'])
        self.assertTrue(service['volumes'][0]['source'].startswith('/private/app/umbrel-'))
        self.assertEqual(service['volumes'][0]['target'], '/data')
        self.assertIn('example_web_1', service['networks']['default']['aliases'])
        self.assertNotIn('app_proxy', built['services'])
        self.assertIn(REVISION, recipe['documentation'])

    def test_required_hooks_and_files_cannot_disappear(self):
        for path, value, code in [('hooks/pre-start', 'exit 0', 'package_steps'),
                ('exports.sh', 'export VALUE=1', 'package_steps'),
                ('data/config.json', '{}', 'package_files'),
                ('data/.gitkeep', 'not empty', 'package_files')]:
            with self.subTest(path=path):
                files = package(); files['example/' + path] = value
                document, blocked = compile_inventory(archive_inventory(archive(files), REVISION))
                self.assertEqual(document['apps'], [])
                self.assertEqual(blocked[0]['code'], code)

    def test_proxy_auth_is_never_silently_removed(self):
        files = package(); doc = json.loads(files['example/docker-compose.yml'])
        del doc['services']['app_proxy']['environment']['PROXY_AUTH_ADD']
        files['example/docker-compose.yml'] = json.dumps(doc)
        _, blocked = compile_inventory(archive_inventory(archive(files), REVISION))
        self.assertEqual(blocked[0]['code'], 'proxy_auth')

    def test_unresolved_platform_variables_are_not_user_inputs(self):
        files = package(); doc = json.loads(files['example/docker-compose.yml'])
        doc['services']['web']['environment'] = {'SEED': '${APP_SEED}'}
        files['example/docker-compose.yml'] = json.dumps(doc)
        _, blocked = compile_inventory(archive_inventory(archive(files), REVISION))
        self.assertEqual(blocked[0]['code'], 'runtime_variables')

    def test_dependency_order_and_missing_or_cyclic_nodes(self):
        graph = {'app': {'dependencies': ['db', 'cache']}, 'db': {'dependencies': ['cache']}, 'cache': {'dependencies': []}}
        self.assertEqual(installation_order(graph, ['app']), ['cache', 'db', 'app'])
        self.assertEqual(installation_order(graph, ['app'], ['db']), ['cache', 'app'])
        with self.assertRaises(Error): installation_order(graph, ['missing'])
        graph['cache']['dependencies'] = ['app']
        with self.assertRaises(Error): installation_order(graph, ['app'])

    def test_inventory_cannot_hide_missing_dependencies(self):
        with self.assertRaises(Error): archive_inventory(archive(package(dependencies=['missing'])), REVISION)
        files = {**package('app', ['db']), **package('db', ['app'])}
        with self.assertRaises(Error): archive_inventory(archive(files), REVISION)

    def test_every_package_accounted_for(self):
        files = {**package('app'), **package('db')}; files['db/hooks/pre-start'] = 'false'
        inventory = archive_inventory(archive(files), REVISION)
        document, blocked = compile_inventory(inventory)
        self.assertEqual(len(document['apps']) + len(blocked), len(inventory['packages']))
        self.assertEqual(blocked[0]['id'], 'db')

    def test_legitimate_yaml_merge_but_no_duplicates_or_recursive_bombs(self):
        parsed = read_yaml(b'base: &base {a: 1, b: 2}\nservice: {<<: *base, b: 3}')
        self.assertEqual(parsed['service'], {'a': 1, 'b': 3})
        for data in (b'a: 1\na: 2', b'a: &x [*x]', b'a: !!python/object/apply:os.system [echo unsafe]',
                     b'a: ' + b'[' * 40 + b'0' + b']' * 40):
            with self.subTest(data=data), self.assertRaises(Error): read_yaml(data)
        raw = 'a: &a [1, 2]\n'
        for index in range(12):
            parent = 'a' if index == 0 else 'x' + str(index-1)
            raw += 'x%d: &x%d [%s]\n' % (index, index, ', '.join(['*'+parent] * 5))
        with self.assertRaises(Error): read_yaml(raw.encode())

    def test_unsafe_archive_entries_and_symlinks_rejected(self):
        for path in ('../escape', '/absolute', 'repo/../escape', 'repo\\escape'):
            with self.subTest(path=path), self.assertRaises(Error):
                archive_inventory(archive(extra=lambda z: z.writestr(path, 'bad')), REVISION)
        info = zipfile.ZipInfo('repo-' + REVISION + '/example/link')
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(Error):
            archive_inventory(archive(extra=lambda z: z.writestr(info, '/etc/passwd')), REVISION)

    def test_bounded_files_and_unknown_manifest(self):
        files = package(); files['example/umbrel-app.yml'] = 'x' * (256*1024+1)
        with self.assertRaises(Error): archive_inventory(archive(files), REVISION)
        files = package(); meta = json.loads(files['example/umbrel-app.yml']); meta['manifestVersion'] = 99
        files['example/umbrel-app.yml'] = json.dumps(meta)
        _, blocked = compile_inventory(archive_inventory(archive(files), REVISION))
        self.assertEqual(blocked[0]['code'], 'manifest_version')

    def test_fetch_resolves_once_then_downloads_exact_commit(self):
        raw = archive()
        with patch('titan.store_sources.download', side_effect=[json.dumps({'object': {'sha': REVISION}}).encode(), raw]) as get:
            inventory = fetch_inventory()
        self.assertEqual(inventory['revision'], REVISION)
        self.assertTrue(get.call_args_list[1].args[0].endswith('/zip/' + REVISION))
        with patch('titan.store_sources.download', return_value=raw) as get:
            fetch_inventory(REVISION)
        self.assertEqual(get.call_count, 1)
        for invalid in ('master', '../main', None):
            with patch('titan.store_sources.download', return_value=b'{}'), self.assertRaises(Error):
                fetch_inventory(invalid)


if __name__ == '__main__': unittest.main()

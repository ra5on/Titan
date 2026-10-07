"""Native offers never import an external catalog; old installations survive."""
import copy
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

from titan.app_stores import StoreMixin
from titan.catalog import APPS
from titan.core import Error
from titan.native_catalog import AVAILABLE_APP_IDS, CI_FILENAME, CI_SOURCE, load_ci_fixtures
from titan.store_recipes import recipes

FIXTURE_ID = 's5f61a2c464-runtime-stack'


class MemoryHost(StoreMixin):
    catalog_auto_bootstrap = True  # An old opt-in must not restore imports.

    def __init__(self, directory=None):
        self.rows = {}
        self.directory = directory
        self.app_config_lock = threading.RLock()

    def load(self, key, default):
        return copy.deepcopy(self.rows.get(key, default))

    def save(self, key, value):
        self.rows[key] = copy.deepcopy(value)


class NativeCatalogTests(unittest.TestCase):
    def setUp(self):
        self.original = copy.deepcopy(APPS)
        self.addCleanup(self.restore)

    def restore(self):
        APPS.clear()
        APPS.update(self.original)

    def fixture(self):
        return json.loads((Path(__file__).parent / 'fixtures/runtime-stack-store.json').read_text())

    def test_startup_and_catalog_are_local_even_with_previous_bootstrap_enabled(self):
        host = MemoryHost()
        with patch.object(host, 'store_document', side_effect=AssertionError('external fetch')) as fetch:
            host.initialize_app_stores()
            host.ensure_app_catalog()
            offered = host.op_catalog()
        fetch.assert_not_called()
        self.assertEqual({row['id'] for row in offered['apps']}, AVAILABLE_APP_IDS)
        self.assertFalse(offered['store_status']['automatic'])
        self.assertEqual(offered['skipped'], [])
        self.assertEqual(host.op_app_stores()['presets'], [])
        self.assertEqual(host.rows, {})
        self.assertEqual(host._ci_fixture_ids, set())

    def test_cached_uninstalled_recipes_never_become_offers_or_grant_ci_access(self):
        doc = self.fixture()
        _, parsed = recipes(doc, CI_SOURCE)
        recipe = next(iter(parsed.values()))
        recipe['ci_fixture'] = True
        host = MemoryHost()
        host.rows = {'app-store-sources-v4': [{'id':'saved','url':CI_SOURCE,'document':doc,'enabled':True}],
                     'installed-app-recipes-v1': {FIXTURE_ID:recipe}}
        original = copy.deepcopy(host.rows)
        host.initialize_app_stores()
        self.assertNotIn(FIXTURE_ID, APPS)
        self.assertEqual(host._ci_fixture_ids, set())
        self.assertEqual(host.op_catalog()['installed_recipes'], [])
        self.assertEqual(host.rows, original)

    def test_installed_frozen_recipe_and_registry_are_preserved_without_refresh(self):
        doc = self.fixture()
        _, parsed = recipes(doc, CI_SOURCE)
        recipe = next(iter(parsed.values()))
        recipe['name'] = 'Installed version'
        host = MemoryHost()
        host.rows = {'apps':[{'id':FIXTURE_ID}],
                     'app-store-sources-v4':[{'id':'saved','url':CI_SOURCE,'document':doc,'enabled':False}],
                     'installed-app-recipes-v1':{FIXTURE_ID:recipe}}
        original = copy.deepcopy(host.rows)
        host.initialize_app_stores()
        self.assertEqual(APPS[FIXTURE_ID]['name'], 'Installed version')
        catalog = host.op_catalog()
        self.assertEqual({row['id'] for row in catalog['apps']}, AVAILABLE_APP_IDS)
        self.assertEqual([row['id'] for row in catalog['installed_recipes']], [FIXTURE_ID])
        self.assertEqual(host.rows, original)
        self.assertEqual(host._ci_fixture_ids, set())

    def test_public_store_mutators_are_retired_without_writes_or_network(self):
        host = MemoryHost()
        with patch.object(host, 'store_document', side_effect=AssertionError('network')):
            for name, args in [('add', {'url':CI_SOURCE,'trusted':True}), ('refresh', {'store':'saved'}),
                               ('toggle', {'store':'saved','enabled':True}), ('remove', {'store':'saved'})]:
                with self.subTest(name=name), self.assertRaises(Error) as caught:
                    getattr(host, 'op_app_store_' + name)(**args)
                self.assertEqual(caught.exception.status, 410)
        self.assertEqual(host.rows, {})

    def root_stat(self, descriptor):
        metadata = self.real_fstat(descriptor)
        values = list(metadata)
        values[4] = 0
        return os.stat_result(values)

    def prepare(self, directory, **changes):
        value = {'schema':1,'disposable':True,'document':self.fixture(),'legacy_ids':['heimdall']}
        value.update(changes)
        path = directory / CI_FILENAME
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        return path

    def run_as_root(self, host):
        # Unit tests need no sudo; only ownership is substituted. Permissions,
        # descriptors, nofollow, file types, links and reads stay real.
        self.real_fstat = os.fstat
        with patch('titan.native_catalog.os.fstat', side_effect=self.root_stat):
            load_ci_fixtures(host)

    def test_root_injected_fixture_is_private_and_never_added_to_product_offers(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.prepare(directory)
            host = MemoryHost(directory)
            self.run_as_root(host)
            self.assertEqual(host._ci_fixture_ids, {'heimdall',FIXTURE_ID})
            self.assertIn(FIXTURE_ID, APPS)
            self.assertEqual({row['id'] for row in host.op_catalog()['apps']}, AVAILABLE_APP_IDS)
            self.assertEqual(host.op_catalog()['installed_recipes'], [])

    def test_test_fixture_rejects_untrusted_owner_permissions_links_and_file_types(self):
        for case in ['file_mode','directory_mode','symlink','hardlink','fifo','oversize']:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                path = self.prepare(directory)
                if case == 'file_mode':
                    path.chmod(0o644)
                elif case == 'directory_mode':
                    directory.chmod(0o777)
                elif case == 'symlink':
                    target = directory / 'target'
                    path.rename(target)
                    path.symlink_to(target)
                elif case == 'hardlink':
                    os.link(path, directory / 'second')
                elif case == 'fifo':
                    path.unlink()
                    os.mkfifo(path, 0o600)
                else:
                    path.write_bytes(b' ' * (256 * 1024 + 1))
                host = MemoryHost(directory)
                with self.assertRaises((Error, OSError, ValueError)):
                    self.run_as_root(host)
                self.assertEqual(host._ci_fixture_ids, set())
                self.assertNotIn(FIXTURE_ID, APPS)
        if os.geteuid() != 0:
            with tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                self.prepare(directory)
                host = MemoryHost(directory)
                with self.assertRaises(Error):
                    load_ci_fixtures(host)
                self.assertEqual(host._ci_fixture_ids, set())

    def test_fixture_requires_exact_disposable_shape_and_own_recipe_id(self):
        for changes in [{'disposable':False}, {'schema':2}, {'legacy_ids':['titan-nextcloud-office']},
                        {'extra':True}, {'document':{'schema':1,'name':'Other','apps':[]}}]:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                self.prepare(directory, **changes)
                host = MemoryHost(directory)
                with self.assertRaises(Error):
                    self.run_as_root(host)
                self.assertEqual(host._ci_fixture_ids, set())
                self.assertNotIn(FIXTURE_ID, APPS)


if __name__ == '__main__':
    unittest.main()

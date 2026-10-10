import copy
import json
import os
from pathlib import Path
from unittest.mock import patch
import unittest

from titan.catalog import APPS, compose
from titan.core import Error
from titan.umbrel_catalog import archive_inventory
from titan.umbrel_store import update_offer
from test_umbrel_catalog import archive, REVISION
import test_app_management as fixture


class UpdateTests(unittest.TestCase):
    setUp = fixture.AppManagementTests.setUp
    tearDown = fixture.AppManagementTests.tearDown
    command = fixture.AppManagementTests.command
    make_container = fixture.AppManagementTests.make_container

    def install_catalog_app(self):
        self.inventory = archive_inventory(archive(), REVISION)
        self.inventory['packages']['example']['compose']['services']['web']['user'] = f'{os.getuid()}:{os.getgid()}'
        with patch('titan.umbrel_store.fetch_inventory', return_value=self.inventory):
            self.host.op_app_store_refresh('umbrel')
        key = next(key for key, value in APPS.items() if value.get('umbrel_catalog'))
        self.addCleanup(APPS.pop, key, None)
        with patch('titan.app_package_setup.provision'):
            self.host.dispatch('app_install', app=key, port=8088)
        self.containers[key]['State']['Status'] = 'exited'
        return key

    def offer(self, image='example/web:2'):
        self.inventory['packages']['example']['compose']['services']['web']['image'] = image
        with patch('titan.umbrel_store.fetch_inventory', return_value=self.inventory):
            self.host.op_app_store_refresh('umbrel')

    def test_new_offer_is_pure_and_explicit_update_freezes_it(self):
        key = self.install_catalog_app()
        before = copy.deepcopy(APPS[key])
        self.offer()
        target = update_offer(self.host, key)
        self.assertEqual(APPS[key], before)
        self.assertEqual(target['image'], 'example/web:2')
        definition = compose(key, '/control', 1000, 1000, 8088, '/data', recipe=target)
        self.assertEqual(definition['services'][key]['image'], 'example/web:2')
        self.assertEqual(APPS[key], before)
        self.assertTrue(self.host.op_package_details(key)['update']['available'])
        result = self.host.op_package_update(key)
        self.assertTrue(result['kept_stopped'])
        self.assertTrue(Path(result['backup']['path']).is_file())
        self.assertEqual(APPS[key]['image'], 'example/web:2')
        self.assertEqual(self.host.load('installed-app-recipes-v1', {})[key]['image'], 'example/web:2')
        saved = json.loads((self.host.directory/'apps'/key/'compose.json').read_text())
        self.assertEqual(saved['services'][key]['image'], 'example/web:2')
        self.assertFalse(self.host.op_package_details(key)['update']['available'])

    def test_running_app_cannot_write_between_backup_and_update(self):
        key = self.install_catalog_app()
        self.containers[key]['State']['Status'] = 'running'
        self.offer()
        self.calls.clear()
        with patch('titan.app_package_setup.provision'):
            result = self.host.op_package_update(key)
        self.assertFalse(result['kept_stopped'])
        backup = next(i for i, call in enumerate(self.calls) if call[0] == 'tar')
        remove = next(i for i, call in enumerate(self.calls) if call[:2] == ['docker','rm'])
        self.assertLess(backup, remove)
        self.assertFalse(any(call[:2] == ['docker','start'] or 'up' in call for call in self.calls[backup:remove]))

    def test_mount_migration_blocks_before_backup_or_container_changes(self):
        key = self.install_catalog_app()
        self.inventory['packages']['example']['compose']['services']['web']['volumes'] = ['${APP_DATA_DIR}/new:/new']
        self.offer()
        self.calls.clear()
        with self.assertRaisesRegex(Error, 'Migration'):
            self.host.op_package_update(key)
        self.assertFalse(any(call[0] == 'tar' or call[:2] == ['docker','rm'] for call in self.calls))
        self.assertEqual(APPS[key]['image'], 'example/web:1')
        self.assertIn('Migration', self.host.op_package_details(key)['update']['blocked'])

    def test_removed_catalog_app_cannot_appear_updated(self):
        key = self.install_catalog_app()
        self.inventory['packages']['example']['files']['hooks/pre-start'] = {'size': 4}
        self.offer()
        with self.assertRaisesRegex(Error, 'nicht für Updates'):
            self.host.op_package_update(key)
        self.assertEqual(APPS[key]['image'], 'example/web:1')


if __name__ == '__main__': unittest.main()

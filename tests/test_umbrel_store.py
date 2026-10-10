import copy
import threading
import unittest
from unittest.mock import patch

from titan.app_stores import StoreMixin
from titan.catalog import APPS
from titan.core import Error
from titan.umbrel_catalog import archive_inventory
from titan.umbrel_store import CACHE, activate, load
from test_umbrel_catalog import archive, REVISION


class Host(StoreMixin):
    def __init__(self):
        self.data = {}
        self.app_config_lock = threading.RLock()
    def load(self, key, default=None): return copy.deepcopy(self.data.get(key, default))
    def save(self, key, value): self.data[key] = copy.deepcopy(value)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        previous = copy.deepcopy(APPS)
        self.addCleanup(lambda: (APPS.clear(), APPS.update(previous)))
        self.inventory = archive_inventory(archive(), REVISION)

    def refresh(self):
        with patch('titan.umbrel_store.fetch_inventory', return_value=self.inventory):
            return self.host.op_app_store_refresh('umbrel')

    def test_explicit_refresh_and_cached_restart_have_real_offers(self):
        self.assertFalse(self.host.op_catalog()['umbrel']['loaded'])
        result = self.refresh()
        self.assertEqual(result['apps'], 1)
        catalog = self.host.op_catalog()
        offers = [row for row in catalog['apps'] if row.get('umbrel_catalog')]
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]['catalog_revision'], REVISION)
        self.assertNotIn('stack', offers[0])
        self.assertEqual(catalog['umbrel']['total'], 1)
        APPS.pop(offers[0]['id'])
        _, parsed = load(self.host); activate(self.host, parsed)
        self.assertIn(offers[0]['id'], APPS)

    def test_failed_refresh_preserves_previous_catalog(self):
        self.refresh()
        before = copy.deepcopy(self.host.data)
        with patch('titan.umbrel_store.fetch_inventory', side_effect=Error('offline')):
            with self.assertRaises(Error): self.host.op_app_store_refresh('umbrel')
        self.assertEqual(self.host.data, before)

    def test_concurrent_refresh_does_not_start_a_second_download(self):
        self.host._umbrel_refresh_lock = threading.Lock()
        self.host._umbrel_refresh_lock.acquire()
        with patch('titan.umbrel_store.fetch_inventory') as fetch:
            with self.assertRaises(Error) as caught:
                self.host.op_app_store_refresh('umbrel')
            self.assertEqual(caught.exception.status, 409)
            fetch.assert_not_called()
        self.host._umbrel_refresh_lock.release()
        with patch('titan.umbrel_store.fetch_inventory', side_effect=Error('offline')):
            with self.assertRaises(Error):
                self.host.op_app_store_refresh('umbrel')
        # A failed attempt cannot permanently lock the store.
        self.assertEqual(self.refresh()['apps'], 1)

    def test_refresh_preserves_installed_recipe_and_persists_new_offer(self):
        self.refresh()
        key = next(key for key, value in APPS.items() if value.get('umbrel_catalog'))
        self.host.data['apps'] = [{'id': key}]
        original = copy.deepcopy(APPS[key])
        self.inventory['packages']['example']['compose']['services']['web']['image'] = 'example/web:2'
        self.refresh()
        self.assertEqual(APPS[key], original)
        _, offers = load(self.host)
        self.assertEqual(offers[key]['image'], 'example/web:2')

    def test_removed_uninstalled_offer_disappears(self):
        self.refresh()
        key = next(key for key, value in APPS.items() if value.get('umbrel_catalog'))
        self.inventory['packages']['example']['files']['hooks/pre-start'] = {'size': 4, 'sha256': 'a'*64}
        result = self.refresh()
        self.assertEqual(result['apps'], 0)
        self.assertNotIn(key, APPS)
        self.assertEqual(self.host.op_catalog()['umbrel']['blocked'][0]['id'], 'example')
        self.assertEqual(load(self.host)[1], {})


if __name__ == '__main__': unittest.main()

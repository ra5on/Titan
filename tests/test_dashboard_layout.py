import json
import tempfile
import unittest
from titan.core import Error, Store
from titan.dashboard_layout import TILES, load_layout, save_layout
from test_lifecycle_http import HTTPFixture


class DashboardPreferenceTests(unittest.TestCase):
    def test_persistence_is_per_account_and_completes_partial_order(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            result = save_layout(store, 'admin', {'order': ['vms', 'apps']})
            self.assertEqual(result['order'][:2], ['vms', 'apps'])
            self.assertEqual(set(result['order']), set(TILES))
            self.assertEqual(load_layout(Store(directory), 'admin'), result)
            self.assertEqual(load_layout(store, 'reader')['order'], list(TILES))
            self.assertEqual(save_layout(store, 'admin', {'order': []})['order'], list(TILES))

    def test_unknown_duplicate_and_injected_actor_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            for value in ({'order': ['vms', 'vms']}, {'order': ['root']}, {'order': [1]},
                          {'order': None}, {'order': 'vms'}, {'order': [], 'user': 'reader'}):
                with self.subTest(value=value), self.assertRaises(Error): save_layout(store, 'admin', value)

    def test_damaged_saved_preferences_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            for value in (None, [], {'order': ['bad']}, {'order': ['vms', 'vms']}):
                store.set_config('dashboard-layout:admin', value)
                self.assertEqual(load_layout(store, 'admin')['order'], list(TILES))


class DashboardHTTPTests(HTTPFixture, unittest.TestCase):
    def test_login_and_csrf_required(self):
        self.assertEqual(self.request('/api/dashboard-layout', actor=None)[0], 401)
        self.assertEqual(self.request('/api/dashboard-layout', {'order': []}, csrf='bad')[0], 403)
        self.assertEqual(self.request('/api/dashboard-layout', {'order': []}, headers={'Origin': 'https://foreign.invalid'})[0], 403)

    def test_current_account_only_and_persisted_get(self):
        status, result, _ = self.json_request('/api/dashboard-layout', {'order': ['vms']})
        self.assertEqual(status, 200)
        self.assertEqual(result['order'][0], 'vms')
        self.assertEqual(self.json_request('/api/dashboard-layout')[1], result)
        self.assertEqual(self.json_request('/api/dashboard-layout', actor='reader')[1]['order'], list(TILES))
        self.assertEqual(self.request('/api/dashboard-layout', {'order': [], 'name': 'reader'})[0], 400)
        self.agent.call.assert_not_called()

    def test_vm_options_are_admin_only_and_dispatch(self):
        self.assertEqual(self.request('/api/vm-options', actor=None)[0], 401)
        self.assertEqual(self.request('/api/vm-options', actor='reader')[0], 403)
        self.agent.call.assert_not_called()
        self.agent.call.return_value = {'storage': [], 'disk_images': [], 'cpu_topology': {'online': [0]}}
        self.assertEqual(self.json_request('/api/vm-options')[0], 200)
        self.agent.call.assert_called_once_with('vm_options')

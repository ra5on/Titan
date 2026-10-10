import io
import json
import unittest
import zipfile
from test_lifecycle_http import HTTPFixture


class ColdRecoveryHTTPTests(HTTPFixture, unittest.TestCase):
    def test_plan_and_kit_require_admin_and_reject_parameters(self):
        for endpoint in ('inventory', 'kit'):
            path = '/api/recovery/' + endpoint
            for actor, status in ((None, 401), ('reader', 403)):
                self.assertEqual(self.request(path, actor=actor)[0], status)
            for query in ('?target=/dev/sda', '?target='):
                self.assertEqual(self.request(path + query)[0], 400)
        self.agent.call.assert_not_called()

    def test_inventory_is_uncached_and_kit_contains_exact_inventory_and_reader(self):
        value = {'format': 'titan-cold-recovery-v1', 'disks': [{'id': 'disk-001'}]}
        self.agent.call.return_value = value
        status, body, headers = self.json_request('/api/recovery/inventory')
        self.assertEqual((status, body), (200, value))
        self.assertEqual(headers['Cache-Control'], 'no-store')
        status, body, headers = self.request('/api/recovery/kit')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn('attachment;', headers['Content-Disposition'])
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            self.assertEqual(set(archive.namelist()), {'inventory.json', 'titan-recovery.py', 'START.txt'})
            self.assertEqual(json.loads(archive.read('inventory.json')), value)
            compile(archive.read('titan-recovery.py'), 'titan-recovery.py', 'exec')

    def test_demo_does_not_export_a_real_recovery_plan(self):
        self.app.store.create_user("demo", "demo-original-password", "admin", "demo")
        self.app.demo = True
        for endpoint in ('inventory', 'kit'):
            self.assertEqual(self.request('/api/recovery/' + endpoint)[0], 409)
        self.agent.call.assert_not_called()

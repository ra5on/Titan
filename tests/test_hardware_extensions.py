import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET
from titan.vm_usb import inventory, assigned, USBMixin
from titan.hardware import gpus
from titan.app_stores import recipes, store_url
from titan.catalog import APPS, compose
from titan.core import Error


class HardwareTests(unittest.TestCase):
    def test_usb_unique_hub_storage_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, kind in [('1-1', '03'), ('1-2', '08'), ('usb1', '09')]:
                device = root / name
                device.mkdir()
                for key, value in {'idVendor': '1234', 'idProduct': 'abcd' if kind == '03' else kind + '00', 'bDeviceClass': kind}.items():
                    (device / key).write_text(value)
            rows = inventory(root)
            self.assertEqual([r['id'] for r in rows if not r['blocked']], ['1234:abcd'])
            copy = root / '1-3'; copy.mkdir()
            (copy / 'idVendor').write_text('1234'); (copy / 'idProduct').write_text('abcd')
            self.assertTrue(all(r['blocked'] for r in inventory(root)))

    def test_gpu_reports_bound_driver_and_vfio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); device = root / '0000:01:00.0'; device.mkdir()
            (device / 'class').write_text('0x030000'); (device / 'vendor').write_text('0x10de')
            (device / 'device').write_text('0x1234')
            self.assertFalse(gpus(root)[0]['bound'])
            driver = root / 'vfio-pci'; driver.mkdir()
            (device / 'driver').symlink_to(driver)
            self.assertTrue(gpus(root)[0]['passthrough'])

    def test_usb_offline_edit_and_unavailable_fail_closed(self):
        class Host(USBMixin):
            def managed_vm(self, vm):
                return {'id': vm, 'xml': '<domain><devices/></domain>', 'state': self.state}
            def redefine_vm(self, record, root):
                self.xml = root
        host = Host(); host.state = 'running'
        with self.assertRaises(Error): host.op_vm_usb_update('vm', [])
        host.state = 'shut off'
        with patch.object(host, 'op_vm_usb', return_value={'devices': [{'id': '1234:abcd', 'blocked': False}]}):
            host.op_vm_usb_update('vm', ['1234:abcd'])
            self.assertEqual(assigned(host.xml), ['1234:abcd'])
            self.assertEqual(host.xml.find('./devices/hostdev/source').get('startupPolicy'), 'mandatory')
            with self.assertRaises(Error): host.op_vm_usb_update('vm', ['0000:0000'])
        host.op_vm_usb_update('vm', [])
        self.assertEqual(assigned(host.xml), [])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.url = 'https://raw.githubusercontent.com/example/apps/main/titan-store.json'
        self.item = {'id': 'demo', 'name': 'Demo', 'description': 'Test app', 'image': 'example/demo:1',
                     'port': 8080, 'documentation': 'https://example.org/docs', 'login_note': 'Create an account.',
                     'environment': {'EXAMPLE': '${DO_NOT_EXPAND}'}}
        self.document = {'schema': 1, 'name': 'Example', 'apps': [self.item]}

    def test_store_compiles_fixed_container_with_literal_environment(self):
        name, parsed = recipes(self.document, self.url)
        identifier, recipe = next(iter(parsed.items()))
        APPS[identifier] = recipe
        try:
            service = compose(identifier, '/private', 1000, 1000, 9090, '/data')['services'][identifier]
            self.assertEqual(service['ports'], ['9090:8080'])
            self.assertEqual(service['environment']['EXAMPLE'], '$${DO_NOT_EXPAND}')
            self.assertNotIn('privileged', service)
            self.assertEqual(recipe['first_login']['instructions'], 'Create an account.')
        finally:
            APPS.pop(identifier)

    def test_editable_environment_and_port_defaults(self):
        self.item['ports'] = [{'target': 9000, 'published': 9100, 'protocol': 'udp'}]
        self.item['settings'] = [{'env': 'PASSWORD', 'label': 'Passwort', 'default': '', 'secret': True}]
        _, parsed = recipes(self.document, self.url)
        identifier, recipe = next(iter(parsed.items()))
        APPS[identifier] = recipe
        try:
            with self.assertRaises(Error): compose(identifier, '/private', 1, 1, 8080, '/data')
            service = compose(identifier, '/private', 1, 1, 8080, '/data', {'setting_0': 'a$b', 'port_0': 9200})['services'][identifier]
            self.assertEqual(service['environment']['PASSWORD'], 'a$$b')
            self.assertIn('9200:9000/udp', service['ports'])
        finally:
            APPS.pop(identifier)

    def test_store_persists_recipe_and_protects_installed_apps(self):
        from titan.app_stores import StoreMixin
        import io
        class Host(StoreMixin):
            def __init__(self): self.records = {}
            def load(self, key, default): return self.records.get(key, default)
            def save(self, key, value): self.records[key] = value
        host = Host()
        with self.assertRaises(Error): host.op_app_store_add(self.url)
        import json
        with patch('titan.app_stores.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value = io.BytesIO(json.dumps(self.document).encode())
            host.op_app_store_add(self.url, trusted=True)
        row = host.op_app_stores()['stores'][0]
        _, parsed = recipes(self.document, self.url)
        identifier = next(iter(parsed))
        try:
            host.records['apps'] = [{'id': identifier}]
            with self.assertRaises(Error): host.op_app_store_remove(row['id'])
            APPS.pop(identifier)
            host.initialize_app_stores()
            self.assertIn(identifier, APPS)
            host.records['apps'] = []
            host.op_app_store_remove(row['id'])
            self.assertNotIn(identifier, APPS)
            self.assertEqual(host.op_app_stores()['stores'], [])
        finally:
            APPS.pop(identifier, None)

    def test_store_rejects_privileged_and_socket_recipe(self):
        for key, value in [('privileged', True), ('devices', ['/dev/sda']), ('command', 'evil')]:
            with self.subTest(key=key):
                self.item[key] = value
                with self.assertRaises(Error): recipes(self.document, self.url)
                del self.item[key]
        self.item['image'] = '${HOST_SECRET}'
        with self.assertRaises(Error): recipes(self.document, self.url)

    def test_only_public_raw_github_no_credentials_queries_or_redirect_hosts(self):
        self.assertEqual(store_url(self.url), self.url)
        for value in ['http://localhost/a.json', 'https://raw.githubusercontent.com@localhost/a.json',
                      self.url + '?token=secret', 'https://example.com/store.json']:
            with self.assertRaises(Error): store_url(value)

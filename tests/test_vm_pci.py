import os
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from titan.core import Error
from titan.vm_pci import PCIMixin, apply, assigned, inventory

DOMAIN = "<domain><name>gast</name><devices><disk/><hostdev mode='subsystem' type='usb'><source><vendor id='0x1234'/></source></hostdev></devices></domain>"
NAMES = {('10de', '2684'): 'GeForce RTX 4090', ('8086', '56a0'): 'Arc A770'}


class DefinitionTests(unittest.TestCase):
    def test_devices_round_trip_and_usb_passthrough_is_kept(self):
        root = apply(ET.fromstring(DOMAIN), ['0000:01:00.0', '0000:01:00.1'])
        self.assertEqual(assigned(root), ['0000:01:00.0', '0000:01:00.1'])
        node = root.find("./devices/hostdev[@type='pci']")
        self.assertEqual(node.get('managed'), 'yes')
        self.assertEqual(node.find('./source/address').attrib, {'domain': '0x0000', 'bus': '0x01', 'slot': '0x00', 'function': '0x0'})
        self.assertEqual(len(root.findall("./devices/hostdev[@type='usb']")), 1)
        self.assertEqual(assigned(apply(root, [])), [])

    def test_malformed_addresses_in_a_definition_are_ignored(self):
        root = ET.fromstring("<domain><devices><hostdev type='pci'><source><address domain='zz' bus='0x01' slot='0x00' function='0x0'/></source></hostdev>"
                             "<hostdev type='pci'><source/></hostdev></devices></domain>")
        self.assertEqual(assigned(root), [])


@unittest.skipUnless(os.name == 'posix', 'the sysfs fixture uses symbolic links')
class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / 'devices'
        self.groups = Path(self.temporary.name) / 'groups'
        self.root.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def device(self, address, class_code, vendor='0x10de', product='0x2684', group=None, driver=None, boot_vga=None):
        path = self.root / address
        path.mkdir()
        (path / 'class').write_text(class_code + '\n')
        (path / 'vendor').write_text(vendor + '\n')
        (path / 'device').write_text(product + '\n')
        if boot_vga is not None:
            (path / 'boot_vga').write_text(boot_vga + '\n')
        if group is not None:
            (self.groups / group).mkdir(parents=True, exist_ok=True)
            (path / 'iommu_group').symlink_to(self.groups / group)
        if driver:
            target = Path(self.temporary.name) / 'drivers' / driver
            target.mkdir(parents=True, exist_ok=True)
            (path / 'driver').symlink_to(target)

    def test_graphics_card_moves_with_its_audio_function_and_bridges_stay(self):
        self.device('0000:00:01.0', '0x060400', group='12')
        self.device('0000:01:00.0', '0x030000', group='12', driver='nvidia', boot_vga='0')
        self.device('0000:01:00.1', '0x040300', product='0x22ba', group='12')
        self.device('0000:02:00.0', '0x020000', vendor='0x8086', group='13')
        found = inventory(self.root, NAMES)
        self.assertEqual(len(found), 1)
        card = found[0]
        self.assertEqual((card['address'], card['kind'], card['name']), ('0000:01:00.0', 'gpu', 'NVIDIA GeForce RTX 4090'))
        self.assertEqual(card['companions'], ['0000:01:00.1'])
        self.assertFalse(card['blocked'])
        self.assertNotIn('warning', card)

    def test_shared_group_and_missing_iommu_block_passthrough_with_a_reason(self):
        self.device('0000:01:00.0', '0x030000', group='5')
        self.device('0000:03:00.0', '0x010802', vendor='0x144d', group='5')
        self.device('0000:04:00.0', '0x030000', vendor='0x8086', product='0x56a0')
        shared, missing = inventory(self.root, NAMES)
        self.assertTrue(shared['blocked'])
        self.assertIn('0000:03:00.0', shared['reason'])
        self.assertTrue(missing['blocked'])
        self.assertTrue(missing['reason'].startswith('IOMMU ist nicht aktiv'))
        self.assertEqual(missing['name'], 'Intel Arc A770')

    def test_host_display_card_is_offered_with_a_warning(self):
        self.device('0000:01:00.0', '0x030000', group='1', boot_vga='1')
        self.assertIn('Monitor am NAS', inventory(self.root, NAMES)[0]['warning'])


class Host(PCIMixin):
    def __init__(self, devices, state='shut off', other=''):
        self.devices, self.state, self.other, self.saved = devices, state, other, None

    def managed_vm(self, vm):
        return {'id': 'vm-1', 'state': self.state, 'xml': DOMAIN}

    def command(self, args, **kwargs):
        if args[:2] == ['virsh', 'list']:
            return 'vm-1\nvm-2\n'
        return "<domain><name>anderer-gast</name><devices>" + self.other + "</devices></domain>"

    def redefine_vm(self, record, root):
        self.saved = root


class UpdateTests(unittest.TestCase):
    def host(self, **kwargs):
        from unittest.mock import patch
        devices = [{'address': '0000:01:00.0', 'kind': 'gpu', 'name': 'NVIDIA GeForce', 'driver': 'nvidia', 'boot_vga': False,
                    'companions': ['0000:01:00.1'], 'blocked': False, 'reason': ''},
                   {'address': '0000:05:00.0', 'kind': 'gpu', 'name': 'AMD', 'driver': None, 'boot_vga': False,
                    'companions': [], 'blocked': True, 'reason': 'Teilt sich die IOMMU-Gruppe mit anderen Geräten (0000:06:00.0).'}]
        patcher = patch('titan.vm_pci.inventory', side_effect=lambda root: [dict(item) for item in devices])
        patcher.start()
        self.addCleanup(patcher.stop)
        return Host(devices, **kwargs)

    def test_selected_card_is_saved_together_with_its_companion_functions(self):
        host = self.host()
        result = host.op_vm_pci_update('vm-1', ['0000:01:00.0'])
        self.assertEqual(result['passed'], ['0000:01:00.0', '0000:01:00.1'])
        self.assertEqual(assigned(host.saved), ['0000:01:00.0', '0000:01:00.1'])

    def test_running_vm_blocked_devices_and_bad_input_are_rejected(self):
        with self.assertRaises(Error) as running:
            self.host(state='running').op_vm_pci_update('vm-1', ['0000:01:00.0'])
        self.assertEqual(running.exception.status, 409)
        host = self.host()
        for devices in (['0000:05:00.0'], ['0000:09:00.0'], ['../etc'], 'x', ['0000:01:00.0'] * 2, ['0000:01:00.0'] * 5):
            with self.assertRaises(Error):
                host.op_vm_pci_update('vm-1', devices)
        self.assertIsNone(host.saved)

    def test_device_of_another_vm_cannot_be_taken(self):
        other = "<hostdev type='pci'><source><address domain='0x0000' bus='0x01' slot='0x00' function='0x1'/></source></hostdev>"
        host = self.host(other=other)
        listing = host.op_vm_pci('vm-1')
        self.assertEqual(listing['devices'][0]['reason'], 'Zugeordnet: anderer-gast')
        with self.assertRaises(Error):
            host.op_vm_pci_update('vm-1', ['0000:01:00.0'])


if __name__ == '__main__':
    unittest.main()

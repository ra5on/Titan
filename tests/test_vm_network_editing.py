import unittest
import xml.etree.ElementTree as ET
from titan.core import Error
from titan.vm_extensions import VMExtensionsMixin
from titan.vm_networks import VMNetworkMixin


class NetworkHost(VMExtensionsMixin, VMNetworkMixin):
    def __init__(self):
        self.xml = '<domain><uuid>test-vm</uuid><devices><interface type="network"><source network="default"/><mac address="52:54:00:00:00:01"/><address type="pci" slot="0x03"/></interface><interface type="network"><source network="default"/><mac address="52:54:00:00:00:02"/><address type="pci" slot="0x04"/></interface></devices></domain>'
        self.state = 'shut off'
    def managed_vm(self, vm): return {'xml': self.xml, 'state': self.state}
    def redefine_vm(self, record, root): self.xml = ET.tostring(root, encoding='unicode')
    def vm_network_choices(self): return {'networks': [{'name': 'default'}, {'name': 'isolated'}], 'bridges': [], 'interfaces': []}
    def command(self, *args, **kwargs): return ''


class NetworkEditingTests(unittest.TestCase):
    def test_editing_second_card_preserves_first_card_and_pci_order(self):
        host = NetworkHost()
        before = ET.fromstring(host.xml).findall('./devices/interface')
        host.op_vm_nic_update('test-vm', 1, {'mode': 'network', 'source': 'isolated', 'model': 'e1000', 'mac': '52:54:00:00:00:02', 'connected': False})
        after = ET.fromstring(host.xml).findall('./devices/interface')
        self.assertEqual(ET.tostring(before[0]), ET.tostring(after[0]))
        self.assertEqual(after[1].find('source').get('network'), 'isolated')
        self.assertEqual(after[1].find('address').get('slot'), '0x04')
        self.assertEqual(after[1].find('link').get('state'), 'down')

    def test_running_and_duplicate_mac_are_rejected_without_redefinition(self):
        host = NetworkHost()
        before = host.xml
        with self.assertRaises(Error):
            host.op_vm_nic_update('test-vm', 1, {'mac': '52:54:00:00:00:01'})
        host.state = 'running'
        with self.assertRaises(Error):
            host.op_vm_nic_update('test-vm', 1, {'source': 'isolated'})
        self.assertEqual(host.xml, before)

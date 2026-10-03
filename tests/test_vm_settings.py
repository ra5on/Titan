from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import test_vm_lifecycle as lifecycle
import test_vm_management as management
from titan.core import Error

class SettingsTests(unittest.TestCase):
    setUp = management.VMManagementTests.setUp
    tearDown = management.VMManagementTests.tearDown
    command = management.VMManagementTests.command
    def test_firmware_roundtrip_keeps_uuid_controller_addresses_disk_and_vars(self):
        with patch.object(self.host,'validate_vm_firmware'):
            self.host.op_vm_update(self.vm_id,2,2048,firmware='uefi')
        uefi=ET.fromstring(self.metadata.read_text())
        self.assertEqual(uefi.findtext('uuid'),self.vm_id)
        nvram=uefi.findtext('./os/nvram')
        self.xml=ET.tostring(uefi,encoding='unicode')
        self.host.op_vm_update(self.vm_id,2,2048,firmware='bios')
        bios=ET.fromstring(self.metadata.read_text());self.assertIsNone(bios.find('./os/loader'));self.assertIsNone(bios.find('./os/nvram'))
        self.xml=ET.tostring(bios,encoding='unicode')
        with patch.object(self.host,'validate_vm_firmware'):
            self.host.op_vm_update(self.vm_id,2,2048,firmware='uefi')
        self.assertEqual(ET.fromstring(self.metadata.read_text()).findtext('./os/nvram'),nvram)
        self.assertEqual(self.disk.read_bytes(),b'retained virtual disk')

    def test_network_models_sources_link_mac_and_pxe_are_saved(self):
        choices={'networks':[{'name':'default'}],'bridges':['br0'],'interfaces':['eth0']}
        for mode,source in [('network','default'),('bridge','br0'),('direct','eth0'),('none','')]:
            with self.subTest(mode=mode),patch.object(self.host,'vm_network_choices',return_value=choices):
                value={'mode':mode,'source':source,'model':'e1000','mac':'52:54:00:12:34:56','connected':False}
                self.host.op_vm_update(self.vm_id,2,2048,network=value,boot='network')
                root=ET.fromstring(self.metadata.read_text())
                self.assertEqual(root.find('./os/boot').get('dev'),'network')
                self.assertEqual(self.host.vm_network_info(root)['mode'],mode)
                if mode!='none':self.assertFalse(self.host.vm_network_info(root)['connected'])

    def test_duplicate_mac_is_rejected_without_redefinition(self):
        other=ET.fromstring(self.xml);ET.SubElement(other.find('./devices/interface'),'mac',address='52:54:00:12:34:56')
        other.find('uuid').text='11111111-1111-1111-1111-111111111111'
        def command(args,**kwargs):
            if args[:2]==['virsh','list']:return other.findtext('uuid')
            if args[:2]==['virsh','dumpxml'] and args[2]==other.findtext('uuid'):return ET.tostring(other,encoding='unicode')
            return self.command(args,**kwargs)
        with patch.object(self.host,'command',side_effect=command),patch.object(self.host,'vm_network_choices',return_value={'networks':[{'name':'default'}]}):
            with self.assertRaisesRegex(Error,'MAC-Adresse'):
                self.host.op_vm_update(self.vm_id,2,2048,network={'mac':'52:54:00:12:34:56'})
        self.assertEqual(self.metadata.read_text(),self.xml)

    def test_bad_network_is_rejected_without_redefinition(self):
        for value in [{'mode':'host'}, {'mode':'bridge','source':'missing'}, {'mac':'ff:ff:ff:ff:ff:ff'}, {'connected':'false'}, {'model':'command'}, {'mode':'none','command':'evil'}]:
            with self.subTest(value=value),patch.object(self.host,'vm_network_choices',return_value={'networks':[],'bridges':[],'interfaces':[]}):
                self.calls.clear()
                with self.assertRaises(Error):self.host.op_vm_update(self.vm_id,2,2048,network=value)
                self.assertFalse(any(c[1]=='define' for c in self.calls))

class ReuseTests(unittest.TestCase):
    setUp = lifecycle.VMLifecycleTests.setUp
    tearDown = lifecycle.VMLifecycleTests.tearDown
    creation_command = lifecycle.VMLifecycleTests.creation_command
    def test_deleted_name_gets_fresh_instance_without_touching_retained_disk(self):
        self.host.save('vms',[]);self.metadata.unlink()
        before=self.disk.read_bytes()
        with patch.object(self.host,'op_vms',return_value={'available':True,'vms':[]}),patch.object(self.host,'vm_network_ready'),patch('titan.host.pwd.getpwnam',return_value=SimpleNamespace(pw_uid=1001,pw_gid=1001)),patch('titan.host.os.chown'),patch('titan.host.run',side_effect=self.creation_command()):
            result=self.host.op_vm_create('linux',1,1024,8,self.iso.name)
        new=Path(result['disk_path']);self.assertNotEqual(new,self.disk)
        self.assertTrue(new.exists());self.assertEqual(self.disk.read_bytes(),before)
        self.assertEqual(self.host.vm_disk_storage('linux',new),'system')
        xml=ET.fromstring(self.metadata.read_text())
        self.assertEqual(xml.find('./devices/disk/source').get('file'),str(new))

    def test_retained_uefi_variables_get_a_new_instance_path(self):
        self.host.save('vms',[]);self.metadata.unlink()
        variables=self.root/'titan-linux_VARS.fd';variables.write_bytes(b'old boot variables')
        with patch.object(self.host,'vm_nvram_path',side_effect=lambda name:self.root/('titan-'+name+'_VARS.fd')),patch.object(self.host,'validate_vm_firmware'),patch.object(self.host,'op_vms',return_value={'available':True,'vms':[]}),patch.object(self.host,'vm_network_ready'),patch('titan.host.pwd.getpwnam',return_value=SimpleNamespace(pw_uid=1001,pw_gid=1001)),patch('titan.host.os.chown'),patch('titan.host.run',side_effect=self.creation_command()):
            self.host.op_vm_create('linux',1,1024,8,self.iso.name,firmware='uefi')
        root=ET.fromstring(self.metadata.read_text())
        self.assertNotEqual(root.findtext('./os/nvram'),str(variables))
        self.assertEqual(variables.read_bytes(),b'old boot variables')

    def test_unique_instance_paths_remain_strictly_managed(self):
        for filename in ('linux--evil.qcow2','other--'+'a'*32+'.qcow2','linux--'+'a'*32+'.raw','../linux.qcow2'):
            with self.assertRaises(Error):self.host.vm_disk_storage('linux',self.vm_root/filename)

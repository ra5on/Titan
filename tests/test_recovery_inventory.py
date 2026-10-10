"""Inventory must not silently omit inactive VM disks or unavailable pools."""
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from titan.core import Error
from titan.recovery_host import inventory


class RecoveryInventoryTests(unittest.TestCase):
    def setUp(self):
        self.target=Path('/backup')
        self.host=SimpleNamespace(backups=SimpleNamespace(settings=lambda:{'target':'external'},validate_target=lambda value:self.target),
            directory=Path('/agent'),vm_root=Path('/vms'),volume_manager=SimpleNamespace(records=lambda:[],require=Mock()),
            op_shares=lambda:[{'path':'/shares/photos'}],command=Mock(return_value='<domain><devices/></domain>'))
        self.records={'pools':[],'apps':[],'vms':[]}
        self.host.load=lambda name,default:self.records.get(name,default)
        self.devices=[]
        def stat(path):
            self.devices.append(str(path))
            return SimpleNamespace(st_dev=1 if str(path).startswith('/backup') else 2)
        self.addCleanup(patch.stopall)
        patch.object(Path,'exists',return_value=True).start()
        patch.object(Path,'stat',stat).start()
        patch('titan.recovery_host.recovery.block_inventory',return_value=[]).start()
        patch('titan.recovery_host.recovery.disk_for_device',side_effect=lambda disks,device:{'identity':'serial:backup' if device==1 else 'serial:source'}).start()
        self.live=patch('titan.recovery_host.recovery.live_inventory',return_value={'disks':['complete']}).start()
        self.run=patch('titan.host.run',return_value='').start()

    def test_inactive_vm_extra_disk_iso_and_nvram_are_checked(self):
        self.records['vms']=[{'id':'vm-1','name':'Test'}]
        self.host.command.return_value='''<domain><os><nvram>/extra/vars.fd</nvram></os><devices>
          <disk device="disk"><source file="/extra/guest.qcow2"/></disk>
          <disk device="disk"><source file="/extra/second.qcow2"/></disk>
          <disk device="cdrom"><source file="/extra/install.iso"/></disk>
        </devices></domain>'''
        self.assertEqual(inventory(self.host),{'disks':['complete']})
        self.host.command.assert_called_once_with(['virsh','dumpxml','vm-1','--inactive'],timeout=10)
        for path in ('/extra/guest.qcow2','/extra/second.qcow2','/extra/install.iso','/extra/vars.fd'):
            self.assertIn(path,self.devices)

    def test_vm_data_on_backup_disk_is_rejected(self):
        self.records['vms']=[{'id':'vm-1','name':'Test'}]
        self.host.command.return_value='<domain><devices><disk><source file="/backup/guest.qcow2"/></disk></devices></domain>'
        with self.assertRaisesRegex(Error,'derselben physischen Platte'): inventory(self.host)
        self.live.assert_not_called()

    def test_network_and_block_vm_sources_are_not_claimed_complete(self):
        self.records['vms']=[{'id':'vm-1','name':'Test'}]
        for source in ('<source protocol="rbd" name="remote"/>','<source dev="/dev/sdz"/>'):
            self.host.command.return_value='<domain><devices><disk>'+source+'</disk></devices></domain>'
            with self.assertRaisesRegex(Error,'nicht lokal sicherbaren'): inventory(self.host)
        self.live.assert_not_called()

    def test_missing_registered_pool_is_rejected_even_when_other_pool_online(self):
        self.records['pools']=[{'name':'missing'}]
        self.run.return_value='other\tONLINE'
        with self.assertRaisesRegex(Error,'vollständig online'): inventory(self.host)
        self.live.assert_not_called()

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from titan.core import Error
from titan.demo import Demo


class DemoPackagesVMTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.demo=Demo(Path(self.temporary.name)/'files')
        self.vm=self.demo.vms[0]['id']

    def tearDown(self):
        self.demo._temporary.cleanup()
        self.temporary.cleanup()

    def stop(self): self.demo.call('vm_action',vm=self.vm,action='shutdown')

    def test_nextcloud_dependencies_and_private_credentials(self):
        options={'username':'administrator','password':'Chosen-private-password','nas_host':'nas.local'}
        self.demo.call('app_install',app='titan-nextcloud-office',port=18088,options=options)
        details=self.demo.call('package_details',app='titan-nextcloud-office')
        self.assertTrue(details['ready'])
        self.assertEqual(details['total_services'],6)
        self.assertTrue(next(service for service in details['services'] if service['id'].endswith('-office-init'))['ready'])
        self.assertEqual(details['login']['username'],'administrator')
        for key in ('password','database_password','office_secret'):
            self.assertNotIn(self.demo._app_settings['titan-nextcloud-office'][key],json.dumps(details))

    def test_available_packages_and_service_log_scope(self):
        self.assertFalse(self.demo.call('package_details',app='titan-immich')['installed'])
        self.demo.call('app_install',app='titan-immich',port=18283)
        with self.assertRaises(Error): self.demo.call('package_logs',app='titan-immich',service='foreign')
        logs=self.demo.call('package_logs',app='titan-immich',service='titan-immich-database')
        self.assertIn('[Demo]',logs['logs'])

    def test_actual_install_form_payload_accepts_empty_hardware_and_all_immich_services(self):
        payload={'app':'titan-immich','port':2283,'share':None,'network':{'mode':'default'},'hardware':[]}
        with patch('titan.app_devices.devices',side_effect=AssertionError('Demo must never inspect real devices')):
            self.demo.call('app_install',**payload)
        details=self.demo.call('package_details',app='titan-immich')
        self.assertTrue(details['ready'])
        self.assertEqual(details['total_services'],4)
        self.assertEqual({service['id'] for service in details['services']},{'titan-immich','titan-immich-database','titan-immich-redis','titan-immich-immich-machine-learning'})
        self.assertTrue(all(service['ready'] for service in details['services']))

    def test_install_hardware_and_stack_network_match_production_constraints(self):
        for hardware in (['/dev/dri/renderD128'], 'usb', [1]):
            with self.subTest(hardware=hardware),self.assertRaises(Error):
                self.demo.call('app_install',app='titan-immich',port=2283,hardware=hardware)
        with self.assertRaisesRegex(Error,'isoliertes Standardnetz'):
            self.demo.call('app_install',app='titan-immich',port=2283,hardware=[],network={'mode':'host'})
        with self.assertRaisesRegex(Error,'Installationsparameter'):
            self.demo.call('app_install',app='titan-immich',port=2283,hardware=[],unexpected=True)
        self.assertFalse(any(item['id']=='titan-immich' for item in self.demo.apps))

    def test_live_and_private_package_settings_are_rejected(self):
        self.demo.call('app_install',app='titan-immich',port=18283)
        with self.assertRaises(Error): self.demo.call('package_settings',app='titan-immich',port=18284)
        self.demo.call('app_action',app='titan-immich',action='stop')
        with self.assertRaises(Error): self.demo.call('package_settings',app='titan-immich',port=18284,options={'database_password':'changed'})
        self.demo.call('package_settings',app='titan-immich',port=18284)
        self.assertEqual(self.demo.call('package_details',app='titan-immich')['port'],18284)

    def test_offline_hardware_snapshot_and_clone_persist(self):
        with self.assertRaises(Error): self.demo.call('vm_disk_add',vm=self.vm,disk_gb=12)
        self.stop()
        self.demo.call('vm_disk_add',vm=self.vm,disk_gb=12)
        self.demo.call('vm_nic_add',vm=self.vm,network={'mode':'network','source':'default','model':'virtio','connected':True})
        self.demo.call('vm_guest_agent',vm=self.vm,enabled=True)
        snapshot=self.demo.call('vm_snapshot_create',vm=self.vm,name='Baseline')['snapshot']
        with self.assertRaises(Error): self.demo.call('vm_disk_add',vm=self.vm,disk_gb=1)
        self.demo.call('vm_guest_agent',vm=self.vm,enabled=False)
        self.demo.call('vm_snapshot_restore',vm=self.vm,snapshot=snapshot['id'])
        self.assertTrue(self.demo.call('vm_extensions',vm=self.vm)['guest_agent']['configured'])
        clone=self.demo.call('vm_clone',vm=self.vm,name='clone')['id']
        hardware=self.demo.call('vm_extensions',vm=clone)
        self.assertEqual(len(hardware['disks']),2)
        self.assertEqual(len(hardware['networks']),2)
        self.assertEqual(hardware['snapshots'],[])
        self.assertNotEqual(hardware['disks'][0]['disk'],self.demo.call('vm_extensions',vm=self.vm)['disks'][0]['disk'])

    def test_guest_actions_require_realistic_demo_agent_state(self):
        with self.assertRaises(Error): self.demo.call('vm_guest_action',vm=self.vm,action='shutdown')
        self.stop()
        self.demo.call('vm_guest_agent',vm=self.vm,enabled=True)
        self.demo.call('vm_action',vm=self.vm,action='start')
        self.demo.call('vm_guest_action',vm=self.vm,action='shutdown')
        self.assertEqual(self.demo.vm(self.vm)['state'],'shut off')

    def test_stopped_vm_has_zero_io_and_live_disk_totals_cover_all_disks(self):
        self.stop()
        self.demo.call('vm_disk_add',vm=self.vm,disk_gb=16)
        vm=self.demo.call('vms')['vms'][0]
        self.assertEqual(vm['virtual_size'],32*1024**3)
        self.assertEqual(vm['disk_total_capacity_bytes'],48*1024**3)
        self.assertEqual(vm['disk_count'],2)
        for key in ('cpu_percent','memory_resident_bytes','disk_read_bps','disk_write_bps','network_rx_bps','network_tx_bps'):
            self.assertEqual(vm['metrics'][key],0,key)
        self.demo.call('vm_action',vm=self.vm,action='start')
        vm=self.demo.call('vms')['vms'][0]
        self.assertGreater(vm['metrics']['disk_read_bps'],0)
        self.demo.call('vm_action',vm=self.vm,action='suspend')
        vm=self.demo.call('vms')['vms'][0]
        self.assertGreater(vm['metrics']['memory_resident_bytes'],0)
        for key in ('cpu_percent','disk_read_bps','disk_write_bps','network_rx_bps','network_tx_bps'):
            self.assertEqual(vm['metrics'][key],0,key)

    def test_external_demo_backup_restores_all_disks_and_nics(self):
        self.stop()
        self.demo.call('vm_disk_add',vm=self.vm,disk_gb=24)
        self.demo.call('vm_nic_add',vm=self.vm,network={'mode':'network','source':'default','model':'virtio','connected':True})
        backup=self.demo.call('vm_backup',vm=self.vm,target='/var/media/demo-backup')['backup']['id']
        restored=self.demo.call('vm_restore',backup=backup,name='restored')['id']
        hardware=self.demo.call('vm_extensions',vm=restored)
        self.assertEqual(len(hardware['disks']),2)
        self.assertEqual(len(hardware['networks']),2)
        self.assertEqual(hardware['state'],'shut off')


if __name__=='__main__':unittest.main()

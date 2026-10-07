"""Real qcow2 checkpoints/clone roundtrips without requiring a running KVM host."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid
import xml.etree.ElementTree as ET

from titan.core import Error
from titan.vm_management import VMMixin
from titan.vm_networks import VMNetworkMixin
from titan.vm_storage import VMStorageMixin
from titan.locations import LocationsMixin
from titan.storage_locations import StorageLocations
from titan.backups import Backups


class FixtureHost(LocationsMixin, VMMixin, VMStorageMixin, VMNetworkMixin):
    def __init__(self, root):
        self.directory = root / 'agent'
        self.directory.mkdir(mode=0o700)
        self.share_root = root / 'shares'
        self.share_root.mkdir(mode=0o755)
        self.system_root = Path('/')
        self.lock = threading.RLock()
        self._storage_locations = StorageLocations(self, self.command)
        self.vm_root = root / 'vms'
        self.vm_root.mkdir(mode=0o755)
        self.volume_manager = SimpleNamespace(records=lambda: [], required_path=lambda path: None)
        self.records, self.domains, self.states = {}, {}, {}
        self.calls = []
        self.console_processes = {}
        self.failure = None
    def load(self, name, default): return json.loads(json.dumps(self.records.get(name, default)))
    def save(self, name, value): self.records[name] = json.loads(json.dumps(value))
    def op_status(self): return {'memory_total': 16 * 1024 ** 3}
    def apply_vm_cpu_policy(self, root, cpus, ids): return ids or []
    def vm_cpu_ids(self, root): return []
    def validate_vm_cpu_ids(self, cpus, ids): return ids
    def vm_storage_label(self, path): pass
    def op_vms(self): return {'available': True, 'vms': [{'name': item['name'], 'id': item['id']} for item in self.load('vms', [])]}
    def op_shares(self): return []
    def command(self, args, **kwargs):
        self.calls.append(args)
        if self.failure: self.failure(args)
        if args[0] == 'zpool': return ''
        if args[0] == 'qemu-img':
            result = subprocess.run(args, text=True, capture_output=True, pass_fds=kwargs.get('pass_fds', ()), timeout=kwargs.get('timeout', 30))
            if result.returncode: raise Error(result.stderr)
            return result.stdout.strip()
        command = args[1]
        if command == 'define':
            root = ET.fromstring(Path(args[2]).read_text())
            identifier = root.findtext('uuid')
            if not identifier:
                identifier = str(uuid.uuid4())
                ET.SubElement(root, 'uuid').text = identifier
            self.domains[identifier] = ET.tostring(root, encoding='unicode')
            self.states[identifier] = 'shut off'
            return ''
        if command == 'dumpxml': return self.domains[args[2]]
        if command == 'domstate': return self.states[args[2]]
        if command == 'domuuid': return next(key for key, xml in self.domains.items() if ET.fromstring(xml).findtext('name') == args[2])
        if command == 'undefine':
            identity=args[2]
            if identity not in self.domains:
                identity=next((key for key,xml in self.domains.items() if ET.fromstring(xml).findtext('name')==args[2]),identity)
            self.domains.pop(identity,None)
            return ''
        if command == 'list': return '\n'.join(ET.fromstring(xml).findtext('name') for xml in self.domains.values()) if '--name' in args else '\n'.join(self.domains)
        if command == 'net-list': return 'default'
        if command == 'net-dumpxml': return '<network><name>default</name><forward mode="nat"/></network>'
        if command == 'qemu-agent-command':
            return json.dumps({'return': [{'name': 'eth0', 'hardware-address': '52:54:00:00:00:01', 'ip-addresses': [{'ip-address': '192.168.122.7'}]}] if 'guest-network-get-interfaces' in args[3] else {}})
        return ''


@unittest.skipUnless(shutil.which('qemu-img') and shutil.which('qemu-io'), 'qemu-utils needed for real checkpoint test')
class VMExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.host = FixtureHost(self.root)
        self.owner = patch('titan.vm_extensions.pwd.getpwnam', return_value=SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid()))
        self.owner.start()
        self.disk = self.host.vm_root / 'linux.qcow2'
        subprocess.run(['qemu-img', 'create', '-f', 'qcow2', str(self.disk), '16M'], check=True, capture_output=True)
        xml = self.host.vm_definition('linux', 1, 1024, self.disk)
        self.vm = self.host.register_vm_definition('linux', xml)
    def tearDown(self): self.owner.stop(); self.temp.cleanup()
    def write(self, path, pattern):
        subprocess.run(['qemu-io', '-f', 'qcow2', '-c', 'write -P ' + hex(pattern) + ' 0 512', str(path)], check=True, capture_output=True)
    def check(self, path, pattern):
        subprocess.run(['qemu-io', '-f', 'qcow2', '-c', 'read -P ' + hex(pattern) + ' 0 512', str(path)], check=True, capture_output=True)

    def backup_manager(self):
        target=self.root/'external'
        target.mkdir()
        manager=Backups(self.host,self.host.command)
        info=target.stat()
        manager._target_identity=(info.st_dev,info.st_ino)
        self.host.backups=manager
        return manager,target

    def test_real_snapshot_roundtrip_restores_all_disks_and_keeps_vm_off(self):
        added = self.host.op_vm_disk_add(self.vm, 1)
        extra = Path(added['disk']['disk'])
        self.write(self.disk, 0x11); self.write(extra, 0x22)
        snapshot = self.host.op_vm_snapshot_create(self.vm, 'Vor dem Update')['snapshot']
        self.assertEqual(snapshot['disk_count'], 2)
        self.write(self.disk, 0x33); self.write(extra, 0x44)
        self.host.op_vm_snapshot_restore(self.vm, snapshot['id'])
        self.check(self.disk, 0x11); self.check(extra, 0x22)
        self.assertEqual(self.host.states[self.vm], 'shut off')
        self.host.op_vm_snapshot_remove(self.vm, snapshot['id'])
        self.assertEqual(self.host.op_vm_extensions(self.vm)['snapshots'], [])
        self.host.op_vm_disk_remove(self.vm, added['disk']['target'])
        self.assertTrue(extra.exists())
        self.assertEqual(len(self.host.managed_vm(self.vm)['disks']), 1)

    def test_snapshot_actions_use_explicit_driver_with_qemu82_compatible_cli(self):
        def qemu82_options(args):
            if args[:2] != ['qemu-img', 'snapshot']: return
            self.assertNotIn('-f', args, 'QEMU 8.2 snapshot rejects the -f option.')
            self.assertEqual(args[2], '--image-opts')
            self.assertRegex(args[-1], r'^driver=qcow2,file\.driver=file,file\.filename=/proc/self/fd/[0-9]+$')
            descriptor = int(args[-1].rsplit('/', 1)[1])
            self.assertEqual(os.fstat(descriptor).st_ino, self.disk.stat().st_ino)
        self.host.failure = qemu82_options
        self.write(self.disk, 0x11)
        snapshot = self.host.op_vm_snapshot_create(self.vm, 'QEMU 8.2 compatibility')['snapshot']['id']
        self.write(self.disk, 0x22)
        self.host.op_vm_snapshot_restore(self.vm, snapshot)
        self.check(self.disk, 0x11)
        self.host.op_vm_snapshot_remove(self.vm, snapshot)
        actions = {args[3] for args in self.host.calls if args[:2] == ['qemu-img', 'snapshot']}
        self.assertEqual(actions, {'-c', '-a', '-d'})

    def test_snapshot_format_checks_reject_raw_backing_and_external_data_before_qemu(self):
        record = self.host.managed_vm(self.vm)
        header = self.disk.read_bytes()[:104]
        variants = {
            'wrong magic': b'RAW!' + header[4:],
            'backing file': header[:8] + (104).to_bytes(8, 'big') + header[16:],
            'external data': header[:72] + (4).to_bytes(8, 'big') + header[80:],
        }
        try:
            for name, invalid in variants.items():
                with self.subTest(name=name):
                    with self.disk.open('r+b') as stream: stream.write(invalid)
                    self.host.calls.clear()
                    with self.assertRaises(Error):
                        self.host._vm_qcow_snapshot(record, record['disks'][0], '-c', 's-' + 'a' * 32)
                    self.assertFalse(any(args[0] == 'qemu-img' for args in self.host.calls))
        finally:
            with self.disk.open('r+b') as stream: stream.write(header)

    def test_clone_and_snapshot_restore_accept_labels_with_spaces_without_unsafe_paths(self):
        snapshot = self.host.op_vm_snapshot_create(self.vm, "Vor Änderung")["snapshot"]["id"]
        source = self.host.managed_vm(self.vm)
        for operation, label in ((self.host.op_vm_clone, "Meine VM Kopie"),
                                 (lambda vm, name: self.host.op_vm_snapshot_restore_new(vm, snapshot, name), "Windows 11 Snapshot")):
            restored = operation(self.vm, label)
            record = self.host.managed_vm(restored["id"])
            self.assertEqual(record["display_name"], label)
            self.assertRegex(record["name"], r"^[a-z][a-z0-9_-]{0,30}$")
            self.assertTrue(Path(record["disk"]).is_relative_to(self.host.vm_root))
            self.assertNotEqual(record["id"], self.vm)
            self.assertNotEqual(record["disk"], source["disk"])
        self.assertEqual(self.host.managed_vm(self.vm)["xml"], source["xml"])

    def test_real_clone_is_independent_and_has_all_disks(self):
        added = self.host.op_vm_disk_add(self.vm, 1)
        self.write(self.disk, 0x11); self.write(added['disk']['disk'], 0x22)
        cloned = self.host.op_vm_clone(self.vm, 'copy')['id']
        copy = self.host.managed_vm(cloned)
        self.assertEqual(len(copy['disks']), 2)
        self.check(copy['disk'], 0x11); self.check(copy['disks'][1]['disk'], 0x22)
        self.write(self.disk, 0x33)
        self.check(copy['disk'], 0x11)
        self.assertNotEqual(cloned, self.vm)

    def test_snapshot_restore_new_exports_all_checkpoint_disks_and_preserves_current_vm(self):
        extra = Path(self.host.op_vm_disk_add(self.vm, 1)['disk']['disk'])
        self.write(self.disk, 0x11); self.write(extra, 0x22)
        snapshot = self.host.op_vm_snapshot_create(self.vm, 'Baseline')['snapshot']['id']
        self.write(self.disk, 0x33); self.write(extra, 0x44)
        source_xml = self.host.domains[self.vm]
        original_hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (self.disk, extra)]
        self.host.calls.clear()
        result = self.host.op_vm_snapshot_restore_new(self.vm, snapshot, 'recovered')
        recovered = self.host.managed_vm(result['id'])
        self.assertTrue(result['source_preserved'])
        self.assertNotEqual(result['id'], self.vm)
        self.assertEqual(self.host.domains[self.vm], source_xml)
        self.assertEqual([hashlib.sha256(path.read_bytes()).hexdigest() for path in (self.disk, extra)], original_hashes)
        self.check(self.disk, 0x33); self.check(extra, 0x44)
        self.check(recovered['disks'][0]['disk'], 0x11); self.check(recovered['disks'][1]['disk'], 0x22)
        self.assertEqual(self.host.states[result['id']], 'shut off')
        self.assertEqual(len(self.host.op_vm_extensions(self.vm)['snapshots']), 1)
        self.assertFalse(any(call[:2] == ['qemu-img', 'snapshot'] for call in self.host.calls))
        converts = [call for call in self.host.calls if call[:2] == ['qemu-img', 'convert']]
        self.assertEqual(len(converts), 2)
        self.assertTrue(all('snapshot.name=' + snapshot in call for call in converts))

    def test_snapshot_restore_new_failure_cleans_only_new_files_and_duplicate_name_is_rejected(self):
        extra = Path(self.host.op_vm_disk_add(self.vm, 1)['disk']['disk'])
        self.write(self.disk, 0x11); self.write(extra, 0x22)
        snapshot = self.host.op_vm_snapshot_create(self.vm, 'Baseline')['snapshot']['id']
        self.write(self.disk, 0x33); self.write(extra, 0x44)
        with self.assertRaisesRegex(Error, 'bereits verwendet'):
            self.host.op_vm_snapshot_restore_new(self.vm, snapshot, 'linux')
        conversions = 0
        def fail_second(args):
            nonlocal conversions
            if args[:2] == ['qemu-img', 'convert']:
                conversions += 1
                if conversions == 2: raise Error('second disk unavailable')
        self.host.failure = fail_second
        with self.assertRaisesRegex(Error, 'second disk'):
            self.host.op_vm_snapshot_restore_new(self.vm, snapshot, 'failed-copy')
        self.assertFalse(list(self.host.vm_root.glob('failed-copy*')))
        self.assertEqual(len(self.host.load('vms', [])), 1)
        self.check(self.disk, 0x33); self.check(extra, 0x44)

    def test_explicit_shutdown_waits_for_stopped_vm_without_forced_poweroff(self):
        self.host.states[self.vm] = 'running'
        with patch.object(self.host, 'op_vm_action', create=True) as shutdown, patch('titan.vm_extensions.time.sleep', side_effect=lambda _: self.host.states.update({self.vm: 'shut off'})):
            self.host.op_vm_snapshot_create(self.vm, 'After shutdown', shutdown=True)
        shutdown.assert_called_once_with(self.vm, 'shutdown')
        self.assertEqual(self.host.states[self.vm], 'shut off')
        self.host.states[self.vm] = 'running'
        with patch.object(self.host, 'op_vm_action', create=True) as shutdown, patch('titan.vm_extensions.time.monotonic', side_effect=[0, 121]), patch('titan.vm_extensions.time.sleep') as sleep:
            with self.assertRaisesRegex(Error, 'nicht zwangsweise'):
                self.host.op_vm_snapshot_create(self.vm, 'Timeout', shutdown=True)
        shutdown.assert_called_once_with(self.vm, 'shutdown')
        sleep.assert_not_called()
        self.assertEqual(len(self.host.op_vm_extensions(self.vm)['snapshots']), 1)
        self.assertFalse(any(call[:2] == ['virsh', 'destroy'] for call in self.host.calls))

    def test_snapshot_restore_new_preserves_saved_uefi_variables_and_original_current_variables(self):
        variables = self.root / 'nvram'
        variables.mkdir()
        with patch.object(self.host, 'vm_nvram_path', side_effect=lambda name: variables / ('titan-' + name + '_VARS.fd')), patch.object(self.host, 'validate_vm_firmware'):
            record = self.host.managed_vm(self.vm)
            root = ET.fromstring(record['xml']); root.find('os').set('firmware', 'efi')
            original = self.host.vm_instance_nvram_path('linux', self.disk)
            original.write_bytes(b'saved-boot-variables')
            ET.SubElement(root.find('os'), 'nvram').text = str(original)
            self.host.redefine_vm(record, root)
            snapshot = self.host.op_vm_snapshot_create(self.vm, 'UEFI')['snapshot']['id']
            original.write_bytes(b'current-boot-variables')
            recovered = self.host.op_vm_snapshot_restore_new(self.vm, snapshot, 'uefi-copy')['id']
            copied = Path(ET.fromstring(self.host.managed_vm(recovered)['xml']).findtext('./os/nvram'))
            self.assertNotEqual(copied, original)
            self.assertEqual(copied.read_bytes(), b'saved-boot-variables')
            self.assertEqual(original.read_bytes(), b'current-boot-variables')

    def test_live_storage_summary_aggregates_all_disks_and_preserves_boot_capacity(self):
        extra=Path(self.host.op_vm_disk_add(self.vm,1)['disk']['disk'])
        self.write(self.disk,0x55);self.write(extra,0x66)
        details=self.host.vm_disk_details(self.host.managed_vm(self.vm))
        self.assertEqual(details['virtual_size'],16*1024**2)
        self.assertEqual(details['disk_total_capacity_bytes'],1024**3+16*1024**2)
        self.assertEqual(details['disk_count'],2)
        self.assertEqual(details['disk_allocated_bytes'],(self.disk.stat().st_blocks+extra.stat().st_blocks)*512)

    def test_live_disk_and_snapshot_mutations_do_not_run(self):
        self.host.states[self.vm] = 'running'
        operations = [lambda: self.host.op_vm_disk_add(self.vm, 1), lambda: self.host.op_vm_clone(self.vm, 'copy'),
                      lambda: self.host.op_vm_snapshot_create(self.vm, 'unsafe'), lambda: self.host.op_vm_guest_agent(self.vm, True),
                      lambda: self.host.op_vm_nic_remove(self.vm, 0)]
        for operation in operations:
            self.host.calls.clear()
            with self.assertRaises(Error): operation()
            self.assertFalse(any(call[0] == 'qemu-img' for call in self.host.calls))

    def test_snapshot_rollback_on_second_disk_apply_failure_restores_current_data(self):
        extra = Path(self.host.op_vm_disk_add(self.vm, 1)['disk']['disk'])
        self.write(self.disk, 0x11); self.write(extra, 0x22)
        snapshot = self.host.op_vm_snapshot_create(self.vm, 'old')['snapshot']['id']
        self.write(self.disk, 0x33); self.write(extra, 0x44)
        applies = 0
        def failure(args):
            nonlocal applies
            if args[:2] == ['qemu-img', 'snapshot'] and '-a' in args and snapshot in args:
                applies += 1
                if applies == 2: raise Error('second disk unavailable')
        self.host.failure = failure
        with self.assertRaises(Error): self.host.op_vm_snapshot_restore(self.vm, snapshot)
        self.check(self.disk, 0x33); self.check(extra, 0x44)

    def test_nics_remain_independent_and_guest_agent_reports_guest_ip(self):
        self.host.op_vm_nic_add(self.vm, {'mode': 'network', 'source': 'default', 'mac': '52:54:00:00:00:01'})
        self.assertEqual(len(self.host.op_vm_extensions(self.vm)['networks']), 2)
        root = ET.fromstring(self.host.managed_vm(self.vm)['xml'])
        self.host.apply_vm_network(root, {'mode': 'network', 'source': 'default', 'connected': False})
        self.host.redefine_vm(self.host.managed_vm(self.vm), root)
        self.assertEqual(len(root.findall('./devices/interface')), 2)
        self.host.op_vm_guest_agent(self.vm, True)
        self.host.states[self.vm] = 'running'
        agent = self.host.op_vm_extensions(self.vm)['guest_agent']
        self.assertTrue(agent['connected'])
        self.assertEqual(agent['interfaces'][0]['addresses'], ['192.168.122.7'])
        self.host.op_vm_guest_action(self.vm, 'shutdown')
        self.assertIn(['virsh', 'shutdown', self.vm, '--mode', 'agent'], self.host.calls)

    def test_additional_disk_metadata_tampering_is_blocked(self):
        self.host.op_vm_disk_add(self.vm, 1)
        records = self.host.load('vms', [])
        records[0]['extra_disks'][0]['disk'] = '/etc/passwd'
        self.host.save('vms', records)
        with self.assertRaises(Error): self.host.managed_vm(self.vm)

    def test_snapshot_prevents_disk_count_change_until_removed(self):
        self.host.op_vm_snapshot_create(self.vm, 'baseline')
        with self.assertRaisesRegex(Error, 'Snapshots entfernen'): self.host.op_vm_disk_add(self.vm, 1)

    def test_clone_cannot_redefine_foreign_libvirt_domain(self):
        foreign = str(uuid.uuid4())
        root = ET.fromstring(self.host.domains[self.vm])
        root.find('uuid').text = foreign; root.find('name').text = 'titan-copy'
        self.host.domains[foreign] = ET.tostring(root, encoding='unicode')
        with self.assertRaisesRegex(Error, 'libvirt-VM'): self.host.op_vm_clone(self.vm, 'copy')
        self.assertFalse((self.host.vm_root / 'copy.qcow2').exists())

    def test_uefi_checkpoint_and_clone_preserve_variables_without_sharing_file(self):
        variables = self.root / 'nvram'
        variables.mkdir()
        with patch.object(self.host, 'vm_nvram_path', side_effect=lambda name: variables / ('titan-' + name + '_VARS.fd')), patch.object(self.host, 'validate_vm_firmware'):
            record = self.host.managed_vm(self.vm)
            root = ET.fromstring(record['xml'])
            root.find('os').set('firmware', 'efi')
            original = self.host.vm_instance_nvram_path('linux', self.disk)
            original.write_bytes(b'original-boot-variables')
            ET.SubElement(root.find('os'), 'nvram').text = str(original)
            self.host.redefine_vm(record, root)
            snapshot = self.host.op_vm_snapshot_create(self.vm, 'UEFI')['snapshot']['id']
            original.write_bytes(b'new-boot-variables')
            self.host.op_vm_snapshot_restore(self.vm, snapshot)
            self.assertEqual(original.read_bytes(), b'original-boot-variables')
            clone = self.host.op_vm_clone(self.vm, 'copy')['id']
            copied = Path(ET.fromstring(self.host.managed_vm(clone)['xml']).findtext('./os/nvram'))
            self.assertNotEqual(copied, original)
            self.assertEqual(copied.read_bytes(), original.read_bytes())
            original.write_bytes(b'another-boot-change')
            self.assertEqual(copied.read_bytes(), b'original-boot-variables')

    def test_real_external_multidisk_backup_restores_all_disk_bytes_and_vm_identity(self):
        extra = Path(self.host.op_vm_disk_add(self.vm, 1)['disk']['disk'])
        self.write(self.disk, 0x11); self.write(extra, 0x22)
        target = self.root / 'external'
        target.mkdir()
        backups = Backups(self.host, self.host.command)
        metadata = target.stat()
        backups._target_identity = (metadata.st_dev, metadata.st_ino)
        self.host.backups = backups
        with patch.object(backups, 'validate_target', return_value=target):
            backups.save_settings({'target':str(target)})
            result = self.host.op_vm_backup(self.vm)
            manifest = backups.verified_vm(result['backup'])
            self.assertEqual(len(manifest['disks']), 2)
            restored = self.host.op_vm_restore(result['backup'], 'restored')
        record = self.host.managed_vm(restored['id'])
        self.assertNotEqual(record['id'], self.vm)
        self.assertEqual(len(record['disks']), 2)
        self.check(record['disk'], 0x11); self.check(record['disks'][1]['disk'], 0x22)
        self.assertEqual(record['state'], 'shut off')

    def test_external_vm_backup_rejects_missing_secondary_disk_and_preserves_existing_restore(self):
        extra = Path(self.host.op_vm_disk_add(self.vm, 1)['disk']['disk'])
        extra.unlink()
        with self.assertRaises(Error): self.host.managed_vm(self.vm)

    def test_registration_failure_with_unconfirmed_undefine_retains_clone_files(self):
        self.write(self.disk,0x55)
        def failure(args):
            if args[:2]==['virsh','undefine']: raise Error('libvirt transport unavailable')
        self.host.failure=failure
        with patch.object(self.host,'save',side_effect=Error('metadata unavailable')):
            with self.assertRaisesRegex(Error,'Laufwerke und Definition bleiben erhalten') as raised:
                self.host.op_vm_clone(self.vm,'copy')
        self.assertTrue(raised.exception.retain_vm_files)
        self.assertTrue((self.host.vm_root/'copy.qcow2').exists())
        self.check(self.host.vm_root/'copy.qcow2',0x55)
        self.assertTrue((self.host.directory/'vm-copy.xml').exists())

    def test_disk_add_with_unconfirmed_redefinition_retains_bytes_and_metadata(self):
        def failure(args):
            if args[:2]==['virsh','define']: raise Error('libvirt transport unavailable')
        self.host.failure=failure
        with self.assertRaises(Error) as raised:self.host.op_vm_disk_add(self.vm,1)
        self.assertTrue(raised.exception.retain_vm_files)
        extras=self.host.load('vms',[])[0]['extra_disks']
        self.assertEqual(len(extras),1)
        self.assertTrue(Path(extras[0]['disk']).exists())

    def test_old_single_disk_manifest_remains_restorable(self):
        self.write(self.disk,0x55)
        manager,target=self.backup_manager()
        with patch.object(manager,'validate_target',return_value=target):
            manager.save_settings({'target':str(target)})
            backup=self.host.op_vm_backup(self.vm)['backup']
            manifest=manager.namespace()/backup/'manifest.json'
            value=json.loads(manifest.read_text());value.pop('vm_disks')
            manifest.write_text(json.dumps(value));manifest.chmod(0o600)
            verified=manager.verified_vm(backup)
            self.assertIsNone(verified['disks'][0]['virtual_size'])
            restored=self.host.op_vm_restore(backup,'oldbackup')['id']
        self.check(self.host.managed_vm(restored)['disk'],0x55)

    def test_real_external_multidisk_uefi_backup_restores_boot_variables(self):
        extra=Path(self.host.op_vm_disk_add(self.vm,1)['disk']['disk'])
        self.write(self.disk,0x55);self.write(extra,0x66)
        variables=self.root/'nvram';variables.mkdir()
        manager,target=self.backup_manager()
        with patch.object(self.host,'vm_nvram_path',side_effect=lambda name:variables/('titan-'+name+'_VARS.fd')),patch.object(self.host,'validate_vm_firmware'):
            record=self.host.managed_vm(self.vm)
            root=ET.fromstring(record['xml']);root.find('os').set('firmware','efi')
            original=self.host.vm_instance_nvram_path('linux',self.disk)
            original.write_bytes(b'original-uefi-variables')
            ET.SubElement(root.find('os'),'nvram').text=str(original)
            self.host.redefine_vm(record,root)
            with patch.object(manager,'validate_target',return_value=target):
                manager.save_settings({'target':str(target)})
                backup=self.host.op_vm_backup(self.vm)['backup']
                restored=self.host.op_vm_restore(backup,'uefirestored')['id']
            restored_record=self.host.managed_vm(restored)
            nvram=Path(ET.fromstring(restored_record['xml']).findtext('./os/nvram'))
            self.assertNotEqual(original,nvram)
            self.assertEqual(nvram.read_bytes(),original.read_bytes())
            self.check(restored_record['disk'],0x55);self.check(restored_record['disks'][1]['disk'],0x66)


if __name__ == '__main__': unittest.main()

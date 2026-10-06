import copy
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from titan.core import Error
from titan.system_disk import SystemDisk, ROOT_TYPE, MIN_GROW, main

GIB = 1024 ** 3
REAL_STAT = os.stat
REAL_READ_TEXT = Path.read_text


class DiskFixture:
    """All commands and device reads are simulated; never open a host disk."""
    def __init__(self, disk='/dev/vda', partition='/dev/vda4', sector=512):
        self.disk, self.partition, self.sector = disk, partition, sector
        self.calls = []
        self.disk_size, self.partition_size, self.fs_size = 32 * GIB, 19 * GIB, 19 * GIB
        self.major_minor = '252:4'
        self.disk_major_minor = '252:0'
        self.number = '4'
        self.kernel_start_bytes = 3 * GIB
        self.part_uuid = '00000000-0000-4000-a000-000000000004'
        self.fs_uuid = '910678ff-f77e-4a7d-8d53-86f2ac47a823'
        self.mounts = {'/var': {'target': '/var', 'source': partition + '[/var]', 'fstype': 'xfs', 'options': 'rw,relatime,seclabel', 'maj:min': self.major_minor, 'fsroot': '/var'},
                       '/sysroot': {'target': '/sysroot', 'source': partition, 'fstype': 'xfs', 'options': 'ro,relatime,seclabel', 'maj:min': self.major_minor, 'fsroot': '/'}}
        self.rows = [{'name': disk, 'type': 'disk', 'maj:min': self.disk_major_minor, 'size': self.disk_size, 'ro': False, 'rm': False, 'pkname': None, 'log-sec': sector},
                     {'name': partition, 'type': 'part', 'maj:min': self.major_minor, 'size': self.partition_size, 'ro': False, 'rm': False, 'pkname': disk, 'log-sec': sector, 'fstype': 'xfs', 'uuid': self.fs_uuid, 'parttype': ROOT_TYPE, 'partlabel': 'root', 'partuuid': self.part_uuid}]
        self.table = {'label': 'gpt', 'id': '00000000-0000-4000-a000-000000000001', 'device': disk, 'unit': 'sectors', 'firstlba': 34, 'lastlba': 22 * GIB // sector - 34, 'sectorsize': sector,
                      'partitions': [
                          {'node': self.node(1), 'start': MIN_GROW // sector, 'size': MIN_GROW // sector, 'type': '21686148-6449-6e6f-744e-656564454649', 'uuid': '00000000-0000-4000-a000-000000000010', 'name': 'BIOS-BOOT'},
                          {'node': self.node(2), 'start': 2 * MIN_GROW // sector, 'size': 512 * MIN_GROW // sector, 'type': 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b', 'uuid': '00000000-0000-4000-a000-000000000020', 'name': 'EFI-SYSTEM'},
                          {'node': self.node(3), 'start': GIB // sector, 'size': GIB // sector, 'type': 'bc13c2ff-59e6-4262-a352-b275fd6f7172', 'uuid': '00000000-0000-4000-a000-000000000030', 'name': 'boot'},
                          {'node': partition, 'start': 3 * GIB // sector, 'size': self.partition_size // sector, 'type': ROOT_TYPE, 'uuid': self.part_uuid, 'name': 'root'}]}
        self.dryrun_override = None
        self.fail_command = None
        self.partition_updates_kernel = True
        self.xfs_grows = True
        self.mutate_boot = False
        self.external_log = False
        self.mutate_during_second_scan = False
        self.scans = 0

    def node(self, number):
        return self.disk + ('p' if self.disk[-1].isdigit() else '') + str(number)

    @property
    def root(self):
        return next(item for item in self.table['partitions'] if item['node'] == self.partition)

    def target_size(self):
        sectors_per_mib = MIN_GROW // self.sector
        return ((self.disk_size // self.sector - 33 - self.root['start']) // sectors_per_mib) * sectors_per_mib

    def run(self, args, timeout=30):
        self.calls.append(list(args))
        if args[0] == self.fail_command:
            return subprocess.CompletedProcess(args, 2, '', 'Simulierter Fehler')
        if args[0] == 'findmnt':
            if args[3] == '/var':
                self.scans += 1
                if self.mutate_during_second_scan and self.scans == 2:
                    self.disk_size += GIB
                    self.rows[0]['size'] = self.disk_size
            return subprocess.CompletedProcess(args, 0, json.dumps({'filesystems': [self.mounts[args[3]]]}), '')
        if args[0] == 'lsblk':
            return subprocess.CompletedProcess(args, 0, json.dumps({'blockdevices': self.rows}), '')
        if args[0] == 'sfdisk':
            return subprocess.CompletedProcess(args, 0, json.dumps({'partitiontable': self.table}), '')
        if args[0] == 'growpart':
            old_size, start, target = self.root['size'], self.root['start'], self.target_size()
            if '--dry-run' in args and self.dryrun_override:
                return self.dryrun_override
            if old_size >= target:
                return subprocess.CompletedProcess(args, 1, 'NOCHANGE: partition already uses available space', '')
            output = f'CHANGE: partition=4 start={start} old: size={old_size} end={start + old_size - 1} new: size={target} end={start + target - 1}'
            if '--dry-run' not in args:
                self.root['size'] = target
                self.partition_size = target * self.sector
                if self.partition_updates_kernel:
                    self.rows[1]['size'] = self.partition_size
                self.table['lastlba'] = self.disk_size // self.sector - 34
                if self.mutate_boot:
                    self.table['partitions'][1]['size'] -= 1
                output = output.replace('CHANGE:', 'CHANGED:')
            return subprocess.CompletedProcess(args, 0, output, '')
        if args[0] == 'xfs_info':
            log = '/dev/external-log' if self.external_log else 'internal'
            output = f'meta-data={self.partition} isize=512 agcount=4\ndata     = bsize=4096 blocks={self.fs_size // 4096}, imaxpct=25\nlog      = {log} bsize=4096 blocks=16384\nrealtime = none extsz=4096 blocks=0, rtextents=0\n'
            return subprocess.CompletedProcess(args, 0, output, '')
        if args[0] == 'xfs_growfs':
            if self.xfs_grows:
                self.fs_size = self.partition_size
            return subprocess.CompletedProcess(args, 0, 'data blocks changed', '')
        raise AssertionError('Unexpected command: ' + repr(args))

    def stat(self, path, *args, **kwargs):
        path = os.fspath(path)
        if path in ('/var', '/sysroot'):
            return SimpleNamespace(st_dev=os.makedev(252, 4), st_mode=stat.S_IFDIR)
        if not path.startswith('/dev/'):
            return REAL_STAT(path, *args, **kwargs)
        # The fixture never dereferences or opens the simulated /dev nodes.
        actual = self.disk_major_minor if path == self.disk else self.major_minor
        major, minor = map(int, actual.split(':'))
        return SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(major, minor))

    def read_text(self, path):
        if str(path) == '/sys/dev/block/252:4/start':
            return str(self.kernel_start_bytes // 512)
        assert str(path) == '/sys/dev/block/252:4/partition', path
        return self.number

    def statvfs(self, path):
        assert path == '/var'
        blocks = self.fs_size // 4096
        return SimpleNamespace(f_blocks=blocks, f_bfree=blocks - 1000, f_bavail=blocks - 1000, f_frsize=4096)


class SystemDiskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = DiskFixture()
        self.manager = SystemDisk(self.fixture.run, Path(self.temp.name) / 'grow.lock')
        for target, value in [('titan.system_disk.os.stat', self.fixture.stat),
                              ('titan.system_disk.os.statvfs', self.fixture.statvfs),
                              ('titan.system_disk.Path.read_text', lambda path: self.fixture.read_text(path))]:
            patcher = patch(target, side_effect=value) if target != 'titan.system_disk.Path.read_text' else patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def assert_no_mutation(self):
        self.assertFalse(any(args[0] == 'xfs_growfs' or args[0] == 'growpart' and '--dry-run' not in args for args in self.fixture.calls))

    def grow(self):
        return self.manager.grow(self.manager.status()['revision'], 'ERWEITERN')

    def test_status_is_read_only_and_exposes_geometry_not_used_space_revision(self):
        state = self.manager.status()
        self.assertTrue(state['supported'], state['reason'])
        self.assertTrue(state['available'])
        self.assertEqual(state['disk_size'], 32 * GIB)
        self.assertEqual(state['filesystem_size'], 19 * GIB)
        self.assertEqual(state['partition_start'], 3 * GIB)
        self.assertEqual(state['filesystem_used'], 1000 * 4096)
        self.assertEqual(state['revision'], self.manager.status()['revision'])
        self.assertFalse(self.manager.lock_path.exists())
        self.assert_no_mutation()

    def test_growth_keeps_efi_boot_uuid_start_and_uses_rw_var_not_ro_sysroot(self):
        before_parts = copy.deepcopy(self.fixture.table['partitions'])
        result = self.grow()
        self.assertTrue(result['changed'])
        self.assertTrue(result['partition_grown'])
        self.assertTrue(result['filesystem_grown'])
        self.assertFalse(result['after']['available'])
        self.assertEqual(before_parts[:-1], self.fixture.table['partitions'][:-1])
        for key in ('start', 'uuid', 'type', 'name'):
            self.assertEqual(before_parts[-1][key], self.fixture.root[key])
        self.assertIn(['xfs_growfs', '-d', '/var'], self.fixture.calls)
        self.assertIn(['growpart', '--fudge', '0', '--update=on', '/dev/vda', '4'], self.fixture.calls)
        self.assertNotEqual(result['before']['revision'], result['after']['revision'])

    def test_second_fresh_growth_is_idempotent_without_mutating_commands(self):
        self.grow()
        self.fixture.calls.clear()
        result = self.grow()
        self.assertTrue(result['ok'])
        self.assertFalse(result['changed'])
        self.assert_no_mutation()

    def test_replay_old_revision_blocks_before_any_mutation(self):
        revision = self.manager.status()['revision']
        self.grow()
        self.fixture.calls.clear()
        with self.assertRaisesRegex(Error, 'Status erneut laden'):
            self.manager.grow(revision, 'ERWEITERN')
        self.assert_no_mutation()

    def test_disk_change_between_read_and_click_blocks(self):
        revision = self.manager.status()['revision']
        self.fixture.rows[0]['size'] += GIB
        self.fixture.disk_size += GIB
        with self.assertRaisesRegex(Error, 'Status erneut laden'):
            self.manager.grow(revision, 'ERWEITERN')
        self.assert_no_mutation()

    def test_disk_change_during_grow_preflight_blocks(self):
        revision = self.manager.status()['revision']
        self.fixture.scans = 0
        self.fixture.mutate_during_second_scan = True
        with self.assertRaisesRegex(Error, 'während der Prüfung'):
            self.manager.grow(revision, 'ERWEITERN')
        self.assert_no_mutation()

    def test_invalid_confirmation_and_revision_block_without_scan(self):
        for revision, confirmation in [('a' * 64, 'Ja'), (None, 'ERWEITERN'), ('../dev/sda', 'ERWEITERN')]:
            with self.assertRaises(Error):
                self.manager.grow(revision, confirmation)
        self.assertEqual(self.fixture.calls, [])

    def test_filesystem_only_recovery_after_previous_partition_grow(self):
        self.fixture.run(['growpart', '--fudge', '0', '--update=on', '/dev/vda', '4'])
        self.fixture.calls.clear()
        result = self.grow()
        self.assertFalse(result['partition_grown'])
        self.assertTrue(result['filesystem_grown'])
        self.assertFalse(any(args[0] == 'growpart' and '--dry-run' not in args for args in self.fixture.calls))

    def test_different_var_partition_blocked(self):
        self.fixture.mounts['/sysroot']['maj:min'] = '252:5'
        state = self.manager.status()
        self.assertFalse(state['supported'])
        self.assert_no_mutation()

    def test_ro_var_blocked_even_when_sysroot_matches(self):
        self.fixture.mounts['/var']['options'] = 'ro,relatime'
        state = self.manager.status()
        self.assertFalse(state['supported'])
        self.assertIn('schreibgeschützt', state['reason'])
        self.assert_no_mutation()

    def test_luks_lvm_raid_and_multipath_blocked(self):
        for kind in ('crypt', 'lvm', 'raid1', 'mpath'):
            self.fixture.rows[1]['type'] = kind
            state = self.manager.status()
            self.assertFalse(state['supported'], kind)
            self.assertIn('zusammengesetzte', state['reason'])
        self.assert_no_mutation()

    def test_partition_with_holders_blocked(self):
        self.fixture.rows.append({'name': '/dev/dm-0', 'type': 'crypt', 'maj:min': '253:0', 'pkname': self.fixture.partition})
        self.assertFalse(self.manager.status()['supported'])
        self.assert_no_mutation()

    def test_data_partition_after_root_blocks_no_modification(self):
        self.fixture.table['partitions'].append({'node': '/dev/vda5', 'start': 24 * GIB // 512, 'size': GIB // 512, 'type': '0fc63daf-8483-4772-8e79-3d69d8477de4'})
        self.assertFalse(self.manager.status()['supported'])
        self.assert_no_mutation()

    def test_known_boot_partition_after_root_also_blocks(self):
        self.fixture.table['partitions'].append({'node': '/dev/vda5', 'start': 24 * GIB // 512, 'size': GIB // 512, 'type': 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b'})
        state = self.manager.status()
        self.assertFalse(state['supported'])
        self.assertIn('Hinter der Systempartition', state['reason'])
        self.assert_no_mutation()

    def test_overlap_unsafe_parttype_label_or_mbr_blocked(self):
        for change in ('overlap', 'type', 'label', 'mbr'):
            table = copy.deepcopy(self.fixture.table)
            if change == 'overlap':
                self.fixture.table['partitions'][2]['start'] = MIN_GROW // 512
            elif change == 'type':
                self.fixture.root['type'] = 'bad'
            elif change == 'label':
                self.fixture.root['name'] = 'nas-data'
            else:
                self.fixture.table['label'] = 'dos'
            self.assertFalse(self.manager.status()['supported'], change)
            self.fixture.table = table
        self.assert_no_mutation()

    def test_unsupported_filesystem_mount_and_external_log_blocked(self):
        self.fixture.mounts['/var']['fstype'] = 'ext4'
        self.assertFalse(self.manager.status()['supported'])
        self.fixture.mounts['/var']['fstype'] = 'xfs'
        self.fixture.external_log = True
        self.assertFalse(self.manager.status()['supported'])
        self.assert_no_mutation()

    def test_readonly_removable_disk_and_nonblock_device_blocked(self):
        for field in ('ro', 'rm'):
            self.fixture.rows[0][field] = True
            self.assertFalse(self.manager.status()['supported'])
            self.fixture.rows[0][field] = False
        with patch('titan.system_disk.os.stat', return_value=SimpleNamespace(st_mode=stat.S_IFREG, st_dev=os.makedev(252, 4), st_rdev=os.makedev(252, 4))):
            self.assertFalse(self.manager.status()['supported'])
        self.assert_no_mutation()

    def test_unsafe_dryrun_smaller_start_shift_or_larger_than_disk_blocked(self):
        start, size = self.fixture.root['start'], self.fixture.root['size']
        for new_start, new_size in [(start + 1, size + 100), (start, size - 100), (start, 100 * GIB // 512)]:
            self.fixture.dryrun_override = subprocess.CompletedProcess([], 0, f'CHANGE: partition=4 start={new_start} old: size={size} end={start + size - 1} new: size={new_size} end={new_start + new_size - 1}', '')
            self.assertFalse(self.manager.status()['supported'])
        self.assert_no_mutation()

    def test_missing_tools_invalid_data_are_readonly_unsupported_status(self):
        self.fixture.fail_command = 'growpart'
        state = self.manager.status()
        self.assertFalse(state['supported'])
        self.assertIn('Simulierter Fehler', state['reason'])
        self.assert_no_mutation()

    def test_kernel_partition_not_updated_blocks_before_xfs(self):
        self.fixture.partition_updates_kernel = False
        with self.assertRaisesRegex(Error, 'Kernelstatus'):
            self.grow()
        self.assertFalse(any(args[0] == 'xfs_growfs' for args in self.fixture.calls))

    def test_boot_efi_changed_by_tool_blocks_before_xfs(self):
        self.fixture.mutate_boot = True
        with self.assertRaisesRegex(Error, 'Partitionstabelle'):
            self.grow()
        self.assertFalse(any(args[0] == 'xfs_growfs' for args in self.fixture.calls))

    def test_failed_growpart_does_not_attempt_xfs(self):
        revision = self.manager.status()['revision']
        self.fixture.fail_command = 'growpart'
        with self.assertRaises(Error):
            self.manager.grow(revision, 'ERWEITERN')
        self.assertFalse(any(args[0] == 'xfs_growfs' for args in self.fixture.calls))

    def test_xfs_failure_or_no_growth_is_not_reported_success(self):
        self.fixture.xfs_grows = False
        with self.assertRaisesRegex(Error, 'nicht vollständig'):
            self.grow()

    def test_grow_lock_rejects_parallel_mutation(self):
        revision = self.manager.status()['revision']
        with self.manager.lock_path.open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.assertRaisesRegex(Error, 'bereits erweitert'):
                self.manager.grow(revision, 'ERWEITERN')
        self.assert_no_mutation()

    def test_boot_errors_do_not_block_boot(self):
        with patch('sys.argv', ['system_disk', '--boot']), patch.object(SystemDisk, '_grow', side_effect=Error('Unsicheres Layout')), patch('sys.stderr') as stderr:
            self.assertEqual(main(), 0)
            self.assertTrue(stderr.write.called)

    def test_nvme_and_4k_geometry_without_device_hardcoding(self):
        self.fixture.__init__('/dev/nvme0n1', '/dev/nvme0n1p4', sector=4096)
        result = self.grow()
        self.assertTrue(result['changed'])
        self.assertEqual(result['after']['sector_size'], 4096)
        self.assertEqual(result['after']['disk'], '/dev/nvme0n1')



    def test_lock_symlink_is_rejected_without_device_mutation(self):
        revision = self.manager.status()['revision']
        target = Path(self.temp.name) / 'unrelated'
        target.write_text('untouched')
        self.manager.lock_path.symlink_to(target)
        with self.assertRaises(OSError):
            self.manager.grow(revision, 'ERWEITERN')
        with patch('titan.system_disk.Path.read_text', REAL_READ_TEXT):
            self.assertEqual(target.read_text(), 'untouched')
        self.assert_no_mutation()

    def test_mount_device_identity_changed_is_blocked(self):
        with patch('titan.system_disk.os.stat', return_value=SimpleNamespace(st_dev=os.makedev(252, 99), st_mode=stat.S_IFDIR)):
            state = self.manager.status()
        self.assertFalse(state['supported'])
        self.assertIn('Gerätezuordnung', state['reason'])
        self.assert_no_mutation()

    def test_noninteger_or_shrunken_physical_disk_blocks(self):
        self.fixture.rows[0]['size'] = float(self.fixture.disk_size)
        self.assertFalse(self.manager.status()['supported'])
        self.fixture.rows[0]['size'] = 10 * GIB
        self.fixture.disk_size = 10 * GIB
        self.assertFalse(self.manager.status()['supported'])
        self.assert_no_mutation()

    def test_normal_file_usage_changes_do_not_change_revision(self):
        revision = self.manager.status()['revision']
        with patch('titan.system_disk.os.statvfs', return_value=SimpleNamespace(f_blocks=10000, f_bfree=2000, f_bavail=2000, f_frsize=4096)):
            self.assertEqual(self.manager.status()['revision'], revision)

    def test_gpt_start_changed_with_same_kernel_size_blocks_before_plan_or_mutation(self):
        self.fixture.root['start'] += 2048
        state = self.manager.status()
        self.assertFalse(state['supported'])
        self.assertIn('Kernelstart', state['reason'])
        self.assertFalse(any(args[0] == 'growpart' for args in self.fixture.calls))
        self.assert_no_mutation()

    def test_kernel_start_change_after_status_blocks_manual_growth(self):
        revision = self.manager.status()['revision']
        self.fixture.kernel_start_bytes += MIN_GROW
        with self.assertRaisesRegex(Error, 'Kernelstart'):
            self.manager.grow(revision, 'ERWEITERN')
        self.assert_no_mutation()

    def test_4kn_sysfs_start_uses_512_byte_units_and_rejects_logical_units(self):
        self.fixture.__init__('/dev/nvme0n1', '/dev/nvme0n1p4', sector=4096)
        self.assertTrue(self.manager.status()['supported'])
        self.fixture.kernel_start_bytes //= 8
        state = self.manager.status()
        self.assertFalse(state['supported'])
        self.assertIn('Kernelstart', state['reason'])
        self.assert_no_mutation()


if __name__ == '__main__':
    unittest.main()

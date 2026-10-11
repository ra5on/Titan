"""Debian A/B DATA growth, with all device IO simulated and no real disk writes."""
import copy
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from titan.core import Error
from titan.debian_system_disk import DebianSystemDisk, EFI_TYPE, LABELS, LINUX_TYPE
from test_system_disk import DiskFixture, GIB, REAL_STAT

REAL_REALPATH = os.path.realpath


class DebianFixture(DiskFixture):
    def __init__(self, disk='/dev/vda', sector=512, slot=3):
        partition = disk + ('p' if disk[-1].isdigit() else '') + '5'
        super().__init__(disk, partition, sector)
        self.part_uuid = '00000000-0000-4000-a000-000000000005'
        self.number, self.major_minor = '5', '252:5'
        self.disk_size, self.partition_size, self.fs_size = 80 * GIB, 15 * GIB, 15 * GIB
        self.kernel_start_bytes = 33 * GIB
        self.rows[0]['size'] = self.disk_size
        self.rows[1].update(size=self.partition_size, fstype='ext4', partlabel='TITAN-DATA',
                            parttype=LINUX_TYPE, partuuid=self.part_uuid, **{'maj:min': self.major_minor})
        self.table['partitions'] = []
        for index, (start, size) in enumerate(((2048 * sector, GIB // 4), (GIB // 2, GIB // 4),
                                             (GIB, 16 * GIB), (17 * GIB, 16 * GIB),
                                             (33 * GIB, self.partition_size)), 1):
            uuid = self.part_uuid if index == 5 else f'00000000-0000-4000-a000-{index:012d}'
            kind = EFI_TYPE if index == 1 else LINUX_TYPE
            self.table['partitions'].append({'node': self.node(index), 'start': start // sector,
                                             'size': size // sector, 'type': kind,
                                             'uuid': uuid, 'name': LABELS[index - 1]})
            if index != 5:
                self.rows.append({'name': self.node(index), 'type': 'part', 'maj:min': f'252:{index}',
                                  'size': size, 'ro': False, 'rm': False, 'pkname': disk, 'log-sec': sector,
                                  'fstype': 'vfat' if index == 1 else 'ext4', 'parttype': kind,
                                  'partlabel': LABELS[index - 1], 'partuuid': uuid})
        self.mounts = {
            DebianSystemDisk.mountpoint: {'target': DebianSystemDisk.mountpoint, 'source': partition,
                'fstype': 'ext4', 'options': 'rw,relatime', 'maj:min': '252:5', 'fsroot': '/'},
            '/': {'target': '/', 'source': self.node(slot), 'fstype': 'ext4',
                  'options': 'rw,relatime', 'maj:min': f'252:{slot}', 'fsroot': '/'},
        }
        self.geometry = {'Filesystem UUID': self.fs_uuid, 'Filesystem volume name': 'TITAN-DATA',
                         'Filesystem state': 'clean', 'Filesystem features': 'has_journal ext_attr extent 64bit',
                         'Journal inode': '8', 'Block size': '4096'}
        self.geometry_override = None

    def run(self, args, timeout=30):
        if args[0] in ('tune2fs', 'resize2fs'):
            self.calls.append(list(args))
            if args[0] == self.fail_command:
                return subprocess.CompletedProcess(args, 2, '', 'Simulierter Fehler')
            if args[0] == 'resize2fs':
                if self.xfs_grows:
                    self.fs_size = self.partition_size
                return subprocess.CompletedProcess(args, 0, '', '')
            fields = {**self.geometry, 'Block count': str(self.fs_size // 4096)}
            output = self.geometry_override if self.geometry_override is not None else '\n'.join(f'{k}: {v}' for k, v in fields.items())
            return subprocess.CompletedProcess(args, 0, output, '')
        if args[0] == 'findmnt' and args[3] == DebianSystemDisk.mountpoint:
            self.scans += 1
            if self.mutate_during_second_scan and self.scans == 2:
                self.disk_size += GIB
                self.rows[0]['size'] = self.disk_size
        result = super().run(args, timeout)
        if args[0] == 'growpart' and not self.dryrun_override:
            result.stdout = result.stdout.replace('partition=4', 'partition=5')
        return result

    def stat(self, path, *args, **kwargs):
        path = os.fspath(path)
        if path in self.mounts:
            major, minor = map(int, self.mounts[path]['maj:min'].split(':'))
            return SimpleNamespace(st_dev=os.makedev(major, minor), st_mode=stat.S_IFDIR)
        row = next((row for row in self.rows if row['name'] == path), None)
        if row:
            major, minor = map(int, row['maj:min'].split(':'))
            return SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(major, minor))
        return REAL_STAT(path, *args, **kwargs)

    def read_text(self, path):
        row = next(row for row in self.rows if '/'+row['maj:min']+'/' in str(path))
        item = next(item for item in self.table['partitions'] if item['node'] == row['name'])
        if str(path).endswith('/partition'):
            return str(LABELS.index(row['partlabel']) + 1)
        self_start = self.kernel_start_bytes if row['name'] == self.partition else item['start'] * self.sector
        return str(self_start // 512)

    def statvfs(self, path):
        assert path == DebianSystemDisk.mountpoint
        blocks = self.fs_size // 4096
        return SimpleNamespace(f_blocks=blocks, f_bfree=blocks - 1000, f_bavail=blocks - 2000, f_frsize=4096)


class DebianSystemDiskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = DebianFixture()
        self.manager = DebianSystemDisk(self.fixture.run, Path(self.temp.name) / 'grow.lock')
        for target, value in (
            ('titan.system_disk.os.stat', self.fixture.stat),
            ('titan.system_disk.os.statvfs', self.fixture.statvfs),
            ('titan.system_disk.Path.read_text', lambda path: self.fixture.read_text(path)),
            ('titan.system_disk.os.path.realpath', lambda path, **kw: self.fixture.partition if path == '/dev/disk/by-partlabel/TITAN-DATA' else REAL_REALPATH(path, **kw)),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def grow(self):
        return self.manager.grow(self.manager.status()['revision'], 'ERWEITERN')

    def assert_no_mutation(self):
        self.assertFalse(any(args[0] == 'resize2fs' or args[0] == 'growpart' and '--dry-run' not in args for args in self.fixture.calls))

    def test_status_works_on_both_slots_and_nvme_4kn_without_writing(self):
        for disk, sector, slot in (('/dev/vda', 512, 3), ('/dev/sda', 512, 4), ('/dev/nvme0n1', 4096, 3)):
            with self.subTest(disk=disk, slot=slot):
                self.fixture.__init__(disk, sector, slot)
                value = self.manager.status()
                self.assertTrue(value['supported'], value['reason'])
                self.assertTrue(value['available'])
                self.assertEqual(value['filesystem'], 'ext4')
                self.assertEqual(value['partition_number'], 5)
                self.assertEqual(value['filesystem_size'], 15 * GIB)
                self.assert_no_mutation()

    def test_grow_changes_only_data_and_preserves_boot_and_both_system_slots(self):
        before = copy.deepcopy(self.fixture.table['partitions'])
        result = self.grow()
        self.assertTrue(result['changed'])
        self.assertFalse(result['after']['available'])
        self.assertEqual(self.fixture.table['partitions'][:4], before[:4])
        self.assertEqual(self.fixture.root['start'], before[4]['start'])
        self.assertEqual(self.fixture.root['uuid'], before[4]['uuid'])
        self.assertIn(['resize2fs', '/dev/vda5'], self.fixture.calls)
        self.assertIn(['growpart', '--fudge', '0', '--update=on', '/dev/vda', '5'], self.fixture.calls)
        self.assertFalse(any(args[0].startswith('mkfs') or args[0].startswith('xfs') for args in self.fixture.calls))
        self.fixture.calls.clear()
        self.assertFalse(self.grow()['changed'])
        self.assert_no_mutation()

    def test_partition_only_interruption_can_be_completed(self):
        self.fixture.run(['growpart', '/dev/vda', '5'])
        self.fixture.calls.clear()
        result = self.grow()
        self.assertFalse(result['partition_grown'])
        self.assertTrue(result['filesystem_grown'])
        self.assertFalse(any(args[0] == 'growpart' and '--dry-run' not in args for args in self.fixture.calls))

    def test_foreign_missing_readonly_and_nonstandard_layouts_are_refused(self):
        cases = (
            lambda: self.fixture.mounts['/'].update({'maj:min': '8:3'}),
            lambda: self.fixture.mounts[self.manager.mountpoint].update(fsroot='/subdir'),
            lambda: self.fixture.mounts[self.manager.mountpoint].update(options='ro,relatime'),
            lambda: self.fixture.rows[0].update(ro=True),
            lambda: self.fixture.rows[0].update(rm=True),
            lambda: self.fixture.rows[1].update(fstype='xfs'),
            lambda: self.fixture.table['partitions'].pop(2),
            lambda: self.fixture.table['partitions'][2].update(name='other-root'),
            lambda: self.fixture.table['partitions'][3].update(type=EFI_TYPE),
            lambda: self.fixture.rows[1].update(pkname='/dev/other'),
            lambda: self.fixture.rows[1].update(partuuid='00000000-0000-4000-a000-000000000099'),
            lambda: setattr(self.fixture, 'kernel_start_bytes', 34 * GIB),
        )
        for index, change in enumerate(cases):
            with self.subTest(case=index):
                self.fixture.__init__()
                change()
                self.assertFalse(self.manager.status()['supported'])
                self.assert_no_mutation()

    def test_wrong_label_target_and_external_ext4_journal_are_refused(self):
        with patch('titan.system_disk.os.path.realpath', side_effect=lambda path, **kw: '/dev/vda3' if path == '/dev/disk/by-partlabel/TITAN-DATA' else REAL_REALPATH(path, **kw)):
            self.assertFalse(self.manager.status()['supported'])
        for fields in ({'Journal device': '0x0806'}, {'Filesystem UUID': 'other'},
                       {'Filesystem volume name': 'other'}, {'Filesystem state': 'clean with errors'},
                       {'Block size': '65536'}):
            with self.subTest(fields=fields):
                self.fixture.__init__()
                self.fixture.geometry.update(fields)
                self.assertFalse(self.manager.status()['supported'])
                self.assert_no_mutation()

    def test_stale_confirmation_and_disk_change_before_write_are_refused(self):
        revision = self.manager.status()['revision']
        self.fixture.disk_size += GIB
        self.fixture.rows[0]['size'] = self.fixture.disk_size
        with self.assertRaises(Error):
            self.manager.grow(revision, 'ERWEITERN')
        self.assert_no_mutation()
        self.fixture.__init__()
        self.fixture.mutate_during_second_scan = True
        with self.assertRaises(Error):
            self.grow()
        self.assert_no_mutation()

    def test_changed_system_slot_or_stale_kernel_blocks_resize(self):
        for flag in ('mutate_boot', 'partition_updates_kernel'):
            with self.subTest(flag=flag):
                self.fixture.__init__()
                setattr(self.fixture, flag, flag == 'mutate_boot')
                with self.assertRaises(Error):
                    self.grow()
                self.assertFalse(any(args[0] == 'resize2fs' for args in self.fixture.calls))

    def test_failed_tools_or_incomplete_growth_never_report_success(self):
        for tool in ('growpart', 'resize2fs'):
            self.fixture.__init__()
            revision = self.manager.status()['revision']
            self.fixture.fail_command = tool
            with self.assertRaises(Error):
                self.manager.grow(revision, 'ERWEITERN')
        self.fixture.__init__()
        self.fixture.xfs_grows = False
        with self.assertRaises(Error):
            self.grow()

    def test_host_api_uses_debian_data_inspector(self):
        from titan.host import Host
        with patch('titan.debian_system_disk.DebianSystemDisk') as factory:
            host = object.__new__(Host)
            host.op_system_disk()
            factory.return_value.status.assert_called_once_with()
            host.op_system_disk_grow('a' * 64, 'ERWEITERN')
            factory.return_value.grow.assert_called_once_with(expected_revision='a' * 64, confirmation='ERWEITERN')

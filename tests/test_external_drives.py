import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from titan.core import Error
from titan.external_drives import ExternalDrivesMixin, drive_name, filesystems


def lsblk():
    return {'blockdevices': [
        {'name': 'sda', 'path': '/dev/sda', 'type': 'disk', 'tran': 'sata', 'fstype': None, 'children': [
            {'name': 'sda1', 'path': '/dev/sda1', 'type': 'part', 'fstype': 'ext4', 'uuid': 'aaaa-system', 'mountpoints': ['/']}]},
        {'name': 'sdb', 'path': '/dev/sdb', 'type': 'disk', 'tran': 'usb', 'model': 'Extreme SSD', 'fstype': None, 'children': [
            {'name': 'sdb1', 'path': '/dev/sdb1', 'type': 'part', 'fstype': 'exfat', 'label': 'Fotos 2026', 'uuid': '1A2B-3C4D',
             'size': 64000000000, 'mountpoints': [None]},
            {'name': 'sdb2', 'path': '/dev/sdb2', 'type': 'part', 'fstype': 'crypto_LUKS', 'uuid': 'cccc', 'mountpoints': [None]}]},
        {'name': 'sdc', 'path': '/dev/sdc', 'type': 'disk', 'tran': 'usb', 'model': 'Stick', 'fstype': 'vfat', 'uuid': 'ABCD-0001',
         'size': 8000000000, 'mountpoints': [None]}]}


class Host(ExternalDrivesMixin):
    def __init__(self, root):
        self.external_root = Path(root)
        self.calls = []
        self.mounted = set()
        self.fail_umount = False

    def command(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == 'lsblk':
            value = lsblk()
            for disk in value['blockdevices']:
                for node in [disk, *disk.get('children', [])]:
                    if node.get('uuid') in self.mounted:
                        node['mountpoints'] = [str(self.external_root / drive_name(node.get('label'), disk.get('model'), node['uuid']))]
            return json.dumps(value)
        if args[0] == 'mount':
            self.mounted.add(args[args.index('--source') + 1].removeprefix('UUID='))
        if args[0] == 'umount':
            if self.fail_umount:
                raise Error('target is busy')
            self.mounted.clear()
        return ''


class InventoryTests(unittest.TestCase):
    def test_only_supported_file_systems_on_usb_disks_are_offered(self):
        found = filesystems(lsblk()['blockdevices'])
        self.assertEqual([item['device'] for item in found], ['/dev/sdb1', '/dev/sdc'])
        self.assertEqual(found[0]['name'], 'extern-fotos-2026-1a2b3c')
        self.assertEqual(found[1]['name'], 'extern-stick-abcd00')
        for item in found:
            self.assertRegex(item['name'], r'^[a-z][a-z0-9_-]{0,30}$')

    def test_names_stay_valid_for_unusual_labels(self):
        for label in ('Ärger & Söhne/..', '', None, 'x' * 80, '../../etc'):
            name = drive_name(label, None, 'FFFF-0000')
            self.assertRegex(name, r'^extern-[a-z0-9]+(?:-[a-z0-9]+)*$')
            self.assertLessEqual(len(name), 31)


class MountTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.host = Host(self.temporary.name)
        owner = type('Owner', (), {'pw_uid': 990, 'pw_gid': 991})()
        self.owner = patch('titan.external_drives.pwd.getpwnam', return_value=owner)
        self.owner.start()

    def tearDown(self):
        self.owner.stop()
        self.temporary.cleanup()

    def mounts(self):
        return [call for call in self.host.calls if call[0] == 'mount']

    def test_automount_is_data_only_and_owned_by_the_service_identity(self):
        self.host.external_automount()
        first, second = self.mounts()
        self.assertEqual(first[first.index('-t') + 1], 'exfat')
        options = first[first.index('-o') + 1].split(',')
        for required in ('nosuid', 'nodev', 'noexec', 'uid=990', 'gid=991', 'umask=007'):
            self.assertIn(required, options)
        self.assertEqual(first[first.index('--source') + 1], 'UUID=1A2B-3C4D')
        self.assertEqual(first[first.index('--target') + 1], str(Path(self.temporary.name) / 'extern-fotos-2026-1a2b3c'))
        self.assertEqual(second[second.index('-t') + 1], 'vfat')
        self.host.external_automount()
        self.assertEqual(len(self.mounts()), 2, 'mounted drives are not mounted twice')

    def test_ejected_drive_is_not_remounted_until_it_is_replugged(self):
        self.host.external_automount()
        result = self.host.op_external_drive_eject('extern-fotos-2026-1a2b3c')
        self.assertTrue(result['ok'])
        self.assertFalse((Path(self.temporary.name) / 'extern-fotos-2026-1a2b3c').exists())
        before = len(self.mounts())
        self.host.external_automount()
        remounted = [call[call.index('--source') + 1] for call in self.mounts()[before:]]
        self.assertNotIn('UUID=1A2B-3C4D', remounted)

    def test_busy_drive_reports_a_clear_error_and_stays_mounted(self):
        self.host.external_automount()
        self.host.fail_umount = True
        with self.assertRaises(Error) as raised:
            self.host.op_external_drive_eject('extern-fotos-2026-1a2b3c')
        self.assertEqual(raised.exception.status, 409)
        self.assertIn('1A2B-3C4D', self.host.mounted)

    def test_unknown_or_malformed_names_are_rejected(self):
        for name in ('dokumente', 'extern-', '../etc', 'extern-nicht-da', 7):
            with self.assertRaises(Error):
                self.host.op_external_drive_eject(name)
        self.assertIsNone(self.host.external_record('dokumente'))
        self.assertIsNone(self.host.external_record('extern-nicht-da'))

    @unittest.skipUnless(os.name == 'posix', 'directory descriptors need POSIX')
    def test_unplugged_mount_directory_is_never_opened_for_file_access(self):
        target = Path(self.temporary.name) / 'extern-stick-abcd00'
        target.mkdir()
        with self.assertRaises(Error) as raised:
            self.host.open_external_root(target)
        self.assertEqual(raised.exception.status, 503)
        with self.assertRaises(Error):
            self.host.open_external_root('/etc')


if __name__ == '__main__':
    unittest.main()

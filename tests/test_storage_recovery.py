"""Recovery commands are captured; these tests never invoke ZFS or block tools."""
import copy
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from titan.core import Error
from titan.demo import Demo
from titan.storage_recovery import StorageRecovery, scan_status, topology, validate_replace


MEMBER = "1000000000000000002"
SIZE = 4 * 1024**4


def output(guid=False, health="DEGRADED", states=("ONLINE", "FAULTED"), layout="mirror", scan="none requested"):
    lines = ["  pool: tank", " state: " + health, "  scan: " + scan, "config:", "", "        NAME STATE READ WRITE CKSUM",
             "        tank " + health + " 0 0 0"]
    if layout:
        lines.append("          " + ("1000000000000000009" if guid else layout + "-0") + " " + health + " 0 0 0")
    for index, state in enumerate(states):
        name = str(1000000000000000001 + index) if guid else "/dev/sd" + chr(ord('a') + index) + "1"
        lines.append(("            " if layout else "          ") + name + " " + state + " 0 0 0")
    lines.extend(["", "errors: No known data errors"])
    return "\n".join(lines)


class StorageRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.settings = {"pools": [{"name": "tank", "mountpoint": "/var/srv/titan/tank"}]}
        self.disks = [
            {"name": "/dev/sda", "type": "disk", "size": SIZE, "serial": "HEALTHY-A", "model": "NAS", "maj:min": "8:0", "ro": False,
             "children": [{"name": "/dev/sda1", "type": "part", "fstype": "zfs_member"}]},
            {"name": "/dev/sdb", "type": "disk", "size": SIZE, "serial": "FAILED-B", "model": "NAS", "maj:min": "8:16", "ro": False, "fstype": "zfs_member"},
            {"name": "/dev/sdc", "type": "disk", "size": SIZE, "serial": "SPARE-C", "model": "NAS", "maj:min": "8:32", "ro": False},
        ]
        self.host = SimpleNamespace(share_root=Path('/var/srv/titan'), load=lambda key, default: self.settings.get(key, default),
                                    disks=lambda: copy.deepcopy(self.disks), volume_manager=SimpleNamespace(blank_disk=Mock(side_effect=self.blank)),
                                    op_smart=Mock(return_value={'smart_status': {'passed': True}}))
        self.health, self.states, self.layout, self.scan = 'DEGRADED', ('ONLINE', 'FAULTED'), 'mirror', 'none requested'
        self.commands = []
        self.manager = StorageRecovery(self.host, self.command)
        self.manager.device_path = lambda disk: '/dev/disk/by-id/ata-' + disk.rsplit('/', 1)[-1]

    def command(self, args, **kwargs):
        self.commands.append(args)
        if args[:2] == ['zpool', 'list']:
            return 'tank'
        if args[:2] == ['zpool', 'get']:
            return '1000000000000000000'
        if args[:2] == ['zpool', 'status']:
            return output('-g' in args, self.health, self.states, self.layout, self.scan)
        if args[:2] == ['zpool', 'replace']:
            return ''
        raise AssertionError('Unexpected command: ' + repr(args))

    def blank(self, disk, filesystem):
        item = next((item for item in self.disks if item['name'] == disk), None)
        if not item or item.get('fstype') or item.get('children') or item.get('mountpoints') or item.get('ro'):
            raise Error('Nur leere, ungemountete und beschreibbare Laufwerke sind zulässig.')
        return os.makedev(8, 32)

    def arguments(self, value=None):
        value = value or self.manager.status('tank')
        return {'pool': 'tank', 'member_guid': MEMBER, 'disk': '/dev/sdc', 'expected_revision': value['revision'],
                'confirmation_pool': 'tank', 'confirmation_disk': '/dev/sdc'}

    def mutations(self):
        return [command for command in self.commands if command[:2] == ['zpool', 'replace']]

    def test_preview_has_guid_topology_blank_candidates_and_stable_revision(self):
        before = self.manager.status('tank')
        self.assertTrue(before['managed'])
        self.assertTrue(before['supported'])
        self.assertEqual(before['layout'], 'mirror')
        self.assertEqual(before['minimum_size'], SIZE)
        self.assertEqual([(item['guid'], item['replaceable']) for item in before['members']],
                         [('1000000000000000001', False), (MEMBER, True)])
        self.assertEqual([item['disk'] for item in before['candidates'] if item['eligible']], ['/dev/sdc'])
        self.assertEqual(before['revision'], self.manager.status('tank')['revision'])
        self.assertEqual(self.mutations(), [])

    def test_replace_checks_device_revalidates_and_starts_without_force_or_waiting(self):
        args = self.arguments()
        info = SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, 32))
        with patch('titan.storage_recovery.os.open', return_value=999) as opened, \
                patch('titan.storage_recovery.os.fstat', return_value=info), \
                patch('titan.storage_recovery.os.stat', return_value=info), \
                patch('titan.storage_recovery.os.close') as close:
            result = self.manager.replace(**args)
        self.assertEqual(self.mutations(), [['zpool', 'replace', 'tank', MEMBER, '/dev/disk/by-id/ata-sdc']])
        self.assertFalse(result['completed'])
        self.assertTrue(result['resilver_started'])
        self.assertEqual(opened.call_args.args[0], '/dev/sdc')
        close.assert_called_once_with(999)
        self.assertGreaterEqual(sum(call.args[0] == '/dev/sdc' for call in self.host.volume_manager.blank_disk.call_args_list), 5)
        self.assertFalse(any(flag in self.mutations()[0] for flag in ('-f', '-s', '-w')))

    def test_stale_disk_serial_pool_guid_and_state_never_mutate(self):
        for change in ('serial', 'state', 'guid'):
            with self.subTest(change=change):
                args = self.arguments()
                if change == 'serial':
                    self.disks[2]['serial'] = 'OTHER-SPARE'
                elif change == 'state':
                    self.health, self.states = 'ONLINE', ('ONLINE', 'ONLINE')
                else:
                    original = self.manager.run
                    self.manager.run = lambda command, **kw: '999' if command[:2] == ['zpool', 'get'] else original(command, **kw)
                with self.assertRaises(Error) as caught:
                    self.manager.replace(**args)
                self.assertEqual(caught.exception.status, 409)
                self.assertEqual(self.mutations(), [])
                self.disks[2]['serial'] = 'SPARE-C'
                self.health, self.states = 'DEGRADED', ('ONLINE', 'FAULTED')
                self.manager.run = self.command

    def test_no_healthy_member_replacement_and_no_wrong_confirmations(self):
        valid = self.arguments()
        for changes in ({'member_guid': '1000000000000000001'}, {'confirmation_pool': 'wrong'}, {'confirmation_disk': '/dev/sda'},
                        {'disk': '/dev/sdc1'}, {'disk': '--help'}, {'pool': '--help'}, {'expected_revision': 'stale'}, {'force': True},
                        {'member_guid': None}, {'member_guid': ['bad']}):
            with self.subTest(changes=changes), self.assertRaises(Error):
                self.manager.replace(**{**valid, **changes})
        self.assertEqual(self.mutations(), [])

    def test_unmanaged_nonredundant_unavailable_and_insufficient_replicas_blocked(self):
        for health, states, layout, managed in (
                ('DEGRADED', ('ONLINE', 'FAULTED'), 'mirror', False),
                ('DEGRADED', ('ONLINE', 'FAULTED'), None, True),
                ('UNAVAIL', ('FAULTED', 'FAULTED'), 'mirror', True),
                ('DEGRADED', ('ONLINE', 'FAULTED', 'FAULTED'), 'raidz1', True)):
            with self.subTest(health=health, states=states, layout=layout, managed=managed):
                self.health, self.states, self.layout = health, states, layout
                self.settings['pools'] = [{'name': 'tank', 'mountpoint': '/var/srv/titan/tank'}] if managed else []
                value = self.manager.status('tank')
                self.assertTrue(value['reason'])
                self.assertFalse(any(item['replaceable'] for item in value['members']))
                with self.assertRaises(Error):
                    self.manager.replace(**self.arguments(value))
        self.assertEqual(self.mutations(), [])

    def test_small_used_readonly_missing_serial_or_signature_disk_is_ineligible(self):
        for changes in ({'size': SIZE - 1}, {'fstype': 'ext4'}, {'children': [{'name': '/dev/sdc1'}]},
                        {'mountpoints': ['/']}, {'ro': True}, {'serial': ''}, {'serial': 'unknown'}, {'serial': '000000'}, {'serial': 'HEALTHY-A'}):
            with self.subTest(changes=changes):
                previous = dict(self.disks[2])
                self.disks[2].update(changes)
                value = self.manager.status('tank')
                candidate = next(item for item in value['candidates'] if item['disk'] == '/dev/sdc')
                self.assertFalse(candidate['eligible'])
                self.assertTrue(candidate['reason'])
                self.disks[2] = previous
        with patch.object(self.host.volume_manager, 'blank_disk', side_effect=Error('Signatur oder Holder gefunden')):
            self.assertFalse(self.manager.status('tank')['candidates'][2]['eligible'])
        self.assertEqual(self.mutations(), [])

    def test_no_persistent_path_failed_or_unavailable_smart_blocks_candidate(self):
        with patch.object(self.manager, 'device_path', side_effect=lambda disk: disk):
            self.assertFalse(self.manager.status('tank')['candidates'][2]['eligible'])
        for data in ({'smart_status': {'passed': False}}, {}, {'smart_status': {'passed': 'yes'}},
                     {'smart_status': {'passed': True}, 'smartctl': {'exit_status': 2}},
                     {'smart_status': {'passed': True}, 'smartctl': {'exit_status': 8}},
                     {'smart_status': {'passed': True}, 'ata_smart_data': {'self_test': {'status': {'passed': False}}}}):
            with patch.object(self.host, 'op_smart', return_value=data):
                candidate = self.manager.status('tank')['candidates'][2]
                self.assertFalse(candidate['eligible'])
                self.assertIn(candidate['smart_health'], ('failed', 'unknown'))
        with patch.object(self.host, 'op_smart', side_effect=Error('SMART unavailable')):
            self.assertFalse(self.manager.status('tank')['candidates'][2]['eligible'])
        with patch.object(self.host, 'op_smart', side_effect=subprocess.TimeoutExpired('smartctl', 30)):
            self.assertFalse(self.manager.status('tank')['candidates'][2]['eligible'])
        self.assertEqual(self.mutations(), [])

    def test_stored_pool_guid_mismatch_blocks_but_legacy_records_still_bind_live_revision(self):
        legacy = self.manager.status('tank')
        self.assertFalse(legacy['identity_confirmed'])
        self.assertTrue(legacy['members'][1]['replaceable'])
        self.settings['pools'][0]['guid'] = '1000000000000000000'
        matching = self.manager.status('tank')
        self.assertTrue(matching['identity_confirmed'])
        self.settings['pools'][0]['guid'] = '999'
        mismatch = self.manager.status('tank')
        self.assertFalse(mismatch['identity_confirmed'])
        self.assertFalse(any(item['replaceable'] for item in mismatch['members']))
        self.assertIn('Poolkennung', mismatch['reason'])
        with self.assertRaises(Error):
            self.manager.replace(**self.arguments(mismatch))
        self.assertEqual(self.mutations(), [])

    def test_numeric_root_guid_must_match_pool_property(self):
        original = self.manager.run
        def different_root(args, **kw):
            result = original(args, **kw)
            return result.replace('        tank DEGRADED', '        999 DEGRADED') if args[:2] == ['zpool', 'status'] and '-g' in args else result
        with patch.object(self.manager, 'run', side_effect=different_root), self.assertRaises(Error):
            self.manager.status('tank')

    def test_redundant_raidz1_and_raidz2_accept_only_tolerated_failures(self):
        for layout, states in (('raidz1', ('ONLINE', 'FAULTED', 'ONLINE')), ('raidz2', ('ONLINE', 'FAULTED', 'FAULTED', 'ONLINE'))):
            with self.subTest(layout=layout):
                self.layout, self.states = layout, states
                # Add physical owners for every healthy leaf and an extra blank candidate.
                for index in range(2, len(states)):
                    name = '/dev/sd' + chr(ord('a') + index)
                    record = {'name': name, 'type': 'disk', 'size': SIZE, 'serial': 'MEMBER-' + name, 'ro': False, 'maj:min': '8:' + str(index * 16),
                              'children': [{'name': name + '1', 'type': 'part', 'fstype': 'zfs_member'}]}
                    if index < len(self.disks):
                        self.disks[index] = record
                    else:
                        self.disks.append(record)
                self.disks.append({'name': '/dev/sdz', 'type': 'disk', 'size': SIZE, 'serial': 'SPARE-Z', 'ro': False, 'maj:min': '8:240'})
                value = self.manager.status('tank')
                self.assertTrue(value['supported'])
                self.assertEqual(sum(item['replaceable'] for item in value['members']), states.count('FAULTED'))
                self.assertTrue(next(item for item in value['candidates'] if item['disk'] == '/dev/sdz')['eligible'])
                self.disks = self.disks[:2] + [{'name': '/dev/sdc', 'type': 'disk', 'size': SIZE, 'serial': 'SPARE-C', 'ro': False, 'maj:min': '8:32'}]

    def test_resilver_and_scrub_progress_blocks_additional_replacement(self):
        for scan, kind in (('resilver in progress since Thu Oct 8 10:00:00 2026\n        42.50% done, 00:10:00 to go', 'resilver'),
                           ('scrub in progress since Thu Oct 8 10:00:00 2026\n        7.00% done, 00:30:00 to go', 'scrub')):
            with self.subTest(kind=kind):
                self.scan = scan
                value = self.manager.status('tank')
                self.assertTrue(value['scan']['active'])
                self.assertEqual(value['scan']['kind'], kind)
                self.assertIsNotNone(value['scan']['progress_percent'])
                self.assertFalse(any(item['replaceable'] for item in value['members']))
        self.assertEqual(self.mutations(), [])

    def test_revalidation_during_pinned_open_or_by_id_retarget_fails_closed(self):
        for stage in ('serial', 'device'):
            args = self.arguments()
            info = SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, 32))
            def opened(*args, **kwargs):
                if stage == 'serial':
                    self.disks[2]['serial'] = 'SWAPPED-DEVICE'
                return 999
            target = info if stage == 'serial' else SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, 48))
            with patch('titan.storage_recovery.os.open', side_effect=opened), \
                    patch('titan.storage_recovery.os.fstat', return_value=info), \
                    patch('titan.storage_recovery.os.stat', return_value=target), \
                    patch('titan.storage_recovery.os.close') as closed, self.assertRaises(Error):
                self.manager.replace(**args)
            closed.assert_called_once_with(999)
            self.disks[2]['serial'] = 'SPARE-C'
        self.assertEqual(self.mutations(), [])

    def test_nested_replacing_topology_and_auxiliary_devices_not_supported(self):
        guids, paths = output(True), output(False)
        self.assertFalse(topology('tank', guids.replace('errors:', 'logs\nerrors:'), paths.replace('errors:', 'logs\nerrors:'))['supported'])
        nested_guids = guids.replace('            ' + MEMBER, '            1000000000000000019 FAULTED 0 0 0\n              ' + MEMBER)
        nested_paths = paths.replace('            /dev/sdb1', '            replacing-1 FAULTED 0 0 0\n              /dev/sdb1')
        self.assertFalse(topology('tank', nested_guids, nested_paths)['supported'])
        multiple_guids = guids.replace('\nerrors:', '\n          1000000000000000029 ONLINE 0 0 0\n            1000000000000000030 ONLINE 0 0 0\n            1000000000000000031 ONLINE 0 0 0\nerrors:')
        multiple_paths = paths.replace('\nerrors:', '\n          mirror-1 ONLINE 0 0 0\n            /dev/sdc1 ONLINE 0 0 0\n            /dev/sdd1 ONLINE 0 0 0\nerrors:')
        self.assertFalse(topology('tank', multiple_guids, multiple_paths)['supported'])
        with self.assertRaises(Error):
            topology('tank', guids, paths.replace('FAULTED', 'ONLINE'))
        with self.assertRaises(Error):
            topology('tank', guids.replace(MEMBER, 'not-a-guid'), paths)

    def test_missing_member_name_can_be_guid_with_previous_path_for_display(self):
        paths = output(False).replace('/dev/sdb1 FAULTED 0 0 0', MEMBER + ' UNAVAIL 0 0 0 was /dev/disk/by-id/ata-old-part1')
        guids = output(True).replace('FAULTED', 'UNAVAIL')
        result = topology('tank', guids, paths)
        self.assertEqual(result['members'][1]['guid'], MEMBER)
        self.assertEqual(result['members'][1]['path'], '/dev/disk/by-id/ata-old-part1')

    def test_missing_import_or_unreadable_guid_refused(self):
        with patch.object(self.manager, 'run', return_value='other'):
            with self.assertRaises(Error):
                self.manager.status('tank')
        def bad_guid(args, **kw):
            return 'tank' if args[:2] == ['zpool', 'list'] else '-'
        with patch.object(self.manager, 'run', side_effect=bad_guid), self.assertRaises(Error):
            self.manager.status('tank')


class StorageRecoveryDemoTests(unittest.TestCase):
    def test_demo_is_memory_only_rejects_healthy_and_bad_candidates_then_shows_progress(self):
        with tempfile.TemporaryDirectory() as directory, patch('subprocess.run') as external:
            demo = Demo(Path(directory))
            try:
                before = demo.call('pool_recovery', pool='tank')
                self.assertEqual(before['health'], 'ONLINE')
                self.assertFalse(any(item['replaceable'] for item in before['members']))
                demo._demo_recovery_failed = True
                failed = demo.call('pool_recovery', pool='tank')
                self.assertEqual(failed['health'], 'DEGRADED')
                args = {'pool': 'tank', 'member_guid': MEMBER, 'disk': '/dev/sdc', 'expected_revision': failed['revision'],
                        'confirmation_pool': 'tank', 'confirmation_disk': '/dev/sdc'}
                for disk in ('/dev/nvme0n1', '/dev/sdd', '/dev/sda'):
                    with self.assertRaises(Error):
                        demo.call('pool_replace', **{**args, 'disk': disk, 'confirmation_disk': disk})
                result = demo.call('pool_replace', **args)
                self.assertTrue(result['simulation'])
                self.assertFalse(result['completed'])
                value = demo.call('pool_recovery', pool='tank')
                self.assertTrue(value['scan']['active'])
                self.assertEqual(value['scan']['kind'], 'resilver')
                self.assertFalse(any(item['replaceable'] for item in value['members']))
                with self.assertRaises(Error):
                    demo.call('pool_replace', **args)
                demo._demo_recovery_started -= 61
                self.assertEqual(demo.call('pool_recovery', pool='tank')['health'], 'ONLINE')
                external.assert_not_called()
            finally:
                demo._temporary.cleanup()


class PoolIdentityPersistenceTests(unittest.TestCase):
    def test_new_pool_remembers_actual_guid_without_forcing_disks(self):
        from titan.host import Host
        with tempfile.TemporaryDirectory() as directory:
            host = Host(directory, directory, directory)
            host.save('pools', [{'name': 'tank', 'mountpoint': str(Path(directory) / 'tank'), 'guid': 'old-guid'}])
            disks = [{'name': '/dev/sda', 'type': 'disk'}, {'name': '/dev/sdb', 'type': 'disk'}]
            def command(args, **kw):
                if args[0] == 'wipefs':
                    return '{"signatures": []}'
                if args[:2] == ['zpool', 'get']:
                    return '123456789'
                return ''
            with patch.object(host, 'disks', return_value=disks), patch.object(host, 'op_storage', return_value={'pools': []}), \
                    patch('titan.host.run', side_effect=command) as run:
                host.op_pool_create('tank', 'mirror', ['/dev/sda', '/dev/sdb'], 'tank')
            self.assertEqual(host.load('pools', [])[0]['guid'], '123456789')
            commands = [call.args[0] for call in run.call_args_list]
            self.assertTrue(any(args[:2] == ['zpool', 'create'] for args in commands))
            self.assertFalse(any('-f' in args for args in commands))

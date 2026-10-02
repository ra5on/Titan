"""Grow only Titan' mounted, final plain GPT/XFS system partition.

No caller supplies a device or a size. /var and /sysroot must identify the
same filesystem; /var is the verified writable bind mount used by xfs_growfs.
growpart preserves partition starts/identities and updates the kernel using
partx. Every boot retries safely, including recovery after partition-only grow.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from .core import Error

LOCK = Path('/run/titan-system-grow.lock')
MIN_GROW = 1024 * 1024
ROOT_TYPE = '4f68bce3-e8cd-4db1-96e7-fbcaf984b709'
BOOT_TYPES = {'21686148-6449-6e6f-744e-656564454649',
              'c12a7328-f81f-11d2-ba4b-00a0c93ec93b',
              'bc13c2ff-59e6-4262-a352-b275fd6f7172'}
DEVICE = re.compile(r'/dev/[A-Za-z0-9_./-]+')
UUID = re.compile(r'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}')
MAJMIN = re.compile(r'[0-9]+:[0-9]+')
CHANGE = re.compile(r'CHANGE: partition=(\d+) start=(\d+) old: size=(\d+) end=(\d+) new: size=(\d+) end=(\d+)')


def command(arguments, timeout=30):
    try:
        return subprocess.run(arguments, capture_output=True, text=True, timeout=timeout,
                              env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C.UTF-8'})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Error(f'Systemdatenträger konnte nicht geprüft/erweitert werden: {arguments[0]}: {exc}', 503) from None


def positive(value):
    if (not isinstance(value, (int, str)) or isinstance(value, bool)
            or isinstance(value, str) and not re.fullmatch(r'[0-9]+', value)):
        raise ValueError('invalid integer size')
    number = int(value)
    if number <= 0:
        raise ValueError('nonpositive size')
    return number


def unsupported(message):
    raise Error(message, 409)


def device_path(value):
    if not isinstance(value, str) or not DEVICE.fullmatch(value) or '..' in value.split('/'):
        unsupported('Die Systemgerätekennung ist ungültig.')
    resolved = os.path.realpath(value)
    if not DEVICE.fullmatch(resolved):
        unsupported('Das Systemgerät ist kein lokales Blockgerät.')
    return resolved


class SystemDisk:
    def __init__(self, runner=None, lock_path=None):
        self.runner = runner or command
        self.lock_path = Path(lock_path or LOCK)

    def _run(self, arguments, allowed=(0,), timeout=30):
        result = self.runner(arguments, timeout=timeout)
        if result.returncode not in allowed:
            raise Error((result.stderr.strip() or result.stdout.strip() or f'{arguments[0]} fehlgeschlagen.')[-2000:], 503)
        return result

    def _json(self, arguments):
        def pairs(values):
            result = {}
            for key, value in values:
                if key in result:
                    raise ValueError('duplicate key')
                result[key] = value
            return result
        return json.loads(self._run(arguments).stdout, object_pairs_hook=pairs)

    def _mount(self, path):
        data = self._json(['findmnt', '--json', '--target', path, '--output', 'TARGET,SOURCE,FSTYPE,OPTIONS,MAJ:MIN,FSROOT'])
        rows = data.get('filesystems', [])
        if len(rows) != 1 or rows[0].get('target') != path or rows[0].get('children'):
            unsupported(f'{path} ist nicht eindeutig als Systemdateisystem eingehängt.')
        row = rows[0]
        if row.get('fstype') != 'xfs' or not MAJMIN.fullmatch(str(row.get('maj:min', ''))):
            unsupported('Automatische Systemerweiterung unterstützt ausschließlich das unveränderte Titan-XFS-Layout.')
        if os.path.realpath(path) != path:
            unsupported(f'{path} darf kein symbolischer Link sein.')
        actual = os.stat(path).st_dev
        if f'{os.major(actual)}:{os.minor(actual)}' != row['maj:min']:
            unsupported(f'Die Gerätezuordnung von {path} hat sich geändert.')
        return row

    def _block(self, row):
        path = device_path(row['name'])
        actual = os.stat(path)
        if not stat.S_ISBLK(actual.st_mode) or f'{os.major(actual.st_rdev)}:{os.minor(actual.st_rdev)}' != row['maj:min']:
            unsupported('Das erkannte Systemgerät stimmt nicht mit dem tatsächlichen Blockgerät überein.')
        if row.get('ro') not in (False, 0) or row.get('rm') not in (False, 0):
            unsupported('Schreibgeschützte oder entfernbare Systemdatenträger werden nicht automatisch erweitert.')
        return path

    def _inspect(self):
        var, root = self._mount('/var'), self._mount('/sysroot')
        if var['maj:min'] != root['maj:min'] or root.get('fsroot') != '/':
            unsupported('/var und /sysroot liegen nicht auf derselben unveränderten Systempartition.')
        if 'rw' not in var.get('options', '').split(',') or 'ro' in var.get('options', '').split(','):
            unsupported('/var ist schreibgeschützt; das Systemdateisystem kann nicht erweitert werden.')
        data = self._json(['lsblk', '--json', '--bytes', '--paths', '--list', '--output',
                          'NAME,TYPE,MAJ:MIN,SIZE,RO,RM,FSTYPE,UUID,PARTTYPE,PARTLABEL,PARTUUID,PKNAME,LOG-SEC'])
        rows = data.get('blockdevices', [])
        matches = [row for row in rows if row.get('maj:min') == var['maj:min']]
        if len(matches) != 1 or matches[0].get('type') != 'part':
            unsupported('LUKS, LVM, RAID, Multipath und andere zusammengesetzte Systemgeräte werden nicht automatisch erweitert.')
        part = matches[0]
        partition = self._block(part)
        parents = [row for row in rows if device_path(row['name']) == device_path(part.get('pkname'))]
        if len(parents) != 1 or parents[0].get('type') != 'disk':
            unsupported('Die Systempartition hat keinen eindeutigen einfachen Systemdatenträger.')
        disk_row = parents[0]
        disk = self._block(disk_row)
        if any(row.get('pkname') and device_path(row['pkname']) == partition for row in rows):
            unsupported('Die Systempartition besitzt zusätzliche Gerätezuordnungen; eine Erweiterung ist gesperrt.')
        number = positive(Path(f'/sys/dev/block/{part["maj:min"]}/partition').read_text().strip())
        if number > 128 or part.get('fstype') != 'xfs' or str(part.get('parttype', '')).lower() != ROOT_TYPE or part.get('partlabel') != 'root':
            unsupported('Die eingehängte Partition ist nicht die erwartete Titan-XFS-Systempartition mit GPT-Kennung root.')
        if not UUID.fullmatch(str(part.get('uuid', ''))) or not UUID.fullmatch(str(part.get('partuuid', ''))):
            unsupported('Eindeutige UUIDs der Systempartition und ihres Dateisystems fehlen.')
        table = self._json(['sfdisk', '--json', disk]).get('partitiontable', {})
        sector = positive(table.get('sectorsize'))
        disk_size, partition_size = positive(disk_row['size']), positive(part['size'])
        if (table.get('label') != 'gpt' or table.get('unit') != 'sectors' or device_path(table.get('device')) != disk
                or not UUID.fullmatch(str(table.get('id', ''))) or sector not in (512, 4096)
                or positive(disk_row['log-sec']) != sector or disk_size % sector):
            unsupported('Die GPT-Systempartitionstabelle oder Sektorgröße wird nicht unterstützt.')
        partitions = table.get('partitions', [])
        if not isinstance(partitions, list) or not partitions:
            unsupported('Die GPT-Systempartitionstabelle ist leer oder ungültig.')
        selected = [item for item in partitions if device_path(item.get('node')) == partition]
        if len(selected) != 1:
            unsupported('Die Systempartition ist in GPT nicht eindeutig vorhanden.')
        selected = selected[0]
        start, size = positive(selected['start']), positive(selected['size'])
        if (size * sector != partition_size or selected.get('name') != 'root' or str(selected.get('type', '')).lower() != ROOT_TYPE
                or str(selected.get('uuid', '')).lower() != part['partuuid'].lower() or selected.get('attrs')):
            unsupported('GPT- und Kernelstatus der Systempartition stimmen nicht überein; nach einem Neustart erneut prüfen.')
        # Linux block sysfs always reports 512-byte sectors, including 4Kn
        # devices. A mounted partition may retain the previous kernel start
        # after someone rewrites GPT; matching sizes alone are insufficient.
        kernel_start = positive(Path(f'/sys/dev/block/{part["maj:min"]}/start').read_text().strip()) * 512
        if kernel_start != start * sector:
            unsupported('GPT- und Kernelstart der Systempartition unterscheiden sich. Keine Erweiterung; Systemdatenträger zuerst prüfen.')
        previous_end, seen = 0, set()
        for item in sorted(partitions, key=lambda value: positive(value['start'])):
            item_start, item_size = positive(item['start']), positive(item['size'])
            node = device_path(item.get('node'))
            if node in seen or item_start <= previous_end or item_start + item_size > disk_size // sector - 33:
                unsupported('Die Partitionen überlappen oder überschreiten die Systemdatenträgergröße.')
            seen.add(node)
            previous_end = item_start + item_size - 1
            if node != partition and str(item.get('type', '')).lower() not in BOOT_TYPES:
                unsupported('Der Systemdatenträger enthält weitere Datenpartitionen; eine automatische Erweiterung ist gesperrt.')
        if start + size - 1 != previous_end:
            unsupported('Hinter der Systempartition liegt eine weitere Partition. Sie kann nicht sicher erweitert werden.')
        # Verify a dry-run against the actual table; growpart understands stale
        # backup GPT headers after a hypervisor enlarged the physical disk.
        preview = self._run(['growpart', '--dry-run', '--fudge', '0', '--update=on', disk, str(number)], allowed=(0, 1))
        new_size = size
        if preview.returncode == 1:
            if not preview.stdout.strip().startswith('NOCHANGE:'):
                unsupported('growpart konnte den freien Endbereich nicht eindeutig prüfen.')
        else:
            lines = preview.stdout.strip().splitlines()
            match = CHANGE.fullmatch(lines[0]) if len(lines) == 1 else None
            if not match:
                unsupported('growpart hat keinen eindeutig prüfbaren Erweiterungsplan geliefert.')
            plan_number, plan_start, old_size, old_end, new_size, new_end = map(int, match.groups())
            if (plan_number != number or plan_start != start or old_size != size or old_end != start + size - 1
                    or new_size <= size or new_end != start + new_size - 1 or new_end >= disk_size // sector - 33):
                unsupported('Der Erweiterungsplan verschiebt oder überschreitet die Systempartition.')
        geometry = self._run(['xfs_info', '/var']).stdout
        match = re.search(r'^data\s*=\s*bsize=(\d+)\s+blocks=(\d+)', geometry, re.MULTILINE)
        if not match or not re.search(r'^log\s*=\s*internal\b', geometry, re.MULTILINE) or not re.search(r'^realtime\s*=\s*none\b', geometry, re.MULTILINE):
            unsupported('Die XFS-Geometrie benötigt externe Geräte oder ist nicht eindeutig prüfbar.')
        blocksize, blocks = map(positive, match.groups())
        filesystem_size = blocksize * blocks
        if filesystem_size > partition_size:
            unsupported('Das XFS-Dateisystem ist größer als die erkannte Systempartition.')
        usage = os.statvfs('/var')
        partition_delta = (new_size - size) * sector
        filesystem_delta = partition_size - filesystem_size
        available = partition_delta >= MIN_GROW or filesystem_delta >= MIN_GROW
        proof = {'var': var, 'root': root, 'disk_major_minor': disk_row['maj:min'],
                 'partition_major_minor': part['maj:min'], 'table': table, 'new_size': new_size,
                 'filesystem_blocks': blocks, 'filesystem_blocksize': blocksize}
        identity = {'proof': proof, 'disk_size': disk_size, 'partition_size': partition_size,
                    'filesystem_uuid': part['uuid'], 'partition_uuid': part['partuuid']}
        revision = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        state = {'supported': True, 'available': available, 'revision': revision,
                 'reason': 'Freier Platz des Systemdatenträgers kann sicher genutzt werden.' if available else 'Die Systempartition und ihr XFS-Dateisystem nutzen bereits den verfügbaren Platz.',
                 'disk': disk, 'partition': partition, 'partition_number': number, 'filesystem': 'xfs', 'mountpoint': '/var',
                 'disk_size': disk_size, 'partition_size': partition_size, 'filesystem_size': filesystem_size,
                 'filesystem_used': (usage.f_blocks - usage.f_bfree) * usage.f_frsize,
                 'filesystem_available': usage.f_bavail * usage.f_frsize,
                 'partition_growable_bytes': partition_delta, 'filesystem_growable_bytes': filesystem_delta,
                 'growable_bytes': partition_delta + filesystem_delta,
                 'partition_start': start * sector, 'partition_uuid': part['partuuid'],
                 'filesystem_uuid': part['uuid'], 'disk_uuid': table['id'], 'sector_size': sector}
        return state, proof

    def status(self):
        try:
            return self._inspect()[0]
        except (Error, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            reason = str(exc) if isinstance(exc, Error) else 'Die Systemdatenträgerdaten konnten nicht eindeutig geprüft werden: ' + str(exc)
            return {'supported': False, 'available': False, 'revision': None, 'reason': reason,
                    'disk': None, 'partition': None, 'partition_number': None, 'filesystem': None, 'mountpoint': '/var',
                    'disk_size': None, 'partition_size': None, 'filesystem_size': None,
                    'filesystem_used': None, 'filesystem_available': None,
                    'partition_growable_bytes': None, 'filesystem_growable_bytes': None, 'growable_bytes': None}

    def grow(self, expected_revision, confirmation):
        if not isinstance(expected_revision, str) or not re.fullmatch(r'[a-f0-9]{64}', expected_revision) or confirmation != 'ERWEITERN':
            raise Error('Aktueller Systemdatenträgerstatus und Bestätigung ERWEITERN sind erforderlich.')
        return self._grow(expected_revision)

    def _grow(self, expected_revision=None):
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Error('Der Systemdatenträger wird bereits erweitert. Status später erneut prüfen.', 409) from None
            try:
                before, proof = self._inspect()
                if expected_revision is not None and before['revision'] != expected_revision:
                    raise Error('Die Systemdatenträgergröße oder Gerätezuordnung hat sich geändert. Status erneut laden.', 409)
                fresh, _ = self._inspect()
                if fresh['revision'] != before['revision']:
                    raise Error('Der Systemdatenträger hat sich während der Prüfung geändert. Status erneut laden.', 409)
                if not before['available']:
                    return {'ok': True, 'changed': False, 'partition_grown': False, 'filesystem_grown': False,
                            'before': before, 'after': fresh, 'message': before['reason']}
                if before['partition_growable_bytes'] >= MIN_GROW:
                    self._run(['growpart', '--fudge', '0', '--update=on', before['disk'], str(before['partition_number'])], timeout=120)
                intermediate, changed_proof = self._inspect()
                self._verify(before, proof, intermediate, changed_proof)
                # /sysroot may be RO. The same XFS filesystem is deliberately
                # grown through its proven writable /var bind mount instead.
                self._run(['xfs_growfs', '-d', '/var'], timeout=120)
                after, final_proof = self._inspect()
                self._verify(before, proof, after, final_proof)
                if after['available'] or after['filesystem_size'] <= before['filesystem_size']:
                    raise Error('Die Systemerweiterung wurde nicht vollständig bestätigt. Status prüfen; ein Neustart setzt die sichere Erweiterung fort.', 503)
                partition_grown = after['partition_size'] > before['partition_size']
                filesystem_grown = after['filesystem_size'] > before['filesystem_size']
                return {'ok': True, 'changed': partition_grown or filesystem_grown,
                        'partition_grown': partition_grown, 'filesystem_grown': filesystem_grown,
                        'before': before, 'after': after, 'message': 'Die Systempartition und ihr XFS-Dateisystem nutzen jetzt den verfügbaren Systemdatenträgerplatz.'}
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                raise Error(f'Die Systemdatenträgerprüfung ist fehlgeschlagen: {exc}', 503) from None
        finally:
            os.close(fd)

    def _verify(self, before, proof, after, changed_proof):
        stable = ('disk', 'partition', 'partition_number', 'disk_size', 'partition_start', 'partition_uuid', 'filesystem_uuid', 'disk_uuid', 'sector_size')
        old_table, new_table = proof['table'], changed_proof['table']
        old_parts = {item['node']: item for item in old_table['partitions']}
        new_parts = {item['node']: item for item in new_table['partitions']}
        valid = all(before[key] == after[key] for key in stable) and old_parts.keys() == new_parts.keys()
        for node, item in old_parts.items():
            compared = dict(new_parts.get(node, {}))
            if node == before['partition']:
                compared['size'] = item['size']
            valid = valid and compared == item
        if (not valid or after['partition_size'] < before['partition_size'] or after['filesystem_size'] < before['filesystem_size']
                or after['partition_size'] != proof['new_size'] * before['sector_size']):
            raise Error('Gerätekennung oder Partitionstabelle hat sich unerwartet geändert. Weitere Erweiterung ist gesperrt.', 503)


def main():
    parser = argparse.ArgumentParser(description='Titan Systemdisk sicher beim Start erweitern')
    parser.add_argument('--boot', action='store_true')
    args = parser.parse_args()
    manager = SystemDisk()
    if not args.boot:
        print(json.dumps(manager.status(), ensure_ascii=False))
        return 0
    try:
        result = manager._grow()
        print('Titan Systemdatenträger: ' + result['message'], flush=True)
    except Exception as exc:
        # Growth is best effort; a disk/layout problem must never suppress the
        # web interface or interrupt boot. The admin status explains the issue.
        print('Titan Systemdatenträger nicht erweitert: ' + str(exc), file=sys.stderr, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())

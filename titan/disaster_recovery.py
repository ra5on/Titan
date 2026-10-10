#!/usr/bin/env python3
"""Titan cold whole-disk recovery. Standalone Python 3, no Titan installation needed.

Run from an independent Linux rescue system. Never operates on mounted disks.
The packet includes the OS and every disk in an exported inventory, preserving
ZFS metadata/snapshots, account IDs, ACLs, containers and VM disks byte for byte.
"""
import argparse
import contextlib
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

FORMAT = 'titan-cold-recovery-v1'
CHUNK = 4 * 1024 * 1024
HEADER = 1024 * 1024
MAX_DISKS = 128


class RecoveryError(Exception):
    pass


def command(args):
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return result.stdout


def strict_json(data):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value: raise RecoveryError('Doppelter Schlüssel in Metadaten.')
            value[key] = item
        return value
    return json.loads(data, object_pairs_hook=unique)


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + '.new')
    if tmp.exists():
        read_private(tmp)  # A crash may leave only our private incomplete journal.
        tmp.unlink()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if tmp.exists(): tmp.unlink()


def private_directory(path, create=False):
    path = Path(os.path.abspath(path))
    # Reject links at every component, including a symlinked parent.
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor /= part
        if create and cursor == path: cursor.mkdir(mode=0o700)
        info = cursor.lstat()
        if not stat.S_ISDIR(info.st_mode): raise RecoveryError('Kein unverlinktes Verzeichnis: ' + str(cursor))
    info = path.stat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise RecoveryError('Sicherungsverzeichnis muss dem ausführenden Benutzer gehören und Modus 0700 haben.')
    return path


def read_private(path, maximum=1024*1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > maximum:
            raise RecoveryError('Ungeschützte oder ungültige Metadaten.')
        return stream.read()


def digest_fd(fd, size, *, substitute_header=None, substitute_tail=None):
    h = hashlib.sha256(); offset = 0
    while offset < size:
        block = os.pread(fd, min(CHUNK, size-offset), offset)
        if not block: raise RecoveryError('Datenträger endet vor der erwarteten Größe.')
        if substitute_header is not None and offset < len(substitute_header):
            count = min(len(block), len(substitute_header)-offset)
            block = substitute_header[offset:offset+count] + block[count:]
        if substitute_tail is not None:
            tail_start = size-len(substitute_tail)
            start = max(offset, tail_start)
            end = min(offset+len(block), size)
            if start < end:
                block = block[:start-offset] + substitute_tail[start-tail_start:end-tail_start] + block[end-offset:]
        h.update(block); offset += len(block)
    return h.hexdigest()


def write_at(fd, block, offset):
    while block:
        count = os.pwrite(fd, block, offset)
        if count <= 0: raise RecoveryError('Schreibvorgang blieb unvollständig.')
        offset += count; block = block[count:]


def validate_disks(disks):
    if not isinstance(disks, list) or not 1 <= len(disks) <= MAX_DISKS:
        raise RecoveryError('Ungültige Laufwerksliste.')
    ids, identities = set(), set()
    for disk in disks:
        if (not isinstance(disk, dict) or not re.fullmatch(r'disk-[0-9]{3}', str(disk.get('id', '')))
                or disk['id'] in ids or not isinstance(disk.get('identity'), str) or not disk['identity']
                or len(disk['identity']) > 512 or disk['identity'] in identities
                or type(disk.get('size')) is not int or not 2*HEADER <= disk['size'] <= 1024**5
                or disk.get('sector') not in (512, 4096) or disk['size'] % disk['sector']
                or type(disk.get('system')) is not bool):
            raise RecoveryError('Unvollständige oder mehrdeutige Laufwerkskennung.')
        ids.add(disk['id']); identities.add(disk['identity'])
    if not any(disk['system'] for disk in disks): raise RecoveryError('Systemlaufwerk fehlt.')
    return disks


def block_inventory():
    data = strict_json(command(['lsblk', '--json', '--bytes', '--paths', '--output',
                               'NAME,TYPE,SIZE,MAJ:MIN,SERIAL,WWN,LOG-SEC,MOUNTPOINTS,MODEL']))
    disks = []
    for entry in data['blockdevices']:
        if entry.get('type') != 'disk': continue
        wwn = str(entry.get('wwn') or '').strip()
        serial = str(entry.get('serial') or '').strip()
        identity = 'wwn:' + wwn if wwn else 'serial:' + serial if serial else None
        def walk(node):
            yield node
            for child in node.get('children', []): yield from walk(child)
        children = list(walk(entry))
        disks.append({'path': entry['name'], 'identity': identity, 'size': int(entry['size']),
                      'sector': int(entry['log-sec']), 'model': str(entry.get('model') or '').strip(),
                      'devices': [item['maj:min'] for item in children],
                      'nodes': [item['name'] for item in children],
                      'mounted': any(any(m is not None for m in item.get('mountpoints', [])) for item in children),
                      'type': entry['type']})
    return disks


def disk_for_device(disks, device):
    key = f'{os.major(device)}:{os.minor(device)}'
    matches = [disk for disk in disks if key in disk['devices']]
    if len(matches) != 1: raise RecoveryError('Speicher kann keinem einzelnen physischen Laufwerk zugeordnet werden: ' + key)
    return matches[0]


def live_inventory(target):
    """Export all local disks except the independent backup destination.

    The host caller additionally checks managed storage does not use that target.
    No disks are read or changed here; only topology and metadata are queried.
    """
    if not Path('/usr/share/titan/image-info.json').is_file():
        raise RecoveryError('Vollständige Sicherung benötigt eine Titan-A/B-Installation.')
    disks = block_inventory()
    system = disk_for_device(disks, os.stat('/var/lib/titan-system').st_dev)
    excluded = disk_for_device(disks, os.stat(target).st_dev)
    if system == excluded: raise RecoveryError('Das Sicherungsziel liegt auf der Systemplatte.')
    selected = [disk for disk in disks if disk != excluded]
    records = [{**{key: disk[key] for key in ('identity', 'size', 'sector', 'model')},
                'id': f'disk-{number:03}', 'system': disk == system} for number, disk in enumerate(selected, 1)]
    validate_disks(records)
    return {'format': FORMAT, 'created': time.time(), 'disks': records,
            'excluded_identity': excluded['identity'], 'architecture': 'x86_64'}


@contextlib.contextmanager
def pin_disks(records, mapping, *, writing=False, resumed=False):
    """Exclusive block descriptors held through the entire operation, not path reopens."""
    if os.geteuid() != 0: raise RecoveryError('Im Rettungssystem als root starten.')
    disks = block_inventory(); descriptors = {}; used = set()
    try:
        for record in records:
            wanted = mapping[record['id']]
            candidates = [disk for disk in disks if disk['identity'] == wanted]
            if len(candidates) != 1: raise RecoveryError('Laufwerk fehlt oder Kennung ist mehrdeutig: ' + str(wanted))
            disk = candidates[0]
            if disk['identity'] in used or disk['mounted']:
                raise RecoveryError('Laufwerk wird verwendet oder ist mehrfach zugeordnet.')
            used.add(disk['identity'])
            if disk['size'] < record['size'] or disk['sector'] != record['sector']:
                raise RecoveryError('Ziel ist zu klein oder verwendet eine andere logische Sektorgröße.')
            if not writing and disk['size'] != record['size']:
                raise RecoveryError('Quelllaufwerk wurde seit der Inventarisierung verändert.')
            for node in disk['devices']:
                holders = Path('/sys/dev/block') / node / 'holders'
                if not holders.is_dir() or any(holders.iterdir()):
                    raise RecoveryError('Datenträger wird von einem anderen Speicherverbund verwendet.')
            # O_EXCL on a block device prevents mounting/claiming it while pinned.
            fd = os.open(disk['path'], (os.O_RDWR if writing else os.O_RDONLY) | os.O_EXCL | os.O_NOFOLLOW)
            descriptors[record['id']] = fd
            info = os.fstat(fd)
            expected = os.makedev(*map(int, disk['devices'][0].split(':')))
            if not stat.S_ISBLK(info.st_mode) or info.st_rdev != expected:
                raise RecoveryError('Laufwerk wurde während der Prüfung ersetzt.')
            if writing and not resumed:
                result = strict_json(command(['wipefs', '--json', '--no-act', disk['path']]))
                if result.get('signatures'): raise RecoveryError('Zielplatte enthält Signaturen. Nur zuvor geleerte Test-/Ersatzplatten verwenden.')
        yield descriptors
    finally:
        for fd in descriptors.values(): os.close(fd)


def pack_disk(fd, output, size):
    h = hashlib.sha256(); offset = 0
    with output.open('xb') as destination:
        os.chmod(output, 0o600)
        with gzip.GzipFile(fileobj=destination, mode='wb', compresslevel=1, mtime=0) as stream:
            while offset < size:
                block = os.pread(fd, min(CHUNK, size-offset), offset)
                if not block: raise RecoveryError('Quellplatte ist unvollständig lesbar.')
                stream.write(block); h.update(block); offset += len(block)
        destination.flush(); os.fsync(destination.fileno())
    return {'raw_sha256': h.hexdigest(), 'compressed_size': output.stat().st_size}


class Packet:
    def __init__(self, directory):
        self.directory = private_directory(directory)
        raw = read_private(self.directory/'manifest.json')
        self.fingerprint = hashlib.sha256(raw).hexdigest()
        self.manifest = strict_json(raw)
        if (not isinstance(self.manifest, dict) or self.manifest.get('format') != FORMAT
                or self.manifest.get('complete') is not True or self.manifest.get('architecture') != 'x86_64'):
            raise RecoveryError('Keine vollständige Titan-Systemsicherung.')
        self.disks = validate_disks(self.manifest.get('disks'))
        names = {'manifest.json'}
        for disk in self.disks:
            if (disk.get('file') != disk['id']+'.img.gz' or not re.fullmatch(r'[a-f0-9]{64}', str(disk.get('raw_sha256', '')))
                    or type(disk.get('compressed_size')) is not int or disk['compressed_size'] <= 0):
                raise RecoveryError('Ungültige Archivbeschreibung.')
            names.add(disk['file'])
        if set(os.listdir(self.directory)) != names: raise RecoveryError('Unvollständiges oder verändertes Sicherungsverzeichnis.')

    @contextlib.contextmanager
    def stream(self, disk):
        fd = os.open(self.directory/disk['file'], os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077
                    or info.st_size != disk['compressed_size'] or info.st_dev != self.directory.stat().st_dev):
                raise RecoveryError('Unsicheres oder verändertes Archiv.')
            with gzip.GzipFile(fileobj=source, mode='rb') as stream: yield stream

    def blocks(self, disk):
        size = 0; digest = hashlib.sha256()
        with self.stream(disk) as stream:
            while block := stream.read(CHUNK):
                size += len(block)
                if size > disk['size']: raise RecoveryError('Archiv überschreitet die erwartete Größe.')
                digest.update(block); yield block
        if size != disk['size'] or digest.hexdigest() != disk['raw_sha256']:
            raise RecoveryError('Sicherung ist beschädigt. Größe oder Prüfsumme stimmt nicht.')

    def verify(self):
        for disk in self.disks:
            for _ in self.blocks(disk): pass
        return self.fingerprint


def backup(directory, inventory, descriptors):
    disks = validate_disks(inventory['disks'])
    if set(descriptors) != {disk['id'] for disk in disks}: raise RecoveryError('Mindestens eine Quellplatte fehlt.')
    directory = private_directory(directory, create=True)
    completed = []
    for disk in disks:
        filename = disk['id']+'.img.gz'
        print('Sichere ' + disk['id'], flush=True)
        completed.append({**disk, 'file': filename, **pack_disk(descriptors[disk['id']], directory/filename, disk['size'])})
    atomic_json(directory/'manifest.json', {'format': FORMAT, 'architecture': 'x86_64', 'created': time.time(),
                                          'complete': True, 'disks': completed})
    # Read the completed packet back before reporting success.
    return Packet(directory).verify()


def restore(packet, descriptors, mapping, journal_path, *, resume=False, sparse_files=False, checkpoint=None):
    """Core transfer. Production descriptors come exclusively from pin_disks.

    sparse_files is private to disposable regular-file tests, never a CLI option.
    The system disk's boot header is published only after ALL disk data verifies.
    """
    packet.verify()  # Verify EVERY archive before the first target write.
    expected = {disk['id'] for disk in packet.disks}
    if set(descriptors) != expected or set(mapping) != expected or len(set(mapping.values())) != len(expected):
        raise RecoveryError('Jedes Laufwerk muss genau einem eigenen Ziel zugeordnet werden.')
    if any(identity in {d['identity'] for d in packet.disks} for identity in mapping.values()):
        raise RecoveryError('Originalplatten dürfen nicht als Wiederherstellungsziel verwendet werden.')
    for disk in packet.disks:
        info = os.fstat(descriptors[disk['id']])
        if sparse_files and (not stat.S_ISREG(info.st_mode) or info.st_size < disk['size']):
            raise RecoveryError('Ungültige isolierte Testdatei.')
    journal_path = Path(journal_path)
    private_directory(journal_path.parent)
    identity = {'fingerprint': packet.fingerprint, 'targets': mapping}
    if resume:
        saved = strict_json(read_private(journal_path))
        if any(saved.get(key) != value for key, value in identity.items()):
            raise RecoveryError('Wiederaufnahme gehört zu einer anderen Sicherung oder anderen Zielplatten.')
        if saved.get('state') == 'complete':
            for disk in packet.disks:
                if digest_fd(descriptors[disk['id']], disk['size']) != disk['raw_sha256']:
                    raise RecoveryError('Bereits abgeschlossene Wiederherstellung wurde nachträglich verändert.')
            return saved
    elif journal_path.exists(): raise RecoveryError('Wiederherstellungsjournal existiert bereits. Explizit wiederaufnehmen.')
    def report(state, **extra):
        value = {**identity, 'state': state, 'updated': time.time(), **extra}
        atomic_json(journal_path, value)
        if checkpoint: checkpoint(state, value)
        return value
    report('writing')
    # Invalidate all primary partition tables and bootloaders before data copy.
    for disk in packet.disks:
        fd = descriptors[disk['id']]
        if sparse_files:
            length = os.fstat(fd).st_size
            os.ftruncate(fd, 0); os.ftruncate(fd, length)
        write_at(fd, bytes(HEADER), 0)
        # Withhold the backup GPT too: firmware can recover a missing primary
        # table from the final sectors and otherwise boot an incomplete restore.
        write_at(fd, bytes(HEADER), disk['size']-HEADER); os.fsync(fd)
    headers, tails = {}, {}
    for disk in packet.disks:
        fd = descriptors[disk['id']]; offset = 0; header = bytearray(); tail = bytearray()
        print('Stelle wieder her: ' + disk['id'], flush=True)
        for block in packet.blocks(disk):
            start = min(len(block), max(0, HEADER-offset))
            if start: header.extend(block[:start])
            end = max(start, min(len(block), disk['size']-HEADER-offset))
            if offset+len(block) > disk['size']-HEADER:
                tail.extend(block[max(0, disk['size']-HEADER-offset):])
            remaining = block[start:end]
            if remaining:
                if sparse_files and remaining == bytes(len(remaining)):
                    # The entire test file was reset to a zero-filled sparse file.
                    pass
                else: write_at(fd, remaining, offset+start)
            offset += len(block)
        os.fsync(fd)
        if digest_fd(fd, disk['size'], substitute_header=header, substitute_tail=tail) != disk['raw_sha256']:
            raise RecoveryError('Zurückgelesene Zielplatte stimmt nicht mit der Sicherung überein.')
        headers[disk['id']] = bytes(header)
        tails[disk['id']] = bytes(tail)
        report('disk_verified', disk=disk['id'])
    report('committing')
    # Data disks first, boot/system disk(s) last. All data is complete by now.
    for disk in sorted(packet.disks, key=lambda item: item['system']):
        fd = descriptors[disk['id']]
        write_at(fd, tails[disk['id']], disk['size']-HEADER)
        write_at(fd, headers[disk['id']], 0); os.fsync(fd)
        if digest_fd(fd, disk['size']) != disk['raw_sha256']:
            raise RecoveryError('Abschließende Prüfung der Zielplatte fehlgeschlagen.')
    return report('complete')


def load_inventory(path):
    value = strict_json(Path(path).read_bytes())
    if not isinstance(value, dict) or value.get('format') != FORMAT or value.get('architecture') != 'x86_64':
        raise RecoveryError('Ungültiger Rettungsplan.')
    validate_disks(value.get('disks'))
    return value


def choose(title, items, label):
    if not items: raise RecoveryError('Keine passenden Einträge verfügbar: ' + title)
    print('\n' + title)
    for number, item in enumerate(items, 1): print(f'{number}. {label(item)}')
    value = input('Nummer (Enter = Abbruch): ').strip()
    if not value.isdigit() or not 1 <= int(value) <= len(items): raise RecoveryError('Abgebrochen.')
    return items[int(value)-1]


def wizard():
    print('Titan · Vollständige Sicherung und Wiederherstellung')
    print('Von einem separaten Rettungsmedium starten. Das NAS muss sauber heruntergefahren sein.')
    action = choose('Was möchtest du tun?', ['backup', 'restore', 'verify'],
                    lambda item: {'backup':'Vollständig sichern', 'restore':'Auf Ersatzplatten wiederherstellen', 'verify':'Sicherung vollständig prüfen'}[item])
    # No arbitrary mount commands or automatic formatting. Only existing ext4/XFS
    # backup volumes are offered; source/target exclusion is rechecked afterwards.
    data = strict_json(command(['lsblk','--json','--paths','--output','NAME,TYPE,FSTYPE,SIZE,MOUNTPOINTS']))
    def flatten(entries):
        for item in entries:
            yield item
            yield from flatten(item.get('children', []))
    choices = [item for item in flatten(data['blockdevices']) if item.get('fstype') in ('ext4','xfs')
               and not any(x is not None for x in item.get('mountpoints', []))]
    volume = choose('Sicherungslaufwerk (ext4/XFS, wird nicht formatiert)', choices,
                    lambda item: f"{item['name']} · {item['size']} · {item['fstype']}")
    mount = Path('/mnt/titan-recovery')
    mount.mkdir(parents=True, exist_ok=True)
    if os.path.ismount(mount) or any(mount.iterdir()): raise RecoveryError('Rettungsverzeichnis wird bereits verwendet.')
    read_options = 'ro,nosuid,nodev,noexec,' + ('noload' if volume['fstype'] == 'ext4' else 'norecovery')
    command(['mount','-o',read_options,volume['name'],str(mount)])
    def writable_backup_volume():
        command(['umount',str(mount)])
        command(['mount','-o','nosuid,nodev,noexec',volume['name'],str(mount)])
    try:
        if action == 'backup':
            import zipfile
            kit = choose('Aus Titan heruntergeladenen Rettungsplan auswählen', list(mount.glob('*.zip')), lambda p:p.name)
            with zipfile.ZipFile(kit) as archive:
                if archive.getinfo('inventory.json').file_size > 1024*1024: raise RecoveryError('Rettungsplan ist zu groß.')
                inventory = strict_json(archive.read('inventory.json'))
            if inventory.get('format') != FORMAT or inventory.get('architecture') != 'x86_64': raise RecoveryError('Ungültiger Rettungsplan.')
            validate_disks(inventory.get('disks'))
            target = disk_for_device(block_inventory(), mount.stat().st_dev)
            sources = {d['identity'] for d in inventory['disks']}
            if target['identity'] in sources: raise RecoveryError('Sicherungsziel ist eine Quellplatte.')
            extras = [d for d in block_inventory() if not d['mounted'] and d['identity'] not in sources]
            if extras: raise RecoveryError('Seit dem Rettungsplan sind weitere Laufwerke vorhanden. Plan auf Titan erneut exportieren.')
            print('Alle Laufwerke des Plans müssen vorhanden und unbenutzt sein. Laufzeit abhängig von der gesamten Plattengröße.')
            if input('Sicherung starten? JA eingeben: ') != 'JA': raise RecoveryError('Abgebrochen.')
            writable_backup_volume()
            output = mount / ('titan-full-' + time.strftime('%Y%m%d-%H%M%S'))
            with pin_disks(inventory['disks'], {d['id']:d['identity'] for d in inventory['disks']}) as descriptors:
                fingerprint = backup(output, inventory, descriptors)
            print('Sicherung geprüft und vollständig: ' + str(output) + '\n' + fingerprint)
        else:
            folder = choose('Sicherung auswählen', sorted(mount.glob('titan-full-*')), lambda p:p.name)
            packet = Packet(folder)
            print('Prüfe alle Archive. Noch werden keine Zielplatten verändert.', flush=True)
            print('Prüfsumme: ' + packet.verify())
            if action == 'verify': return
            available = [d for d in block_inventory() if not d['mounted'] and d['identity']
                         and d['identity'] not in {d['identity'] for d in packet.disks}]
            mapping = {}
            for disk in packet.disks:
                target = choose('Ersatz für ' + disk['id'] + ' (' + str(disk['size']//1024**3) + ' GiB)',
                    [d for d in available if d['identity'] not in mapping.values() and d['size'] >= disk['size'] and d['sector'] == disk['sector']],
                    lambda d:json.dumps({k:d[k] for k in ('path','model','identity','size')},ensure_ascii=True))
                mapping[disk['id']] = target['identity']
            backup_disk = disk_for_device(block_inventory(), mount.stat().st_dev)
            if backup_disk['identity'] in {d['identity'] for d in packet.disks}:
                raise RecoveryError('Sicherung liegt auf einer Originalplatte.')
            writable_backup_volume()
            work = mount / '.titan-restore'
            if not work.exists(): work.mkdir(mode=0o700)
            private_directory(work)
            journal = work / (packet.fingerprint + '.json')
            resume = journal.exists()
            print('Zielzuordnung: ' + json.dumps(mapping,ensure_ascii=True))
            print('Die gewählten Ziele werden vollständig beschrieben. Originalplatten bleiben unberührt.')
            if input('Zum Start WIEDERHERSTELLEN eingeben: ') != 'WIEDERHERSTELLEN': raise RecoveryError('Abgebrochen.')
            with pin_disks(packet.disks,mapping,writing=True,resumed=resume) as descriptors:
                restore(packet,descriptors,mapping,journal,resume=resume)
            print('Vollständig wiederhergestellt und zurückgelesen. Ausschalten, Rettungsmedium und Originalplatten entfernen; von der Ersatz-Systemplatte starten.')
    finally:
        command(['umount',str(mount)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('wizard', help='Geführte Sicherung und Wiederherstellung')
    sub.add_parser('disks', help='Laufwerkskennungen anzeigen')
    p = sub.add_parser('backup'); p.add_argument('--inventory', required=True); p.add_argument('--output', required=True)
    p = sub.add_parser('verify'); p.add_argument('packet')
    p = sub.add_parser('restore'); p.add_argument('packet'); p.add_argument('--map', required=True, help='JSON: disk-001 -> Ersatzplattenkennung')
    p.add_argument('--journal', required=True); p.add_argument('--confirm', required=True, help='Vollständiger SHA256-Fingerabdruck des geprüften Pakets')
    p.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'wizard': wizard(); return
        if args.action == 'disks': print(json.dumps(block_inventory(), indent=2)); return
        if args.action == 'backup':
            inventory = load_inventory(args.inventory)
            # The output parent must be on a different disk from every source.
            target = disk_for_device(block_inventory(), os.stat(Path(args.output).parent).st_dev)
            if target['identity'] in {disk['identity'] for disk in inventory['disks']}:
                raise RecoveryError('Sicherung liegt auf einer Quellplatte.')
            with pin_disks(inventory['disks'], {d['id']:d['identity'] for d in inventory['disks']}) as descriptors:
                print(backup(args.output, inventory, descriptors))
        elif args.action == 'verify': print(Packet(args.packet).verify())
        else:
            packet = Packet(args.packet)
            if args.confirm != packet.fingerprint: raise RecoveryError('Fingerabdruck wurde nicht bestätigt.')
            mapping = strict_json(Path(args.map).read_bytes())
            if not isinstance(mapping, dict) or set(mapping) != {d['id'] for d in packet.disks}:
                raise RecoveryError('Unvollständige Zielzuordnung.')
            protected = {disk_for_device(block_inventory(), os.stat(path).st_dev)['identity']
                         for path in (packet.directory, Path(args.journal).parent)}
            if protected & set(mapping.values()): raise RecoveryError('Sicherung und Journal dürfen nicht auf einer Zielplatte liegen.')
            with pin_disks(packet.disks, mapping, writing=True, resumed=args.resume) as descriptors:
                print(json.dumps(restore(packet, descriptors, mapping, args.journal, resume=args.resume)))
    except (RecoveryError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, 'Wiederherstellung/Sicherung abgebrochen: ' + str(error) + '\n')


if __name__ == '__main__': main()

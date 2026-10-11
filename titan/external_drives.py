"""USB storage: find file systems on USB disks, mount them below /var/media and release them.

Mounted drives are data-only (nosuid, nodev, noexec). Administrators browse
them in the file manager; the existing external-target checks make them
eligible backup destinations. Nothing here formats or repairs a drive.
"""
import json
import logging
import os
from pathlib import Path
import pwd
import re
from .core import Error

ROOT = Path('/var/media')
PREFIX = 'extern-'
NAME = re.compile(r'extern-[a-z0-9]+(?:-[a-z0-9]+)*\Z')
UUID = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{3,63}\Z')
NATIVE = ('ext4', 'xfs', 'btrfs')
# File systems without Unix owners, and the kernel driver that mounts them.
FOREIGN = {'vfat': 'vfat', 'exfat': 'exfat', 'ntfs': 'ntfs3'}
OPTIONS = 'nosuid,nodev,noexec,noatime'
LSBLK = ['lsblk', '--json', '--bytes', '--output', 'NAME,PATH,TYPE,TRAN,FSTYPE,LABEL,UUID,SIZE,MODEL,MOUNTPOINTS']


def slug(value, limit):
    return re.sub(r'[^a-z0-9]+', '-', str(value or '').lower()).strip('-')[:limit].strip('-')


def drive_name(label, model, uuid):
    """Stable, readable mount name; the UUID suffix keeps equal labels apart."""
    suffix = re.sub(r'[^a-z0-9]', '', str(uuid).lower())[:6] or 'usb'
    return PREFIX + (slug(label, 16) or slug(model, 16) or 'laufwerk') + '-' + suffix


def filesystems(blockdevices):
    """Mountable file systems on USB-attached disks, from ``lsblk --json --bytes``."""
    result = []
    for disk in blockdevices or []:
        if disk.get('type') != 'disk' or disk.get('tran') != 'usb':
            continue
        children = disk.get('children') or []
        for node in children or [disk]:
            fstype, uuid = node.get('fstype'), node.get('uuid')
            if node.get('type') not in ('disk', 'part') or (fstype not in NATIVE and fstype not in FOREIGN):
                continue
            if not isinstance(uuid, str) or not UUID.fullmatch(uuid) or not isinstance(node.get('path'), str):
                continue
            label = str(node.get('label') or disk.get('model') or 'USB-Laufwerk').strip()
            result.append({'name': drive_name(node.get('label'), disk.get('model'), uuid), 'device': node['path'],
                           'uuid': uuid, 'filesystem': fstype, 'label': label[:64], 'size': int(node.get('size') or 0),
                           'mountpoints': [value for value in node.get('mountpoints') or [] if value]})
    return result


class ExternalDrivesMixin:
    external_root = ROOT

    def _external_inventory(self):
        value = json.loads(self.command(LSBLK, timeout=20))
        return filesystems(value.get('blockdevices'))

    def _external_target(self, name):
        if not isinstance(name, str) or not NAME.fullmatch(name) or len(name) > 31:
            raise Error('Unbekanntes USB-Laufwerk.', 404)
        return self.external_root / name

    def _external_item(self, name):
        self._external_target(name)
        item = next((item for item in self._external_inventory() if item['name'] == name), None)
        if item is None:
            raise Error('USB-Laufwerk ist nicht angeschlossen.', 404)
        return item

    def op_external_drives(self):
        drives = []
        for item in self._external_inventory():
            target = str(self.external_root / item['name'])
            mounted = target in item['mountpoints']
            entry = {key: item[key] for key in ('name', 'label', 'device', 'filesystem', 'size')}
            entry.update(path=target, mounted=mounted, in_use_elsewhere=bool(item['mountpoints']) and not mounted)
            if mounted:
                try:
                    usage = os.statvfs(target)
                    entry.update(total_bytes=usage.f_blocks * usage.f_frsize, free_bytes=usage.f_bavail * usage.f_frsize)
                except OSError:
                    entry['mounted'] = False
            drives.append(entry)
        return {'drives': drives}

    def _external_mount(self, item):
        target = self._external_target(item['name'])
        self.external_root.mkdir(mode=0o755, parents=True, exist_ok=True)
        try:
            os.mkdir(target, 0o700)
        except FileExistsError:
            if os.path.ismount(target) or os.listdir(target):
                raise Error('Der Einhängepunkt für dieses Laufwerk ist belegt.', 409)
        options, kernel = OPTIONS, item['filesystem']
        if kernel in FOREIGN:
            owner = pwd.getpwnam('titan-files')
            options += f',uid={owner.pw_uid},gid={owner.pw_gid},umask=007'
            kernel = FOREIGN[kernel]
        try:
            self.command(['mount', '-t', kernel, '-o', options, '--source', 'UUID=' + item['uuid'], '--target', str(target)], timeout=60)
        except Exception:
            try:
                os.rmdir(target)
            except OSError:
                pass
            raise

    def op_external_drive_mount(self, name):
        item = self._external_item(name)
        if item['mountpoints']:
            raise Error('Das Laufwerk ist bereits eingehängt.', 409)
        self._external_mount(item)
        getattr(self, '_external_ejected', set()).discard(item['uuid'])
        return {'ok': True, 'message': 'Laufwerk eingehängt.'}

    def op_external_drive_eject(self, name):
        item = self._external_item(name)
        target = self._external_target(name)
        if str(target) not in item['mountpoints']:
            raise Error('Das Laufwerk ist nicht eingehängt.', 409)
        try:
            self.command(['umount', '--', str(target)], timeout=120)
        except Error as exc:
            raise Error('Das Laufwerk wird noch verwendet (zum Beispiel von einer Sicherung oder einem geöffneten Ordner). ' + str(exc), 409) from None
        try:
            os.rmdir(target)
        except OSError:
            pass
        # Do not mount it again while it stays plugged in.
        if not hasattr(self, '_external_ejected'):
            self._external_ejected = set()
        self._external_ejected.add(item['uuid'])
        return {'ok': True, 'message': 'Das Laufwerk kann jetzt abgezogen werden.'}

    def external_automount(self):
        """Mount newly attached USB file systems; an ejected drive waits until it is replugged."""
        ejected = getattr(self, '_external_ejected', None)
        if ejected is None:
            ejected = self._external_ejected = set()
        inventory = self._external_inventory()
        ejected &= {item['uuid'] for item in inventory}
        for item in inventory:
            if item['mountpoints'] or item['uuid'] in ejected:
                continue
            try:
                self._external_mount(item)
            except (Error, OSError) as exc:
                logging.warning('USB drive %s could not be mounted: %s', item['name'], type(exc).__name__)

    def external_automount_loop(self, stop, interval=10):
        while not stop.wait(interval):
            try:
                self.external_automount()
            except Exception as exc:
                logging.warning('USB drive scan failed: %s', type(exc).__name__)

    def external_record(self, name):
        """File-manager location for a mounted drive, or None. Administrators only: no readers or writers."""
        if not isinstance(name, str) or not NAME.fullmatch(name):
            return None
        target = str(self.external_root / name)
        for item in self._external_inventory():
            if item['name'] == name and target in item['mountpoints']:
                return {'name': name, 'path': target, 'readers': [], 'writers': [], 'external': True, 'label': item['label']}
        return None

    def open_external_root(self, path):
        path = Path(path)
        if path.parent != self.external_root or not NAME.fullmatch(path.name):
            raise Error('Ungültiger Laufwerkspfad.')
        parent = os.open(self.external_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            # An unplugged drive leaves the empty mount directory behind; never write into it.
            if os.fstat(fd).st_dev == os.fstat(parent).st_dev:
                os.close(fd)
                raise Error('Das USB-Laufwerk ist nicht mehr eingehängt.', 503)
            return fd
        finally:
            os.close(parent)

"""Private recovery packets: verified archives, sparse files, ACLs and xattrs.

This module never chooses disks, mounts filesystems, or starts restored services.
Callers must first stop writers and validate every source and destination device.
"""
import ctypes
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile

from .core import Error
from .backups import directory_fd

FORMAT = 'titan-recovery-v1'
FILES = re.compile(r'(persistent|volume-[a-z][a-z0-9_-]{0,31})\.tar\.gz\Z')
MAX_ENTRIES = 1_000_000
MAX_MANIFEST = 1024 * 1024


def regular(fd, *, private=False, maximum=None):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or (private and (info.st_uid != os.geteuid() or info.st_mode & 0o077)) or (maximum is not None and info.st_size > maximum):
        raise Error('Unsichere oder ungültige Wiederherstellungsdatei.')
    return info


def hash_descriptor(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    h = hashlib.sha256()
    while chunk := os.read(fd, 1024 * 1024): h.update(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return h.hexdigest()


def member_path(name):
    while name.startswith('./'): name = name[2:]
    name = name.rstrip('/')
    if name in ('', '.'): return ''
    if (not isinstance(name, str) or len(name) > 4096 or name.startswith('/') or '\\' in name
            or any(ord(c) < 32 for c in name) or any(p in ('', '.', '..') for p in name.split('/'))):
        raise Error('Die Sicherung enthält einen unsicheren Dateipfad.')
    return name


def inspect_tar(fd):
    """Scan the complete archive before root extraction; no following archived links."""
    os.lseek(fd, 0, os.SEEK_SET)
    names, links, allocated, logical = {}, [], 0, 0
    try:
        with os.fdopen(os.dup(fd), 'rb') as stream, tarfile.open(fileobj=stream, mode='r|gz') as archive:
            for item in archive:
                name = member_path(item.name)
                if len(names) >= MAX_ENTRIES or name in names:
                    raise Error('Die Sicherung enthält zu viele oder doppelte Dateipfade.')
                if not (item.isdir() or item.isfile() or item.issym() or item.islnk() or item.isfifo()
                        or item.ischr() and item.devmajor == item.devminor == 0):
                    raise Error('Die Sicherung enthält ein nicht unterstütztes Spezialgerät.')
                if not name and not item.isdir():
                    raise Error('Ungültige Archivwurzel.')
                if item.size < 0 or item.uid < 0 or item.gid < 0 or item.uid >= 2**32 or item.gid >= 2**32:
                    raise Error('Ungültige Dateigröße oder Besitzerkennung.')
                names[name] = 'directory' if item.isdir() else 'file' if item.isfile() else 'link' if item.issym() else 'hardlink' if item.islnk() else 'special'
                if item.islnk(): links.append((name, member_path(item.linkname)))
                if item.isfile():
                    logical += item.size
                    if item.sparse is not None:
                        end = 0
                        for offset, length in item.sparse:
                            if offset < end or length < 0 or offset + length > item.size:
                                raise Error('Ungültige Sparse-Dateibereiche.')
                            allocated += length; end = offset + length
                    else: allocated += item.size
            for name in names:
                parent = PurePosixPath(name).parent
                while str(parent) != '.':
                    if names.get(str(parent)) != 'directory':
                        raise Error('Ein Archivpfad führt durch einen Link oder ein fehlendes Verzeichnis.')
                    parent = parent.parent
            for name, target in links:
                if names.get(target) != 'file':
                    raise Error('Ein Archiv-Hardlink verweist nicht auf eine reguläre Datei.')
    except (tarfile.TarError, OSError, EOFError, ValueError) as exc:
        raise Error('Das Sicherungsarchiv ist beschädigt oder unvollständig.') from exc
    finally:
        os.lseek(fd, 0, os.SEEK_SET)
    return {'entries': len(names), 'allocated': allocated, 'logical': logical}


def checked_process(arguments, **kwargs):
    result = subprocess.run(arguments, stderr=subprocess.PIPE, **kwargs)
    if result.returncode:
        # Filenames may be sensitive. Do not publish tar stderr in the web journal.
        raise Error('Archivübertragung fehlgeschlagen. Die Sicherung wird nicht als vollständig markiert.', 503)


def pack_tree(source_fd, destination_fd, *, exclusions=()):
    """Call only while writers are stopped and this filesystem is frozen."""
    arguments = ['tar', '--create', '--gzip', '--sparse', '--format=pax', '--acls', '--xattrs', '--xattrs-include=*',
                 '--numeric-owner', '--atime-preserve=system', '--one-file-system', '--directory', f'/proc/self/fd/{source_fd}',
                 *['--exclude='+item for item in exclusions], '.']
    checked_process(arguments, stdout=destination_fd, pass_fds=(source_fd,))
    os.fsync(destination_fd)
    regular(destination_fd)
    return {'size': os.fstat(destination_fd).st_size, 'sha256': hash_descriptor(destination_fd)}


def unpack_tree(archive_fd, destination, *, inspected=None):
    """Extract only into a newly-created private, empty staging directory."""
    inspection = inspected or inspect_tar(archive_fd)
    destination = Path(destination)
    with directory_fd(destination) as target:
        info = os.fstat(target)
        if info.st_uid != os.geteuid() or info.st_mode & 0o077 or os.listdir(target):
            raise Error('Wiederherstellung benötigt ein neues privates und leeres Staging-Verzeichnis.')
        reserve = inspection['allocated'] + inspection['entries'] * 8192 + 64 * 1024**2
        space = os.fstatvfs(target)
        if space.f_bavail * space.f_frsize < reserve:
            raise Error('Auf dem Ziel ist nicht genügend freier Platz für die vollständige Wiederherstellung.', 409)
        os.lseek(archive_fd, 0, os.SEEK_SET)
        checked_process(['tar', '--extract', '--gzip', '--sparse', '--acls', '--xattrs', '--xattrs-include=*',
                         '--numeric-owner', '--same-owner', '--same-permissions', '--delay-directory-restore',
                         '--directory', f'/proc/self/fd/{target}'], stdin=archive_fd, stdout=subprocess.DEVNULL, pass_fds=(target,))
        os.fsync(target)


def exchange_directories(parent, first, second):
    """Atomic publication: a crash cannot expose an absent/half-restored persistent tree."""
    if any('/' in name or name in ('', '.', '..') for name in (first, second)):
        raise Error('Ungültige Wiederherstellungsverzeichnisse.')
    with directory_fd(parent) as fd:
        for name in (first, second):
            value = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISDIR(value.st_mode) or value.st_uid != os.geteuid():
                raise Error('Wiederherstellungsziel wurde ersetzt.')
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, 'renameat2', None)
        if rename is None: raise Error('Atomarer Verzeichniswechsel wird auf diesem System nicht unterstützt.')
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(fd, os.fsencode(first), fd, os.fsencode(second), 2):
            raise Error('Atomarer Wiederherstellungswechsel fehlgeschlagen: '+os.strerror(ctypes.get_errno()), 503)
        os.fsync(fd)


class Packet:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.context = None
        self.fd = None

    def __enter__(self):
        self.context = directory_fd(self.directory)
        self.fd = self.context.__enter__()
        try:
            value = os.fstat(self.fd)
            if value.st_uid != os.geteuid() or value.st_mode & 0o077:
                raise Error('Die vollständige Sicherung muss privat und gegen fremde Änderungen geschützt sein.')
            descriptor = os.open('manifest.json', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.fd)
            with os.fdopen(descriptor) as stream:
                regular(stream.fileno(), private=True, maximum=MAX_MANIFEST)
                raw = stream.read()
                from .updates import strict_json
                self.manifest = strict_json(raw)
            self.fingerprint = hashlib.sha256(raw.encode()).hexdigest()
            m = self.manifest
            if (not isinstance(m, dict) or m.get('format') != FORMAT or m.get('complete') is not True or not isinstance(m.get('archives'), list)
                    or not 1 <= len(m['archives']) <= 129 or not isinstance(m.get('system'), dict)):
                raise Error('Dies ist keine vollständige Titan-Systemsicherung.')
            names = set()
            for item in m['archives']:
                if (not isinstance(item, dict) or not FILES.fullmatch(str(item.get('file', '')))
                        or item['file'] in names or type(item.get('size')) is not int or not 0 < item['size'] <= 100*1024**4
                        or not re.fullmatch(r'[a-f0-9]{64}', str(item.get('sha256', '')))):
                    raise Error('Ungültiges Sicherungsverzeichnis.')
                names.add(item['file'])
            if 'persistent.tar.gz' not in names:
                raise Error('Die Sicherung enthält keinen vollständigen Titan-Zustand.')
            if set(os.listdir(self.fd)) != names | {'manifest.json'}:
                raise Error('Die Sicherung enthält unvollständige oder unbekannte Dateien.')
            return self
        except Exception:
            self.context.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        return self.context.__exit__(*args)

    def open_archive(self, item):
        descriptor = os.open(item['file'], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.fd)
        try:
            info = regular(descriptor, private=True)
            if info.st_dev != os.fstat(self.fd).st_dev or info.st_size != item['size'] or hash_descriptor(descriptor) != item['sha256']:
                raise Error('Die Sicherung ist beschädigt oder wurde verändert. Keine Wiederherstellung.', 409)
            return descriptor
        except Exception:
            os.close(descriptor); raise

    def verify(self):
        results = {}
        for item in self.manifest['archives']:
            fd = self.open_archive(item)
            try: results[item['file']] = inspect_tar(fd)
            finally: os.close(fd)
        return results

#!/usr/bin/env python3
"""Fixed boot-time filesystem checks; never create/import/modify a pool."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ARC_MAX = 1024 ** 3
ARC_MIN = 128 * 1024 ** 2
PROOF = Path('/run/titan-storage-components.json')
TOOLS = ('mkfs.ext4', 'e2fsck', 'resize2fs', 'mkfs.xfs', 'xfs_repair', 'xfs_growfs', 'zpool', 'zfs', 'modprobe', 'modinfo')
SAFE_PATH = '/usr/sbin:/usr/bin:/sbin:/bin'


def command(args):
    executable = shutil.which(args[0], path=SAFE_PATH)
    if not executable:
        raise RuntimeError('A required filesystem component is missing')
    result = subprocess.run([executable, *args[1:]], check=True, capture_output=True,
                            text=True, timeout=30, env={'PATH': SAFE_PATH, 'LC_ALL': 'C'})
    if len(result.stdout) > 1024 * 1024:
        raise RuntimeError('Filesystem query returned an oversized response')
    return result.stdout.strip()


def check():
    if os.geteuid() != 0:
        raise RuntimeError('Filesystem module preparation requires the boot service')
    for name in TOOLS:
        if not shutil.which(name, path=SAFE_PATH):
            raise RuntimeError('A required filesystem component is missing')
    command(['modprobe', 'zfs'])
    kernel = os.uname().release
    if not re.fullmatch(r'[a-zA-Z0-9.+_-]{1,128}', kernel):
        raise RuntimeError('Invalid running kernel identity')
    if not Path('/sys/module/zfs').is_dir() or not command(['modinfo', '-F', 'vermagic', 'zfs']).startswith(kernel + ' '):
        raise RuntimeError('ZFS module does not match the running kernel')
    command(['zpool', 'list', '-H', '-o', 'name'])
    command(['zfs', 'list', '-H', '-o', 'name'])
    maximum = int(Path('/sys/module/zfs/parameters/zfs_arc_max').read_text())
    minimum = int(Path('/sys/module/zfs/parameters/zfs_arc_min').read_text())
    if maximum != ARC_MAX or minimum != ARC_MIN:
        raise RuntimeError('The active ZFS memory limits differ from the factory configuration')
    fields = [line.split() for line in Path('/proc/spl/kstat/zfs/arcstats').read_text().splitlines()]
    size = next(int(row[2]) for row in fields if len(row) == 3 and row[0] == 'size')
    if not 0 <= size < 2 ** 64:
        raise RuntimeError('The active ZFS cache size is invalid')
    boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if not re.fullmatch(r'[a-f0-9-]{36}', boot_id):
        raise RuntimeError('Invalid boot identity')
    return {'format': 'titan-storage-components-v1', 'boot_id': boot_id, 'kernel': kernel,
            'ext4_tools': True, 'xfs_tools': True, 'zfs_module_loaded': True,
            'zfs_module_matches_kernel': True, 'zpool_query': True, 'zfs_query': True,
            'zfs_arc_max_bytes': maximum, 'zfs_arc_min_bytes': minimum,
            'zfs_arc_size_bytes': size}


def publish(value, target=PROOF):
    target = Path(target)
    parent = target.parent.stat()
    if target.parent.is_symlink() or parent.st_uid != 0 or parent.st_mode & 0o022:
        raise RuntimeError('Filesystem proof directory is not trusted')
    descriptor, path = tempfile.mkstemp(prefix='.titan-storage-', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            os.fchmod(stream.fileno(), 0o644)
            json.dump(value, stream, separators=(',', ':'), allow_nan=False)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(path, target)
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(path): os.unlink(path)


if __name__ == '__main__':
    publish(check())

#!/usr/bin/env python3
"""Build an experimental Debian 13 package without installing on the build host."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = Path(os.environ.get('TITAN_APP_SOURCE_ROOT', ROOT)).resolve(strict=True)
sys.path.insert(0, str(APP_ROOT))
from titan import __version__

DEPENDENCIES = ('python3 (>= 3.13)', 'systemd', 'systemd-sysv', 'caddy', 'openssl',
    'acl', 'util-linux', 'smartmontools', 'tar', 'curl', 'ca-certificates', 'kmod',
    'iproute2', 'e2fsprogs', 'xfsprogs', 'zfsutils-linux', 'zfs-dkms', 'cloud-guest-utils', 'gdisk', 'samba',
    'samba-common-bin', 'docker.io', 'docker-cli', 'docker-compose (>= 2)', 'qemu-system-x86',
    'qemu-utils', 'ovmf', 'python3-yaml', 'libvirt-daemon-system', 'libvirt-daemon-driver-qemu',
    'libvirt-daemon', 'libvirt-daemon-lock', 'libvirt-daemon-log', 'libvirt-daemon-config-network', 'libvirt-clients', 'novnc', 'websockify', 'firewalld', 'apparmor')


def stage(destination):
    def copy(source, target, executable=False):
        original = APP_ROOT / source
        if original.is_symlink() or not original.is_file():
            raise ValueError('Application payload must contain regular source files.')
        path = destination / target
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, path)
        path.chmod(0o755 if executable else 0o644)
    # Explicit source roots; no workspace state, credentials or build artifacts.
    for source in sorted((APP_ROOT / 'titan').rglob('*')):
        if source.is_symlink():
            raise ValueError('Symlinks are not accepted in the application payload.')
        if source.is_file() and '__pycache__' not in source.parts and source.suffix not in ('.pyc', '.pyo'):
            copy(source.relative_to(APP_ROOT), 'usr/lib/titan/' + str(source.relative_to(APP_ROOT)))
    for source, target in (
        ('image/firstboot.py', 'usr/share/titan/firstboot.py'),
        ('image/titan.sysusers', 'usr/lib/sysusers.d/titan.conf'),
        ('image/titan.tmpfiles', 'usr/lib/tmpfiles.d/titan.conf'),
        ('image/titan-firewall.xml', 'usr/lib/firewalld/services/titan.xml'),
        ('packaging/release-public.pem', 'usr/share/titan/release-public.pem'),
        ('LICENSE', 'usr/share/doc/titan-debian-preview/LICENSE'),
        ('NOTICE', 'usr/share/doc/titan-debian-preview/NOTICE'),
        ('docs/DEBIAN-MIGRATION.md', 'usr/share/doc/titan-debian-preview/MIGRATION.md')):
        copy(source, target)
    # Older frozen application commits predate these release documents.
    for source, name in (('docs/LICENSING.md', 'LICENSING.md'), ('docs/DEBIAN-SOURCES.md', 'SOURCES.md')):
        if (APP_ROOT/source).exists() or (APP_ROOT/source).is_symlink():
            copy(source, 'usr/share/doc/titan-debian-preview/' + name)
    for source, name in (('scripts/component-functions.sh','component-functions.sh'),
                         ('packaging/debian/runtime.sh','install-components.sh'),
                         ('scripts/diagnose.sh','diagnose.sh')):
        copy(source, 'usr/share/titan/' + name, True)
    for name in ('titan-agent', 'titan-web', 'titan-proxy', 'titan-firstboot', 'titan-runtime', 'titan-service-containment'):
        source = ('packaging' if name in ('titan-agent','titan-web','titan-proxy') else 'image') + '/' + name + '.service'
        if (APP_ROOT/source).is_symlink():
            raise ValueError('Application services must be regular source files.')
        text = (APP_ROOT/source).read_text()
        text = '\n'.join(line for line in text.splitlines() if not line.startswith('SELinuxContext=')) + '\n'
        text = text.replace('smb.service', 'smbd.service')
        target=destination/'usr/lib/systemd/system'/f'{name}.service'
        target.parent.mkdir(parents=True, exist_ok=True); target.write_text(text)
    info={'format':'titan-debian-preview-v1','platform':'debian-preview','version':__version__,
          'release_stage':'alpha','architecture':'x86_64','distribution':'debian','suite':'trixie',
          'update_backend':'disabled','bootable_image':False}
    (destination/'usr/share/titan/image-info.json').write_text(json.dumps(info,indent=2)+'\n')
    control=destination/'DEBIAN';control.mkdir()
    (control/'control').write_text(f'''Package: titan-debian-preview
Version: {__version__}+debian1
Architecture: amd64
Maintainer: Titan maintainers <maintainers@titan.invalid>
Depends: {', '.join(DEPENDENCIES)}
Conflicts: titan
Section: admin
Priority: optional
Description: Experimental Titan Debian integration, without system updates
 Dedicated Debian 13 test VMs only. A/B updates and rollback are not available.
 Installation does not enable or start NAS services automatically.
''')
    (control/'preinst').write_text('''#!/bin/sh
set -eu
. /etc/os-release
[ "$ID" = debian ] && [ "$VERSION_ID" = 13 ] || { echo 'Debian 13 required; Ubuntu is not supported yet.' >&2; exit 1; }
''')
    (control/'preinst').chmod(0o755)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'dist/debian')
    args=parser.parse_args();args.output.mkdir(parents=True, exist_ok=True)
    target=args.output.resolve()/f'titan-debian-preview_{__version__}+debian1_amd64.deb'
    with tempfile.TemporaryDirectory(prefix='titan-deb-') as work:
        directory=Path(work)/'package';directory.mkdir();stage(directory)
        subprocess.run(['dpkg-deb','--root-owner-group','--build',str(directory),str(target)],check=True)
    print(target)

if __name__=='__main__':
    main()

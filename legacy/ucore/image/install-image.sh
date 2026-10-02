#!/bin/bash
set -euo pipefail
export LC_ALL=C.UTF-8
# This runs ONLY in the container image build, never on the NAS/workstation.
[[ ${TITAN_IMAGE_BUILD:-0} == 1 ]] || { echo 'Image build container required.' >&2; exit 1; }
command -v chcon >/dev/null || { echo 'SELinux chcon binary required in the Titan image.' >&2; exit 1; }
install -d -m 0755 /usr/share/titan /usr/lib/systemd/system /usr/lib/sysusers.d /usr/lib/tmpfiles.d \
    /etc/titan /etc/pki/containers /etc/containers/registries.d /etc/firewalld/services
install -m 0644 /tmp/titan-image/image-info.json /usr/share/titan/image-info.json
# JSON is valid YAML. Keep the CoreOS boot layout with mkfs defaults understood
# by our pinned disk builder, rather than inheriting newer agcount schema fields.
install -d -m 0755 /usr/lib/image-builder/bootc
rm -f /usr/lib/image-builder/bootc/disk.yaml
install -m 0644 /tmp/titan-image/bootc-disk.json /usr/lib/image-builder/bootc/disk.yaml
checkmodule -M -m -o /tmp/titan_shares.mod /tmp/titan-image/titan-shares.te
semodule_package -o /usr/share/titan/titan-shares.pp -m /tmp/titan_shares.mod
rm /tmp/titan_shares.mod
checkmodule -M -m -o /tmp/titan_proxy.mod /tmp/titan-image/titan-proxy.te
semodule_package -o /usr/share/titan/titan-proxy.pp -m /tmp/titan_proxy.mod
rm /tmp/titan_proxy.mod
install -m 0644 /tmp/titan-image/firstboot.py /usr/share/titan/firstboot.py
install -D -m 0644 /tmp/titan-image/00-00-titan.preset /usr/lib/systemd/system-preset/00-00-titan.preset
install -m 0644 /tmp/titan-image/titan-runtime.service /usr/lib/systemd/system/titan-runtime.service
install -m 0644 /tmp/titan-image/titan-firstboot.service /usr/lib/systemd/system/titan-firstboot.service
install -m 0644 /tmp/titan-image/titan-system-grow.service /usr/lib/systemd/system/titan-system-grow.service
install -m 0644 /tmp/titan-image/titan-boot-status.service /usr/lib/systemd/system/titan-boot-status.service
install -m 0644 /tmp/titan-image/titan-boot-status.timer /usr/lib/systemd/system/titan-boot-status.timer
install -m 0644 /tmp/titan-image/boot-status.sh /usr/share/titan/boot-status.sh
install -m 0644 /tmp/titan-image/titan.sysusers /usr/lib/sysusers.d/titan.conf
install -m 0644 /tmp/titan-image/titan.tmpfiles /usr/lib/tmpfiles.d/titan.conf
install -m 0644 /tmp/titan-image/titan-firewall.xml /etc/firewalld/services/titan.xml
install -m 0644 /tmp/titan-image/registries.yaml /etc/containers/registries.d/titan.yaml
install -m 0644 /tmp/titan-packaging/release-public.pem /etc/pki/containers/titan.pub
install -m 0644 /tmp/titan-packaging/release-public.pem /usr/share/titan/release-public.pem
for task_service in titan-agent titan-web titan-proxy; do
    install -m 0644 "/tmp/titan-packaging/$task_service.service" "/usr/lib/systemd/system/$task_service.service"
done
python3 - <<'PY'
import json
from pathlib import Path
path = Path('/etc/containers/policy.json')
policy = json.loads(path.read_text())
policy['default'] = [{'type': 'reject'}]
policy.setdefault('transports', {}).setdefault('docker', {})['ghcr.io/ra5on/titan'] = [{
    'type': 'sigstoreSigned', 'keyPath': '/etc/pki/containers/titan.pub',
    'signedIdentity': {'type': 'matchRepository'}}]
path.write_text(json.dumps(policy, indent=2) + '\n')
PY
python3 - <<'PYDOCKER'
import json, shlex, subprocess
from pathlib import Path
# Fedora supplies SELinux support in its vendor command line. Docker rejects
# options repeated in daemon.json, even when both values are identical.
unit = Path('/usr/lib/systemd/system/docker.service').read_text()
logical = unit.replace('\\\n', ' ').splitlines()
section, starts = '', []
for line in logical:
    line = line.strip()
    if line.startswith('[') and line.endswith(']'):
        section = line
    elif section == '[Service]' and line.startswith('ExecStart='):
        value = line.partition('=')[2].strip()
        starts = starts + [value] if value else []
if len(starts) != 1:
    raise SystemExit('Expected one Fedora Docker vendor ExecStart command.')
arguments = shlex.split(starts[0])
expected = ['/usr/bin/dockerd', '-H', 'fd://',
            '--containerd=/run/containerd/containerd.sock', '--selinux-enabled',
            '--userland-proxy-path', '/usr/bin/docker-proxy',
            '--init-path', '/usr/bin/tini-static']
if arguments != expected:
    raise SystemExit('Docker vendor flags changed; review SELinux and socket activation before building the image.')
path=Path('/etc/docker/daemon.json')
if path.exists():
    config = json.loads(path.read_text())
    if not isinstance(config, dict):
        raise SystemExit('Docker daemon configuration must be a JSON object.')
    if 'selinux-enabled' in config:
        del config['selinux-enabled']
        path.write_text(json.dumps(config, indent=2) + '\n')
# --validate checks the effective vendor flags plus /etc/docker/daemon.json
# without starting a daemon, creating containers or changing the build host.
try:
    subprocess.run([arguments[0], '--validate', *arguments[1:]], check=True,
                   capture_output=True, text=True, timeout=30,
                   env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C.UTF-8'})
except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
    raise SystemExit('Docker configuration validation failed with the pinned Fedora vendor flags.') from None
print('Docker configuration validated: vendor SELinux, fd:// socket, containerd, proxy and init flags; daemon not started.')
PYDOCKER
# Only Titan can stage tested, signed whole-system updates; never reboot automatically.
systemctl mask zincati.service bootc-fetch-apply-updates.timer rpm-ostreed-automatic.timer
systemctl enable titan-system-grow.service titan-runtime.service titan-firstboot.service titan-agent.service titan-web.service titan-proxy.service \
    titan-boot-status.timer \
    docker.service firewalld.service smb.service \
    virtqemud.socket virtnetworkd.socket virtstoraged.socket virtlogd.socket virtlockd.socket \
    virtnodedevd.socket virtnwfilterd.socket virtsecretd.socket
mkdir -p /usr/lib/systemd/system/smb.service.d /usr/lib/systemd/system/docker.service.d
for task_service in smb docker; do
    printf '[Unit]\nRequires=titan-firstboot.service\nAfter=titan-firstboot.service\n' > "/usr/lib/systemd/system/$task_service.service.d/titan.conf"
    if [[ "$task_service" == docker ]]; then
        printf '\n[Service]\nStandardOutput=journal+console\nStandardError=journal+console\n' >> "/usr/lib/systemd/system/$task_service.service.d/titan.conf"
    fi
done
# Deliberately no SSH password/key in a publicly distributed image.
systemctl disable sshd.service sshd.socket 2>/dev/null || true
for task_program in python3 caddy openssl docker virsh qemu-img qemu-system-x86_64 websockify \
    mkfs.ext4 mkfs.xfs zpool zfs semanage restorecon growpart sfdisk xfs_info xfs_growfs lsblk findmnt partx; do
    command -v "$task_program" >/dev/null || { echo "Missing image component: $task_program" >&2; exit 1; }
done
test -f /usr/share/novnc/core/rfb.js
docker compose version
python3 - <<'PY'
import sys,json
sys.path.insert(0,'/usr/lib/titan')
import titan
info=json.load(open('/usr/share/titan/image-info.json'))
assert (titan.__version__,titan.__release_stage__) == (info['version'],info['release_stage'])
PY
find /usr/lib/titan -type d -name __pycache__ -prune -exec rm -rf '{}' +
find /usr/lib/titan -type d -exec chmod 0755 '{}' +
find /usr/lib/titan -type f -exec chmod 0644 '{}' +
# bootc persists /var at first boot; image builds must not embed instance state.
rm -rf /var/*

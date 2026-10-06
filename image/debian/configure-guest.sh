#!/bin/bash
# Executed only inside the libguestfs appliance's Debian guest filesystem.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export LC_ALL=C.UTF-8
. /etc/os-release
[[ "$ID" == debian && "$VERSION_ID" == 13 ]] || exit 1
[[ -f /tmp/titan-preview.deb ]] || exit 1
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
chmod 0755 /usr/sbin/policy-rc.d
# The offline guest has no running resolved service. Use the libguestfs
# SLIRP DNS proxy while provisioning; first boot switches to DHCP/resolved.
ip -brief address
ip -4 route
# Some runner kernels expose extra virtual interfaces that prevent the
# appliance init script from configuring eth0. This is the temporary
# libguestfs network namespace, not the installed NAS network configuration.
if ! ip -4 route show default | grep -q .; then
    ip link set eth0 up
    ip address replace 169.254.2.15/16 dev eth0
    ip route replace default via 169.254.2.2 dev eth0
fi
rm -f /etc/resolv.conf
printf 'nameserver 169.254.2.3\n' > /etc/resolv.conf
getent ahostsv4 deb.debian.org
# Sources are explicit and remain inside Debian 13. This is a new disposable
# filesystem, never an existing NAS or the GitHub runner's package database.
rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources
cat > /etc/apt/sources.list.d/titan-debian.sources <<'SOURCES'
Types: deb
URIs: https://deb.debian.org/debian
Suites: trixie trixie-updates
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: https://security.debian.org/debian-security
Suites: trixie-security
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
SOURCES
apt-get -o APT::Update::Error-Mode=any -o Acquire::Retries=3 update
python3 /tmp/titan-package-state.py inventory --output /tmp/titan-before-packages.json
apt-get --no-remove -y dist-upgrade
# Headers must match the actual installed boot kernel, never the appliance's
# uname. Limit automatic DKMS work and keep its temporary private key out of the
# distributable filesystem. Packages remain in the official trixie repositories.
mkdir -p /etc/dkms/framework.conf.d
cat > /etc/dkms/framework.conf.d/titan-build.conf <<'DKMS'
parallel_jobs=2
mok_signing_key="/tmp/titan-zfs-build.key"
mok_certificate="/tmp/titan-zfs-build.pub"
DKMS
task_zfs_kernel=$(find /boot -maxdepth 1 -type f -name 'vmlinuz-*' -printf '%f\n' | sort -V | tail -n 1)
[[ "$task_zfs_kernel" =~ ^vmlinuz-[a-zA-Z0-9.+_-]+$ ]] || exit 1
task_zfs_kernel=${task_zfs_kernel#vmlinuz-}
case "$task_zfs_kernel" in
    *-cloud-amd64) task_zfs_headers=linux-headers-cloud-amd64 ;;
    *-amd64) task_zfs_headers=linux-headers-amd64 ;;
    *) echo 'Unsupported Debian boot kernel for ZFS.' >&2; exit 1 ;;
esac
apt-get install -y --no-install-recommends "$task_zfs_headers" "linux-headers-$task_zfs_kernel"
apt-get install -y --no-install-recommends /tmp/titan-preview.deb systemd systemd-resolved qemu-guest-agent python3-apt zfsutils-linux zfs-dkms
# Explicitly compile/install for the shipped kernel even if the package's
# automatic hook skipped the build because libguestfs runs a different kernel.
dkms autoinstall -k "$task_zfs_kernel" -j 2
depmod -a "$task_zfs_kernel"
[[ "$(modinfo -k "$task_zfs_kernel" -F vermagic zfs)" == "$task_zfs_kernel "* ]]
task_zfs_module=$(modinfo -k "$task_zfs_kernel" -F filename zfs)
[[ -f "$task_zfs_module" && ! -L "$task_zfs_module" ]]
dkms status -m zfs -k "$task_zfs_kernel" | grep -F ", $task_zfs_kernel, x86_64: installed"
rm -f /tmp/titan-zfs-build.key /tmp/titan-zfs-build.pub /etc/dkms/framework.conf.d/titan-build.conf
# Reserve RAM for services, containers and VMs on an 8 GiB NAS. Actual ARC use
# remains part of the ordinary system RAM measurement; no metric is subtracted.
mkdir -p /etc/modprobe.d
printf 'options zfs zfs_arc_max=1073741824 zfs_arc_min=134217728\n' > /etc/modprobe.d/titan-zfs.conf
update-initramfs -u -k "$task_zfs_kernel"
install -D -m 0755 /tmp/titan-zfs-components.py /usr/libexec/titan-zfs-components.py
rm /tmp/titan-zfs-components.py
cat > /usr/lib/systemd/system/titan-storage-components.service <<'ZFSUNIT'
[Unit]
Description=Load and verify Titan filesystem components
DefaultDependencies=no
After=systemd-modules-load.service systemd-remount-fs.service
Before=zfs-import-cache.service zfs-import-scan.service zfs-import.target zfs-mount.service local-fs.target sysinit.target titan-agent.service
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /usr/libexec/titan-zfs-components.py
RemainAfterExit=yes
TimeoutStartSec=120
[Install]
WantedBy=sysinit.target
ZFSUNIT
systemctl enable titan-storage-components.service
# Resolve service identities in the factory image so all A/B releases can
# compare an explicit UID/GID contract before touching an inactive slot.
systemd-sysusers /usr/lib/sysusers.d/titan.conf
# The NAS works without an external cloud-init seed or baked login credentials.
mkdir -p /etc/cloud /etc/systemd/network
touch /etc/cloud/cloud-init.disabled
cat > /etc/systemd/network/20-titan.network <<'NET'
[Match]
Name=en* eth*
[Network]
DHCP=yes
[DHCPv4]
UseMTU=true
NET
systemctl disable networking.service cloud-init-local.service cloud-init.service cloud-config.service cloud-final.service 2>/dev/null || true
systemctl enable systemd-networkd.service systemd-networkd-wait-online.service systemd-resolved.service qemu-guest-agent.service
ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
# Disable the vendor web server; Titan has its own unprivileged Caddy instance.
systemctl disable caddy.service ssh.service ssh.socket 2>/dev/null || true
systemctl mask caddy.service ssh.service ssh.socket
systemctl disable apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
passwd -l root
# The base is the generic image (locked users), never the passwordless nocloud image.
python3 - <<'PY'
import json
from pathlib import Path
path=Path('/usr/share/titan/image-info.json');v=json.loads(path.read_text())
v.update(bootable_image=True,preview_id='debian-preview-20261002',rollback_available=False)
path.write_text(json.dumps(v,indent=2)+'\n')
ui=Path('/usr/lib/titan/titan/web/index.html')
ui.write_text(ui.read_text().replace('>ALPHA</span>','>DEBIAN · PREVIEW</span>').replace('Titan wird aktiv entwickelt. Nutze Testdaten und halte unabhängige Sicherungen bereit.','Debian-Testimage: Systemupdates und A/B-Rollback noch nicht verfügbar. Nur Testdaten verwenden.'))
PY
install -m 0755 /tmp/titan-grow-root.sh /usr/share/titan/debian-grow-root.sh
cat > /usr/lib/systemd/system/titan-debian-grow.service <<'UNIT'
[Unit]
Description=Grow the Debian preview root filesystem to available disk capacity
After=local-fs.target
Before=titan-firstboot.service
[Service]
Type=oneshot
ExecStart=/bin/bash /usr/share/titan/debian-grow-root.sh
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
for task_service in smbd docker; do
    mkdir -p "/etc/systemd/system/$task_service.service.d"
    printf '[Unit]\nRequires=titan-firstboot.service\nAfter=titan-firstboot.service\n' > "/etc/systemd/system/$task_service.service.d/titan.conf"
done
systemctl enable firewalld.service smbd.service docker.service libvirtd.socket virtlogd.socket virtlockd.socket \
    titan-debian-grow.service titan-service-containment.service titan-firstboot.service titan-runtime.service titan-agent.service titan-web.service titan-proxy.service
# Visible diagnostics and IP address in Proxmox's console, without a shared password.
cat > /usr/lib/systemd/system/titan-preview-console.service <<'UNIT'
[Unit]
Description=Print Debian preview status and address
After=network-online.target
[Service]
Type=oneshot
ExecStart=/bin/bash /usr/share/titan/preview-console.sh
StandardOutput=journal+console
[Install]
WantedBy=multi-user.target
UNIT
cat > /usr/share/titan/preview-console.sh <<'CONSOLE'
#!/bin/bash
printf '\nTitan Debian PREVIEW - no system updates or A/B rollback yet\n'
printf 'Open https://<NAS-IP>:5000 and create your administrator account.\n'
ip -brief -4 addr show scope global
systemctl --no-pager --full status titan-firstboot titan-runtime titan-agent titan-web titan-proxy || true
CONSOLE
systemctl enable titan-preview-console.service
# Clear all machine-specific state before distribution. No firstboot has run.
rm -f /tmp/titan-preview.deb /tmp/titan-grow-root.sh /usr/sbin/policy-rc.d /etc/ssh/ssh_host_* /var/lib/dbus/machine-id
truncate -s 0 /etc/machine-id
rm -f /var/lib/systemd/random-seed
rm -rf /var/lib/cloud/* /var/lib/apt/lists/*
apt-get clean
find /var/log -type f -exec truncate -s 0 '{}' +
dpkg-query -W > /usr/share/titan/debian-packages.txt
docker compose version
virsh --version
test -f /usr/share/novnc/core/rfb.js

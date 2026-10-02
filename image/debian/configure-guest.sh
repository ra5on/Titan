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
apt-get -o APT::Update::Error-Mode=any -o Acquire::Retries=3 update
apt-get install -y --no-install-recommends /tmp/titan-preview.deb systemd systemd-resolved qemu-guest-agent
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
    titan-debian-grow.service titan-firstboot.service titan-runtime.service titan-agent.service titan-web.service titan-proxy.service
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

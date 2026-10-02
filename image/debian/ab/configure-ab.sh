#!/bin/bash
# Runs only inside the disposable libguestfs guest after base provisioning.
set -euo pipefail
trap 'echo "Titan A/B guest provisioning failed at line $LINENO" >&2' ERR
export DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8
[[ -d /tmp/titan-ab && -f /tmp/titan-ab/image-info.json.sig ]] || exit 1
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
chmod 0755 /usr/sbin/policy-rc.d
if ! ip -4 route show default | grep -q .; then
    ip link set eth0 up
    ip address replace 169.254.2.15/16 dev eth0
    ip route replace default via 169.254.2.2 dev eth0
fi
rm -f /etc/resolv.conf
printf 'nameserver 169.254.2.3\n' > /etc/resolv.conf
apt-get -o APT::Update::Error-Mode=any -o Acquire::Retries=3 update
apt-get install -y --no-install-recommends rauc grub-efi-amd64-bin grub2-common initramfs-tools
install -d /etc/rauc /boot/titan /boot/efi /var/lib/titan-system
install -m 0644 /tmp/titan-ab/system.conf /etc/rauc/system.conf
install -m 0644 /tmp/titan-ab/rauc-root.pem /usr/share/titan/rauc-root.pem
install -m 0644 /tmp/titan-ab/image-info.json /usr/share/titan/image-info.json
install -m 0644 /tmp/titan-ab/image-info.json.sig /usr/share/titan/image-info.json.sig
openssl pkeyutl -verify -rawin -pubin -inkey /usr/share/titan/release-public.pem -in /usr/share/titan/image-info.json -sigfile /usr/share/titan/image-info.json.sig
install -m 0644 /tmp/titan-ab/fstab /etc/fstab
install -m 0755 /tmp/titan-ab/persist-initramfs.sh /etc/initramfs-tools/scripts/init-bottom/titan-persist
install -m 0755 /tmp/titan-ab/persist-hook.sh /etc/initramfs-tools/hooks/titan-persist
install -m 0755 /tmp/titan-ab/grow-data.sh /usr/share/titan/debian-grow-data.sh
install -m 0644 /tmp/titan-ab/titan-system-health.service /usr/lib/systemd/system/titan-system-health.service
systemctl disable titan-debian-grow.service
cat > /usr/lib/systemd/system/titan-data-grow.service <<'UNIT'
[Unit]
Description=Grow Titan persistent data to the installed disk capacity
After=local-fs.target
Before=titan-firstboot.service
[Service]
Type=oneshot
ExecStart=/bin/bash /usr/share/titan/debian-grow-data.sh
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
systemctl enable titan-data-grow.service titan-system-health.service
systemctl mask apt-daily.service apt-daily-upgrade.service apt-daily.timer apt-daily-upgrade.timer
# Normal application updates happen only through complete signed system bundles.
# /etc persists across slots; automatic apt writes would bypass that contract.
ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
python3 - <<'PY'
from pathlib import Path
p=Path('/usr/lib/titan/titan/web/index.html')
s=p.read_text().replace('>DEBIAN · PREVIEW</span>', '>ALPHA</span>').replace('Debian-Testimage: Systemupdates und A/B-Rollback noch nicht verfügbar. Nur Testdaten verwenden.', 'Titan wird aktiv entwickelt. Nutze Testdaten und halte unabhängige Sicherungen bereit.')
p.write_text(s)
p=Path('/usr/share/titan/preview-console.sh')
p.write_text(p.read_text().replace('Titan Debian PREVIEW - no system updates or A/B rollback yet', 'Titan Debian ALPHA - signed A/B system updates and rollback'))
PY
# Explicit root=LABEL in GRUB; do not embed the build appliance root UUID.
printf 'RESUME=none\n' > /etc/initramfs-tools/conf.d/resume
update-initramfs -u -k all
task_kernel=$(find /boot -maxdepth 1 -type f -name 'vmlinuz-*' -printf '%f\n' | sort -V | tail -n 1)
[[ "$task_kernel" =~ ^vmlinuz-[a-zA-Z0-9.+_-]+$ ]] || exit 1
test -f "/boot/initrd.img-${task_kernel#vmlinuz-}"
ln -sfn "boot/$task_kernel" /vmlinuz
ln -sfn "boot/initrd.img-${task_kernel#vmlinuz-}" /initrd.img
test -e /vmlinuz
test -e /initrd.img
printf 'search --no-floppy --label TITAN-BOOT --set=root\nconfigfile /grub.cfg\n' > /tmp/titan-grub-early.cfg
grub-mkstandalone -O x86_64-efi -o /tmp/titan-BOOTX64.EFI --modules='part_gpt fat ext2 normal linux search search_label loadenv test' 'boot/grub/grub.cfg=/tmp/titan-grub-early.cfg'
rm -f /tmp/titan-grub-early.cfg /usr/sbin/policy-rc.d /var/lib/systemd/random-seed /var/lib/dbus/machine-id /etc/ssh/ssh_host_*
truncate -s 0 /etc/machine-id
rm -rf /var/lib/apt/lists/* /tmp/titan-ab
apt-get clean
find /var/log -type f -exec truncate -s 0 '{}' +
dpkg-query -W > /usr/share/titan/debian-packages.txt

#!/bin/bash
# A separate offline rescue OS. No NAS state or signing secrets enter this image.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${1:-}" == --disposable-runner ]] || exit 1
: "${TITAN_SYSTEM_VERSION:?}" "${RUNNER_TEMP:?}"
task_work="$RUNNER_TEMP/titan-rescue-build"
mkdir -p "$task_work" dist/debian-image
cp titan/disaster_recovery.py "$task_work/titan-recovery.py"
docker run --rm -i --privileged -v "$task_work:/work" -e TITAN_SYSTEM_VERSION debian:13-slim bash -s <<'BUILD'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends live-build ca-certificates
mkdir /work/live
cd /work/live
lb config --mode debian --distribution trixie --architectures amd64 \
  --binary-images iso-hybrid --bootloaders grub-efi --debian-installer none \
  --archive-areas 'main contrib non-free non-free-firmware' --apt-recommends false \
  --bootappend-live 'boot=live components hostname=titan-recovery username=recovery' \
  --iso-application "Titan Recovery $TITAN_SYSTEM_VERSION" --iso-volume TITAN_RECOVERY
mkdir -p config/package-lists config/includes.chroot/usr/local/bin \
  config/includes.chroot/etc/systemd/system/multi-user.target.wants
cat > config/package-lists/titan.list.chroot <<'PACKAGES'
linux-image-amd64
live-boot
live-config
systemd-sysv
python3
util-linux
e2fsprogs
xfsprogs
qemu-guest-agent
qemu-utils
acl
parted
firmware-realtek
firmware-bnx2
firmware-bnx2x
firmware-qlogic
firmware-misc-nonfree
intel-microcode
amd64-microcode
PACKAGES
cp /work/titan-recovery.py config/includes.chroot/usr/local/bin/titan-recovery
chmod 0755 config/includes.chroot/usr/local/bin/titan-recovery
cat > config/includes.chroot/etc/systemd/system/titan-recovery.service <<'UNIT'
[Unit]
Description=Titan offline recovery assistant
After=systemd-udev-settle.service local-fs.target
Wants=systemd-udev-settle.service
Conflicts=getty@tty1.service
[Service]
Type=idle
ExecStart=/usr/bin/python3 /usr/local/bin/titan-recovery wizard
StandardInput=tty-force
StandardOutput=tty
StandardError=tty
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
ln -s ../titan-recovery.service config/includes.chroot/etc/systemd/system/multi-user.target.wants/titan-recovery.service
ln -s /dev/null config/includes.chroot/etc/systemd/system/getty@tty1.service
ln -s /usr/lib/systemd/system/qemu-guest-agent.service config/includes.chroot/etc/systemd/system/multi-user.target.wants/qemu-guest-agent.service
lb build
cp live-image-amd64.hybrid.iso /work/titan-recovery.iso
cp live-image-amd64.packages /work/recovery-packages.txt
BUILD
cp "$task_work/titan-recovery.iso" "dist/debian-image/titan-$TITAN_SYSTEM_VERSION-recovery-amd64.iso"
cp "$task_work/recovery-packages.txt" dist/debian-image/recovery-packages.txt
# Build workspace is disposable and can be large. Keep only the deliverables.
sudo rm -rf "$task_work/live"

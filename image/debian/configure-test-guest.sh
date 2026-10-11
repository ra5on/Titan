#!/bin/bash
# Executed inside the disposable libguestfs guest only, never on the runner.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
. /etc/os-release
[[ "$ID" == debian && "$VERSION_ID" == 13 && -f /tmp/titan-configure-test-guest.sh ]] || exit 1
if ! ip -4 route show default | grep -q .; then
    ip link set eth0 up
    ip address replace 169.254.2.15/16 dev eth0
    ip route replace default via 169.254.2.2 dev eth0
fi
rm -f /etc/resolv.conf
printf 'nameserver 169.254.2.3\n' > /etc/resolv.conf
# Keep resolver setup and apt in one libguestfs command. Its --install helper
# replaces resolv.conf between commands with the inactive image's resolver.
getent ahostsv4 deb.debian.org
rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources
cat > /etc/apt/sources.list.d/test-guest.sources <<'SOURCES'
Types: deb
URIs: https://deb.debian.org/debian
Suites: trixie trixie-updates
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: https://security.debian.org/debian-security
Suites: trixie-security
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
SOURCES
apt-get -o APT::Update::Error-Mode=any -o Acquire::Retries=3 update
apt-get install -y --no-install-recommends qemu-guest-agent
touch /etc/cloud/cloud-init.disabled
systemctl enable qemu-guest-agent
apt-get clean
rm -rf /var/lib/apt/lists/*
ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
rm /tmp/titan-configure-test-guest.sh

#!/bin/bash
# The installed guest only: derive the device from its mounted ext4 root.
set -euo pipefail
export LC_ALL=C.UTF-8
python3 - <<'PY'
import json
from pathlib import Path
v=json.loads(Path('/usr/share/titan/image-info.json').read_text())
assert v['platform']=='debian-preview' and v.get('bootable_image') is True
PY
[[ "$(findmnt -nro FSTYPE /)" == ext4 ]] || exit 1
task_root=$(readlink -f -- "$(findmnt -nro SOURCE /)")
[[ "$task_root" =~ ^/dev/(sd[a-z]+[0-9]+|vd[a-z]+[0-9]+|nvme[0-9]+n[0-9]+p[0-9]+)$ ]] || exit 1
[[ "$(lsblk -dnro TYPE "$task_root")" == part ]] || exit 1
task_parent=$(lsblk -dnro PKNAME "$task_root")
[[ "$task_parent" =~ ^(sd[a-z]+|vd[a-z]+|nvme[0-9]+n[0-9]+)$ ]] || exit 1
task_number=$(cat "/sys/class/block/${task_root##*/}/partition")
[[ "$task_number" =~ ^[0-9]+$ ]] || exit 1
task_status=0
growpart --dry-run "/dev/$task_parent" "$task_number" || task_status=$?
case "$task_status" in
    0) growpart "/dev/$task_parent" "$task_number" ;;
    1) : ;; # no remaining free sectors; still resize after interrupted prior grow
    *) exit "$task_status" ;;
esac
resize2fs "$task_root"
ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf

#!/bin/bash
# Normalize a newly exported regular ext4 file, never a host block device.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
[[ "${GITHUB_ACTIONS:-}" == true ]] || exit 1
task_file=${1:?rootfs file required}
task_bytes=${2:-17179869184}
[[ -f "$task_file" && ! -L "$task_file" && $(stat -c %h "$task_file") == 1 ]] || exit 1
[[ "$task_bytes" =~ ^[0-9]{8,11}$ ]] || exit 1
(( task_bytes >= 67108864 && task_bytes <= 17179869184 && task_bytes % 4096 == 0 )) || exit 1
[[ $(stat -c %s "$task_file") -le "$task_bytes" ]] || exit 1
[[ $(blkid -p -s TYPE -o value "$task_file") == ext4 ]] || exit 1
check_rootfs() {
    local task_status=0
    e2fsck -f -p "$task_file" || task_status=$?
    [[ "$task_status" == 0 || "$task_status" == 1 ]]
}
check_rootfs
truncate -s "$task_bytes" "$task_file"
resize2fs "$task_file"
check_rootfs

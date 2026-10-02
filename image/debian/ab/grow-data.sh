#!/bin/bash
# Only the last, dedicated data partition may grow. A/B system slots stay fixed.
set -euo pipefail
export LC_ALL=C.UTF-8
task_data=$(readlink -f /dev/disk/by-partlabel/TITAN-DATA)
[[ -b "$task_data" && "$(findmnt -nro FSTYPE /var/lib/titan-system)" == ext4 ]] || exit 1
[[ "$(readlink -f "$(findmnt -nro SOURCE /var/lib/titan-system)")" == "$task_data" ]] || exit 1
[[ "$(lsblk -dnro TYPE "$task_data")" == part ]] || exit 1
task_parent=$(lsblk -dnro PKNAME "$task_data")
[[ "$task_parent" =~ ^(sd[a-z]+|vd[a-z]+|nvme[0-9]+n[0-9]+)$ ]] || exit 1
task_number=$(cat "/sys/class/block/${task_data##*/}/partition")
[[ "$task_number" == 5 ]] || exit 1
task_status=0
growpart --dry-run "/dev/$task_parent" "$task_number" || task_status=$?
case "$task_status" in
 0) growpart "/dev/$task_parent" "$task_number" ;;
 1) : ;;
 *) exit "$task_status" ;;
esac
resize2fs "$task_data"

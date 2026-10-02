#!/bin/sh
# Included inside the signed RAUC bundle, never downloaded separately.
set -eu
[ "${1:-}" = slot-post-install ] || exit 1
case "${RAUC_SLOT_NAME:-}" in
    rootfs.0) task_slot=A ;;
    rootfs.1) task_slot=B ;;
    *) exit 1 ;;
esac
task_expected=$(readlink -f "/dev/disk/by-partlabel/TITAN-$task_slot")
[ -b "$task_expected" ] && [ "$(readlink -f "$RAUC_SLOT_DEVICE")" = "$task_expected" ] || exit 1
[ "$(readlink -f "$(findmnt -nro SOURCE /)")" != "$task_expected" ] || exit 1
# Both slots receive the same payload. Labels and UUIDs must become unique
# before GRUB searches for the candidate and before udev identifies its root.
tune2fs -L "TITAN-$task_slot" -U random "$task_expected"

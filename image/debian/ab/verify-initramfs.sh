#!/bin/bash
# Build gate, no mounts or hardware writes. Inspect the shipped kernel/initrd.
set -euo pipefail
[[ $# == 2 && "$1" =~ ^[a-zA-Z0-9.+_-]+-amd64$ && "$1" != *-cloud-amd64 ]] || {
    echo 'Titan requires the general AMD64 kernel for portable hardware boot.' >&2; exit 1;
}
task_kernel=$1
task_initrd=$2
[[ -f "$task_initrd" && ! -L "$task_initrd" ]] || exit 1
task_list=$(mktemp)
trap 'rm -f "$task_list"' EXIT
lsinitramfs "$task_initrd" > "$task_list"
# This checks an explicit baseline, not every device supported by Debian.
for task_driver in ext4 overlay ahci nvme usb_storage uas xhci_pci virtio_pci virtio_blk virtio_scsi megaraid_sas mpt3sas; do
    task_module=$(modinfo -k "$task_kernel" -F filename "$task_driver")
    if [[ "$task_module" == '(builtin)' ]]; then continue; fi
    [[ -f "$task_module" && "$task_module" == */"$task_kernel"/* ]] || {
        echo "Missing module for shipped kernel: $task_driver" >&2; exit 1;
    }
    task_name=$(basename "$task_module")
    task_name=${task_name%%.ko*}
    [[ "$task_name" =~ ^[a-zA-Z0-9_-]+$ ]] || exit 1
    grep -Eq "/${task_name}\.ko(\.(xz|gz|zst))?$" "$task_list" || {
        echo "Required boot driver absent from initramfs: $task_driver" >&2; exit 1;
    }
done

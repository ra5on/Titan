#!/bin/sh
PREREQ=""
prereqs() { echo "$PREREQ"; }
case "$1" in prereqs) prereqs; exit 0 ;; esac
. /usr/share/initramfs-tools/hook-functions
copy_exec /usr/bin/cp /bin
copy_exec /usr/bin/chmod /bin
copy_exec /usr/bin/mv /bin
copy_exec /usr/bin/sync /bin
copy_exec /usr/bin/rm /bin
# A dedicated path prevents klibc hooks from shadowing util-linux mount.
copy_exec /usr/bin/mount /bin/titan-mount
copy_exec /usr/sbin/e2fsck /sbin
manual_add_modules ext4
manual_add_modules overlay

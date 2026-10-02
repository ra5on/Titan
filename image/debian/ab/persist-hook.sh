#!/bin/sh
PREREQ=""
prereqs() { echo "$PREREQ"; }
case "$1" in prereqs) prereqs; exit 0 ;; esac
. /usr/share/initramfs-tools/hook-functions
copy_exec /usr/bin/cp /bin
copy_exec /usr/bin/chmod /bin
copy_exec /usr/bin/mv /bin
copy_exec /usr/bin/sync /bin
copy_exec /usr/bin/mount /bin
manual_add_modules ext4

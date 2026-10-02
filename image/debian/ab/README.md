# Titan Debian A/B contract v1

UEFI boot, two ext4 system slots, a separate bootloader environment and a shared
ext4 data partition. RAUC verifies verity bundles and writes only the inactive
slot. Titan activates a slot only after validating the full signed release.
GRUB attempts a candidate once; absence of health confirmation makes the next
boot select the other healthy slot. A hung machine still needs a reset (or a
working hardware watchdog); boot selection is not a hardware watchdog.

`/etc` uses a persistent overlay upper layer over each slot's factory defaults.
Unmodified OS configuration follows the selected release; local changes persist.
NAS metadata, Samba identities, Docker/containerd, libvirt, homes and
NAS data are persisted before PID 1 through an initramfs script. `/var/lib/dpkg`
and the kernel belong to each system slot. The signed factory user/group UID/GID
contract must match the running image before installation; changes require a separate migration. Configuration/data schema is fixed at
1: releases requiring incompatible shared state are rejected. Rollback preserves
current NAS configuration and user data; it is not a database/data restore.
New base services/configuration need explicit compatible initialization, not an
unconditional copy of new `/etc` defaults over existing NAS settings.

The persistent signing key remains Ed25519. It signs release manifests and an
ephemeral ECDSA code-signing certificate per build; RAUC CMS uses that certificate.
The installed trust anchor is `packaging/rauc-root.pem`. No second user secret is
needed, and build-specific leaf private keys are discarded.

This integration is not release-ready until the disposable VM suite demonstrates
install, signed update, reboot, health confirmation, manual rollback, failed-boot
fallback, preserved users/ACLs/data and data-partition growth.

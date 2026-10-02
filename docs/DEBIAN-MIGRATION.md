# Debian migration: first integration stage

The target is Debian 13 (trixie), amd64, with Titan-owned A/B system releases.
Ubuntu is a possible future platform, not a supported alternative today.
Existing uCore installations are not converted and must not install this package.
The current production update channel remains separate from this development work.

## Implemented

- Explicit platform profiles for Samba units, libvirt monitoring and QEMU file ownership.
- Debian preview package containing Titan, HTTPS configuration, firstboot and service units.
- Debian package dependencies include Docker/Compose, QEMU/libvirt, noVNC, Samba,
  ext4/XFS utilities and monitoring tools. No third-party executable installer downloads.
- Debian runtime service repair uses libvirtd and retains AppArmor.
- The preview rejects the uCore update path. No system update or rollback is advertised.
- Package build does not install packages, start services or modify disks on its host.

Build from the repository root:

```sh
python3 scripts/build-debian-package.py
```

This produces a **development .deb**, not a bootable IMG and not an A/B update.
Install only in a disposable, otherwise empty Debian 13 amd64 VM with a normal
working network and official Debian repositories. Never use the current NAS.
Installing the package does not activate its services. Deliberate test activation:

```sh
sudo apt install ./titan-debian-preview_*_amd64.deb
sudo systemctl daemon-reload
sudo systemctl enable --now firewalld
sudo systemctl start titan-firstboot
sudo systemctl enable --now smbd docker libvirtd.socket virtlogd.socket virtlockd.socket
sudo systemctl enable --now titan-firstboot titan-runtime titan-agent titan-web titan-proxy
```

Firstboot configures Samba and opens HTTPS/SMB in firewalld. Access is through
`https://<VM-IP>:5000`. No default passwords are supplied. Guest networking,
AppArmor access to additional VM volumes, external SMB access and Docker port
exposure still need live verification. ZFS packaging/kernel integration is not
included in this first preview; ext4/XFS are the initial storage targets.

## Remaining before an image or public Debian release

1. Build Debian root filesystems in isolated CI; record exact package versions.
2. Create bootable disks: EFI, two system slots, independent persistent data.
   Use stable filesystem identifiers, not assumptions about /dev/sda.
3. Signed update manifest including platform, slot format, digest, size and schema
   compatibility. Verify the entire payload before touching the inactive slot.
4. Boot attempts, health confirmation and recovery without a working web UI.
   Failed trial boots must return to the previous slot. No automatic reboot.
5. Define per-slot configuration and shared state explicitly: passwd/group IDs,
   Samba credentials, network settings and Titan DB migrations must remain coherent.
   Shared /var alone does not provide rollback of application schemas or /etc.
6. Test update/reboot/rollback, interrupted writes, full disks, growth, recovery,
   Docker data, SMB ACLs, real guest boot and VM storage access in QEMU/Proxmox.
7. Migration export/import preserving credentials, UIDs, ACLs, volumes and app data.
   A clean installation with checked restore is preferred over in-place conversion.

Do not mark Debian beta-ready until these gates pass. Keep the old release code
until replacement and recovery are proven; historical references document existing
installations and are not evidence that Debian is ready.

Package references: https://packages.debian.org/trixie/docker-compose and
https://packages.debian.org/trixie/libvirt-daemon-system.

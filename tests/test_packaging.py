"""Validate the complete immutable image and its release contract."""
import json
from pathlib import Path
import re
import tomllib
import unittest
from titan import __version__,__release_stage__
ROOT=Path(__file__).resolve().parents[1]


class ImagePackagingTests(unittest.TestCase):
    def test_pinned_hci_base_and_required_dependencies(self):
        source=(ROOT/'legacy/ucore/Containerfile').read_text()
        self.assertRegex(source,r'FROM ghcr.io/ublue-os/ucore-hci@sha256:[a-f0-9]{64}')
        for package in ('caddy','python3-websockify','novnc','xfsprogs','policycoreutils-python-utils'):
            self.assertIn(package,source)
        self.assertIn('"bootc", "container", "lint"',source)

    def test_archived_ucore_metadata_remains_frozen(self):
        info=json.loads((ROOT/'legacy/ucore/image/image-info.json').read_text())
        # Archived uCore artifacts do not track new Debian release versions.
        self.assertEqual(info['version'],'0.4.6')
        self.assertEqual(info['release_stage'],__release_stage__)
        self.assertEqual(info['image_repository'],'ghcr.io/ra5on/titan')
        self.assertEqual(info['platform'],'ucore-hci')

    def test_disk_metadata_and_custom_layout_keep_coreos_boot_partition(self):
        disk=json.loads((ROOT/'legacy/ucore/image/bootc-disk.json').read_text())
        self.assertEqual(disk['mount_configuration'],'none')
        metadata=disk['partition_table']
        custom=tomllib.loads((ROOT/'legacy/ucore/image/disk.toml').read_text())['customizations']['disk']
        filesystems={p['payload']['mountpoint']:p['payload'] for p in metadata['partitions'] if 'payload' in p}
        self.assertEqual(filesystems['/boot']['type'],'ext4')
        self.assertEqual(filesystems['/']['type'],'xfs')
        self.assertTrue(any(p['label']=='BIOS-BOOT' for p in metadata['partitions']))
        for partition in custom['partitions']:
            inherited=filesystems[partition['mountpoint']]
            self.assertEqual((partition['fs_type'],partition['label']), (inherited['type'],inherited['label']))
        self.assertFalse(any('mkfs_options' in filesystem for filesystem in filesystems.values()))
        self.assertIn('/usr/lib/image-builder/bootc/disk.yaml', (ROOT/'legacy/ucore/image/install-image.sh').read_text())

    def test_secret_paths_are_excluded_from_build(self):
        ignore=(ROOT/'.containerignore').read_text()
        for path in ('.secrets','.demo','dist','artifacts','**/*.key','**/__pycache__'):
            self.assertIn(path,ignore)

    def test_services_require_firstboot_and_keep_web_sandbox(self):
        for name in ('agent','web','proxy'):
            source=(ROOT/f'packaging/titan-{name}.service').read_text()
            self.assertIn('Requires=titan-firstboot.service',source)
            self.assertIn('After=titan-firstboot.service',source)
        source=(ROOT/'packaging/titan-web.service').read_text()
        self.assertIn('ProtectSystem=strict',source)
        self.assertIn('User=titan\n',source)

    def test_release_gates_image_on_real_vm_boot_and_signature(self):
        source=(ROOT/'legacy/ucore/workflows/release.yml').read_text()
        for marker in ('cosign import-key-pair','cosign verify','sudo skopeo','bash scripts/smoke-image.sh',
                       'dist/*.img.xz','TITAN_SIGNING_KEY','--rootfs xfs','org.opencontainers.image.version'):
            self.assertIn(marker,source)
        self.assertLess(source.index('bash scripts/smoke-image.sh'),source.index('gh release create'))
        self.assertNotIn('build_deb',source)
        self.assertRegex(source,r'bootc-image-builder@sha256:[a-f0-9]{64}')

    def test_legacy_package_builder_is_absent(self):
        for name in ('scripts/build_deb.py','scripts/prepare_apt.py','packaging/postinst','packaging/prerm'):
            self.assertFalse((ROOT/name).exists())

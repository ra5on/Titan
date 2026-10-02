"""Managed namespace traversal, without widening share data permissions."""
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from titan.core import Error
from titan.host import Host
from titan.volumes import Volumes


class SharePathTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.storage = self.root / "storage"
        self.storage.mkdir(mode=0o755)
        self.host = Host(self.root / "agent", self.storage, self.root / "vms", self.root / "smb.conf")
        self.cleanup_modes = []

    def tearDown(self):
        for path in self.cleanup_modes:
            path.chmod(0o755)
        self.temporary.cleanup()

    def test_create_under_agent_umask_allows_parent_traversal_only(self):
        owner = SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid())
        original_umask = os.umask(0o027)
        try:
            with patch("titan.management_host.pwd.getpwnam", return_value=owner), \
                    patch.object(self.host, "share_acl_transaction", side_effect=lambda record, readers, writers, publish: publish()), \
                    patch.object(self.host, "share_config_transaction"):
                self.host.op_share_create("documents", [], ["titan-files"])
        finally:
            os.umask(original_umask)
        namespace = self.storage / "shares"
        share = namespace / "documents"
        self.assertEqual(stat.S_IMODE(namespace.stat().st_mode), 0o751)
        self.assertEqual(stat.S_IMODE(share.stat().st_mode), 0o750)
        self.assertEqual(self.host.op_shares()[0]["path"], str(share))

    def test_access_repairs_legacy_parent_without_touching_child_or_file(self):
        namespace = self.storage / "shares"
        namespace.mkdir(mode=0o700)
        share = namespace / "documents"
        share.mkdir(mode=0o750)
        secret = share / "private.txt"
        secret.write_text("kept")
        secret.chmod(0o600)
        owner = namespace.stat().st_uid, namespace.stat().st_gid
        fd = self.host.open_share_root(share)
        os.close(fd)
        self.assertEqual(stat.S_IMODE(namespace.stat().st_mode), 0o711)
        self.assertEqual((namespace.stat().st_uid, namespace.stat().st_gid), owner)
        self.assertEqual(stat.S_IMODE(share.stat().st_mode), 0o750)
        self.assertEqual(stat.S_IMODE(secret.stat().st_mode), 0o600)
        self.assertEqual(secret.read_text(), "kept")

    def test_restricted_storage_root_repairs_traversal_without_read_or_write_access(self):
        self.storage.chmod(0o700)
        owner = SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid())
        original_umask = os.umask(0o027)
        try:
            with patch("titan.management_host.pwd.getpwnam", return_value=owner):
                path = self.host.system_share_path("documents")
        finally:
            os.umask(original_umask)
        self.assertEqual(stat.S_IMODE(self.storage.stat().st_mode), 0o711)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o750)

    def test_symlink_namespace_is_not_followed_or_modified(self):
        outside = self.root / "outside"
        outside.mkdir(mode=0o700)
        (self.storage / "shares").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            self.host.system_share_path("documents")
        self.assertFalse((outside / "documents").exists())
        self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o700)

    def test_writable_or_foreign_namespace_is_rejected_before_creation(self):
        namespace = self.storage / "shares"
        namespace.mkdir(mode=0o750)
        namespace.chmod(0o752)
        with self.assertRaises(Error):
            self.host.system_share_path("documents")
        self.assertFalse((namespace / "documents").exists())
        self.assertEqual(stat.S_IMODE(namespace.stat().st_mode), 0o752)
        namespace.chmod(0o750)
        with patch("titan.management_host.os.geteuid", return_value=namespace.stat().st_uid + 1), self.assertRaises(Error):
            self.host.system_share_path("documents")
        self.assertFalse((namespace / "documents").exists())
        self.assertEqual(stat.S_IMODE(namespace.stat().st_mode), 0o750)

    def test_existing_share_folder_is_not_adopted_or_chowned(self):
        namespace = self.storage / "shares"
        namespace.mkdir(mode=0o751)
        share = namespace / "documents"
        share.mkdir(mode=0o700)
        (share / "existing.txt").write_text("preserve")
        with patch("titan.management_host.os.fchown") as chown, self.assertRaises(Error) as rejected:
            self.host.system_share_path("documents")
        self.assertEqual(rejected.exception.status, 409)
        chown.assert_not_called()
        self.assertEqual(stat.S_IMODE(share.stat().st_mode), 0o700)
        self.assertEqual((share / "existing.txt").read_text(), "preserve")

    def volume_fixture(self):
        namespace = self.storage / "volumes"
        namespace.mkdir(mode=0o750)
        mountpoint = namespace / "disk"
        mountpoint.mkdir(mode=0o755)
        mounted_namespace = mountpoint / "shares"
        mounted_namespace.mkdir(mode=0o750)
        share = mounted_namespace / "documents"
        share.mkdir(mode=0o750)
        record = {"name": "disk", "filesystem": "ext4", "uuid": str(uuid.uuid4())}
        self.host.save("volumes", [record])
        manager = Volumes(self.host, lambda *args, **kwargs: "", self.root / "fstab", os.geteuid())
        self.host._volumes = manager
        device = os.stat(mountpoint).st_dev
        mounts = [{"target": str(mountpoint), "fstype": "ext4", "uuid": record["uuid"],
                   "maj:min": f"{os.major(device)}:{os.minor(device)}"}]
        return manager, record, namespace, mountpoint, mounted_namespace, share, mounts

    def test_mounted_volume_access_repairs_namespaces_without_data_mode_change(self):
        manager, record, namespace, mountpoint, mounted_namespace, share, mounts = self.volume_fixture()
        secret = share / "private.txt"
        secret.write_text("volume data")
        secret.chmod(0o600)
        with patch.object(manager, "mounts", return_value=mounts):
            fd = self.host.open_share_root(share)
            os.close(fd)
        self.assertEqual(stat.S_IMODE(namespace.stat().st_mode), 0o751)
        self.assertEqual(stat.S_IMODE(mounted_namespace.stat().st_mode), 0o751)
        self.assertEqual(stat.S_IMODE(mountpoint.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(share.stat().st_mode), 0o750)
        self.assertEqual(stat.S_IMODE(secret.stat().st_mode), 0o600)

    def test_volume_creation_under_umask_opens_only_shared_namespace(self):
        manager, record, namespace, mountpoint, mounted_namespace, share, mounts = self.volume_fixture()
        original_umask = os.umask(0o027)
        try:
            with patch.object(manager, "mounts", return_value=mounts):
                path = manager.share_path("disk", "pictures")
        finally:
            os.umask(original_umask)
        self.assertEqual(path, mounted_namespace / "pictures")
        self.assertEqual(stat.S_IMODE(namespace.stat().st_mode), 0o751)
        self.assertEqual(stat.S_IMODE(mounted_namespace.stat().st_mode), 0o751)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o750)

    def test_mounted_private_volume_root_allows_share_traversal_without_listing(self):
        manager, record, namespace, mountpoint, mounted_namespace, share, mounts = self.volume_fixture()
        mountpoint.chmod(0o700)
        with patch.object(manager, "mounts", return_value=mounts):
            fd = self.host.open_share_root(share)
            os.close(fd)
        self.assertEqual(stat.S_IMODE(mountpoint.stat().st_mode), 0o711)
        self.assertEqual(stat.S_IMODE(share.stat().st_mode), 0o750)

    def test_new_share_on_mounted_private_volume_root_repairs_only_traversal(self):
        manager, record, namespace, mountpoint, mounted_namespace, share, mounts = self.volume_fixture()
        mountpoint.chmod(0o700)
        with patch.object(manager, "mounts", return_value=mounts):
            path = manager.share_path("disk", "pictures")
        self.assertEqual(stat.S_IMODE(mountpoint.stat().st_mode), 0o711)
        self.assertEqual(stat.S_IMODE(share.stat().st_mode), 0o750)
        self.assertEqual(path, mounted_namespace / "pictures")

    def test_offline_volume_denies_access_without_opening_fallback_permissions(self):
        manager, record, namespace, mountpoint, mounted_namespace, share, mounts = self.volume_fixture()
        mountpoint.chmod(0o000)
        self.cleanup_modes.append(mountpoint)
        with patch.object(manager, "mounts", return_value=[]), patch("titan.management_host.os.fchmod") as chmod:
            with self.assertRaises(Error) as rejected:
                self.host.open_share_root(share)
        self.assertEqual(rejected.exception.status, 503)
        chmod.assert_not_called()
        self.assertEqual(stat.S_IMODE(mountpoint.stat().st_mode), 0o000)
        self.assertEqual(stat.S_IMODE(namespace.stat().st_mode), 0o750)


if __name__ == "__main__":
    unittest.main()

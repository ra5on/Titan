"""Exercise real ACL tools only inside a temporary, owned directory.

The desktop sandbox maps one UID. Use that UID so a sandbox's unmapped IDs
do not masquerade as an ACL failure; actual multiuser SMB runs in the CI guest.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from titan.host import Host


@unittest.skipUnless(shutil.which("getfacl") and shutil.which("setfacl"), "ACL tools are unavailable")
class RealShareACLTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="titan-real-acl-")
        self.root = Path(self.temporary.name)
        self.share_root = self.root / "storage"
        self.share_root.mkdir(mode=0o755)
        self.host = Host(self.root / "agent", self.share_root, self.root / "vms", self.root / "smb.conf")
        self.host.save("accounts", [{"name": "testuser", "uid": os.getuid(), "enabled": True}])
        self.account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        self.pwd_patch = patch("titan.management_host.pwd.getpwnam", return_value=self.account)
        self.pwd_patch.start()
        self.share = self.share_root / "shares" / "documents"
        self.share.parent.mkdir(mode=0o751)
        self.share.mkdir(mode=0o700)
        self.record = {"name": "documents", "path": str(self.share), "readers": [], "writers": ["testuser"]}
        self.host.save("shares", [self.record])

    def tearDown(self):
        self.pwd_patch.stop()
        self.share.chmod(0o700)
        for item in self.share.rglob("*"):
            if item.is_dir(): item.chmod(0o700)
            else: item.chmod(0o600)
        self.temporary.cleanup()

    @staticmethod
    def acl(path):
        return subprocess.run(["getfacl", "--omit-header", "--numeric", "--", str(path)],
                              capture_output=True, text=True, check=True).stdout

    def test_real_acl_writer_and_new_file_default_inheritance(self):
        self.host.share_acl_transaction(self.record, [], ["testuser"], lambda: None)
        text = self.acl(self.share)
        self.assertIn(f"user:{os.getuid()}:rwx", text)
        self.assertIn(f"default:user:{os.getuid()}:rwx", text)
        child = self.share / "created.txt"
        child.write_text("saved")
        self.assertIn(f"user:{os.getuid()}:rwx", self.acl(child))
        self.assertIn("mask::rw-", self.acl(child))
        self.assertEqual(child.read_text(), "saved")

    def test_real_acl_readonly_existing_file_and_revoked_owner(self):
        child = self.share / "data.txt"
        child.write_text("original")
        child.chmod(0o600)
        self.host.share_acl_transaction(self.record, ["testuser"], [], lambda: None)
        self.assertTrue(os.access(child, os.R_OK))
        self.assertFalse(os.access(child, os.W_OK))
        self.assertIn("user::r--", self.acl(child))
        self.assertEqual(child.read_text(), "original")
        # The production agent is root and can traverse after revocation. This
        # unprivileged fixture cannot, so revoke an empty directory instead.
        self.share.chmod(0o700)
        child.unlink()
        self.host.share_acl_transaction(self.record, [], [], lambda: None)
        self.assertFalse(os.access(self.share, os.R_OK))
        self.assertFalse(os.access(self.share, os.X_OK))

    def test_real_acl_transaction_failure_restores_exact_access_and_defaults(self):
        self.host.share_acl_transaction(self.record, [], ["testuser"], lambda: None)
        child = self.share / "data.txt"
        child.write_text("kept")
        before = self.acl(self.share), self.acl(child)
        def fail():
            raise RuntimeError("publish failed")
        with self.assertRaises(RuntimeError):
            self.host.share_acl_transaction(self.record, ["testuser"], [], fail)
        self.assertEqual((self.acl(self.share), self.acl(child)), before)
        self.assertEqual(child.read_text(), "kept")


if __name__ == "__main__":
    unittest.main()

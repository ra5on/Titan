import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from titan.core import Error, Store
from titan.demo import Demo
from titan.host import Host
from titan.users import Users


class UserDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.store.setup("admin", "admin-original-password")
        self.store.create_user("reader", "reader-original-password", "user", "reader")
        self.agent = Mock()
        self.users = Users(self.store, self.agent)

    def tearDown(self):
        self.temp.cleanup()

    def test_removal_revokes_every_session_and_removes_web_identity(self):
        tokens = [self.store.login("reader", "reader-original-password")[0] for _ in range(2)]
        result = self.users.remove("admin", "reader", "reader")
        self.assertTrue(result["data_retained"])
        self.agent.call.assert_called_once_with("account_remove", name="reader")
        self.assertEqual([item["name"] for item in self.store.users()], ["admin"])
        for token in tokens:
            self.assertIsNone(self.store.session(token))
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions WHERE username='reader'").fetchone()[0], 0)
        with self.assertRaises(Error):
            self.store.login("reader", "reader-original-password")

    def test_web_access_is_revoked_before_host_cleanup_and_failure_can_be_retried(self):
        token, _ = self.store.login("reader", "reader-original-password")
        def fail(*args, **kwargs):
            self.assertIsNone(self.store.session(token))
            self.assertFalse(self.store.user_record("reader")["enabled"])
            raise Error("SMB nicht erreichbar", 503)
        self.agent.call.side_effect = fail
        with self.assertRaises(Error) as error:
            self.users.remove("admin", "reader", "reader")
        self.assertEqual(error.exception.status, 503)
        self.assertIn("erneut", str(error.exception))
        self.assertFalse(self.store.user_record("reader")["enabled"])
        self.agent.call.side_effect = None
        self.users.remove("admin", "reader", "reader")
        self.assertEqual([item["name"] for item in self.store.users()], ["admin"])

    def test_self_delete_and_missing_confirmation_have_no_host_effect(self):
        for name, confirmation in (("admin", "admin"), ("reader", "wrong"), ("reader", None)):
            with self.assertRaises(Error):
                self.users.remove("admin", name, confirmation)
        self.assertTrue(self.store.user_record("reader")["enabled"])
        self.agent.call.assert_not_called()

    def test_revoked_or_normal_actor_cannot_execute_queued_delete(self):
        self.store.create_user("second", "second-long-password", "admin", "second")
        self.store.update_user("second", enabled=False)
        for actor in ("reader", "second"):
            with self.assertRaises(Error) as error:
                self.users.remove(actor, "reader", "reader")
            self.assertEqual(error.exception.status, 403)
        self.agent.call.assert_not_called()

    def test_deleting_service_backed_admin_retains_shared_host_identity(self):
        self.store.create_user("second", "second-long-password", "admin", "second")
        self.users.remove("second", "admin", "admin")
        self.agent.call.assert_not_called()
        self.assertEqual([item["name"] for item in self.store.users()], ["reader", "second"])

    def test_shared_custom_identity_is_not_deleted_out_from_under_another_user(self):
        self.store.create_user("second", "second-long-password", "user", "reader")
        with self.assertRaises(Error) as error:
            self.users.remove("admin", "reader", "reader")
        self.assertEqual(error.exception.status, 409)
        self.assertTrue(self.store.user_record("reader")["enabled"])
        self.agent.call.assert_not_called()

    def test_demo_removes_account_memberships_and_preserves_files(self):
        with tempfile.TemporaryDirectory() as folder:
            demo = Demo(Path(folder) / "files")
            contents = (demo.directory / "Willkommen.txt").read_text()
            result = demo.call("account_remove", name="patrick")
            self.assertTrue(result["data_retained"])
            self.assertNotIn("patrick", demo.shares[0]["writers"])
            self.assertIn("titan-files", demo.shares[0]["writers"])
            self.assertEqual((demo.directory / "Willkommen.txt").read_text(), contents)
            with self.assertRaises(Error):
                demo.call("account_update", name="patrick", enabled=True)
            with self.assertRaises(Error):
                demo.validate_rights([], ["patrick"])
            demo._temporary.cleanup()


class HostDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.share = self.root / "documents"
        self.share.mkdir()
        (self.share / "important.txt").write_text("retained content")
        self.config = self.root / "smb.conf"
        self.host = Host(self.root / "agent", self.root, self.root / "vms", self.config)
        self.host.save("accounts", [{"name": "alice", "uid": 2000, "enabled": True},
                                    {"name": "bob", "uid": 2001, "enabled": True}])
        self.host.save("shares", [{"name": "documents", "path": str(self.share), "readers": ["alice"], "writers": ["bob"]}])
        self.samba = {"alice", "bob"}
        self.acls = {}
        self.base_acl = "user::rwx\nuser:2000:r-x\nuser:2001:rwx\ngroup::r-x\nmask::rwx\nother::---"
        self.host.command = Mock(side_effect=self.command)
        self.pwd = patch("titan.management_host.pwd.getpwnam", side_effect=self.account)
        self.pwd.start()

    def tearDown(self):
        self.pwd.stop()
        self.temp.cleanup()

    @staticmethod
    def account(name):
        values = {"alice": 2000, "bob": 2001, "titan-files": 991, "root": 0}
        if name not in values:
            raise KeyError(name)
        return SimpleNamespace(pw_uid=values[name], pw_gid=values[name])

    def command(self, args, **kwargs):
        if args == ["pdbedit", "-L"]:
            return "\n".join(name + ":2000:" for name in sorted(self.samba))
        if args[:3] == ["pdbedit", "-L", "-w"]:
            name = args[-1]
            return name + ":" + str(self.account(name).pw_uid) + ":" + "A" * 32 + ":" + "B" * 32 + ":[U          ]:LCT-00000000:"
        if args[:2] == ["smbpasswd", "-x"]:
            self.samba.discard(args[-1])
        if args[0] == "getfacl":
            info = os.fstat(kwargs["pass_fds"][0])
            return self.acls.get((info.st_dev, info.st_ino), self.base_acl)
        if args[0] == "setfacl" and "--set-file=-" in args:
            info = os.fstat(kwargs["pass_fds"][0])
            self.acls[(info.st_dev, info.st_ino)] = kwargs["input"].strip()
        return ""

    def test_deletion_cleans_memberships_acls_and_smb_but_preserves_uid_and_data(self):
        result = self.host.dispatch("account_remove", name="alice")
        self.assertTrue(result["linux_account_retained"])
        self.assertNotIn("alice", self.samba)
        self.assertEqual(self.host.op_shares()[0]["readers"], [])
        self.assertEqual(self.host.op_shares()[0]["writers"], ["bob"])
        self.assertIn("valid users = bob", self.config.read_text())
        self.assertTrue(self.host.op_accounts()[0]["removed"])
        self.assertTrue(self.acls)
        for value in self.acls.values():
            self.assertIn("user:2000:---", value)
            self.assertIn("user:2001:rwX", value)
        self.assertEqual((self.share / "important.txt").read_text(), "retained content")
        commands = [call.args[0] for call in self.host.command.call_args_list]
        self.assertIn(["usermod", "--lock", "alice"], commands)
        self.assertNotIn("userdel", [item[0] for item in commands])
        self.assertIn(["smbcontrol", "smbd", "close-share", "documents"], commands)

    def test_existing_disabled_members_survive_cleanup(self):
        self.host.save("accounts", [{"name": "alice", "uid": 2000, "enabled": True},
                                    {"name": "bob", "uid": 2001, "enabled": False}])
        self.host.op_account_remove("alice")
        self.assertEqual(self.host.op_shares()[0]["writers"], ["bob"])
        self.assertIn("available = no", self.config.read_text())

    def test_already_deleted_account_is_idempotent_and_cannot_be_reenabled(self):
        self.host.op_account_remove("alice")
        self.host.command.reset_mock()
        self.host.op_account_remove("alice")
        self.host.command.assert_not_called()
        with self.assertRaises(Error):
            self.host.op_account_update("alice", enabled=True)
        with self.assertRaises(Error):
            self.host.op_account_create("alice", "long-enough-password")

    def test_legacy_deleted_identity_still_has_memberships_cleaned(self):
        self.host.save("accounts", [{"name": "alice", "uid": 2000, "enabled": False, "removed": True},
                                    {"name": "bob", "uid": 2001, "enabled": True}])
        self.host.op_account_remove("alice")
        self.assertEqual(self.host.op_shares()[0]["readers"], [])
        for value in self.acls.values():
            self.assertIn("user:2000:---", value)

    def test_cleanup_failure_keeps_identity_blocked_and_can_retry(self):
        original = self.command
        def fail(args, **kwargs):
            if args[0] == "setfacl" and "--set-file=-" in args:
                raise Error("ACL unavailable")
            return original(args, **kwargs)
        self.host.command.side_effect = fail
        with self.assertRaises(Error):
            self.host.op_account_remove("alice")
        self.assertFalse(self.host.op_accounts()[0]["enabled"])
        self.assertFalse(self.host.op_accounts()[0].get("removed", False))
        self.assertIn("alice", self.samba)
        self.assertEqual(self.host.op_shares()[0]["readers"], ["alice"])
        self.host.command.side_effect = original
        self.host.op_account_remove("alice")
        self.assertNotIn("alice", self.samba)

    def test_absent_samba_identity_does_not_prevent_cleanup(self):
        self.samba.discard("alice")
        self.host.op_account_remove("alice")
        self.assertTrue(self.host.op_accounts()[0]["removed"])
        self.assertEqual(self.host.op_shares()[0]["readers"], [])
        commands = [call.args[0] for call in self.host.command.call_args_list]
        self.assertNotIn(["smbpasswd", "-d", "alice"], commands)
        self.assertNotIn(["smbpasswd", "-x", "alice"], commands)

    def test_samba_reload_failure_never_reenables_removed_identity(self):
        original = self.command
        def fail(args, **kwargs):
            if args == ["systemctl", "reload", "smbd"]:
                raise Error("reload unavailable")
            return original(args, **kwargs)
        self.host.command.side_effect = fail
        with self.assertRaises(Error):
            self.host.op_account_remove("alice")
        self.assertFalse(self.host.op_accounts()[0]["enabled"])
        commands = [call.args[0] for call in self.host.command.call_args_list]
        self.assertIn(["smbpasswd", "-d", "alice"], commands)
        self.assertNotIn(["smbpasswd", "-e", "alice"], commands)
        self.assertFalse(any(item[:2] == ["pdbedit", "-i"] for item in commands))

    def test_retry_after_samba_deletion_does_not_delete_it_twice(self):
        original = self.host.save
        failed = False
        def save(name, value):
            nonlocal failed
            if name == "accounts" and any(item.get("removed") for item in value) and not failed:
                failed = True
                raise OSError("journal unavailable")
            original(name, value)
        self.host.save = save
        with self.assertRaises(OSError):
            self.host.op_account_remove("alice")
        self.assertNotIn("alice", self.samba)
        self.host.op_account_remove("alice")
        self.assertEqual(sum(call.args[0] == ["smbpasswd", "-x", "alice"] for call in self.host.command.call_args_list), 1)
        self.assertTrue(self.host.op_accounts()[0]["removed"])

    def test_concurrent_share_update_cannot_restore_a_deleted_membership(self):
        validated = threading.Event()
        release = threading.Event()
        deleting = threading.Event()
        errors = []
        original_members = self.host.share_members
        original_remove = self.host.op_account_remove
        def members(readers, writers, previous=None):
            result = original_members(readers, writers, previous=previous)
            validated.set()
            if not release.wait(3):
                raise RuntimeError("share test timeout")
            return result
        def remove(name):
            deleting.set()
            return original_remove(name)
        self.host.share_members = members
        self.host.op_account_remove = remove
        def operation(task_operation, **kwargs):
            try:
                self.host.dispatch(task_operation, **kwargs)
            except Exception as exc:
                errors.append(exc)
        share_thread = threading.Thread(target=operation, args=("share_update",),
                                        kwargs={"name": "documents", "readers": ["alice"], "writers": ["bob"]})
        delete_thread = threading.Thread(target=operation, args=("account_remove",), kwargs={"name": "alice"})
        share_thread.start()
        try:
            self.assertTrue(validated.wait(3))
            delete_thread.start()
            self.assertFalse(deleting.wait(.05))
        finally:
            release.set()
            share_thread.join(3)
            if delete_thread.ident:
                delete_thread.join(3)
        self.assertFalse(share_thread.is_alive())
        self.assertFalse(delete_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.host.op_shares()[0]["readers"], [])
        self.assertTrue(self.host.op_accounts()[0]["removed"])

    def test_protected_or_changed_uid_cannot_be_removed(self):
        for name in ("root", "titan-files", "foreign"):
            with self.assertRaises(Error):
                self.host.op_account_remove(name)
        self.host.save("accounts", [{"name": "alice", "uid": 4000, "enabled": True}])
        with self.assertRaises(Error):
            self.host.op_account_remove("alice")
        self.host.command.assert_not_called()


if __name__ == "__main__":
    unittest.main()

import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from titan.core import Error
from titan.host import Host


class ManagedHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.volume = self.root / "volume"
        self.volume.mkdir()
        self.config = self.root / "smb.conf"
        self.config.write_text("previous config")
        self.host = Host(self.root / "agent", self.volume, self.root / "vms", self.config)
        self.host.save("accounts", [{"name": "alice", "uid": 2000}, {"name": "bob", "uid": 2001, "enabled": True}])
        self.share = self.volume / "documents"
        self.share.mkdir()
        (self.share / "old.txt").write_text("important data")
        (self.share / "subfolder").mkdir()
        (self.share / "subfolder" / "child.txt").write_text("child")
        self.host.save("shares", [{"name": "documents", "path": str(self.share), "readers": ["alice"], "writers": ["bob"]}])
        self.password_snapshot = "alice:2000:" + "A" * 32 + ":" + "B" * 32 + ":[U          ]:LCT-00000000:"
        self.calls = []
        self.acls = {}
        self.base_acl = "user::rwx\nuser:2000:r-x\nuser:2001:rwx\ngroup::r-x\nmask::rwx\nother::---"
        self.pwd = patch("titan.management_host.pwd.getpwnam", side_effect=self.account).start()
        self.runner = patch("titan.host.run", side_effect=self.command).start()

    def tearDown(self):
        patch.stopall()
        self.temp.cleanup()

    @staticmethod
    def account(name):
        uids = {"alice": 2000, "bob": 2001, "titan-files": 991, "root": 0, "titan": 990}
        if name not in uids:
            raise KeyError(name)
        return SimpleNamespace(pw_uid=uids[name], pw_gid=uids[name])

    def command(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if args[0] == "pdbedit" and "-L" in args:
            name = args[-1]
            return self.password_snapshot if name == "alice" else self.password_snapshot.replace("alice:2000:", "bob:2001:")
        if args[0] == "getfacl":
            fd = kwargs["pass_fds"][0]
            info = os.fstat(fd)
            return self.acls.get((info.st_dev, info.st_ino), self.base_acl)
        if args[0] == "setfacl" and "--set-file=-" in args:
            fd = kwargs["pass_fds"][0]
            info = os.fstat(fd)
            self.acls[(info.st_dev, info.st_ino)] = kwargs["input"].strip()
        return ""

    def test_legacy_accounts_are_enabled_and_system_accounts_protected(self):
        self.assertTrue(self.host.op_accounts()[0]["enabled"])
        for name in ("root", "titan", "titan-files", "foreign"):
            with self.assertRaises(Error):
                self.host.op_account_password(name, "long-enough-password")
        self.assertEqual(self.calls, [])

    def test_changed_uid_and_system_uid_are_rejected_before_mutation(self):
        for uid in (2005, 999):
            self.host.save("accounts", [{"name": "alice", "uid": uid}])
            with self.assertRaises(Error):
                self.host.op_account_set_enabled("alice", False)
        self.assertEqual(self.calls, [])

    def test_disabling_account_closes_smb_and_denies_file_access(self):
        self.host.op_account_set_enabled("alice", False)
        self.assertFalse(self.host.op_accounts()[0]["enabled"])
        self.assertIn((["smbpasswd", "-d", "alice"], {}), self.calls)
        self.assertTrue(any(args == ["smbcontrol", "smbd", "close-share", "documents"] for args, _ in self.calls))
        self.assertIn("valid users = bob", self.config.read_text())
        with patch("titan.host.subprocess.run") as worker:
            with self.assertRaises(Error) as result:
                self.host.op_file("alice", "documents", "read", "old.txt")
            self.assertEqual(result.exception.status, 403)
            worker.assert_not_called()

    def test_password_and_status_are_one_transaction_with_private_rollback(self):
        original = self.command
        failed = False
        rollback_seen = []
        def command(args, **kwargs):
            nonlocal failed
            if args == ["systemctl", "reload", "smbd"] and not failed:
                failed = True
                raise Error("Secret must not appear: " + self.password_snapshot)
            if args[0] == "pdbedit" and "-i" in args:
                snapshot = Path(args[2].removeprefix("smbpasswd:"))
                rollback_seen.append(snapshot)
                self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)
                self.assertEqual(snapshot.read_text(), self.password_snapshot + "\n")
            return original(args, **kwargs)
        self.runner.side_effect = command
        with self.assertRaises(Error) as result:
            self.host.op_account_update("alice", password="long-enough-password", enabled=False)
        self.assertNotIn(self.password_snapshot, str(result.exception))
        self.assertTrue(self.host.op_accounts()[0]["enabled"])
        self.assertEqual(len(rollback_seen), 1)
        self.assertFalse(rollback_seen[0].exists())
        self.assertTrue(any(args == ["smbpasswd", "-s", "alice"] for args, _ in self.calls))

    def test_account_removal_preserves_linux_uid_and_files(self):
        result = self.host.op_account_remove("alice")
        self.assertTrue(result["data_retained"])
        self.assertTrue(self.host.op_accounts()[0]["removed"])
        self.assertEqual((self.share / "old.txt").read_text(), "important data")
        self.assertFalse(any(args[0] == "userdel" for args, _ in self.calls))
        with self.assertRaises(Error):
            self.host.op_account_set_enabled("alice", True)

    def test_bad_password_or_status_has_no_host_effect(self):
        for params in ({"enabled": "false"}, {"password": "short"}, {"password": "long-enough\npassword"}):
            with self.assertRaises(Error):
                self.host.op_account_update("alice", **params)
        self.assertEqual(self.calls, [])

    def test_share_update_applies_existing_tree_without_following_symlinks(self):
        outside = self.root / "outside.txt"
        outside.write_text("outside")
        (self.share / "link.txt").symlink_to(outside)
        (self.share / "outside-dir").symlink_to(self.root, target_is_directory=True)
        self.host.op_share_update("documents", readers=["bob"], writers=["alice"])
        self.assertEqual(len(self.acls), 4)  # Root, subfolder and two regular files.
        self.assertNotIn((outside.stat().st_dev, outside.stat().st_ino), self.acls)
        for text in self.acls.values():
            self.assertIn("user:2000:rwX", text)
            self.assertIn("user:2001:r-X", text)
        directory_acl = self.acls[(self.share.stat().st_dev, self.share.stat().st_ino)]
        self.assertIn("default:user:2001:r-x", directory_acl)
        self.assertEqual(self.host.op_shares()[0]["writers"], ["alice"])
        self.assertIn("write list = alice", self.config.read_text())
        self.assertTrue(any(args == ["smbcontrol", "smbd", "close-share", "documents"] for args, _ in self.calls))

    def test_share_update_failure_restores_acl_and_samba_config(self):
        original = self.command
        failed = False
        def command(args, **kwargs):
            nonlocal failed
            if args[0] == "setfacl" and "--set-file=-" in args and len(self.acls) == 1 and not failed:
                failed = True
                raise Error("ACL change failed")
            return original(args, **kwargs)
        self.runner.side_effect = command
        with self.assertRaises(Error):
            self.host.op_share_update("documents", readers=[], writers=["alice"])
        self.assertEqual(set(self.acls.values()), {self.base_acl})
        self.assertEqual(self.host.op_shares()[0]["writers"], ["bob"])
        self.assertIn("write list = bob", self.config.read_text())

    def test_owner_permissions_also_follow_reduced_share_rights(self):
        text = self.host.acl_for_members(self.base_acl, ["bob"], ["alice"], True, owner_uid=2001)
        self.assertIn("user::r-X", text)
        self.assertIn("default:user::rwx", text)
        denied = self.host.acl_for_members(self.base_acl, [], ["alice"], False, owner_uid=2001)
        self.assertIn("user::---", denied)

    def test_empty_share_members_disable_share_and_remove_retains_data(self):
        self.host.op_share_update("documents", [], [])
        self.assertIn("available = no", self.config.read_text())
        self.host.op_share_remove("documents")
        self.assertEqual(self.host.op_shares(), [])
        self.assertTrue((self.share / "old.txt").is_file())
        self.assertNotIn("[documents]", self.config.read_text())

    def test_incomplete_acl_rollback_blocks_share_in_smb_and_file_manager(self):
        original = self.command
        writes = 0
        def command(args, **kwargs):
            nonlocal writes
            if args[0] == "setfacl" and "--set-file=-" in args:
                writes += 1
                if writes >= 2:
                    raise Error("ACL write/rollback failed")
            return original(args, **kwargs)
        self.runner.side_effect = command
        with self.assertRaises(Error) as result:
            self.host.op_share_update("documents", [], ["alice"])
        self.assertEqual(result.exception.status, 500)
        self.assertTrue(self.host.op_shares()[0]["blocked"])
        self.assertIn("available = no", self.config.read_text())
        with patch("titan.host.subprocess.run") as worker:
            with self.assertRaises(Error):
                self.host.op_file("alice", "documents", "read", "old.txt")
            worker.assert_not_called()

    def test_concurrent_account_change_cannot_reopen_suspended_acl_share(self):
        self.host.suspended_shares.add("documents")
        self.host.op_account_set_enabled("alice", False)
        self.assertIn("available = no", self.config.read_text())

    def test_share_path_symlink_and_unknown_or_disabled_member_are_rejected(self):
        alias = self.volume / "alias"
        alias.symlink_to(self.share, target_is_directory=True)
        with self.assertRaises(OSError):
            self.host.open_share_root(alias)
        with self.assertRaises(Error):
            self.host.share_members([], ["root"])
        self.host.save("accounts", [{"name": "alice", "uid": 2000, "enabled": False}])
        with self.assertRaises(Error):
            self.host.share_members(["alice"], [])

    def test_cross_share_copy_requires_destination_write_and_move_source_write(self):
        target = self.volume / "target"
        target.mkdir()
        self.host.save("shares", self.host.op_shares() + [{"name": "target", "path": str(target), "readers": [], "writers": ["alice"]}])
        with patch("titan.host.os.getgrouplist", return_value=[2000]), patch("titan.host.subprocess.run", return_value=SimpleNamespace(stdout='{"result":{"ok":true}}')) as worker:
            self.host.op_file("alice", "documents", "copy", "old.txt", destination="copy.txt", destination_share="target")
            request = json.loads(worker.call_args.kwargs["input"])
            self.assertEqual(request["root"], str(self.share))
            self.assertEqual(request["destination_root"], str(target))
            with self.assertRaises(Error):
                self.host.op_file("alice", "documents", "move", "old.txt", destination="copy.txt", destination_share="target")
            with self.assertRaises(Error):
                self.host.op_file("bob", "documents", "copy", "old.txt", destination="copy.txt", destination_share="target")

    def test_untrusted_worker_parameters_are_rejected(self):
        for arguments in ({"root": "/etc"}, {"destination_root": "/etc"}, {"uid": 0}, {"unexpected": True}):
            with patch("titan.host.subprocess.run") as worker:
                with self.assertRaises(Error):
                    self.host.op_file("alice", "documents", "list", **arguments)
                worker.assert_not_called()

    def test_share_config_hides_shares_from_nonmembers_and_inherits_acl(self):
        text = self.host.share_config_text(self.host.op_shares())
        self.assertIn("access based share enum = yes", text)
        self.assertIn("inherit acls = yes", text)
        self.assertIn("read only = yes", text)
        self.assertIn("valid users = alice bob", text)
        self.assertIn("write list = bob", text)
        self.assertNotIn("force user", text)
        self.assertNotIn("guest ok = yes", text)

    def test_smb_readiness_contains_only_flags_and_reports_disabled_passdb(self):
        original = self.command
        snapshot = self.password_snapshot + "\n" + self.password_snapshot.replace("alice:2000:", "bob:2001:").replace("[U          ]", "[DU         ]")
        self.runner.side_effect = lambda args, **kwargs: snapshot if args == ["pdbedit", "-L", "-w"] else original(args, **kwargs)
        accounts = self.host.op_accounts(smb_status=True)
        self.assertTrue(accounts[0]["smb_ready"])
        self.assertTrue(accounts[1]["smb_configured"])
        self.assertFalse(accounts[1]["smb_enabled"])
        self.assertFalse(accounts[1]["smb_ready"])
        self.assertNotIn("A" * 32, json.dumps(accounts))
        self.assertNotIn("B" * 32, json.dumps(accounts))

    def test_smb_readiness_handles_unavailable_passdb_without_exposing_errors(self):
        self.runner.side_effect = Error("private passdb contents " + self.password_snapshot)
        accounts = self.host.op_accounts(smb_status=True)
        self.assertIsNone(accounts[0]["smb_ready"])
        self.assertNotIn(self.password_snapshot, json.dumps(accounts))

    def test_legacy_account_link_copies_only_service_share_rights(self):
        self.host.save("shares", [{"name": "documents", "path": str(self.share), "readers": [], "writers": ["titan-files"]}])
        result = self.host.op_account_link("alice", "new-personal-password")
        self.assertEqual(result["system_user"], "alice")
        self.assertEqual(self.host.op_shares()[0]["writers"], ["alice", "titan-files"])
        self.assertTrue(any(args == ["smbpasswd", "-s", "alice"] for args, _ in self.calls))
        self.assertFalse(any(args[:3] == ["smbpasswd", "-s", "titan-files"] for args, _ in self.calls))

    def test_legacy_link_never_reopens_blocked_share_or_changes_other_members(self):
        self.host.save("shares", [{"name": "documents", "path": str(self.share), "readers": [], "writers": ["titan-files"], "blocked": True}])
        self.host.op_account_link("alice", "new-personal-password")
        self.assertEqual(self.host.op_shares()[0]["writers"], ["titan-files"])
        self.assertTrue(self.host.op_shares()[0]["blocked"])

    def test_legacy_link_preserves_explicit_personal_and_nonservice_share_rights(self):
        other = self.volume / "other"
        other.mkdir()
        shares = [{"name": "documents", "path": str(self.share), "readers": ["alice"], "writers": ["titan-files"]},
                  {"name": "other", "path": str(other), "readers": [], "writers": ["bob"]}]
        self.host.save("shares", shares)
        self.host.op_account_link("alice", "new-personal-password")
        self.assertEqual(self.host.op_shares(), shares)

    def test_legacy_link_refuses_disabled_or_unmanaged_linux_identity(self):
        self.host.save("accounts", [{"name": "alice", "uid": 2000, "enabled": False}])
        with self.assertRaises(Error): self.host.op_account_link("alice", "new-personal-password")
        self.assertEqual(self.calls, [])
        self.host.save("accounts", [])
        with self.assertRaises(Error): self.host.op_account_link("bob", "new-personal-password")
        self.assertFalse(any(args[0] == "useradd" for args, _ in self.calls))

    def test_edit_can_keep_or_reduce_disabled_membership_without_granting_new_access(self):
        self.host.save("accounts", [{"name": "alice", "uid": 2000, "enabled": False}, {"name": "bob", "uid": 2001, "enabled": True}])
        self.host.op_share_update("documents", ["alice"], ["bob"])
        self.assertEqual(self.host.op_shares()[0]["readers"], ["alice"])
        self.assertIn("valid users = bob", self.config.read_text())
        with self.assertRaises(Error): self.host.op_share_update("documents", [], ["alice", "bob"])
        with self.assertRaises(Error): self.host.op_share_create("another", ["alice"], ["bob"])
        self.host.op_share_update("documents", [], ["bob"])
        self.assertEqual(self.host.op_shares()[0]["readers"], [])

    def test_edit_drops_all_members_without_enabling_guests(self):
        self.host.op_share_update("documents", [], [])
        text = self.config.read_text()
        self.assertIn("available = no", text)
        self.assertIn("guest ok = no", text)
        self.assertNotIn("guest ok = yes", text)

    def test_access_reports_active_nic_zone_without_changing_firewall(self):
        calls = []
        def command(args, **kwargs):
            calls.append(args)
            if args[0] == "systemctl": return "active"
            if args[1] == "--get-default-zone": return "public"
            if args[1] == "--get-zone-of-interface=eth0": return "home"
            if args[-1] == "--list-services": return "ssh"
            if args[-1] == "--list-ports": return ""
            if args[-1] == "--get-target": return "default"
            raise AssertionError(args)
        with patch.object(self.host, "command", side_effect=command), patch.object(self.host, "_host_addresses", return_value=[{"address": "192.168.1.50", "family": 4, "interface": "eth0", "scope": "lan"}]):
            access = self.host.op_shares_access()
        self.assertTrue(access["service_active"])
        self.assertEqual(access["firewall"][0]["zone"], "home")
        self.assertFalse(access["firewall"][0]["samba_service_enabled"])
        self.assertIn("home", access["warnings"][0])
        self.assertFalse(any("--add" in option for args in calls for option in args))

    def test_access_does_not_claim_firewall_blocks_explicit_smb_port(self):
        def command(args, **kwargs):
            if args[0] == "systemctl": return "active"
            if args[1] == "--get-default-zone": return "public"
            if args[1] == "--get-zone-of-interface=eth0": raise Error("no zone")
            if args[-1] == "--list-services": return ""
            if args[-1] == "--list-ports": return "445/tcp"
            if args[-1] == "--get-target": return "default"
            raise AssertionError(args)
        with patch.object(self.host, "command", side_effect=command), patch.object(self.host, "_host_addresses", return_value=[{"address": "192.168.1.50", "family": 4, "interface": "eth0", "scope": "lan"}]):
            access = self.host.op_shares_access()
        self.assertEqual(access["firewall"][0]["zone"], "public")
        self.assertTrue(access["firewall"][0]["port_445_enabled"])
        self.assertEqual(access["warnings"], [])


if __name__ == "__main__":
    unittest.main()

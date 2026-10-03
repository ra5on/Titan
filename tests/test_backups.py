import contextlib
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock

from titan.backups import Backups, directory_fd, digest_file, external_path
from titan.config_restore import validate_config, restore
from titan.core import Error, Store, atomic_json, configuration_lock


class ExternalBackupTargetTests(unittest.TestCase):
    def setUp(self):
        self.host = Mock(share_root=Path('/var/srv/titan'), directory=Path('/var/lib/titan-agent'),
                         vm_root=Path('/var/lib/libvirt/images/titan'))
        self.host.op_shares.return_value = []
        self.selected = {'target': '/var/mnt/usb', 'source': '/dev/usb', 'fstype': 'xfs',
                         'maj:min': '8:2', 'options': 'rw'}
        self.system = {'target': '/', 'source': '/dev/system', 'fstype': 'xfs', 'maj:min': '8:1'}
        self.run = Mock(side_effect=lambda args: json.dumps({'filesystems': [
            self.system if args[3] == '/' else self.selected]}))
        self.backups = Backups(self.host, self.run)

    def validate(self, path):
        with patch('titan.backups.directory_fd', return_value=contextlib.nullcontext(42)) as opened, \
                patch('titan.backups.os.fstat', return_value=Mock(st_dev=9, st_ino=17)), \
                patch('titan.backups.os.stat', return_value=Mock(st_dev=1)):
            result = self.backups.validate_target(path)
            opened.assert_called_once_with(result)
            return result

    def test_coreos_canonical_external_targets_accept_separate_mounted_disks(self):
        for root in ('/var/mnt', '/var/media'):
            self.selected['target'] = root + '/usb'
            with self.subTest(root=root):
                self.assertEqual(self.validate(root + '/usb/backups'), Path(root + '/usb/backups'))

    def test_only_known_coreos_root_alias_is_canonicalized(self):
        with patch.object(Path, 'is_symlink', return_value=True), \
                patch('titan.backups.os.readlink', return_value='var/mnt'):
            self.assertEqual(self.validate('/mnt/usb/backups'), Path('/var/mnt/usb/backups'))
        with patch.object(Path, 'is_symlink', return_value=True), \
                patch('titan.backups.os.readlink', return_value='/etc'):
            with self.assertRaises(Error):
                external_path('/mnt/usb')
        with patch.object(Path, 'is_symlink', return_value=True), \
                patch('titan.backups.os.readlink', side_effect=OSError('link changed')):
            with self.assertRaises(Error):
                external_path('/mnt/usb')
        for path in (None, [], '', '/var/mnt/a\x00b'):
            with self.subTest(path=path), self.assertRaises(Error):
                external_path(path)

    def test_system_filesystem_readonly_and_unmounted_targets_remain_rejected(self):
        for change in ({'target': '/var'}, {'source': '/dev/system'},
                       {'maj:min': '8:1'}, {'options': 'ro'}, {'fstype': 'tmpfs'}):
            with self.subTest(change=change):
                original = self.selected.copy()
                self.selected.update(change)
                with self.assertRaises(Error):
                    self.validate('/var/mnt/usb')
                self.selected = original
        for path in ('/var/lib/titan-agent', '/var/mnt/../lib', 'var/mnt/usb'):
            with self.subTest(path=path), self.assertRaises(Error):
                self.backups.validate_target(path)

    def test_nested_directory_symlink_is_still_refused(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / 'real').mkdir()
            (path / 'link').symlink_to(path / 'real', target_is_directory=True)
            with self.assertRaises(Error), directory_fd(path / 'link'):
                pass


class FakeHost:
    def __init__(self, root):
        self.directory = root / "agent"
        self.share_root = root / "shares"
        self.vm_root = root / "vms"
        self.samba_config = root / "samba.conf"
        self.account_lock = threading.RLock()
        self.volume_manager = Mock()
        self.volume_manager.required_path.return_value = None
        self.directory.mkdir()
        self.share_root.mkdir()
        self.vm_root.mkdir()
        share = self.share_root / "data"
        share.mkdir()
        (share / "hello.txt").write_text("valuable file")
        (share / "nested").mkdir()
        (share / "nested" / "other.txt").write_text("nested value")
        self.save("shares", [{"name": "data", "path": str(share), "readers": [], "writers": ["titan-files"], "dataset": None}])

    def validate_vm_disk_path(self, name, disk):
        if Path(disk) != self.vm_root / (name + ".qcow2"):
            raise Error("VM-Laufwerk liegt außerhalb eines verwalteten Speichers.")
        return {"device": os.stat(Path(disk).parent).st_dev}

    def load(self, name, default):
        path = self.directory / (name + ".json")
        return json.loads(path.read_text()) if path.exists() else default

    def save(self, name, value):
        atomic_json(self.directory / (name + ".json"), value)

    def op_shares(self):
        return self.load("shares", [])

    def op_accounts(self):
        return self.load("accounts", [])

    def samba_snapshot(self, name):
        return f"{name}:1001:{'0' * 32}:{'1' * 32}:[U          ]:LCT-00000001:\n"

    def restore_samba_snapshot(self, name, text):
        pass

    def share_acl_transaction(self, record, readers, writers, operation):
        return operation()

    def share_config_text(self, shares, accounts=None):
        return "\n".join("[" + item["name"] + "]" for item in shares)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.host = FakeHost(self.root)
        self.target = self.root / "external"
        self.target.mkdir()
        self.store = Store(self.root / "web")
        self.store.setup("admin", "long-enough-password")
        self.store.login("admin", "long-enough-password")
        self.run = Mock(return_value='{"format":"qcow2"}')
        self.backups = Backups(self.host, self.run, self.store.path)
        info = self.target.stat()
        self.backups._target_identity = (info.st_dev, info.st_ino)
        self.target_mock = patch.object(self.backups, "validate_target", return_value=self.target)
        self.target_mock.start()
        self.backups.save_settings({"target": str(self.target), "shares": ["data"], "include_config": True})

    def tearDown(self):
        self.target_mock.stop()
        self.temporary.cleanup()

    def test_real_backup_verify_restore_and_no_overwrite(self):
        backup = self.backups.create()
        self.assertTrue(self.backups.verify(backup["id"])["ok"])
        self.backups.restore(backup["id"], "data", "restore-one")
        path = self.host.share_root / "data" / "restore-one" / "data"
        self.assertEqual((path / "hello.txt").read_text(), "valuable file")
        self.assertEqual((path / "nested" / "other.txt").read_text(), "nested value")
        with self.assertRaises(Error):
            self.backups.restore(backup["id"], "data", "restore-one")
        self.assertEqual((self.host.share_root / "data" / "hello.txt").read_text(), "valuable file")

    def test_unmounted_source_volume_aborts_backup_without_an_archive(self):
        self.host.volume_manager.required_path.side_effect = Error("Volume nicht eingehängt", 503)
        with self.assertRaises(Error):
            self.backups.create(include_config=False)
        self.assertFalse(self.backups.state()["last"]["ok"])
        self.assertEqual(self.backups.list(), [])

    def test_restore_refuses_volume_disappearance_before_creating_folder(self):
        backup = self.backups.create(include_config=False)
        self.host.volume_manager.required_path.side_effect = Error("Volume nicht eingehängt", 503)
        with self.assertRaises(Error):
            self.backups.restore(backup["id"], "data", "missing-volume")
        self.assertFalse((self.host.share_root / "data" / "missing-volume").exists())

    def test_mount_device_mismatch_blocks_root_data_access(self):
        backup = self.backups.create(include_config=False)
        self.host.volume_manager.required_path.return_value = os.stat(self.host.share_root).st_dev + 1
        with self.assertRaises(Error):
            self.backups.create(include_config=False)
        with self.assertRaises(Error):
            self.backups.restore(backup["id"], "data", "wrong-device")
        self.assertFalse((self.host.share_root / "data" / "wrong-device").exists())

    def test_config_snapshot_is_consistent_and_revoke_sessions(self):
        backup = self.backups.create()
        exported = Path(self.backups.export_config(backup["id"])["path"])
        with contextlib.closing(sqlite3.connect(exported / "titan.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sessions").fetchone()[0], 0)
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sessions").fetchone()[0], 1)
        self.assertEqual(self.backups.read_config(backup["id"])["users"][0]["name"], "admin")
        self.assertEqual((exported / "config.json").stat().st_mode & 0o777, 0o600)

    def test_checksum_damage_refuses_restore_before_creating_destination(self):
        backup = self.backups.create()
        path = self.backups.namespace() / backup["id"] / "archive.tar.gz"
        with path.open("r+b") as stream:
            stream.seek(20)
            stream.write(b"broken")
        with self.assertRaises(Error):
            self.backups.restore(backup["id"], "data", "safe-folder")
        self.assertFalse((self.host.share_root / "data" / "safe-folder").exists())

    def test_symlink_source_refused_and_failed_state_persisted(self):
        (self.host.share_root / "data" / "link").symlink_to("/etc/passwd")
        with self.assertRaises(Error):
            self.backups.create()
        self.assertFalse(self.backups.state()["last"]["ok"])
        self.assertEqual(self.backups.list(), [])

    def test_unsafe_archive_members_refused_even_with_matching_hash(self):
        backup = self.backups.create()
        base = self.backups.namespace() / backup["id"]
        for name, kind in (("../outside", tarfile.REGTYPE), ("shares/data/link", tarfile.SYMTYPE), ("config/evil.sh", tarfile.REGTYPE)):
            with self.subTest(name=name):
                with tarfile.open(base / "archive.tar.gz", "w:gz") as archive:
                    member = tarfile.TarInfo(name)
                    member.type, member.size = kind, 0
                    member.linkname = "/etc/passwd" if kind == tarfile.SYMTYPE else ""
                    archive.addfile(member)
                backup.update({"entries": 1, "unpacked_bytes": 0,
                               "bytes": (base / "archive.tar.gz").stat().st_size,
                               "sha256": digest_file(base / "archive.tar.gz")})
                atomic_json(base / "manifest.json", backup)
                with self.assertRaises(Error):
                    self.backups.verify(backup["id"])

    def test_retention_only_valid_own_backup_directories(self):
        self.backups.save_settings({"retention": 1, "include_config": False})
        first = self.backups.create()
        second = self.backups.create()
        base = self.backups.namespace()
        self.assertFalse((base / first["id"]).exists())
        self.assertTrue((base / second["id"]).exists())
        unknown = base / "other-user-backup"
        unknown.mkdir()
        (unknown / "important").write_text("keep")
        invalid = base / "b-20000101T000000-123456789abc"
        invalid.mkdir()
        (invalid / "archive.tar.gz").write_text("not a backup")
        self.backups.retention()
        self.assertTrue((unknown / "important").exists())
        self.assertTrue(invalid.exists())

    def test_missing_mount_never_falls_back_to_root_disk(self):
        self.target_mock.stop()
        with self.assertRaises(Error):
            self.backups.validate_target("/tmp")
        self.run.return_value = '{"filesystems":[{"target":"/","source":"/dev/root","fstype":"ext4","maj:min":"8:1"}]}'
        with self.assertRaises(Error):
            self.backups.validate_target("/mnt")
        self.target_mock.start()

    def test_mount_disappearance_fails_scheduled_backup_and_no_retry_loop(self):
        self.backups.save_settings({"auto_backup": True, "window_hour": 0})
        now = datetime.datetime(2026, 9, 30, 10).timestamp()
        with patch.object(self.backups, "validate_target", side_effect=Error("Ziel nicht eingehängt")):
            result = self.backups.scheduled(now)
            self.assertIn("error", result)
            self.assertFalse(self.backups.scheduled(now)["due"])
            self.assertFalse(self.backups.state()["last"]["ok"])

    def test_weekly_schedule_respects_day_and_hour(self):
        self.backups.save_settings({"auto_backup": True, "interval": "weekly", "window_day": 2, "window_hour": 3})
        self.assertFalse(self.backups.due(datetime.datetime(2026, 9, 30, 2).timestamp()))
        self.assertTrue(self.backups.due(datetime.datetime(2026, 9, 30, 3).timestamp()))
        self.assertFalse(self.backups.due(datetime.datetime(2026, 10, 1, 3).timestamp()))

    def test_settings_validation_and_arbitrary_backup_identifiers(self):
        for value in ({"auto_backup": "yes"}, {"retention": 0}, {"window_hour": 25}, {"shares": [["data"]]}, {"shares": ["unknown"]}, {"unknown": True}):
            with self.assertRaises(Error):
                self.backups.save_settings(value)
        for value in ("../../etc", "/etc", "b-bad"):
            with self.assertRaises(Error):
                self.backups.verify(value)

    def test_namespace_symlink_refuses_outside_write(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.target / ".titan-backups").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(Error):
            self.backups.create()
        self.assertEqual(list(outside.iterdir()), [])

    def test_vm_backup_roundtrip_and_backing_chain_rejection(self):
        disk = self.host.vm_root / "test.qcow2"
        disk.write_bytes(b"a standalone disk")
        backup = self.backups.create_vm("test", "<domain><name>titan-test</name></domain>", disk)
        self.assertEqual(self.backups.verified_vm(backup["id"])["vm_name"], "test")
        restored = Path(self.backups.restore_vm_files(backup["id"], "restored"))
        self.assertEqual(restored.read_bytes(), disk.read_bytes())
        with self.assertRaises(Error):
            self.backups.restore_vm_files(backup["id"], "restored")
        self.run.return_value = '{"format":"qcow2","backing-filename":"/etc/passwd"}'
        with self.assertRaises(Error):
            self.backups.create_vm("test", "<domain/>", disk)

    def test_uefi_vars_backup_roundtrip_and_symlink_rejection(self):
        from types import SimpleNamespace
        disk = self.host.vm_root / 'test.qcow2'
        disk.write_bytes(b'standalone disk')
        self.host.vm_nvram_path = lambda name: self.root / (name + '_VARS.fd')
        original = self.host.vm_nvram_path('test')
        original.write_bytes(b'guest persistent boot variables')
        xml = '<domain><name>titan-test</name><os firmware="efi"><nvram>' + str(original) + '</nvram></os></domain>'
        backup = self.backups.create_vm('test', xml, disk)
        with patch('titan.backups.pwd.getpwnam', return_value=SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())):
            self.assertTrue(self.backups.restore_vm_nvram(backup['id'], 'restored'))
        self.assertEqual(self.host.vm_nvram_path('restored').read_bytes(), original.read_bytes())
        with patch('titan.backups.pwd.getpwnam', return_value=SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())), self.assertRaises((Error, FileExistsError)):
            self.backups.restore_vm_nvram(backup['id'], 'restored')
        original.unlink()
        original.symlink_to(self.host.vm_nvram_path('restored'))
        with self.assertRaises((Error, OSError)): self.backups.create_vm('test', xml, disk)

    def test_config_restore_changes_settings_and_rolls_back_on_failure(self):
        self.store.save_settings({"hostname": "old"})
        backup = self.backups.create()
        data = self.backups.read_config(backup["id"])
        self.store.save_settings({"hostname": "new"})
        result = restore(self.host, data, self.store.path, Mock())
        self.assertTrue(result["ok"])
        self.assertEqual(self.store.settings()["hostname"], "old")
        self.assertEqual(self.store.jobs(), [])
        failing = Mock(side_effect=lambda args: (_ for _ in ()).throw(RuntimeError("failed")) if args[0] == "testparm" else "")
        self.store.save_settings({"hostname": "keep-after-failure"})
        with self.assertRaises(Error):
            restore(self.host, data, self.store.path, failing)
        self.assertEqual(self.store.settings()["hostname"], "keep-after-failure")

    def test_config_restore_confirmation_and_fixed_scheduler(self):
        backup = self.backups.create()
        with self.assertRaises(Error):
            self.backups.restore_config(backup["id"], "wrong")
        response = self.backups.restore_config(backup["id"], backup["id"])
        self.assertTrue(response["scheduled"])
        args = self.run.call_args.args[0]
        self.assertEqual(args[0], "systemd-run")
        self.assertIn("titan.config_restore", args)
        self.assertTrue((self.host.directory / "config-restore.lock").exists())

    def test_config_restore_rejects_foreign_uid_and_unsafe_share_path(self):
        backup = self.backups.create()
        data = self.backups.read_config(backup["id"])
        data["agent"]["accounts"] = [{"name": "someone", "uid": 0, "enabled": True}]
        with self.assertRaises(Error):
            validate_config(self.host, data)
        data["agent"]["accounts"] = []
        data["agent"]["shares"][0]["path"] = "/etc"
        with self.assertRaises(Error):
            validate_config(self.host, data)

    def test_samba_credentials_roundtrip_and_same_uid_validation(self):
        self.host.save("accounts", [{"name": "alice", "uid": 1001, "enabled": True}])
        backup = self.backups.create()
        data = self.backups.read_config(backup["id"])
        self.assertEqual(len(data["samba"]), 1)
        account = Mock(pw_uid=1001)
        with patch("titan.config_restore.pwd.getpwnam", return_value=account):
            self.assertIs(validate_config(self.host, data), data)
            with patch.object(self.host, "restore_samba_snapshot") as importer:
                restore(self.host, data, self.store.path, Mock())
                self.assertEqual(importer.call_args.args[0], "alice")
                self.assertEqual(importer.call_args.args[1], data["samba"][0] + "\n")
            data["samba"] = []
            with self.assertRaises(Error):
                validate_config(self.host, data)
        with patch("titan.config_restore.pwd.getpwnam", return_value=Mock(pw_uid=2001)):
            with self.assertRaises(Error):
                validate_config(self.host, data)

    def test_failed_acl_rollback_leaves_smb_stopped_and_recovery_copy(self):
        backup = self.backups.create()
        data = self.backups.read_config(backup["id"])
        runner = Mock()
        with patch.object(self.host, "share_acl_transaction", side_effect=Error("ACL konnte nicht zurückgesetzt werden", 500)):
            with self.assertRaises(Error):
                restore(self.host, data, self.store.path, runner)
        commands = [item.args[0] for item in runner.call_args_list]
        self.assertIn(["systemctl", "stop", "smbd.service"], commands)
        self.assertNotIn(["systemctl", "start", "smbd.service"], commands)
        self.assertTrue(list(self.host.directory.glob("restore-recovery-*/recovery.json")))

    def test_restore_applies_target_acl_and_rejects_blocked_share(self):
        backup = self.backups.create()
        with patch.object(self.host, "share_acl_transaction", wraps=self.host.share_acl_transaction) as acl:
            self.backups.restore(backup["id"], "data", "restored")
            self.assertEqual(acl.call_args.args[0]["path"], str(self.host.share_root / "data" / "restored"))
            self.assertEqual(acl.call_args.args[2], ["titan-files"])
        shares = self.host.op_shares()
        shares[0]["blocked"] = True
        self.host.save("shares", shares)
        with self.assertRaises(Error):
            self.backups.restore(backup["id"], "data", "another")

    def test_smb_start_failure_still_attempts_web_restart(self):
        backup = self.backups.create()
        data = self.backups.read_config(backup["id"])
        def runner(args):
            if args == ["systemctl", "start", "smbd.service"]:
                raise Error("SMB konnte nicht starten")
        command = Mock(side_effect=runner)
        with self.assertRaises(Error):
            restore(self.host, data, self.store.path, command)
        self.assertIn(["systemctl", "start", "titan-web.service"], [call.args[0] for call in command.call_args_list])

    def test_stop_failure_before_snapshot_attempts_web_restart(self):
        backup = self.backups.create()
        data = self.backups.read_config(backup["id"])
        def runner(args):
            if args == ["systemctl", "stop", "titan-web.service"]:
                raise Error("Web konnte nicht gestoppt werden")
        command = Mock(side_effect=runner)
        with self.assertRaises(Error):
            restore(self.host, data, self.store.path, command)
        self.assertIn(["systemctl", "start", "titan-web.service"], [call.args[0] for call in command.call_args_list])

    def test_config_restore_keeps_newer_app_installations(self):
        backup = self.backups.create()
        data = self.backups.read_config(backup["id"])
        app = {"id": "newapp", "port": 8080, "data": str(self.host.share_root / "data"), "scheme": "http"}
        self.host.save("apps", [app])
        restore(self.host, data, self.store.path, Mock())
        self.assertEqual(self.host.load("apps", []), [app])

    def test_config_snapshot_waits_until_web_and_samba_account_commit_finishes(self):
        self.host.save("accounts", [{"name": "alice", "uid": 1001, "enabled": True}])
        attempted, acquired, complete = threading.Event(), threading.Event(), threading.Event()
        result = {}
        @contextlib.contextmanager
        def observed_lock(directory):
            attempted.set()
            with configuration_lock(directory):
                acquired.set()
                yield
        def snapshot():
            try:
                result["backup"] = self.backups.create(shares=[])
            except Exception as exc:
                result["error"] = exc
            finally:
                complete.set()
        with patch("titan.backups.configuration_lock", observed_lock):
            with configuration_lock(self.store.directory):
                thread = threading.Thread(target=snapshot)
                thread.start()
                self.assertTrue(attempted.wait(2))
                self.assertFalse(acquired.is_set())
                # Model the gap after Samba RPC succeeds and before SQL commits.
                self.store.update_user("admin", password="a-new-long-password")
                new_hash = self.store.user_record("admin")["password"]
            self.assertTrue(complete.wait(3))
            thread.join()
        self.assertNotIn("error", result)
        exported = self.backups.read_config(result["backup"]["id"])
        self.assertEqual(exported["users"][0]["password"], new_hash)
        self.assertEqual(len(exported["samba"]), 1)


if __name__ == "__main__":
    unittest.main()

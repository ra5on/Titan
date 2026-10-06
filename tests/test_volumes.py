import contextlib
import copy
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from titan.core import Error
from titan.host import Host
from titan.volumes import Volumes


class VolumeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.share_root = self.root / "data"
        self.share_root.mkdir()
        self.share_root.chmod(0o755)
        self.fstab = self.root / "fstab"
        self.fstab.write_text("# Existing boot volume\nUUID=system / ext4 defaults 0 1\n")
        self.fstab.chmod(0o644)
        self.host = Host(self.root / "agent", self.share_root, self.root / "vms", self.root / "smb.conf")
        self.calls = []
        self.mounted = False
        self.formatted = None
        self.fail_mount = False
        self.disk = {"name": "/dev/sdb", "type": "disk", "size": 1024**3, "fstype": None,
                     "uuid": None, "ro": False, "maj:min": "8:16", "mountpoints": []}
        self.manager = Volumes(self.host, self.command, self.fstab, os.geteuid())
        self.host._volumes = self.manager
        self.host.disks = lambda: [copy.deepcopy(self.disk)]

    def tearDown(self):
        for path in self.share_root.rglob("*"):
            if path.is_dir() and not path.is_symlink(): path.chmod(0o755)
        self.temporary.cleanup()

    def command(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if args[0].startswith("mkfs."):
            fs = args[0][5:]
            value = args[args.index("-U") + 1] if fs == "ext4" else args[args.index("-m") + 1].split("=", 1)[1]
            self.disk.update(fstype=fs, uuid=value)
            self.formatted = value
        if args[0] == "blkid": return f"TYPE={self.disk['fstype']}\nUUID={self.disk['uuid']}"
        if args[0] == "mount":
            if self.fail_mount: raise Error("Simulated mount failure")
            self.mounted = True
        if args[0] == "findmnt":
            entries = []
            if self.mounted:
                name = self.host.load("volumes", [])[0]["name"]
                value = os.stat(self.share_root).st_dev
                entries = [{"target": str(self.manager.root / name), "fstype": self.disk["fstype"],
                            "uuid": self.disk["uuid"], "maj:min": f"{os.major(value)}:{os.minor(value)}"}]
            return json.dumps({"filesystems": entries})
        if args[0] == "wipefs": return '{"signatures": []}'
        return ""

    @contextlib.contextmanager
    def safe_format_simulation(self):
        probe = self.root / "dummy-device"
        probe.touch()
        original_open = os.open
        original_mkdir = os.mkdir
        def mkdir(path, mode=0o777, **kwargs):
            return original_mkdir(path, 0o700 if mode==0 else mode, **kwargs)
        def open_file(path, flags, *args, **kwargs):
            return original_open(probe if str(path) == "/dev/sdb" else path, flags, *args, **kwargs)
        # Formatter calls are captured by command(); no external command is executed.
        with patch.object(self.manager, "blank_disk", return_value=0), \
                patch("titan.volumes.os.mkdir", side_effect=mkdir), \
                patch("titan.volumes.os.open", side_effect=open_file), \
                patch("titan.volumes.os.fchmod") as chmod, \
                patch("titan.volumes.stat.S_ISBLK", return_value=True), \
                patch("titan.volumes.shutil.which", return_value="/mock/tool"):
            yield chmod

    def test_ext4_default_create_uuid_mount_and_idempotent_persistence(self):
        with self.safe_format_simulation() as chmod:
            result = self.manager.create("documents", "/dev/sdb", confirmation_name="documents", confirmation_disk="/dev/sdb")
            self.assertTrue(result["ok"])
            self.assertTrue(any(call.args[1] == 0 for call in chmod.call_args_list))
            before = self.fstab.read_text()
            self.manager.mount("documents")
        self.assertEqual(self.fstab.read_text(), before)
        self.assertIn("UUID=system / ext4 defaults 0 1", before)
        self.assertIn("UUID=" + self.formatted, before)
        self.assertIn("defaults,nofail,nodev,nosuid", before)
        self.assertEqual(before.count("# Titan volume documents"), 1)
        formats = [args for args, _ in self.calls if args[0].startswith("mkfs.")]
        self.assertEqual(len(formats), 1)
        self.assertEqual(formats[0][0], "mkfs.ext4")
        self.assertTrue(formats[0][-1].startswith("/proc/self/fd/"))
        self.assertNotIn("-F", formats[0]); self.assertNotIn("-f", formats[0])
        self.assertEqual(self.host.load("volumes", [])[0]["phase"], "ready")

    def test_dashboard_sums_mounted_volumes_and_reports_offline_storage_as_unavailable(self):
        volumes = [{"mounted": True, "total": 1000, "used": 100},
                   {"mounted": True, "total": 2000, "used": 400},
                   {"mounted": False, "total": 9000, "used": 8000}]
        with patch.object(self.host, "service_status", return_value={}), \
                patch.object(self.manager, "records", return_value=[{"name": "documents"}]), \
                patch.object(self.manager, "inventory", return_value={"volumes": volumes}), \
                patch("titan.host.shutil.disk_usage") as fallback:
            self.assertEqual(self.host.op_status()["storage"], {"total": 3000, "used": 500, "scope": "data"})
            fallback.assert_not_called()
            for volume in volumes: volume["mounted"] = False
            offline = self.host.op_status()
            self.assertEqual(offline["storage"], {"total": None, "used": None})
            self.assertIn("nicht eingehängt", offline["storage_error"])
            fallback.assert_not_called()

    def test_xfs_uses_safe_short_label_no_force_and_xfs_fstab_pass(self):
        name = "verylongnameforavolumelabel"
        with self.safe_format_simulation():
            self.manager.create(name, "/dev/sdb", "xfs", name, "/dev/sdb")
        command = next(args for args, _ in self.calls if args[0] == "mkfs.xfs")
        self.assertLessEqual(len(command[command.index("-L") + 1]), 12)
        self.assertNotIn("-f", command)
        self.assertIn(" xfs defaults,nofail,nodev,nosuid 0 0", self.fstab.read_text())

    def test_mount_failure_is_visible_and_fstab_addition_is_rolled_back(self):
        self.fail_mount = True
        before = self.fstab.read_text()
        with self.safe_format_simulation(), self.assertRaises(Error):
            self.manager.create("documents", "/dev/sdb", "ext4", "documents", "/dev/sdb")
        self.assertEqual(self.fstab.read_text(), before)
        record = self.host.load("volumes", [])[0]
        self.assertEqual(record["phase"], "failed")
        self.assertIn("mount failure", record["error"])
        inventory = self.manager.inventory()["volumes"][0]
        self.assertFalse(inventory["mounted"])
        with self.assertRaises(Error): self.manager.require("documents")

    def test_wrong_confirmation_or_missing_tool_never_formats(self):
        with patch("titan.volumes.shutil.which", return_value="/mock/tool"):
            for fields in (("bad", "/dev/sdb"), ("documents", "/dev/sda")):
                with self.assertRaises(Error): self.manager.create("documents", "/dev/sdb", "ext4", *fields)
        with patch("titan.volumes.shutil.which", return_value=None), self.assertRaises(Error):
            self.manager.create("documents", "/dev/sdb", "ext4", "documents", "/dev/sdb")
        self.assertEqual(self.calls, [])

    def test_used_partitioned_read_only_virtual_and_unknown_disks_are_rejected(self):
        variants = [{"fstype": "ext4"}, {"children": [{"name": "/dev/sdb1"}]}, {"mountpoints": ["/"]},
                    {"ro": True}, {"ro": None}, {"type": "loop"}, {"size": 1}]
        for changes in variants:
            with self.subTest(changes=changes):
                old = dict(self.disk);self.disk.update(changes)
                with self.assertRaises(Error): self.manager.blank_disk("/dev/sdb", "ext4")
                self.disk = old
        for path in ("/dev/sda", "/dev/sdb1", "/dev/loop0", "/dev/disk/by-id/test", "--help"):
            with self.assertRaises(Error): self.manager.blank_disk(path, "ext4")
        self.assertFalse(any(args[0].startswith("mkfs.") for args, _ in self.calls))

    def test_signature_and_holder_checks_fail_closed(self):
        block = SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8,16))
        original_stat = os.stat
        def device_stat(path, *args, **kwargs):
            return block if str(path) == "/dev/sdb" else original_stat(path, *args, **kwargs)
        with patch("titan.volumes.os.stat", side_effect=device_stat), \
                patch("titan.volumes.Path.is_dir", return_value=True), \
                patch("titan.volumes.Path.iterdir", return_value=iter([Path("dm-0")])):
            with self.assertRaises(Error): self.manager.blank_disk("/dev/sdb", "ext4")
        with patch("titan.volumes.os.stat", side_effect=device_stat), \
                patch("titan.volumes.Path.is_dir", return_value=True), \
                patch("titan.volumes.Path.iterdir", return_value=iter([])), \
                patch("titan.volumes.Path.read_text", return_value="Filename Type Size Used Priority\n"):
            self.manager.run = lambda args, **kw: '{"signatures": [{"type": "gpt"}]}' if args[0] == "wipefs" else '{"filesystems": []}'
            with self.assertRaises(Error): self.manager.blank_disk("/dev/sdb", "ext4")

    def test_fstab_collision_and_symlinks_refused_before_format(self):
        record = {"name":"documents","filesystem":"ext4","uuid":"12345678-1234-1234-1234-123456789abc"}
        self.fstab.write_text("/dev/sdz " + str(self.manager.root / "documents") + " ext4 defaults 0 2\n")
        with self.assertRaises(Error): self.manager.persist(record, dry_run=True)
        self.fstab.unlink();self.fstab.symlink_to(self.root / "other")
        with self.assertRaises(OSError): self.manager.persist(record, dry_run=True)
        self.assertEqual(self.calls, [])

    def test_mount_loss_blocks_share_open_and_wrong_filesystem_is_rejected(self):
        with self.safe_format_simulation(): self.manager.create("documents", "/dev/sdb", "ext4", "documents", "/dev/sdb")
        self.mounted = False
        with self.assertRaises(Error): self.host.open_share_root(self.manager.root / "documents")
        self.mounted = True;self.disk["uuid"] = "12345678-1234-1234-1234-123456789abc"
        with self.assertRaises(Error): self.manager.require("documents")

    def test_duplicate_uuid_or_occupied_mountpoint_never_mounts(self):
        with self.safe_format_simulation(): self.manager.create("documents", "/dev/sdb", "ext4", "documents", "/dev/sdb")
        self.mounted = False
        self.host.disks=lambda:[dict(self.disk),dict(self.disk,name="/dev/sdc")]
        self.calls=[]
        with self.safe_format_simulation(), self.assertRaises(Error): self.manager.mount("documents")
        self.assertFalse(any(args[0] == "mount" for args,_ in self.calls))

    def test_successful_format_and_failed_probe_retains_uuid_for_safe_recovery(self):
        run = self.command
        def failed_probe(args, **kwargs):
            if args[0] == "blkid": raise Error("Probe unavailable")
            return run(args, **kwargs)
        self.manager.run = failed_probe
        with self.safe_format_simulation(), self.assertRaises(Error):
            self.manager.create("documents", "/dev/sdb", "ext4", "documents", "/dev/sdb")
        saved = self.host.load("volumes", [])[0]
        self.assertEqual(saved["phase"], "verify_failed")
        self.assertEqual(saved["uuid"], self.formatted)
        self.manager.run = self.command
        with self.safe_format_simulation(): self.manager.mount("documents")
        self.assertEqual(self.host.load("volumes", [])[0]["phase"], "ready")
        self.assertEqual(sum(args[0].startswith("mkfs.") for args,_ in self.calls), 1)
        with self.safe_format_simulation(), self.assertRaises(Error):
            self.manager.create("documents", "/dev/sdb", "ext4", "documents", "/dev/sdb")

    def test_second_device_check_cannot_validate_another_disk_for_pinned_fd(self):
        with self.safe_format_simulation(), patch.object(self.manager, "blank_disk", side_effect=[0,123]), self.assertRaises(Error):
            self.manager.create("documents", "/dev/sdb", "ext4", "documents", "/dev/sdb")
        self.assertFalse(any(args[0].startswith("mkfs.") for args,_ in self.calls))

    def test_existing_volume_apps_cannot_start_update_or_restart_backup_when_unmounted(self):
        with self.safe_format_simulation(): self.manager.create("documents", "/dev/sdb", "ext4", "documents", "/dev/sdb")
        data = self.manager.root / "documents" / "shares" / "movies"
        data.mkdir(parents=True)
        config = self.host.directory / "apps" / "jellyfin"
        config.mkdir(parents=True)
        (config / "compose.json").write_text(json.dumps({"services":{"jellyfin":{"volumes":[]}}}))
        self.host.save("apps", [{"id":"jellyfin","data":str(data)}])
        self.mounted = False
        with patch("titan.host.run") as command:
            for action in ("start", "update", "backup"):
                with self.assertRaises(Error): self.host.op_app_action("jellyfin", action)
            self.assertFalse(any(call.args[0][0] == "docker" for call in command.call_args_list))

    def test_config_restore_requires_the_same_known_mounted_volume(self):
        from titan.config_restore import validate_config
        with self.safe_format_simulation(): self.manager.create("documents", "/dev/sdb", "ext4", "documents", "/dev/sdb")
        path = self.manager.share_path("documents", "letters")
        data = {"schema":1,"users":[{"name":"admin","system_user":"titan-files","password":"a"*32+":"+"b"*128,"role":"admin","enabled":1}],
                "config":{},"agent":{"accounts":[],"apps":[],"shares":[{"name":"letters","path":str(path),"readers":[],"writers":["titan-files"],"volume":"documents"}]},"samba":[]}
        self.assertIs(validate_config(self.host,data),data)
        self.mounted = False
        with self.assertRaises(Error): validate_config(self.host,data)

    def test_demo_volume_shares_and_files_are_isolated_and_mount_required(self):
        from titan.demo import Demo
        demo = Demo(self.root / "demo")
        try:
            fallback_storage = demo.call("status")["storage"]
            demo.call("volume_create", name="documents", disk="/dev/sdc", confirmation_name="documents", confirmation_disk="/dev/sdc")
            self.assertEqual(demo.call("status")["storage"], {key: demo.volume_records[0][key] for key in ("total", "used")})
            demo.call("share_create", name="letters", volume="documents", readers=[], writers=["titan-files"])
            demo.call("file", share="letters", action="mkdir", path="Private")
            demo.volume_records[0]["mounted"] = False
            self.assertEqual(demo.call("status")["storage"], fallback_storage)
            with self.assertRaises(Error): demo.call("file", share="letters", action="list")
            demo.call("volume_mount", name="documents")
            self.assertEqual(demo.call("file", share="letters", action="list")["entries"][0]["name"],"Private")
            self.assertFalse(Path("/srv/titan/volumes/documents").exists())
        finally: demo._temporary.cleanup()


if __name__ == "__main__": unittest.main()

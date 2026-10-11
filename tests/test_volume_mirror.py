import contextlib
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from titan.core import Error
from titan.host import Host
from titan.volume_mirror import SCRUB_INTERVAL, replace_state
from titan.volumes import Volumes


class ReplaceStateTests(unittest.TestCase):
    def test_status_lines_are_reduced_to_a_state(self):
        self.assertEqual(replace_state("Never started"), {"state": "none", "percent": None})
        self.assertEqual(replace_state("12.5% done, 0 write errs, 0 uncorr. read errs"), {"state": "running", "percent": 12.5})
        self.assertEqual(replace_state("Started on 11.Oct 10:00:00, finished on 11.Oct 10:05:00, 0 write errs, 0 uncorr. read errs")["state"], "finished")
        self.assertEqual(replace_state("Started on 11.Oct 10:00:00, canceled on 11.Oct 10:01:00 at 3.0%, 0 write errs")["state"], "canceled")
        self.assertEqual(replace_state("Started on 11.Oct 10:00:00, suspended on 11.Oct 10:01:00 at 40.0%, 0 write errs")["state"], "suspended")


class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.share_root = self.root / "data"
        self.share_root.mkdir()
        self.share_root.chmod(0o755)
        self.fstab = self.root / "fstab"
        self.fstab.write_text("UUID=system / ext4 defaults 0 1\n")
        self.fstab.chmod(0o644)
        self.host = Host(self.root / "agent", self.share_root, self.root / "vms", self.root / "smb.conf")
        self.calls = []
        self.mounted = False
        self.status = "Never started"
        self.accepted = True
        blank = {"type": "disk", "size": 1024**3, "fstype": None, "uuid": None, "ro": False, "mountpoints": []}
        self.disks = [dict(blank, name="/dev/sd" + letter) for letter in "bcd"]
        self.manager = Volumes(self.host, self.command, self.fstab, os.geteuid())
        self.manager.sysfs = self.root / "sysfs"
        self.manager.replace_pause = 0
        self.host._volumes = self.manager
        self.host.disks = lambda: copy.deepcopy(self.disks)
        # Nothing is really mounted, so the device number Btrfs files report is supplied.
        patcher = patch("titan.volumes.mount_device", return_value=os.stat(self.share_root).st_dev)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        for path in self.share_root.rglob("*"):
            if path.is_dir() and not path.is_symlink(): path.chmod(0o755)
        self.temporary.cleanup()

    def command(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == "mkfs.btrfs":
            count = sum(value.startswith("/proc/self/fd/") for value in args)
            for disk in self.disks[:count]:
                disk.update(fstype="btrfs", uuid=args[args.index("-U") + 1])
        if args[0] == "blkid": return "TYPE=btrfs\nUUID=" + self.disks[0]["uuid"]
        if args[0] == "mount": self.mounted = True
        if args[0] == "findmnt":
            entries = []
            if self.mounted:
                record = self.host.load("volumes", [])[0]
                value = os.stat(self.share_root).st_dev
                entries = [{"target": str(self.manager.root / record["name"]), "fstype": "btrfs",
                            "uuid": record["uuid"], "maj:min": f"{os.major(value)}:{os.minor(value)}"}]
            return json.dumps({"filesystems": entries})
        if args[0] == "wipefs": return '{"signatures": []}'
        if args[:3] == ["btrfs", "replace", "status"]: return self.status
        if args[:3] == ["btrfs", "replace", "start"] and self.accepted: self.status = "0.0% done, 0 write errs, 0 uncorr. read errs"
        return ""

    @contextlib.contextmanager
    def simulation(self):
        probe = self.root / "dummy-device"
        probe.touch()
        original_open, original_mkdir = os.open, os.mkdir
        def mkdir(path, mode=0o777, **kwargs):
            return original_mkdir(path, 0o700 if mode == 0 else mode, **kwargs)
        def open_file(path, flags, *args, **kwargs):
            return original_open(probe if str(path).startswith("/dev/sd") else path, flags, *args, **kwargs)
        with patch.object(self.manager, "blank_disk", return_value=0), \
                patch("titan.volumes.os.mkdir", side_effect=mkdir), \
                patch("titan.volumes.os.open", side_effect=open_file), \
                patch("titan.volumes.os.fchmod"), \
                patch("titan.volume_mirror.os.open", side_effect=open_file), \
                patch("titan.volume_mirror.os.fchmod"), \
                patch("titan.volumes.stat.S_ISBLK", return_value=True), \
                patch("titan.volume_mirror.stat.S_ISBLK", return_value=True), \
                patch("titan.volumes.shutil.which", return_value="/mock/tool"):
            yield

    def create(self):
        with self.simulation():
            return self.manager.create("spiegel", "/dev/sdb", "btrfs", "spiegel", "/dev/sdb", ["/dev/sdc"])

    def kernel(self, missing=(), errors=0, present=("sdb", "sdc"), target=False):
        """Write the sysfs view the kernel offers for a mounted Btrfs volume."""
        base = self.manager.sysfs / self.manager.record("spiegel")["uuid"]
        for path in sorted(base.rglob("*"), reverse=True) if base.exists() else []:
            path.rmdir() if path.is_dir() else path.unlink()
        for devid in (1, 2):
            entry = base / "devinfo" / str(devid)
            entry.mkdir(parents=True)
            (entry / "missing").write_text("1\n" if devid in missing else "0\n")
            (entry / "replace_target").write_text("0\n")
            (entry / "error_stats").write_text(f"write_errs 0\nread_errs {errors if devid == 2 else 0}\nflush_errs 0\ncorruption_errs 0\ngeneration_errs 0\n")
        if target:
            entry = base / "devinfo" / "0"
            entry.mkdir()
            (entry / "replace_target").write_text("1\n")
        (base / "devices").mkdir()
        for name in present:
            (base / "devices" / name).touch()

    def test_mirror_keeps_two_copies_and_registers_every_member_before_mounting(self):
        self.assertTrue(self.create()["ok"])
        command = next(args for args in self.calls if args[0] == "mkfs.btrfs")
        self.assertEqual(command[command.index("-d") + 1], "raid1")
        self.assertEqual(command[command.index("-m") + 1], "raid1")
        self.assertEqual(sum(value.startswith("/proc/self/fd/") for value in command), 2)
        self.assertNotIn("-f", command)
        self.assertLess(self.calls.index(["btrfs", "device", "scan"]), next(index for index, args in enumerate(self.calls) if args[0] == "mount"))
        record = self.manager.record("spiegel")
        self.assertEqual(record["disks"], ["/dev/sdb", "/dev/sdc"])
        self.assertEqual(self.fstab.read_text().count("UUID=" + record["uuid"]), 1)
        with self.simulation():
            row = self.manager.inventory()["volumes"][0]
        self.assertTrue(row["mirror"])
        self.assertFalse(row["degraded"])

    def test_mirror_needs_btrfs_distinct_disks_and_at_most_four(self):
        for filesystem, mirror in (("ext4", ["/dev/sdc"]), ("btrfs", ["/dev/sdb"]), ("btrfs", ["/dev/sdc", "/dev/sdc"]),
                                   ("btrfs", ["/dev/sdc", "/dev/sdd", "/dev/sde", "/dev/sdf"]), ("btrfs", "/dev/sdc")):
            with self.simulation(), self.assertRaises(Error):
                self.manager.create("spiegel", "/dev/sdb", filesystem, "spiegel", "/dev/sdb", mirror)
        self.assertFalse(any(args[0].startswith("mkfs.") for args in self.calls))

    def test_a_mirror_with_a_missing_disk_is_never_mounted_implicitly(self):
        self.create()
        self.mounted = False
        del self.disks[1]
        self.calls = []
        with self.simulation(), self.assertRaises(Error) as raised:
            self.manager.mount("spiegel")
        self.assertEqual(raised.exception.status, 409)
        self.assertFalse(any(args[0] == "mount" for args in self.calls))
        with self.simulation():
            row = self.manager.inventory()["volumes"][0]
        self.assertTrue(row["degraded"])
        self.assertEqual(row["state"], "Laufwerk fehlt")

    def test_missing_disk_is_replaced_by_device_number_after_a_degraded_mount(self):
        self.create()
        self.mounted = False
        self.disks[1].update(fstype=None, uuid=None)
        self.kernel(missing=(2,), present=("sdb",))
        self.calls = []
        with self.simulation():
            for arguments in (("spiegel", "/dev/sdd", "falsch", "/dev/sdd"), ("spiegel", "/dev/sdd", "spiegel", "/dev/sdb")):
                with self.assertRaises(Error):
                    self.manager.replace(*arguments)
            self.assertEqual(self.calls, [])
            self.assertTrue(self.manager.replace("spiegel", "/dev/sdd", "spiegel", "/dev/sdd")["ok"])
        target = str(self.manager.root / "spiegel")
        self.assertIn(["mount", "-o", "degraded", "--", target], self.calls)
        self.assertIn(["btrfs", "replace", "start", "2", "/dev/sdd", target], self.calls)
        self.assertEqual(self.manager.record("spiegel")["replacing"]["disk"], "/dev/sdd")
        with self.simulation(), self.assertRaises(Error) as raised:
            self.manager.replace("spiegel", "/dev/sdd", "spiegel", "/dev/sdd")
        self.assertEqual(raised.exception.status, 409)

    def test_present_failing_disk_is_named_and_read_only_when_needed(self):
        self.create()
        self.kernel(errors=7)
        with self.simulation():
            row = self.manager.inventory()["volumes"][0]
            self.assertEqual((row["errors"], row["state"]), (7, "Fehler gefunden"))
            with self.assertRaises(Error):
                self.manager.replace("spiegel", "/dev/sdd", "spiegel", "/dev/sdd")
            self.manager.replace("spiegel", "/dev/sdd", "spiegel", "/dev/sdd", "/dev/sdc")
        self.assertIn(["btrfs", "replace", "start", "-r", "/dev/sdc", "/dev/sdd", str(self.manager.root / "spiegel")], self.calls)

    def test_failed_start_does_not_leave_a_replacement_pending(self):
        self.create()
        self.kernel(missing=(2,), present=("sdb",))
        run = self.command
        def refuse(args, **kwargs):
            if args[:3] == ["btrfs", "replace", "start"]: raise Error("target too small")
            return run(args, **kwargs)
        self.manager.run = refuse
        with self.simulation(), self.assertRaises(Error):
            self.manager.replace("spiegel", "/dev/sdd", "spiegel", "/dev/sdd")
        self.assertIsNone(self.manager.record("spiegel")["replacing"])

    def test_a_copy_the_kernel_never_began_is_an_error_not_a_pending_replacement(self):
        self.create()
        self.kernel(missing=(2,), present=("sdb",))
        self.accepted = False
        with self.simulation(), self.assertRaises(Error) as raised:
            self.manager.replace("spiegel", "/dev/sdd", "spiegel", "/dev/sdd")
        self.assertIn("nicht gestartet", str(raised.exception))
        self.assertIsNone(self.manager.record("spiegel")["replacing"])

    def test_finishing_waits_for_the_copy_then_restores_both_copies(self):
        self.create()
        self.kernel(missing=(2,), present=("sdb",))
        with self.simulation():
            self.manager.replace("spiegel", "/dev/sdd", "spiegel", "/dev/sdd")
            self.status = "40.0% done, 0 write errs, 0 uncorr. read errs"
            self.kernel(missing=(2,), present=("sdb",), target=True)
            self.calls = []
            self.manager.maintain()
            self.assertFalse(any(args[:2] == ["btrfs", "balance"] for args in self.calls))
            row = self.manager.inventory()["volumes"][0]
            self.assertEqual((row["state"], row["replacing"]), ("Austausch läuft", {"disk": "/dev/sdd", "percent": 40.0}))
            self.status = "Started on 11.Oct 10:00:00, finished on 11.Oct 10:05:00, 0 write errs, 0 uncorr. read errs"
            self.kernel(present=("sdb", "sdd"))
            self.manager.maintain()
        target = str(self.manager.root / "spiegel")
        self.assertIn(["btrfs", "balance", "start", "-dconvert=raid1,soft", "-mconvert=raid1,soft", "--", target], self.calls)
        record = self.manager.record("spiegel")
        self.assertIsNone(record["replacing"])
        self.assertEqual(record["disks"], ["/dev/sdb", "/dev/sdd"])

    def test_unfinished_replacement_is_reported_instead_of_marked_healthy(self):
        self.create()
        self.kernel(missing=(2,), present=("sdb",))
        with self.simulation():
            self.manager.replace("spiegel", "/dev/sdd", "spiegel", "/dev/sdd")
            self.status = "Started on 11.Oct 10:00:00, canceled on 11.Oct 10:01:00 at 3.0%, 0 write errs"
            self.calls = []
            self.manager.maintain()
        self.assertFalse(any(args[:2] == ["btrfs", "balance"] for args in self.calls))
        record = self.manager.record("spiegel")
        self.assertIsNone(record["replacing"])
        self.assertIn("nicht abgeschlossen", record["error"])

    def test_every_block_is_read_once_a_month(self):
        self.create()
        created = self.manager.record("spiegel")["created"]
        self.calls = []
        with self.simulation():
            self.manager.maintain(created + SCRUB_INTERVAL - 60)
            self.assertFalse(any(args[:2] == ["btrfs", "scrub"] for args in self.calls))
            self.manager.maintain(created + SCRUB_INTERVAL + 60)
            self.manager.maintain(created + SCRUB_INTERVAL + 120)
        self.assertEqual(sum(args[:3] == ["btrfs", "scrub", "start"] for args in self.calls), 1)


if __name__ == "__main__":
    unittest.main()

import contextlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
import uuid
import xml.etree.ElementTree as ET

from titan.core import Error
from titan.host import Host, run

GIB = 1024**3


def qcow_header(size=8 * GIB, backing=False, external=False):
    data = bytearray(104)
    data[:4] = b"QFI\xfb"
    struct.pack_into(">IQI", data, 4, 3, 104 if backing else 0, 8 if backing else 0)
    struct.pack_into(">Q", data, 24, size)
    struct.pack_into(">Q", data, 72, 4 if external else 0)
    struct.pack_into(">I", data, 100, 104)
    return bytes(data)


class VMStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.host = Host(self.root / "agent", self.root / "shares", self.root / "vms", self.root / "samba.conf")
        self.host.vm_root.mkdir(mode=0o755)
        self.share = self.host.share_root / "shares" / "images"
        self.share.mkdir(parents=True)
        self.host.share_root.chmod(0o755)
        self.share.parent.chmod(0o755)
        self.host.volume_manager.owner_uid = os.geteuid()
        self.host.save("shares", [{"name": "images", "path": str(self.share), "readers": [], "writers": []}])
        self.memory = patch.object(self.host, "op_status", return_value={"memory_total": 16 * GIB})
        self.memory.start()
        self.cpu = patch.object(self.host, "validate_vm_cpu_ids", side_effect=lambda cpus, ids: ids or [])
        self.cpu.start()
        self.calls = []
        self.vm_id = str(uuid.uuid4())

    def tearDown(self):
        self.memory.stop()
        self.cpu.stop()
        self.temp.cleanup()

    def image(self, name="source.qcow2", **kwargs):
        path = self.share / name
        path.write_bytes(qcow_header(**kwargs) if path.suffix == ".qcow2" else b"raw image fixture")
        return path

    def command(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if args[:2] == ["qemu-img", "info"]:
            return json.dumps({"format": args[3], "virtual-size": 8 * GIB})
        if args[:2] == ["qemu-img", "create"]:
            Path(args[4]).write_bytes(qcow_header(int(args[5][:-1]) * GIB))
        if args[:2] == ["qemu-img", "convert"]:
            with Path(args[-1]).open("ab") as stream:
                stream.write(b"copied fixture sectors")
        if args[:2] == ["virsh", "domuuid"]:
            return self.vm_id
        return ""

    def creation_context(self, command=None):
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(self.host, "op_vms", return_value={"available": True, "vms": []}))
        stack.enter_context(patch.object(self.host, "vm_network_ready"))
        stack.enter_context(patch("titan.host.pwd.getpwnam", return_value=SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid())))
        stack.enter_context(patch("titan.host.run", side_effect=command or self.command))
        # Fixtures are sparse and allocate only KiB; emulate a NAS with enough
        # free capacity for the conservative production import reservation.
        stack.enter_context(patch("titan.host.os.fstatvfs", return_value=SimpleNamespace(f_bavail=65536, f_frsize=1024**2)))
        return stack

    def configure_volume(self, mounted=True):
        record = {"name": "ssd", "filesystem": "ext4", "uuid": str(uuid.uuid4()), "disk": "/dev/mock", "phase": "mounted"}
        path = self.host.volume_manager.root / "ssd"
        path.mkdir(parents=True, mode=0o755)
        path.parent.chmod(0o755)
        self.host.save("volumes", [record])
        value = os.stat(path)
        mount = {"target": str(path), "fstype": "ext4", "uuid": record["uuid"],
                 "maj:min": str(os.major(value.st_dev)) + ":" + str(os.minor(value.st_dev))}
        return record, path, patch.object(self.host.volume_manager, "mounts", return_value=[mount] if mounted else [])

    def test_create_import_preserves_source_and_registers_size_storage_cpu(self):
        source = self.image()
        original = source.read_bytes()
        with self.creation_context():
            result = self.host.op_vm_create("imported", 1, 1024, 16, disk_image="share:images:source.qcow2", cpu_ids=[0])
        self.assertTrue(result["source_retained"])
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(result["disk_gb"], 16)
        records = self.host.load("vms", [])
        self.assertEqual(records[0]["storage"], "system")
        self.assertEqual(records[0]["virtual_size"], 16 * GIB)
        root = ET.fromstring((self.host.directory / "vm-imported.xml").read_text())
        self.assertEqual(root.find("vcpu").get("cpuset"), "0")
        self.assertEqual(root.find("./os/boot").get("dev"), "hd")
        convert = next(args for args, _ in self.calls if args[:2] == ["qemu-img", "convert"])
        self.assertIn("-n", convert)
        self.assertNotIn("-U", convert)
        self.assertNotIn("--force-share", convert)

    def test_explicit_absolute_source_is_cloned_without_changing_original(self):
        source = self.image()
        before = source.read_bytes(), source.stat().st_mtime_ns, source.stat().st_ino
        with self.creation_context():
            result = self.host.op_vm_create("absolute", 1, 1024, 16, disk_image=str(source))
        self.assertTrue(result["source_retained"])
        self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns, source.stat().st_ino), before)
        target = self.host.vm_root / "absolute.qcow2"
        self.assertNotEqual(target.stat().st_ino, source.stat().st_ino)
        self.assertEqual(result["disk_path"], str(target))
        convert, arguments = next((args, kwargs) for args, kwargs in self.calls if args[:2] == ["qemu-img", "convert"])
        self.assertNotIn(str(source), convert)
        self.assertEqual(len(arguments["pass_fds"]), 2)

    def test_image_details_returns_capacity_format_and_source_without_running_qemu(self):
        source = self.image(size=10 * GIB + 1)
        with patch("titan.host.run", side_effect=self.command):
            value = self.host.op_vm_image_details(str(source))
        self.assertEqual(value["id"], str(source))
        self.assertEqual(value["path"], str(source))
        self.assertEqual(value["format"], "qcow2")
        self.assertEqual(value["virtual_size"], 10 * GIB + 1)
        self.assertEqual(value["min_disk_gb"], 11)
        self.assertEqual(value["size"], source.stat().st_size)
        self.assertTrue(value["source_retained"])
        self.assertFalse(any(args[0] == "qemu-img" for args, _ in self.calls))
        raw = self.image("source.raw")
        with patch("titan.host.run", side_effect=self.command):
            value = self.host.op_vm_image_details(str(raw))
        self.assertEqual(value["format"], "raw")
        self.assertEqual(value["virtual_size"], raw.stat().st_size)
        self.assertEqual(value["min_disk_gb"], 8)

    def test_direct_source_respects_isolated_system_namespace(self):
        self.host.system_root = self.root
        source = self.image()
        path = "/" + source.relative_to(self.root).as_posix()
        with patch("titan.host.run", side_effect=self.command):
            value = self.host.op_vm_image_details(path)
        self.assertEqual(value["path"], str(source))
        self.assertEqual(value["id"], path)
        with self.assertRaises(Error):
            with self.host.vm_image_source(str(source)):
                pass

    def test_direct_source_rejects_links_traversal_kernel_paths_and_special_files(self):
        source = self.image()
        link = self.share / "link.qcow2"
        link.symlink_to(source)
        folder_link = self.root / "folder-link"
        folder_link.symlink_to(self.share, target_is_directory=True)
        fifo = self.share / "fifo.raw"
        os.mkfifo(fifo)
        (self.share / "folder.raw").mkdir()
        (self.share / "empty.raw").write_bytes(b"")
        tokens = [str(link), str(folder_link / source.name), str(self.share / ".." / "source.qcow2"),
                  str(self.share) + "//source.qcow2", str(self.share) + "/./source.qcow2", str(source) + "\n",
                  "/dev/source.img", "/proc/source.raw", "/sys/source.raw", str(fifo),
                  str(self.share / "folder.raw"), str(self.share / "empty.raw"), str(self.share / "source.iso")]
        for token in tokens:
            with self.subTest(token=token), self.assertRaises(Error):
                with self.host.vm_image_source(token):
                    pass

    def test_direct_source_missing_file_is_readable_not_found_error(self):
        with self.assertRaises(Error) as caught:
            with self.host.vm_image_source(str(self.share / "missing.qcow2")):
                pass
        self.assertEqual(caught.exception.status, 404)

    def test_direct_probe_rejects_backing_external_and_invalid_header_before_qemu(self):
        for options in ({"backing": True}, {"external": True}):
            source = self.image(**options)
            with patch("titan.host.run", side_effect=self.command), self.assertRaises(Error):
                self.host.op_vm_image_details(str(source))
        source.write_bytes(b"invalid qcow2 image")
        with patch("titan.host.run", side_effect=self.command), self.assertRaises(Error):
            self.host.op_vm_image_details(str(source))
        self.assertFalse(any(args[0] == "qemu-img" for args, _ in self.calls))

    def test_direct_probe_and_create_reject_active_hardlink_alias(self):
        source = self.image()
        alias = self.share / "alias.qcow2"
        os.link(source, alias)
        xml = '<domain><devices><disk><source file="' + str(source) + '"/></disk></devices></domain>'
        original = self.command
        def command(args, **kwargs):
            if args[:2] == ["virsh", "list"]: return "foreign-domain"
            if args[:2] == ["virsh", "dumpxml"]: return xml
            return original(args, **kwargs)
        with patch("titan.host.run", side_effect=command), self.assertRaises(Error) as caught:
            self.host.op_vm_image_details(str(alias))
        self.assertEqual(caught.exception.status, 409)
        with self.creation_context(command), self.assertRaises(Error):
            self.host.op_vm_create("busy_absolute", 1, 1024, 8, disk_image=str(alias))
        self.assertFalse((self.host.vm_root / "busy_absolute.qcow2").exists())

    def test_direct_source_on_unmounted_managed_volume_does_not_read_fallback_file(self):
        _, volume, mounts = self.configure_volume(mounted=False)
        source = volume / "source.raw"
        source.write_bytes(b"fallback is not volume data")
        with mounts, self.assertRaises(Error) as caught:
            with self.host.vm_image_source(str(source)):
                pass
        self.assertEqual(caught.exception.status, 503)

    def test_direct_source_rechecks_required_volume_device_and_closes_source(self):
        source = self.image()
        device = source.stat().st_dev
        with patch("titan.storage_locations.StorageLocations.required_path", side_effect=[device, device + 1]), self.assertRaises(Error):
            with self.host.vm_image_source(str(source)) as (fd, _):
                self.assertEqual(os.pread(fd, 4, 0), b"QFI\xfb")
        with self.assertRaises(OSError):
            os.fstat(fd)

    def test_volume_create_and_managed_validation_keep_uuid_and_disk_on_selected_volume(self):
        record, path, mounts = self.configure_volume()
        iso = self.host.vm_root / "iso"
        iso.mkdir()
        (iso / "installer.iso").write_bytes(b"test ISO")
        with mounts, self.creation_context():
            result = self.host.op_vm_create("volume_guest", 1, 1024, 8, "installer.iso", storage="volume:ssd")
        disk = path / "vms" / "volume_guest.qcow2"
        self.assertEqual(result["disk_path"], str(disk))
        self.assertFalse((self.host.vm_root / disk.name).exists())
        metadata = self.host.load("vms", [])[0]
        self.assertEqual(metadata["storage_uuid"], record["uuid"])
        xml = ET.fromstring((self.host.directory / "vm-volume_guest.xml").read_text())
        ET.SubElement(xml, "uuid").text = self.vm_id
        xml = ET.tostring(xml, encoding="unicode")
        # Recreate the mount patch because patch context objects are single-use.
        value = os.stat(path)
        mount = {"target": str(path), "fstype": "ext4", "uuid": record["uuid"],
                 "maj:min": f"{os.major(value.st_dev)}:{os.minor(value.st_dev)}"}
        def command(args, **kwargs):
            return xml if args[1] == "dumpxml" else "shut off"
        with patch.object(self.host.volume_manager, "mounts", return_value=[mount]), patch("titan.host.run", side_effect=command):
            managed = self.host.managed_vm(self.vm_id)
        self.assertEqual(managed["storage"], "volume:ssd")
        self.assertEqual(managed["disk"], str(disk))
        self.host.save("volumes", [{**record, "uuid": str(uuid.uuid4())}])
        with patch.object(self.host.volume_manager, "mounts", return_value=[mount]), patch("titan.host.run", side_effect=command):
            with self.assertRaises(Error):
                self.host.managed_vm(self.vm_id)

    def test_offline_volume_never_allocates_on_underlying_system_disk(self):
        _, path, mounts = self.configure_volume(mounted=False)
        source = self.image()
        with mounts, self.creation_context():
            with self.assertRaises(Error) as result:
                self.host.op_vm_create("missing", 1, 1024, 8, storage="volume:ssd", disk_image="share:images:" + source.name)
        self.assertEqual(result.exception.status, 503)
        self.assertFalse((path / "vms").exists())
        self.assertFalse(any(args[0] == "qemu-img" for args, _ in self.calls))

    def test_sources_reject_absolute_traversal_symlink_directory_and_blocked_share(self):
        self.image()
        (self.share / "link.qcow2").symlink_to(self.share / "source.qcow2")
        (self.share / "folder.raw").mkdir()
        tokens = ["/etc/passwd", "share:images:/source.qcow2", "share:images:../source.qcow2", "share:images:link.qcow2", "share:images:folder.raw"]
        for token in tokens:
            with self.subTest(token=token), self.assertRaises((Error, OSError)):
                with self.host.vm_image_source(token):
                    pass
        self.host.save("shares", [{"name": "images", "path": str(self.share), "blocked": True}])
        with self.assertRaises(Error):
            with self.host.vm_image_source("share:images:source.qcow2"):
                pass

    def test_backing_and_external_data_headers_are_rejected_before_qemu_is_invoked(self):
        for options in ({"backing": True}, {"external": True}):
            source = self.image(**options)
            with self.creation_context(), self.assertRaises(Error):
                self.host.op_vm_create("unsafe", 1, 1024, 8, disk_image="share:images:" + source.name)
            self.assertFalse(any(args[0] == "qemu-img" for args, _ in self.calls))
            self.assertFalse((self.host.vm_root / "unsafe.qcow2").exists())

    def test_active_foreign_domain_image_and_hardlink_alias_are_rejected(self):
        source = self.image()
        alias = self.share / "alias.qcow2"
        os.link(source, alias)
        xml = '<domain><devices><disk><source file="' + str(source) + '"/></disk></devices></domain>'
        original = self.command
        def command(args, **kwargs):
            if args[:2] == ["virsh", "list"]: return "foreign-domain"
            if args[:2] == ["virsh", "dumpxml"]: return xml
            return original(args, **kwargs)
        with self.creation_context(command), self.assertRaises(Error) as result:
            self.host.op_vm_create("busy", 1, 1024, 8, disk_image="share:images:alias.qcow2")
        self.assertIn("laufenden VM", str(result.exception))
        self.assertFalse((self.host.vm_root / "busy.qcow2").exists())

    def test_import_failure_or_source_mutation_removes_only_new_disk(self):
        source = self.image()
        original = self.command
        for reason in ("failure", "mutation"):
            def command(args, **kwargs):
                result = original(args, **kwargs)
                if args[:2] == ["qemu-img", "convert"]:
                    if reason == "failure": raise Error("conversion failed")
                    with source.open("ab") as stream: stream.write(b"changed")
                return result
            with self.subTest(reason=reason), self.creation_context(command), self.assertRaises(Error):
                self.host.op_vm_create("failed", 1, 1024, 8, disk_image="share:images:" + source.name)
            self.assertFalse((self.host.vm_root / "failed.qcow2").exists())
            self.assertTrue(source.exists())
            self.assertEqual(self.host.load("vms", []), [])

    def test_smaller_disk_and_missing_install_source_are_rejected(self):
        source = self.image(size=16 * GIB)
        def command(args, **kwargs):
            result = self.command(args, **kwargs)
            if args[:2] == ["qemu-img", "info"]: return json.dumps({"format": "qcow2", "virtual-size": 16 * GIB})
            return result
        with self.creation_context(command), self.assertRaises(Error):
            self.host.op_vm_create("small", 1, 1024, 8, disk_image="share:images:" + source.name)
        with self.creation_context(), self.assertRaises(Error):
            self.host.op_vm_create("empty", 1, 1024, 8)
        self.assertFalse((self.host.vm_root / "small.qcow2").exists())

    def test_options_show_only_regular_unblocked_images_and_offline_target(self):
        self.image()
        self.image("source.raw")
        (self.share / "unsafe.qcow2").write_bytes(qcow_header(backing=True))
        (self.share / "symlink.qcow2").symlink_to(self.share / "source.qcow2")
        _, _, mounts = self.configure_volume(mounted=False)
        with mounts, patch("titan.host.run", side_effect=self.command):
            options = self.host.vm_storage_options()
        self.assertEqual({item["name"] for item in options["disk_images"]}, {"source.qcow2", "source.raw"})
        self.assertEqual(options["disk_images"][0]["virtual_size"], 8 * GIB)
        self.assertFalse(next(item for item in options["storage"] if item["id"] == "volume:ssd")["available"])
        self.assertTrue(options["storage"][0]["available"])

    def test_inventory_does_not_run_qemu_on_share_writable_source(self):
        self.image()
        with patch("titan.host.run", side_effect=self.command):
            options = self.host.vm_storage_options()
        self.assertEqual(options["disk_images"][0]["virtual_size"], 8 * GIB)
        self.assertFalse(any(args[0] == "qemu-img" for args, _ in self.calls))

    def test_qemu_receives_private_snapshot_and_concurrent_source_header_change_is_rejected(self):
        source = self.image()
        source_inode = source.stat().st_ino
        original = self.command
        parsed = []
        def command(args, **kwargs):
            if args[:2] == ["qemu-img", "info"]:
                private = Path(args[-1])
                parsed.append(private.stat().st_ino)
                previous = source.stat()
                source.write_bytes(qcow_header(backing=True))
                # Some filesystems coalesce metadata timestamps within one tick.
                os.utime(source, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1000000))
                self.assertNotEqual(private.stat().st_ino, source_inode)
                self.assertEqual(private.read_bytes(), qcow_header())
            return original(args, **kwargs)
        with self.creation_context(command), self.assertRaises(Error):
            self.host.op_vm_create("race", 1, 1024, 8, disk_image="share:images:" + source.name)
        self.assertTrue(parsed)
        self.assertFalse((self.host.vm_root / "race.qcow2").exists())
        self.assertEqual(list(self.host.vm_root.iterdir()), [])
        self.assertEqual(source.read_bytes(), qcow_header(backing=True))

    def test_private_fallback_copy_retains_sparse_layout_and_cleans_temporary_directory(self):
        source = self.share / "sparse.raw"
        with source.open("wb") as stream:
            stream.write(b"BOOTSECTOR")
            stream.seek(2 * GIB - 1)
            stream.write(b"Z")
        with self.host.vm_storage_fd() as (target, _), self.host.vm_image_source("share:images:sparse.raw") as (fd, _):
            with patch("titan.vm_storage.fcntl.ioctl", side_effect=OSError("reflink unavailable")):
                with self.host.vm_private_image(target, fd) as copy:
                    self.assertEqual(os.fstat(copy).st_size, 2 * GIB)
                    self.assertEqual(os.pread(copy, 10, 0), b"BOOTSECTOR")
                    self.assertEqual(os.pread(copy, 1, 2 * GIB - 1), b"Z")
                    self.assertLess(os.fstat(copy).st_blocks * 512, 1024 * 1024)
        self.assertEqual(list(self.host.vm_root.iterdir()), [])

    def test_compressed_source_reservation_uses_virtual_capacity_before_qemu(self):
        source = self.image(size=100 * GIB)
        with self.creation_context(), self.assertRaises(Error) as result:
            self.host.op_vm_create("too_large", 1, 1024, 100, disk_image="share:images:" + source.name)
        self.assertEqual(result.exception.status, 409)
        self.assertIn("freier Speicher", str(result.exception))
        self.assertFalse(any(args[0] == "qemu-img" for args, _ in self.calls))
        self.assertEqual(list(self.host.vm_root.iterdir()), [])

    def test_volume_vm_edit_media_backup_and_remove_preserve_selected_disk(self):
        record, mountpoint, mounts = self.configure_volume()
        iso_dir = self.host.vm_root / "iso"
        iso_dir.mkdir()
        (iso_dir / "installer.iso").write_bytes(b"ISO fixture")
        with mounts, self.creation_context():
            result = self.host.op_vm_create("volume_lifecycle", 1, 1024, 8, "installer.iso", storage="volume:ssd")
        disk = Path(result["disk_path"])
        metadata = self.host.directory / "vm-volume_lifecycle.xml"
        root = ET.fromstring(metadata.read_text())
        ET.SubElement(root, "uuid").text = self.vm_id
        xml = [ET.tostring(root, encoding="unicode")]
        value = os.stat(mountpoint)
        mount = {"target": str(mountpoint), "fstype": "ext4", "uuid": record["uuid"],
                 "maj:min": f"{os.major(value.st_dev)}:{os.minor(value.st_dev)}"}
        manager = Mock()
        manager.settings.return_value = {"target": "/existing/backup"}
        manager.create_vm.return_value = {"id": "fixture-backup"}
        self.host._backups = manager
        def command(args, **kwargs):
            if args[:2] == ["virsh", "dumpxml"]: return xml[0]
            if args[:2] == ["virsh", "domstate"]: return "shut off"
            if args[:2] == ["virsh", "define"]: xml[0] = metadata.read_text()
            return ""
        before = disk.read_bytes()
        with patch.object(self.host.volume_manager, "mounts", return_value=[mount]), patch("titan.host.run", side_effect=command):
            self.host.op_vm_update(self.vm_id, 1, 2048)
            self.host.op_vm_media(self.vm_id)
            self.host.op_vm_backup(self.vm_id)
            result = self.host.op_vm_remove(self.vm_id)
        self.assertEqual(manager.create_vm.call_args.args[2], str(disk))
        self.assertTrue(result["disk_retained"])
        self.assertEqual(disk.read_bytes(), before)
        self.assertFalse(metadata.exists())
        self.assertEqual(self.host.load("vms", []), [])

    def test_start_rechecks_cpu_selection_against_current_online_ids(self):
        self.cpu.stop()
        managed = {"id": self.vm_id, "cpus": 1, "cpu_ids": [5]}
        with patch.object(self.host, "managed_vm", return_value=managed), \
                patch.object(self.host, "op_vms", return_value={"available": True}), \
                patch.object(self.host, "cpu_topology", return_value={"online": [0, 1]}), \
                patch.object(self.host, "vm_network_ready") as network, \
                patch("titan.host.run") as command:
            with self.assertRaises(Error) as result:
                self.host.op_vm_action(self.vm_id, "start")
        self.assertEqual(result.exception.status, 409)
        network.assert_not_called()
        command.assert_not_called()

    def test_root_controlled_storage_rejects_symlink_or_shared_writable_directory(self):
        source = self.image()
        outside = self.root / "outside"
        outside.mkdir()
        self.host.vm_root.rmdir()
        self.host.vm_root.symlink_to(outside, target_is_directory=True)
        with self.creation_context(), self.assertRaises(Error):
            self.host.op_vm_create("link", 1, 1024, 8, disk_image="share:images:" + source.name)
        self.assertEqual(list(outside.iterdir()), [])
        self.host.vm_root.unlink()
        self.host.vm_root.mkdir(mode=0o777)
        self.host.vm_root.chmod(0o777)  # Set the unsafe fixture independently of the runner umask.
        with self.creation_context(), self.assertRaises(Error):
            self.host.op_vm_create("shared", 1, 1024, 8, disk_image="share:images:" + source.name)
        self.assertEqual(list(self.host.vm_root.iterdir()), [])

    @unittest.skipUnless(shutil.which("qemu-img"), "qemu-img not available for isolated integration fixture")
    def test_real_qemu_import_copies_private_image_with_larger_capacity(self):
        source = self.share / "real.qcow2"
        run(["qemu-img", "create", "-f", "qcow2", str(source), "8G"])
        before = source.read_bytes()
        def command(args, **kwargs):
            if args[0] == "qemu-img": return run(args, **kwargs)
            return self.command(args, **kwargs)
        with self.creation_context(command):
            self.host.op_vm_create("real", 1, 1024, 16, disk_image="share:images:real.qcow2")
        disk = self.host.vm_root / "real.qcow2"
        self.assertEqual(json.loads(run(["qemu-img", "info", "--output=json", str(disk)]))["virtual-size"], 16 * GIB)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(self.host.load("vms", [])[0]["virtual_size"], 16 * GIB)

    @unittest.skipUnless(shutil.which("qemu-img"), "qemu-img not available for isolated integration fixture")
    def test_real_qemu_direct_path_import_retains_original_bytes_and_metadata(self):
        source = self.share / "direct-source.qcow2"
        run(["qemu-img", "create", "-f", "qcow2", str(source), "8G"])
        before = source.read_bytes(), source.stat().st_ino, source.stat().st_mtime_ns, source.stat().st_ctime_ns
        def command(args, **kwargs):
            if args[0] == "qemu-img": return run(args, **kwargs)
            return self.command(args, **kwargs)
        with self.creation_context(command):
            details = self.host.op_vm_image_details(str(source))
            result = self.host.op_vm_create("direct_real", 1, 1024, 16, disk_image=str(source))
            after = self.host.op_vm_image_details(str(source))
        self.assertTrue(result["source_retained"])
        self.assertEqual((source.read_bytes(), source.stat().st_ino, source.stat().st_mtime_ns, source.stat().st_ctime_ns), before)
        self.assertEqual(after["revision"], details["revision"])
        value = json.loads(run(["qemu-img", "info", "--output=json", result["disk_path"]]))
        self.assertEqual(value["format"], "qcow2")
        self.assertEqual(value["virtual-size"], 16 * GIB)


if __name__ == "__main__":
    unittest.main()

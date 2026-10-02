import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid
import xml.etree.ElementTree as ET

from titan.core import Error
from titan.host import Host


class VMManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.vm_root = self.root / "vms"
        self.vm_root.mkdir(mode=0o755)
        self.host = Host(self.root / "agent", self.root / "shares", self.vm_root, self.root / "smb.conf")
        self.name = "linux"
        self.vm_id = str(uuid.uuid4())
        self.disk = self.vm_root / "linux.qcow2"
        self.disk.write_bytes(b"retained virtual disk")
        self.status = patch.object(self.host, "op_status", return_value={"memory_total": 16 * 1024**3}).start()
        self.xml = self.host.vm_definition("linux", 2, 2048, self.disk)
        document = ET.fromstring(self.xml)
        ET.SubElement(document, "uuid").text = self.vm_id
        self.xml = ET.tostring(document, encoding="unicode")
        self.metadata = self.host.directory / "vm-linux.xml"
        self.metadata.write_text(self.xml)
        self.host.save("vms", [{"id": self.vm_id, "name": self.name, "disk": str(self.disk)}])
        self.state = "shut off"
        self.calls = []
        self.runner = patch("titan.host.run", side_effect=self.command).start()

    def tearDown(self):
        patch.stopall()
        self.temp.cleanup()

    def command(self, arguments, **kwargs):
        self.calls.append(arguments)
        if arguments[:2] == ["virsh", "dumpxml"]:
            return self.xml
        if arguments[:2] == ["virsh", "domstate"]:
            return self.state
        if arguments[:2] == ["virsh", "domuuid"]:
            return self.vm_id
        return ""

    def test_update_offline_vm_changes_cpu_and_memory_without_disk_change(self):
        self.host.op_vm_update(self.vm_id, 1, 4096)
        root = ET.fromstring(self.metadata.read_text())
        self.assertEqual(root.findtext("vcpu"), "1")
        self.assertEqual(root.findtext("memory"), str(4096 * 1024))
        self.assertEqual(root.findtext("uuid"), self.vm_id)
        self.assertEqual(root.find("./devices/disk/source").get("file"), str(self.disk))
        self.assertEqual(self.disk.read_bytes(), b"retained virtual disk")
        self.assertIn(["virsh", "define", str(self.metadata)], self.calls)

    def test_running_vm_update_and_removal_are_rejected(self):
        self.state = "running"
        for operation in (lambda: self.host.op_vm_update(self.vm_id, 2, 2048), lambda: self.host.op_vm_remove(self.vm_id)):
            with self.assertRaises(Error) as result:
                operation()
            self.assertEqual(result.exception.status, 409)
        self.assertFalse(any(command[1] in ("define", "undefine") for command in self.calls))

    def test_failed_define_restores_previous_metadata(self):
        original = self.command
        def command(arguments, **kwargs):
            if arguments[:2] == ["virsh", "define"]:
                raise Error("libvirt rejected resource change")
            return original(arguments, **kwargs)
        self.runner.side_effect = command
        with self.assertRaises(Error):
            self.host.op_vm_update(self.vm_id, 1, 4096)
        self.assertEqual(self.metadata.read_text(), self.xml)

    def create_iso(self, name="linux.iso"):
        directory = self.vm_root / "iso"
        directory.mkdir(exist_ok=True)
        iso = directory / name
        iso.write_bytes(b"finalized ISO fixture")
        return iso

    def test_media_install_swap_and_eject_preserve_vm_identity_and_devices(self):
        first = self.create_iso()
        second = self.create_iso("rescue.iso")
        document = ET.fromstring(self.xml)
        ET.SubElement(document.find("./devices/interface"), "mac", address="52:54:00:12:34:56")
        self.xml = ET.tostring(document, encoding="unicode")
        original = self.command
        def command(arguments, **kwargs):
            result = original(arguments, **kwargs)
            if arguments[:2] == ["virsh", "define"]:
                self.xml = self.metadata.read_text()
            return result
        self.runner.side_effect = command
        result = self.host.op_vm_media(self.vm_id, first.name)
        self.assertEqual(result, {"ok": True, "iso": first.name, "boot": "cdrom"})
        document = ET.fromstring(self.metadata.read_text())
        cdrom = document.find("./devices/disk[@device='cdrom']")
        ET.SubElement(cdrom, "address", type="drive", controller="0", bus="0", target="0", unit="0")
        self.xml = ET.tostring(document, encoding="unicode")
        self.host.op_vm_media(self.vm_id, second.name)
        document = ET.fromstring(self.metadata.read_text())
        self.assertEqual(document.findtext("uuid"), self.vm_id)
        self.assertEqual(document.findtext("vcpu"), "2")
        self.assertEqual(document.findtext("memory"), str(2048 * 1024))
        self.assertEqual(document.find("./devices/disk[@device='disk']/source").get("file"), str(self.disk))
        self.assertEqual(document.find("./devices/interface/mac").get("address"), "52:54:00:12:34:56")
        cdrom = document.find("./devices/disk[@device='cdrom']")
        self.assertEqual(cdrom.find("source").get("file"), str(second))
        self.assertEqual(cdrom.find("address").get("unit"), "0")
        self.assertEqual(cdrom.find("target").get("tray"), "closed")
        self.assertEqual([node.get("dev") for node in document.findall("./os/boot")], ["cdrom", "hd"])
        self.assertIsNotNone(cdrom.find("readonly"))
        self.assertEqual(self.host.managed_vm(self.vm_id)["iso"], second.name)
        result = self.host.op_vm_media(self.vm_id)
        self.assertEqual(result, {"ok": True, "iso": None, "boot": "hd"})
        document = ET.fromstring(self.metadata.read_text())
        cdrom = document.find("./devices/disk[@device='cdrom']")
        self.assertIsNone(cdrom.find("source"))
        self.assertEqual(cdrom.find("target").get("tray"), "open")
        self.assertEqual([node.get("dev") for node in document.findall("./os/boot")], ["hd"])
        self.assertEqual(self.host.managed_vm(self.vm_id)["iso"], None)
        self.assertEqual(self.disk.read_bytes(), b"retained virtual disk")
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())

    def test_media_changes_require_shut_off_vm_before_redefinition(self):
        iso = self.create_iso()
        self.state = "running"
        for value in (iso.name, None):
            with self.assertRaises(Error) as result:
                self.host.op_vm_media(self.vm_id, value)
            self.assertEqual(result.exception.status, 409)
        self.assertFalse(any(command[1] == "define" for command in self.calls))
        self.assertEqual(self.metadata.read_text(), self.xml)

    def test_media_rejects_missing_traversal_symlink_empty_and_directory_sources(self):
        directory = self.vm_root / "iso"
        directory.mkdir()
        (directory / "directory.iso").mkdir()
        (directory / "empty.iso").touch()
        (directory / "outside.iso").symlink_to(self.disk)
        for name in ("../linux.qcow2", "missing.iso", "directory.iso", "empty.iso", "outside.iso", "", 123):
            with self.subTest(name=name):
                with self.assertRaises(Error):
                    self.host.op_vm_media(self.vm_id, name)
                self.assertEqual(self.metadata.read_text(), self.xml)
        self.assertFalse(any(command[1] == "define" for command in self.calls))

    def test_media_rejects_symlink_library(self):
        outside = self.root / "outside-library"
        outside.mkdir()
        (outside / "linux.iso").write_bytes(b"ISO fixture")
        (self.vm_root / "iso").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(Error):
            self.host.op_vm_media(self.vm_id, "linux.iso")
        self.assertFalse(any(command[1] == "define" for command in self.calls))

    def test_new_definition_validates_iso_and_sets_installation_boot_order(self):
        iso = self.create_iso()
        document = ET.fromstring(self.host.vm_definition(self.name, 2, 2048, self.disk, iso.name))
        self.assertEqual([node.get("dev") for node in document.findall("./os/boot")], ["cdrom", "hd"])
        self.assertEqual(document.find("./devices/disk[@device='cdrom']/source").get("file"), str(iso))
        iso.unlink()
        iso.symlink_to(self.disk)
        with self.assertRaises(Error):
            self.host.vm_definition(self.name, 2, 2048, self.disk, iso.name)

    def test_media_failed_define_rolls_back_previous_xml_and_reports_original_error(self):
        iso = self.create_iso()
        original = self.command
        definitions = []
        def command(arguments, **kwargs):
            if arguments[:2] == ["virsh", "define"]:
                definitions.append(self.metadata.read_text())
                if len(definitions) == 1:
                    raise Error("ISO definition rejected")
            return original(arguments, **kwargs)
        self.runner.side_effect = command
        with self.assertRaisesRegex(Error, "ISO definition rejected"):
            self.host.op_vm_media(self.vm_id, iso.name)
        self.assertEqual(len(definitions), 2)
        self.assertEqual(definitions[-1], self.xml)
        self.assertEqual(self.metadata.read_text(), self.xml)
        self.assertEqual(self.disk.read_bytes(), b"retained virtual disk")

    def test_media_reports_when_libvirt_cannot_confirm_rollback(self):
        iso = self.create_iso()
        original = self.command
        def command(arguments, **kwargs):
            if arguments[:2] == ["virsh", "define"]:
                raise Error("libvirt unavailable")
            return original(arguments, **kwargs)
        self.runner.side_effect = command
        with self.assertRaises(Error) as result:
            self.host.op_vm_media(self.vm_id, iso.name)
        self.assertEqual(result.exception.status, 500)
        self.assertIn("bisherige Definition", str(result.exception))
        self.assertEqual(self.metadata.read_text(), self.xml)
        self.assertEqual(self.disk.read_bytes(), b"retained virtual disk")

    def test_media_metadata_write_failure_does_not_change_definition_or_leave_temporary_files(self):
        iso = self.create_iso()
        with patch("titan.vm_management.os.replace", side_effect=OSError("write failure")):
            with self.assertRaises(OSError):
                self.host.op_vm_media(self.vm_id, iso.name)
        self.assertEqual(self.metadata.read_text(), self.xml)
        self.assertFalse(any(command[1] == "define" for command in self.calls))
        self.assertEqual(list(self.host.directory.glob("vm-linux.xml.*")), [])

    def test_media_rejects_unsupported_cdrom_or_per_device_boot(self):
        iso = self.create_iso()
        original = self.xml
        for kind in ("multiple-cdrom", "block-cdrom", "per-device-boot"):
            with self.subTest(kind=kind):
                document = ET.fromstring(original)
                devices = document.find("devices")
                if kind == "multiple-cdrom":
                    for _ in range(2):
                        ET.SubElement(devices, "disk", type="file", device="cdrom")
                elif kind == "block-cdrom":
                    ET.SubElement(devices, "disk", type="block", device="cdrom")
                else:
                    ET.SubElement(devices.find("disk"), "boot", order="1")
                self.xml = ET.tostring(document, encoding="unicode")
                with self.assertRaises(Error):
                    self.host.op_vm_media(self.vm_id, iso.name)
        self.assertEqual(self.metadata.read_text(), original)
        self.assertFalse(any(command[1] == "define" for command in self.calls))

    def test_atomic_metadata_update_never_writes_through_destination_symlink(self):
        outside = self.root / "must-not-change.xml"
        outside.write_text("retained outside data")
        self.metadata.unlink()
        self.metadata.symlink_to(outside)
        self.host.op_vm_update(self.vm_id, 1, 4096)
        self.assertEqual(outside.read_text(), "retained outside data")
        self.assertFalse(self.metadata.is_symlink())
        self.assertEqual(ET.fromstring(self.metadata.read_text()).findtext("uuid"), self.vm_id)

    def test_memory_parsing_honors_libvirt_units_and_rejects_malformed_values(self):
        for unit, value, expected in (("KiB", "2097152", 2048), ("MiB", "2048", 2048),
                                      ("GiB", "2", 2048), ("bytes", "2147483648", 2048),
                                      ("MB", "2048", 1953), ("GB", "2", 1907)):
            with self.subTest(unit=unit):
                document = ET.fromstring(self.xml)
                document.find("memory").set("unit", unit)
                document.find("memory").text = value
                self.assertEqual(self.host.vm_memory_mb(document), expected)
        for value in (None, "invalid", "0", "-10"):
            document = ET.fromstring(self.xml)
            document.find("memory").text = value
            with self.assertRaises(Error):
                self.host.vm_memory_mb(document)
        document = ET.fromstring(self.xml)
        document.find("memory").set("unit", "unknown")
        with self.assertRaises(Error):
            self.host.vm_memory_mb(document)

    def test_malformed_cpu_xml_is_reported_as_management_error(self):
        document = ET.fromstring(self.xml)
        document.find("vcpu").text = "invalid"
        self.xml = ET.tostring(document, encoding="unicode")
        with self.assertRaises(Error) as result:
            self.host.managed_vm(self.vm_id)
        self.assertEqual(result.exception.status, 409)

    def test_removal_retains_disk_and_ends_console_process(self):
        process = SimpleNamespace(poll=lambda: None, terminate=unittest.mock.Mock())
        self.host.console_processes[self.vm_id] = (process, 55001)
        result = self.host.op_vm_action(self.vm_id, "remove")
        self.assertTrue(result["disk_retained"])
        self.assertTrue(self.disk.is_file())
        self.assertEqual(self.host.load("vms", []), [])
        self.assertFalse(self.metadata.exists())
        process.terminate.assert_called_once()
        self.assertIn(["virsh", "undefine", self.vm_id], self.calls)

    def test_foreign_uuid_name_or_disk_is_rejected(self):
        original = self.xml
        transforms = [lambda root: setattr(root.find("name"), "text", "unmanaged"),
                      lambda root: setattr(root.find("uuid"), "text", str(uuid.uuid4())),
                      lambda root: root.find("./devices/disk/source").set("file", "/etc/passwd")]
        for transform in transforms:
            root = ET.fromstring(original)
            transform(root)
            self.xml = ET.tostring(root, encoding="unicode")
            with self.assertRaises(Error):
                self.host.managed_vm(self.vm_id)
        self.assertFalse(any(command[1] in ("define", "undefine") for command in self.calls))

    def test_missing_metadata_and_symlink_disk_are_rejected(self):
        self.host.save("vms", [])
        self.metadata.unlink()
        with self.assertRaises(Error):
            self.host.managed_vm(self.vm_id)
        self.host.save("vms", [{"id": self.vm_id, "name": self.name, "disk": str(self.disk)}])
        outside = self.root / "outside.qcow2"
        self.disk.rename(outside)
        self.disk.symlink_to(outside)
        with self.assertRaises(Error):
            self.host.managed_vm(self.vm_id)

    def test_legacy_vm_adoption_requires_original_name_and_disk(self):
        self.host.save("vms", [])
        record = self.host.managed_vm(self.vm_id)
        self.assertEqual(record["id"], self.vm_id)
        self.assertEqual(self.host.load("vms", [])[0]["id"], self.vm_id)

    def test_restore_definition_is_fresh_without_uuid_or_external_devices(self):
        restored = self.vm_root / "restored.qcow2"
        restored.write_bytes(b"new copied disk")
        root = ET.fromstring(self.host.vm_definition("restored", 1, 1024, restored))
        self.assertIsNone(root.find("uuid"))
        self.assertEqual(root.findtext("name"), "titan-restored")
        self.assertEqual(root.find("./devices/graphics").get("listen"), "127.0.0.1")
        self.assertEqual(root.find("./devices/interface/source").get("network"), "default")
        self.assertEqual(len(root.findall("./devices/disk")), 1)
        self.assertEqual(root.findall("./devices/hostdev"), [])
        with self.assertRaises(Error):
            self.host.vm_definition("restored", 1, 1024, "/outside.qcow2")

    def backup_manager(self):
        manager = unittest.mock.Mock()
        manager.settings.return_value = {"target": "/mnt/old-backup", "auto_backup": False}
        manager.create_vm.return_value = {"id": "b-20260930T200000-abcdef123456", "type": "vm"}
        manager.verified_vm.return_value = {"xml": self.xml, "type": "vm"}
        self.host._backups = manager
        patch.object(self.host, "op_vms", return_value={"available": True, "vms": []}).start()
        return manager

    def test_vm_backup_is_offline_and_uses_shared_validated_target(self):
        manager = self.backup_manager()
        result = self.host.op_vm_backup(self.vm_id, "/mnt/new-backup")
        manager.save_settings.assert_called_once_with({"target": "/mnt/new-backup"})
        manager.create_vm.assert_called_once_with("linux", self.xml, str(self.disk))
        self.assertEqual(result["backup"], "b-20260930T200000-abcdef123456")
        self.state = "running"
        manager.reset_mock()
        with self.assertRaises(Error):
            self.host.op_vm_backup(self.vm_id, "/mnt/new-backup")
        manager.save_settings.assert_not_called()
        manager.create_vm.assert_not_called()

    def test_failed_backup_restores_previous_shared_target(self):
        manager = self.backup_manager()
        manager.create_vm.side_effect = Error("backup drive disconnected")
        with self.assertRaises(Error):
            self.host.op_vm_backup(self.vm_id, "/mnt/new-backup")
        self.assertEqual(self.host.load("backup-settings", {}), manager.settings.return_value)

    def test_vm_restore_uses_new_name_uuid_and_sanitized_definition(self):
        manager = self.backup_manager()
        source = ET.fromstring(self.xml)
        ET.SubElement(source.find("devices"), "hostdev", type="pci")
        manager.verified_vm.return_value = {"xml": ET.tostring(source, encoding="unicode"), "type": "vm"}
        new_id = str(uuid.uuid4())
        original = self.command
        def command(arguments, **kwargs):
            if arguments == ["virsh", "domuuid", "titan-restored"]:
                return new_id
            return original(arguments, **kwargs)
        self.runner.side_effect = command
        def restore_files(backup, name):
            target = self.vm_root / (name + ".qcow2")
            target.write_bytes(b"restored from backup")
            return str(target)
        manager.restore_vm_files.side_effect = restore_files
        with patch("titan.vm_management.pwd.getpwnam", return_value=SimpleNamespace(pw_uid=2002, pw_gid=2002)), patch("titan.vm_management.os.fchown") as chown:
            result = self.host.op_vm_restore("backup-id", "restored")
            chown.assert_called_once()
        restored_xml = ET.fromstring((self.host.directory / "vm-restored.xml").read_text())
        self.assertEqual(result["id"], new_id)
        self.assertIsNone(restored_xml.find("uuid"))
        self.assertEqual(restored_xml.findall("./devices/hostdev"), [])
        self.assertEqual(restored_xml.find("./devices/disk/source").get("file"), str(self.vm_root / "restored.qcow2"))
        self.assertEqual(self.disk.read_bytes(), b"retained virtual disk")

    def test_restore_rejects_existing_disk_without_overwrite(self):
        manager = self.backup_manager()
        existing = self.vm_root / "existing.qcow2"
        existing.write_bytes(b"must survive")
        with self.assertRaises(Error):
            self.host.op_vm_restore("backup-id", "existing")
        manager.restore_vm_files.assert_not_called()
        self.assertEqual(existing.read_bytes(), b"must survive")

    def test_failed_restore_definition_removes_only_created_disk(self):
        manager = self.backup_manager()
        def restore_files(backup, name):
            target = self.vm_root / (name + ".qcow2")
            target.write_bytes(b"new copy")
            return str(target)
        manager.restore_vm_files.side_effect = restore_files
        original = self.command
        def command(arguments, **kwargs):
            if arguments[:2] == ["virsh", "define"]:
                raise Error("libvirt refused definition")
            return original(arguments, **kwargs)
        self.runner.side_effect = command
        with patch("titan.vm_management.pwd.getpwnam", return_value=SimpleNamespace(pw_uid=2002, pw_gid=2002)), patch("titan.vm_management.os.fchown"):
            with self.assertRaises(Error):
                self.host.op_vm_restore("backup-id", "restored")
        self.assertFalse((self.vm_root / "restored.qcow2").exists())
        self.assertFalse((self.host.directory / "vm-restored.xml").exists())
        self.assertTrue(self.disk.exists())


class AccountConcurrencyTests(unittest.TestCase):
    def test_account_dispatch_does_not_wait_for_long_running_file_job(self):
        with tempfile.TemporaryDirectory() as directory:
            host = Host(directory)
            entered = threading.Event()
            released = threading.Event()
            host.op_long_job = lambda: (entered.set(), released.wait(2))
            host.op_accounts = lambda: []
            worker = threading.Thread(target=host.dispatch, args=("long_job",))
            worker.start()
            self.assertTrue(entered.wait(1))
            try:
                self.assertEqual(host.dispatch("accounts"), [])
            finally:
                released.set()
                worker.join(2)
            self.assertFalse(worker.is_alive())

    def test_configuration_restore_maintenance_guard_blocks_mutations(self):
        with tempfile.TemporaryDirectory() as directory:
            host = Host(directory)
            (Path(directory) / "config-restore.lock").write_text("maintenance")
            with patch.object(host, "op_account_create") as operation:
                with self.assertRaises(Error) as result:
                    host.dispatch("account_create", name="alice", password="long-enough-password")
                self.assertEqual(result.exception.status, 503)
                operation.assert_not_called()


if __name__ == "__main__":
    unittest.main()

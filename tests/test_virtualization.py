import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from titan.core import Error
from titan.host import Host
from titan.virtualization import availability


class VirtualizationAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cpuinfo = self.root / "cpuinfo"
        self.cpuinfo.write_text("flags : fpu vmx sse\n")
        self.novnc = self.root / "rfb.js"
        self.novnc.write_text("export default class RFB {}\n")
        self.arch = patch("titan.virtualization.os.uname", return_value=SimpleNamespace(machine="x86_64"))
        self.tools = patch("titan.virtualization.shutil.which", return_value="/usr/bin/fixture")
        self.arch.start()
        self.tools.start()

    def tearDown(self):
        self.arch.stop()
        self.tools.stop()
        self.temp.cleanup()

    def test_missing_kvm_is_unavailable_despite_installed_vm_tools(self):
        result = availability(self.root / "missing", self.cpuinfo, self.novnc)
        self.assertTrue(result["installed"])
        self.assertFalse(result["available"])
        self.assertFalse(result["kvm"])
        self.assertIn("Kernelmodule", result["error"])

    def test_missing_cpu_features_explain_bios_and_nested_virtualization(self):
        self.cpuinfo.write_text("flags : fpu sse\n")
        result = availability(self.root / "missing", self.cpuinfo, self.novnc)
        self.assertIn("BIOS/UEFI", result["error"])
        self.assertIn("Hypervisor", result["error"])

    def test_missing_vm_packages_do_not_claim_hardware_is_cause(self):
        with patch("titan.virtualization.shutil.which", side_effect=lambda command, **kwargs: None if command == "websockify" else "/usr/bin/fixture"):
            result = availability(self.root / "missing", self.cpuinfo, self.novnc)
        self.assertFalse(result["installed"])
        self.assertEqual(result["missing"], ["websockify"])
        self.assertIn("Komponenten fehlen", result["error"])

    def test_only_accessible_character_device_is_available(self):
        with patch("titan.virtualization.Path.lstat", return_value=SimpleNamespace(st_mode=stat.S_IFCHR | 0o660)), patch("titan.virtualization.os.access", return_value=True):
            self.assertTrue(availability(novnc=self.novnc)["available"])
        with patch("titan.virtualization.Path.lstat", return_value=SimpleNamespace(st_mode=stat.S_IFCHR | 0o660)), patch("titan.virtualization.os.access", return_value=False):
            self.assertIn("Geräterechte", availability(novnc=self.novnc)["error"])
        ordinary = self.root / "ordinary-file"
        ordinary.touch()
        self.assertFalse(availability(ordinary, self.cpuinfo, self.novnc)["available"])
        symlink = self.root / "symlink"
        symlink.symlink_to("/dev/null")
        self.assertFalse(availability(symlink, self.cpuinfo, self.novnc)["available"])

    def test_missing_novnc_files_explain_browser_console_dependency(self):
        self.novnc.unlink()
        result = availability(self.root / "missing", self.cpuinfo, self.novnc)
        self.assertFalse(result["installed"])
        self.assertFalse(result["available"])
        self.assertEqual(result["missing"], ["noVNC"])
        self.assertIn("Browserkonsole", result["error"])

    def test_unsupported_architecture_keeps_nas_available(self):
        with patch("titan.virtualization.os.uname", return_value=SimpleNamespace(machine="aarch64")):
            result = availability()
        self.assertFalse(result["available"])
        self.assertIn("NAS funktioniert", result["error"])

    def test_host_vms_and_creation_fail_before_any_libvirt_or_disk_command(self):
        host = Host(self.root / "agent", self.root / "shares", self.root / "vms")
        status = {"available": False, "installed": True, "kvm": False, "missing": [], "error": "KVM fehlt"}
        with patch("titan.host.vm_availability", return_value=status), patch("titan.host.run") as command:
            self.assertEqual(host.op_vms(), {**status, "vms": []})
            with self.assertRaises(Error) as error:
                host.op_vm_create("test", 1, 1024, 8, "linux.iso")
            self.assertEqual(error.exception.status, 503)
            with self.assertRaises(Error):
                host.op_vm_action("unused", "start")
            command.assert_not_called()
        self.assertFalse((host.vm_root / "test.qcow2").exists())

    def test_available_kvm_still_reports_libvirt_service_failure(self):
        host = Host(self.root / "agent", self.root / "shares", self.root / "vms")
        with patch("titan.host.vm_availability", return_value={"available": True, "installed": True, "kvm": True, "missing": []}), patch("titan.host.run", side_effect=Error("libvirtd nicht erreichbar")):
            result = host.op_vms()
        self.assertFalse(result["available"])
        self.assertTrue(result["kvm"])
        self.assertIn("libvirtd", result["error"])


if __name__ == "__main__":
    unittest.main()

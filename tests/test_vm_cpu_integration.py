"""CPU policy changes on an owned VM, without any real libvirt commands."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid
import xml.etree.ElementTree as ET

from titan.core import Error
from titan.host import Host


class VMCPUIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.vm_root = self.root / "vms"
        self.vm_root.mkdir(mode=0o755)
        self.host = Host(self.root / "agent", self.root / "shares", self.vm_root, self.root / "smb.conf")
        self.disk = self.vm_root / "guest.qcow2"
        self.disk.write_bytes(b"unchanged virtual disk fixture")
        self.vm_id = str(uuid.uuid4())
        self.status = patch.object(self.host, "op_status", return_value={"memory_total": 16 * 1024**3}).start()
        self.cpu_count = patch("titan.vm_management.os.cpu_count", return_value=4).start()
        self.topology = patch.object(self.host, "cpu_topology", return_value={"online": [0, 2, 8]}).start()
        document = ET.fromstring(self.host.vm_definition("guest", 2, 2048, self.disk, cpu_ids=[2, 0]))
        ET.SubElement(document, "uuid").text = self.vm_id
        self.xml = ET.tostring(document, encoding="unicode")
        self.metadata = self.host.directory / "vm-guest.xml"
        self.metadata.write_text(self.xml)
        self.host.save("vms", [{"id": self.vm_id, "name": "guest", "disk": str(self.disk)}])
        self.commands = []
        self.runner = patch("titan.host.run", side_effect=self.command).start()

    def tearDown(self):
        patch.stopall()
        self.temp.cleanup()

    def command(self, arguments, **kwargs):
        self.commands.append(arguments)
        if arguments[:2] == ["virsh", "dumpxml"]:
            return self.xml
        if arguments[:2] == ["virsh", "domstate"]:
            return "shut off"
        return ""

    def test_vm_definition_and_owned_inventory_retain_cpu_zero_sparse_pool(self):
        root = ET.fromstring(self.xml)
        self.assertEqual(root.find("vcpu").get("placement"), "static")
        self.assertEqual(root.find("vcpu").get("cpuset"), "0,2")
        self.assertEqual(self.host.managed_vm(self.vm_id)["cpu_ids"], [0, 2])

    def test_ram_edit_without_cpu_ids_preserves_cpu_policy(self):
        result = self.host.op_vm_update(self.vm_id, 2, 4096)
        root = ET.fromstring(self.metadata.read_text())
        self.assertEqual(result["cpu_ids"], [0, 2])
        self.assertEqual(root.find("vcpu").get("cpuset"), "0,2")
        self.assertEqual(root.findtext("memory"), str(4096 * 1024))
        self.assertEqual(root.findtext("uuid"), self.vm_id)
        self.assertEqual(self.disk.read_bytes(), b"unchanged virtual disk fixture")

    def test_explicit_auto_removes_pool_without_changing_resources(self):
        result = self.host.op_vm_update(self.vm_id, 2, 2048, cpu_ids=[])
        self.assertEqual(result["cpu_ids"], [])
        root = ET.fromstring(self.metadata.read_text())
        self.assertIsNone(root.find("vcpu").get("cpuset"))
        self.assertEqual(root.findtext("vcpu"), "2")
        self.assertEqual(root.find("vcpu").get("placement"), "static")

    def test_offline_selection_rejected_before_metadata_or_libvirt_mutation(self):
        with self.assertRaises(Error) as result:
            self.host.op_vm_update(self.vm_id, 2, 2048, cpu_ids=[0, 3])
        self.assertEqual(result.exception.status, 409)
        self.assertEqual(self.metadata.read_text(), self.xml)
        self.assertFalse(any(command[:2] == ["virsh", "define"] for command in self.commands))


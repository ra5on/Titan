from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch
import uuid
import xml.etree.ElementTree as ET

from titan.core import Error
from titan.host import Host


CAPABILITY = {"available": True, "installed": True, "kvm": True, "missing": []}


class VMLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.vm_root = self.root / "vms"
        self.vm_root.mkdir(mode=0o755)
        self.host = Host(self.root / "agent", self.root / "shares", self.vm_root, self.root / "smb.conf")
        self.vm_id = str(uuid.uuid4())
        self.iso = self.host.iso_directory() / "linux.iso"
        self.iso.write_bytes(b"finalized ISO fixture")
        self.disk = self.vm_root / "linux.qcow2"
        self.disk.write_bytes(b"retained managed disk")
        self.status = patch.object(self.host, "op_status", return_value={"memory_total": 16 * 1024**3})
        self.status.start()
        self.document = ET.fromstring(self.host.vm_definition("linux", 2, 2048, self.disk, self.iso.name))
        ET.SubElement(self.document, "uuid").text = self.vm_id
        self.xml = ET.tostring(self.document, encoding="unicode")
        self.metadata = self.host.directory / "vm-linux.xml"
        self.metadata.write_text(self.xml)
        self.host.save("vms", [{"id": self.vm_id, "name": "linux", "disk": str(self.disk)}])

    def tearDown(self):
        self.status.stop()
        self.temp.cleanup()

    def test_inventory_parses_resources_media_and_autostart_and_isolates_invalid_guests(self):
        bad_id = str(uuid.uuid4())
        foreign_id = str(uuid.uuid4())
        self.document.find("memory").set("unit", "GiB")
        self.document.find("memory").text = "2"
        self.xml = ET.tostring(self.document, encoding="unicode")
        def command(arguments, **kwargs):
            if arguments[:2] == ["virsh", "list"]:
                return "\n".join((self.vm_id, bad_id, foreign_id))
            if arguments[:2] == ["virsh", "dumpxml"]:
                if arguments[2] == bad_id:
                    return "<broken"
                if arguments[2] == foreign_id:
                    return "<domain><name>foreign-guest</name></domain>"
                return self.xml
            if arguments[:2] == ["virsh", "domstate"]:
                return "shut off\n"
            if arguments[:2] == ["virsh", "dominfo"]:
                return "Name: titan-linux\nAutostart:          enable  \n"
            raise AssertionError(arguments)
        with patch("titan.host.vm_availability", return_value=CAPABILITY), patch("titan.host.run", side_effect=command):
            result = self.host.op_vms()
        self.assertTrue(result["available"])
        self.assertEqual(len(result["vms"]), 1)
        record = result["vms"][0]
        self.assertEqual(record["id"], self.vm_id)
        self.assertEqual(record["memory_mb"], 2048)
        self.assertEqual(record["cpus"], 2)
        self.assertEqual(record["state"], "shut off")
        self.assertTrue(record["autostart"])
        self.assertEqual(record["iso"], "linux.iso")
        self.assertEqual(record["boot"], "cdrom")
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn(bad_id, result["warnings"][0])

    def test_inventory_excludes_unregistered_or_mismatched_managed_uuid(self):
        self.host.save("vms", [{"id": str(uuid.uuid4()), "name": "linux", "disk": str(self.disk)}])
        def command(arguments, **kwargs):
            return self.vm_id if arguments[:2] == ["virsh", "list"] else self.xml
        with patch("titan.host.vm_availability", return_value=CAPABILITY), patch("titan.host.run", side_effect=command):
            result = self.host.op_vms()
        self.assertTrue(result["available"])
        self.assertEqual(result["vms"], [])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("UUID", result["warnings"][0])

    def test_network_activates_and_persists_default_nat_when_inactive(self):
        command = Mock(side_effect=lambda args, **kwargs: "Active:   no\n" if args[1] == "net-info" else "")
        with patch("titan.host.run", command):
            self.host.vm_network_ready()
        self.assertEqual([call.args[0] for call in command.call_args_list], [
            ["virsh", "net-info", "default"], ["virsh", "net-start", "default"],
            ["virsh", "net-autostart", "default"]])

    def test_active_network_is_not_started_again_but_autostart_is_confirmed(self):
        command = Mock(side_effect=lambda args, **kwargs: "Active:\tyes\n" if args[1] == "net-info" else "")
        with patch("titan.host.run", command):
            self.host.vm_network_ready()
        self.assertEqual([call.args[0] for call in command.call_args_list], [
            ["virsh", "net-info", "default"], ["virsh", "net-autostart", "default"]])

    def test_network_failure_is_reported_before_vm_start(self):
        with patch.object(self.host, "op_vms", return_value={"available": True}), \
                patch.object(self.host, "vm_id", return_value=self.vm_id), \
                patch.object(self.host, "managed_vm", return_value={"xml": self.xml}), \
                patch("titan.host.run", side_effect=Error("default network missing")) as command:
            with self.assertRaises(Error) as result:
                self.host.op_vm_action(self.vm_id, "start")
        self.assertEqual(result.exception.status, 503)
        self.assertIn("Netzwerk", str(result.exception))
        self.assertEqual([call.args[0] for call in command.call_args_list], [["virsh", "net-info", "default"]])

    def test_vm_start_checks_network_then_invalidates_previous_console_bridge(self):
        old = Mock()
        old.poll.return_value = None
        self.host.console_processes[self.vm_id] = (old, 50001, 5900)
        events = []
        with patch.object(self.host, "op_vms", return_value={"available": True}), \
                patch.object(self.host, "vm_id", return_value=self.vm_id), \
                patch.object(self.host, "managed_vm", return_value={"xml": self.xml}), \
                patch.object(self.host, "vm_network_ready", side_effect=lambda: events.append("network")), \
                patch("titan.host.run", side_effect=lambda args, **kwargs: events.append(args)):
            self.host.op_vm_action(self.vm_id, "start")
        self.assertEqual(events, ["network", ["virsh", "start", self.vm_id]])
        old.terminate.assert_called_once()
        self.assertNotIn(self.vm_id, self.host.console_processes)

    def creation_command(self, failure=None):
        def command(arguments, **kwargs):
            if arguments[:2] == ["qemu-img", "create"]:
                Path(arguments[4]).write_bytes(b"newly allocated virtual disk")
                if failure == "qemu-img":
                    raise Error("disk allocation failed after partial creation")
            if arguments[:2] == ["virsh", "define"] and failure == "define":
                raise Error("libvirt refused definition")
            if arguments[:2] == ["virsh", "domuuid"]:
                return str(uuid.uuid4())
            return ""
        return command

    def test_creation_success_registers_disk_iso_and_definition_without_starting_guest(self):
        with patch.object(self.host, "op_vms", return_value={"available": True, "vms": []}), \
                patch.object(self.host, "vm_network_ready") as network, \
                patch("titan.host.pwd.getpwnam", return_value=SimpleNamespace(pw_uid=1001, pw_gid=1001)), \
                patch("titan.host.os.chown"), \
                patch("titan.host.run", side_effect=self.creation_command()) as command:
            result = self.host.op_vm_create("fresh", 1, 1024, 8, self.iso.name)
        self.assertTrue(result["ok"])
        network.assert_called_once()
        self.assertTrue((self.vm_root / "fresh.qcow2").is_file())
        definition = ET.fromstring((self.host.directory / "vm-fresh.xml").read_text())
        self.assertEqual(definition.find("./devices/disk[@device='cdrom']/source").get("file"), str(self.iso))
        self.assertEqual(self.host.load("vms", [])[1]["id"], result["id"])
        self.assertFalse(any(call.args[0][:2] == ["virsh", "start"] for call in command.call_args_list))

    def test_creation_removes_partial_disk_and_metadata_on_all_allocation_setup_failures(self):
        for failure in ("qemu-img", "chmod", "chown", "definition", "define"):
            with self.subTest(failure=failure):
                name = "failed_" + failure.replace("-", "_")
                original_definition = self.host.vm_definition
                original_chmod = __import__("os").chmod
                def chmod(path, mode, **kwargs):
                    if failure == "chmod" and Path(path).suffix == ".qcow2":
                        raise PermissionError("disk permission setup failed")
                    return original_chmod(path, mode, **kwargs)
                def definition(*args, **kwargs):
                    if failure == "definition":
                        raise Error("invalid VM definition")
                    return original_definition(*args, **kwargs)
                with patch.object(self.host, "op_vms", return_value={"available": True, "vms": []}), \
                        patch.object(self.host, "vm_network_ready"), \
                        patch.object(self.host, "vm_definition", side_effect=definition), \
                        patch("titan.host.pwd.getpwnam", return_value=SimpleNamespace(pw_uid=1001, pw_gid=1001)), \
                        patch("titan.host.os.chmod", side_effect=chmod), \
                        patch("titan.host.os.chown", side_effect=PermissionError("owner setup failed") if failure == "chown" else None), \
                        patch("titan.host.run", side_effect=self.creation_command(failure)):
                    with self.assertRaises((Error, PermissionError)):
                        self.host.op_vm_create(name, 1, 1024, 8, self.iso.name)
                self.assertFalse((self.vm_root / (name + ".qcow2")).exists())
                self.assertFalse((self.host.directory / ("vm-" + name + ".xml")).exists())
                self.assertEqual(self.disk.read_bytes(), b"retained managed disk")

    def test_creation_rejects_dangling_disk_and_actual_metadata_paths_before_allocating(self):
        for kind in ("disk", "metadata"):
            with self.subTest(kind=kind):
                name = "retained_" + kind
                path = self.vm_root / (name + ".qcow2") if kind == "disk" else self.host.directory / ("vm-" + name + ".xml")
                outside = self.root / ("missing-" + kind)
                path.symlink_to(outside)
                with patch.object(self.host, "op_vms", return_value={"available": True, "vms": []}), \
                        patch("titan.host.run") as command, patch.object(self.host, "vm_network_ready") as network:
                    with self.assertRaises(Error):
                        self.host.op_vm_create(name, 1, 1024, 8, self.iso.name)
                command.assert_not_called()
                network.assert_not_called()
                self.assertTrue(path.is_symlink())
                self.assertFalse(outside.exists())

    def console_xml(self, port="5901", listen="127.0.0.1"):
        document = ET.fromstring(self.xml)
        graphics = document.find("./devices/graphics")
        graphics.set("port", port)
        graphics.set("listen", listen)
        return ET.tostring(document, encoding="unicode")

    def mocked_console(self, xml=None, child=None):
        child = child or Mock()
        child.poll.return_value = None
        socket = MagicMock()
        socket.__enter__.return_value = socket
        socket.getsockname.return_value = ("127.0.0.1", 51001)
        connection = MagicMock()
        return (patch.object(self.host, "vm_id", return_value=self.vm_id),
                patch("titan.host.run", return_value=xml or self.console_xml()),
                patch("titan.host.socket.socket", return_value=socket),
                patch("titan.host.socket.create_connection", return_value=connection),
                patch("titan.host.subprocess.Popen", return_value=child))

    def test_console_reuses_only_live_bridge_for_current_guest_vnc_port(self):
        child = Mock()
        child.poll.return_value = None
        self.host.console_processes[self.vm_id] = (child, 50001, 5901)
        patches = self.mocked_console()
        with patches[0], patches[1], patches[2] as socket, patches[3] as connect, patches[4] as popen:
            result = self.host.op_console(self.vm_id)
        self.assertEqual(result, {"port": 50001})
        child.terminate.assert_not_called()
        socket.assert_not_called()
        connect.assert_not_called()
        popen.assert_not_called()

    def test_console_replaces_bridge_when_guest_vnc_port_changes_or_old_record_lacks_target(self):
        for record_size in (2, 3):
            with self.subTest(record_size=record_size):
                old = Mock()
                old.poll.return_value = None
                new = Mock()
                self.host.console_processes[self.vm_id] = (old, 50001) if record_size == 2 else (old, 50001, 5900)
                patches = self.mocked_console(child=new)
                with patches[0], patches[1], patches[2] as socket, patches[3] as connect, patches[4] as popen:
                    result = self.host.op_console(self.vm_id)
                old.terminate.assert_called_once()
                self.assertEqual(result, {"port": 51001})
                self.assertEqual(self.host.console_processes[self.vm_id], (new, 51001, 5901))
                self.assertEqual(popen.call_args.args[0], ["websockify", "127.0.0.1:51001", "127.0.0.1:5901"])
                connect.assert_called_once_with(("127.0.0.1", 51001), timeout=0.2)
                socket.assert_called_once()

    def test_console_replaces_exited_bridge_even_when_guest_port_matches(self):
        old = Mock()
        old.poll.return_value = 0
        new = Mock()
        self.host.console_processes[self.vm_id] = (old, 50001, 5901)
        patches = self.mocked_console(child=new)
        with patches[0], patches[1], patches[2], patches[3], patches[4] as popen:
            result = self.host.op_console(self.vm_id)
        self.assertEqual(result, {"port": 51001})
        old.terminate.assert_not_called()
        popen.assert_called_once()
        self.assertEqual(self.host.console_processes[self.vm_id], (new, 51001, 5901))

    def test_console_failed_proxy_start_does_not_leave_cached_bridge(self):
        child = Mock()
        patches = self.mocked_console(child=child)
        child.poll.return_value = 1
        with patches[0], patches[1], patches[2], patches[3] as connect, patches[4]:
            with self.assertRaisesRegex(Error, "konnte nicht starten"):
                self.host.op_console(self.vm_id)
        connect.assert_not_called()
        self.assertNotIn(self.vm_id, self.host.console_processes)

    def test_console_waits_for_slow_proxy_under_nested_virtualization(self):
        child = Mock()
        patches = self.mocked_console(child=child)
        with patches[0], patches[1], patches[2], patches[3] as connect, patches[4], patch("titan.host.time.sleep"):
            connect.side_effect = [OSError("starting")] * 60 + [MagicMock()]
            self.assertEqual(self.host.op_console(self.vm_id), {"port": 51001})
        self.assertEqual(connect.call_count, 61)
        child.terminate.assert_not_called()
        self.assertEqual(self.host.console_processes[self.vm_id], (child, 51001, 5901))

    def test_console_connection_timeout_terminates_proxy_and_does_not_cache_it(self):
        child = Mock()
        patches = self.mocked_console(child=child)
        with patches[0], patches[1], patches[2], patches[3] as connect, patches[4], patch("titan.host.time.sleep"):
            connect.side_effect = OSError("proxy not listening")
            with self.assertRaisesRegex(Error, "nicht erreichbar"):
                self.host.op_console(self.vm_id)
        self.assertEqual(connect.call_count, 300)
        child.terminate.assert_called_once()
        self.assertNotIn(self.vm_id, self.host.console_processes)

    def test_console_rejects_non_loopback_invalid_or_inactive_target_before_proxy_spawn(self):
        for port, listen in (("-1", "127.0.0.1"), ("5899", "127.0.0.1"),
                             ("65536", "127.0.0.1"), ("5901", "0.0.0.0")):
            with self.subTest(port=port, listen=listen):
                patches = self.mocked_console(self.console_xml(port, listen))
                with patches[0], patches[1], patches[2] as socket, patches[3] as connect, patches[4] as popen:
                    with self.assertRaises(Error):
                        self.host.op_console(self.vm_id)
                socket.assert_not_called()
                connect.assert_not_called()
                popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()

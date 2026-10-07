"""Offline, reversible VM hardware, clone and checkpoint operations.

Snapshots are qcow2 internal disk checkpoints made only after shutdown. They
contain all managed disks plus the inactive XML and UEFI variables; no running
memory is captured and they are not a substitute for an external backup.
"""
import contextlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import time
import uuid
import xml.etree.ElementTree as ET

from .backups import directory_fd
from .core import Error, atomic_json, identifier, integer
from .platforms import current as host_platform
from .vm_names import display_name as vm_display_name, identity as vm_identity, set_title as set_vm_title


class VMExtensionsMixin:
    def _offline_vm(self, vm, shutdown=False):
        if type(shutdown) is not bool:
            raise Error("Herunterfahren muss Ja oder Nein sein.")
        record = self.managed_vm(vm)
        if shutdown and record["state"] in ("running", "in shutdown"):
            if record["state"] == "running":
                self.op_vm_action(vm, "shutdown")
            deadline = time.monotonic() + 120
            while record["state"] != "shut off":
                if time.monotonic() >= deadline:
                    raise Error("Die VM wurde innerhalb von 120 Sekunden nicht vollständig heruntergefahren. Es wurde keine Sicherung erstellt und die VM nicht zwangsweise ausgeschaltet. Im Gast herunterfahren und erneut versuchen.", 409)
                time.sleep(1)
                record = self.managed_vm(vm)
        if record["state"] != "shut off":
            raise Error("Die VM zuerst vollständig herunterfahren. Diese Änderung erfolgt im ausgeschalteten Zustand.", 409)
        return record

    def _vm_registry_replace(self, vm, **changes):
        records = self.load("vms", [])
        found = False
        for item in records:
            if item["id"] == vm:
                item.update(changes)
                found = True
        if not found:
            raise Error("VM-Verwaltungsdaten fehlen.", 409)
        self.save("vms", records)

    @contextlib.contextmanager
    def _vm_disk_fd(self, record, disk, writable=False):
        self.validate_vm_disk_path(record["name"], disk["disk"], disk.get("storage"), disk.get("storage_uuid"))
        with self.vm_storage_fd(disk["storage"]) as (parent, _):
            fd = os.open(Path(disk["disk"]).name, (os.O_RDWR if writable else os.O_RDONLY) | os.O_NOFOLLOW, dir_fd=parent)
            try:
                metadata = os.fstat(fd)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise Error("VM-Laufwerk ist keine eigenständige reguläre Datei.", 409)
                self.vm_image_header(fd, "qcow2")
                yield fd
            finally:
                os.close(fd)

    def _vm_snapshot_root(self, vm, create=False):
        # UUID comes from managed_vm, never directly from the caller.
        path = self.directory / "vm-snapshots" / str(uuid.UUID(vm))
        if create:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.exists():
            return path
        with directory_fd(path) as fd:
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise Error("Unsicheres VM-Snapshot-Verzeichnis.", 503)
        return path

    def _vm_snapshot_records(self, record):
        root = self._vm_snapshot_root(record["id"])
        if not root.exists():
            return []
        result = []
        for path in sorted(root.glob("s-*.json")):
            if not re.fullmatch(r"s-[a-f0-9]{32}\.json", path.name):
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd) as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 1024 * 1024:
                        raise Error("Unsichere VM-Snapshot-Metadaten.", 503)
                    value = json.load(stream)
                if not isinstance(value, dict) or value.get("id") != path.stem or value.get("vm") != record["id"] or not isinstance(value.get("disks"), list):
                    raise Error("VM-Snapshot-Metadaten stimmen nicht überein.", 503)
                result.append(value)
            except (OSError, ValueError, TypeError):
                raise Error("VM-Snapshot-Metadaten sind nicht lesbar.", 503) from None
        return result

    def _vm_snapshot(self, record, snapshot):
        if not isinstance(snapshot, str) or not re.fullmatch(r"s-[a-f0-9]{32}", snapshot):
            raise Error("Ungültige Snapshot-ID.")
        value = next((item for item in self._vm_snapshot_records(record) if item["id"] == snapshot), None)
        if value is None:
            raise Error("Snapshot wurde nicht gefunden.", 404)
        if value["disks"] != [{"disk": item["disk"], "target": item["target"]} for item in record["disks"]]:
            raise Error("Laufwerke und Snapshot passen nicht mehr zusammen.", 409)
        return value

    def _vm_qcow_snapshot(self, record, disk, action, name):
        if action not in ("-c", "-a", "-d") or not re.fullmatch(r"(?:s|undo)-[a-f0-9]{32}", name):
            raise Error("Ungültige interne Snapshot-Operation.")
        with self._vm_disk_fd(record, disk, writable=True) as fd:
            if action == "-d":
                info = json.loads(self.command(["qemu-img", "info", "--output=json", "-f", "qcow2", "/proc/self/fd/" + str(fd)], pass_fds=(fd,), timeout=30))
                if not any(item.get("name") == name for item in info.get("snapshots", []) if isinstance(item, dict)):
                    return ""
            # QEMU 8.2's snapshot command supports --image-opts but not -f.
            # Keep the driver explicit and operate only on the checked, pinned
            # descriptor rather than relying on format autodetection or paths.
            image = "driver=qcow2,file.driver=file,file.filename=/proc/self/fd/" + str(fd)
            return self.command(["qemu-img", "snapshot", "--image-opts", action, name, image], pass_fds=(fd,), timeout=600)

    def op_vm_extensions(self, vm):
        record = self.managed_vm(vm)
        root = ET.fromstring(record["xml"])
        disks = []
        for disk in record["disks"]:
            size, allocated = None, None
            try:
                with self._vm_disk_fd(record, disk) as fd:
                    size = self.vm_image_probe(fd, "qcow2")["virtual-size"]
                    allocated = os.fstat(fd).st_blocks * 512
            except (Error, OSError):
                pass
            disks.append({**disk, "virtual_size": size, "allocated_bytes": allocated, "boot": disk["disk"] == record["disk"]})
        snapshots = [{key: item[key] for key in ("id", "name", "created", "disk_count", "mode")} for item in self._vm_snapshot_records(record)]
        agent = self._vm_guest_info(record)
        return {"vm": record["id"], "state": record["state"], "disks": disks, "networks": self.vm_network_interfaces(root),
                "snapshots": snapshots, "guest_agent": agent, "offline_required": True,
                "snapshot_note": "Vollständige Laufwerks-Snapshots bei ausgeschalteter VM; RAM wird nicht gespeichert. Snapshots bleiben auf denselben Laufwerken und ersetzen keine externe Sicherung.",
                "external_backup_available": True}

    def _vm_guest_info(self, record):
        root = ET.fromstring(record["xml"])
        configured = root.find("./devices/channel/target[@name='org.qemu.guest_agent.0']") is not None
        result = {"configured": configured, "connected": False, "interfaces": [], "message": "QEMU-Gastagent im Gastsystem installieren und aktivieren." if configured else "Gastagent-Kanal ist deaktiviert."}
        if not configured or record["state"] != "running":
            return result
        try:
            response = json.loads(self.command(["virsh", "qemu-agent-command", record["id"], '{"execute":"guest-ping"}', "--timeout", "3"], timeout=5))
            if "return" not in response:
                raise Error("Gastagent antwortet nicht.")
            result.update(connected=True, message="Gastagent verbunden. Sauberes Herunterfahren und Gast-IP-Adressen verfügbar.")
            interfaces = json.loads(self.command(["virsh", "qemu-agent-command", record["id"], '{"execute":"guest-network-get-interfaces"}', "--timeout", "3"], timeout=5)).get("return", [])
            if isinstance(interfaces, list):
                for interface in interfaces[:32]:
                    if not isinstance(interface, dict): continue
                    addresses = [item.get("ip-address") for item in interface.get("ip-addresses", [])[:32] if isinstance(item, dict) and isinstance(item.get("ip-address"), str)]
                    result["interfaces"].append({"name": str(interface.get("name", ""))[:64], "mac": str(interface.get("hardware-address", ""))[:32], "addresses": addresses})
        except (Error, ValueError, TypeError, AttributeError):
            if not result["connected"]:
                result["message"] = "Gastagent-Kanal vorhanden, aber der Dienst im Gastsystem antwortet noch nicht."
        return result

    def op_vm_guest_agent(self, vm, enabled):
        if not isinstance(enabled, bool):
            raise Error("Gastagent-Einstellung muss Ja oder Nein sein.")
        record = self._offline_vm(vm)
        root = ET.fromstring(record["xml"])
        devices = root.find("devices")
        for channel in list(devices.findall("channel")):
            target = channel.find("target")
            if target is not None and target.get("name") == "org.qemu.guest_agent.0": devices.remove(channel)
        if enabled:
            channel = ET.SubElement(devices, "channel", type="unix")
            ET.SubElement(channel, "target", type="virtio", name="org.qemu.guest_agent.0")
        self.redefine_vm(record, root)
        return {"ok": True, "enabled": enabled, "message": "Kanal gespeichert. Im Gastsystem zusätzlich qemu-guest-agent installieren und aktivieren."}

    def op_vm_guest_action(self, vm, action):
        if action not in ("shutdown", "reboot"):
            raise Error("Ungültige Gastagent-Aktion.")
        record = self.managed_vm(vm)
        if not self._vm_guest_info(record)["connected"]:
            raise Error("Gastagent ist nicht verbunden. Reguläres Herunterfahren über die VM-Aktionen verwenden.", 409)
        output = self.command(["virsh", action, record["id"], "--mode", "agent"], timeout=30)
        return {"ok": True, "output": output, "mode": "agent"}

    def op_vm_disk_add(self, vm, disk_gb, storage="system"):
        record = self._offline_vm(vm)
        if len(record["disks"]) >= 8:
            raise Error("Titan unterstützt bis zu acht Laufwerke pro VM.")
        if self._vm_snapshot_records(record):
            raise Error("Vor dem Ändern der Laufwerksanzahl vorhandene Snapshots entfernen. Externe Sicherungen bleiben erhalten.", 409)
        disk_gb = integer(disk_gb, 1, 16384)
        root = ET.fromstring(record["xml"])
        used = {disk["target"] for disk in record["disks"]}
        target = next("vd" + char for char in "bcdefghijklmnopqrstuvwxyz" if "vd" + char not in used)
        filename = record["name"] + "--" + uuid.uuid4().hex + ".qcow2"
        with self.vm_storage_fd(storage, create=True) as (parent, location):
            path = Path(location["path"]) / filename
            # vm_storage_record.path already names the vms subdirectory.
            fd = os.open(filename, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o660, dir_fd=parent)
            try:
                owner = pwd.getpwnam(host_platform().qemu_user)
                os.fchown(fd, owner.pw_uid, owner.pw_gid)
                os.fchmod(fd, 0o660)
                self.command(["qemu-img", "create", "-f", "qcow2", "/proc/self/fd/" + str(fd), str(disk_gb) + "G"], pass_fds=(fd,), timeout=60)
            except Exception:
                os.unlink(filename, dir_fd=parent)
                raise
            finally:
                os.close(fd)
        self.vm_storage_label(path)
        extra = {"disk": str(path), "storage": location["id"], "target": target, "virtual_size": disk_gb * 1024 ** 3}
        if location.get("uuid"): extra["storage_uuid"] = location["uuid"]
        previous = self.load("vms", [])
        old = next(item for item in previous if item["id"] == record["id"]).get("extra_disks", [])
        node = ET.SubElement(root.find("devices"), "disk", type="file", device="disk")
        ET.SubElement(node, "driver", name="qemu", type="qcow2")
        ET.SubElement(node, "source", file=str(path))
        ET.SubElement(node, "target", dev=target, bus="virtio")
        try:
            self._vm_registry_replace(record["id"], extra_disks=old + [extra])
            self.redefine_vm(record, root)
        except Exception as failure:
            if getattr(failure, "retain_vm_files", False):
                # The new disk may already be referenced by libvirt. Preserve
                # both its metadata and bytes until the definition is confirmed.
                raise
            self.save("vms", previous)
            path.unlink(missing_ok=True)
            raise
        return {"ok": True, "disk": extra, "message": "Zusätzliches Laufwerk angelegt. Im Gastsystem partitionieren und formatieren."}

    def op_vm_disk_remove(self, vm, target):
        record = self._offline_vm(vm)
        if self._vm_snapshot_records(record):
            raise Error("Vor dem Entfernen eines Laufwerks vorhandene Snapshots entfernen.", 409)
        disk = next((item for item in record["disks"][1:] if item["target"] == target), None)
        if disk is None:
            raise Error("Nur ein zusätzliches Laufwerk kann getrennt werden.")
        root = ET.fromstring(record["xml"])
        devices = root.find("devices")
        node = next(node for node in devices.findall("disk[@device='disk']") if node.find("target").get("dev") == target)
        devices.remove(node)
        previous = self.load("vms", [])
        extra = next(item for item in previous if item["id"] == record["id"]).get("extra_disks", [])
        try:
            self._vm_registry_replace(record["id"], extra_disks=[item for item in extra if item["target"] != target])
            self.redefine_vm(record, root)
        except Exception:
            self.save("vms", previous)
            raise
        return {"ok": True, "disk_retained": True, "disk": disk["disk"], "message": "Laufwerk getrennt. Die Image-Datei bleibt erhalten."}

    def op_vm_nic_add(self, vm, network):
        record = self._offline_vm(vm)
        root = ET.fromstring(record["xml"])
        if len(root.findall("./devices/interface")) >= 8:
            raise Error("Titan unterstützt bis zu acht Netzwerkkarten pro VM.")
        if not isinstance(network, dict) or network.get("mode") == "none":
            raise Error("Für die neue Netzwerkkarte ein verfügbares Netzwerk auswählen.")
        temporary = ET.fromstring(record["xml"])
        for node in list(temporary.findall("./devices/interface")): temporary.find("devices").remove(node)
        self.apply_vm_network(temporary, network)
        node = temporary.find("./devices/interface")
        existing = {item.find("mac").get("address", "").lower() for item in root.findall("./devices/interface") if item.find("mac") is not None}
        mac = node.find("mac")
        if mac is not None and mac.get("address", "").lower() in existing:
            raise Error("Diese MAC-Adresse gehört bereits zu einer Netzwerkkarte dieser VM.", 409)
        root.find("devices").append(node)
        self.redefine_vm(record, root)
        return {"ok": True, "message": "Netzwerkkarte hinzugefügt."}

    def op_vm_nic_remove(self, vm, index):
        record = self._offline_vm(vm)
        root = ET.fromstring(record["xml"])
        nodes = root.findall("./devices/interface")
        index = integer(index, 0, max(0, len(nodes) - 1))
        if not nodes:
            raise Error("Die VM besitzt keine Netzwerkkarte.")
        root.find("devices").remove(nodes[index])
        self.redefine_vm(record, root)
        return {"ok": True, "message": "Netzwerkkarte entfernt."}

    def op_vm_snapshot_create(self, vm, name, shutdown=False):
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or any(ord(char) < 32 for char in name):
            raise Error("Snapshot-Name muss 1–80 sichtbare Zeichen enthalten.")
        record = self._offline_vm(vm, shutdown=shutdown)
        if len(self._vm_snapshot_records(record)) >= 32:
            raise Error("Bis zu 32 Snapshots pro VM werden unterstützt.")
        snapshot = "s-" + uuid.uuid4().hex
        path = self._vm_snapshot_root(record["id"], create=True)
        completed = []
        value = {"id": snapshot, "vm": record["id"], "name": name.strip(), "created": time.time(), "mode": "offline-disks",
                 "disk_count": len(record["disks"]), "disks": [{"disk": item["disk"], "target": item["target"]} for item in record["disks"]], "xml": record["xml"]}
        nvram = ET.fromstring(record["xml"]).findtext("./os/nvram")
        try:
            if nvram:
                expected = self.vm_instance_nvram_path(record["name"], record["disk"])
                if Path(nvram) != expected:
                    raise Error("UEFI-Variablenpfad passt nicht zur VM.", 409)
                with directory_fd(expected.parent) as parent:
                    source = os.open(expected.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
                    with os.fdopen(source, "rb") as stream:
                        metadata = os.fstat(stream.fileno())
                        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 16 * 1024 ** 2:
                            raise Error("UEFI-Variablen sind nicht lesbar.", 409)
                        nvram_bytes = stream.read()
                destination = path / (snapshot + ".nvram")
                fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "wb") as stream: stream.write(nvram_bytes)
                value["nvram"] = str(expected)
            for disk in record["disks"]:
                self._vm_qcow_snapshot(record, disk, "-c", snapshot)
                completed.append(disk)
            atomic_json(path / (snapshot + ".json"), value)
        except Exception:
            cleanup_failed = False
            for disk in completed:
                try: self._vm_qcow_snapshot(record, disk, "-d", snapshot)
                except Error: cleanup_failed = True
            if cleanup_failed:
                value["incomplete"] = True
                atomic_json(path / (snapshot + ".json"), value)
                raise Error("Snapshot unvollständig; verbleibende Teile können über Snapshot entfernen bereinigt werden.", 503) from None
            (path / (snapshot + ".nvram")).unlink(missing_ok=True)
            raise
        return {"ok": True, "snapshot": {key: value[key] for key in ("id", "name", "created", "disk_count", "mode")}, "message": "Alle VM-Laufwerke und die ausgeschaltete Konfiguration gesichert."}

    def op_vm_snapshot_remove(self, vm, snapshot):
        record = self._offline_vm(vm)
        value = self._vm_snapshot(record, snapshot)
        failures = []
        for disk in record["disks"]:
            try: self._vm_qcow_snapshot(record, disk, "-d", value["id"])
            except Error as exc: failures.append(str(exc))
        if failures:
            raise Error("Nicht alle Snapshot-Teile konnten entfernt werden. Metadaten bleiben für einen erneuten Versuch erhalten.", 503)
        path = self._vm_snapshot_root(record["id"])
        (path / (snapshot + ".json")).unlink()
        (path / (snapshot + ".nvram")).unlink(missing_ok=True)
        return {"ok": True, "message": "Snapshot entfernt; die VM-Dateien bleiben erhalten."}

    def op_vm_snapshot_restore(self, vm, snapshot):
        record = self._offline_vm(vm)
        value = self._vm_snapshot(record, snapshot)
        if value.get("incomplete"):
            raise Error("Ein unvollständiger Snapshot kann nicht wiederhergestellt werden.", 409)
        root = ET.fromstring(value["xml"])
        if root.findtext("uuid") != record["id"] or root.findtext("name") != "titan-" + record["name"]:
            raise Error("Snapshot-Konfiguration passt nicht zur VM.", 409)
        paths = [node.find("source").get("file") for node in root.findall("./devices/disk[@device='disk']")]
        if paths != [disk["disk"] for disk in record["disks"]]:
            raise Error("Snapshot-Konfiguration enthält abweichende Laufwerke.", 409)
        saved_nvram = None
        current_nvram = None
        if value.get("nvram"):
            expected = self.vm_instance_nvram_path(record["name"], record["disk"])
            if value["nvram"] != str(expected):
                raise Error("UEFI-Snapshot gehört nicht zu dieser VM.", 409)
            self.validate_vm_firmware("uefi")
            with directory_fd(self._vm_snapshot_root(record["id"])) as parent:
                fd = os.open(snapshot + ".nvram", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
                with os.fdopen(fd, "rb") as stream:
                    if os.fstat(stream.fileno()).st_size > 16 * 1024 ** 2: raise Error("UEFI-Snapshot ist ungültig.")
                    saved_nvram = stream.read()
            with directory_fd(expected.parent) as parent:
                fd = os.open(expected.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
                with os.fdopen(fd, "rb") as stream: current_nvram = stream.read(16 * 1024 ** 2 + 1)
        undo = "undo-" + uuid.uuid4().hex
        checkpoints = []
        try:
            for disk in record["disks"]:
                self._vm_qcow_snapshot(record, disk, "-c", undo)
                checkpoints.append(disk)
            for disk in record["disks"]: self._vm_qcow_snapshot(record, disk, "-a", snapshot)
            if saved_nvram is not None: self._vm_write_nvram(Path(value["nvram"]), saved_nvram)
            self.redefine_vm(record, root)
        except Exception:
            failed = False
            for disk in checkpoints:
                try: self._vm_qcow_snapshot(record, disk, "-a", undo)
                except Error: failed = True
            if current_nvram is not None:
                try: self._vm_write_nvram(Path(value["nvram"]), current_nvram)
                except (Error, OSError): failed = True
            if failed:
                raise Error("Wiederherstellung fehlgeschlagen. Sicherheits-Snapshot " + undo + " bleibt zur manuellen Wiederherstellung erhalten; VM ausgeschaltet lassen.", 503) from None
            raise
        finally:
            # A failed rollback keeps its undo checkpoints for manual recovery.
            if not locals().get("failed", False):
                for disk in checkpoints:
                    try: self._vm_qcow_snapshot(record, disk, "-d", undo)
                    except Error: pass
        return {"ok": True, "message": "Snapshot wiederhergestellt. Die VM bleibt ausgeschaltet."}

    @staticmethod
    def _vm_write_nvram(path, content):
        with directory_fd(path.parent) as parent:
            fd = os.open(path.name, os.O_WRONLY | os.O_NOFOLLOW, dir_fd=parent)
            with os.fdopen(fd, "wb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode): raise Error("Unsichere UEFI-Variablen.")
                stream.write(content)
                stream.truncate()
                stream.flush()
                os.fsync(stream.fileno())

    def op_vm_snapshot_restore_new(self, vm, snapshot, name, storage="system", shutdown=False):
        # Export the checkpoint directly. Applying it to the source, even only
        # temporarily, would risk replacing the administrator's current VM.
        name = vm_display_name(name)
        record = self.managed_vm(vm)
        value = self._vm_snapshot(record, snapshot)
        if value.get("incomplete"):
            raise Error("Ein unvollständiger Snapshot kann nicht wiederhergestellt werden.", 409)
        root = ET.fromstring(value["xml"])
        if (root.findtext("uuid") != record["id"] or root.findtext("name") != "titan-" + record["name"] or
                [node.find("source").get("file") for node in root.findall("./devices/disk[@device='disk']")] != [disk["disk"] for disk in record["disks"]]):
            raise Error("Snapshot-Konfiguration passt nicht zur ursprünglichen VM.", 409)
        record = self._offline_vm(vm, shutdown=shutdown)
        restored = self._vm_copy(record, name, storage, snapshot=value)
        return {**restored, "snapshot": snapshot, "source_vm": record["id"], "source_preserved": True,
                "message": "Snapshot als neue ausgeschaltete VM mit eigenen Laufwerken wiederhergestellt. Die ursprüngliche VM und ihre aktuellen Daten bleiben erhalten. Gast-IP und Rechnernamen vor dem ersten Start prüfen."}

    def op_vm_clone(self, vm, name, storage="system"):
        return self._vm_copy(self._offline_vm(vm), name, storage)

    def _vm_copy(self, record, name, storage="system", snapshot=None):
        name, label = vm_identity(name)
        if any(item["name"] == name or item.get("display_name", item["name"]) == label for item in self.load("vms", [])) or (self.directory / ("vm-" + name + ".xml")).exists():
            raise Error("Dieser VM-Name wird bereits verwendet.", 409)
        if "titan-" + name in self.command(["virsh", "list", "--all", "--name"], timeout=10).splitlines():
            raise Error("Dieser Name gehört bereits zu einer libvirt-VM.", 409)
        root = ET.fromstring(snapshot["xml"] if snapshot else record["xml"])
        root.find("name").text = "titan-" + name
        set_vm_title(root, label)
        for node in root.findall("uuid"): root.remove(node)
        devices = root.find("devices")
        for node in list(devices.findall("hostdev")): devices.remove(node)
        for node in devices.findall("interface"):
            for mac in list(node.findall("mac")): node.remove(mac)
            for target in list(node.findall("target")): node.remove(target)
        for channel in devices.findall("channel"):
            for source in list(channel.findall("source")): channel.remove(source)
        copied = []
        nvram_created = False
        try:
            with self.vm_storage_fd(storage, create=True) as (parent, location):
                for index, disk in enumerate(record["disks"]):
                    filename = name + ("" if index == 0 else "--" + uuid.uuid4().hex) + ".qcow2"
                    destination = Path(location["path"]) / filename
                    target = os.open(filename, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o660, dir_fd=parent)
                    copied.append(destination)
                    try:
                        owner = pwd.getpwnam(host_platform().qemu_user)
                        os.fchown(target, owner.pw_uid, owner.pw_gid)
                        os.fchmod(target, 0o660)
                        with self._vm_disk_fd(record, disk) as source:
                            checkpoint = ["-l", "snapshot.name=" + snapshot["id"]] if snapshot else []
                            self.command(["qemu-img", "convert", "-f", "qcow2", *checkpoint, "-O", "qcow2", "/proc/self/fd/" + str(source), "/proc/self/fd/" + str(target)], pass_fds=(source, target), timeout=3600)
                        # Probe every independent result before any definition
                        # is registered. No backing dependency is accepted.
                        self.vm_image_probe(target, "qcow2")
                    finally:
                        os.close(target)
                    self.vm_storage_label(destination)
                    devices.findall("disk[@device='disk']")[index].find("source").set("file", str(destination))
            nvram = root.find("./os/nvram")
            if nvram is not None:
                previous = Path(nvram.text)
                expected = self.vm_instance_nvram_path(record["name"], record["disk"])
                if previous != expected: raise Error("Unsichere UEFI-Quelldatei.", 409)
                destination = self.vm_instance_nvram_path(name, copied[0])
                source_path = self._vm_snapshot_root(record["id"]) / (snapshot["id"] + ".nvram") if snapshot else previous
                if snapshot and snapshot.get("nvram") != str(expected):
                    raise Error("UEFI-Snapshot gehört nicht zur ursprünglichen VM.", 409)
                with directory_fd(source_path.parent) as parent:
                    source = os.open(source_path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
                    with os.fdopen(source, "rb") as stream:
                        info = os.fstat(stream.fileno())
                        if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024 ** 2: raise Error("UEFI-Datei ist ungültig.")
                        content = stream.read()
                with directory_fd(destination.parent) as parent:
                    target = os.open(destination.name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                    nvram_created = True
                    with os.fdopen(target, "wb") as stream:
                        owner = pwd.getpwnam(host_platform().qemu_user)
                        os.fchown(stream.fileno(), owner.pw_uid, owner.pw_gid)
                        stream.write(content)
                nvram.text = str(destination)
            cloned = self.register_vm_definition(name, ET.tostring(root, encoding="unicode"))
            extras = [{"disk": str(path), "storage": location["id"], "target": record["disks"][index + 1]["target"], **({"storage_uuid": location["uuid"]} if location.get("uuid") else {})} for index, path in enumerate(copied[1:])]
            self._vm_registry_replace(cloned, extra_disks=extras)
        except Exception as failure:
            if getattr(failure, "retain_vm_files", False):
                raise
            # Registration rolls itself back on failure; a registry failure after
            # a successful define must undefine before copied files are removed.
            if "cloned" in locals():
                try:
                    self.command(["virsh", "undefine", cloned] + (["--keep-nvram"] if nvram_created else []))
                    self.save("vms", [item for item in self.load("vms", []) if item["id"] != cloned])
                except Error:
                    raise Error("Klon angelegt, Verwaltungsdaten konnten nicht gespeichert werden. Laufwerke bleiben erhalten; VM-Status prüfen.", 503) from None
            for path in copied: path.unlink(missing_ok=True)
            if nvram_created: destination.unlink(missing_ok=True)
            (self.directory / ("vm-" + name + ".xml")).unlink(missing_ok=True)
            raise
        return {"ok": True, "id": cloned, "name": name, "message": "Eigenständiger Klon mit allen Laufwerken angelegt. USB-Geräte und MAC-Adressen wurden nicht übernommen; Gast-IP und Rechnernamen vor dem ersten Start prüfen."}

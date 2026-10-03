"""Management of Titan-owned libvirt domains; removal retains VM disks."""
from .platforms import current as host_platform
import os
from pathlib import Path
import pwd
import re
import stat
import tempfile
import uuid
import xml.etree.ElementTree as ET

from .core import Error, identifier, integer


class VMMixin:
    @staticmethod
    def vm_nvram_path(name):
        return Path("/var/lib/libvirt/qemu/nvram") / ("titan-" + identifier(name) + "_VARS.fd")

    def vm_instance_nvram_path(self, name, disk):
        name = identifier(name)
        self.vm_disk_storage(name, disk)
        stem = Path(disk).stem
        return self.vm_nvram_path(name).with_name("titan-" + stem + "_VARS.fd")

    @staticmethod
    def validate_vm_firmware(firmware):
        if firmware not in ("bios", "uefi"):
            raise Error("Bootmodus muss BIOS oder UEFI sein.")
        if firmware == "uefi" and not any(Path(path).is_file() for path in ("/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_CODE.fd")):
            raise Error("UEFI-Firmware fehlt. Ein Titan-Systemupdate mit OVMF installieren.", 503)

    def vm_resources(self, cpus, memory_mb):
        cpus = integer(cpus, 1, os.cpu_count() or 1)
        total = self.op_status()["memory_total"]
        if not isinstance(total, int) or total <= 0:
            raise Error("RAM-Kapazität des Servers ist momentan nicht lesbar. VM-Einrichtung erneut versuchen.", 503)
        memory_mb = integer(memory_mb, 512, max(512, total // 1024**2 - 1024))
        return cpus, memory_mb

    def vm_iso_path(self, name):
        """Only finalized, regular ISO files in the managed library are usable."""
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.iso", name):
            raise Error("Ungültiger ISO-Dateiname.")
        directory = self.vm_root / "iso"
        path = directory / name
        try:
            if directory.is_symlink() or not directory.is_dir() or directory.resolve().parent != self.vm_root.resolve():
                raise Error("Unsicherer ISO-Speicherpfad.", 409)
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or path.resolve().parent != directory.resolve():
                raise Error("ISO muss eine vollständige, reguläre Datei im verwalteten Speicher sein.", 409)
        except OSError:
            raise Error("ISO nicht gefunden.", 404) from None
        return path

    def vm_media_info(self, root):
        source = root.find("./devices/disk[@device='cdrom']/source")
        path = Path(source.get("file", "")) if source is not None else None
        iso = path.name if path is not None and path.parent == self.vm_root / "iso" else None
        boots = root.findall("./os/boot")
        return {"iso": iso, "boot": boots[0].get("dev", "hd") if boots else "hd", "firmware": "uefi" if root.find("./os/loader") is not None or root.find("os").get("firmware") == "efi" else "bios"}

    def vm_definition(self, name, cpus, memory_mb, disk, iso=None, cpu_ids=None, firmware="bios"): 
        name = identifier(name)
        self.validate_vm_firmware(firmware)
        cpus, memory_mb = self.vm_resources(cpus, memory_mb)
        expected = Path(disk)
        self.validate_vm_disk_path(name, expected, exists=False)
        root = ET.Element("domain", type="kvm")
        ET.SubElement(root, "name").text = "titan-" + name
        ET.SubElement(root, "memory", unit="KiB").text = str(memory_mb * 1024)
        ET.SubElement(root, "vcpu").text = str(cpus)
        self.apply_vm_cpu_policy(root, cpus, cpu_ids)
        os_node = ET.SubElement(root, "os")
        ET.SubElement(os_node, "type", arch=os.uname().machine).text = "hvm"
        if firmware == "uefi":
            os_node.set("firmware", "efi")
            os_node.find("type").set("machine", "q35")
            firmware_node = ET.SubElement(os_node, "firmware")
            ET.SubElement(firmware_node, "feature", enabled="no", name="secure-boot")
            ET.SubElement(firmware_node, "feature", enabled="no", name="enrolled-keys")
            ET.SubElement(os_node, "nvram").text = str(self.vm_instance_nvram_path(name, disk))
        if iso:
            ET.SubElement(os_node, "boot", dev="cdrom")
        ET.SubElement(os_node, "boot", dev="hd")
        features = ET.SubElement(root, "features")
        ET.SubElement(features, "acpi")
        ET.SubElement(features, "apic")
        ET.SubElement(root, "cpu", mode="host-model")
        devices = ET.SubElement(root, "devices")
        sources = [("disk", expected, "vda", "virtio")]
        if iso:
            sources.append(("cdrom", self.vm_iso_path(iso), "sda", "sata"))
        for kind, source, target, bus in sources:
            node = ET.SubElement(devices, "disk", type="file", device=kind)
            ET.SubElement(node, "driver", name="qemu", type="qcow2" if kind == "disk" else "raw")
            ET.SubElement(node, "source", file=str(source))
            ET.SubElement(node, "target", dev=target, bus=bus)
            if kind == "cdrom":
                ET.SubElement(node, "readonly")
        interface = ET.SubElement(devices, "interface", type="network")
        ET.SubElement(interface, "source", network="default")
        ET.SubElement(interface, "model", type="virtio")
        ET.SubElement(devices, "graphics", type="vnc", port="-1", autoport="yes", listen="127.0.0.1")
        video = ET.SubElement(devices, "video")
        ET.SubElement(video, "model", type="vga")
        ET.SubElement(devices, "input", type="tablet", bus="usb")
        balloon = ET.SubElement(devices,"memballoon",model="virtio")
        ET.SubElement(balloon,"stats",period="5")
        return ET.tostring(root, encoding="unicode")

    def register_vm_definition(self, name, xml, virtual_size=None):
        name = identifier(name)
        path = self.directory / ("vm-" + name + ".xml")
        path.write_text(xml)
        self.command(["virsh", "define", str(path)])
        try:
            vm_id = str(uuid.UUID(self.command(["virsh", "domuuid", "titan-" + name])))
            records = self.load("vms", [])
            records = [item for item in records if item["name"] != name]
            root = ET.fromstring(xml)
            source = root.find("./devices/disk[@device='disk']/source")
            if source is None:
                raise Error("VM-Laufwerk fehlt in der Definition.")
            disk = source.get("file")
            location = self.validate_vm_disk_path(name, disk)
            entry = {"name": name, "id": vm_id, "disk": disk, "storage": location["id"]}
            if location.get("uuid"):
                entry["storage_uuid"] = location["uuid"]
            if virtual_size is not None:
                entry["virtual_size"] = virtual_size
            records.append(entry)
            self.save("vms", records)
        except Exception:
            self.command(["virsh", "undefine", "titan-" + name] + (["--keep-nvram"] if ET.fromstring(xml).find("./os/nvram") is not None else []))
            path.unlink(missing_ok=True)
            raise
        return vm_id

    def managed_vm(self, value):
        try:
            vm_id = str(uuid.UUID(value))
        except (ValueError, TypeError, AttributeError):
            raise Error("Ungültige VM-ID.")
        xml = self.command(["virsh", "dumpxml", vm_id])
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            raise Error("Ungültige VM-Definition.")
        domain_name = root.findtext("name", "")
        if not re.fullmatch(r"titan-[a-z][a-z0-9_-]{0,30}", domain_name) or root.findtext("uuid") != vm_id:
            raise Error("VM gehört nicht zu Titan.", 403)
        name = domain_name[6:]
        records = self.load("vms", [])
        record = next((item for item in records if item["name"] == name), None)
        path = self.directory / ("vm-" + name + ".xml")
        if record:
            if record["id"] != vm_id:
                raise Error("Die VM-UUID wurde außerhalb von Titan geändert.", 409)
        elif not path.is_file() or path.is_symlink():
            raise Error("VM besitzt keine Titan-Verwaltungsmetadaten.", 403)
        else:
            # Migration of pre-registry Alpha VMs requires the original root-owned
            # metadata, matching domain name and matching managed disk.
            try:
                original = ET.fromstring(path.read_text())
            except ET.ParseError:
                raise Error("Titan-VM-Metadaten sind ungültig.", 409)
            if original.findtext("name") != domain_name:
                raise Error("Titan-VM-Metadaten stimmen nicht überein.", 409)
        disks = root.findall("./devices/disk[@device='disk']")
        expected = Path(record["disk"]) if record else self.vm_root / (name + ".qcow2")
        if len(disks) != 1 or disks[0].get("type") != "file":
            raise Error("Diese VM besitzt keine unterstützte Titan-Disk.", 409)
        source = disks[0].find("source")
        driver = disks[0].find("driver")
        if source is None or source.get("file") != str(expected) or driver is None or driver.get("type") != "qcow2":
            raise Error("VM-Laufwerk stimmt nicht mit den Titan-Metadaten überein.", 409)
        try:
            location = self.validate_vm_disk_path(name, expected, record.get("storage") if record else None,
                                                  record.get("storage_uuid") if record else None)
        except OSError:
            raise Error("Unsicherer oder fehlender VM-Laufwerkspfad.", 409) from None
        if record and record.get("disk") != str(expected):
            raise Error("VM-Laufwerksmetadaten stimmen nicht überein.", 409)
        if not record:
            original_disk = original.find("./devices/disk[@device='disk']/source")
            if original_disk is None or original_disk.get("file") != str(expected):
                raise Error("Ursprünglicher VM-Laufwerkspfad stimmt nicht überein.", 409)
            self.save("vms", records + [{"name": name, "id": vm_id, "disk": str(expected)}])
        try:
            cpus = int(root.findtext("vcpu"))
        except (ValueError, TypeError):
            raise Error("VM-Prozessoreinstellungen sind ungültig.", 409) from None
        if cpus < 1:
            raise Error("VM-Prozessoreinstellungen sind ungültig.", 409)
        return {"id": vm_id, "name": name, "disk": str(expected), "storage": location["id"], "xml": xml,
                "state": self.command(["virsh", "domstate", vm_id]).strip(),
                "cpus": cpus, "memory_mb": self.vm_memory_mb(root), "cpu_ids": self.vm_cpu_ids(root), **self.vm_media_info(root)}

    @staticmethod
    def vm_memory_mb(root):
        node = root.find("memory")
        if node is None:
            raise Error("VM-Arbeitsspeicher fehlt.")
        # libvirt accepts both SI and binary units. Avoid float rounding for
        # large byte counts and return the whole MiB value used by the UI.
        factors = {"b": 1, "bytes": 1, "KB": 1000, "kilobytes": 1000,
                   "k": 1024, "KiB": 1024, "kibibytes": 1024,
                   "MB": 1000**2, "megabytes": 1000**2,
                   "M": 1024**2, "MiB": 1024**2, "mebibytes": 1024**2,
                   "GB": 1000**3, "gigabytes": 1000**3,
                   "G": 1024**3, "GiB": 1024**3, "gibibytes": 1024**3,
                   "TB": 1000**4, "terabytes": 1000**4,
                   "T": 1024**4, "TiB": 1024**4, "tebibytes": 1024**4}
        multiplier = factors.get(node.get("unit", "KiB"))
        if multiplier is None:
            raise Error("VM-Speichereinheit wird nicht unterstützt.")
        try:
            memory = int(node.text) * multiplier // 1024**2
        except (ValueError, TypeError):
            raise Error("VM-Arbeitsspeicher ist ungültig.", 409) from None
        if memory < 1:
            raise Error("VM-Arbeitsspeicher ist ungültig.", 409)
        return memory

    def vm_id(self, value, check_cpu=False):
        record = self.managed_vm(value)
        if check_cpu:
            self.validate_vm_cpu_ids(record["cpus"], record["cpu_ids"])
            from .vm_usb import assigned
            self.validate_vm_usb(record["id"], assigned(ET.fromstring(record["xml"])))
        return record["id"]

    @staticmethod
    def write_vm_xml(path, xml):
        """Replace metadata atomically without following a destination symlink."""
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name + ".", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(xml)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def redefine_vm(self, record, root):
        path = self.directory / ("vm-" + record["name"] + ".xml")
        self.write_vm_xml(path, ET.tostring(root, encoding="unicode"))
        try:
            self.command(["virsh", "define", str(path)])
        except Exception:
            try:
                self.write_vm_xml(path, record["xml"])
                self.command(["virsh", "define", str(path)])
            except Exception:
                raise Error("VM-Änderung fehlgeschlagen; die bisherige Definition konnte nicht erneut bestätigt werden.", 500) from None
            raise

    def op_vm_media(self, vm, iso=None):
        record = self.managed_vm(vm)
        if record["state"] != "shut off":
            raise Error("Die VM muss zum Wechseln des Installationsmediums ausgeschaltet sein.", 409)
        source = self.vm_iso_path(iso) if iso is not None else None
        root = ET.fromstring(record["xml"])
        devices = root.find("devices")
        os_node = root.find("os")
        if devices is None or os_node is None:
            raise Error("VM-Geräte- oder Starteinstellungen fehlen.", 409)
        cdroms = devices.findall("disk[@device='cdrom']")
        if len(cdroms) > 1 or any(node.get("type") != "file" for node in cdroms):
            raise Error("Diese VM besitzt keine unterstützte Titan-CD-ROM-Konfiguration.", 409)
        if any(node.find("boot") is not None for node in devices):
            raise Error("Individuelle Geräte-Bootreihenfolgen müssen zuerst auf dem Host entfernt werden.", 409)
        cdrom = cdroms[0] if cdroms else None
        if cdrom is None and source is not None:
            cdrom = ET.SubElement(devices, "disk", type="file", device="cdrom")
            ET.SubElement(cdrom, "driver", name="qemu", type="raw")
            ET.SubElement(cdrom, "target", dev="sda", bus="sata")
            ET.SubElement(cdrom, "readonly")
        if cdrom is not None:
            # Keep the existing target/address so changing media does not move
            # the drive inside the guest. A source-less CD-ROM is an empty tray.
            for node in cdrom.findall("source"):
                cdrom.remove(node)
            target = cdrom.find("target")
            driver = cdrom.find("driver")
            if target is None or driver is None or driver.get("type") != "raw":
                raise Error("VM-CD-ROM-Konfiguration ist ungültig.", 409)
            target.set("tray", "closed" if source is not None else "open")
            if source is not None:
                ET.SubElement(cdrom, "source", file=str(source))
            if cdrom.find("readonly") is None:
                ET.SubElement(cdrom, "readonly")
        for node in os_node.findall("boot"):
            os_node.remove(node)
        if source is not None:
            ET.SubElement(os_node, "boot", dev="cdrom")
        ET.SubElement(os_node, "boot", dev="hd")
        self.redefine_vm(record, root)
        return {"ok": True, "iso": iso, "boot": "cdrom" if source is not None else "hd"}

    def op_vm_update(self, vm, cpus, memory_mb, cpu_ids=None, firmware=None, network=None, boot=None):
        record = self.managed_vm(vm)
        if record["state"] != "shut off":
            raise Error("Die VM muss zum Bearbeiten ausgeschaltet sein.", 409)
        cpus, memory_mb = self.vm_resources(cpus, memory_mb)
        root = ET.fromstring(record["xml"])
        pins = record["cpu_ids"] if cpu_ids is None else cpu_ids
        pins = self.apply_vm_cpu_policy(root, cpus, pins)
        root.find("vcpu").text = str(cpus)
        if "current" in root.find("vcpu").attrib:
            root.find("vcpu").set("current", str(cpus))
        memory = root.find("memory")
        memory.set("unit", "KiB")
        memory.text = str(memory_mb * 1024)
        current = root.find("currentMemory")
        if current is not None:
            current.set("unit", "KiB")
            current.text = str(memory_mb * 1024)
        if firmware is not None and firmware != record['firmware']:
            self.validate_vm_firmware(firmware)
            os_node = root.find('os')
            for tag in ('loader','nvram','firmware','varstore'):
                for child in os_node.findall(tag): os_node.remove(child)
            os_node.attrib.pop('firmware',None)
            if firmware == 'uefi':
                os_node.set('firmware','efi')
                features = ET.SubElement(os_node,'firmware')
                ET.SubElement(features,'feature',enabled='no',name='secure-boot')
                ET.SubElement(features,'feature',enabled='no',name='enrolled-keys')
                nvram = self.vm_instance_nvram_path(record['name'],record['disk'])
                if os.path.lexists(nvram) and (nvram.is_symlink() or not nvram.is_file()): raise Error('Unsicherer UEFI-Speicherpfad.',409)
                ET.SubElement(os_node,'nvram').text = str(nvram)
        if network is not None: self.apply_vm_network(root, network)
        if boot is not None:
            if boot not in ('hd','cdrom','network'): raise Error('Ungültige Bootreihenfolge.')
            if any(node.find('boot') is not None for node in root.find('devices')): raise Error('Individuelle Geräte-Bootreihenfolge ist vorhanden.',409)
            os_node = root.find('os')
            for child in os_node.findall('boot'): os_node.remove(child)
            ET.SubElement(os_node,'boot',dev=boot)
            if boot != 'hd': ET.SubElement(os_node,'boot',dev='hd')
        self.redefine_vm(record, root)
        return {"ok": True, "cpus": cpus, "memory_mb": memory_mb, "cpu_ids": pins}

    def op_vm_remove(self, vm):
        record = self.managed_vm(vm)
        if record["state"] != "shut off":
            raise Error("Die VM muss vor dem Entfernen ausgeschaltet sein.", 409)
        self.command(["virsh", "undefine", record["id"]] + (["--keep-nvram"] if record["firmware"] == "uefi" else []))
        metadata = self.directory / ("vm-" + record["name"] + ".xml")
        try:
            self.save("vms", [item for item in self.load("vms", []) if item["id"] != record["id"]])
        except Exception:
            metadata.write_text(record["xml"])
            self.command(["virsh", "define", str(metadata)])
            raise
        metadata.unlink(missing_ok=True)
        process = self.console_processes.pop(record["id"], None)
        if process and process[0].poll() is None:
            process[0].terminate()
        return {"ok": True, "disk_retained": True, "disk": record["disk"]}

    def op_vm_backup(self, vm, target=None):
        record = self.managed_vm(vm)
        if record["state"] != "shut off":
            raise Error("Die VM muss für die Sicherung vollständig ausgeschaltet sein.", 409)
        manager = self.backups
        previous = manager.settings()
        changed = target is not None and target != previous["target"]
        if changed:
            manager.save_settings({"target": target})
        try:
            result = manager.create_vm(record["name"], record["xml"], record["disk"])
        except Exception:
            if changed:
                # The previously selected target must not disappear because a
                # failed one-off VM backup selected a different external drive.
                self.save("backup-settings", previous)
            raise
        return {"ok": True, "backup": result["id"], "manifest": result,
                "message": "VM gesichert. Das gewählte Laufwerk ist das gemeinsame Titan-Sicherungsziel."}

    def op_vm_restore(self, backup, name):
        name = identifier(name)
        manager = self.backups
        verified = manager.verified_vm(backup)
        try:
            original = ET.fromstring(verified["xml"])
            cpus, memory_mb = self.vm_resources(int(original.findtext("vcpu")), self.vm_memory_mb(original))
        except (ET.ParseError, TypeError, ValueError):
            raise Error("VM-Sicherung enthält keine gültigen CPU-/Speichereinstellungen.")
        os_type = original.find("./os/type")
        if os_type is None or os_type.get("arch", os.uname().machine) != os.uname().machine:
            raise Error("VM-Sicherung passt nicht zur Architektur dieses Servers.")
        existing = self.op_vms()
        if not existing["available"]:
            raise Error(existing.get("error", "KVM/libvirt ist nicht verfügbar."), 503)
        disk = self.vm_root / (name + ".qcow2")
        metadata = self.directory / ("vm-" + name + ".xml")
        if (os.path.lexists(disk) or os.path.lexists(metadata) or
                any(item["name"] == name for item in existing["vms"]) or
                any(item["name"] == name for item in self.load("vms", []))):
            raise Error("VM-Name oder Laufwerk existiert bereits; Wiederherstellung benötigt einen neuen Namen.", 409)
        firmware = self.vm_media_info(original)["firmware"]
        self.validate_vm_firmware(firmware)
        if firmware == "uefi" and os.path.lexists(self.vm_nvram_path(name)):
            raise Error("UEFI-Speicher dieses Namens existiert bereits.", 409)
        copied = Path(manager.restore_vm_files(backup, name))
        if copied != disk:
            raise Error("Wiederherstellung lieferte einen unerwarteten Laufwerkspfad.", 500)
        created_inode = None
        restored_nvram = False
        try:
            fd = os.open(disk, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                info = os.fstat(fd)
                created_inode = (info.st_dev, info.st_ino)
                if not stat.S_ISREG(info.st_mode):
                    raise Error("Wiederhergestelltes VM-Laufwerk ist keine reguläre Datei.")
                qemu = pwd.getpwnam(host_platform().qemu_user)
                os.fchown(fd, qemu.pw_uid, qemu.pw_gid)
                os.fchmod(fd, 0o660)
            finally:
                os.close(fd)
            # Only resource values are imported. UUID, devices, host paths and
            # network details from an archive never become a live definition.
            firmware = self.vm_media_info(original)["firmware"]
            xml = self.vm_definition(name, cpus, memory_mb, disk, firmware=firmware)
            if firmware == "uefi":
                restored_nvram = manager.restore_vm_nvram(backup, name)
            vm_id = self.register_vm_definition(name, xml)
        except Exception:
            if restored_nvram:
                self.vm_nvram_path(name).unlink(missing_ok=True)
            if created_inode is not None:
                try:
                    info = os.stat(disk, follow_symlinks=False)
                    if (info.st_dev, info.st_ino) == created_inode:
                        disk.unlink()
                except FileNotFoundError:
                    pass
            metadata.unlink(missing_ok=True)
            raise
        return {"ok": True, "id": vm_id, "name": name, "message": "VM unter neuem Namen wiederhergestellt und ausgeschaltet angelegt."}

    def op_vm_disk_grow(self, vm, disk_gb):
        record = self.managed_vm(vm)
        if record["state"] != "shut off": raise Error("VM zuerst herunterfahren.",409)
        disk_gb = integer(disk_gb,1,16384)
        current = self.vm_disk_details(record).get("virtual_size")
        if current is None or disk_gb*1024**3 <= current: raise Error("Nur eine größere Laufwerkskapazität ist erlaubt.")
        self.prepare_vm_storage_access()
        self.command(["qemu-img","resize","-f","qcow2",record["disk"],str(disk_gb)+"G"],timeout=60)
        entries = self.load("vms",[])
        for item in entries:
            if item["id"] == record["id"]: item["virtual_size"] = disk_gb*1024**3
        self.save("vms",entries)
        return {"ok":True,"message":"Laufwerk erweitert. Partition/Dateisystem im Gastsystem erweitern."}

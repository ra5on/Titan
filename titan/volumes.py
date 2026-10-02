"""Managed single-disk Ext4/XFS volumes. No import, force-format or shell commands."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time
import uuid
from .core import Error, identifier

DISK = re.compile(r"/dev/(?:(?:sd|vd|xvd|hd)[a-z]+|nvme[0-9]+n[0-9]+|mmcblk[0-9]+)\Z")
FILESYSTEMS = {"ext4": "mkfs.ext4", "xfs": "mkfs.xfs"}
OPTIONS = "defaults,nofail,nodev,nosuid"


def flatten(disks):
    for disk in disks:
        yield disk
        yield from flatten(disk.get("children", []))


class Volumes:
    def __init__(self, host, run, fstab="/etc/fstab", owner_uid=0):
        self.host, self.run = host, run
        self.fstab = Path(fstab)
        self.owner_uid = owner_uid  # Injectable only by local tests, never an RPC argument.

    @property
    def root(self):
        return self.host.share_root / "volumes"

    def records(self):
        records = self.host.load("volumes", [])
        if not isinstance(records, list) or len(records) > 128:
            raise Error("Verwaltete Volume-Metadaten sind ungültig.")
        for item in records:
            identifier(item["name"])
            if item["filesystem"] not in FILESYSTEMS or str(uuid.UUID(item["uuid"])) != item["uuid"]:
                raise Error("Verwaltete Volume-Metadaten sind ungültig.")
        return records

    def record(self, name):
        name = identifier(name)
        record = next((item for item in self.records() if item["name"] == name), None)
        if not record:
            raise Error("Volume nicht gefunden.", 404)
        return record

    def availability(self):
        return {name: {"available": bool(shutil.which(binary))} for name, binary in FILESYSTEMS.items()}

    def mounts(self):
        data = json.loads(self.run(["findmnt", "--json", "--output", "TARGET,SOURCE,FSTYPE,UUID,MAJ:MIN"]))
        if not isinstance(data, dict) or not isinstance(data.get("filesystems"), list):
            raise Error("Eingehängte Dateisysteme konnten nicht zuverlässig geprüft werden.")
        def entries(items):
            for item in items:
                yield item
                yield from entries(item.get("children", []))
        return list(entries(data.get("filesystems", [])))

    def mounted(self, record, mounts=None):
        target = str(self.root / record["name"])
        matches = [item for item in (self.mounts() if mounts is None else mounts) if item.get("target") == target]
        if not matches:
            return None
        if len(matches) != 1 or matches[0].get("uuid") != record["uuid"] or matches[0].get("fstype") != record["filesystem"]:
            raise Error("Am Volume-Pfad ist ein anderes Dateisystem eingehängt. Zugriff verweigert.", 409)
        major, minor = map(int, matches[0]["maj:min"].split(":"))
        return os.makedev(major, minor)

    def require(self, name):
        record = self.record(name)
        device = self.mounted(record)
        if device is None:
            raise Error("Volume ist nicht eingehängt. Erst auf der Speicherseite einhängen; Datenzugriff ist gesperrt.", 503)
        return record, device

    def required_path(self, path):
        path = Path(path)
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            return None
        if not self.records():
            return None  # Preserve an older ZFS pool named volumes; creation refuses that collision.
        if not relative.parts or any(part in (".", "..") for part in relative.parts):
            raise Error("Ungültiger Volume-Pfad.")
        _, device = self.require(relative.parts[0])
        return device

    def share_path(self, volume, share):
        record, device = self.require(volume)
        path = self.root / record["name"] / "shares" / identifier(share)
        with self.target_fd(record, create=False) as fd:
            if os.fstat(fd).st_dev != device:
                raise Error("Volume wurde während der Aktion ausgehängt.", 503)
            self.host.share_namespace_traversal(fd, self.owner_uid)
            try:
                os.mkdir("shares", 0o755, dir_fd=fd)
            except FileExistsError:
                pass
            parent = os.open("shares", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                self.secure_directory(parent)
                self.host.share_namespace_traversal(parent, self.owner_uid)
                try:
                    os.mkdir(share, 0o770, dir_fd=parent)
                except FileExistsError:
                    raise Error("Der Freigabeordner existiert bereits; vorhandene Daten werden nicht übernommen.", 409)
            finally:
                os.close(parent)
        return path

    @contextlib.contextmanager
    def target_fd(self, record, create=False):
        descriptors = []
        try:
            fd = os.open(self.host.share_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.append(fd)
            self.secure_directory(fd)
            for component, mode in (("volumes", 0o755), (record["name"], 0o000)):
                if create:
                    try:
                        os.mkdir(component, mode, dir_fd=fd)
                    except FileExistsError:
                        pass
                fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                descriptors.append(fd)
                self.secure_directory(fd)
                if component == "volumes":
                    self.host.share_namespace_traversal(fd, self.owner_uid)
            yield fd
        finally:
            for fd in reversed(descriptors):
                os.close(fd)

    def secure_directory(self, fd):
        value = os.fstat(fd)
        if value.st_uid != self.owner_uid or value.st_mode & 0o022:
            raise Error("Volume-Verzeichnisse müssen root gehören und gegen fremde Schreibzugriffe geschützt sein.")

    def blank_disk(self, disk, filesystem):
        if not isinstance(disk, str) or not DISK.fullmatch(disk):
            raise Error("Nur ein direktes physisches Laufwerk darf eingerichtet werden.")
        candidates = [item for item in self.host.disks() if item.get("name") == disk]
        if len(candidates) != 1:
            raise Error("Laufwerk nicht eindeutig gefunden.")
        item = candidates[0]
        if (item.get("type") != "disk" or item.get("fstype") or item.get("children") or
                any(item.get("mountpoints") or []) or item.get("ro") not in (False, 0, "0") or
                int(item.get("size", 0)) < (512 if filesystem == "xfs" else 64) * 1024**2):
            raise Error("Nur vollständig leere, ausreichend große, unpartitionierte, beschreibbare und ungemountete Laufwerke sind zulässig.")
        info = os.stat(disk, follow_symlinks=False)
        if not stat.S_ISBLK(info.st_mode):
            raise Error("Laufwerk ist kein direktes Blockgerät.")
        identity = f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}"
        if item.get("maj:min") != identity:
            raise Error("Laufwerkskennung wurde verändert.")
        holders = Path("/sys/dev/block") / identity / "holders"
        if not holders.is_dir() or any(holders.iterdir()):
            raise Error("Laufwerk wird von einem anderen Speicherverbund verwendet oder konnte nicht geprüft werden.")
        if any(item.get("maj:min") == identity for item in self.mounts()):
            raise Error("Laufwerk ist eingehängt.")
        for line in Path("/proc/swaps").read_text().splitlines()[1:]:
            source = line.split()[0]
            try:
                value = os.stat(source)
            except FileNotFoundError:
                continue
            if stat.S_ISBLK(value.st_mode) and value.st_rdev == info.st_rdev:
                raise Error("Laufwerk wird als Swap verwendet.")
        signatures = json.loads(self.run(["wipefs", "--json", "--no-act", disk])).get("signatures")
        if not isinstance(signatures, list):
            raise Error("Laufwerkssignaturen konnten nicht zuverlässig geprüft werden.")
        if signatures:
            raise Error("Laufwerk enthält bereits Signaturen. Vorhandene Daten werden nicht formatiert.")
        return info.st_rdev

    def fstab_text(self, record):
        marker = "# Titan volume " + record["name"]
        entry = f"UUID={record['uuid']} {self.root / record['name']} {record['filesystem']} {OPTIONS} 0 {2 if record['filesystem'] == 'ext4' else 0}"
        return marker, entry

    def persist(self, record, remove=False, dry_run=False):
        """Preserve unrelated fstab content, reject collisions, replace atomically."""
        marker, entry = self.fstab_text(record)
        parent = os.open(self.fstab.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        temporary = None
        try:
            self.secure_directory(parent)
            fd = os.open(self.fstab.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or before.st_uid != self.owner_uid or before.st_mode & 0o022 or before.st_size > 1024**2:
                    raise Error("fstab ist unsicher oder zu groß.")
                with os.fdopen(os.dup(fd), "r") as stream:
                    lines = stream.read().splitlines()
                indexes = []
                for index, line in enumerate(lines):
                    fields = line.split()
                    if not fields or line.lstrip().startswith("#"):
                        continue
                    if fields[0] in ("UUID=" + record["uuid"], "/dev/disk/by-uuid/" + record["uuid"]) or (len(fields) > 1 and fields[1] == str(self.root / record["name"])):
                        if line != entry or index == 0 or lines[index - 1] != marker:
                            raise Error("UUID oder Volume-Pfad besitzt bereits einen anderen fstab-Eintrag.", 409)
                        indexes.append(index)
                if len(indexes) > 1 or lines.count(marker) > 1 or (marker in lines and not indexes):
                    raise Error("Titan-fstab-Eintrag ist widersprüchlich.")
                if dry_run or (bool(indexes) and not remove) or (not indexes and remove):
                    return False
                if remove:
                    del lines[indexes[0] - 1:indexes[0] + 1]
                else:
                    lines.extend([marker, entry])
                value = "\n".join(lines) + "\n"
                if len(value.encode()) > 1024**2:
                    raise Error("fstab würde zu groß.")
                output, temporary = tempfile.mkstemp(prefix=".titan-fstab-", dir=self.fstab.parent)
                with os.fdopen(output, "w") as stream:
                    os.fchmod(stream.fileno(), stat.S_IMODE(before.st_mode))
                    stream.write(value)
                    stream.flush()
                    os.fsync(stream.fileno())
                current = os.stat(self.fstab.name, dir_fd=parent, follow_symlinks=False)
                if (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_size) != (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_size):
                    raise Error("fstab wurde gleichzeitig geändert. Aktion abgebrochen.", 409)
                os.replace(Path(temporary).name, self.fstab.name, src_dir_fd=parent, dst_dir_fd=parent)
                temporary = None
                os.fsync(parent)
                return True
            finally:
                os.close(fd)
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)
            os.close(parent)

    def create(self, name, disk, filesystem="ext4", confirmation_name=None, confirmation_disk=None):
        name = identifier(name)
        if filesystem not in FILESYSTEMS or confirmation_name != name or confirmation_disk != disk:
            raise Error("Dateisystem oder Bestätigung ungültig. Volume-Name und exakten Laufwerkspfad bestätigen.")
        if not shutil.which(FILESYSTEMS[filesystem]):
            raise Error("Das Werkzeug für " + filesystem.upper() + " ist nicht installiert.", 503)
        if any(item["name"] == name for item in self.records()):
            raise Error("Volume-Name ist bereits verwaltet.", 409)
        record = {"name": name, "disk": disk, "filesystem": filesystem, "uuid": str(uuid.uuid4()), "created": time.time(), "phase": "formatted"}
        device = self.blank_disk(disk, filesystem)
        self.persist(record, dry_run=True)
        with self.target_fd(record, create=True) as target:
            if os.listdir(target) or self.mounted(record) is not None:
                raise Error("Volume-Pfad ist bereits belegt.")
            os.fchmod(target, 0o000)
        fd = os.open(disk, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        formatted = False
        journaled = False
        try:
            opened = os.fstat(fd)
            if not stat.S_ISBLK(opened.st_mode) or opened.st_rdev != device:
                raise Error("Laufwerk wurde ausgetauscht.")
            if self.blank_disk(disk, filesystem) != device:
                raise Error("Laufwerk wurde während der Sicherheitsprüfung ausgetauscht.")
            record["phase"] = "formatting"
            self.host.save("volumes", self.records() + [record])
            journaled = True
            arguments = [FILESYSTEMS[filesystem], "-L", name[:12]]
            arguments += ["-U", record["uuid"]] if filesystem == "ext4" else ["-m", "uuid=" + record["uuid"]]
            arguments += ["/proc/self/fd/" + str(fd)]
            self.run(arguments, timeout=900, pass_fds=(fd,))
            formatted = True
            detected = dict(line.split("=", 1) for line in self.run(["blkid", "-p", "-o", "export", "/proc/self/fd/" + str(fd)], pass_fds=(fd,)).splitlines() if "=" in line)
            if detected.get("TYPE") != filesystem or detected.get("UUID") != record["uuid"]:
                raise Error("Neues Dateisystem konnte nicht mit seiner UUID verifiziert werden.")
        except Exception as exc:
            if journaled:
                self.host.save("volumes", [{**item, "phase": "verify_failed" if formatted else "format_failed", "error": str(exc)} if item["name"] == name else item for item in self.records()])
            raise
        finally:
            os.close(fd)
        self.host.save("volumes", [{**item, "phase": "formatted", "error": None} if item["name"] == name else item for item in self.records()])
        return self.mount(name)

    def mount(self, name):
        record = self.record(name)
        if record.get("phase") in ("formatting", "format_failed"):
            raise Error("Formatierung wurde nicht erfolgreich bestätigt. Erneutes Formatieren oder automatisches Einhängen wird verweigert.", 409)
        changed = False
        try:
            mounted = self.mounted(record)
            with self.target_fd(record, create=True) as target:
                if mounted is None:
                    if os.listdir(target):
                        raise Error("Unter dem ungemounteten Volume liegen Dateien; Einhängen verweigert.")
                    os.fchmod(target, 0o000)
            if mounted is None:
                devices = [item for item in flatten(self.host.disks()) if item.get("uuid") == record["uuid"]]
                if len(devices) != 1 or devices[0].get("type") != "disk" or devices[0].get("fstype") != record["filesystem"] or devices[0].get("children") or any(devices[0].get("mountpoints") or []):
                    raise Error("Verwaltete UUID fehlt, ist mehrfach vorhanden oder bereits anderweitig verwendet.")
                changed = self.persist(record)
                self.run(["systemctl", "daemon-reload"])
                self.run(["mount", "--", str(self.root / name)], timeout=120)
                mounted = self.mounted(record)
                if mounted is None:
                    raise Error("Einhängen wurde nicht bestätigt.")
            else:
                self.persist(record)
            with self.target_fd(record) as target:
                if os.fstat(target).st_dev != mounted:
                    raise Error("Volume wurde während der Prüfung ausgehängt.")
                os.fchmod(target, 0o755)
                if Path("/sys/fs/selinux/enforce").is_file():
                    self.run(["restorecon", "-F", "--", str(self.root / name)])
            self.host.save("volumes", [{**item, "phase": "ready", "error": None} if item["name"] == name else item for item in self.records()])
            return {"ok": True, "message": record["filesystem"].upper() + "-Volume eingerichtet und per UUID dauerhaft eingehängt.", "path": str(self.root / name)}
        except Exception as exc:
            if changed:
                with contextlib.suppress(Exception):
                    self.persist(record, remove=True)
                    self.run(["systemctl", "daemon-reload"])
            self.host.save("volumes", [{**item, "phase": "failed", "error": str(exc)} if item["name"] == name else item for item in self.records()])
            raise

    def inventory(self):
        mounts = self.mounts() if self.records() else []
        volumes = []
        for record in self.records():
            item = {**record, "mountpoint": str(self.root / record["name"]), "mounted": False, "state": "Nicht eingehängt", "total": 0, "used": 0, "free": 0}
            try:
                device = self.mounted(record, mounts)
                if device is not None:
                    with self.target_fd(record) as fd:
                        if os.fstat(fd).st_dev != device:
                            raise Error("Volume wurde ausgehängt.")
                        usage = os.fstatvfs(fd)
                    item.update(mounted=True, state="Eingehängt", total=usage.f_blocks * usage.f_frsize,
                                free=usage.f_bavail * usage.f_frsize, used=(usage.f_blocks - usage.f_bfree) * usage.f_frsize)
                elif record.get("error"):
                    item["state"] = "Prüfen"
            except Exception as exc:
                item.update(state="Prüfen", error=str(exc))
            volumes.append(item)
        existing = [{key: item.get(key) for key in ("name", "type", "fstype", "uuid", "size", "mountpoints")}
                    for item in flatten(self.host.disks()) if item.get("fstype") in FILESYSTEMS]
        return {"volumes": volumes, "existing_filesystems": existing, "filesystems": self.availability()}

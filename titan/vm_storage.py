"""Bounded VM image imports and verified, managed VM disk destinations."""
import contextlib
import errno
import fcntl
import json
import math
import itertools
import subprocess
import os
import re
from pathlib import Path, PurePosixPath
import stat
import struct
import secrets
import xml.etree.ElementTree as ET

from .backups import directory_fd
from .core import Error, identifier
from .files import revision

GIB = 1024 ** 3
IMAGE_EXTENSIONS = {".qcow2": "qcow2", ".raw": "raw", ".img": "raw"}
MAX_IMAGE_SIZE = 10000 * GIB


class VMStorageMixin:
    def vm_storage_record(self, storage="system"):
        if storage == "system":
            return {"id": "system", "label": "Systemlaufwerk", "path": str(self.vm_root), "filesystem": None}
        if not isinstance(storage, str) or not storage.startswith("volume:"):
            raise Error("Ungültiger VM-Speicherort.")
        name = identifier(storage[7:])
        record = self.volume_manager.record(name)
        return {"id": storage, "label": name + " (" + record["filesystem"].upper() + ")",
                "path": str(self.volume_manager.root / name / "vms"),
                "filesystem": record["filesystem"], "uuid": record["uuid"]}

    @contextlib.contextmanager
    def vm_storage_fd(self, storage="system", create=False):
        record = self.vm_storage_record(storage)
        if storage == "system":
            # mkdir never follows an existing final symlink; directory_fd checks
            # every ancestor before any image command uses its descriptor.
            if create:
                self.vm_root.mkdir(parents=True, exist_ok=True, mode=0o755)
            with directory_fd(self.vm_root) as fd:
                self.vm_storage_secure(fd, traverse=create)
                if create:
                    self.vm_storage_label(self.vm_root)
                yield fd, record
            return
        volume, device = self.volume_manager.require(storage[7:])
        with self.volume_manager.target_fd(volume) as target:
            if os.fstat(target).st_dev != device:
                raise Error("VM-Volume wurde ausgehängt.", 503)
            if create:
                # The mount root is a Titan-controlled namespace, never a share
                # containing user data. QEMU needs only permission to traverse it.
                mode = stat.S_IMODE(os.fstat(target).st_mode)
                os.fchmod(target, mode | 0o011)
                try:
                    os.mkdir("vms", 0o755, dir_fd=target)
                except FileExistsError:
                    pass
            fd = os.open("vms", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=target)
            try:
                self.vm_storage_secure(fd, traverse=create)
                if create:
                    self.vm_storage_label(Path(record["path"]))
                if os.fstat(fd).st_dev != device:
                    raise Error("VM-Volume wurde während der Aktion ausgehängt.", 503)
                yield fd, record
                _, after = self.volume_manager.require(storage[7:])
                if after != device:
                    raise Error("VM-Volume wurde während der Aktion ausgetauscht.", 503)
            finally:
                os.close(fd)

    def vm_storage_label(self, path):
        # Only the root-owned, no-follow namespace directory is relabeled.
        # Recursive restorecon would overwrite running guests' dynamic MCS labels.
        if Path("/sys/fs/selinux/enforce").is_file():
            self.command(["restorecon", "-F", "--", str(path)])

    @staticmethod
    def vm_storage_secure(fd, traverse=False):
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise Error("VM-Speicher muss root gehören und gegen fremde Schreibzugriffe geschützt sein.", 409)
        if traverse:
            os.fchmod(fd, stat.S_IMODE(info.st_mode) | 0o011)

    def prepare_vm_storage_access(self):
        # Only root-controlled namespaces, never guest disks or share ACLs.
        warnings = []
        with self.vm_storage_fd("system", create=True):
            pass
        self.vm_storage_label(self.iso_directory())
        for volume in self.volume_manager.records():
            path = self.volume_manager.root / volume["name"] / "vms"
            if not path.exists():
                continue
            try:
                with self.vm_storage_fd("volume:" + volume["name"], create=True):
                    pass
            except (Error, OSError) as exc:
                warnings.append("VM-Speicher " + volume["name"] + ": " + str(exc))
        return warnings

    def vm_disk_storage(self, name, disk):
        name = identifier(name)
        path = Path(disk)
        if path.name != name + ".qcow2" and not re.fullmatch(re.escape(name) + r"--[a-f0-9]{32}\.qcow2", path.name):
            raise Error("VM-Laufwerksname passt nicht zur Maschine.", 409)
        if path.parent == self.vm_root:
            return "system"
        for record in self.volume_manager.records():
            if path.parent == self.volume_manager.root / record["name"] / "vms":
                return "volume:" + record["name"]
        raise Error("VM-Laufwerk liegt außerhalb eines verwalteten Speichers.", 409)

    def validate_vm_disk_path(self, name, disk, storage=None, storage_uuid=None, exists=True):
        discovered = self.vm_disk_storage(name, disk)
        if storage is not None and storage != discovered:
            raise Error("VM-Speicherort stimmt nicht mit den Metadaten überein.", 409)
        with self.vm_storage_fd(discovered) as (fd, record):
            if storage_uuid and storage_uuid != record.get("uuid"):
                raise Error("VM-Volume-UUID stimmt nicht mit den Metadaten überein.", 409)
            try:
                info = os.stat(Path(disk).name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                if exists:
                    raise Error("VM-Laufwerk fehlt.", 409) from None
            else:
                if not stat.S_ISREG(info.st_mode):
                    raise Error("VM-Laufwerk ist keine reguläre Datei.", 409)
            device = os.fstat(fd).st_dev
        return {**record, "device": device}

    def vm_storage_options(self):
        storage, warnings = [], []
        for choice in ["system"] + ["volume:" + item["name"] for item in self.volume_manager.records()]:
            record = self.vm_storage_record(choice)
            try:
                if choice == "system":
                    # A new installation may not have allocated its VM folder yet.
                    nearest = self.vm_root
                    while not nearest.exists():
                        nearest = nearest.parent
                    with directory_fd(nearest) as fd:
                        value = os.fstatvfs(fd)
                else:
                    volume, device = self.volume_manager.require(choice[7:])
                    with self.volume_manager.target_fd(volume) as fd:
                        if os.fstat(fd).st_dev != device:
                            raise Error("VM-Volume wurde ausgehängt.", 503)
                        value = os.fstatvfs(fd)
                record.update(available=True, free_bytes=value.f_bavail * value.f_frsize)
            except (Error, OSError) as exc:
                record.update(available=False, free_bytes=0, error=str(exc))
            storage.append(record)
        images = []
        try:
            used = self.vm_active_image_paths()
        except (Error, OSError, ET.ParseError, subprocess.TimeoutExpired) as exc:
            return {"storage": storage, "disk_images": [], "warnings": ["Laufwerksimages konnten nicht auf aktive Nutzung geprüft werden: " + str(exc)]}
        inspected, scanned = 0, 0
        for share in self.op_shares():
            if share.get("blocked") or share["name"] in getattr(self, "suspended_shares", set()):
                continue
            try:
                root = self.open_share_root(share["path"])
                try:
                    pending = [(os.dup(root), "", 0)]
                    try:
                        while pending and scanned < 3000 and inspected < 24:
                            fd, parent, depth = pending.pop()
                            try:
                                with os.scandir(fd) as entries:
                                    names = sorted(item.name for item in itertools.islice(entries, 3000 - scanned))
                                for filename in names:
                                    scanned += 1
                                    if scanned > 3000 or inspected >= 24:
                                        break
                                    relative = parent + filename
                                    info = os.stat(filename, dir_fd=fd, follow_symlinks=False)
                                    if stat.S_ISDIR(info.st_mode) and depth < 4 and not filename.startswith(".") and len(pending) < 64:
                                        child = os.open(filename, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                                        pending.append((child, relative + "/", depth + 1))
                                    elif stat.S_ISREG(info.st_mode) and Path(filename).suffix.lower() in IMAGE_EXTENSIONS:
                                        inspected += 1
                                        path = Path(share["path"]) / relative
                                        if str(path) in used:
                                            continue
                                        token = "share:" + share["name"] + ":" + relative
                                        try:
                                            with self.vm_image_source(token) as (source, item):
                                                if self.vm_image_is_active(source, used):
                                                    continue
                                                image = self.vm_image_probe(source, item["format"])
                                                images.append({**item, "id": token, "virtual_size": image["virtual-size"]})
                                        except (Error, OSError, ValueError, subprocess.TimeoutExpired):
                                            continue
                            finally:
                                os.close(fd)
                    finally:
                        for fd, _, _ in pending:
                            os.close(fd)
                finally:
                    os.close(root)
            except (Error, OSError, ValueError) as exc:
                warnings.append("Image-Ordner " + share["name"] + " nicht verfügbar: " + str(exc))
            if scanned >= 3000 or inspected >= 24:
                warnings.append("Image-Suche begrenzt: maximal 24 Kandidaten und 3000 Einträge, bis 4 Unterordner.")
                break
        return {"storage": storage, "disk_images": images, "warnings": warnings}

    def vm_active_image_paths(self):
        used = set()
        domains = self.command(["virsh", "list", "--uuid"], timeout=5).splitlines()
        if len(domains) > 128:
            raise Error("Zu viele aktive VMs für eine sichere Image-Prüfung.", 409)
        for vm in domains:
            root = ET.fromstring(self.command(["virsh", "dumpxml", vm], timeout=5))
            for source in root.findall("./devices/disk/source"):
                if source.get("file"):
                    used.add(str(Path(source.get("file"))))
        return used

    @staticmethod
    def vm_image_is_active(fd, paths):
        before = os.fstat(fd)
        for path in paths:
            try:
                live = os.stat(path)
            except OSError:
                raise Error("Nutzung eines aktiven Laufwerks konnte nicht geprüft werden.", 409) from None
            if (live.st_dev, live.st_ino) == (before.st_dev, before.st_ino):
                return True
        return False

    @contextlib.contextmanager
    def vm_image_source(self, token):
        if isinstance(token, str) and token.startswith("/"):
            with self.vm_absolute_image_source(token) as source:
                yield source
            return
        if not isinstance(token, str) or len(token) > 4096 or not token.startswith("share:"):
            raise Error("Ungültiges Laufwerksimage.")
        parts = token.split(":", 2)
        if len(parts) != 3:
            raise Error("Ungültiges Laufwerksimage.")
        name = identifier(parts[1])
        relative = parts[2]
        if (not relative or "\\" in relative or "\x00" in relative or PurePosixPath(relative).is_absolute() or
                any(part in ("", ".", "..") for part in relative.split("/"))):
            raise Error("Ungültiger Image-Pfad.")
        share = next((item for item in self.op_shares() if item["name"] == name), None)
        if share is None or share.get("blocked") or name in getattr(self, "suspended_shares", set()):
            raise Error("Image-Freigabe ist nicht verfügbar.", 409)
        image_format = IMAGE_EXTENSIONS.get(Path(relative).suffix.lower())
        if image_format is None:
            raise Error("Nur qcow2-, raw- oder img-Laufwerksimages werden unterstützt.")
        root = self.open_share_root(share["path"])
        try:
            source = self.open_relative(root, relative)
            try:
                path = Path(share["path"]) / relative
                yield source, self.vm_source_metadata(source, path, "share:" + name)
            finally:
                os.close(source)
        finally:
            os.close(root)

    @staticmethod
    def vm_source_metadata(source, path, storage):
        image_format = IMAGE_EXTENSIONS.get(Path(path).suffix.lower())
        if image_format is None:
            raise Error("Nur qcow2-, raw- oder img-Laufwerksimages werden unterstützt.")
        info = os.fstat(source)
        if not stat.S_ISREG(info.st_mode) or info.st_size == 0 or info.st_size > MAX_IMAGE_SIZE:
            raise Error("Image muss eine vollständige reguläre Datei sein.")
        if os.pread(source, 4, 0) == b"QFI\xfb":
            image_format = "qcow2"
        return {"name": Path(path).name, "path": str(path), "format": image_format,
                "size": info.st_size, "storage": storage}

    @contextlib.contextmanager
    def vm_absolute_image_source(self, path):
        """Open an explicit administrator-selected file without following links."""
        if (not isinstance(path, str) or len(path) > 4096 or not path.startswith("/") or
                "\\" in path or any(ord(char) < 32 or ord(char) == 127 for char in path)):
            raise Error("Absoluten Pfad zu einem qcow2-, raw- oder img-Laufwerksimage angeben.")
        parts = path.split("/")[1:]
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise Error("Ungültiger absoluter Image-Pfad.")
        if parts[0] in ("dev", "proc", "sys"):
            raise Error("Kernel- und Gerätedateien können nicht als Laufwerksimage verwendet werden.", 403)
        if Path(path).suffix.lower() not in IMAGE_EXTENSIONS:
            raise Error("Nur qcow2-, raw- oder img-Laufwerksimages werden unterstützt.")
        # system_root is / in production, and a private temporary fixture in
        # demos/tests. The namespace stays attached to descriptors throughout.
        candidate = self.system_root / "/".join(parts)
        required_device = self.volume_manager.required_path(candidate)
        root = source = None
        try:
            try:
                root = os.open(self.system_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                source = self.open_relative(root, "/".join(parts))
                if required_device is not None and os.fstat(source).st_dev != required_device:
                    raise Error("Image-Volume wurde während des Zugriffs ausgehängt.", 503)
                item = self.vm_source_metadata(source, candidate, "system")
            except FileNotFoundError:
                raise Error("Laufwerksimage wurde unter diesem Pfad nicht gefunden.", 404) from None
            except OSError:
                raise Error("Laufwerksimage kann nicht sicher geöffnet werden. Reguläre Datei und Pfad ohne symbolische Links wählen.", 403) from None
            yield source, item
            if required_device is not None and self.volume_manager.required_path(candidate) != required_device:
                raise Error("Image-Volume wurde während des Zugriffs ausgetauscht.", 503)
        finally:
            if source is not None:
                os.close(source)
            if root is not None:
                os.close(root)

    def op_vm_image_details(self, path):
        """Bounded read-only hint; creation performs the private-copy validation."""
        with self.vm_image_source(path) as (source, item):
            used = self.vm_active_image_paths()
            if self.vm_image_is_active(source, used):
                raise Error("Image wird von einer laufenden VM verwendet; vor dem Import ausschalten.", 409)
            image = self.vm_image_probe(source, item["format"])
            return {**item, "id": path, "virtual_size": image["virtual-size"],
                    "min_disk_gb": max(8, math.ceil(image["virtual-size"] / GIB)),
                    "source_retained": True, "revision": revision(os.fstat(source))}

    @staticmethod
    def vm_image_header(fd, image_format):
        if image_format != "qcow2":
            return None
        header = os.pread(fd, 104, 0)
        if len(header) < 72 or header[:4] != b"QFI\xfb":
            raise Error("Image enthält keinen gültigen qcow2-Header.")
        version, backing_offset, backing_size = struct.unpack(">IQI", header[4:20])
        if version not in (2, 3) or backing_offset or backing_size or struct.unpack(">I", header[32:36])[0]:
            raise Error("Nur eigenständige, unverschlüsselte Images ohne Backing-Datei werden unterstützt.")
        if version == 3 and (len(header) < 104 or struct.unpack(">Q", header[72:80])[0] & 4):
            raise Error("qcow2 mit externer Datendatei wird nicht importiert.")
        return header

    def vm_image_probe(self, fd, image_format):
        # Share users may modify these bytes concurrently. This bounded read is
        # only an inventory hint and never asks root QEMU to open referenced data.
        header = self.vm_image_header(fd, image_format)
        size = struct.unpack(">Q", header[24:32])[0] if header else os.fstat(fd).st_size
        if size <= 0 or size > MAX_IMAGE_SIZE:
            raise Error("Imagegröße ist ungültig.")
        return {"format": image_format, "virtual-size": size}

    @staticmethod
    def vm_copy_sparse(source, target, size):
        offset = 0
        sparse = hasattr(os, "SEEK_DATA")
        while offset < size:
            end = size
            if sparse:
                try:
                    offset = os.lseek(source, offset, os.SEEK_DATA)
                    end = min(size, os.lseek(source, offset, os.SEEK_HOLE))
                except OSError as exc:
                    if exc.errno == errno.ENXIO:
                        break
                    if exc.errno not in (errno.EINVAL, errno.ENOTSUP):
                        raise
                    sparse = False
                    end = size
            while offset < end:
                data = os.pread(source, min(1024 * 1024, end - offset), offset)
                if not data:
                    raise Error("Quellimage wurde während des Kopierens verkürzt.", 409)
                written = 0
                while written < len(data):
                    count = os.pwrite(target, data[written:], offset + written)
                    if count <= 0:
                        raise Error("Image-Kopie konnte nicht vollständig geschrieben werden.", 500)
                    written += count
                offset += len(data)
        os.ftruncate(target, size)

    @contextlib.contextmanager
    def vm_private_image(self, target, source):
        # QEMU must never parse a header still writable by an SMB user. FICLONE
        # creates a private CoW snapshot where supported; otherwise a checked
        # sparse copy is completed before QEMU touches any bytes.
        name = ".import-" + secrets.token_hex(12)
        directory = copy = None
        created = False
        try:
            os.mkdir(name, 0o700, dir_fd=target)
            created = True
            directory = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=target)
            copy = os.open("source.img", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            before = os.fstat(source)
            try:
                fcntl.ioctl(copy, 0x40049409, source)  # Linux FICLONE
            except OSError:
                self.vm_copy_sparse(source, copy, before.st_size)
            os.fsync(copy)
            after = os.fstat(source)
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise Error("Quellimage wurde während der Snapshot-Kopie verändert. Import abgebrochen.", 409)
            yield copy
        finally:
            if copy is not None:
                os.close(copy)
            if directory is not None:
                try:
                    os.unlink("source.img", dir_fd=directory)
                except FileNotFoundError:
                    pass
                os.close(directory)
            if created:
                os.rmdir(name, dir_fd=target)

    def vm_image_info(self, fd, image_format, timeout=15):
        self.vm_image_header(fd, image_format)
        try:
            image = json.loads(self.command(["qemu-img", "info", "-f", image_format, "--output=json", "/proc/self/fd/" + str(fd)],
                                            timeout=timeout, pass_fds=(fd,)))
        except (ValueError, OSError) as exc:
            raise Error("Laufwerksimage konnte nicht geprüft werden.") from exc
        def external(value):
            if isinstance(value, dict):
                return any((key in ("backing-filename", "full-backing-filename", "data-file") and bool(item)) or external(item)
                           for key, item in value.items())
            if isinstance(value, list):
                return any(external(item) for item in value)
            return False
        size = image.get("virtual-size") if isinstance(image, dict) else None
        if (not isinstance(image, dict) or image.get("format") != image_format or external(image) or
                not isinstance(size, int) or isinstance(size, bool) or size <= 0 or size > MAX_IMAGE_SIZE):
            raise Error("Image ist nicht eigenständig oder seine virtuelle Größe ist ungültig.")
        return image

    def vm_disk_details(self, record):
        # Read only the fixed header for capacity; never bypass QEMU image locks
        # or parse live backing chains. Stored creation size is the fallback.
        metadata = next((item for item in self.load("vms", []) if item["name"] == record["name"]), {})
        size = metadata.get("virtual_size")
        allocated = None
        try:
            with self.vm_storage_fd(record["storage"]) as (fd, _):
                source = os.open(Path(record["disk"]).name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    size = self.vm_image_probe(source, "qcow2")["virtual-size"]
                    allocated = os.fstat(source).st_blocks * 512
                finally:
                    os.close(source)
        except (Error, OSError, ValueError):
            pass
        if not isinstance(size, int) or size < 0:
            size = None
        return {"disk_path": record["disk"], "storage": record["storage"], "virtual_size": size,
                "disk_gb": math.ceil(size / GIB) if size else None, "disk_allocated_bytes": allocated}

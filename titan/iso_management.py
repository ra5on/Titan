"""Staged installation media uploads. Incomplete images never enter the library."""
import base64
import binascii
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time
import xml.etree.ElementTree as ET

from .core import Error, atomic_json, integer


def run(*args, **kwargs):
    from .host import run as host_run
    return host_run(*args, **kwargs)


class IsoMixin:
    def iso_directory(self):
        directory = self.vm_root / "iso"
        if self.vm_root.is_symlink() or directory.is_symlink():
            raise Error("ISO-Verzeichnis darf kein symbolischer Link sein.", 403)
        directory.mkdir(parents=True, exist_ok=True, mode=0o755)
        if directory.resolve().parent != self.vm_root.resolve():
            raise Error("Ungültiges ISO-Verzeichnis.", 403)
        from .backups import directory_fd
        for path in (self.vm_root, directory):
            with directory_fd(path) as fd:
                info = os.fstat(fd)
                if info.st_uid != os.geteuid() or info.st_mode & 0o022:
                    raise Error("ISO-Speicher muss geschützt dem Verwaltungsdienst gehören.", 409)
                os.fchmod(fd, stat.S_IMODE(info.st_mode) | 0o011)
        return directory

    @staticmethod
    def iso_name(name):
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.iso", name):
            raise Error("Ungültiger ISO-Dateiname. Verwende Buchstaben, Zahlen, Punkt, Bindestrich oder Unterstrich.")
        return name

    def op_isos(self):
        directory = self.iso_directory()
        return sorted(item.name for item in directory.glob("*.iso")
                      if not item.is_symlink() and item.is_file() and item.stat().st_size > 0)

    def op_iso_library(self):
        inventory = self.op_vms()
        return {"items": [{"name": name, "size": (self.vm_root / "iso" / name).stat().st_size,
                           "used_by": [vm["name"] for vm in inventory["vms"] if vm.get("iso") == name]}
                          for name in self.op_isos()], "error": inventory.get("error")}

    def upload_paths(self, upload_id):
        if not isinstance(upload_id, str) or not re.fullmatch(r"[a-f0-9]{32}", upload_id):
            raise Error("Ungültige Upload-Kennung.")
        directory = self.iso_directory() / ".uploads"
        if directory.is_symlink():
            raise Error("Ungültiges Upload-Verzeichnis.", 403)
        directory.mkdir(mode=0o700, exist_ok=True)
        return directory / (upload_id + ".part"), directory / (upload_id + ".json")

    def op_iso_cancel(self, upload_id):
        partial, metadata = self.upload_paths(upload_id)
        partial.unlink(missing_ok=True)
        metadata.unlink(missing_ok=True)
        return {"ok": True}

    def op_iso_upload(self, name, offset, data, total, upload_id=None):
        name = self.iso_name(name)
        offset = integer(offset, 0, 64 * 1024**3)
        total = integer(total, 1, 64 * 1024**3)
        try:
            chunk = base64.b64decode(data, validate=True)
        except (ValueError, TypeError, binascii.Error):
            raise Error("Ungültiger Upload-Block.")
        if not chunk or len(chunk) > 1024**2 or offset + len(chunk) > total:
            raise Error("Ungültige Upload-Größe.")
        destination = self.iso_directory() / name
        if destination.exists() or destination.is_symlink():
            raise Error("ISO existiert bereits. Verwende einen anderen Dateinamen.", 409)
        if upload_id is None:
            if offset:
                raise Error("Upload-Kennung für weitere Blöcke erforderlich.", 409)
            upload_id = secrets.token_hex(16)
            partial, metadata = self.upload_paths(upload_id)
            # Remove abandoned uploads after one day; completed images are outside this directory.
            for old in partial.parent.glob("*.json"):
                if not old.is_symlink() and old.stat().st_mtime < time.time() - 86400:
                    old.with_suffix(".part").unlink(missing_ok=True)
                    old.unlink(missing_ok=True)
            atomic_json(metadata, {"name": name, "total": total})
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        else:
            partial, metadata = self.upload_paths(upload_id)
            if metadata.is_symlink() or not metadata.is_file() or json.loads(metadata.read_text()) != {"name": name, "total": total}:
                raise Error("Upload passt nicht zur begonnenen Übertragung.", 409)
            flags = os.O_WRONLY | os.O_NOFOLLOW
        try:
            fd = os.open(partial, flags | os.O_NONBLOCK, 0o600)
        except OSError:
            raise Error("Upload-Datei fehlt oder ist unsicher.", 409)
        with os.fdopen(fd, "wb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != offset:
                raise Error("Upload-Position stimmt nicht überein.", 409)
            stream.seek(offset)
            stream.write(chunk)
            stream.flush()
            if offset + len(chunk) == total:
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), 0o644)
        complete = offset + len(chunk) == total
        if complete:
            # link is atomic and refuses to replace existing media, including symbolic links.
            try:
                os.link(partial, destination, follow_symlinks=False)
            except FileExistsError:
                raise Error("ISO existiert bereits.", 409)
            partial.unlink()
            metadata.unlink()
        return {"offset": offset + len(chunk), "upload_id": upload_id, "complete": complete}

    def op_iso_remove(self, name):
        name = self.iso_name(name)
        path = self.vm_iso_path(name)
        # Also consider foreign guests: never delete an image still referenced by libvirt.
        for vm in run(["virsh", "list", "--all", "--uuid"]).splitlines():
            for arguments in (["virsh", "dumpxml", vm], ["virsh", "dumpxml", vm, "--inactive"]):
                root = ET.fromstring(run(arguments))
                for source in root.findall("./devices/disk/source"):
                    if source.get("file") and Path(source.get("file")).resolve() == path.resolve():
                        raise Error("ISO wird noch von einer VM verwendet. Zuerst das Medium auswerfen.", 409)
        path.unlink()
        return {"ok": True, "message": "ISO entfernt."}

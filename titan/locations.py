"""Read-only, named locations for ordinary NAS forms.

Selection is guidance only: the mutation's existing path, mount and permission
checks remain authoritative, including when a drive disappears after selection.
"""
import json
from pathlib import Path
import shutil

from .core import Error
from .backups import Backups


PROGRAMS = (("python3", "Python 3"), ("bash", "Bash"), ("node", "Node.js"),
            ("rsync", "Rsync"), ("rclone", "Rclone"), ("ffmpeg", "FFmpeg"))


def locations(host, runner):
    items, warnings = [], []
    backup_validator = Backups(host, runner)
    def add(path, label, kind, backup=False):
        try:
            canonical = Path(path).resolve()
            available = canonical.is_dir()
        except (OSError, RuntimeError):
            return
        if not available:
            return
        value = str(canonical)
        previous = next((item for item in items if item["path"] == value), None)
        if previous:
            previous["backup_eligible"] |= backup
            return
        items.append({"path": value, "label": label, "kind": kind,
                      "backup_eligible": backup})
    add(host.share_root, "Titan-Daten", "data")
    add(host.vm_root, "Virtuelle Laufwerke", "vm")
    for share in host.op_shares():
        add(share["path"], "Freigabe · " + share["name"], "share")
    try:
        mounted = json.loads(runner(["findmnt", "--json", "--list", "--output", "TARGET,SOURCE,FSTYPE,OPTIONS"]))
        for mount in mounted.get("filesystems", []):
            raw = mount.get("target")
            if not isinstance(raw, str) or not raw.startswith("/"):
                continue
            try:
                path = Path(raw).resolve()
            except (OSError, RuntimeError):
                continue
            if not any(path.is_relative_to(base) for base in (Path("/var/mnt"), Path("/var/media"), Path("/mnt"), Path("/media"))):
                continue
            if "ro" in str(mount.get("options", "")).split(","):
                continue
            eligible = False
            try:
                backup_validator.validate_target(str(path))
                eligible = True
            except (Error, OSError):
                pass
            add(path, f"Laufwerk · {path.name} ({mount.get('fstype') or 'Dateisystem'})", "mount", eligible)
    except (Error, OSError, ValueError, TypeError) as exc:
        warnings.append("Eingehängte Laufwerke konnten nicht vollständig ermittelt werden: " + str(exc))
    add("/", "Systemverzeichnis", "system")
    programs = [{"path": path, "label": label} for command, label in PROGRAMS
                if (path := shutil.which(command, path="/usr/sbin:/usr/bin:/sbin:/bin"))]
    return {"items": items, "programs": programs, "warnings": warnings}


class LocationsMixin:
    def op_storage_locations(self):
        from .host import run
        return locations(self, run)

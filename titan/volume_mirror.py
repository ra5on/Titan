"""Btrfs mirrors across several disks: health, guided disk replacement, scrubs.

A mirror keeps two copies of everything (Btrfs raid1 for data and metadata).
Titan never mounts a mirror with a missing disk on its own account at boot:
the degraded mount happens only as the first step of a replacement the
administrator confirmed, and the finishing pass restores full redundancy.
"""
import contextlib
import os
from pathlib import Path
import re
import stat
import time
from .core import Error

MIRROR_LIMIT = 4
SCRUB_INTERVAL = 30 * 86400
ERRORS = ("write_errs", "read_errs", "flush_errs", "corruption_errs", "generation_errs")


def members(record):
    return list(record.get("disks") or [record["disk"]])


def mirrored(record):
    return record.get("filesystem") == "btrfs" and len(members(record)) > 1


def replace_state(text):
    """Reduce `btrfs replace status -1` to a state and a percentage."""
    lowered = text.lower()
    progress = re.search(r"([0-9]+(?:\.[0-9]+)?)% done", lowered)
    if "never started" in lowered or not lowered.strip():
        return {"state": "none", "percent": None}
    for word, state in (("finished on", "finished"), ("canceled on", "canceled"), ("suspended on", "suspended")):
        if word in lowered:
            return {"state": state, "percent": 100.0 if state == "finished" else float(progress.group(1)) if progress else None}
    return {"state": "running", "percent": float(progress.group(1)) if progress else None}


class MirrorMixin:
    sysfs = Path("/sys/fs/btrfs")
    replace_pause = 1.0

    def mirror_disks(self, disk, filesystem, mirror):
        """Validate the additional disks of a new mirror."""
        if mirror in (None, []):
            return []
        if filesystem != "btrfs":
            raise Error("Ein Verbund aus mehreren Laufwerken ist hier nur mit Btrfs möglich.")
        if (not isinstance(mirror, list) or not 1 <= len(mirror) < MIRROR_LIMIT or
                any(not isinstance(item, str) for item in mirror) or len(set(mirror + [disk])) != len(mirror) + 1):
            raise Error(f"Ein Btrfs-Verbund besteht aus zwei bis {MIRROR_LIMIT} verschiedenen Laufwerken.")
        return list(mirror)

    def update(self, name, **changes):
        self.host.save("volumes", [{**item, **changes} if item["name"] == name else item for item in self.records()])

    def present(self, record):
        """Member disks the system currently sees, found by the filesystem UUID."""
        from .volumes import flatten
        return [item for item in flatten(self.host.disks()) if item.get("uuid") == record["uuid"]]

    def mirror_health(self, record):
        """Kernel view of a mounted Btrfs volume; None while it is not mounted."""
        base = self.sysfs / record["uuid"]
        if not (base / "devinfo").is_dir():
            return None
        missing, errors, replacing = [], 0, False
        for entry in (base / "devinfo").iterdir():
            def read(name):
                try:
                    return (entry / name).read_text().strip()
                except OSError:
                    return ""
            if read("replace_target") == "1":
                replacing = True
                continue
            if read("missing") == "1" and entry.name.isdigit():
                missing.append(int(entry.name))
            for line in read("error_stats").splitlines():
                fields = line.split()
                if len(fields) == 2 and fields[0] in ERRORS and fields[1].isdigit():
                    errors += int(fields[1])
        devices = base / "devices"
        present = sorted("/dev/" + item.name for item in devices.iterdir()) if devices.is_dir() else []
        return {"missing": sorted(missing), "errors": errors, "replacing": replacing, "present": present}

    def replace_text(self, record):
        return self.run(["btrfs", "replace", "status", "-1", "--", str(self.root / record["name"])])

    def replace_status(self, record):
        return replace_state(self.replace_text(record))

    def replace_started(self, record, before, attempts=10):
        """The start command detaches before the kernel accepts the disk, so confirm the copy began."""
        for _ in range(attempts):
            text = self.replace_text(record)
            if text != before or replace_state(text)["state"] in ("running", "suspended"):
                return True
            time.sleep(self.replace_pause)
        return False

    def mount_degraded(self, record):
        """Mount a mirror with a missing disk. Only a replacement calls this."""
        if not self.present(record):
            raise Error("Kein Laufwerk dieses Verbunds ist angeschlossen.", 409)
        with self.target_fd(record, create=True) as target:
            if os.listdir(target):
                raise Error("Unter dem ungemounteten Volume liegen Dateien; Einhängen verweigert.")
            os.fchmod(target, 0o000)
        self.persist(record)
        self.run(["systemctl", "daemon-reload"])
        self.run(["btrfs", "device", "scan"])
        self.run(["mount", "-o", "degraded", "--", str(self.root / record["name"])], timeout=120)
        mounted = self.mounted(record)
        if mounted is None:
            raise Error("Einhängen wurde nicht bestätigt.")
        with self.target_fd(record) as target:
            if os.fstat(target).st_dev != mounted:
                raise Error("Volume wurde während der Prüfung ausgehängt.")
            os.fchmod(target, 0o755)

    def replace(self, name, disk, confirmation_name=None, confirmation_disk=None, member=None):
        """Start copying a mirror onto a blank disk in place of a missing or failing one."""
        record = self.record(name)
        if not mirrored(record):
            raise Error("Nur ein Btrfs-Verbund aus mehreren Laufwerken kann ein Laufwerk ersetzen.")
        if confirmation_name != record["name"] or confirmation_disk != disk:
            raise Error("Bestätigung ungültig. Volume-Name und exakten Laufwerkspfad bestätigen.")
        if record.get("replacing"):
            raise Error("Für diesen Verbund läuft bereits ein Austausch.", 409)
        device = self.blank_disk(disk, "btrfs")
        if self.mounted(record) is None:
            self.mount_degraded(record)
        health = self.mirror_health(record)
        if health is None:
            raise Error("Der Zustand des Verbunds konnte nicht gelesen werden.", 503)
        before = self.replace_text(record)
        if health["replacing"] or replace_state(before)["state"] in ("running", "suspended"):
            self.update(name, replacing={"disk": disk, "started": time.time()})
            raise Error("Ein unterbrochener Austausch wird fortgesetzt. Abschluss abwarten.", 409)
        if len(health["missing"]) > 1:
            raise Error("Dem Verbund fehlen mehrere Laufwerke. Daten zuerst aus einer Sicherung wiederherstellen.", 409)
        if health["missing"]:
            source, arguments = str(health["missing"][0]), []
        elif member in health["present"]:
            # A present but failing disk is read only where no good copy exists.
            source, arguments = member, ["-r"]
        else:
            raise Error("Dem Verbund fehlt kein Laufwerk. Das zu ersetzende Laufwerk auswählen.", 409)
        fd = os.open(disk, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISBLK(opened.st_mode) or opened.st_rdev != device or self.blank_disk(disk, "btrfs") != device:
                raise Error("Laufwerk wurde während der Sicherheitsprüfung ausgetauscht.")
            self.update(name, replacing={"disk": disk, "started": time.time()}, error=None)
            try:
                # The kernel remembers the path it is given, so this must be the real device path.
                self.run(["btrfs", "replace", "start", *arguments, source, disk, str(self.root / name)], timeout=300)
                if not self.replace_started(record, before):
                    raise Error("Der Austausch ist nicht gestartet. Das Ersatzlaufwerk muss mindestens so groß sein wie das ersetzte; Einzelheiten stehen im Systemprotokoll.", 409)
            except Exception:
                self.update(name, replacing=None)
                raise
        finally:
            os.close(fd)
        return {"ok": True, "message": "Der Austausch läuft. Die Daten bleiben währenddessen erreichbar; der Fortschritt steht auf der Speicherseite."}

    def finish_replace(self, record):
        """Complete a replacement: wait for the copy, then restore two copies of everything."""
        name = record["name"]
        if self.mounted(record) is None:
            self.mount_degraded(record)  # The kernel resumes an interrupted copy on mount.
        if self.replace_status(record)["state"] in ("running", "suspended"):
            return False
        health = self.mirror_health(record)
        if health is None or health["replacing"]:
            return False
        if health["missing"]:
            self.update(name, replacing=None, error="Der Austausch wurde nicht abgeschlossen. Laufwerk prüfen und erneut ersetzen.")
            return True
        # Data written while a disk was missing exists only once; mirror it again.
        self.run(["btrfs", "balance", "start", "-dconvert=raid1,soft", "-mconvert=raid1,soft", "--", str(self.root / name)], timeout=6 * 3600)
        with contextlib.suppress(Error):
            self.run(["btrfs", "device", "stats", "--reset", "--", str(self.root / name)])
        present = health["present"] or members(record)
        self.update(name, disks=present, disk=present[0], replacing=None, error=None, phase="ready")
        return True

    def scrub_due(self, record, now):
        """Let Btrfs read every block monthly so silent damage is found and repaired."""
        if now - record.get("scrubbed", record.get("created", 0)) < SCRUB_INTERVAL or self.mounted(record) is None:
            return False
        self.update(record["name"], scrubbed=now)
        self.run(["btrfs", "scrub", "start", "--", str(self.root / record["name"])])
        return True

    def maintain(self, now=None):
        """Periodic pass of the system service over all Btrfs volumes."""
        now = time.time() if now is None else now
        for record in self.records():
            if record["filesystem"] != "btrfs" or record.get("phase") in ("formatting", "format_failed", "verify_failed"):
                continue
            with contextlib.suppress(Error, OSError, ValueError):
                if record.get("replacing"):
                    self.finish_replace(record)
                else:
                    self.scrub_due(record, now)

    def mirror_inventory(self, record, item):
        """Add the mirror's members and condition to one inventory row."""
        expected = members(record)
        item.update(disks=expected, mirror=mirrored(record), degraded=False, errors=0, replacing=None)
        health = self.mirror_health(record) if item["mounted"] else None
        if health:
            item["errors"] = health["errors"]
            if health["present"]:
                item["disks"] = health["present"]
        if record.get("replacing"):
            status = {"state": "running", "percent": None}
            if item["mounted"]:
                with contextlib.suppress(Error, OSError):
                    status = self.replace_status(record)
            item.update(replacing={"disk": record["replacing"].get("disk"), "percent": status["percent"]},
                        state="Austausch läuft" if item["mounted"] else "Austausch unterbrochen")
        elif not mirrored(record):
            pass
        elif health and health["missing"]:
            item.update(degraded=True, state="Laufwerk fehlt", error="Ein Laufwerk des Verbunds fehlt. Die Daten liegen nur noch einfach vor.")
        elif not item["mounted"] and len(self.present(record)) < len(expected):
            item.update(degraded=True, state="Laufwerk fehlt", error="Ein Laufwerk des Verbunds fehlt. Ersetze es, damit der Verbund wieder eingehängt wird.")
        if item["errors"] and not item["replacing"] and not item["degraded"]:
            item.update(state="Fehler gefunden", error=f"Btrfs hat {item['errors']} Lese-, Schreib- oder Prüfsummenfehler gezählt. " +
                        ("Das betroffene Laufwerk ersetzen." if mirrored(record) else "Laufwerk prüfen und die Daten sichern."))
        return item

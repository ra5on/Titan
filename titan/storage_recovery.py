"""Conservative replacement of failed members in Titan-managed ZFS pools.

The current topology is read from ZFS, never inferred from saved layout choices.
Only a simple redundant data vdev is supported. No force, detach, import,
labelclear, or rollback commands are exposed. A successful replace STARTS a ZFS
resilver; it is not proof that data recovery or the resilver has completed.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import threading

from .core import Error, identifier
from .volumes import DISK, flatten

GUID = re.compile(r"[1-9][0-9]{0,19}\Z")
REVISION = re.compile(r"[a-f0-9]{64}\Z")
STATES = {"ONLINE", "DEGRADED", "FAULTED", "OFFLINE", "UNAVAIL", "REMOVED", "AVAIL", "INUSE"}
FAILED = {"FAULTED", "OFFLINE", "UNAVAIL", "REMOVED"}
ROW = re.compile(r"^(\s*)(\S+)\s+(" + "|".join(sorted(STATES)) + r")\s+(\d+)\s+(\d+)\s+(\d+)(?:\s+(.*))?$")
ARGUMENTS = {"pool", "member_guid", "disk", "expected_revision", "confirmation_pool", "confirmation_disk"}
PLACEHOLDER_SERIALS = {"unknown", "none", "n/a", "na", "not available", "to be filled by o.e.m.", "default string"}


def validate_replace(arguments):
    if not isinstance(arguments, dict) or set(arguments) != ARGUMENTS:
        raise Error("Pool, ausgefallenes Mitglied, Ersatzlaufwerk, aktueller Stand und beide Bestätigungen sind erforderlich.")
    identifier(arguments["pool"])
    if not isinstance(arguments["member_guid"], str) or not GUID.fullmatch(arguments["member_guid"]):
        raise Error("Das ausgefallene Poolmitglied anhand seiner ZFS-Kennung auswählen.")
    if not isinstance(arguments["disk"], str) or not DISK.fullmatch(arguments["disk"]):
        raise Error("Ein direktes physisches Ersatzlaufwerk auswählen.")
    if not isinstance(arguments["expected_revision"], str) or not REVISION.fullmatch(arguments["expected_revision"]):
        raise Error("Speicherzustand aktualisieren und erneut prüfen.")
    if arguments["confirmation_pool"] != arguments["pool"] or arguments["confirmation_disk"] != arguments["disk"]:
        raise Error("Poolname und exakten Ersatzlaufwerkspfad zur Bestätigung eingeben.")


def status_rows(output):
    """Parse the stable C-locale config table; unknown sections fail closed."""
    if not isinstance(output, str) or len(output) > 512 * 1024:
        raise Error("ZFS-Poolstatus ist ungültig.", 503)
    inside, rows, sections = False, [], []
    for source in output.splitlines():
        line = source.expandtabs(8)
        if line.strip() == "config:":
            inside = True
            continue
        if not inside:
            continue
        if line.lstrip().startswith("errors:"):
            break
        if not line.strip() or line.lstrip().startswith("NAME "):
            continue
        match = ROW.fullmatch(line)
        if match is None:
            sections.append(line.strip())
            continue
        spaces, name, state, read, write, checksum, note = match.groups()
        rows.append({"indent": len(spaces), "name": name, "state": state,
                     "read_errors": int(read), "write_errors": int(write),
                     "checksum_errors": int(checksum), "note": note or ""})
    if not rows:
        raise Error("ZFS-Pooltopologie konnte nicht zuverlässig gelesen werden.", 503)
    return rows, sections


def scan_status(output):
    lines = output.splitlines()
    selected = []
    collecting = False
    for line in lines:
        if line.lstrip().startswith("scan:"):
            collecting = True
        if collecting:
            if line.lstrip().startswith(("config:", "expand:", "remove:", "checkpoint:")):
                break
            if line.strip():
                selected.append(line.strip())
    detail = " ".join(selected).removeprefix("scan:").strip()
    lowered = detail.lower()
    kind = "resilver" if "resilver" in lowered else "scrub" if "scrub" in lowered else "none"
    active = "in progress" in lowered or "resilvering" in output.lower() or "(repairing)" in output.lower()
    percentage = re.search(r"(\d+(?:\.\d+)?)% done", detail)
    return {"kind": kind, "active": active,
            "progress_percent": float(percentage.group(1)) if percentage and 0 <= float(percentage.group(1)) <= 100 else None,
            "detail": detail or "Kein Prüflauf oder Wiederaufbau gemeldet."}


def topology(pool, guid_output, path_output):
    guids, guid_sections = status_rows(guid_output)
    paths, path_sections = status_rows(path_output)
    if len(guids) != len(paths) or guid_sections != path_sections:
        raise Error("ZFS-Topologie hat sich während der Prüfung verändert. Erneut laden.", 409)
    for left, right in zip(guids, paths):
        if (left["indent"], left["state"]) != (right["indent"], right["state"]):
            raise Error("ZFS-Topologie hat sich während der Prüfung verändert. Erneut laden.", 409)
    if paths[0]["name"] != pool or guids[0]["name"] not in (pool, paths[0]["name"]) and not GUID.fullmatch(guids[0]["name"]):
        raise Error("ZFS-Poolkennung ist widersprüchlich.", 503)
    depths = sorted(set(row["indent"] for row in paths))
    simple = (not path_sections and len(depths) == 3 and len(paths) >= 4 and
              paths[1]["indent"] == depths[1] and
              all(row["indent"] == depths[2] for row in paths[2:]))
    layout_match = re.fullmatch(r"(mirror|raidz1|raidz2)-[0-9]+", paths[1]["name"]) if len(paths) > 1 else None
    layout = layout_match.group(1) if layout_match else "unsupported"
    members = []
    for index, (left, right) in enumerate(zip(guids, paths)):
        # Leaf nodes only; replacing/spare nesting is deliberately unsupported.
        if index == 0 or index + 1 < len(paths) and paths[index + 1]["indent"] > right["indent"]:
            continue
        if not GUID.fullmatch(left["name"]) or int(left["name"]) >= 2**64:
            raise Error("ZFS-Mitglied besitzt keine eindeutige gültige Kennung.", 503)
        display_path = right["name"]
        if GUID.fullmatch(display_path):
            previous = re.search(r"(?:^|\s)was (\S+)", right["note"])
            display_path = previous.group(1) if previous else ""
        members.append({"guid": left["name"], "path": display_path, "state": right["state"],
                        **{key: right[key] for key in ("read_errors", "write_errors", "checksum_errors")},
                        "replaceable": False})
    if len({member["guid"] for member in members}) != len(members):
        raise Error("ZFS-Mitglieder sind nicht eindeutig.", 503)
    minimum = {"mirror": 2, "raidz1": 3, "raidz2": 4}.get(layout, 0)
    return {"health": paths[0]["state"], "layout": layout,
            "reported_pool_guid": guids[0]["name"] if GUID.fullmatch(guids[0]["name"]) else None,
            "supported": bool(simple and layout_match and len(members) >= minimum), "members": members}


def revision_for(value):
    members = [{key: item[key] for key in ("guid", "path", "state", "replaceable")} for item in value["members"]]
    candidates = [{key: item.get(key) for key in ("disk", "device_path", "serial", "model", "size", "maj:min", "smart_health", "eligible", "reason")}
                  for item in value["candidates"]]
    identity = {key: value[key] for key in ("pool", "pool_guid", "health", "managed", "layout", "supported", "minimum_size")}
    identity.update(members=members, candidates=candidates, scan_active=value["scan"]["active"])
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class StorageRecovery:
    def __init__(self, host, run):
        self.host, self.run = host, run
        self.lock = threading.RLock()

    def device_path(self, disk):
        """Prefer a persistent by-id name; candidates remain direct lsblk disks."""
        directory = Path("/dev/disk/by-id")
        if directory.is_dir():
            names = sorted(directory.iterdir(), key=lambda item: (not item.name.startswith(("wwn-", "nvme-eui.", "ata-", "scsi-")), item.name))
            for item in names:
                if "-part" not in item.name and item.is_symlink() and os.path.realpath(item) == disk:
                    return str(item)
        return disk

    def smart_health(self, disk):
        try:
            data = self.host.op_smart(disk)
            from .monitoring import self_test_failure
            exit_status = data.get("smartctl", {}).get("exit_status", 0)
            if type(exit_status) is not int or exit_status & 7:
                return "unknown"
            if exit_status & 8 or self_test_failure(data):
                return "failed"
            passed = data.get("smart_status", {}).get("passed")
            if type(passed) is bool:
                return "passed" if passed else "failed"
        except (Error, OSError, ValueError, KeyError, TypeError, AttributeError, TimeoutError, subprocess.TimeoutExpired):
            pass
        return "unknown"

    def status(self, pool):
        pool = identifier(pool)
        imported = self.run(["zpool", "list", "-H", "-o", "name"], timeout=20).splitlines()
        if pool not in imported:
            raise Error("ZFS-Pool ist nicht importiert oder nicht verfügbar.", 404)
        pool_guid = self.run(["zpool", "get", "-H", "-o", "value", "guid", pool], timeout=20).strip()
        if not GUID.fullmatch(pool_guid) or int(pool_guid) >= 2**64:
            raise Error("ZFS-Poolkennung ist ungültig.", 503)
        guid_output = self.run(["zpool", "status", "-g", "-p", pool], timeout=20)
        path_output = self.run(["zpool", "status", "-L", "-P", "-p", pool], timeout=20)
        value = topology(pool, guid_output, path_output)
        if value["reported_pool_guid"] is not None and value["reported_pool_guid"] != pool_guid:
            raise Error("ZFS-Poolkennung hat sich während der Prüfung verändert. Erneut laden.", 409)
        record = next((item for item in self.host.load("pools", []) if item.get("name") == pool and
                       item.get("mountpoint") == str(self.host.share_root / pool)), None)
        known_guid = record.get("guid") if record else None
        value.update(pool=pool, pool_guid=pool_guid, scan=scan_status(path_output), raw_status=path_output,
                     managed=record is not None, identity_confirmed=bool(known_guid and known_guid == pool_guid))
        reason = ""
        healthy = sum(item["state"] == "ONLINE" for item in value["members"])
        failed = sum(item["state"] in FAILED for item in value["members"])
        tolerance = {"mirror": len(value["members"]) - 1, "raidz1": 1, "raidz2": 2}.get(value["layout"], 0)
        if not value["managed"]:
            reason = "Dieser Pool wird nicht von Titan verwaltet. Automatischer Laufwerkstausch ist gesperrt."
        elif known_guid is not None and known_guid != pool_guid:
            reason = "Die gespeicherte ZFS-Poolkennung stimmt nicht überein. Automatischer Laufwerkstausch ist gesperrt."
        elif not value["supported"]:
            reason = "Automatischer Austausch unterstützt einen einfachen Mirror-, RAIDZ1- oder RAIDZ2-Datenverbund ohne Zusatzgeräte."
        elif value["health"] not in ("ONLINE", "DEGRADED") or healthy < len(value["members"]) - tolerance:
            reason = "Nicht genügend gesunde Mitglieder oder der Pool ist nicht zugänglich. Wiederherstellung aus einer unabhängigen Sicherung prüfen."
        elif value["scan"]["active"]:
            reason = "Ein Prüflauf oder Wiederaufbau läuft bereits. Vor einem weiteren Laufwerkstausch Abschluss abwarten."
        elif any(item["state"] not in FAILED | {"ONLINE"} for item in value["members"]):
            reason = "Der Mitgliedszustand ist nicht eindeutig. Automatischer Austausch ist gesperrt."
        elif not failed:
            reason = "Kein ausgefallenes Poolmitglied erkannt. Gesunde Laufwerke werden nicht ausgetauscht."
        for item in value["members"]:
            item["replaceable"] = not reason and item["state"] in FAILED
        value["reason"] = reason
        disks = self.host.disks()
        owners = {}
        for disk in disks:
            for child in flatten([disk]):
                owners[child["name"]] = disk
        sizes = [int(owners[item["path"]]["size"]) for item in value["members"]
                 if item["state"] == "ONLINE" and item["path"] in owners]
        # Conservative whole-disk minimum. ZFS performs the final usable-size check.
        value["minimum_size"] = min(sizes) if len(sizes) == healthy and sizes else None
        candidates = []
        active_disks = {owners[item["path"]]["name"] for item in value["members"] if item["state"] == "ONLINE" and item["path"] in owners}
        serials = [str(item.get("serial") or "").strip().casefold() for item in disks if item.get("type") == "disk"]
        for disk in disks:
            if disk.get("type") != "disk":
                continue
            candidate = {"disk": disk["name"], "device_path": self.device_path(disk["name"]),
                         "model": disk.get("model") or "", "serial": disk.get("serial") or "",
                         "size": int(disk.get("size") or 0), "maj:min": disk.get("maj:min"), "smart_health": "unknown", "eligible": False}
            problem = ""
            serial = candidate["serial"].strip().casefold()
            if disk["name"] in active_disks:
                problem = "Laufwerk gehört bereits zum aktiven Pool."
            elif not serial or serial in PLACEHOLDER_SERIALS or re.fullmatch(r"[0f\s-]+", serial) or serials.count(serial) != 1:
                problem = "Keine eindeutige Seriennummer verfügbar. Laufwerk kann nicht sicher bestätigt werden."
            elif not candidate["device_path"].startswith("/dev/disk/by-id/"):
                problem = "Kein dauerhafter Hardwarepfad verfügbar. Automatischer Laufwerkstausch ist gesperrt."
            elif value["minimum_size"] is None:
                problem = "Benötigte Laufwerksgröße konnte nicht zuverlässig ermittelt werden."
            elif candidate["size"] < value["minimum_size"]:
                problem = "Ersatzlaufwerk ist kleiner als die verbleibenden Poollaufwerke."
            else:
                try:
                    self.host.volume_manager.blank_disk(candidate["disk"], "ext4")
                except (Error, OSError, ValueError, KeyError, TypeError) as exc:
                    problem = str(exc)[:400]
                else:
                    candidate["smart_health"] = self.smart_health(candidate["disk"])
                    if candidate["smart_health"] != "passed":
                        problem = "SMART meldet einen Laufwerksfehler." if candidate["smart_health"] == "failed" else "SMART-Zustand konnte nicht bestätigt werden. Automatischer Austausch ist gesperrt."
            candidate.update(eligible=not problem, reason=problem)
            candidates.append(candidate)
        value["candidates"] = candidates
        value["revision"] = revision_for(value)
        return value

    def replace(self, **arguments):
        validate_replace(arguments)
        with self.lock:
            before = self.status(arguments["pool"])
            if before["revision"] != arguments["expected_revision"]:
                raise Error("Poolzustand oder Laufwerksidentität hat sich geändert. Vorschau aktualisieren.", 409)
            member = next((item for item in before["members"] if item["guid"] == arguments["member_guid"]), None)
            if member is None or not member["replaceable"]:
                raise Error(before["reason"] or "Nur ein erkanntes ausgefallenes Mitglied kann ersetzt werden.", 409)
            candidate = next((item for item in before["candidates"] if item["disk"] == arguments["disk"]), None)
            if candidate is None or not candidate["eligible"]:
                raise Error((candidate or {}).get("reason") or "Ersatzlaufwerk ist nicht verfügbar.", 409)
            device = self.host.volume_manager.blank_disk(candidate["disk"], "ext4")
            fd = os.open(candidate["disk"], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                opened = os.fstat(fd)
                if not stat.S_ISBLK(opened.st_mode) or opened.st_rdev != device:
                    raise Error("Ersatzlaufwerk wurde ausgetauscht.", 409)
                latest = self.status(arguments["pool"])
                if latest["revision"] != before["revision"] or self.host.volume_manager.blank_disk(candidate["disk"], "ext4") != device:
                    raise Error("Pool oder Ersatzlaufwerk wurde während der Prüfung verändert.", 409)
                target = os.stat(candidate["device_path"])
                if not stat.S_ISBLK(target.st_mode) or target.st_rdev != device:
                    raise Error("Der dauerhafte Laufwerkspfad verweist auf ein anderes Gerät.", 409)
                # ZFS must retain a persistent hardware path, including its
                # whole-disk partition suffix. /proc/self/fd cannot be used as
                # its durable vdev path. The open handle is an additional
                # identity check, not an atomic libzfs/udev hotplug guarantee.
                self.run(["zpool", "replace", arguments["pool"], member["guid"], candidate["device_path"]], timeout=120)
            finally:
                os.close(fd)
            # ZFS owns the persistent resilver job; no waiting or forced retries.
            return {"ok": True, "pool": arguments["pool"], "member_guid": member["guid"], "disk": candidate["disk"],
                    "resilver_started": True, "completed": False,
                    "message": "Laufwerkstausch an ZFS übergeben. Wiederaufbau und Poolzustand bis zum Abschluss beobachten; dies ist noch keine abgeschlossene Datenwiederherstellung."}

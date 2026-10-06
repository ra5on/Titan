"""Scheduled, allow-listed SMART/ZFS maintenance and non-destructive recovery.

Snapshot recovery creates a new dataset. It never rolls back the live dataset or
recursively destroys newer/manual snapshots. Retention touches only snapshots
created by the SAME saved schedule ID.
"""
import datetime
import os
from pathlib import Path
import re
import secrets
import threading
import time

from .backups import directory_fd
from .core import Error, identifier, integer

JOB_ID = re.compile(r"m-[a-f0-9]{16}")
SNAPSHOT_PART = re.compile(r"[A-Za-z0-9_.:-]{1,255}")


class StorageMaintenance:
    def __init__(self, host, run):
        self.host, self.run = host, run
        self.lock = threading.RLock()

    def settings(self):
        return self.host.load("storage-maintenance", {"jobs": []})

    def inventory(self):
        storage = self.host.op_storage()
        return {"disks": [item for item in storage.get("disks", []) if item.get("type") == "disk"],
                "pools": storage.get("pools", []), "datasets": storage.get("datasets", [])}

    def validate(self, job):
        allowed = {"id", "type", "target", "enabled", "interval", "window_day", "window_hour", "test", "retention"}
        if not isinstance(job, dict) or set(job) - allowed:
            raise Error("Ungültiger Wartungszeitplan.")
        result = {"enabled": True, "interval": "weekly", "window_day": 6,
                  "window_hour": 3, "test": "short", "retention": 14, **job}
        if not JOB_ID.fullmatch(str(result.get("id", ""))):
            raise Error("Ungültige Zeitplankennung.")
        if type(result["enabled"]) is not bool or result["interval"] not in ("daily", "weekly"):
            raise Error("Ungültiges Wartungsintervall.")
        result["window_day"] = integer(result["window_day"], 0, 6)
        result["window_hour"] = integer(result["window_hour"], 0, 23)
        result["retention"] = integer(result["retention"], 1, 365)
        if result["test"] not in ("short", "long"):
            raise Error("SMART-Test muss kurz oder ausführlich sein.")
        inventory = self.inventory()
        choices = {"smart": {item["name"] for item in inventory["disks"]},
                   "scrub": {item["name"] for item in inventory["pools"]},
                   "snapshot": {item["name"] for item in inventory["datasets"]}}
        if (not isinstance(result.get("type"), str) or not isinstance(result.get("target"), str) or
                result["type"] not in choices or result["target"] not in choices[result["type"]]):
            raise Error("Das ausgewählte Laufwerk oder der Speicherbereich ist nicht verfügbar.", 404)
        return result

    def save_job(self, **value):
        with self.lock:
            state = self.settings()
            if not value.get("id"):
                value["id"] = "m-" + secrets.token_hex(8)
            elif not any(item["id"] == value["id"] for item in state["jobs"]):
                raise Error("Wartungszeitplan nicht gefunden.", 404)
            job = self.validate(value)
            jobs = [item for item in state["jobs"] if item["id"] != job["id"]]
            if len(jobs) >= 200:
                raise Error("Maximal 200 Wartungszeitpläne sind erlaubt.")
            jobs.append(job)
            self.host.save("storage-maintenance", {"jobs": jobs})
            return job

    def remove_job(self, id):
        with self.lock:
            if not isinstance(id, str) or not JOB_ID.fullmatch(id):
                raise Error("Ungültige Zeitplankennung.")
            state = self.settings()
            if not any(item["id"] == id for item in state["jobs"]):
                raise Error("Wartungszeitplan nicht gefunden.", 404)
            self.host.save("storage-maintenance", {"jobs": [item for item in state["jobs"] if item["id"] != id]})
            return {"ok": True}

    def smart_test(self, disk, test="short"):
        if test not in ("short", "long") or disk not in {item["name"] for item in self.inventory()["disks"]}:
            raise Error("Nur erkannte physische Laufwerke können mit einem kurzen oder ausführlichen SMART-Test geprüft werden.")
        output = self.run(["smartctl", "-t", test, "-j", disk], timeout=30)
        return {"ok": True, "disk": disk, "test": test,
                "message": "SMART-Selbsttest gestartet. Ergebnis nach Abschluss im Laufwerkszustand prüfen.", "output": output}

    def snapshots(self):
        inventory = self.inventory()
        if not inventory["pools"]:
            return []
        output = self.run(["zfs", "list", "-H", "-p", "-t", "snapshot", "-o", "name,used,creation,titan:maintenance"])
        datasets = {item["name"] for item in inventory["datasets"]}
        result = []
        for line in output.splitlines():
            fields = line.split("\t")
            if len(fields) not in (3, 4):
                raise Error("Ungültige ZFS-Wiederherstellungspunktliste.")
            name, used, created = fields[:3]
            owner = fields[3] if len(fields) == 4 and JOB_ID.fullmatch(fields[3]) else None
            dataset, separator, suffix = name.partition("@")
            if separator and dataset in datasets and SNAPSHOT_PART.fullmatch(suffix):
                result.append({"name": name, "dataset": dataset, "used": int(used), "created": int(created),
                               "automatic": owner is not None, "schedule_id": owner})
        return sorted(result, key=lambda item: (item["created"], item["name"]), reverse=True)

    def snapshot(self, name):
        if not isinstance(name, str) or len(name) > 4096:
            raise Error("Ungültiger Wiederherstellungspunkt.")
        item = next((item for item in self.snapshots() if item["name"] == name), None)
        if item is None:
            raise Error("Wiederherstellungspunkt nicht gefunden.", 404)
        return item

    def remove_snapshot(self, snapshot, confirmed=False):
        with self.lock:
            if confirmed is not True:
                raise Error("Löschen zuerst bestätigen.")
            item = self.snapshot(snapshot)
            # No -r/-R: clones, holds or dependencies fail safely.
            self.run(["zfs", "destroy", item["name"]])
            return {"ok": True}

    def restore_snapshot(self, snapshot, name):
        with self.lock:
            item = self.snapshot(snapshot)
            name = identifier(name)
            storage = self.inventory()
            parent = next((dataset for dataset in storage["datasets"] if dataset["name"] == item["dataset"]), None)
            if not parent or not parent.get("mountpoint"):
                raise Error("Quellspeicher ist nicht eingehängt.")
            mountpoint = Path(parent["mountpoint"])
            if not mountpoint.is_absolute() or not mountpoint.is_relative_to(self.host.share_root):
                raise Error("Nur verwaltete NAS-Speicherbereiche können wiederhergestellt werden.")
            target = parent["name"] + "/" + name
            destination = mountpoint / name
            if target in {dataset["name"] for dataset in storage["datasets"]} or os.path.lexists(destination):
                raise Error("Der neue Wiederherstellungsbereich existiert bereits.", 409)
            with directory_fd(mountpoint):
                self.run(["zfs", "clone", "-o", "mountpoint=" + str(destination), item["name"], target])
            return {"ok": True, "dataset": target, "path": str(destination),
                    "message": "Wiederherstellung in einem neuen Speicherbereich abgeschlossen. Die aktuellen Daten bleiben erhalten."}

    def _execute(self, job, now):
        job = self.validate(job)
        if job["type"] == "smart":
            return self.smart_test(job["target"], job["test"])
        if job["type"] == "scrub":
            self.run(["zpool", "scrub", job["target"]])
            return {"ok": True, "message": "ZFS-Datenprüfung gestartet."}
        prefix = "titan-auto-" + job["id"][2:] + "-"
        stamp = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = job["target"] + "@" + prefix + stamp + "-" + secrets.token_hex(3)
        self.run(["zfs", "snapshot", "-o", "titan:maintenance=" + job["id"], name])
        # Never destroy manual snapshots or those belonging to another job.
        owned = [item for item in self.snapshots() if item["dataset"] == job["target"] and
                 item.get("schedule_id") == job["id"] and item["name"].split("@", 1)[1].startswith(prefix)]
        owned.sort(key=lambda item: (item["name"] == name, item["created"], item["name"]), reverse=True)
        retained, blocked = [], []
        for item in owned[job["retention"]:]:
            try:
                self.run(["zfs", "destroy", item["name"]])
            except Error:
                blocked.append(item["name"])
            else:
                retained.append(item["name"])
        return {"ok": True, "snapshot": name, "removed": retained, "retention_blocked": blocked}

    def scheduled(self, now=None):
        with self.lock:
            now = time.time() if now is None else now
            date = datetime.datetime.fromtimestamp(now)
            state = self.host.load("storage-maintenance-state", {"runs": {}})
            results = []
            for job in self.settings()["jobs"]:
                if (not job["enabled"] or date.hour < job["window_hour"] or
                        job["interval"] == "weekly" and date.weekday() != job["window_day"] or
                        state["runs"].get(job["id"], {}).get("day") == date.strftime("%Y-%m-%d")):
                    continue
                # Mark before commands: reboot/error never starts a retry storm.
                run = {"day": date.strftime("%Y-%m-%d"), "time": now, "ok": False}
                state["runs"][job["id"]] = run
                self.host.save("storage-maintenance-state", state)
                try:
                    result = self._execute(job, now)
                    run.update(ok=True, result=result)
                except Exception as exc:
                    run["error"] = str(exc)[:1000]
                self.host.save("storage-maintenance-state", state)
                monitor = getattr(self.host, "monitor", None)
                if monitor:
                    key = "maintenance:" + job["id"]
                    if run["ok"] and run.get("result", {}).get("retention_blocked"):
                        monitor.report(key, "ZFS-Aufbewahrung benötigt eine Prüfung",
                                       "Diese Wiederherstellungspunkte werden weiterhin benötigt und wurden nicht gelöscht: " +
                                       ", ".join(run["result"]["retention_blocked"]), "warning")
                    elif run["ok"]:
                        monitor.clear(key)
                    else:
                        monitor.report(key, "Speicherwartung fehlgeschlagen", run["error"])
                results.append({"id": job["id"], **run})
            return {"runs": results}

    def status(self):
        return {**self.settings(), **self.host.load("storage-maintenance-state", {"runs": {}})}

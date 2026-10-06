"""New storage/backup/notification UI operations for the isolated demo only.

Never invokes smartctl/zfs/SMTP or resolves simulated host mount paths. File
restoration uses the demo's private backup tree and its existing safe copier.
"""
import copy
import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace

from .backups import archive_name, directory_fd
from .core import Error, identifier, integer
from .files import operate
from .notification_delivery import NotificationDelivery
from .storage_maintenance import StorageMaintenance

OPERATIONS = {"storage_maintenance", "storage_maintenance_save", "storage_maintenance_remove",
              "storage_maintenance_scheduled", "smart_test", "snapshot_restore", "snapshot_remove",
              "backup_browse", "backup_restore_selection", "notification_settings",
              "notification_save_settings", "notification_test"}


class DemoStorageMixin:
    def _storage_helpers(self):
        with self._account_lock:
            if not hasattr(self, "_demo_storage_settings"):
                self._demo_storage_settings = {}
                self._demo_storage_lock = threading.RLock()
                adapter = SimpleNamespace(share_root=self._private, monitor=None,
                                         op_storage=lambda: self.call("storage"))
                adapter.load = lambda key, default: copy.deepcopy(self._demo_storage_settings.get(key, default))
                adapter.save = lambda key, value: self._demo_storage_settings.update({key: copy.deepcopy(value)})
                self._demo_maintenance = StorageMaintenance(adapter, lambda *args, **kwargs: '{}')
                self._demo_notifications = NotificationDelivery(adapter)
            return self._demo_maintenance, self._demo_notifications

    def op_storage_maintenance(self):
        return self._storage_helpers()[0].status()

    def op_storage_maintenance_save(self, **job):
        return self._storage_helpers()[0].save_job(**job)

    def op_storage_maintenance_remove(self, id):
        return self._storage_helpers()[0].remove_job(id)

    def op_storage_maintenance_scheduled(self):
        return {"runs": [], "message": "Demo: Wartungszeitpläne werden nur angezeigt."}

    def op_smart_test(self, disk, test="short"):
        result = self._storage_helpers()[0].smart_test(disk, test)
        return {**result, "message": "Demo: SMART-Selbsttest simuliert. Kein echtes Laufwerk wird angesprochen."}

    def op_snapshot_remove(self, snapshot, confirmed=False):
        if confirmed is not True:
            raise Error("Löschen zuerst bestätigen.")
        item = next((item for item in self.snapshots if item["name"] == snapshot), None)
        if item is None:
            raise Error("Wiederherstellungspunkt nicht gefunden.", 404)
        if any(dataset.get("origin") == snapshot for dataset in self.datasets):
            raise Error("Der Punkt wird von einem wiederhergestellten Speicherbereich benötigt.", 409)
        self.snapshots.remove(item)
        return {"ok": True, "message": "Demo: Wiederherstellungspunkt entfernt."}

    def op_snapshot_restore(self, snapshot, name):
        name = identifier(name)
        item = next((item for item in self.snapshots if item["name"] == snapshot), None)
        if item is None:
            raise Error("Wiederherstellungspunkt nicht gefunden.", 404)
        original = snapshot.split('@', 1)[0]
        parent = next((item for item in self.datasets if item["name"] == original), None)
        if parent is None:
            raise Error("Quellspeicherbereich fehlt.", 404)
        target = original + '/' + name
        if any(item["name"] == target for item in self.datasets):
            raise Error("Speicherbereich existiert bereits.", 409)
        self.datasets.append({**copy.deepcopy(parent), "name": target, "origin": snapshot,
                              "mountpoint": parent["mountpoint"] + '/' + name})
        return {"ok": True, "dataset": target, "path": parent["mountpoint"] + '/' + name,
                "message": "Demo: Gesicherter Stand als zusätzlicher Speicherbereich angezeigt. Kein Host-ZFS wird verändert."}

    def op_backup_browse(self, backup, path="", offset=0, limit=200):
        self.verify_backup(backup)
        record = self.backup(backup)
        if record["type"] != "shares":
            raise Error("Die Dateiansicht ist für Freigabensicherungen verfügbar.")
        offset, limit = integer(offset, 0, 1000000), integer(limit, 1, 500)
        parts = archive_name(path) if path else ()
        if parts and parts[0] not in record["shares"]:
            raise Error("Sicherungsordner nicht gefunden.", 404)
        root = self._private / "backups" / backup
        selected = root.joinpath(*parts)
        with directory_fd(selected) as fd:
            items = []
            for name in os.listdir(fd):
                if not parts and name not in record["shares"]:
                    continue
                archive_name(name)
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                directory = os.path.isdir(selected / name)
                items.append({"name": name, "path": '/'.join((*parts, name)),
                              "type": "directory" if directory else "file", "size": None if directory else info.st_size,
                              "modified": info.st_mtime})
        items.sort(key=lambda item: (item["type"] != "directory", item["name"].casefold()))
        return {"backup": backup, "path": path, "items": items[offset:offset + limit], "total": len(items),
                "offset": offset, "limit": limit, "created": record["created"], "verified": True, "demo": True}

    def op_backup_restore_selection(self, backup, paths, share, name):
        self.verify_backup(backup)
        record = self.backup(backup)
        if (not isinstance(paths, list) or not 1 <= len(paths) <= 1000 or any(not isinstance(p, str) for p in paths)
                or len(set(paths)) != len(paths) or record["type"] != "shares"):
            raise Error("Ungültige Dateiauswahl.")
        parts = [archive_name(path) for path in paths]
        if any(item[0] not in record["shares"] for item in parts):
            raise Error("Nur gesicherte Freigabedaten können wiederhergestellt werden.")
        root = self._private / "backups" / backup
        for selection in parts:
            with directory_fd(root.joinpath(*selection[:-1])) as fd:
                try:
                    os.stat(selection[-1], dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    raise Error("Ausgewählte Datei fehlt.", 404) from None
        self.share(share)
        name = identifier(name)
        target = self._share_paths[share]
        operate(str(target), "mkdir", name)
        copied = []
        for selection in sorted(parts, key=len):
            if any(selection[:len(previous)] == previous for previous in copied):
                continue
            for length in range(1, len(selection)):
                folder = '/'.join((name, *selection[:length]))
                try:
                    operate(str(target), "mkdir", folder)
                except FileExistsError:
                    pass
            source = '/'.join(selection)
            operate(str(root), "copy", source, destination=name + '/' + source, destination_root=str(target))
            copied.append(selection)
        return {"ok": True, "path": name, "selected": paths,
                "message": "Demo-Dateiauswahl im separaten Demo-Ordner wiederhergestellt. Keine Hostdaten verändert."}

    def op_notification_settings(self):
        return self._storage_helpers()[1].settings()

    def op_notification_save_settings(self, **settings):
        return self._storage_helpers()[1].save_settings(**settings)

    def op_notification_test(self):
        settings = self.op_notification_settings()
        if not (settings["host"] and settings["sender"] and settings["recipients"]):
            raise Error("Zuerst SMTP-Server, Absender und Empfänger speichern.")
        return {"ok": True, "message": "Demo: E-Mail-Test simuliert. Es wird keine Verbindung zu einem SMTP-Server aufgebaut."}


def demo_io_metrics(now=None):
    """Labelled sample rates for screenshots; never reads host /proc."""
    now = time.time() if now is None else now
    history = [{"time": now - (23-index)*5, "cpu_percent": 12 + (index % 7)*2,
                "memory_percent": 40.625, "memory_occupied_percent": 40.625, "cpu_temperature": 42.0,
                "network_receive_bps": (3 + index % 5) * 1024**2,
                "network_transmit_bps": (1 + index % 4) * 1024**2,
                "disk_read_bps": (12 + index % 6) * 1024**2,
                "disk_write_bps": (7 + index % 3) * 1024**2} for index in range(24)]
    recent = history[-1]
    return {"status_history": history,
            "network_interfaces": [{"name": "demo0", "receive_bps": recent["network_receive_bps"], "transmit_bps": recent["network_transmit_bps"]}],
            "disk_devices": [{"name": "demo-sda", "read_bps": recent["disk_read_bps"], "write_bps": recent["disk_write_bps"]}],
            **{key: recent[key] for key in ("network_receive_bps", "network_transmit_bps", "disk_read_bps", "disk_write_bps")}}

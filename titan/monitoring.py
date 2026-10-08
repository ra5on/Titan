"""Read-only hardware/service monitoring and persistent local UI notifications."""
from .platforms import current as host_platform
import hashlib
import datetime
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time

from .core import Error


PRIORITIES = {"info": 0, "warning": 1, "error": 2, "critical": 3}


SERVICES = {"web": ("titan-web.service", "python3"), "agent": ("titan-agent.service", "python3"),
            "https": ("titan-proxy.service", "caddy"), "samba": ("smb.service", "smbd"),
            "docker": ("docker.service", "docker"), "vms": ("virtqemud.socket", "virsh"),
            "zfs": ("zfs.target", "zpool")}


def self_test_failure(data):
    """Use explicit latest ATA/NVMe results, never old failures or text guesses.

    smartmontools marks aborted/running ATA tests as unknown; NVMe result
    codes 5, 6 and 7 report actual test errors. A user-aborted test is not a
    failing disk. See the upstream ataprint.cpp/nvmeprint.cpp JSON writers.
    """
    status = data.get("ata_smart_data", {}).get("self_test", {}).get("status", {})
    if type(status.get("passed")) is bool:
        return str(status.get("string", "ATA-Selbsttest fehlgeschlagen"))[:200] if status["passed"] is False else None
    logs = data.get("ata_smart_self_test_log", {})
    for kind in ("extended", "standard"):
        table = logs.get(kind, {}).get("table", [])
        if table and isinstance(table[0], dict):
            status = table[0].get("status", {})
            value = status.get("value")
            if type(value) is int and value >> 4 == 15:
                return None
            if type(status.get("passed")) is bool:
                return str(status.get("string", "ATA-Selbsttest fehlgeschlagen"))[:200] if status["passed"] is False else None
    table = data.get("nvme_self_test_log", {}).get("table", [])
    latest = next((item for item in table if isinstance(item, dict)), None)
    if latest:
        result = latest.get("self_test_result", {})
        if type(result.get("value")) is int and result["value"] in (5, 6, 7):
            return str(result.get("string", "NVMe-Selbsttest fehlgeschlagen"))[:200]
    return None


class Monitor:
    def __init__(self, host, run, interval=300):
        self.host, self.run, self.interval = host, run, interval
        self.lock = threading.RLock()

    def _state(self):
        state = self.host.load("monitoring", {"checked": 0, "alerts": []})
        for alert in state["alerts"]:
            alert.setdefault("route", self.route(alert.get("key", "")))
            alert.setdefault("episode", 1)
        return state

    @staticmethod
    def route(key):
        prefix, _, detail = str(key).partition(":")
        if prefix == "service":
            return {"docker": "apps", "vms": "vms", "samba": "shares", "zfs": "storage",
                    "https": "settings?section=network"}.get(detail, "services")
        return {"space": "storage", "smart": "storage", "temperature": "resources", "disks": "storage",
                "pool": "storage", "volume": "storage", "maintenance": "storage", "backup": "backups",
                "update": "updates", "app": "apps", "vm": "vms"}.get(prefix, "monitoring")

    def _deliver(self, state):
        from .notification_delivery import NotificationDelivery
        if not hasattr(self, "_delivery"):
            self._delivery = NotificationDelivery(self.host)
        try:
            state["delivery"] = self._delivery.deliver(state["alerts"])
        except (Error, OSError, ValueError, TypeError):
            state["delivery"] = {"error": "E-Mail-Benachrichtigungen konnten nicht geprüft werden."}
        return state

    def _alert(self, state, key, title, detail, severity="error"):
        alert_id = hashlib.sha256(key.encode()).hexdigest()[:24]
        alert = next((item for item in state["alerts"] if item["id"] == alert_id), None)
        if alert is None:
            alert = {"id": alert_id, "key": key, "first_seen": time.time(), "active": False}
            state["alerts"].append(alert)
        if not alert["active"]:
            alert["acknowledged"] = False
            alert["episode"] = alert.get("episode", 0) + 1
            alert.pop("resolved_at", None)
        elif PRIORITIES.get(severity, 0) > PRIORITIES.get(alert.get("severity"), 0):
            # Acknowledging a warning must not hide a later critical failure.
            alert["acknowledged"] = False
        alert.update({"active": True, "severity": severity, "title": title, "detail": str(detail)[:2000], "last_seen": time.time(), "route": self.route(key)})
        state["alerts"] = sorted(state["alerts"], key=lambda item: item["last_seen"], reverse=True)[:200]

    def report(self, key, title, message, severity="error"):
        with self.lock:
            if severity not in ("warning", "error", "info", "critical"):
                raise Error("Ungültige Meldungsstufe.")
            state = self._state()
            self._alert(state, key, title, message, severity)
            self._deliver(state)
            self.host.save("monitoring", state)

    def clear(self, key):
        with self.lock:
            state = self._state()
            for alert in state["alerts"]:
                if alert["key"] == key and alert["active"]:
                    alert["active"] = False
                    alert["resolved_at"] = time.time()
            self.host.save("monitoring", state)

    def acknowledge(self, id):
        with self.lock:
            state = self._state()
            alert = next((item for item in state["alerts"] if item["id"] == id), None)
            if alert is None:
                raise Error("Meldung nicht gefunden.", 404)
            alert["acknowledged"] = True
            self.host.save("monitoring", state)
            return {"ok": True}

    def get(self):
        with self.lock:
            return self._state()

    def _service(self, unit, executable):
        installed = bool(shutil.which(executable))
        if not installed:
            return {"installed": False, "active": False, "state": "not-installed"}
        try:
            output = self.run(["systemctl", "show", unit, "--property=LoadState,ActiveState,SubState", "--no-pager"])
            properties = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
            if properties.get("LoadState") == "not-found":
                return {"installed": True, "active": False, "state": "not-found", "error": "Programm ist installiert, aber die zugehörige systemd-Unit fehlt."}
            return {"installed": True, "active": properties.get("ActiveState") == "active",
                    "state": properties.get("ActiveState", "unknown"), "substate": properties.get("SubState", "unknown")}
        except (Error, OSError) as exc:
            return {"installed": True, "active": False, "state": "unknown", "error": str(exc)[:300]}

    def _pools(self):
        if not shutil.which("zpool"):
            return [], None
        try:
            pools = []
            for line in self.run(["zpool", "list", "-H", "-p", "-o", "name,health,size,alloc"]).splitlines():
                name, health, size, used = line.split("\t")
                pools.append({"name": name, "health": health, "size": int(size), "used": int(used)})
            return pools, None
        except (Error, OSError, ValueError) as exc:
            return [], str(exc)[:300]

    def _services(self, pools, pool_error):
        # Configuration keeps a broken component visible even when its binary
        # was removed. Merely installing ZFS does not mean a pool is in use.
        configured = {"web": True, "agent": True, "https": True}
        configuration_errors = {}
        for name, record in (("docker", "apps"), ("samba", "shares")):
            try:
                configured[name] = bool(self.host.load(record, []))
            except (Error, OSError, ValueError, TypeError) as exc:
                configured[name] = True
                configuration_errors[name] = str(exc)[:300]
        try:
            configured["vms"] = any(self.host.directory.glob("vm-*.xml"))
        except OSError as exc:
            configured["vms"] = True
            configuration_errors["vms"] = str(exc)[:300]
        services = {}
        definitions = dict(SERVICES)
        profile = host_platform()
        definitions["samba"] = (profile.samba_unit, "smbd")
        definitions["vms"] = (profile.vm_unit, "virsh")
        for name, definition in definitions.items():
            if name == "zfs":
                installed = bool(shutil.which("zpool"))
                previous = self._state()
                known_pools = bool(previous.get("known_pools", previous.get("pools"))) if pool_error or not installed else False
                in_use = bool(pools) or known_pools
                healthy = bool(pools) and all(pool["health"] == "ONLINE" for pool in pools)
                service = {"installed": installed, "configured": in_use,
                           "relevant": in_use or bool(pool_error), "active": healthy,
                           "state": "active" if healthy else "unknown" if pool_error else "degraded" if pools else "not-installed" if not installed else "unused"}
                if pool_error:
                    service["error"] = pool_error
                elif in_use and not installed:
                    service["error"] = "Für die eingerichteten ZFS-Pools fehlen die ZFS-Werkzeuge."
                elif pools and not healthy:
                    service["error"] = "; ".join(pool["name"] + ": " + pool["health"] for pool in pools if pool["health"] != "ONLINE")
            else:
                service = self._service(*definition)
                service["configured"] = configured.get(name, False)
                service["relevant"] = service["installed"] or service["configured"]
                if name in configuration_errors:
                    service["error"] = "Konfiguration konnte nicht gelesen werden: " + configuration_errors[name]
            services[name] = service
        return services

    def service_status(self):
        return self._services(*self._pools())

    def _smart(self, disk):
        if not shutil.which("smartctl"):
            return {"name": disk, "health": "unavailable", "temperature": None, "error": "smartmontools ist nicht installiert."}
        try:
            # smartctl exit codes are a bitmask: a health warning is useful output,
            # not a generic process failure. Never request a destructive SMART test.
            result = subprocess.run(["smartctl", "-a", "-l", "selftest", "-j", disk], text=True, capture_output=True, timeout=30,
                                    env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C.UTF-8"})
            data = json.loads(result.stdout)
            health = data.get("smart_status", {}).get("passed")
            temperature = data.get("temperature", {}).get("current")
            if temperature is None:
                temperature = data.get("nvme_smart_health_information_log", {}).get("temperature")
            if not isinstance(temperature, (int, float)) or not -40 <= temperature <= 200:
                temperature = None
            value = {"name": disk, "health": "passed" if health is True else "failed" if health is False else "unknown", "temperature": temperature}
            failure = self_test_failure(data)
            if failure:
                value["self_test_error"] = failure
            if result.returncode & 7:
                value["error"] = "; ".join(item.get("string", "SMART-Abfrage fehlgeschlagen") for item in data.get("smartctl", {}).get("messages", []))[:500] or "SMART wird von diesem Laufwerk nicht unterstützt oder ist nicht erreichbar."
            return value
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            return {"name": disk, "health": "unknown", "temperature": None, "error": "SMART-Abfrage fehlgeschlagen: " + type(exc).__name__}

    def check(self, force=False):
        with self.lock:
            state = self._state()
            if not force and time.time() - state.get("checked", 0) < self.interval:
                return state
            current = set()
            def warn(key, title, detail, severity="error"):
                current.add(key)
                self._alert(state, key, title, detail, severity)
            if "known_pools" not in state:
                state["known_pools"] = [pool["name"] for pool in state.get("pools", [])]
            pools, pool_error = self._pools()
            state["services"] = self._services(pools, pool_error)
            for name, service in state["services"].items():
                if service["relevant"] and not service["active"]:
                    warn("service:" + name, "Dienst ist nicht aktiv: " + name, service.get("error", service["state"]))
            telemetry = getattr(self.host, "telemetry", None)
            hardware = telemetry.sample() if telemetry is not None else {}
            state["temperatures"] = hardware.get("temperatures", [])
            state["telemetry_sampled_at"] = hardware.get("telemetry_sampled_at")
            for sensor in state["temperatures"]:
                critical = sensor.get("critical")
                # Warn against the hardware driver's own critical threshold.
                # A universal guessed CPU temperature would be misleading on
                # different processors and sensors without that information.
                if isinstance(critical, (int, float)) and critical > 10 and sensor["current"] >= critical - 10:
                    warn("temperature:sensor:" + sensor["id"], "Temperaturgrenze erreicht: " + sensor["label"],
                         f"{sensor['current']} °C; kritische Sensorgrenze {critical} °C.",
                         "error" if sensor["current"] >= critical else "warning")
            state["storage"] = []
            paths = {"system": Path("/"), "shares": self.host.share_root}
            target = self.host.load("backup-settings", {}).get("target")
            if target:
                try:
                    from .backups import Backups
                    paths["backup"] = Backups(self.host, self.run).validate_target(target)
                except (Error, OSError, ValueError, TypeError):
                    warn("backup:target", "Externes Backupziel ist nicht sicher erreichbar",
                         "Das konfigurierte Ziel ist nicht eingehängt oder liegt auf der Systemplatte. " + str(target))
            for label, path in paths.items():
                try:
                    usage = shutil.disk_usage(path)
                    ratio = usage.used / usage.total if usage.total else 1
                    state["storage"].append({"name": label, "path": str(path), "total": usage.total, "used": usage.used, "free": usage.free, "percent": round(ratio * 100, 1)})
                    if ratio >= 0.9:
                        warn("space:" + label, "Wenig freier Speicher: " + label,
                             f"{ratio * 100:.1f}% belegt; {usage.free // 1024 ** 2} MiB frei.", "error" if ratio >= 0.97 else "warning")
                except OSError:
                    warn("space:" + label, "Speicherziel nicht erreichbar: " + label, str(path))
            state["volumes"] = []
            try:
                state["volumes"] = self.host.volume_manager.inventory()["volumes"]
                for volume in state["volumes"]:
                    name = volume["name"]
                    if not volume.get("mounted"):
                        warn("volume:" + name, "Datenvolume ist nicht eingehängt: " + name,
                             volume.get("error") or "Freigaben und Apps auf diesem Volume sind gesperrt.")
                        continue
                    ratio = volume["used"] / volume["total"] if volume["total"] else 1
                    state["storage"].append({"name": "volume:" + name, "path": volume["mountpoint"],
                                             "total": volume["total"], "used": volume["used"],
                                             "free": volume["free"], "percent": round(ratio * 100, 1)})
                    if ratio >= 0.9:
                        warn("space:volume:" + name, "Wenig freier Speicher: " + name,
                             f"{ratio * 100:.1f}% belegt; {volume['free'] // 1024 ** 2} MiB frei.",
                             "error" if ratio >= 0.97 else "warning")
            except (Error, OSError, ValueError, KeyError, TypeError) as exc:
                warn("volume:check", "Datenvolumes konnten nicht geprüft werden", str(exc))
            try:
                disks = self.host.disks()
                state["disks"] = [self._smart(item["name"]) for item in disks if item.get("type") == "disk"]
                for disk in state["disks"]:
                    if disk["health"] == "failed":
                        warn("smart:" + disk["name"], "Laufwerk meldet SMART-Fehler", disk["name"])
                    if disk.get("self_test_error"):
                        warn("smart:self-test:" + disk["name"], "Laufwerks-Selbsttest meldet einen Fehler",
                             disk["name"] + ": " + disk["self_test_error"] + ". Daten sichern und Laufwerk prüfen.")
                    if disk.get("temperature") is not None and disk["temperature"] >= 55:
                        warn("temperature:" + disk["name"], "Laufwerk ist zu warm", f"{disk['name']}: {disk['temperature']} °C", "warning")
            except (Error, OSError, ValueError) as exc:
                state["disks"] = []
                warn("disks:check", "Laufwerksprüfung fehlgeschlagen", str(exc))
            state["pools"] = pools
            if shutil.which("zpool") and pool_error is None:
                state["known_pools"] = [pool["name"] for pool in pools]
            for pool in pools:
                if pool["health"] != "ONLINE":
                    warn("pool:" + pool["name"], "ZFS-Pool ist nicht gesund", pool["name"] + ": " + pool["health"])
            if pool_error:
                warn("pool:check", "ZFS-Prüfung fehlgeschlagen", pool_error)
            backup = self.host.load("backup-state", {}).get("last", {})
            if backup.get("ok") is False:
                warn("backup:last", "Letztes Backup fehlgeschlagen", backup.get("error", "Unbekannter Backupfehler."))
            from .backup_freshness import overdue
            from .backups import DEFAULTS
            backup_settings = {**DEFAULTS, **self.host.load("backup-settings", {})}
            running = getattr(getattr(self.host, "_backups", None), "running", False) is True
            missed = overdue(self.host, backup_settings, running=running)
            if missed:
                scheduled = datetime.datetime.fromtimestamp(missed["scheduled"]).strftime("%d.%m.%Y %H:%M")
                last = (datetime.datetime.fromtimestamp(missed["last_success"]).strftime("%d.%m.%Y %H:%M")
                        if missed["last_success"] is not None else "noch keine passende erfolgreiche Sicherung")
                warn("backup:overdue", "Geplante Sicherung fehlt oder ist veraltet",
                     "Seit dem geplanten Termin am " + scheduled + " wurde der ausgewählte Inhalt nicht vollständig erfolgreich gesichert. "
                     "Zwei Stunden Kulanz sind abgelaufen. Letzter passender Erfolg: " + last + ". Backupziel und Zeitplan prüfen.", "warning")
            restored = self.host.load("config-restore-result", {})
            if restored.get("ok") is False:
                warn("backup:config-restore", "Konfigurationswiederherstellung fehlgeschlagen",
                     restored.get("error", "Dienst- und Freigabestatus prüfen."))
            for alert in state["alerts"]:
                # Explicit reports are managed with report()/clear(); checks own
                # only the known source namespaces.
                if alert["key"].split(":", 1)[0] in ("service", "space", "smart", "temperature", "disks", "pool", "volume", "backup") and alert["key"] not in current:
                    if alert["active"]:
                        alert["resolved_at"] = time.time()
                    alert["active"] = False
            state["checked"] = time.time()
            self._deliver(state)
            self.host.save("monitoring", state)
            return state

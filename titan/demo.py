"""Explicitly isolated in-memory demo. No host changes and no privileged RPC."""
import base64
import copy
import hashlib
import json
import re
import shlex
import shutil
import tempfile
from pathlib import Path
import threading
import time
import uuid
from .core import Error, identifier, integer
from .catalog import APPS, published_ports, validate_options
from .cpu_topology import demo_topology
from .files import operate
from .system_files import operate_system, SYSTEM_SHARE, ALLOWED
from .demo_terminal import FakeTerminalManager
from .service_manager import CUSTOM_PREFIX, SERVICE_ACTIONS, ServiceManagerMixin, service_name, _text, _scalar
from . import __version__, __release_stage__


class Demo:
    def __init__(self, directory):
        self.directory = directory
        self.pools = [{"name": "tank", "size": 8 * 1024**4, "used": 2.34 * 1024**4,
                       "free": 5.66 * 1024**4, "health": "ONLINE"}]
        self.datasets = [{"name": "tank/dokumente", "used": 18 * 1024**3, "available": 1024**4, "mountpoint": "/var/srv/titan/tank/dokumente"}]
        self.accounts = [{"name": "patrick", "uid": 1001, "enabled": True}, {"name": "familie", "uid": 1002, "enabled": True}]
        self.shares = [{"name": "dokumente", "path": "/var/srv/titan/tank/dokumente", "readers": ["familie"], "writers": ["patrick", "titan-files"]}]
        self.apps = [{"id": "jellyfin", "name": "Jellyfin", "port": 8096, "scheme": "http", "state": "running", "status": "Up 4 days"},
                     {"id": "syncthing", "name": "Syncthing", "port": 8384, "scheme": "http", "state": "running", "status": "Up 4 days"}]
        self._app_settings = {}
        self._app_networks = {"bridge": {"Id": "d" * 64, "Name": "bridge", "Driver": "bridge", "Internal": False,
            "IPAM": {"Config": [{"Subnet": "172.17.0.0/16", "Gateway": "172.17.0.1"}]}, "Containers": {}}}
        self._system_state = None
        self._system_disk_state = None
        self.vms = [{"id": str(uuid.uuid4()), "name": "linux-lab", "state": "running", "cpus": 2, "memory_mb": 4096, "autostart": True, "iso": None, "boot": "hd", "disk_path": "/var/lib/libvirt/images/titan/linux-lab.qcow2", "disk_gb": 32, "virtual_size": 32 * 1024**3, "storage": "system", "cpu_ids": []}]
        self.isos = [{"name": "linux-netinst.iso", "size": 650 * 1024**2}]
        self.iso_uploads = {}
        self.terminals = FakeTerminalManager()
        self._service_lock = threading.RLock()
        self.services = {}
        for name, description, active, enabled, user in (
                ("titan-web.service", "Titan Weboberfläche", True, True, "titan"),
                ("titan-agent.service", "Titan Verwaltungsdienst", True, True, "root"),
                ("titan-proxy.service", "Titan HTTPS-Zugang", True, True, "titan-proxy"),
                ("docker.service", "Docker Container Engine", True, True, "root"),
                ("smb.service", "Samba Dateifreigaben", True, True, "root"),
                ("virtqemud.service", "libvirt VM-Verwaltung", True, True, "root"),
                ("ssh.service", "OpenSSH Server", False, False, "root"),
                ("cron.service", "Zeitgesteuerte Aufgaben", False, True, "root")):
            self.services[name] = {"description": "Demo · " + description, "active": active,
                                   "enabled": enabled, "user": user, "working_directory": "",
                                   "logs": ["[Demo] Dienst wird ausschließlich simuliert."]}
        self.volume_records = []
        self.demo_disks = [{"name": "/dev/sda", "size": 4 * 1024**4, "model": "NAS HDD", "type": "disk", "fstype": "zfs_member", "ro": False, "mountpoints": []},
                           {"name": "/dev/sdb", "size": 4 * 1024**4, "model": "NAS HDD", "type": "disk", "fstype": "zfs_member", "ro": False, "mountpoints": []},
                           {"name": "/dev/sdc", "size": 4 * 1024**4, "model": "NAS HDD", "type": "disk", "fstype": None, "ro": False, "mountpoints": []}]
        self.snapshots = []
        self._temporary = tempfile.TemporaryDirectory(prefix="titan-demo-")
        self._private = Path(self._temporary.name)
        self._share_paths = {"dokumente": directory}
        self._system_path = self._private / "system"
        for name in ("etc", "home/demo", "srv", "tmp", "var/media/demo-backup/Archiv", "var/media/demo-backup/Computer"):
            (self._system_path / name).mkdir(parents=True, exist_ok=True)
        (self._system_path / "etc/hostname").write_text("titan-demo\n")
        (self._system_path / "home/demo/Notizen.txt").write_text("Isolierte Systemdatei der Titan-Demo.\n")
        self.backup_settings = {"target": "", "auto_backup": False, "interval": "daily", "window_day": 6,
                                "window_hour": 3, "retention": 7, "shares": ["dokumente"], "include_config": True}
        self.backup_records = []
        self.last_backup = None
        self.alerts = [{"id": "demo-backup", "severity": "warning", "level": "warning",
                        "title": "Beispiel: Sicherungsziel fehlt", "detail": "Richte ein externes Sicherungsziel ein.",
                        "active": True, "acknowledged": False, "first_seen": time.time(), "last_seen": time.time()}]
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "Dokumente").mkdir(exist_ok=True)
        (self.directory / "Willkommen.txt").write_text("Willkommen bei Titan!\nDies ist eine isolierte Demo.\nDateien in dieser Vorschau liegen nur im Demo-Verzeichnis.\n")

    @staticmethod
    def demo_cpu_ids(cpus, cpu_ids):
        if cpu_ids is None:
            return []
        if (not isinstance(cpu_ids, list) or any(not isinstance(item, int) or isinstance(item, bool) for item in cpu_ids) or
                len(cpu_ids) != len(set(cpu_ids)) or any(item < 0 or item >= 8 for item in cpu_ids) or
                (cpu_ids and len(cpu_ids) < cpus)):
            raise Error("Ungültige Host-CPU-Auswahl.")
        return sorted(cpu_ids)

    @staticmethod
    def demo_host_addresses():
        return [{"address": "192.168.1.50", "family": 4, "interface": "demo0", "scope": "lan"},
                {"address": "127.0.0.1", "family": 4, "interface": "lo", "scope": "loopback"}]

    def demo_app_networks(self):
        from .app_networks import selection
        networks = []
        for name, item in self._app_networks.items():
            used = [app for app in self.apps if selection(app.get("network")).get("name", "bridge" if selection(app.get("network"))["mode"] == "bridge" else "") == name]
            networks.append({"id": item["Id"], "name": name, "driver": "bridge", "internal": item["Internal"],
                "managed": name != "bridge", "selectable": True, "static_ipv4": name != "bridge",
                "subnets": [{"subnet": subnet["Subnet"], "gateway": subnet["Gateway"], "family": 4} for subnet in item["IPAM"]["Config"]],
                "containers": [{"name": "titan-" + app["id"], "ipv4": self.demo_app_container(app)["networks"][0]["ipv4"], "ipv6": ""} for app in used if app["state"] == "running"],
                "used_by": [app["id"] for app in used]})
        return {"available": self.services["docker.service"]["active"], "networks": networks,
                "host_addresses": self.demo_host_addresses(), "public_ip": None,
                "warnings": ["Demo: Netzwerkbetrieb wird ausschließlich simuliert."]}

    def demo_app_container(self, item):
        from .app_networks import AppNetworkMixin, selection
        import ipaddress
        network = selection(item.get("network"))
        mode = network["mode"]
        name = network.get("name", "bridge") if mode == "bridge" else "titan-" + item["id"] + "_default"
        if mode == "host": name = "host"
        info = self._app_networks.get(name, {"Driver": "bridge", "Internal": False,
                "IPAM": {"Config": [{"Subnet": "172.20.0.0/16", "Gateway": "172.20.0.1"}]}})
        subnet = info["IPAM"]["Config"][0]
        address = network.get("ipv4_address", str(ipaddress.IPv4Network(subnet["Subnet"]).network_address + 10 + next((index for index, app in enumerate(self.apps) if app["id"] == item["id"]), 0))) if mode != "host" else ""
        publications = published_ports(item["id"], item["port"], self._app_settings.get(item["id"]), host_mode=mode == "host")
        ports = [{"host": "0.0.0.0", "port": port["host"], "target": port["target"], "protocol": port["protocol"]} for port in publications] if mode != "host" else []
        raw = {"State": {"Status": item["state"]}, "HostConfig": {"NetworkMode": name}, "NetworkSettings": {"Networks": {name: {
            "IPAddress": address if item["state"] == "running" else "", "Gateway": subnet["Gateway"] if mode != "host" else ""}},
            "Ports": {f"{port['target']}/{port['protocol']}": [{"HostIp": "0.0.0.0", "HostPort": str(port["port"])}] for port in ports}}}
        return {"id": "demo-container-" + item["id"], "name": "titan-" + item["id"], "image": APPS[item["id"]]["image"],
                "state": item["state"], "health": "", "restarts": 0, "exit_code": 0, "ports": ports,
                **AppNetworkMixin._app_address_summary(self, raw, item, {name: info}, self.demo_host_addresses())}

    def call(self, operation, **args):
        if operation.startswith("terminal_"):
            method = {"terminal_create": self.terminals.create, "terminal_poll": self.terminals.poll,
                      "terminal_write": self.terminals.write, "terminal_resize": self.terminals.resize,
                      "terminal_close": self.terminals.close}.get(operation)
            if method is None:
                raise Error("Unbekannte Demo-Terminalaktion.")
            values = dict(args)
            if "id" in values:
                values["session_id"] = values.pop("id")
            return method(**values)
        if operation == "services":
            if args:
                raise Error("Ungültige Dienstlistenparameter.")
            with self._service_lock:
                items = [self.service_summary(name) for name in sorted(self.services, key=lambda name: (not self.services[name].get("failed"), not name.startswith(CUSTOM_PREFIX), name.casefold()))]
                counts = {"total": len(items), "active": sum(item["active"] == "active" for item in items),
                          "failed": sum(item["active"] == "failed" for item in items),
                          "enabled": sum(item["enabled"] for item in items), "custom": sum(item["custom"] for item in items)}
                return {"items": items, "users": self.service_users(), "total": len(items),
                        "truncated": False, "custom_prefix": CUSTOM_PREFIX, "counts": counts}
        if operation == "service_details":
            return self.service_details(**args)
        if operation == "service_action":
            return self.service_action(**args)
        if operation == "service_create":
            return self.service_create(**args)
        if operation == "system_file":
            action = args["action"]
            extra = {key: value for key, value in args.items() if key not in ("action", "path")}
            if action not in ALLOWED or set(extra) - ALLOWED[action]:
                raise Error("Ungültige Systemdateiaktion oder zusätzliche Parameter.")
            target_system = False
            if action in ("copy", "move"):
                target = extra.pop("destination_share", None) or SYSTEM_SHARE
                target_system = target == SYSTEM_SHARE
                if not target_system:
                    self.share(target)
                    extra["destination_root"] = str(self._share_paths[target])
            return operate_system(str(self._system_path), action, args.get("path", ""),
                                  system_path_root=str(self._system_path), destination_system=target_system, **extra)
        admin_file = operation == "admin_file"
        if admin_file:
            operation = "file"
            args["user"] = "titan-files"
        if operation == "app_stores":
            return {"stores": []}
        if operation in ("app_store_add", "app_store_remove"):
            raise Error("Eigene Stores benötigen ein installiertes Titan-System. Die Demo lädt keine fremden Vorlagen.")
        if operation == "vm_usb":
            return {"devices": [], "selected": [], "editable": True}
        if operation == "vm_usb_update":
            if args.get("devices"):
                raise Error("In der Demo sind keine echten USB-Geräte verfügbar.")
            return {"ok": True, "devices": []}
        if operation == "components":
            docker, vms = self.services["docker.service"]["active"], self.services["virtqemud.service"]["active"]
            return {"components": {"docker": {"installed": True, "available": docker, "daemon": docker, "compose": True, "missing": [],
                                               **({"error": "Demo: Docker-Dienst ist gestoppt."} if not docker else {})},
                                    "vms": {"installed": True, "available": vms, "daemon": vms, "kvm": True, "missing": [],
                                            **({"error": "Demo: libvirt-Dienst ist gestoppt."} if not vms else {})}}, "repair": {}}
        if operation == "component_install":
            if args.get("component", "all") not in ("all", "docker", "vms"):
                raise Error("Ungültige Komponente.")
            if args.get("component", "all") in ("all", "docker"):
                self.services["docker.service"]["active"] = True
            if args.get("component", "all") in ("all", "vms"):
                self.services["virtqemud.service"]["active"] = True
            return {"ok": True, "message": "Demo: Komponentenreparatur simuliert.", "status": self.call("components")["components"], "warnings": [], "output": "Keine Hostpakete oder Dienste verändert."}
        if operation == "vm_options":
            storage = [{"id": "system", "label": "Systemlaufwerk", "path": "/var/lib/libvirt/images/titan",
                        "available": True, "free_bytes": 110 * 1024**3}]
            for volume in self.volume_records:
                storage.append({"id": "volume:" + volume["name"], "label": volume["name"] + " (" + volume["filesystem"].upper() + ")",
                                "path": "/var/srv/titan/volumes/" + volume["name"] + "/vms",
                                "available": volume.get("mounted", True), "free_bytes": volume.get("total", 1024**4) - volume.get("used", 0)})
            return {"storage": storage, "disk_images": [{"id": "share:dokumente:Images/linux-cloud.qcow2",
                    "name": "linux-cloud.qcow2", "path": "/var/srv/titan/tank/dokumente/Images/linux-cloud.qcow2",
                    "format": "qcow2", "size": 500 * 1024**2, "virtual_size": 8 * 1024**3, "storage": "share:dokumente"}],
                    "cpu_topology": demo_topology(), "isos": self.call("isos"), "warnings": []}
        if operation == "status":
            mounted = [volume for volume in self.volume_records if volume["mounted"]]
            storage = ({key: sum(volume[key] for volume in mounted) for key in ("total", "used")}
                       if mounted else {"total": 8 * 1024**4, "used": 2.34 * 1024**4})
            return {"hostname": "titan", "uptime": 352845, "load": 0.32, "cpus": 8,
                    "memory_total": 32 * 1024**3, "memory_used": 8.6 * 1024**3,
                    "memory_available": 23.4 * 1024**3, "memory_cached": 4.1 * 1024**3,
                    "swap_total": 0, "swap_used": 0, "cpu_percent": 22.0,
                    "cpu_temperature": 42.0, "temperature_available": True,
                    "telemetry_sampled_at": time.time(), "telemetry_errors": {},
                    "temperatures": [{"id": "demo:cpu", "label": "Demo · CPU", "kind": "cpu", "current": 42.0, "critical": 100.0}],
                    "status_history": [{"time": time.time()-(23-index)*5, "cpu_percent": 12+(index%7)*2,
                                        "memory_percent": 26.875, "cpu_temperature": 42.0} for index in range(24)],
                    "services": {**{name: self.services[unit]["active"] for name, unit in
                                    (("docker", "docker.service"), ("samba", "smb.service"), ("vms", "virtqemud.service"))}, "zfs": True},
                    "service_details": {name: {"installed": True, "active": active, "state": "active" if active else "inactive"}
                                        for name, active in (("docker", self.services["docker.service"]["active"]),
                                                             ("samba", self.services["smb.service"]["active"]),
                                                             ("vms", self.services["virtqemud.service"]["active"]), ("zfs", True))},
                    "storage": storage}
        if operation == "storage_locations":
            return {"items": [{"path": "/home/demo", "label": "Demo-Dateien", "kind": "data", "backup_eligible": False},
                              {"path": "/var/media/demo-backup", "label": "Demo · externes Sicherungslaufwerk", "kind": "mount", "backup_eligible": True},
                              {"path": "/", "label": "Demo-Systemverzeichnis", "kind": "system", "backup_eligible": False}],
                    "programs": [{"path": "/usr/bin/python3", "label": "Python 3"}, {"path": "/usr/bin/bash", "label": "Bash"}], "warnings": []}
        if operation == "storage":
            return {"pools": copy.deepcopy(self.pools), "datasets": copy.deepcopy(self.datasets),
                    "disks": copy.deepcopy(self.demo_disks), "volumes": copy.deepcopy(self.volume_records),
                    "filesystems": {"ext4": {"available": True}, "xfs": {"available": True}},
                    "existing_filesystems": [{key: item.get(key) for key in ("name", "type", "fstype", "uuid", "size", "mountpoints")} for item in self.demo_disks if item.get("fstype") in ("ext4", "xfs")],
                    "status": "pool: tank\nstate: ONLINE\nscan: scrub repaired 0B with 0 errors\nerrors: No known data errors"}
        if operation == "system_disk":
            return copy.deepcopy(self.system_disk())
        if operation == "system_disk_grow":
            from .server import validate_system_disk_growth
            validate_system_disk_growth(args)
            state = self.system_disk()
            if args["expected_revision"] != state["revision"]:
                raise Error("Demo: Systemdisk-Stand geändert. Ansicht aktualisieren.", 409)
            before = copy.deepcopy(state)
            changed = state["growable_bytes"] > 0
            state["partition_size"] += state["partition_growable_bytes"]
            state["filesystem_size"] = state["partition_size"]
            state["filesystem_available"] = state["filesystem_size"] - state["filesystem_used"]
            state.update(partition_growable_bytes=0, filesystem_growable_bytes=0, growable_bytes=0)
            state["revision"] = hashlib.sha256(str(state["partition_size"]).encode()).hexdigest()
            return {"ok": True, "changed": changed, "partition_grown": changed, "filesystem_grown": changed,
                    "before": before, "after": copy.deepcopy(state), "simulation": True,
                    "message": "Demo: Kapazität nur simuliert; kein Hostlaufwerk verändert."}
        if operation == "shares": return copy.deepcopy(self.shares)
        if operation == "accounts":
            accounts = copy.deepcopy(self.accounts)
            if args.get("smb_status"):
                for account in accounts:
                    enabled = account.get("enabled", True) and not account.get("removed")
                    account.update(smb_configured=not account.get("removed", False), smb_enabled=enabled, smb_ready=enabled)
            return accounts
        if operation == "shares_access":
            return {"host_addresses": self.demo_host_addresses(), "service_active": self.services["smb.service"]["active"],
                    "port": 445, "firewall": [{"interface": "demo0", "zone": "public", "samba_service_enabled": True, "port_445_enabled": False, "target": "default"}],
                    "warnings": ["Demo: SMB-Zugang wird ausschließlich simuliert."]}
        if operation == "app_networks":
            return self.demo_app_networks()
        if operation == "apps":
            installed = copy.deepcopy(self.apps)
            available = self.services["docker.service"]["active"]
            if not available:
                for item in installed:
                    item.update(state="unavailable", status="[Demo] Docker-Dienst ist gestoppt.")
            else:
                for item in installed:
                    item["container"] = self.demo_app_container(item)
            return {"installed": installed, "available": available, "error": "" if available else "[Demo] Docker-Dienst ist gestoppt."}
        if operation == "vms": return {"vms": copy.deepcopy(self.vms), "available": True}
        if operation == "snapshots": return copy.deepcopy(self.snapshots)
        if operation == "isos": return [item["name"] for item in self.isos]
        if operation == "iso_library":
            return {"items": [{**item, "used_by": [vm["name"] for vm in self.vms if vm.get("iso") == item["name"]]} for item in self.isos]}
        if operation == "app_details":
            app = next((item for item in self.apps if item["id"] == args["app"]), None)
            if app is None: raise Error("App nicht gefunden.", 404)
            item = copy.deepcopy(app)
            return {"app": item, "container": self.demo_app_container(item),
                    "logs": "[Demo] Dienst bereit.\n[Demo] Keine Fehler.", "warnings": ["Demo: Containerbetrieb wird ausschließlich simuliert."],
                    "config_path": "/var/lib/titan-agent/apps/" + item["id"] + "/config", "data_path": item.get("data", "/var/srv/titan/apps/" + item["id"])}
        if operation == "file":
            allowed = {"list": {"offset", "limit", "search"}, "read": {"offset", "size"}, "mkdir": set(),
                       "write": {"data", "revision"}, "create": {"data"}, "delete": {"confirmation_path"},
                       "upload": {"offset", "data"}, "rename": {"destination"}, "trash": set(), "trash_list": {"offset", "limit", "search"},
                       "restore": {"trash_name", "destination"}, "copy": {"destination", "destination_share"},
                       "move": {"destination", "destination_share"}}
            action = args["action"]
            extras = {k: v for k, v in args.items() if k not in ("share", "user", "action", "path")}
            if action not in allowed or set(extras) - allowed[action]:
                raise Error("Ungültige Dateiaktion oder zusätzliche Parameter.")
            if action == "delete" and not admin_file:
                raise Error("Diese Dateiaktion erfordert Administratorrechte.", 403)
            user = args.get("user", "titan-files")
            if user != "titan-files" and not any(item["name"] == user and item.get("enabled", True) for item in self.accounts):
                raise Error("Benutzer ist gesperrt oder nicht vorhanden.", 403)
            share = self.share(args["share"])
            if action == "delete" and extras.pop("confirmation_path", None) != share["name"] + "/" + args.get("path", ""):
                raise Error("Zum Löschen muss der vollständige angezeigte Pfad bestätigt werden.")
            if not admin_file and user not in share["readers"] + share["writers"]:
                raise Error("Kein Zugriff auf diese Freigabe.", 403)
            if not admin_file and action not in ("list", "read", "copy", "trash_list") and user not in share["writers"]:
                raise Error("Die Freigabe ist schreibgeschützt.", 403)
            if action in ("copy", "move"):
                target_name = extras.pop("destination_share", None) or share["name"]
                if target_name == SYSTEM_SHARE and admin_file:
                    from .system_files import canonical_relative, virtual, PROTECTED
                    destination = canonical_relative(self._system_path, extras["destination"], parent_only=True)
                    if virtual(destination) or destination in PROTECTED:
                        raise Error("Dieses Systemziel kann nicht ersetzt werden.", 403)
                    extras["destination"] = destination
                    extras["destination_root"] = str(self._system_path)
                else:
                    target = self.share(target_name)
                    if not admin_file and user not in target["writers"]:
                        raise Error("Keine Schreibrechte auf der Zielfreigabe.", 403)
                    extras["destination_root"] = str(self._share_paths[target["name"]])
            return operate(str(self._share_paths[share["name"]]), action, args.get("path", ""), **extras)
        if operation == "backup_settings": return copy.deepcopy(self.backup_settings)
        if operation in ("backup_settings_save", "backup_save_settings"):
            value = args.get("settings", args.get("value", args))
            return self.save_backup_settings(value)
        if operation == "backups":
            return {"items": copy.deepcopy(self.backup_records), "backups": copy.deepcopy(self.backup_records),
                    "target": self.backup_settings["target"], "settings": copy.deepcopy(self.backup_settings), "last": self.last_backup}
        if operation == "backup_create": return self.create_backup(**args)
        if operation == "backup_verify": return self.verify_backup(args["backup"])
        if operation == "backup_restore": return self.restore_backup(**args)
        if operation == "backup_config_export":
            record = self.backup(args["backup"])
            if not record.get("include_config"): raise Error("Diese Sicherung enthält keine Konfiguration.")
            return {"ok": True, "message": "Demo: Konfiguration separat exportiert. Die laufende Konfiguration wurde nicht geändert.",
                    "path": str(self._private / "exports" / record["id"])}
        if operation == "backup_config_restore":
            record = self.backup(args["backup"])
            if args.get("confirmation") != record["id"]: raise Error("Die Bestätigung stimmt nicht überein.")
            if not record.get("include_config"): raise Error("Diese Sicherung enthält keine Konfiguration.")
            return {"ok": True, "message": "Demo: Konfigurationswiederherstellung simuliert. Echte Einstellungen bleiben erhalten."}
        if operation == "backup_scheduled": return {"ok": True, "message": "Demo: Zeitpläne werden nur angezeigt."}
        if operation in ("monitoring", "monitoring_check"):
            now = time.time()
            for alert in self.alerts:
                if alert["id"] == "demo-backup": alert["active"] = not bool(self.backup_settings["target"])
            return {"checked": now, "services": self.call("status")["service_details"], "disks": [{"name": "/dev/sda", "health": "PASSED", "temperature": 34},
                    {"name": "/dev/sdb", "health": "PASSED", "temperature": 36}], "pools": copy.deepcopy(self.pools),
                    "storage": self.call("status")["storage"], "alerts": copy.deepcopy(self.alerts),
                    "message": "Demo: Zustandsprüfung simuliert."}
        if operation == "monitoring_ack":
            item = next((item for item in self.alerts if item["id"] == args["id"]), None)
            if not item: raise Error("Meldung nicht gefunden.", 404)
            item["acknowledged"] = True
            return {"ok": True}
        if operation == "vm_image_details":
            path = args.get("path", "")
            if not isinstance(path, str) or not path.startswith("/") or not path.lower().endswith((".qcow2", ".raw", ".img")):
                raise Error("Ein absoluter QCOW2-/RAW-/IMG-Dateipfad ist erforderlich.")
            return {"id": path, "name": Path(path).name, "path": path,
                    "format": "qcow2" if path.lower().endswith(".qcow2") else "raw",
                    "size": 500 * 1024**2, "virtual_size": 8 * 1024**3,
                    "min_disk_gb": 8, "storage": "system", "source_retained": True}
        if operation == "update_check":
            return self.update_check(args["repository"], args.get("channel", "stable"))
        if operation == "update_install": raise Error("Installation ist im Demo-Modus deaktiviert.")
        if operation == "system_updates": return copy.deepcopy(self.system_updates())
        if operation in ("update_rollback", "system_reboot"):
            from .updates import validate_system_action
            validate_system_action(operation, {key: value for key, value in args.items() if key != "repository"})
            state = self.system_updates()
            if state["reboot_scheduled"]:
                raise Error("Demo: Ein Neustart ist bereits simuliert.", 409)
            if operation == "update_rollback":
                if not state["rollback_available"] or state["rollback"]["digest"] != args["expected_digest"]:
                    raise Error("Demo: Vorherige Bereitstellung geändert oder Aktion bereits vorbereitet.", 409)
                state.update(rollback_queued=True, reboot_required=True, rollback_available=False,
                             next_boot=copy.deepcopy(state["rollback"]), rollback_reason="Demo: Rollback ist bereits vorbereitet.")
                return {"ok": True, "simulation": True, "rollback_queued": True, "reboot_required": True,
                        "automatic_reboot": False, "rollback": copy.deepcopy(state["rollback"]),
                        "message": "Demo: Rollback nur im Arbeitsspeicher vorbereitet; das Hostsystem wird nicht verändert."}
            if state["next_boot"]["digest"] != args["expected_digest"]:
                raise Error("Demo: Das Image für den nächsten Start hat sich geändert.", 409)
            active = [vm["name"] for vm in self.vms if vm["state"] not in ("shut off", "shutoff", "stopped")]
            if active:
                raise Error("Neustart gesperrt. Diese virtuellen Maschinen zuerst geordnet herunterfahren: " + ", ".join(active), 409)
            state.update(reboot_scheduled=True, reboot_schedule={"at": time.time() + 60, "mode": "reboot"}, rollback_available=False)
            return {"ok": True, "simulation": True, "reboot_scheduled": True,
                    "reboot_schedule": copy.deepcopy(state["reboot_schedule"]), "next_boot": copy.deepcopy(state["next_boot"]),
                    "delay_seconds": 60, "automatic_reboot": False,
                    "message": "Demo: Neustart ausschließlich simuliert. Kein Hostdienst oder Hostsystem wird neu gestartet."}
        if operation == "console": raise Error("Die Demo besitzt keine echte VM-Konsole.")
        if operation == "volume_create":
            name = identifier(args["name"])
            filesystem = args.get("filesystem", "ext4")
            disk = next((item for item in self.demo_disks if item["name"] == args["disk"]), None)
            if args.get("confirmation_name") != name or args.get("confirmation_disk") != args["disk"] or filesystem not in ("ext4", "xfs"):
                raise Error("Dateisystem oder Bestätigung ist ungültig.")
            if any(item["name"] == name for item in self.volume_records): raise Error("Volume existiert bereits.", 409)
            if not disk or disk.get("fstype") or disk.get("children") or any(disk.get("mountpoints") or []) or disk.get("ro"):
                raise Error("Nur ein vollständig leeres unpartitioniertes Laufwerk ist zulässig.")
            volume = {"name": name, "disk": disk["name"], "filesystem": filesystem, "uuid": str(uuid.uuid4()),
                      "mountpoint": "/var/srv/titan/volumes/" + name, "mounted": True, "state": "Eingehängt", "phase": "ready",
                      "total": disk["size"], "used": 0, "free": disk["size"]}
            self.volume_records.append(volume)
            disk.update(fstype=filesystem, uuid=volume["uuid"], mountpoints=[volume["mountpoint"]])
            return {"ok": True, "message": "Demo: " + filesystem.upper() + "-Volume isoliert simuliert; kein Laufwerk wurde formatiert."}
        if operation == "volume_mount":
            volume = next((item for item in self.volume_records if item["name"] == args["name"]), None)
            if not volume: raise Error("Volume nicht gefunden.", 404)
            volume.update(mounted=True, state="Eingehängt")
            return {"ok": True, "message": "Demo: Bekanntes Volume wieder eingehängt."}
        if operation == "pool_create":
            if args["confirmation"] != args["name"]: raise Error("Poolname stimmt nicht.")
            self.pools.append({"name": identifier(args["name"]), "size": 4 * 1024**4, "used": 0, "free": 4 * 1024**4, "health": "ONLINE"})
        elif operation == "dataset_create":
            self.datasets.append({"name": args["parent"] + "/" + identifier(args["name"]), "used": 0, "available": 1024**4, "mountpoint": "/var/srv/titan/demo"})
        elif operation == "snapshot_create":
            self.snapshots.append({"name": args["dataset"] + "@" + identifier(args["name"]), "used": 0, "created": time.time()})
        elif operation == "account_create":
            name = identifier(args["name"])
            if name == "titan-files" or any(item["name"] == name for item in self.accounts): raise Error("Benutzer existiert bereits.", 409)
            self.accounts.append({"name": name, "uid": 1003 + len(self.accounts), "enabled": True})
        elif operation in ("account_update", "account_password", "account_status"):
            item = next((item for item in self.accounts if item["name"] == args["name"]), None)
            if not item: raise Error("Benutzer nicht gefunden.", 404)
            if item.get("removed"): raise Error("Dieser Benutzer wurde gelöscht.", 403)
            if "enabled" in args:
                if not isinstance(args["enabled"], bool): raise Error("Ungültiger Kontostatus.")
                item["enabled"] = args["enabled"]
        elif operation == "account_remove":
            item = next((item for item in self.accounts if item["name"] == args["name"]), None)
            if not item or item["name"] == "titan-files": raise Error("Nur verwaltete Benutzerkonten dürfen gelöscht werden.", 403)
            item.update(enabled=False, removed=True)
            for share in self.shares:
                share["readers"] = [name for name in share["readers"] if name != item["name"]]
                share["writers"] = [name for name in share["writers"] if name != item["name"]]
            return {"ok": True, "data_retained": True, "linux_account_retained": True}
        elif operation == "share_create":
            name = identifier(args["name"])
            if any(item["name"] == name for item in self.shares): raise Error("Freigabe existiert bereits.", 409)
            self.validate_rights(args["readers"], args["writers"])
            volume = args.get("volume")
            if volume and args.get("dataset"): raise Error("Entweder Volume oder Dataset wählen.")
            if volume and not any(item["name"] == volume and item["mounted"] for item in self.volume_records):
                raise Error("Volume ist nicht eingehängt.", 503)
            directory = self._private / "volumes" / volume / "shares" / name if volume else self._private / "shares" / name
            directory.mkdir(parents=True, exist_ok=True)
            self._share_paths[name] = directory
            self.shares.append({"name": name, "path": "/var/srv/titan/volumes/" + volume + "/shares/" + name if volume else "/var/srv/titan/demo/" + name, "readers": args["readers"], "writers": args["writers"], "volume": volume})
        elif operation == "share_update":
            item = self.share(args["name"])
            self.validate_rights(args["readers"], args["writers"], previous=item)
            item["readers"], item["writers"] = args["readers"], args["writers"]
        elif operation == "share_remove":
            self.shares.remove(self.share(args["name"]))
        elif operation == "app_install":
            from .app_networks import selection
            if set(args) - {"app", "port", "share", "options", "network"}: raise Error("Ungültige App-Installationsparameter.")
            network = selection(args.get("network"))
            app, port = args["app"], integer(args["port"], 1 if network["mode"] == "host" else 1024, 65535)
            options = validate_options(app, args.get("options"))
            if not self.services["docker.service"]["active"]: raise Error("[Demo] Docker-Dienst ist gestoppt.", 503)
            if any(item["id"] == app for item in self.apps): raise Error("App ist bereits installiert.", 409)
            requested = {item["host"] for item in published_ports(app, port, options, host_mode=network["mode"] == "host")}
            reserved = {5000, 5001}
            for item in self.apps:
                reserved.update(publication["host"] for publication in published_ports(item["id"], item["port"], self._app_settings.get(item["id"]), host_mode=selection(item.get("network"))["mode"] == "host"))
            if requested & reserved: raise Error("Port ist bereits für Titan oder eine andere App reserviert.", 409)
            if network["mode"] == "bridge":
                name = network.get("name", "bridge")
                if name not in self._app_networks:
                    raise Error("Demo-Netzwerk existiert nicht.", 404)
                if network.get("ipv4_address"):
                    import ipaddress
                    address = ipaddress.IPv4Address(network["ipv4_address"])
                    subnet = self._app_networks[name]["IPAM"]["Config"][0]
                    parsed = ipaddress.IPv4Network(subnet["Subnet"])
                    if name == "bridge" or address not in parsed or address in (parsed.network_address, parsed.broadcast_address) or str(address) == subnet["Gateway"]:
                        raise Error("Feste IPv4-Adresse muss eine freie Hostadresse des gewählten Subnetzes sein.")
                    if any(selection(item.get("network")).get("name") == name and selection(item.get("network")).get("ipv4_address") == str(address) for item in self.apps):
                        raise Error("Feste IPv4-Adresse ist für eine andere Demo-App reserviert.", 409)
            data = "/var/srv/titan/apps/" + app
            if args.get("share"):
                selected = self.share(args["share"])
                if selected.get("blocked") or "titan-files" not in selected["writers"]:
                    raise Error("Die App benötigt eine aktive Freigabe mit Schreibrechten für titan-files.")
                data = selected["path"]
            self._app_settings[app] = options
            self.apps.append({"id": app, "name": APPS[app]["name"], "port": port, "state": "running", "status": "Up",
                              "scheme": APPS[app].get("scheme", "http"), "data": data, "phase": "ready", "last_error": "", "network": network})
        elif operation == "app_network_create":
            from .app_networks import validate_create
            import ipaddress
            value = validate_create(**args)
            if value["name"] in self._app_networks: raise Error("Dieses Demo-Netzwerk existiert bereits.", 409)
            for item in self._app_networks.values():
                if any(ipaddress.IPv4Network(value["subnet"]).overlaps(ipaddress.IPv4Network(subnet["Subnet"])) for subnet in item["IPAM"]["Config"]):
                    raise Error("Subnetz überschneidet sich mit einem Demo-Netzwerk.", 409)
            self._app_networks[value["name"]] = {"Id": uuid.uuid4().hex * 2, "Name": value["name"], "Driver": "bridge", "Internal": value["internal"],
                "IPAM": {"Config": [{"Subnet": value["subnet"], "Gateway": value["gateway"]}]}, "Containers": {},
                "Labels": {"io.titan.managed": "true", "io.titan.network": value["name"]}}
            return {"ok": True, "network": next(item for item in self.demo_app_networks()["networks"] if item["name"] == value["name"])}
        elif operation == "app_network_remove":
            if set(args) != {"name", "confirmation"}: raise Error("Ungültige Netzwerk-Löschparameter.")
            name = args["name"]
            if args.get("confirmation") != name: raise Error("Zum Entfernen den Netzwerknamen bestätigen.")
            item = next((item for item in self.demo_app_networks()["networks"] if item["name"] == name), None)
            if not item or not item["managed"]: raise Error("Nur eigene Demo-Netzwerke können entfernt werden.", 403)
            if item["used_by"]: raise Error("Demo-Netzwerk wird noch von einer App benutzt.", 409)
            del self._app_networks[name]
            return {"ok": True, "name": name}
        elif operation == "app_action":
            if args["action"] not in ("start", "stop", "restart", "logs", "remove", "update", "backup"):
                raise Error("Ungültige App-Aktion.")
            item = next((item for item in self.apps if item["id"] == args["app"]), None)
            if item is None: raise Error("App ist nicht installiert.", 404)
            if args["action"] == "remove": self.apps.remove(item)
            elif args["action"] == "stop": item["state"] = "exited"
            elif args["action"] in ("start", "restart"): item["state"] = "running"
            elif args["action"] == "logs": return {"output": "[Demo] Dienst bereit.\n[Demo] Keine Fehler."}
            elif args["action"] in ("update", "backup"):
                return {"ok": True, "demo": True, "kept_stopped": item["state"] != "running",
                        "output": "[Demo] App-" + args["action"] + " simuliert; keine Container oder Sicherungsdateien verändert."}
            item["status"] = "Up" if item["state"] == "running" else "Gestoppt"
        elif operation == "vm_create":
            name = identifier(args["name"])
            options = self.call("vm_options")
            iso, image_id = args.get("iso"), args.get("disk_image")
            if iso and iso not in self.call("isos"): raise Error("ISO nicht gefunden.")
            image = next((item for item in options["disk_images"] if item["id"] == image_id), None)
            if image_id and image is None: raise Error("Laufwerksimage nicht gefunden.")
            if not iso and not image: raise Error("ISO oder Laufwerksimage auswählen.")
            choice = next((item for item in options["storage"] if item["id"] == args.get("storage", "system")), None)
            if choice is None or not choice["available"]: raise Error("VM-Speicher ist nicht verfügbar.", 409)
            disk_gb = integer(args["disk_gb"], 8, 10000)
            if image and disk_gb * 1024**3 < image["virtual_size"]: raise Error("Neue Disk darf nicht kleiner als das Image sein.")
            cpus = integer(args["cpus"], 1, 8)
            pins = self.demo_cpu_ids(cpus, args.get("cpu_ids"))
            if any(item["name"] == name for item in self.vms): raise Error("VM existiert bereits.", 409)
            self.vms.append({"id": str(uuid.uuid4()), "name": name, "state": "shut off", "cpus": cpus,
                             "memory_mb": integer(args["memory_mb"], 512, 31744), "autostart": False,
                             "iso": iso, "boot": "cdrom" if iso else "hd", "cpu_ids": pins,
                             "storage": choice["id"], "disk_path": choice["path"] + "/" + name + ".qcow2",
                             "disk_gb": disk_gb, "virtual_size": disk_gb * 1024**3})
        elif operation == "vm_media":
            item = self.vm(args["vm"])
            if item["state"] != "shut off": raise Error("VM muss vollständig heruntergefahren sein.", 409)
            if args.get("iso") and args["iso"] not in self.call("isos"): raise Error("ISO nicht gefunden.")
            item["iso"], item["boot"] = args.get("iso"), "cdrom" if args.get("iso") else "hd"
        elif operation == "vm_action":
            item = self.vm(args["vm"])
            if args["action"] in ("autostart", "disable-autostart"): item["autostart"] = args["action"] == "autostart"
            elif args["action"] in ("start", "reboot", "shutdown", "stop", "poweroff", "resume"): item["state"] = "running" if args["action"] in ("start", "reboot", "resume") else "shut off"
            else: raise Error("Unbekannte VM-Aktion.")
        elif operation in ("vm_update", "vm_remove", "vm_backup"):
            item = self.vm(args["vm"])
            if item["state"] != "shut off": raise Error("VM muss vollständig heruntergefahren sein.", 409)
            if operation == "vm_update":
                cpus = integer(args["cpus"], 1, 8)
                pins = self.demo_cpu_ids(cpus, args.get("cpu_ids", item.get("cpu_ids")))
                item["cpus"], item["cpu_ids"] = cpus, pins
                item["memory_mb"] = integer(args["memory_mb"], 512, 31744)
            elif operation == "vm_remove": self.vms.remove(item)
            else:
                target = args.get("target") or self.backup_settings["target"]
                self.demo_target(target)
                self.backup_settings["target"] = target
                record = {"id": "b-demo-" + uuid.uuid4().hex[:12], "type": "vm", "created": time.time(), "bytes": 1024**3,
                          "vm_name": item["name"], "name": item["name"], "vm": copy.deepcopy(item), "shares": [], "include_config": False}
                self.backup_records.insert(0, record)
                return {"ok": True, "message": "Demo: VM gesichert.", "backup": copy.deepcopy(record)}
        elif operation == "vm_restore":
            record = self.backup(args["backup"])
            name = identifier(args["name"])
            if record["type"] != "vm": raise Error("Diese Sicherung enthält keine VM.")
            if any(item["name"] == name for item in self.vms): raise Error("VM existiert bereits.", 409)
            self.vms.append({**record["vm"], "id": str(uuid.uuid4()), "name": name, "state": "shut off", "autostart": False,
                             "storage": "system", "disk_path": "/var/lib/libvirt/images/titan/" + name + ".qcow2", "cpu_ids": []})
        elif operation == "iso_upload":
            name, total, offset = args["name"], integer(args["total"], 1, 64 * 1024**3), integer(args["offset"], 0, 64 * 1024**3)
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.iso", name): raise Error("Ungültiger ISO-Dateiname.")
            if name in self.call("isos"): raise Error("ISO existiert bereits.", 409)
            size = len(base64.b64decode(args["data"], validate=True))
            if not size or size > 1024**2 or offset + size > total: raise Error("Ungültiger Upload-Block.")
            token = args.get("upload_id")
            if token is None:
                if offset: raise Error("Upload-Kennung fehlt.")
                token = uuid.uuid4().hex
                self.iso_uploads[token] = {"name": name, "total": total, "offset": 0}
            upload = self.iso_uploads.get(token)
            if not upload or upload != {"name": name, "total": total, "offset": offset}: raise Error("Upload stimmt nicht überein.", 409)
            upload["offset"] += size
            complete = upload["offset"] == total
            if complete:
                self.isos.append({"name": name, "size": total})
                del self.iso_uploads[token]
            return {"offset": offset + size, "upload_id": token, "complete": complete}
        elif operation == "iso_cancel": self.iso_uploads.pop(args["upload_id"], None)
        elif operation == "iso_remove":
            if any(vm.get("iso") == args["name"] for vm in self.vms): raise Error("ISO wird von einer VM verwendet.", 409)
            item = next((item for item in self.isos if item["name"] == args["name"]), None)
            if item is None: raise Error("ISO nicht gefunden.", 404)
            self.isos.remove(item)
        elif operation == "smart": return {"smart_status": {"passed": True}, "temperature": {"current": 34}, "message": "Demo: simulierte SMART-Werte."}
        elif operation not in ("scrub",): raise Error("Unbekannte Demo-Aktion.")
        return {"ok": True, "message": "Demo-Aktion ausgeführt."}

    def service_users(self):
        users = [{"name": "titan-files", "uid": 990, "label": "titan-files"},
                 {"name": "root", "uid": 0, "label": "root (Administrator)"},
                 {"name": "demo", "uid": 1000, "label": "demo"}]
        users += [{"name": item["name"], "uid": item["uid"], "label": item["name"]}
                  for item in self.accounts if not item.get("removed") and item.get("enabled", True)]
        return users

    def service_summary(self, service):
        name = service_name(service)
        record = self.services.get(name)
        if record is None:
            raise Error("Dienst nicht gefunden.", 404)
        installed = {name: {"state": "enabled" if record["enabled"] else "disabled", "preset": "enabled"}}
        states = {name: {"load": "loaded", "active": "active" if record["active"] else "inactive",
                         "sub": "running" if record["active"] else "dead", "description": record["description"]}}
        if record.get("failed"):
            states[name].update(active="failed", sub="failed")
        return ServiceManagerMixin._service_summary(name, installed, states,
            {"CanReload": "yes" if name in ("smb.service", "ssh.service") else "no"})

    def service_details(self, service, tail=100):
        tail = integer(tail, 0, 500)
        with self._service_lock:
            summary = self.service_summary(service)
            record = self.services[summary["name"]]
            properties = {"Id": summary["name"], "Names": summary["name"], "Description": record["description"],
                          "LoadState": "loaded", "ActiveState": summary["active"], "SubState": summary["sub"],
                          "UnitFileState": summary["unit_file_state"], "User": record["user"], "MainPID": "0",
                          "WorkingDirectory": record["working_directory"], "Result": "success", "Transient": "no",
                          "FragmentPath": "/etc/systemd/system/" + summary["name"], "NeedDaemonReload": "no"}
            return {"service": {**summary, "properties": properties,
                                "metrics": {"main_pid": 0, "restarts": 0, "memory_bytes": None, "memory_peak_bytes": None, "cpu_seconds": None, "tasks": None},
                                "relationships": {"triggered_by": [], "triggers": [], "requires": [], "wants": [], "after": []}},
                    "logs": "\n".join(record["logs"][-tail:]) if tail else "",
                    "logs_error": "", "logs_truncated": False}

    def service_action(self, service, command):
        if not isinstance(command, str) or command not in SERVICE_ACTIONS:
            raise Error("Ungültige Dienstaktion.")
        with self._service_lock:
            summary = self.service_summary(service)
            if command not in summary["allowed_actions"]:
                raise Error(summary["protected_reason"] or "Dienstaktion ist nicht erlaubt.", 403)
            record = self.services[summary["name"]]
            if command in ("start", "restart", "stop"):
                record["active"] = command != "stop"
                record["failed"] = False
            elif command == "reset-failed":
                record["failed"] = False
            elif command in ("enable", "disable"):
                record["enabled"] = command == "enable"
            record["logs"] = (record["logs"] + ["[Demo] Aktion " + command + " simuliert; kein Hostdienst verändert."])[-500:]
            return {"ok": True, "service": self.service_summary(summary["name"]), "command": command}

    def service_create(self, name, description, program, args="", user="titan-files",
                       working_directory="", autostart=False, start=False):
        name = identifier(name)
        description = _text(description, "Beschreibung", 512, False)
        program = _text(program, "Programm", 4096, False)
        args = _text(args, "Argumente", 8192)
        user = _text(user, "Benutzer", 64, False)
        working_directory = _text(working_directory, "Arbeitsverzeichnis", 4096)
        _scalar(description)
        if type(autostart) is not bool or type(start) is not bool:
            raise Error("Autostart und Start müssen boolesche Werte sein.")
        if user not in {item["name"] for item in self.service_users()}:
            raise Error("Dienstbenutzer ist nicht als ausführendes Konto verfügbar.")
        if not Path(program).is_absolute() or ".." in Path(program).parts:
            raise Error("Programm benötigt einen absoluten Pfad ohne .. .")
        if working_directory:
            _scalar(working_directory)
            if not Path(working_directory).is_absolute() or ".." in Path(working_directory).parts:
                raise Error("Arbeitsverzeichnis benötigt einen absoluten Pfad ohne .. .")
        try:
            argv = shlex.split(args, posix=True)
        except ValueError:
            raise Error("Argumente enthalten unausgeglichene Anführungszeichen.") from None
        if len(argv) > 128:
            raise Error("Höchstens 128 Programmargumente sind zulässig.")
        unit_name = CUSTOM_PREFIX + name + ".service"
        with self._service_lock:
            if unit_name in self.services:
                raise Error("Dienstname ist bereits belegt.", 409)
            self.services[unit_name] = {"description": "Demo · " + description, "active": start, "enabled": autostart,
                                        "user": user, "working_directory": working_directory,
                                        "program": program, "args": argv,
                                        "logs": ["[Demo] Dienst nur im Arbeitsspeicher angelegt. Kein Programm wurde ausgeführt."]}
            return {"ok": True, "created": True, "service": unit_name, "autostart": autostart, "start": start,
                    "message": "Demo: Dienst ausschließlich simuliert; kein Hostprogramm oder systemd verändert."}

    def share(self, name):
        item = next((item for item in self.shares if item["name"] == name), None)
        if not item: raise Error("Freigabe nicht gefunden.", 404)
        if item.get("volume") and not any(volume["name"] == item["volume"] and volume["mounted"] for volume in self.volume_records):
            raise Error("Volume ist nicht eingehängt; Dateizugriff gesperrt.", 503)
        return item

    def system_disk(self):
        if self._system_disk_state is None:
            gib = 1024 ** 3
            size, used = int(20.5 * gib), 8 * gib
            growable = int(42 * gib)
            self._system_disk_state = {"supported": True, "available": True, "reason": "", "demo": True,
                "revision": hashlib.sha256(str(size).encode()).hexdigest(), "disk": "/dev/vda",
                "partition": "/dev/vda4", "partition_number": 4, "filesystem": "xfs", "mountpoint": "/var",
                "disk_size": 64 * gib, "partition_size": size, "filesystem_size": size,
                "filesystem_used": used, "filesystem_available": size - used,
                "partition_growable_bytes": growable, "filesystem_growable_bytes": 0, "growable_bytes": growable}
        return self._system_disk_state

    def system_updates(self):
        if self._system_state is None:
            major, minor, patch = map(int, __version__.split("."))
            previous = f"{major}.{minor}.{max(0, patch - 1)}"
            repo = "ghcr.io/ra5on/titan"
            booted = {"image": repo + "@sha256:" + "a" * 64, "digest": "sha256:" + "a" * 64,
                      "version": __version__, "incompatible": False}
            rollback = {"image": repo + "@sha256:" + "b" * 64, "digest": "sha256:" + "b" * 64,
                        "version": previous, "incompatible": False}
            self._system_state = {"platform": "ucore-hci", "update_kind": "image", "current": __version__,
                "current_stage": __release_stage__, "architecture": "x86_64", "image_repository": repo,
                "booted": booted, "staged": None, "rollback": rollback, "next_boot": copy.deepcopy(booted),
                "rollback_queued": False, "reboot_required": False, "reboot_scheduled": False, "reboot_schedule": None,
                "rollback_available": True, "rollback_reason": "Demo: Vorherige Version und Rollback ausschließlich simuliert.",
                "automatic_reboot": False, "simulation": True, "output": "Demo: Systemupdates und Neustarts verändern kein Hostsystem."}
        return self._system_state

    @staticmethod
    def update_check(repository, channel):
        """A fixed simulated release set demonstrates filtering without network I/O."""
        allowed = {"stable": {"stable"}, "beta": {"stable", "beta"},
                   "alpha": {"stable", "beta", "alpha"}}
        if channel not in allowed:
            raise Error("Ungültiger Update-Kanal.")
        major, minor, patch = (int(part) for part in __version__.split("."))
        if patch:
            stable = (major, minor, patch - 1)
        elif minor:
            stable = (major, minor - 1, 0)
        else:
            stable = (max(0, major - 1), 0, 0)
        candidates = [
            {"version": "v" + ".".join(map(str, stable)), "stage": "stable", "number": stable},
            {"version": f"v{major}.{minor}.{patch + 1}-beta.1", "stage": "beta", "number": (major, minor, patch + 1)},
            {"version": f"v{major}.{minor}.{patch + 2}-alpha.1", "stage": "alpha", "number": (major, minor, patch + 2)},
        ]
        selected = max((item for item in candidates if item["stage"] in allowed[channel]),
                       key=lambda item: item["number"])
        available = selected["number"] > (major, minor, patch)
        return {"current": __version__, "current_stage": __release_stage__,
                "latest": selected["version"], "latest_stage": selected["stage"], "channel": channel,
                "available": available, "signed": False, "simulation": True, "checked": time.time(),
                "message": ("Demo: Ein passendes neueres " + selected["stage"].capitalize() + "-Release wird simuliert."
                            if available else "Demo: Im gewählten Kanal gibt es kein passendes neueres Release. Die ältere stabile Version wird nicht installiert."),
                "notes": "Simulierte Beispieldaten für die Kanalwahl. In der Demo werden weder Pakete heruntergeladen noch Updates installiert.",
                "repository": repository}

    def vm(self, vm):
        item = next((item for item in self.vms if item["id"] == vm), None)
        if not item: raise Error("VM nicht gefunden.", 404)
        return item

    def validate_rights(self, readers, writers, previous=None):
        available = {"titan-files", *[item["name"] for item in self.accounts if item.get("enabled", True) and not item.get("removed")]}
        if not isinstance(readers, list) or not isinstance(writers, list) or (not readers + writers and previous is None):
            raise Error("Wähle mindestens ein berechtigtes Konto.")
        if previous:
            known = {item["name"] for item in self.accounts if not item.get("removed")}
            available |= {name for name in readers if name in known and name in previous["readers"] + previous["writers"] and name not in writers}
            available |= {name for name in writers if name in known and name in previous["writers"]}
        if set(readers) & set(writers) or set(readers + writers) - available:
            raise Error("Zugriffsrechte sind ungültig.")

    @staticmethod
    def demo_target(value):
        if not isinstance(value, str) or not value.startswith(("/mnt/", "/media/", "/var/mnt/", "/var/media/")) or ".." in Path(value).parts:
            raise Error("Demo-Sicherungsziel muss unter /mnt oder /media liegen.")
        # Never access this supplied host path. All demo backup I/O is isolated.

    def save_backup_settings(self, value):
        allowed = set(self.backup_settings)
        if set(value) - allowed: raise Error("Unbekannte Sicherungseinstellung.")
        settings = {**self.backup_settings, **value}
        if settings["target"]: self.demo_target(settings["target"])
        if not isinstance(settings["auto_backup"], bool) or not isinstance(settings["include_config"], bool):
            raise Error("Ungültiger Schalter.")
        if settings["interval"] not in ("daily", "weekly"): raise Error("Ungültiges Intervall.")
        for key, maximum in (("window_day", 6), ("window_hour", 23), ("retention", 100)):
            settings[key] = integer(settings[key], 1 if key == "retention" else 0, maximum)
        if not isinstance(settings["shares"], list): raise Error("Ungültige Freigabeliste.")
        for name in settings["shares"]: self.share(name)
        if settings["auto_backup"] and not settings["target"]: raise Error("Für automatische Sicherungen ist ein Ziel nötig.")
        self.backup_settings = settings
        return copy.deepcopy(settings)

    def backup(self, backup):
        record = next((item for item in self.backup_records if item["id"] == backup), None)
        if not record: raise Error("Sicherung nicht gefunden.", 404)
        return record

    @staticmethod
    def tree_digest(directory):
        result = {}
        for item in directory.rglob("*"):
            if item.is_symlink(): raise Error("Symbolische Links werden nicht gesichert.")
            if item.is_file(): result[str(item.relative_to(directory))] = hashlib.sha256(item.read_bytes()).hexdigest()
        return result

    def create_backup(self, shares=None, include_config=None):
        self.demo_target(self.backup_settings["target"])
        shares = self.backup_settings["shares"] if shares is None else shares
        include_config = self.backup_settings["include_config"] if include_config is None else include_config
        if not isinstance(shares, list) or not isinstance(include_config, bool) or (not shares and not include_config):
            raise Error("Ungültiger Sicherungsinhalt.")
        record = {"id": "b-demo-" + uuid.uuid4().hex[:12], "type": "shares", "created": time.time(),
                  "shares": list(shares), "include_config": include_config, "bytes": 0}
        directory = self._private / "backups" / record["id"]
        directory.mkdir(parents=True)
        try:
            for name in shares:
                self.share(name)
                source = self._share_paths[name]
                target = directory / name
                target.mkdir()
                for entry in source.iterdir():
                    if entry.name != ".titan-trash":
                        operate(str(source), "copy", entry.name, destination=entry.name, destination_root=str(target))
            record["digests"] = self.tree_digest(directory)
            record["bytes"] = sum(item.stat().st_size for item in directory.rglob("*") if item.is_file())
            self.backup_records.insert(0, record)
            self.last_backup = {"time": time.time(), "ok": True}
            groups = [item for item in self.backup_records if item["type"] == "shares"]
            for old in groups[self.backup_settings["retention"]:]:
                shutil.rmtree(self._private / "backups" / old["id"])
                self.backup_records.remove(old)
            return {"ok": True, "message": "Demo-Dateien isoliert gesichert.", "backup": copy.deepcopy(record)}
        except Exception:
            shutil.rmtree(directory)
            self.last_backup = {"time": time.time(), "ok": False, "error": "Demo-Sicherung fehlgeschlagen."}
            raise

    def verify_backup(self, backup):
        record = self.backup(backup)
        if record["type"] == "shares" and self.tree_digest(self._private / "backups" / backup) != record["digests"]:
            raise Error("Sicherung wurde verändert; Wiederherstellung verweigert.")
        return {"ok": True, "message": "Demo: Sicherung erfolgreich geprüft."}

    def restore_backup(self, backup, share, name):
        self.verify_backup(backup)
        record = self.backup(backup)
        if record["type"] != "shares": raise Error("Diese Sicherung enthält eine VM.")
        self.share(share)
        name = identifier(name)
        target = self._share_paths[share]
        operate(str(target), "mkdir", name)
        source = self._private / "backups" / backup
        for source_share in record["shares"]:
            operate(str(source), "copy", source_share, destination=name + "/" + source_share,
                    destination_root=str(target))
        return {"ok": True, "message": "Demo: Dateien in separatem Ordner wiederhergestellt.", "path": name}

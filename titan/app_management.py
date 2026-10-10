"""Lifecycle and diagnostics for Titan' curated, persistent Docker apps."""
import json
import os
import re
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
import contextlib

from .catalog import APPS, compose, published_ports, validate_options
from .core import Error, atomic_json, integer
from .app_networks import AppNetworkMixin, selection, app_readiness


def _run(*args, **kwargs):
    # Keep host command execution central, including its timeout/error handling.
    from .host import run
    return run(*args, **kwargs)


from .app_devices import AppDevicesMixin, validate as validate_devices, devices as app_devices_inventory


from .app_metrics import AppMetricsMixin
from .package_center import PackageCenterMixin, definition_digest


class AppMixin(PackageCenterMixin, AppMetricsMixin, AppDevicesMixin, AppNetworkMixin):
    @staticmethod
    def _app_valid_port(app, port, network):
        if APPS[app].get("web_available") is False:
            return integer(port, 0, 0)
        return integer(port, 1 if network["mode"] == "host" else 1024, 65535)

    def _app_firewall(self, app, enabled=True):
        from .app_firewall import reconcile
        record = next((item for item in self.load("apps", []) if item["id"] == app), None)
        if not record:
            return reconcile(self, "app:" + app, [])
        mode = selection(record.get("network"))["mode"]
        ports = published_ports(app, record["port"], self._app_options(app), host_mode=True) if enabled and mode == "host" else []
        # Bridge/NAT access belongs to Docker. Only reconcile this owner when
        # it has a rule to add, or retained rules to withdraw.
        ledger = self.load("managed-firewall-v1", {})
        if not ports and not any("app:" + app in value.get("owners", []) for value in ledger.values()):
            return {"available": True, "managed_rules": 0, "warnings": []}
        status = reconcile(self, "app:" + app, ports)
        self._app_patch_record(app, {"firewall_warnings": status["warnings"]})
        return status

    def _app_firewall_observed(self, app):
        # Used after individual Docker actions and recovery: dependencies alone
        # must not retain the primary service's network exposure.
        containers = self._app_lifecycle_snapshot(app)
        primary = next((item for item in containers if item.get("Name") == "/titan-" + app), None)
        return self._app_firewall(app, enabled=bool(primary and self._app_container_active(primary)))

    def reconcile_app_firewall(self):
        """Boot/network-change hook; reconcile only recorded Titan app owners."""
        warnings = []
        for record in self.load("apps", [])[:128]:
            try:
                warnings.extend(self._app_firewall_observed(record["id"])["warnings"])
            except (Error, ValueError, KeyError, TypeError) as exc:
                warnings.append(str(exc))
        return warnings

    def _app_config_path(self, app, record=None):
        record = record or next((item for item in self.load("apps", []) if item["id"] == app), {})
        path = Path(record.get("config_path") or self.directory / "apps" / app / "config")
        if record.get("storage_id"):
            resource = self.storage_locations.resolve(record["storage_id"], purpose="apps", write=False)
            if record.get("storage_uuid") and record["storage_uuid"] != resource.get("uuid"):
                raise Error("Der App-Speicher wurde ausgetauscht. Paket bleibt gesperrt.", 409)
            if path != Path(resource["path"]) / app / "config":
                raise Error("Die App-Konfiguration passt nicht zum gespeicherten Speicherort.", 409)
        return path

    def _app_patch_record(self, app, updates=None, remove=False):
        """Change one record against the fresh list, never overwrite another app."""
        with self.app_config_lock:
            records = self.load("apps", [])
            if remove:
                records = [item for item in records if item["id"] != app]
            else:
                for item in records:
                    if item["id"] == app:
                        item.update(updates or {})
            self.save("apps", records)

    def _app_lifecycle_services(self, app):
        """Known service names, including a verified older installed recipe."""
        record = next((item for item in self.load("apps", []) if item["id"] == app), None)
        if record is None or app not in APPS:
            raise Error("App ist nicht installiert.", 404)
        recipe = APPS[app]
        primary = recipe.get("stack", {}).get("primary")
        keys = {app}
        keys.update(app + "-" + key.lower() for key in recipe.get("stack", {}).get("services", {}) if key != primary)
        path = self.directory / "apps" / app / "compose.json"
        if not any(value.is_symlink() for value in (self.directory, path.parent.parent, path.parent, path)) and path.is_file():
            try:
                stored = json.loads(path.read_text())
                if record.get("definition_digest") == definition_digest(stored):
                    keys.update(key for key in stored.get("services", {}) if key == app or re.fullmatch(re.escape(app) + r"-[a-z][a-z0-9_-]{0,40}", key))
            except (OSError, ValueError, TypeError):
                pass
        return record, keys

    @staticmethod
    def _app_owned_container(app, container, service_key):
        value = container.get("Id")
        labels = (container.get("Config") or {}).get("Labels") or {}
        expected = {"io.titan.managed": "true", "io.titan.app": app,
                    "com.docker.compose.project": "titan-" + app, "com.docker.compose.service": service_key}
        if (not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value) or
                container.get("Name") != "/titan-" + service_key or
                any(labels.get(key) != expected_value for key, expected_value in expected.items())):
            raise Error("Ein fremder oder ersetzter Container belegt den App-Namen. Ansicht aktualisieren.", 409)
        return container

    def _app_lifecycle_snapshot(self, app):
        _, keys = self._app_lifecycle_services(app)
        rows = self._app_container_rows()
        result = []
        for key in sorted(keys):
            matches = [row for row in rows if row.get("Names") == "titan-" + key]
            if len(matches) > 1:
                raise Error("Paketdienst konnte nicht eindeutig geprüft werden.", 409)
            if not matches:
                continue
            value = matches[0].get("ID")
            if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
                raise Error("Ungültige Container-ID.", 503)
            values = json.loads(_run(["docker", "inspect", "--type", "container", value], timeout=30))
            if len(values) != 1 or values[0].get("Id") != value:
                raise Error("Paketdienst wurde während der Abfrage ersetzt.", 409)
            result.append(self._app_owned_container(app, values[0], key))
        return result

    @staticmethod
    def _app_container_active(container):
        state = container.get("State") or {}
        return bool(state.get("Running") or state.get("Status") in ("running", "paused", "restarting"))

    def _app_unregister(self, app):
        """Forget an explicitly removed installation, retaining private app data."""
        if APPS.get(app, {}).get('umbrel_catalog'):
            record = next((item for item in self.load('apps', []) if item['id'] == app), None)
            if record is not None:
                retained = self.load('retained-app-installations-v1', {})
                retained[app] = record
                self.save('retained-app-installations-v1', retained)
        self._app_patch_record(app, remove=True)
        from .native_catalog import AVAILABLE_APP_IDS
        if app in AVAILABLE_APP_IDS:
            from .app_installation import AppInstallationMixin
            AppInstallationMixin._installation_path(self, app, private=True).unlink(missing_ok=True)

    def _app_unregister_if_empty(self, app):
        # The caller holds the same package lifecycle lock as install/start.
        # A missing dependency is not an uninstall. Failure to inspect Docker
        # must never be treated as proof that the package has disappeared.
        if self._app_lifecycle_snapshot(app):
            return False
        self._app_firewall(app, enabled=False)
        self._app_unregister(app)
        return True

    def _app_stop_or_remove(self, app, action, unregister=True):
        """Contain a degraded package by immutable owned IDs; never delete data.

        Configuration/network/health mismatches must prevent starting changed
        code, but must not prevent stopping an unambiguously owned container.
        No Compose file is executed on this recovery path.
        """
        containers = self._app_lifecycle_snapshot(app)
        output = []
        for row in containers:
            if row.get("State", {}).get("Status") == "paused":
                output.append(_run(["docker", "unpause", row["Id"]], timeout=30))
        active = [row["Id"] for row in containers if self._app_container_active(row)]
        if active:
            output.append(_run(["docker", "stop", "--time", "30", *active], timeout=180))
        stopped = self._app_lifecycle_snapshot(app)
        original_ids = {row["Id"] for row in containers}
        if any(row["Id"] not in original_ids or self._app_container_active(row) for row in stopped):
            raise Error("Paketdienste sind noch aktiv oder wurden ersetzt. Keine Daten wurden entfernt.", 409)
        self._app_firewall(app, enabled=False)
        if action == "remove":
            if stopped:
                output.append(_run(["docker", "rm", *[row["Id"] for row in stopped]], timeout=120))
            if self._app_lifecycle_snapshot(app):
                raise Error("Paket konnte noch nicht vollständig entfernt werden. Daten bleiben erhalten.", 503)
            if unregister:
                self._app_unregister(app)
            else:
                self._app_patch_record(app, {"phase": "stopped", "last_error": "", "changed": time.time()})
        else:
            self._app_patch_record(app, {"phase": "stopped", "last_error": "", "changed": time.time()})
        return {"ok": True, "scope": "package", "app": app, "action": action,
                "state": "removed" if action == "remove" else "stopped", "data_retained": True,
                "containers": sorted(original_ids), "output": "\n".join(value for value in output if value),
                "message": "Paket deinstalliert. Konfiguration, Datenbanken und Nutzdaten bleiben erhalten." if action == "remove" else "Alle vorhandenen Paketdienste sind gestoppt."}

    def _app_declared_volumes(self, container, expected_bindings, expected_tmpfs=()):
        """Accept Docker's own anonymous image volumes, never extra host binds.

        Redis/Valkey and document-server init images declare VOLUME entries even
        when Compose only specifies other binds. Match the immutable image and
        the actual local, option-free volume before accepting those entries.
        """
        mounts = container.get("Mounts", [])
        declared_tmpfs = {value.split(':', 1)[0]: value.split(':', 1)[1] if ':' in value else '' for value in expected_tmpfs}
        if declared_tmpfs:
            if (container.get('HostConfig', {}).get('Tmpfs') or {}) != declared_tmpfs:
                return False
            mounts = [mount for mount in mounts if not (mount.get('Type') == 'tmpfs' and mount.get('Destination') in declared_tmpfs)]
        if len(mounts) == len(expected_bindings):
            return True
        extras = [value for value in mounts if value.get("Destination") not in expected_bindings]
        if len(mounts) != len(expected_bindings) + len(extras) or not extras:
            return False
        image = container.get("Image")
        if not isinstance(image, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            return False
        values = json.loads(_run(["docker", "inspect", "--type", "image", image], timeout=30))
        if len(values) != 1 or values[0].get("Id") != image:
            return False
        declared = (values[0].get("Config") or {}).get("Volumes") or {}
        destinations = set()
        for mount in extras:
            destination, volume = mount.get("Destination"), mount.get("Name")
            if (mount.get("Type") != "volume" or destination not in declared or
                    destination in destinations or mount.get("Driver") != "local" or
                    not isinstance(volume, str) or not re.fullmatch(r"[a-f0-9]{64}", volume)):
                return False
            destinations.add(destination)
            volumes = json.loads(_run(["docker", "volume", "inspect", volume], timeout=30))
            if (len(volumes) != 1 or volumes[0].get("Name") != volume or
                    volumes[0].get("Driver") != "local" or volumes[0].get("Options") not in ({}, None) or
                    volumes[0].get("Mountpoint") != mount.get("Source")):
                return False
        return True
    def _app_options(self, app):
        """Secrets stay in a separate owner-only file, never in public records."""
        path = self.directory / "apps" / app / "options.json"
        if not path.exists() and not path.is_symlink():
            return validate_options(app)
        if any(part.is_symlink() for part in (self.directory, path.parent.parent, path.parent)):
            raise Error("App-Einstellungen liegen in einem unsicheren Verzeichnis.", 503)
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor) as stream:
                metadata = os.fstat(stream.fileno())
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077 or metadata.st_size > 65536:
                    raise Error("Private App-Einstellungen haben unsichere Dateirechte.", 503)
                return validate_options(app, json.loads(stream.read(65537)))
        except (OSError, ValueError, TypeError):
            raise Error("Private App-Einstellungen fehlen oder sind ungültig.", 503) from None

    def app_storage_ready(self, app, data=None):
        if app not in APPS:
            raise Error("App-Vorlage ist nicht verfügbar.")
        sources = [data] if data else []
        if not data:
            record = next((item for item in self.load("apps", []) if item["id"] == app), None)
            if record and record.get("data"):
                sources.append(record["data"])
            else:
                path = self.directory / "apps" / app / "compose.json"
                if not path.exists() or path.is_symlink():
                    raise Error("App-Konfiguration fehlt oder ist unsicher.", 503)
                service = json.loads(path.read_text())["services"][app]
                for binding in service.get("volumes", []):
                    source = binding.get("source") if isinstance(binding, dict) else binding.split(":", 1)[0]
                    if source:
                        sources.append(source)
        config = self.directory / "apps" / app / "compose.json"
        if not data and config.exists() and not config.is_symlink():
            definition=json.loads(config.read_text())
            for service in definition.get("services",{}).values():
                for binding in service.get("volumes",[]):
                    source=binding.get("source") if isinstance(binding,dict) else binding.split(":",1)[0]
                    if source and Path(source).is_relative_to(self.directory):
                        relative=Path(source).relative_to(self.directory)
                        descriptor=os.open(self.directory,os.O_DIRECTORY|os.O_NOFOLLOW)
                        try:
                            for component in relative.parts:
                                child=os.open(component,os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=descriptor)
                                os.close(descriptor);descriptor=child
                        except OSError:
                            raise Error("App-Konfigurationsverzeichnis fehlt oder enthält einen symbolischen Link.",503) from None
                        finally: os.close(descriptor)
        installed = next((item for item in self.load("apps", []) if item["id"] == app), None)
        if installed and installed.get("storage_id"):
            resource = self.storage_locations.resolve(installed["storage_id"], purpose="apps", write=False)
            if installed.get("storage_uuid") and resource.get("uuid") != installed["storage_uuid"]:
                raise Error("Der App-Speicher wurde ausgetauscht. Paket bleibt gesperrt.", 409)
            sources.append(str(self._app_config_path(app, installed)))
        for source in sources:
            if hasattr(self, "storage_locations"):
                self.storage_locations.validate_path(source, purpose="apps")
            if self.volume_manager.required_path(source) is not None or Path(source).is_relative_to(self.share_root):
                try:
                    descriptor = self.open_share_root(source)
                except OSError:
                    raise Error("App-Datenverzeichnis fehlt oder enthält einen symbolischen Link.", 503)
                os.close(descriptor)

    @staticmethod
    def _app_directory(path, base, owner=None):
        """Create owned directories without following a writable child symlink."""
        path, base = Path(path), Path(base)
        if not path.is_relative_to(base) or path == base or base.is_symlink():
            raise Error("Unsicherer App-Datenpfad.", 403)
        base.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(base, os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in path.relative_to(base).parts:
                try:
                    os.mkdir(component, 0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(component, os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            if owner is not None:
                os.fchown(descriptor, owner.pw_uid, owner.pw_gid)
        except OSError:
            raise Error("App-Verzeichnis fehlt oder enthält einen symbolischen Link.", 403)
        finally:
            os.close(descriptor)

    def managed_app(self, app):
        if app not in APPS:
            raise Error("App-Vorlage ist nicht verfügbar.")
        record = next((dict(item) for item in self.load("apps", []) if item["id"] == app), None)
        if record is None:
            raise Error("App ist nicht installiert.", 404)
        directory = self.directory / "apps" / app
        if ((directory / "restore-pending.json").exists() or (directory / "restore-pending.json").is_symlink()) and getattr(getattr(self, "_app_restore_local", None), "app", None) != app:
            raise Error("Eine App-Wiederherstellung wurde unterbrochen. App bleibt gesperrt; das gespeicherte Recovery-Verzeichnis lokal prüfen.", 503)
        path = directory / "compose.json"
        config = self._app_config_path(app, record)
        if any(item.is_symlink() for item in (self.directory, directory.parent, directory, path, directory / "config", config)) or not path.is_file() or not config.is_dir():
            raise Error("App-Konfiguration fehlt oder ist unsicher.", 503)
        try:
            definition = json.loads(path.read_text())
            service = definition["services"][app]
            from .host import pwd
            owner = pwd.getpwnam("titan-files")
            network = selection(record.get("network"))
            expected = compose(app, str(directory), owner.pw_uid, owner.pw_gid,
                               self._app_valid_port(app, record["port"], network),
                               str(record["data"]), self._app_options(app), network, record.get("hardware"), config_path=record.get("config_path"))
            # Read recipes from older releases, but prevent Docker from silently
            # creating missing bind directories on an unavailable NAS volume.
            normalized = []
            for binding in service.get("volumes", []):
                if isinstance(binding, str):
                    source, target = binding.split(":")
                    binding = {"type": "bind", "source": source, "target": target,
                               "bind": {"create_host_path": False}}
                    if target == "/config":
                        binding["bind"]["selinux"] = "Z"
                normalized.append(binding)
            service["volumes"] = normalized
            if definition != expected and not ((APPS[app].get("titan_package") or APPS[app].get("imported_stack")) and record.get("definition_digest") == definition_digest(definition)):
                raise Error("App-Konfiguration weicht von der verwalteten Vorlage ab.", 403)
            data = Path(record["data"])
            if not data.is_absolute() or not data.is_relative_to(self.share_root) or data == self.share_root:
                raise Error("App-Daten liegen außerhalb des NAS-Datenbereichs.", 403)
        except (KeyError, TypeError, ValueError):
            raise Error("Ungültige App-Konfiguration.", 503)
        return record

    def _app_container_rows(self):
        output = _run(["docker", "ps", "-a", "--no-trunc", "--format", "{{json .}}"], timeout=30)
        try:
            return [json.loads(line) for line in output.splitlines() if line]
        except ValueError:
            raise Error("Docker liefert einen ungültigen Containerstatus.", 503)

    def _app_inspected_containers(self, rows=None):
        rows = self._app_container_rows() if rows is None else rows
        result = []
        for row in rows:
            value = row.get("ID")
            if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
                raise Error("Ungültige Container-ID in der RAM-Prüfung.", 503)
            values = json.loads(_run(["docker", "inspect", "--type", "container", value], timeout=30))
            if len(values) != 1 or values[0].get("Id") != value:
                raise Error("Container während der RAM-Prüfung ersetzt. Erneut versuchen.", 409)
            result.append(values[0])
        return result

    def op_app_memory_preflight(self, app, options=None):
        from .app_packages import PACKAGES, RESOURCE_PROFILES
        from .app_memory import memory_snapshot, memory_preflight, package_memory_plan, vm_memory_reservations
        if app not in APPS:
            raise Error("App-Vorlage nicht gefunden.", 404)
        options = {} if options is None else options
        if not isinstance(options, dict) or set(options) - {"resource_profile", "office_mode"}:
            raise Error("Nur RAM-Profil und Dokumentbearbeitung können vorab geprüft werden.")
        values = {}
        if app in PACKAGES:
            values["resource_profile"] = options.get("resource_profile", "balanced")
            if not isinstance(values["resource_profile"], str) or values["resource_profile"] not in RESOURCE_PROFILES:
                raise Error("Ungültiges RAM-Profil.")
        elif "resource_profile" in options:
            raise Error("Für diese App gibt es kein auswählbares RAM-Profil.")
        if app == "titan-nextcloud-office":
            values["office_mode"] = options.get("office_mode", "disabled")
            if values["office_mode"] not in ("enabled", "disabled"):
                raise Error("Ungültige Auswahl für Dokumentbearbeitung.")
        elif "office_mode" in options:
            raise Error("Dokumentbearbeitung ist nur für Nextcloud verfügbar.")
        plan = package_memory_plan(app, values)
        result = memory_preflight(memory_snapshot(), plan["startup_limit_bytes"],
            self._app_inspected_containers(), installation=True, vms=vm_memory_reservations(_run))
        return {**result, "plan": plan}

    @staticmethod
    def _app_capabilities_match(app, service_key, definition, host):
        from .app_gateway import IMAGE
        actual = {str(value).removeprefix('CAP_') for value in host.get('CapAdd') or []}
        gateway = (service_key == app and APPS.get(app, {}).get('app_gateway')
                   and definition.get('image') == IMAGE)
        if not gateway:
            return not actual
        return (actual == {'NET_BIND_SERVICE'} and host.get('ReadonlyRootfs') is True
                and set(host.get('CapDrop') or []) == {'ALL'}
                and set(host.get('SecurityOpt') or []) in ({'no-new-privileges'}, {'no-new-privileges:true'}))

    def _app_container(self, app, record, rows=None, options=None, service_key=None):
        service_key = service_key or app
        if rows is None:
            rows = self._app_container_rows()
        row = next((item for item in rows if item.get("Names") == "titan-" + service_key), None)
        if row is None:
            return None
        identifier = row.get("ID", "")
        if not isinstance(identifier, str) or not identifier or not all(char in "0123456789abcdef" for char in identifier):
            raise Error("Docker liefert eine ungültige Container-ID.", 503)
        try:
            result = json.loads(_run(["docker", "inspect", "--type", "container", identifier], timeout=30))
            container = result[0]
            labels = container.get("Config", {}).get("Labels") or {}
            expected_labels = {"io.titan.managed": "true", "io.titan.app": app,
                               "com.docker.compose.project": "titan-" + app,
                               "com.docker.compose.service": service_key}
            if any(labels.get(key) != value for key, value in expected_labels.items()):
                raise Error("Ein fremder Container belegt den App-Namen. Titan verändert ihn nicht.", 409)
            bindings = {binding["Destination"]: binding["Source"] for binding in container.get("Mounts", [])
                        if binding.get("Type") == "bind"}
            from .host import pwd
            owner = pwd.getpwnam("titan-files")
            options = self._app_options(app) if options is None else options
            network = selection(record.get("network"))
            document = compose(app, str(self.directory / "apps" / app), owner.pw_uid, owner.pw_gid,
                               record["port"], record["data"], options, network, record.get("hardware"), config_path=record.get("config_path"))
            stored_path = self.directory / "apps" / app / "compose.json"
            if record.get("definition_digest") and stored_path.is_file():
                stored = json.loads(stored_path.read_text())
                if record["definition_digest"] == definition_digest(stored):
                    document = stored
            definition = document["services"][service_key]
            expected_bindings = {binding["target"]: binding["source"] for binding in definition["volumes"]}
            host = container.get("HostConfig", {})
            from .app_memory import limit_bytes
            expected_memory = limit_bytes(definition.get('mem_limit'))
            if expected_memory is None or type(host.get('Memory')) is not int or host['Memory'] != expected_memory:
                raise Error("Das RAM-Limit des Containers stimmt nicht mit der App-Vorlage überein. App stoppen und die Einstellungen prüfen.", 409)
            def address(value):
                # Docker may represent an all-interface bind as both IPv4 and
                # IPv6 entries; specific addresses must match exactly.
                return "*" if value in ("", "0.0.0.0", "::") else value
            expected_ports = {}
            for publication in published_ports(app, record["port"], options, host_mode=network["mode"] == "host") if network["mode"] != "host" else []:
                if "service" in publication and (app if publication["service"] == APPS[app]["stack"]["primary"] else app+"-"+publication["service"].lower()) != service_key:
                    continue
                expected_ports.setdefault(f"{publication['target']}/{publication['protocol']}", set()).add((address(publication.get("host_ip", "")), str(publication["host"])))
            actual_ports = {}
            for target, publications in (host.get("PortBindings") or {}).items():
                actual_ports[target] = {(address(binding.get("HostIp", "")), str(binding["HostPort"])) for binding in publications or []}
            if (container.get("Name") != "/titan-" + service_key or container.get("Id") != identifier or
                    container.get("Config", {}).get("Image") != definition["image"] or
                    bindings != expected_bindings or actual_ports != expected_ports or
                    not self._app_declared_volumes(container, expected_bindings, definition.get("tmpfs", [])) or
                    host.get("Privileged") or not self._app_capabilities_match(app, service_key, definition, host) or
                    (host.get("Devices") or []) != [{"PathOnHost":v.split(":")[0],"PathInContainer":v.split(":")[1],"CgroupPermissions":v.split(":")[2]} for v in definition.get("devices", [])]):
                raise Error("Container und verwaltete App-Konfiguration stimmen nicht überein.", 409)
            expected_requests=definition.get("deploy",{}).get("resources",{}).get("reservations",{}).get("devices",[])
            requests=host.get("DeviceRequests") or []
            if len(requests)!=len(expected_requests) or any(request.get("Driver")!=expected.get("driver") or request.get("DeviceIDs")!=expected.get("device_ids") or request.get("Capabilities")!=[expected.get("capabilities")] or request.get("Count",0)!=0 or request.get("Options") not in ({},None) for request,expected in zip(requests,expected_requests)): raise Error("GPU-Zuordnung stimmt nicht mit der ausgewählten Hardware überein.",409)
            mode = host.get("NetworkMode")
            if network["mode"] == "host":
                if mode != "host":
                    raise Error("Container verwendet nicht das ausgewählte Host-Netzwerk.", 409)
            elif network["mode"] == "bridge":
                expected_name = network.get("name", "bridge")
                # Compose/Engine versions may retain the immutable network ID
                # as NetworkMode for an external network. Accept only the exact
                # ID pinned in our record; attachment and endpoint ID are still
                # checked independently below.
                accepted_modes = {expected_name}
                if record.get("network_id"):
                    accepted_modes.add(record["network_id"])
                if mode not in accepted_modes or set(container.get("NetworkSettings", {}).get("Networks", {})) != {expected_name}:
                    raise Error("Container verwendet nicht das ausgewählte Bridge-Netzwerk.", 409)
                endpoint = container["NetworkSettings"]["Networks"][expected_name]
                if record.get("network_id") and endpoint.get("NetworkID") != record["network_id"]:
                    # Engine stores the requested endpoint at create, but only
                    # fills NetworkID when allocating it on the first start.
                    # SELinux labeling must inspect that container beforehand.
                    # Do not accept missing operational identity after a start,
                    # or a different nonempty identity, even in state=created.
                    state = container.get("State", {})
                    unallocated = (endpoint.get("NetworkID") == "" and
                                   state.get("Status") == "created" and
                                   state.get("StartedAt") in ("0001-01-01T00:00:00Z", "0001-01-01T00:00:00.000000000Z") and
                                   not any(state.get(flag) for flag in ("Running", "Restarting", "Paused")) and
                                   not endpoint.get("EndpointID"))
                    if not unallocated:
                        raise Error("Container-Netzwerk wurde ersetzt oder stimmt nicht mit der App überein.", 409)
                    # A container created against a removed/replaced network
                    # still has its old name. Recheck the actual selected ID.
                    self._app_network_validate(network, app, record)
                if network.get("ipv4_address"):
                    actual_static = (endpoint.get("IPAMConfig") or {}).get("IPv4Address", "")
                    if actual_static != network["ipv4_address"] or (container.get("State", {}).get("Status") in ("running", "restarting") and endpoint.get("IPAddress") != network["ipv4_address"]):
                        raise Error("Container verwendet nicht die konfigurierte feste IPv4-Adresse.", 409)
            else:
                # Imported stacks can deliberately isolate front-end and
                # database traffic in different private Compose networks.
                # Derive this service's exact attachments from its pinned
                # definition rather than widening all services to _default.
                declared = definition.get("networks") or {"default": {}}
                expected_names = {"titan-" + app + "_" + name for name in declared}
                attached = container.get("NetworkSettings", {}).get("Networks")
                if attached is None and expected_names == {"titan-" + app + "_default"}:
                    # Older single-network inspect snapshots omit Networks.
                    attached = {}
                elif not isinstance(attached, dict) or set(attached) != expected_names:
                    raise Error("Container-Netzwerk weicht von der verwalteten Standardvorlage ab.", 409)
                if mode not in expected_names:
                    # Some Engine/Compose versions store the primary network
                    # ID. Verify that ID against the actual named network;
                    # an arbitrary endpoint ID is never sufficient evidence.
                    matched = next((name for name, endpoint in attached.items()
                                    if endpoint.get("NetworkID") == mode and mode), None)
                    if matched is None or self._docker_network(matched)["Id"] != mode:
                        raise Error("Container-Netzwerk weicht von der verwalteten Standardvorlage ab.", 409)
            return container
        except (KeyError, IndexError, TypeError, ValueError):
            raise Error("Docker liefert ungültige App-Details.", 503)

    def _app_container_summary(self, container, record=None, networks=None, addresses=None):
        if container is None:
            return None
        state = container.get("State", {})
        ports = []
        for target, bindings in (container.get("NetworkSettings", {}).get("Ports") or {}).items():
            target_port, protocol = target.split("/", 1)
            for binding in bindings or []:
                ports.append({"host": binding.get("HostIp", ""), "port": int(binding["HostPort"]),
                              "target": int(target_port), "protocol": protocol})
        summary = {"id": container["Id"], "name": container["Name"].lstrip("/"),
                "image": container.get("Config", {}).get("Image", ""),
                "state": state.get("Status", "unknown"), "health": state.get("Health", {}).get("Status", ""),
                "restarts": container.get("RestartCount", 0), "exit_code": state.get("ExitCode", 0),
                "error": state.get("Error", ""), "started": state.get("StartedAt", ""),
                "finished": state.get("FinishedAt", ""), "ports": ports}
        if record is not None:
            summary["error"] = self._package_redact(record["id"], str(summary["error"]))
            summary.update(self._app_address_summary(container, record, networks, addresses))
            summary.update(app_readiness(self, container, record, summary))
        return summary

    @staticmethod
    def _app_logs(container, tail):
        # Docker sends application stderr to its own stderr. Merge both streams,
        # spool to disk, and only return a bounded tail rather than env/inspect.
        arguments = ["docker", "logs", "--timestamps", "--tail", str(tail), container["Id"]]
        with tempfile.TemporaryFile() as output:
            try:
                result = subprocess.run(arguments, stdout=output, stderr=subprocess.STDOUT,
                                        timeout=30, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C.UTF-8"})
            except (OSError, subprocess.TimeoutExpired):
                raise Error("App-Protokoll ist momentan nicht erreichbar.", 503)
            output.seek(0, os.SEEK_END)
            length = output.tell()
            output.seek(max(0, length - 512 * 1024))
            text = output.read().decode("utf-8", errors="replace")
            if result.returncode:
                raise Error(text[-4000:] or "App-Protokoll konnte nicht gelesen werden.", 503)
            return ("[Protokoll auf die letzten 512 KiB begrenzt]\n" if length > 512 * 1024 else "") + text

    def docker(self, app, *arguments, timeout=600):
        starting = bool(arguments and arguments[0] in ("up", "restart", "create"))
        with self.app_memory_lock if starting else contextlib.nullcontext():
            return self._docker(app, *arguments, timeout=timeout)

    def _docker(self, app, *arguments, timeout=600):
        if arguments and arguments[0] in ("up", "restart", "create"):
            self.app_storage_ready(app)
        record = self.managed_app(app)
        container = self._app_container(app, record)
        if arguments and arguments[0] in ("up", "restart", "create"):
            self.app_devices_ready(record)
            network, _ = self._app_network_validate(record.get("network"), app, record)
            if network["mode"] == "host" and not (container and container.get("State", {}).get("Status") in ("running", "restarting")):
                self._host_ports_available(published_ports(app, record["port"], self._app_options(app), host_mode=True))
        path = self.directory / "apps" / app / "compose.json"
        definition = json.loads(path.read_text())
        rows = self._app_container_rows()
        for service_key in definition["services"]:
            if service_key != app: self._app_container(app,record,rows,service_key=service_key)
        if arguments and arguments[0] in ("up", "restart", "create"):
            from .app_memory import check_start_memory
            check_start_memory(app, self._app_options(app), definition,
                self._app_inspected_containers(rows), telemetry=self.telemetry)
        bindings = definition["services"][app]["volumes"]
        if any(isinstance(binding, str) for binding in bindings):
            from .host import pwd
            owner = pwd.getpwnam("titan-files")
            atomic_json(path, compose(app, str(path.parent), owner.pw_uid, owner.pw_gid, record["port"], record["data"], self._app_options(app), record.get("network"), record.get("hardware"), config_path=record.get("config_path")))
        def invoke(*options):
            return _run(["docker", "compose", "--project-name", "titan-" + app, "-f", str(path), *options], timeout=timeout)
        try:
            command = arguments[0] if arguments else None
            from .app_installation import active_install, progress
            installing = active_install(self, app)
            if command in ('up', 'restart', 'create') and app == 'titan-cloudflared':
                from .cloudflare_tunnel import prepare_runtime
                prepare_runtime(self, record)
            if command in ('up', 'restart', 'create') and app == 'titan-tailscale':
                from .native_apps import prepare_tailscale_runtime
                prepare_tailscale_runtime(self, record)
            if command in ("up", "restart", "create"): invoke("config", "--quiet")
            if command in ("up", "restart", "create"):
                if installing:
                    progress(self, app, 'files', 'completed', 'Private Dateien und Compose-Konfiguration erstellt und geprüft.')
                    progress(self, app, 'pull', message='Freigegebenes Container-Image wird geladen.')
                    invoke('pull')
                    progress(self, app, 'pull', 'completed', 'Container-Image vollständig verfügbar.')
                    progress(self, app, 'create', message='Container wird aus der geprüften Compose-Konfiguration erstellt.')
                # Compose's Mount API drops SELinux Z when create_host_path is
                # false. Keep missing-volume protection and label the verified
                # config using the actual new container MCS before it can run.
                options = [option for option in arguments[1:] if option != "-d"] if command != "restart" else ["--no-recreate"]
                created = invoke("create", *options)
                self._app_private_config_label(app, record)
                if installing:
                    progress(self, app, 'create', 'completed', 'Verwalteter Container erstellt; private Speicherzuordnung geprüft.')
                if command == "create":
                    return created
                from .app_memory import check_start_memory
                check_start_memory(app, self._app_options(app), definition,
                    self._app_inspected_containers(), telemetry=self.telemetry)
                self._app_firewall(app, enabled=True)
                if installing:
                    progress(self, app, 'start', message='Verwalteter Container wird gestartet.')
                if APPS[app].get('stack') and command == 'up':
                    output = invoke('up', '-d', '--no-recreate', '--wait', '--wait-timeout', '120' if app == 'titan-tailscale' else '300')
                else:
                    output = invoke("restart" if command == "restart" else "start")
                if installing:
                    progress(self, app, 'start', 'completed', 'Container-Start abgeschlossen. Die Betriebsbereitschaft wird separat geprüft.')
                return output
            return invoke(*arguments)
        except Error as exc:
            try:
                self._app_firewall_observed(app)
            except Error:
                pass
            message = str(exc)
            options = self._app_options(app)
            for field in APPS[app].get("install_schema", []):
                if field["type"] == "password" and options.get(field["key"]):
                    value = options[field["key"]]
                    message = message.replace(value.replace("$", "$$"), "[ausgeblendet]").replace(value, "[ausgeblendet]")
            raise Error(message, exc.status) from None

    @staticmethod
    def _app_selinux_active():
        # A mounted but permissive policy still needs labels for later enforcing.
        return Path("/sys/fs/selinux/enforce").exists()

    def _app_private_config_label(self, app, record):
        if not self._app_selinux_active() or not APPS[app].get("config_mount", True):
            return
        container = self._app_container(app, record)
        label = container.get("MountLabel") if container else None
        match = re.fullmatch(r"system_u:object_r:container_file_t:s0:c(0|[1-9][0-9]{0,3}),c(0|[1-9][0-9]{0,3})", label) if isinstance(label, str) else None
        if not match or any(int(value) > 1023 for value in match.groups()) or match[1] == match[2]:
            raise Error("Docker liefert kein gültiges privates SELinux-Label für die App-Konfiguration.", 503)
        # An unchanged `compose create` can leave an existing container running.
        # Quiesce its writer before checking hardlinks or relabeling the tree.
        if container.get("State", {}).get("Status") in ("running", "restarting"):
            _run(["docker", "compose", "--project-name", "titan-" + app, "-f",
                  str(self.directory / "apps" / app / "compose.json"), "stop"], timeout=60)
            stopped = self._app_container(app, record)
            if (not stopped or stopped.get("MountLabel") != label or
                    stopped.get("State", {}).get("Status") not in ("created", "exited", "dead", "paused")):
                raise Error("App ist vor der SELinux-Kennzeichnung nicht sicher gestoppt.", 503)
        root = self._app_config_path(app, record)
        base = Path(self.storage_locations.resolve(record["storage_id"], purpose="apps", write=False)["path"]) if record.get("storage_id") else self.directory
        components = (app, "config") if record.get("storage_id") else ("apps", app, "config")
        if not base.is_absolute():
            raise Error("App-Konfiguration benötigt einen absoluten lokalen Datenpfad.", 403)
        descriptors, identities = [], []
        try:
            descriptor = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.append(descriptor)
            parent = base
            for component in components:
                metadata = os.fstat(descriptor)
                if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
                    raise Error("Elternverzeichnis der App-Konfiguration ist nicht geschützt.", 403)
                identities.append((parent, metadata.st_dev, metadata.st_ino))
                descriptor = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                descriptors.append(descriptor)
                parent /= component
            metadata = os.fstat(descriptor)
            identities.append((root, metadata.st_dev, metadata.st_ino))
            self._app_config_no_hardlinks(descriptor)
            for path, device, inode in identities:
                current = os.stat(path, follow_symlinks=False)
                if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (device, inode):
                    raise Error("App-Konfigurationspfad wurde während der Prüfung verändert.", 409)
            # -P and -h never traverse a nested symlink into another host tree.
            # Do not use /proc/self/fd here: it is itself a symlink under -h.
            _run(["chcon", "--recursive", "--no-dereference", "-P", "--", label, str(root)], timeout=120)
            for path, device, inode in identities:
                current = os.stat(path, follow_symlinks=False)
                if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (device, inode):
                    raise Error("App-Konfigurationspfad wurde während der Kennzeichnung verändert.", 409)
            if os.getxattr(descriptor, "security.selinux").decode().rstrip("\0") != label:
                raise Error("Privates SELinux-Label der App-Konfiguration wurde nicht übernommen.", 503)
        except (OSError, UnicodeDecodeError):
            raise Error("App-Konfiguration kann nicht sicher mit ihrem SELinux-Label versehen werden.", 503) from None
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    @staticmethod
    def _app_config_no_hardlinks(descriptor):
        # A hardlink would label the same inode in a separate NAS directory.
        # App writers are stopped; descriptor traversal never follows symlinks.
        def walk(directory, depth):
            if depth > 128:
                raise Error("App-Konfiguration ist für eine sichere Kennzeichnung zu tief verschachtelt.", 503)
            for name in os.listdir(directory):
                metadata = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if not stat.S_ISDIR(metadata.st_mode) and metadata.st_nlink != 1:
                    raise Error("App-Konfiguration enthält Hardlinks; SELinux-Kennzeichnung bleibt gesperrt.", 403)
                if stat.S_ISDIR(metadata.st_mode):
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    try:
                        walk(child, depth + 1)
                    finally:
                        os.close(child)
        walk(descriptor, 0)

    def _app_record_result(self, app, error=None):
        self._app_patch_record(app, {"phase": "failed" if error else "ready",
            "last_error": self._package_redact(app, str(error))[-4000:] if error else "", "changed": time.time()})

    def op_app_gateway_info(self, app):
        from .app_access import app_id
        app_id(app)
        record = next((row for row in self.load("apps", []) if row['id'] == app), None)
        if not record or not APPS.get(app, {}).get('app_gateway'):
            raise Error("Geschützter App-Zugang ist nicht installiert.", 404)
        return {'id': app, 'port': record['port'], 'scheme': record.get('scheme', 'http')}

    def op_apps(self):
        records = [dict(record) for record in self.load("apps", [])]
        for record in records:
            if APPS.get(record["id"], {}).get("app_gateway"):
                record["app_gateway"] = True
            if record.get("last_error"):
                record["last_error"] = self._package_redact(record["id"], str(record["last_error"]))
        if not shutil.which("docker", path="/usr/sbin:/usr/bin:/sbin:/bin"):
            for record in records:
                record.update(state="unavailable", status="Docker ist nicht installiert.", web_state="unavailable", web_available=False, web_message="Docker ist nicht installiert.")
            return {"installed": records, "available": False, "error": "Docker ist nicht installiert."}
        try:
            _run(["docker", "compose", "version"], timeout=15)
            rows = self._app_container_rows()
        except Error as exc:
            for record in records:
                record.update(state="unavailable", status=str(exc), web_state="unavailable", web_available=False, web_message=str(exc))
            return {"installed": records, "available": False, "error": str(exc)}
        addresses = self._host_addresses()
        try:
            networks = {item["Name"]: item for item in self._docker_networks()}
        except Error:
            networks = None
        for record in records:
            try:
                checked = self.managed_app(record["id"])
                container = self._app_container(record["id"], checked, rows)
                summary = self._app_container_summary(container, checked, networks, addresses)
                record.update(state=summary["state"] if summary else "missing", container=summary)
                record.update({key: value for key, value in (summary or app_readiness(self, None, checked, None)).items()
                               if key.startswith("web_")})
                record["status"] = (summary["health"] or summary["state"]) if summary else "Container fehlt · Starten erneut versuchen"
                if record.get("last_error"):
                    record["status"] += " · Letzte Aktion fehlgeschlagen"
                if APPS[record['id']].get('titan_package') or APPS[record['id']].get('imported_stack'):
                    services = self._package_services(record['id'], checked, rows)
                    record['services'] = [{key: item[key] for key in ('id','name','state','health','ready','one_shot','warning')} for item in services]
                    record['warnings'] = [item['warning'] for item in services if item.get('warning')] + list(record.get('firewall_warnings', []))
                    record['package_ready'] = all(item['ready'] for item in services)
                    record['status'] = ("Alle Paketdienste bereit" if record['package_ready'] else str(sum(item['ready'] for item in services)) + " von " + str(len(services)) + " Paketdiensten bereit") + (" · Letzte Aktion fehlgeschlagen" if record.get('last_error') else "")
            except Error as exc:
                message = self._package_redact(record["id"], str(exc))
                record.update(state="blocked", status=message, last_error=message, web_state="blocked", web_available=False, web_message=message)
        return {"installed": records, "available": True}

    def op_app_details(self, app, tail=150):
        tail = integer(tail, 1, 500)
        record = self.managed_app(app)
        if record.get("last_error"):
            record["last_error"] = self._package_redact(app, str(record["last_error"]))
        warnings = ([record["last_error"]] if record.get("last_error") else []) + list(record.get("firewall_warnings", []))
        container = None
        logs = ""
        try:
            container = self._app_container(app, record)
            summary = self._app_container_summary(container, record)
            if container:
                try:
                    logs = self._package_redact(app, self._app_logs(container, tail))
                except Error as exc:
                    warnings.append(self._package_redact(app, str(exc)))
            else:
                warnings.append("Container fehlt. Mit Starten kann die Installation erneut versucht werden.")
            record.update(state=summary["state"] if summary else "missing", status=summary["state"] if summary else "Container fehlt")
            record.update({key: value for key, value in (summary or app_readiness(self, None, record, None)).items() if key.startswith("web_")})
        except Error as exc:
            summary = None
            message = self._package_redact(app, str(exc))
            record.update(state="blocked", status=message, web_state="blocked", web_available=False, web_message=message)
            warnings.append(message)
        return {"app": record, "container": summary, "logs": logs, "warnings": warnings,
                "config_path": str(self._app_config_path(app, record)), "data_path": record["data"]}

    def op_app_hardware(self, app, hardware):
        record=self.managed_app(app)
        self.app_storage_ready(app)
        self._app_network_validate(record.get('network'),app,record)
        inventory=app_devices_inventory();ids=validate_devices(hardware,inventory)
        chosen=[item for item in inventory if item['id'] in ids]
        rows=self._app_container_rows()
        path=self.directory/'apps'/app/'compose.json';old=path.read_bytes();definition=json.loads(old)
        for key in definition['services']:
            container=self._app_container(app,record,rows,service_key=key)
            if container and (container.get('State',{}).get('Running') or container.get('State',{}).get('Status') in ('running','paused','restarting')):raise Error('Die App vor dem Ändern der Geräte stoppen.',409)
        from .host import pwd
        owner=pwd.getpwnam('titan-files')
        proposed=compose(app,str(path.parent),owner.pw_uid,owner.pw_gid,record['port'],record['data'],self._app_options(app),record.get('network'),chosen, config_path=record.get("config_path"))
        atomic_json(path,proposed);self._app_patch_record(app,{'hardware':chosen, **({'definition_digest':definition_digest(proposed)} if APPS[app].get('titan_package') or APPS[app].get('imported_stack') else {})})
        args=['docker','compose','--project-name','titan-'+app,'-f',str(path)]
        try:
            _run([*args,'config','--quiet'])
            _run([*args,'create','--force-recreate'],timeout=600)
        except Error as exc:
            atomic_json(path,json.loads(old));self._app_patch_record(app,record)
            try:_run([*args,'create','--force-recreate'],timeout=600)
            except Error:raise Error('Gerätewechsel und Wiederherstellung fehlgeschlagen. Die vorherige Konfiguration wurde gesichert; App-Status prüfen.',503) from None
            raise Error('Gerätewechsel fehlgeschlagen; vorherige Konfiguration wiederhergestellt.',503) from None
        return {'ok':True,'message':'Gerätezuordnung gespeichert. Die App bleibt gestoppt und kann jetzt gestartet werden.'}

    def op_app_install(self, app, port, share=None, options=None, network=None, hardware=None, storage_id=None):
        if not isinstance(app, str) or app not in APPS:
            raise Error("App-Vorlage nicht gefunden.")
        if APPS[app].get("catalog_status") == "preparation":
            raise Error("Diese Titan-Vorlage ist noch in Vorbereitung. Neue Installation ist nicht freigegeben.")
        if APPS[app].get("app_gateway"):
            self.web_access.ensure_app_gateway()
        with self.app_memory_lock:
            return self._install_app(app, port, share, options, network, hardware, storage_id)

    def _install_app(self, app, port, share=None, options=None, network=None, hardware=None, storage_id=None):
        # Reserve ports, write a complete definition, and register it atomically.
        # The slow pull/start/provision phase holds only this app's object lock.
        with self.app_config_lock:
            self._prepare_app_install(app, port, share, options, network, hardware, storage_id)
        try:
            output = self.docker(app, "up", "-d")
            from .app_package_setup import provision
            provision(self, app, _run)
        except Exception as exc:
            self._app_record_result(app, exc)
            raise
        self._app_record_result(app)
        return {"ok": True, "scope": "package", "app": app, "action": "install", "output": output}

    def _prepare_app_install(self, app, port, share=None, options=None, network=None, hardware=None, storage_id=None):
        if app not in APPS:
            raise Error("App-Vorlage nicht gefunden.")
        if APPS[app].get("catalog_status")=="preparation":
            raise Error("Diese Titan-Vorlage ist noch in Vorbereitung. Neue Installation ist nicht freigegeben.")
        retained = self.load('retained-app-installations-v1', {}).get(app) if APPS[app].get('umbrel_catalog') else None
        if retained:
            if storage_id is not None and storage_id != retained.get('storage_id'):
                raise Error('Vorhandene App-Daten liegen auf einem anderen Speicher. Für die Wiederinstallation den bisherigen Speicher auswählen.', 409)
            storage_id = retained.get('storage_id')
            frozen = self.load('installed-app-recipes-v1', {}).get(app)
            if not frozen or not frozen.get('umbrel_catalog'):
                raise Error('Die gespeicherte App-Version fehlt. Vorhandene Daten bleiben unverändert.', 409)
            from .app_credentials import private_recipe
            APPS[app] = private_recipe(frozen)
            if network is None:
                network = retained.get('network')
        available_devices=app_devices_inventory()
        hardware_ids=validate_devices(hardware,available_devices)
        hardware=[item for item in available_devices if item["id"] in hardware_ids]
        network = selection(network if network is not None else {"mode": APPS[app].get("default_network","default")})
        port = self._app_valid_port(app, port, network)
        from .app_packages import prepare_options
        previous = self._app_options(app) if (self.directory / "apps" / app / "options.json").exists() else None
        if retained:
            options = {**(previous or {}), **(options or {})}
        options = validate_options(app, prepare_options(app, options, previous))
        if APPS[app].get('provision') == 'nextcloud-office':
            from .app_package_setup import validate_host
            validate_host(options['nas_host'])
        records = self.load("apps", [])
        if any(item["id"] == app for item in records):
            raise Error("App ist bereits angelegt. In der App-Verwaltung Starten erneut versuchen.", 409)
        publications = published_ports(app, port, options, host_mode=network["mode"] == "host")
        requested = {(item["host"], item["protocol"]) for item in publications}
        from .web_access import reserved_ports
        reserved = {(value, "tcp") for value in reserved_ports()}
        for item in records:
            reserved.update((publication["host"], publication["protocol"]) for publication in published_ports(item["id"], item["port"], self._app_options(item["id"]), host_mode=selection(item.get("network"))["mode"] == "host"))
        if requested & reserved:
            raise Error("Port ist bereits für Titan oder eine andere App reserviert. AdGuard und Pi-hole benötigen beide DNS-Port 53; nur einen DNS-Dienst pro NAS-IP verwenden oder einen anderen Port wählen.", 409)
        _run(["docker", "compose", "version"], timeout=30)
        rows = self._app_container_rows()
        network, network_id = self._app_network_validate(network, app)
        if network["mode"] == "host" or (APPS[app].get("titan_package") or APPS[app].get("imported_stack")):
            self._host_ports_available(publications)
        from .host import pwd
        owner = pwd.getpwnam("titan-files")
        path = self.directory / "apps" / app
        selected = None
        if share:
            selected = next((item for item in self.op_shares() if item["name"] == share), None)
            if not selected or selected.get("blocked") or "titan-files" not in selected["writers"]:
                raise Error("Die App benötigt eine aktive Freigabe mit Schreibrechten für titan-files.")
            resource = self.storage_locations.validate_path(selected["path"], purpose="apps", write=True)
            if storage_id is not None and storage_id != resource["id"]:
                raise Error("Der ausgewählte Ordner gehört zu einem anderen Speicher. Auswahl aktualisieren.", 409)
            storage_id = resource["id"]
        if storage_id is None:
            storage_id = self.load("storage-preferences", {}).get("default_storage", "system")
        resource = self.storage_locations.resolve(storage_id, purpose="apps", write=True)
        from .native_apps import check_requirements
        check_requirements(app, resource)
        data = Path(resource["path"]) / app / "data"
        config = Path(resource["path"]) / app / "config"
        if share:
            selected = next((item for item in self.op_shares() if item["name"] == share), None)
            if not selected or selected.get("blocked") or "titan-files" not in selected["writers"]:
                raise Error("Die App benötigt eine aktive Freigabe mit Schreibrechten für titan-files.")
            data = Path(selected["path"])
            descriptor = self.open_share_root(data)
            os.close(descriptor)
            self.app_storage_ready(app, str(data))
            if (APPS[app].get("titan_package") or APPS[app].get("imported_stack")):
                data = data / "Titan-Apps" / app
        record = {"id": app, "name": APPS[app]["name"], "port": port, "scheme": APPS[app].get("scheme", "http"),
                  "data": str(data), "config_path": str(config), "storage_id": storage_id,
                  **({"storage_uuid": resource["uuid"]} if resource.get("uuid") else {}), "installed": time.time(), "phase": "installing", "last_error": "", "network": network, **({"hardware":hardware} if hardware else {})}
        if network_id:
            record["network_id"] = network_id
        self._app_container(app, record, rows, options)
        proposed = compose(app,str(path),owner.pw_uid,owner.pw_gid,port,str(data),options,network,record.get("hardware"), config_path=record.get("config_path"))
        if retained and (any(record.get(key) != retained.get(key) for key in ('data', 'config_path', 'storage_id', 'storage_uuid'))):
            raise Error('Der bisherige App-Speicher oder Datenpfad stimmt nicht mehr überein. Keine Daten wurden verändert.', 409)
        for service_key in proposed["services"]:
            if service_key != app: self._app_container(app,record,rows,options,service_key)
        from .app_memory import check_install_memory
        memory = check_install_memory(app, options, self._app_inspected_containers(rows))
        record["memory_plan"] = memory["plan"]
        from .umbrel_files import validate as validate_seeds, install as install_seeds
        seeds = APPS[app].get('seed_files', [])
        validate_seeds(seeds)
        file_slots = {row['slot'] for row in seeds if not row['path']}
        # Pin the chosen filesystem while creating the complete package tree.
        # No mkdir is allowed to manufacture an offline pool on the system disk.
        with self.storage_locations.fd(storage_id, purpose="apps", create=True, write=True):
            self._app_directory(path / "config", self.directory, owner)  # Legacy control directory.
            self._app_directory(config, Path(resource["path"]), owner)
            if not share:
                self._app_directory(data, Path(resource["path"]), owner)
            elif (APPS[app].get("titan_package") or APPS[app].get("imported_stack")):
                self._app_directory(data, Path(selected["path"]), owner)
            for service in proposed["services"].values():
                for binding in service["volumes"]:
                    source = Path(binding["source"])
                    if source.is_relative_to(config) and source != config:
                        if source.parent == config and source.name in file_slots:
                            continue
                        mount_owner = owner
                        user = service.get('user')
                        if user:
                            from types import SimpleNamespace
                            parts = user.split(':')
                            mount_owner = SimpleNamespace(pw_uid=int(parts[0]), pw_gid=int(parts[-1]))
                        self._app_directory(source, Path(resource["path"]), mount_owner)
            install_seeds(config, seeds, proposed, owner.pw_uid, owner.pw_gid)
        atomic_json(path / "options.json", options)
        atomic_json(path / "compose.json", compose(app, str(path), owner.pw_uid, owner.pw_gid, port, str(data), options, network, record.get("hardware"), config_path=record.get("config_path")))
        if (APPS[app].get("titan_package") or APPS[app].get("imported_stack")):
            record["definition_digest"] = definition_digest(proposed)
        if APPS[app].get('imported_stack'):
            import copy
            frozen = self.load('installed-app-recipes-v1', {})
            frozen[app] = copy.deepcopy(APPS[app])
            self.save('installed-app-recipes-v1', frozen)
        records.append(record)
        self.save("apps", records)

    def op_app_action(self, app, action):
        if action not in ("start", "stop", "restart", "logs", "remove", "update", "backup"):
            raise Error("Ungültige App-Aktion.")
        if action in ("stop", "remove"):
            try:
                return self._app_stop_or_remove(app, action)
            except Exception as exc:
                self._app_record_result(app, exc)
                raise
        if action == 'update' and (APPS.get(app, {}).get('titan_package') or APPS.get(app, {}).get('imported_stack')):
            return self.op_package_update(app)
        if action in ("start", "restart", "update", "backup"):
            self.app_storage_ready(app)
        try:
            if action == "start":
                result = {"output": self.docker(app, "up", "-d")}
                from .app_package_setup import provision
                provision(self, app, _run)
            elif action == "restart":
                record = self.managed_app(app)
                if not self._app_container(app, record):
                    raise Error("Container fehlt. Bitte zuerst Starten erneut versuchen.", 409)
                result = {"output": self.docker(app, "restart")}
            elif action == "logs":
                return {"output": self.op_app_details(app)["logs"]}
            elif action == "update":
                record = self.managed_app(app)
                container = self._app_container(app, record)
                running = bool(container and container.get("State", {}).get("Status") in ("running", "restarting"))
                backup = self.op_app_backup(app)
                self.docker(app, "pull")
                output = self.docker(app, "up", "-d") if running else self.docker(app, "create", "--force-recreate")
                if running:
                    from .app_package_setup import provision
                    provision(self, app, _run)
                result = {"output": output, "backup": backup, "kept_stopped": not running}
            else:
                return self.op_app_backup(app)
        except Exception as exc:
            if action not in ("logs", "backup"):
                self._app_record_result(app, exc)
            raise
        self._app_record_result(app)
        return {"ok": True, "scope": "package", "app": app, "action": action, **result}

    def op_app_backup(self, app, keep_stopped=False):
        if type(keep_stopped) is not bool:
            raise Error('Ungültige Sicherungsoption.')
        self.app_storage_ready(app)
        record = self.managed_app(app)
        container = self._app_container(app, record)
        running = bool(container and container.get("State", {}).get("Status") in ("running", "restarting"))
        package_running = []
        if APPS[app].get('titan_package') or APPS[app].get('imported_stack'):
            definition = json.loads((self.directory / 'apps' / app / 'compose.json').read_text())
            rows = self._app_container_rows()
            for key in definition['services']:
                member = self._app_container(app, record, rows, service_key=key)
                state = (member or {}).get('State', {}).get('Status')
                if state == 'paused':
                    raise Error('Pausierte Paketdienste vor der Sicherung fortsetzen oder stoppen.', 409)
                if state in ('running', 'restarting'): package_running.append(member['Id'])
            running = bool(package_running)
        if container and container.get("State", {}).get("Status") == "paused":
            raise Error("Pausierte App zuerst in Docker fortsetzen oder stoppen.", 409)
        if running:
            self.docker(app, "stop")
        destination = self.directory / "backups"
        destination.mkdir(exist_ok=True, mode=0o700)
        backup = destination / f"{app}-{time.time_ns()}.tar.gz"
        completed = False
        try:
            arguments = ["tar", "-czf", str(backup), "-C", str(self.directory / "apps"), app]
            config = self._app_config_path(app, record)
            if config != self.directory / "apps" / app / "config":
                arguments += ["--transform=s,^config," + app + "/package-config,", "-C", str(config.parent), "config"]
            _run(arguments, timeout=600)
            completed = True
        except Exception:
            backup.unlink(missing_ok=True)
            raise
        finally:
            if package_running and (not keep_stopped or not completed):
                # Restore only services that were running before the cold backup.
                _run(['docker', 'start', *package_running], timeout=180)
            elif running and (not keep_stopped or not completed):
                self.docker(app, "up", "-d")
        return {"path": str(backup), "scope": "App-Konfiguration; Nutzdaten separat sichern.", "kept_stopped": keep_stopped or not running}

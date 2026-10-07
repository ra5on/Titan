"""Package-wide state, diagnostics, repair and approved update recipes.

Only Titan's four curated packages are presented here. Legacy installed recipes
remain manageable through AppMixin; this is not an arbitrary Compose importer.
"""
import hashlib
import ipaddress
import json

from .app_packages import PACKAGES
from .catalog import APPS, compose, published_ports, validate_options
from .core import Error, atomic_json, integer


def definition_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class PackageCenterMixin:
    def _package_redact(self, app, value):
        if app not in APPS:
            return "Details können ohne gültige private App-Vorlage nicht angezeigt werden."
        try:
            options = self._app_options(app)
        except Error:
            return "Protokoll konnte ohne gültige private App-Einstellungen nicht angezeigt werden."
        for field in APPS[app].get("install_schema", []):
            secret = options.get(field["key"])
            if field["type"] == "password" and secret:
                value = value.replace(secret.replace("$", "$$"), "[ausgeblendet]").replace(secret, "[ausgeblendet]")
        return value

    def _package_services(self, app, record, rows=None):
        if app not in APPS or not (app in PACKAGES or APPS[app].get('imported_stack')):
            raise Error("Dieses Paket gehört nicht zum Titan-Paketzentrum.")
        definition = json.loads((self.directory / "apps" / app / "compose.json").read_text())
        rows = self._app_container_rows() if rows is None else rows
        services = []
        recipe = APPS[app]
        raw_keys = list(recipe["stack"]["services"])
        for key, expected in definition["services"].items():
            original = recipe["stack"]["primary"] if key == app else key[len(app) + 1:]
            one_shot = bool(original == 'office-init' or any(isinstance(service.get('depends_on'), dict) and service['depends_on'].get(key, {}).get('condition') == 'service_completed_successfully' for service in definition['services'].values()))
            warning = ""
            try:
                container = self._app_container(app, record, rows, service_key=key)
            except Error as exc:
                container = None
                warning = self._package_redact(app, str(exc))
            summary = self._app_container_summary(container, record) if container else None
            state = summary["state"] if summary else "blocked" if warning else "missing"
            health = summary["health"] if summary else ""
            ready = bool(summary and (state == "running" and (health == "healthy" if expected.get("healthcheck") else health not in ("starting", "unhealthy")) or one_shot and state == "exited" and summary["exit_code"] == 0))
            if app == 'titan-cloudflared' and key == app and ready:
                from .cloudflare_tunnel import connector_ready
                ready = connector_ready(container)
                if not ready:
                    warning = 'Container läuft, aber die Cloudflare-Verbindung ist nicht bestätigt. Token und Internetzugang prüfen.'
            if app == 'titan-tailscale' and key == app and ready:
                from .native_apps import tailscale_runtime
                ready = tailscale_runtime(container)['connected']
                if not ready:
                    warning = 'Container läuft, aber die Verbindung zum Tailscale-Konto ist nicht bestätigt. Auth-Key und Internetzugang prüfen.'
            label = recipe.get("dependencies", raw_keys)[raw_keys.index(original)] if original in raw_keys else original
            services.append({"id": key, "name": label, "state": state, "health": health, "ready": ready,
                              "one_shot": one_shot, "image": expected["image"], "container": summary, "warning": warning,
                             "depends_on": list(expected.get("depends_on", {}))})
        return services

    def op_package_details(self, app):
        if app not in APPS or not (app in PACKAGES or APPS[app].get('imported_stack')):
            raise Error("Paket nicht gefunden.", 404)
        installed = next((dict(item) for item in self.load("apps", []) if item["id"] == app), None)
        if installed is None:
            return {"installed": False, "app": app, "services": [], "phase": "available"}
        warnings, services = [], []
        try:
            record = self.managed_app(app)
            services = self._package_services(app, record)
            warnings.extend(item["warning"] for item in services if item.get("warning"))
        except (Error, OSError, ValueError, KeyError) as exc:
            warnings.append(str(exc) if isinstance(exc, Error) else "Paketkonfiguration konnte nicht gelesen werden.")
        if installed.get("last_error"):
            installed["last_error"] = self._package_redact(app, str(installed["last_error"]))
            warnings.append(installed["last_error"])
        ready = bool(services and all(item["ready"] for item in services) and not warnings)
        running = sum(item["state"] == "running" for item in services)
        primary = next((item for item in services if item["id"] == app), None)
        primary_web = {key: value for key, value in ((primary or {}).get("container") or {}).items() if key.startswith("web_")}
        installed.update(primary_web)
        options = self._app_options(app)
        settings = [{"key": field["key"], "label": field["label"], "value": options.get(field["key"]), "type": field["type"], "min": field.get("min"), "max": field.get("max"), "choices": field.get("choices"), "editable": field["type"] != "password" and field["key"] != "username"}
                    for field in APPS[app].get("install_schema", []) if field["type"] != "password"]
        definition = json.loads((self.directory / "apps" / app / "compose.json").read_text())
        from .host import pwd
        owner = pwd.getpwnam("titan-files")
        target = compose(app, str(self.directory / "apps" / app), owner.pw_uid, owner.pw_gid, installed["port"], installed["data"], options, installed.get("network"), installed.get("hardware"), config_path=installed.get("config_path"))
        return {"installed": True, "app": installed, "services": services, "ready": ready,
                "primary_state": primary["state"] if primary else "missing",
                "primary_available": primary_web.get("web_available") is True, **primary_web,
                "primary_ready": bool(primary and primary["ready"]),
                "phase": "ready" if ready else "blocked" if warnings else "stopped" if not running else "attention",
                "warnings": warnings, "running_services": running, "total_services": len(services),
                "login": {"instructions": APPS[app]["first_login"]["instructions"], "username": options.get("username", ""), "password_selected": any(field["type"] == "password" and not field.get("generated") for field in APPS[app]["install_schema"])},
                "settings": settings, "data_path": installed["data"], "port": installed["port"],
                "update": {"available": definition_digest(definition) != definition_digest(target), "policy": "installed-store-recipe" if APPS[app].get("imported_stack") else "approved-titan-recipe", "backup_required": True,
                           "message": "Die installierte Store-Vorlage bleibt fest gespeichert. Katalogaktualisierungen ändern diesen Stack nicht. Images werden ausschließlich für diese gespeicherte Vorlage geladen." if APPS[app].get("imported_stack") else "Titan aktualisiert alle Paketdienste gemeinsam auf die freigegebenen Versionen. Vorher wird die Konfiguration einschließlich interner Datenbanken gesichert; Nutzdaten separat sichern."}}

    def op_package_diagnose(self, app):
        record = self.managed_app(app)
        checks = []
        for key, name, check in (
            ("storage", "Datenordner erreichbar", lambda: self.app_storage_ready(app)),
            ("network", "Docker-Netzwerk verfügbar", lambda: self._app_network_validate(record.get("network"), app, record)),
            ("devices", "Zugeordnete Geräte verfügbar", lambda: self.app_devices_ready(record)),
        ):
            try:
                check()
                checks.append({"id": key, "name": name, "ok": True, "message": "Verfügbar"})
            except (Error, OSError) as exc:
                checks.append({"id": key, "name": name, "ok": False, "message": self._package_redact(app, str(exc))})
        details = self.op_package_details(app)
        for service in details["services"]:
            checks.append({"id": service["id"], "name": service["name"], "ok": service["ready"], "message": service["health"] or service["state"]})
        return {"app": app, "ok": all(item["ok"] for item in checks) and not details["warnings"], "checks": checks,
                "warnings": details["warnings"], "repair_available": all(item["ok"] for item in checks if item["id"] in ("storage", "network", "devices")),
                "message": "Reparieren startet vorhandene Dienste und erstellt fehlende Container aus der gespeicherten Vorlage. Daten und private Schlüssel bleiben erhalten."}

    def op_package_logs(self, app, service, tail=100):
        record = self.managed_app(app)
        tail = integer(tail, 1, 500)
        services = self._package_services(app, record)
        if service not in {item['id'] for item in services}:
            raise Error("Dieser Dienst gehört nicht zum Paket.", 403)
        container = self._app_container(app, record, service_key=service)
        if container is None:
            return {'service': service, 'logs': 'Container ist noch nicht vorhanden.'}
        return {'service': service, 'logs': self._package_redact(app, self._app_logs(container, tail))}

    def op_package_repair(self, app):
        if app not in APPS or not (app in PACKAGES or APPS[app].get('imported_stack')):
            raise Error("Paket nicht gefunden.", 404)
        diagnosis = self.op_package_diagnose(app)
        if not diagnosis["repair_available"]:
            raise Error("Zuerst die nicht verfügbaren Laufwerke, Netzwerke oder Geräte wiederherstellen.", 409)
        if app == "titan-nextcloud-office":
            self._app_patch_record(app, {"package_initialized": False})
        result = self.op_app_action(app, "start")
        return {**result, "message": "Paketdienste gestartet und erforderliche Verbindungen erneut eingerichtet."}

    def op_package_settings(self, app, port, options=None):
        with self.app_config_lock:
            return self._package_settings(app, port, options)

    def _package_settings(self, app, port, options=None):
        """Change published ports/Office address on a stopped package safely."""
        if app not in APPS or not (app in PACKAGES or APPS[app].get('imported_stack')):
            raise Error("Paket nicht gefunden.", 404)
        record = self.managed_app(app)
        services = self._package_services(app, record)
        if any(item['state'] in ('running', 'paused', 'restarting') for item in services):
            raise Error("Das gesamte Paket vor dem Ändern der Einstellungen stoppen.", 409)
        port = self._app_valid_port(app, port, {"mode": record.get("network", {}).get("mode", "default")})
        options = {} if options is None else options
        editable = {field['key'] for field in APPS[app]['install_schema'] if field['type'] != 'password' and field['key'] != 'username'}
        if not isinstance(options, dict) or set(options) - editable:
            raise Error("Nur veröffentlichte Ports und NAS-Adresse können hier geändert werden. Konten und Passwörter direkt in der Anwendung verwalten.")
        old_options = self._app_options(app)
        proposed_options = validate_options(app, {**old_options, **options})
        if app == 'titan-nextcloud-office':
            from .app_package_setup import validate_host
            validate_host(proposed_options['nas_host'])
        publications = published_ports(app, port, proposed_options, host_mode=record.get("network", {}).get("mode") == "host")
        requested = {(item['host'], item['protocol']) for item in publications}
        from .web_access import reserved_ports
        reserved = {(value, 'tcp') for value in reserved_ports()}
        for item in self.load('apps', []):
            if item['id'] == app: continue
            reserved.update((value['host'], value['protocol']) for value in published_ports(item['id'], item['port'], self._app_options(item['id'])))
        if requested & reserved:
            raise Error("Ein gewünschter Port ist bereits für Titan oder eine andere App reserviert.", 409)
        self._host_ports_available(publications)
        self.app_storage_ready(app)
        backup = self.op_app_backup(app)
        from .host import pwd, run
        owner = pwd.getpwnam('titan-files')
        path = self.directory / 'apps' / app
        definition = compose(app, str(path), owner.pw_uid, owner.pw_gid, port, record['data'], proposed_options, record.get('network'), record.get('hardware'), config_path=record.get("config_path"))
        # Keep the currently installed image versions. Settings are not an
        # implicit version upgrade (database migrations need the update flow).
        previous_definition = json.loads((path / 'compose.json').read_text())
        for key, service in definition['services'].items():
            if key in previous_definition['services']:
                service['image'] = previous_definition['services'][key]['image']
        old_record = dict(record)
        self._app_stop_or_remove(app, 'remove', unregister=False)
        try:
            atomic_json(path / 'options.json', proposed_options)
            atomic_json(path / 'compose.json', definition)
            self._app_patch_record(app, dict(port=port, definition_digest=definition_digest(definition), package_initialized=False))
            output = self.docker(app, 'create', '--force-recreate')
        except Exception:
            atomic_json(path / 'options.json', old_options)
            atomic_json(path / 'compose.json', previous_definition)
            self._app_patch_record(app, old_record)
            # Remove partially recreated containers using the new definition,
            # then recreate the old stopped package without starting anything.
            try:
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', dir=path, suffix='.json') as temporary:
                    json.dump(definition, temporary); temporary.flush()
                    run(['docker', 'compose', '--project-name', 'titan-' + app, '-f', temporary.name, 'down'], timeout=180)
                self.docker(app, 'create', '--force-recreate')
            except Error:
                raise Error("Einstellungsänderung fehlgeschlagen; alte Konfiguration bleibt gespeichert, Container müssen repariert werden.", 503) from None
            raise
        return {'ok': True, 'output': output, 'backup': backup, 'message': 'Einstellungen gespeichert. Das Paket bleibt gestoppt; beim nächsten Start werden die internen Verbindungen geprüft.'}

    def op_package_update(self, app):
        if app not in APPS or not (app in PACKAGES or APPS[app].get('imported_stack')):
            raise Error("Paket nicht gefunden.", 404)
        record = self.managed_app(app)
        self.app_storage_ready(app)
        services = self._package_services(app, record)
        if any(item['state'] == 'paused' for item in services):
            raise Error("Pausierte Paketdienste vor dem Update fortsetzen oder stoppen.", 409)
        running = any(item['state'] in ('running', 'restarting') for item in services)
        # This cold backup includes the managed configuration tree, database,
        # application configuration and generated secrets. User files outside
        # the package tree are deliberately identified as a separate backup.
        backup = self.op_app_backup(app)
        from .host import pwd, run
        owner = pwd.getpwnam('titan-files')
        path = self.directory / 'apps' / app / 'compose.json'
        definition = compose(app, str(path.parent), owner.pw_uid, owner.pw_gid, record['port'], record['data'], self._app_options(app), record.get('network'), record.get('hardware'), config_path=record.get("config_path"))
        commands = ['docker', 'compose', '--project-name', 'titan-' + app, '-f', str(path)]
        # Verify and stop every existing member using the old definition first.
        # Containers belonging to other projects are never removed.
        self._app_stop_or_remove(app, 'remove', unregister=False)
        atomic_json(path, definition)
        self._app_patch_record(app, dict(definition_digest=definition_digest(definition),
            package_initialized=False, phase='updating', last_update_backup=backup['path']))
        try:
            run([*commands, 'config', '--quiet'], timeout=30)
            self.docker(app, 'pull')
            output = self.docker(app, 'up', '-d') if running else self.docker(app, 'create', '--force-recreate')
            if running:
                from .app_package_setup import provision
                provision(self, app, run)
        except Exception as exc:
            self._app_record_result(app, exc)
            raise Error("Paketupdate nicht vollständig. Die vorherige Konfiguration einschließlich interner Datenbanken liegt unter " + backup['path'] + ". Die neue Vorlage bleibt für Diagnose und Reparatur gespeichert. Bei einer bereits erfolgten Datenbankmigration keine alten Images ohne Wiederherstellung starten.", 503) from None
        self._app_record_result(app)
        return {'ok': True, 'output': output, 'backup': backup, 'kept_stopped': not running,
                'message': 'Alle Paketdienste gemeinsam aktualisiert. Die vor dem Update angelegte Sicherung bleibt erhalten.'}

    def op_app_office_runtime(self):
        """Privileged RPC contract only. Never expose this through an HTTP GET."""
        app = "titan-nextcloud-office"
        record = self.managed_app(app)
        container = self._app_container(app, record, service_key=app + "-eurooffice")
        state = (container or {}).get("State", {})
        if state.get("Status") != "running" or state.get("Health", {}).get("Status") != "healthy":
            raise Error("Euro-Office ist noch nicht bereit. Das Nextcloud-Paket starten oder reparieren.", 503)
        endpoints = container.get("NetworkSettings", {}).get("Networks") or {}
        if len(endpoints) != 1:
            raise Error("Office-Netzwerk konnte nicht eindeutig geprüft werden.", 503)
        endpoint = next(iter(endpoints.values()))
        try:
            address = ipaddress.IPv4Address(endpoint.get("IPAddress", ""))
            gateway = ipaddress.IPv4Address(endpoint.get("Gateway", ""))
        except ipaddress.AddressValueError:
            raise Error("Office benötigt das interne Docker-Bridge-Netzwerk.", 503) from None
        if address.is_loopback or address.is_unspecified or gateway.is_loopback or gateway.is_unspecified:
            raise Error("Ungültige interne Office-Netzwerkadresse.", 503)
        return {"secret": self._app_options(app)["office_secret"], "engine_origin": "http://" + str(address) + ":80", "bridge_gateway": str(gateway)}

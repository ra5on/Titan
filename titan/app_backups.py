"""Cold app snapshots on the selected independent backup disk.

Only a still-installed, unchanged recipe can be restored. Archive host paths,
commands and container identities are never executed or imported.
"""
import contextlib
import json
import os
from pathlib import Path
import re
import secrets
import threading

from .core import Error, atomic_json
from .catalog import APPS, compose, validate_options
from .package_center import definition_digest


APP_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}")


class AppBackups:
    def __init__(self, backups):
        self.backups, self.host = backups, backups.host

    def available(self):
        return [{"id": item["id"], "name": str(item.get("name", APPS[item["id"]].get("name", item["id"])))}
                for item in self.host.load("apps", [])
                if item.get("id") in APPS and APP_ID.fullmatch(item["id"])]

    @staticmethod
    def validate_manifest(value):
        apps, data = value.get("apps"), value.get("app_data")
        if (not isinstance(apps, list) or not 1 <= len(apps) <= 1000 or
                any(not isinstance(app, str) or not APP_ID.fullmatch(app) for app in apps) or len(set(apps)) != len(apps) or
                not isinstance(data, list) or any(not isinstance(app, str) for app in data) or
                len(set(data)) != len(data) or not set(data) <= set(apps)):
            raise Error("Ungültige App-Auswahl im Sicherungsmanifest.")

    def selected(self, apps, data):
        if apps == [] and data == []:
            return [], []
        self.validate_manifest({"apps": apps, "app_data": data})
        known = {item["id"] for item in self.available()}
        if not set(apps) <= known:
            raise Error("Eine ausgewählte App ist nicht mehr installiert oder ihre Vorlage fehlt.", 409)
        return sorted(apps), sorted(data)

    @staticmethod
    def allowed_member(parts, manifest):
        return (len(parts) >= 2 and parts[0] == "apps" and parts[1] in manifest.get("apps", []) and
                (len(parts) == 2 or parts[2:] == ("app.json",) or
                 parts[2] == "config" or parts[2] == "data" and parts[1] in manifest["app_data"]))

    @staticmethod
    def validate_links(nodes, links):
        """Resolve archive links without consulting or following host paths.

        Each link stays in its own config/data tree, including through other
        links and through '..' after a link. Dangling links and loops fail
        closed. Archive parents are separately required to be real directories.
        """
        def reject(message, path):
            raise Error(message + " Archivpfad: " + json.dumps("/".join(path), ensure_ascii=False))

        def components(target, path):
            if (not isinstance(target, str) or not target or len(target) > 4096 or
                    target.startswith("/") or "\\" in target or "\x00" in target):
                reject("App-Sicherung enthält einen absoluten oder ungültigen Link.", path)
            return target.split("/")

        for path, target in links.items():
            root, cursor, pending, expansions = path[:3], list(path[3:-1]), components(target, path), 0
            if len(path) < 4 or root[0] != "apps" or root[2] not in ("config", "data"):
                reject("Links sind nur innerhalb ausgewählter App-Verzeichnisse erlaubt.", path)
            while pending:
                component, pending = pending[0], pending[1:]
                if component in ("", "."):
                    continue
                if component == "..":
                    if not cursor:
                        reject("App-Link verlässt das gesicherte Verzeichnis.", path)
                    cursor.pop()
                    continue
                cursor.append(component)
                current = root + tuple(cursor)
                kind = nodes.get(current)
                if kind == "link":
                    expansions += 1
                    if expansions > 40:
                        reject("App-Sicherung enthält eine Link-Schleife oder zu lange Link-Kette.", path)
                    cursor.pop()
                    pending = components(links[current], path) + pending
                elif kind not in ("directory", "file") or pending and kind != "directory":
                    reject("App-Link hat kein vorhandenes internes Datei- oder Verzeichnisziel.", path)

    def inspect(self, app):
        self.selected([app], [])
        self.host.app_storage_ready(app)
        record = self.host.managed_app(app)
        control = self.host.directory / "apps" / app
        with self.backups._data_fd(control):
            definition = json.loads((control / "compose.json").read_text())
        options = self.host._app_options(app)
        rows, containers = self.host._app_container_rows(), {}
        for key in definition["services"]:
            member = self.host._app_container(app, record, rows, options, service_key=key)
            if not member:
                raise Error("Vor der App-Sicherung oder Wiederherstellung fehlende Container reparieren.", 409)
            if member.get("State", {}).get("Status") == "paused":
                raise Error("Pausierte App-Dienste zuerst fortsetzen oder stoppen.", 409)
            containers[key] = member
        config = self.host._app_config_path(app, record)
        data = Path(record["data"])
        if config == data or config.is_relative_to(data) or data.is_relative_to(config):
            raise Error("App-Konfiguration und Nutzdaten müssen getrennte Verzeichnisse sein.", 409)
        return {"record": record, "control": control, "config": config, "data": data,
                "definition": definition, "options": options, "containers": containers}

    @staticmethod
    def active(member):
        return member.get("State", {}).get("Status") in ("running", "restarting", "paused") or member.get("State", {}).get("Running") is True

    @contextlib.contextmanager
    def quiesce(self, apps):
        prepared, restart = {}, []
        try:
            # Validate every selected package before stopping any application.
            prepared = {app: self.inspect(app) for app in apps}
            for app, snapshot in prepared.items():
                running = [item["Id"] for item in snapshot["containers"].values() if self.active(item)]
                if running:
                    restart.extend(running)
                    self.host.docker(app, "stop")
                checked = self.inspect(app)
                if any(self.active(item) for item in checked["containers"].values()):
                    raise Error("Nicht alle App-Dienste sind gestoppt; Sicherung abgebrochen.", 409)
                prepared[app] = checked
            yield prepared
        finally:
            if restart:
                try:
                    # Restore precisely the pre-backup running set, including
                    # partial packages; never start an initially stopped service.
                    self.backups.run(["docker", "start", *restart], timeout=180)
                except Exception:
                    self.backups._last(False, "App-Sicherung beendet, aber vorher laufende Dienste konnten nicht wieder gestartet werden.")
                    raise Error("Vorher laufende App-Dienste konnten nach der Sicherung nicht wieder gestartet werden. Docker-Status prüfen.", 503) from None

    def write(self, archive, totals, temporary, prepared, app_data):
        for app, snapshot in prepared.items():
            metadata = temporary / ("app-" + app)
            metadata.mkdir(mode=0o700)
            value = {"schema": 1, "app": app, "definition_digest": definition_digest(snapshot["definition"]),
                     "images": {key: item["Image"] for key, item in snapshot["containers"].items()},
                     "image_references": {key: service["image"] for key, service in snapshot["definition"]["services"].items()},
                     "options": snapshot["options"]}
            atomic_json(metadata / "app.json", value)
            self.backups._add_tree(archive, metadata, "apps/" + app, totals, preserve=True)
            self.backups._add_tree(archive, snapshot["config"], "apps/" + app + "/config", totals, preserve=True, allow_links=True)
            if app in app_data:
                self.backups._add_tree(archive, snapshot["data"], "apps/" + app + "/data", totals, preserve=True, allow_links=True)

    def metadata(self, backup, app):
        result = None
        with self.backups._archive(backup) as (manifest, archive):
            if manifest["type"] != "bundle" or app not in manifest["apps"]:
                raise Error("Diese Sicherung enthält die ausgewählte App nicht.", 404)
            for member, parts in self.backups._members(archive, manifest):
                if parts == ("apps", app, "app.json"):
                    if not member.isfile() or member.size > 16 * 1024 * 1024:
                        raise Error("Ungültige App-Metadaten im Archiv.")
                    result = json.load(archive.extractfile(member))
        if (not isinstance(result, dict) or set(result) != {"schema", "app", "definition_digest", "images", "image_references", "options"} or
                result["schema"] != 1 or result["app"] != app):
            raise Error("App-Metadaten fehlen oder sind ungültig.")
        return result

    def local_images_match(self, references, images):
        try:
            names = sorted(set(references.values()))
            rows = json.loads(self.backups.run(["docker", "inspect", "--type", "image", *names], timeout=30))
            if not isinstance(rows, list) or len(rows) != len(names):
                return False
            resolved = {name: row["Id"] for name, row in zip(names, rows)}
            return all(resolved[reference] == images[key] for key, reference in references.items())
        except Exception:
            return False

    @contextlib.contextmanager
    def trusted_restore(self, app):
        # The durable marker stays in place even if Docker/create or a later
        # control-file write fails. Only this thread may validate the known
        # restored definition while other requests continue to fail closed.
        if not hasattr(self.host, "_app_restore_local"):
            self.host._app_restore_local = threading.local()
        local = self.host._app_restore_local
        previous = getattr(local, "app", None)
        local.app = app
        try:
            yield
        finally:
            local.app = previous

    def restore(self, backup, app, confirmation, include_data=False):
        with self.backups.lock:
            if confirmation != backup or type(include_data) is not bool:
                raise Error("App-Wiederherstellung zuerst bestätigen.")
            snapshot = self.inspect(app)
            if any(self.active(item) for item in snapshot["containers"].values()):
                raise Error("Vor der Wiederherstellung das gesamte App-Paket stoppen.", 409)
            manifest = self.backups.manifest(backup)
            if include_data and app not in manifest.get("app_data", []):
                raise Error("Die Sicherung enthält keine Nutzdaten dieser App.")
            self.backups.verify(backup)
            metadata = self.metadata(backup, app)
            options = validate_options(app, metadata["options"])
            record = snapshot["record"]
            from .host import pwd
            owner = pwd.getpwnam("titan-files")
            restored = compose(app, str(snapshot["control"]), owner.pw_uid, owner.pw_gid, record["port"], record["data"],
                               options, record.get("network"), record.get("hardware"), config_path=record.get("config_path"))
            references = {key: service["image"] for key, service in snapshot["definition"]["services"].items()}
            images = {key: item["Image"] for key, item in snapshot["containers"].items()}
            if (definition_digest(restored) != metadata["definition_digest"] or
                    references != metadata["image_references"] or images != metadata["images"] or
                    not self.local_images_match(references, images)):
                raise Error("App-Vorlage, Images oder Einstellungen passen nicht zur Sicherung. Wiederherstellung über einen Versionswechsel ist gesperrt.", 409)
            token, staged, switched = secrets.token_hex(8), [], []
            recovery = self.host.directory / ("app-restore-recovery-" + token)
            recovery.mkdir(mode=0o700)
            atomic_json(recovery / "options.json", snapshot["options"])
            atomic_json(recovery / "compose.json", snapshot["definition"])
            marker = snapshot["control"] / "restore-pending.json"
            marker_written = False
            try:
                for kind in ("config", "data") if include_data else ("config",):
                    destination = snapshot[kind]
                    stage_name = ".titan-restore-" + token + "-" + kind
                    old_name = ".titan-before-restore-" + token + "-" + kind
                    with self.backups._data_fd(destination.parent) as parent:
                        os.mkdir(stage_name, 0o700, dir_fd=parent)
                    stage = destination.parent / stage_name
                    staged.append((destination, stage, old_name))
                    self.backups._extract(backup, stage, lambda parts, kind=kind: parts[:3] == ("apps", app, kind), trim=3, preserve=True)
                # Recheck after a potentially lengthy extraction, before replacing
                # anything. Host dispatch holds the exclusive maintenance gate.
                checked = self.inspect(app)
                if any(self.active(item) for item in checked["containers"].values()):
                    raise Error("App wurde während der Vorbereitung gestartet; Wiederherstellung abgebrochen.", 409)
                atomic_json(recovery / "recovery.json", {"app": app, "backup": backup,
                    "paths": [{"current": str(path), "previous": str(path.parent / old)} for path, _, old in staged]})
                atomic_json(marker, {"recovery": str(recovery), "backup": backup})
                marker_written = True
                # Old containers still hold the old environment. Remove only
                # verified, stopped package members before changing credentials.
                self.host._app_stop_or_remove(app, "remove", unregister=False)
                for destination, stage, old_name in staged:
                    with self.backups._data_fd(destination.parent) as parent:
                        with self.backups._data_fd(destination):
                            os.rename(destination.name, old_name, src_dir_fd=parent, dst_dir_fd=parent)
                        switched.append((destination, stage, old_name))
                        os.rename(stage.name, destination.name, src_dir_fd=parent, dst_dir_fd=parent)
                        os.fsync(parent)
                atomic_json(snapshot["control"] / "options.json", options)
                atomic_json(snapshot["control"] / "compose.json", restored)
                self.host._app_patch_record(app, {"definition_digest": definition_digest(restored), "package_initialized": False})
                # Existing stopped containers still carry their previous env.
                # Recreate from the trusted recipe, without starting services.
                with self.trusted_restore(app):
                    self.host.docker(app, "create", "--force-recreate", "--pull", "never")
                    recreated = self.inspect(app)
                    if {key: member["Image"] for key, member in recreated["containers"].items()} != images:
                        raise Error("App-Images haben sich bei der Wiederherstellung geändert.", 409)
                self.host._app_patch_record(app, {"definition_digest": definition_digest(restored), "package_initialized": False,
                    "phase": "ready", "last_error": "", "last_restore_recovery": str(recovery)})
                marker.unlink()
            except Exception:
                if not marker_written:
                    raise Error("App-Wiederherstellung konnte nicht vorbereitet werden. Bisherige App-Daten bleiben unverändert. Recovery-Verzeichnis: " + str(recovery), 503) from None
                failed = False
                try:
                    self.host._app_stop_or_remove(app, "remove", unregister=False)
                except Exception:
                    failed = True
                for destination, stage, old_name in reversed(switched):
                    try:
                        with self.backups._data_fd(destination.parent) as parent:
                            if destination.exists():
                                os.rename(destination.name, stage.name, src_dir_fd=parent, dst_dir_fd=parent)
                            os.rename(old_name, destination.name, src_dir_fd=parent, dst_dir_fd=parent)
                    except Exception:
                        failed = True
                try:
                    atomic_json(snapshot["control"] / "options.json", snapshot["options"])
                    atomic_json(snapshot["control"] / "compose.json", snapshot["definition"])
                    self.host._app_patch_record(app, {"definition_digest": definition_digest(snapshot["definition"]),
                        "package_initialized": record.get("package_initialized", False)})
                    if not failed:
                        with self.trusted_restore(app):
                            self.host.docker(app, "create", "--force-recreate", "--pull", "never")
                            recovered = self.inspect(app)
                            if {key: member["Image"] for key, member in recovered["containers"].items()} != images:
                                raise Error("Vorherige App-Images konnten nicht wiederhergestellt werden.", 503)
                except Exception:
                    failed = True
                try:
                    self.host._app_patch_record(app, {"phase": "failed", "last_restore_recovery": str(recovery),
                        "last_error": "App-Wiederherstellung fehlgeschlagen; Recovery-Verzeichnis prüfen."})
                except Exception:
                    failed = True
                if not failed:
                    try:
                        marker.unlink()
                    except OSError:
                        failed = True
                raise Error("App-Wiederherstellung fehlgeschlagen. " + ("Automatische Rücksetzung unvollständig; " if failed else "Vorheriger Stand wieder eingesetzt; ") +
                            "App bleibt gestoppt. Recovery-Verzeichnis: " + str(recovery), 503) from None
            return {"ok": True, "app": app, "kept_stopped": True, "include_data": include_data, "recovery": str(recovery),
                    "message": "App-Konfiguration und Zugangsdaten wiederhergestellt" + (" einschließlich Nutzdaten" if include_data else "") +
                    ". Die App bleibt gestoppt. Der vorherige Stand bleibt für die lokale Rücksetzung erhalten."}

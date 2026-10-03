import argparse
import base64
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import secrets
import select
import socket
import threading
import time
import urllib.parse
from . import __version__, __release_stage__
from .catalog import APPS, catalog
from .core import Error, Jobs, Store, identifier, integer, password_hash
from .demo import Demo
from .rpc import AgentClient
from .users import Users
from .user_deletion import validate_removal
from .dashboard_layout import load_layout, save_layout
from . import launcher_layout
from .diagnostics import report as diagnostics_report
from .terminal_http import TerminalHTTPMixin, TerminalApplicationMixin, terminal_owner

WEB = Path(__file__).parent / "web"
MUTATIONS = {"service_action", "service_create", "component_install", "volume_create", "volume_mount", "pool_create", "dataset_create", "snapshot_create", "scrub", "share_create", "share_update", "share_remove",
             "app_store_add", "app_store_remove", "app_store_refresh", "app_store_toggle", "app_install", "app_action", "app_network_create", "app_network_remove", "vm_usb_update", "vm_create", "vm_action", "vm_update", "vm_media", "iso_remove", "vm_remove", "vm_backup", "vm_restore",
             "system_updates", "update_install", "update_rollback", "system_reboot", "system_disk_grow", "backup_create", "backup_verify", "backup_restore",
             "backup_config_export", "backup_config_restore", "monitoring_check"}
FILE_ACTIONS = {"mkdir", "upload", "rename", "trash", "trash_list", "restore", "copy", "move", "read", "write", "create", "delete"}


def validate_system_disk_growth(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"expected_revision", "confirmation"}:
        raise Error("Aktueller Systemdisk-Stand und Bestätigung sind erforderlich.")
    revision = arguments["expected_revision"]
    if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{64}", revision):
        raise Error("Ungültiger Systemdisk-Stand. Speicheransicht aktualisieren.")
    if arguments["confirmation"] != "ERWEITERN":
        raise Error("Bitte ERWEITERN zur Bestätigung eingeben.")


class Application(TerminalApplicationMixin):
    def __init__(self, directory, demo=False, origin=None):
        self.demo = demo
        self.origin = origin
        self.store = Store(directory)
        self.jobs = Jobs(self.store)
        self.agent = Demo(Path(directory) / "demo-files") if demo else AgentClient()
        if demo and not self.store.users():
            self.store.create_user("demo", secrets.token_urlsafe(24), "admin", "titan-files")
            for name in ("patrick", "familie"):
                self.store.create_user(name, secrets.token_urlsafe(24), "user", name)
        self.users = Users(self.store, self.agent, demo)
        self.attempts = {}
        self.attempt_lock = threading.Lock()
        self.setup_lock = threading.Lock()
        self.terminal_stream_lock = threading.Lock()
        self.terminal_streams = set()
        self.setup_csrf = secrets.token_urlsafe(32)
        self.update_lock = threading.Lock()
        self.stop = threading.Event()
        self.initialize_terminals()

    def admin_action(self, actor, operation, arguments):
        if operation == "update_install":
            return self.install_update(actor, arguments["expected_version"])
        if operation in ("update_rollback", "system_reboot"):
            return self.system_action(actor, operation, arguments)
        # Queued jobs may outlive an account's permissions; check them again when
        # executing, not only when accepting the HTTP request.
        current = self.store.user_record(actor)
        if not current["enabled"] or current["role"] != "admin":
            raise Error("Administratorrechte sind nicht mehr gültig.", 403)
        if operation == "system_disk_grow":
            validate_system_disk_growth(arguments)
        return self.agent.call(operation, **arguments)

    def system_action(self, actor, operation, arguments):
        from .updates import validate_system_action
        with self.update_lock:
            current = self.store.user_record(actor)
            if not current["enabled"] or current["role"] != "admin":
                raise Error("Administratorrechte sind nicht mehr gültig.", 403)
            validate_system_action(operation, arguments)
            settings = self.store.settings()
            return self.agent.call(operation, repository=settings["repository"], **arguments)

    def save_settings(self, value, actor=None):
        with self.update_lock:
            if actor is not None:
                current = self.store.user_record(actor)
                if not current["enabled"] or current["role"] != "admin":
                    raise Error("Administratorrechte sind nicht mehr gültig.", 403)
            previous = self.store.settings()
            settings = self.store.save_settings(value)
            if any(settings[key] != previous[key] for key in ("repository", "channel")):
                self.store.set_config("update", {"current": __version__, "current_stage": __release_stage__,
                    "repository": settings["repository"], "channel": settings["channel"], "available": False,
                    "message": "Update-Quelle geändert. Bitte erneut prüfen; die installierte Version bleibt erhalten."})
            return settings

    def install_update(self, actor, expected_version, automatic=False):
        with self.update_lock:
            settings = self.store.settings()
            if automatic:
                if settings["installation"] != "automatic" or not self.store.users():
                    raise Error("Automatische Installation ist nicht mehr aktiviert.", 409)
                current = time.localtime()
                if current.tm_wday != settings["window_day"] or current.tm_hour != settings["window_hour"]:
                    raise Error("Der Auftrag liegt außerhalb des aktuellen Update-Zeitfensters.", 409)
            else:
                current = self.store.user_record(actor)
                if not current["enabled"] or current["role"] != "admin":
                    raise Error("Administratorrechte sind nicht mehr gültig.", 403)
            return self.agent.call("update_install", repository=settings["repository"],
                                   channel=settings["channel"], expected_version=expected_version)

    def housekeeping(self):
        while not self.stop.wait(60):
            if self.demo or not self.store.users():
                continue
            for operation in ("monitoring_check", "backup_scheduled"):
                try:
                    self.agent.call(operation)
                except Exception as exc:
                    self.store.audit("system", operation, str(exc))

    def rate_limit(self, address):
        with self.attempt_lock:
            now = time.time()
            self.attempts = {key: [stamp for stamp in value if stamp > now - 300]
                             for key, value in self.attempts.items() if any(stamp > now - 300 for stamp in value)}
            attempts = self.attempts.setdefault(address, [])
            if len(attempts) >= 10:
                raise Error("Zu viele Anmeldeversuche. Bitte fünf Minuten warten.", 429)
            attempts.append(now)

    def update_check(self):
        with self.update_lock:
            settings = self.store.settings()
            result = self.agent.call("update_check", repository=settings["repository"], channel=settings["channel"])
            self.store.set_config("update", result)
            return result

    def updater(self):
        while not self.stop.wait(60):
            settings = self.store.settings()
            if not self.store.users() and not self.demo:
                continue
            cached = self.store.config("update", {})
            interval = 86400 if settings["check_interval"] == "daily" else 604800
            try:
                if settings["auto_check"] and time.time() - cached.get("checked", 0) >= interval:
                    cached = self.update_check()
                current = time.localtime()
                attempt = f"{current.tm_year}-{current.tm_yday}-{cached.get('latest')}"
                if (not self.demo and settings["installation"] == "automatic" and cached.get("available")
                        and cached.get("signed") and current.tm_wday == settings["window_day"]
                        and current.tm_hour == settings["window_hour"]
                        and self.store.config("auto_update_attempt") != attempt):
                    self.store.set_config("auto_update_attempt", attempt)
                    expected = cached["latest"]
                    self.jobs.submit("system", "update_install",
                        lambda expected=expected: self.install_update("system", expected, automatic=True))
            except Exception as exc:
                self.store.audit("system", "update_check", str(exc))


class Handler(TerminalHTTPMixin, BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    @property
    def app(self):
        return self.server.app

    def log_message(self, fmt, *args):
        # Log route only, never query strings, session values or bodies.
        logging.info("%s %s", self.command, urllib.parse.urlsplit(self.path).path)

    def user(self):
        if self.app.demo:
            current = self.app.store.user_record("demo")
            return {"name": current["name"], "role": current["role"], "system_user": current["system_user"],
                    "csrf": "demo-only"} if current["enabled"] else None
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        return self.app.store.session(cookie["titan_session"].value) if "titan_session" in cookie else None

    def require_user(self, admin=False, mutation=False):
        user = self.user()
        if not user:
            raise Error("Bitte anmelden.", 401)
        if admin and user["role"] != "admin":
            raise Error("Administratorrechte erforderlich.", 403)
        if mutation:
            import hmac
            if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), user["csrf"]):
                raise Error("Sicherheitsprüfung fehlgeschlagen. Bitte Seite neu laden.", 403)
        return user

    def origin_check(self):
        origin = self.headers.get("Origin")
        if origin:
            expected = self.app.origin or "http://" + self.headers.get("Host", "")
            if origin != expected:
                raise Error("Anfrage von fremder Website abgelehnt.", 403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise Error("Anfrage von fremder Website abgelehnt.", 403)

    def send_headers(self, status, size, content_type="application/json; charset=utf-8", extra=None, style_nonce=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'" + (" 'nonce-" + style_nonce + "'" if style_nonce else "") + "; "
                         "img-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'none'; "
                         "base-uri 'none'; frame-ancestors 'self'; form-action 'self'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def reply(self, value, status=200, extra=None):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_headers(status, len(data), extra=extra)
        self.wfile.write(data)

    def body(self):
        length = integer(self.headers.get("Content-Length", "0"), 1, 8 * 1024 * 1024)
        try:
            value = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeError):
            raise Error("Ungültige JSON-Anfrage.")
        if not isinstance(value, dict):
            raise Error("JSON-Objekt erforderlich.")
        return value

    def safe(self, function):
        try:
            if self.app.origin:
                host = urllib.parse.urlsplit(self.app.origin).netloc
                if self.headers.get("Host") != host:
                    raise Error("Ungültiger Hostname.", 403)
            function()
        except Error as exc:
            self.reply({"error": str(exc)}, exc.status)
        except (KeyError, ValueError, TypeError) as exc:
            self.reply({"error": "Ungültige oder fehlende Eingabe."}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            logging.exception("Request failed")
            self.reply({"error": "Interner Fehler. Details im Dienstprotokoll."}, 500)

    def do_GET(self):
        self.safe(self.get)

    def do_POST(self):
        self.safe(self.post)

    def get(self):
        parts = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parts.path)
        query = dict(urllib.parse.parse_qsl(parts.query))
        if path == "/api/session":
            setup_required = not self.app.store.users() and not self.app.demo
            return self.reply({"user": self.user(), "setup_required": setup_required,
                               **({"setup_csrf": self.app.setup_csrf} if setup_required else {}),
                               "demo": self.app.demo, "version": __version__, "stage": __release_stage__})
        if path.startswith("/api/"):
            user = self.require_user()
            if path == "/api/launcher-layout":
                return self.reply(launcher_layout.load(self.app.store, user["name"]))
            if path == "/api/dashboard-layout":
                return self.reply(load_layout(self.app.store, user["name"]))
            if path == "/api/shares":
                shares = self.app.agent.call("shares")
                return self.reply([item for item in shares if user["role"] == "admin" or user["system_user"] in item["readers"] + item["writers"]])
            if path == "/api/files":
                return self.reply(self.file_call(user, share=query["share"], action="list",
                    path=query.get("path", ""), offset=integer(query.get("offset", 0), 0, 2**31-1),
                    limit=integer(query.get("limit", 200), 1, 500), search=query.get("search", "")))
            if path == "/api/file":
                return self.download(user, query)
            if path == "/api/jobs":
                return self.reply(self.app.store.jobs(None if user["role"] == "admin" else user["name"]))
            self.require_user(admin=True)
            if path == '/api/diagnostics':
                if query not in ({}, {'download': '1'}):
                    raise Error('Ungültige Diagnoseoption.')
                return self.reply(diagnostics_report(self.app.agent, self.app.demo), extra={
                    'Content-Disposition': 'attachment; filename="titan-diagnostics.json"'} if query else None)
            if path == '/api/terminal/output':
                self.origin_check()
                pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
                if len(pairs) != 1 or pairs[0][0] != 'id':
                    raise Error('Genau eine Terminalsitzung angeben.')
                return self.terminal_stream(user, dict(pairs))
            if path == '/api/services':
                if query:
                    raise Error('Dienstübersicht unterstützt keine zusätzlichen Optionen.')
                return self.reply(self.app.agent.call('services'))
            if path == '/api/service-details':
                if set(query) - {'service', 'tail'} or 'service' not in query:
                    raise Error('Dienstname angeben.')
                return self.reply(self.app.agent.call('service_details', service=query['service'], tail=integer(query.get('tail', 100), 1, 500)))
            if path == "/api/managed-shares":
                return self.reply(self.app.agent.call("shares"))
            if path == "/api/shares/access":
                if query:
                    raise Error("Freigabe-Zugang unterstützt keine zusätzlichen Optionen.")
                return self.reply(self.app.agent.call("shares_access"))
            if path == "/api/smart":
                return self.reply(self.app.agent.call("smart", disk=query["disk"]))
            if path == "/api/status":
                return self.reply({**self.app.agent.call("status"), "version": __version__, "demo": self.app.demo})
            if path == "/api/app-stores":
                return self.reply(self.app.agent.call("app_stores"))
            if path == "/api/vm-usb":
                return self.reply(self.app.agent.call("vm_usb", vm=query["vm"]))
            if path == "/api/catalog":
                if self.app.demo:
                    return self.reply({"apps": [{**{key:value for key,value in item.items() if key != "environment"}, "install_schema": [{key:value for key,value in field.items() if key != "env"} for field in item.get("install_schema", [])], "id": name, "version": "latest", "documentation": item.get("documentation") or f"https://docs.linuxserver.io/images/docker-{item.get('upstream_name', name)}/"} for name, item in APPS.items()], "source": "LinuxServer.io"})
                return self.reply(self.app.agent.call("catalog"))
            if path == "/api/app-details":
                return self.reply(self.app.agent.call("app_details", app=query["app"], tail=integer(query.get("tail", 150), 1, 500)))
            if path == "/api/users":
                accounts = [account for account in self.app.agent.call("accounts", smb_status=True) if not account.get("removed")]
                return self.reply({"web": self.app.store.users(), "system": accounts, "service_user": "titan-files"})
            if path == "/api/backup/settings":
                return self.reply(self.app.agent.call("backup_settings"))
            if path == "/api/backups":
                listing = self.app.agent.call("backups")
                result = {"items": listing} if isinstance(listing, list) else listing
                if not isinstance(result, dict):
                    raise Error("Ungültige Backup-Antwort.", 503)
                return self.reply({**result, "settings": self.app.agent.call("backup_settings")})
            if path == "/api/monitoring":
                return self.reply(self.app.agent.call("monitoring"))
            if path == "/api/settings": return self.reply(self.app.store.settings())
            if path == "/api/vm-image-info":
                if set(query) != {"path"}:
                    raise Error("Ein Image-Dateipfad ist erforderlich.")
                return self.reply(self.app.agent.call("vm_image_details", path=query["path"]))
            if path == "/api/updates/progress":
                if query:
                    raise Error("Fortschritt unterstützt keine zusätzlichen Optionen.")
                return self.reply(self.app.agent.call("update_progress"), extra={"Cache-Control": "no-store"})
            if path == "/api/updates/system":
                if query:
                    raise Error("Systemstatus unterstützt keine zusätzlichen Optionen.")
                return self.reply(self.app.agent.call("system_updates"))
            if path == "/api/system-disk":
                if query:
                    raise Error("Systemdisk-Status unterstützt keine zusätzlichen Optionen.")
                return self.reply(self.app.agent.call("system_disk"), extra={"Cache-Control": "no-store"})
            if path == "/api/updates": return self.reply(self.app.store.config("update", {
                "current": __version__, "current_stage": __release_stage__, "channel": self.app.store.settings()["channel"], "available": False}))
            if path == "/api/logs": return self.reply(self.app.store.logs())
            if path == "/api/vnc":
                self.origin_check()
                return self.websocket(query["vm"])
            operations = {"/api/storage-locations": "storage_locations", "/api/components": "components", "/api/storage": "storage", "/api/apps": "apps", "/api/app-networks": "app_networks", "/api/vms": "vms",
                          "/api/snapshots": "snapshots", "/api/vm-options": "vm_options", "/api/isos": "isos", "/api/iso-library": "iso_library"}
            if path in operations:
                return self.reply(self.app.agent.call(operations[path]))
            raise Error("API nicht gefunden.", 404)
        if path.startswith("/novnc/"):
            self.require_user(admin=True)
            return self.static(Path("/usr/share/novnc"), path[7:])
        self.static(WEB, "index.html" if path == "/" else path.lstrip("/"))

    def static(self, root, relative):
        target = (root / relative).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file():
            raise Error("Datei nicht gefunden.", 404)
        data = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        nonce = None
        if target == (WEB / 'index.html').resolve():
            nonce = secrets.token_urlsafe(24)
            data = data.replace(b'__TITAN_STYLE_NONCE__', nonce.encode())
        self.send_headers(200, len(data), content_type, style_nonce=nonce)
        self.wfile.write(data)

    def post(self):
        self.origin_check()
        path = urllib.parse.urlsplit(self.path).path
        body = self.body()
        if path == "/api/setup":
            self.app.rate_limit(self.client_address[0])
            if self.app.demo:
                raise Error("Demo ist bereits eingerichtet.")
            expected = self.app.origin or "http://" + self.headers.get("Host", "")
            if self.headers.get("Origin") != expected or self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise Error("Ersteinrichtung nur über die Titan-Weboberfläche. Bitte die Seite öffnen.", 403)
            import hmac
            if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), self.app.setup_csrf):
                raise Error("Einrichtungsseite wurde neu gestartet. Bitte die Seite neu laden.", 403)
            if set(body) != {"name", "password"}:
                raise Error("Für die Ersteinrichtung Benutzername und Passwort angeben.")
            self.app.users.setup(body["name"], body["password"])
            self.app.store.audit(body["name"], "setup", "Administrator angelegt")
            return self.reply({"ok": True})
        if path == "/api/login":
            self.app.rate_limit(self.client_address[0])
            token, csrf = self.app.store.login(body["name"], body["password"])
            cookie = f"titan_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200"
            if not self.app.demo:
                cookie += "; Secure"
            self.app.store.audit(body["name"], "login")
            return self.reply({"ok": True, "csrf": csrf}, extra={"Set-Cookie": cookie})
        user = self.require_user(mutation=True)
        if path == "/api/launcher-layout":
            return self.reply(launcher_layout.save(self.app.store, user["name"], body))
        if path == "/api/dashboard-layout":
            return self.reply(save_layout(self.app.store, user["name"], body))
        if path == "/api/logout":
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            if "titan_session" in cookie:
                self.app.store.logout(cookie["titan_session"].value)
            self.app.close_terminal_owner(terminal_owner(user))
            return self.reply({"ok": True}, extra={"Set-Cookie": "titan_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0; Secure"})
        if path == "/api/files":
            if body.get("action") not in FILE_ACTIONS:
                raise Error("Ungültige Dateiaktion.")
            if set(body) - {"share", "path", "action", "offset", "size", "limit", "search", "data", "destination", "trash_name", "destination_share", "revision", "confirmation_path"}:
                raise Error("Unbekannte Dateioption.")
            result = self.file_call(user, **body)
            self.app.store.audit(user["name"], "file_" + body["action"], body.get("path", ""))
            return self.reply(result)
        if path == "/api/password":
            if set(body) != {"current_password", "password"}:
                raise Error("Aktuelles und neues Passwort sind erforderlich.")
            password_hash(body["password"])
            return self.reply(self.app.jobs.submit(user["name"], "password_change",
                lambda: self.app.users.password(user["name"], body["current_password"], body["password"]), security=True), 202)
        self.require_user(admin=True)
        if path == '/api/terminal':
            return self.terminal_post(user, body)
        if path == "/api/components/install":
            if set(body) != {"component"} or type(body["component"]) is not str or body["component"] not in ("all", "docker", "vms"):
                raise Error("Docker, VMs oder alle Komponenten auswählen.")
            if any(item["action"] == "component_install" and item["status"] in ("queued", "running") for item in self.app.store.jobs()):
                raise Error("Eine Komponenteninstallation läuft bereits.", 409)
            return self.reply(self.app.jobs.submit(user["name"], "component_install",
                lambda: self.app.admin_action(user["name"], "component_install", body)), 202)
        if path == "/api/backup/settings":
            result = self.app.agent.call("backup_save_settings", **body)
            self.app.store.audit(user["name"], "backup_settings")
            return self.reply(result)
        if path == "/api/monitoring/ack":
            if set(body) != {"id"}:
                raise Error("Meldungs-ID erforderlich.")
            result = self.app.agent.call("monitoring_ack", id=body["id"])
            self.app.store.audit(user["name"], "monitoring_ack")
            return self.reply(result)
        if path == "/api/settings":
            settings = self.app.save_settings(body, actor=user["name"])
            self.app.store.audit(user["name"], "settings")
            return self.reply(settings)
        if path == "/api/updates/check":
            return self.reply(self.app.jobs.submit(user["name"], "update_check", self.app.update_check), 202)
        if path == "/api/users":
            if set(body) != {"name", "password", "role"}:
                raise Error("Benutzername, Passwort und Rolle sind erforderlich.")
            name = identifier(body["name"])
            password_hash(body["password"])
            if body.get("role") not in ("admin", "user") or name in {item["name"] for item in self.app.store.users()}:
                raise Error("Rolle ungültig oder Benutzer existiert bereits.")
            def create():
                return self.app.users.create(user["name"], name, body["password"], body["role"])
            return self.reply(self.app.jobs.submit(user["name"], "account_create", create), 202)
        if path == "/api/users/update":
            if "name" not in body or set(body) - {"name", "password", "role", "enabled"} or len(body) < 2:
                raise Error("Ungültige Benutzeränderung.")
            name = identifier(body["name"])
            changes = {key: value for key, value in body.items() if key != "name"}
            self.app.store.validate_user_update(name, **changes)
            if name == user["name"] and changes.get("enabled") is False:
                raise Error("Das eigene Konto kann nicht gesperrt werden.", 409)
            return self.reply(self.app.jobs.submit(user["name"], "user_update",
                lambda: self.app.users.update(user["name"], name, **changes), security=True), 202)
        if path == "/api/users/remove":
            if set(body) != {"name", "confirmation"}:
                raise Error("Benutzername und Bestätigung sind erforderlich.")
            name = identifier(body["name"])
            if body["confirmation"] != name:
                raise Error("Der Benutzername zur Bestätigung stimmt nicht überein.")
            validate_removal(self.app.store, user["name"], name)
            return self.reply(self.app.jobs.submit(user["name"], "user_remove",
                lambda: self.app.users.remove(user["name"], name, body["confirmation"]), security=True), 202)
        if path == "/api/isos/cancel":
            if set(body) != {"upload_id"}:
                raise Error("Upload-Kennung erforderlich.")
            return self.reply(self.app.agent.call("iso_cancel", **body))
        if path == "/api/isos":
            if not {"name", "offset", "data", "total"} <= set(body) or set(body) - {"name", "offset", "data", "total", "upload_id"}:
                raise Error("Ungültige ISO-Upload-Optionen.")
            return self.reply(self.app.agent.call("iso_upload", **body))
        if path == "/api/actions":
            operation = body["operation"]
            arguments = body.get("arguments", {})
            if operation not in MUTATIONS or not isinstance(arguments, dict):
                raise Error("Aktion nicht erlaubt.")
            if operation == "update_install":
                if set(arguments) != {"expected_version"}:
                    raise Error("Erwartete Update-Version erforderlich.")
            if operation in ("update_rollback", "system_reboot"):
                from .updates import validate_system_action
                validate_system_action(operation, arguments)
            if operation == "system_disk_grow":
                validate_system_disk_growth(arguments)
            return self.reply(self.app.jobs.submit(user["name"], operation,
                              lambda: self.app.admin_action(user["name"], operation, arguments)), 202)
        raise Error("API nicht gefunden.", 404)

    def file_call(self, user, **arguments):
        if arguments.get("share") == "@system":
            if user["role"] != "admin":
                raise Error("Systemdateizugriff erfordert Administratorrechte.", 403)
            arguments.pop("share")
            return self.app.agent.call("system_file", **arguments)
        if arguments.get("action") == "delete" and user["role"] != "admin":
            raise Error("Diese Dateiaktion erfordert Administratorrechte.", 403)
        if user["role"] == "admin":
            return self.app.agent.call("admin_file", **arguments)
        return self.app.agent.call("file", user=user["system_user"], **arguments)

    def download(self, user, query):
        first = self.file_call(user, share=query["share"],
                                    action="read", path=query["path"], offset=0, size=1)
        total = first["total"]
        start, end, status = 0, total - 1, 200
        range_header = self.headers.get("Range")
        if range_header:
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header)
            if not match:
                raise Error("Ungültiger Dateibereich.", 416)
            start = int(match[1])
            end = min(int(match[2]) if match[2] else total - 1, total - 1)
            if start > end or start >= total:
                raise Error("Dateibereich außerhalb der Datei.", 416)
            status = 206
        mime = mimetypes.guess_type(first["name"])[0] or "application/octet-stream"
        inline = mime in {"image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf", "text/plain",
                          "video/mp4", "video/webm", "audio/mpeg", "audio/wav", "audio/ogg"} and query.get("preview") == "1"
        headers = {"Accept-Ranges": "bytes", "Content-Disposition": ("inline" if inline else "attachment") +
                   "; filename*=UTF-8''" + urllib.parse.quote(first["name"])}
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{total}"
        self.send_headers(status, max(0, end - start + 1), mime if inline else "application/octet-stream", headers)
        offset = start
        while offset <= end:
            if not self.user():
                self.close_connection = True
                break
            result = self.file_call(user, share=query["share"], action="read",
                                         path=query["path"], offset=offset, size=min(4 * 1024 * 1024, end - offset + 1))
            data = base64.b64decode(result["data"])
            if not data:
                self.close_connection = True
                break
            self.wfile.write(data)
            offset += len(data)

    def websocket(self, vm):
        if self.headers.get("Upgrade", "").lower() != "websocket":
            raise Error("WebSocket-Verbindung erforderlich.")
        # Require an Origin on browser console connections, in addition to the session.
        if not self.headers.get("Origin"):
            raise Error("Origin fehlt.", 403)
        port = self.app.agent.call("console", vm=vm)["port"]
        with socket.create_connection(("127.0.0.1", port), timeout=15) as upstream:
            allowed = ("Upgrade", "Connection", "Sec-WebSocket-Key", "Sec-WebSocket-Version", "Sec-WebSocket-Protocol", "Origin")
            lines = ["GET / HTTP/1.1", f"Host: 127.0.0.1:{port}"]
            lines += [f"{key}: {self.headers[key]}" for key in allowed if self.headers.get(key)]
            upstream.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
            upstream.settimeout(None)
            self.close_connection = True
            self.wfile.flush()
            last_activity = time.monotonic()
            while True:
                current = self.user()
                if not current or current["role"] != "admin":
                    return
                readable, _, _ = select.select([upstream, self.connection], [], [], 5)
                if not readable:
                    if time.monotonic() - last_activity > 300:
                        break
                    continue
                last_activity = time.monotonic()
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    (self.connection if source is upstream else upstream).sendall(data)


def main():
    parser = argparse.ArgumentParser(description="Titan web service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--data", default="/var/lib/titan")
    parser.add_argument("--origin", default=os.environ.get("TITAN_ORIGIN"))
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    if not args.demo and not args.origin:
        parser.error("Produktivbetrieb benötigt --origin https://hostname:5000 und einen TLS-Reverse-Proxy.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = Application(args.data, args.demo, args.origin)
    threading.Thread(target=app.updater, daemon=True).start()
    threading.Thread(target=app.housekeeping, daemon=True).start()
    with ThreadingHTTPServer((args.host, args.port), Handler) as server:
        server.app = app
        server.daemon_threads = True
        server.timeout = 30
        logging.info("Titan %s listening on %s:%s; demo=%s", __version__, args.host, args.port, args.demo)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            app.stop.set()
            app.close_all_terminals()
            if app.demo:
                app.agent.terminals.close_all()


if __name__ == "__main__":
    main()

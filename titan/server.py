import argparse
import base64
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import ipaddress
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
from .core import configuration_lock, job_resources, Error, Jobs, Store, identifier, integer, password_hash, user_profile_text
from .demo import Demo
from .rpc import AgentClient
from .users import Users
from .identity import Identity, permissions, require_application
from .security import Security
from .identity_http import IdentityHTTPMixin, operation_application
from .office_gateway import OfficeApplicationMixin, OfficeHTTPMixin
from .user_deletion import validate_removal
from .dashboard_layout import load_layout, save_layout
from . import launcher_layout
from .diagnostics import report as diagnostics_report
from .terminal_http import TerminalHTTPMixin, TerminalApplicationMixin, terminal_owner
from .root_access import RootAccessApplicationMixin, RootAccessHTTPMixin

WEB = Path(__file__).parent / "web"
MUTATIONS = {"storage_preferences_save", "app_hardware", "docker_container_hardware", "docker_container_batch", "docker_container_create", "docker_container_action", "docker_image_pull", "docker_resource","service_action", "service_create", "component_install", "volume_create", "volume_mount", "pool_create", "dataset_create", "snapshot_create", "scrub", "share_create", "share_update", "share_user_permission", "share_remove",
             "app_store_add", "app_store_remove", "app_store_refresh", "app_store_toggle", "app_install", "app_action", "app_network_create", "app_network_remove", "vm_usb_update", "vm_create", "vm_action", "vm_update", "vm_disk_grow", "vm_media", "iso_remove", "vm_remove", "vm_backup", "vm_restore",
             "system_updates", "update_install", "update_rollback", "system_reboot", "system_shutdown", "system_disk_grow", "backup_create", "backup_verify", "backup_restore",
             "backup_config_export", "backup_config_restore", "monitoring_check", "smart_test", "storage_maintenance_save", "storage_maintenance_remove", "snapshot_restore", "snapshot_remove", "backup_restore_selection", "backup_app_restore", "notification_test", "package_repair", "package_update", "package_settings", "vm_clone", "vm_snapshot_create", "vm_snapshot_restore", "vm_snapshot_remove", "vm_disk_add", "vm_disk_remove", "vm_nic_add", "vm_nic_remove", "vm_guest_agent", "vm_guest_action"}
FILE_ACTIONS = {"mkdir", "upload", "rename", "trash", "trash_list", "restore", "copy", "move", "read", "write", "create", "create_document", "delete"}


def validate_update_kind(value="all"):
    if type(value) is not str or value not in ("all", "titan", "system"):
        raise Error("Titan oder System als Update-Bereich auswählen.")
    return value


def update_cache_key(kind):
    return "update" if kind == "all" else "update:" + kind


def validate_system_disk_growth(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"expected_revision", "confirmation"}:
        raise Error("Aktueller Systemdisk-Stand und Bestätigung sind erforderlich.")
    revision = arguments["expected_revision"]
    if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{64}", revision):
        raise Error("Ungültiger Systemdisk-Stand. Speicheransicht aktualisieren.")
    if arguments["confirmation"] != "ERWEITERN":
        raise Error("Bitte ERWEITERN zur Bestätigung eingeben.")


class Application(RootAccessApplicationMixin, OfficeApplicationMixin, TerminalApplicationMixin):
    def __init__(self, directory, demo=False, origin=None):
        self.demo = demo
        self._origin = origin
        self.store = Store(directory)
        self.jobs = Jobs(self.store)
        self.agent = Demo(Path(directory) / "demo-files") if demo else AgentClient()
        if demo and not self.store.users():
            self.store.create_user("demo", secrets.token_urlsafe(24), "admin", "titan-files")
            for name in ("patrick", "familie"):
                self.store.create_user(name, secrets.token_urlsafe(24), "user", name)
        self.users = Users(self.store, self.agent, demo)
        self.identity = Identity(self.store, self.agent, demo)
        self.security = Security(self.store, demo)
        self.attempts = {}
        self.attempt_lock = threading.Lock()
        self.setup_lock = threading.Lock()
        self.terminal_stream_lock = threading.Lock()
        self.terminal_streams = set()
        self.setup_csrf = secrets.token_urlsafe(32)
        self.update_lock = threading.Lock()
        self.stop = threading.Event()
        self.initialize_terminals()
        self.initialize_root_access()
        self.initialize_office()

    def trusted_origins(self):
        from .web_access import CONFIG, allowed_origins, read_config
        if not self.demo and CONFIG.exists():
            return allowed_origins(read_config(CONFIG))
        return {self._origin} if self._origin else set()

    @property
    def origin(self):
        from .web_access import CONFIG, origin, read_config
        if not self.demo and CONFIG.exists():
            config = read_config(CONFIG)
            return origin(config['host'], config['settings'])
        return self._origin

    @origin.setter
    def origin(self, value):
        self._origin = value

    def admin_action(self, actor, operation, arguments):
        if operation == "update_install":
            return self.install_update(actor, arguments["expected_version"],
                                       update_kind=arguments.get("update_kind", "all"))
        if operation in ("update_rollback", "system_reboot"):
            return self.system_action(actor, operation, arguments)
        # Queued jobs may outlive an account's permissions; check them again when
        # executing, not only when accepting the HTTP request.
        current = self.store.user_record(actor)
        application = operation_application(operation)
        if application:
            require_application(self.store, current, application)
        elif not current["enabled"] or current["role"] != "admin":
            raise Error("Administratorrechte sind nicht mehr gültig.", 403)
        if operation == "system_disk_grow":
            validate_system_disk_growth(arguments)
        if application == "backups" and current["role"] != "admin":
            from .backup_authorization import web_authorize
            current = web_authorize(self.store, self.agent, current, operation, arguments)
            return self.agent.call("delegated_backup", action=operation, user=current["system_user"], arguments=arguments)
        if operation == "share_remove":
            with configuration_lock(self.store.directory), self.store.lock:
                result = self.agent.call(operation, **arguments)
                policy = self.store.config("identity", {"schema": 1, "groups": [], "users": {}})
                for group in policy.get("groups", []):
                    group.get("shares", {}).pop(arguments["name"], None)
                for entry in policy.get("users", {}).values():
                    entry.get("shares", {}).pop(arguments["name"], None)
                self.store.set_config("identity", policy)
                return result
        if operation in ("share_user_permission", "share_update"):
            with configuration_lock(self.store.directory), self.store.lock:
                result = self.agent.call(operation, **arguments)
                policy = self.store.config("identity", {"schema": 1, "groups": [], "users": {}})
                for account in self.store.users():
                    if account["system_user"] == "titan-files":
                        continue
                    if operation == "share_user_permission" and account["system_user"] != arguments["user"]:
                        continue
                    permission = arguments["permission"] if operation == "share_user_permission" else "write" if account["system_user"] in arguments["writers"] else "read" if account["system_user"] in arguments["readers"] else "none"
                    policy["users"].setdefault(account["name"], {"applications": {}, "shares": {}})["shares"][arguments["name"]] = permission
                self.store.set_config("identity", policy)
                return result
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
                for kind in ("all", "titan", "system"):
                    self.store.set_config(update_cache_key(kind), {"current": __version__, "current_stage": __release_stage__,
                        "selection_kind": kind, "repository": settings["repository"], "channel": settings["channel"], "available": False,
                        "message": "Update-Quelle geändert. Bitte erneut prüfen; die installierte Version bleibt erhalten."})
            return settings

    def install_update(self, actor, expected_version, automatic=False, update_kind="all"):
        kind = validate_update_kind(update_kind)
        with self.update_lock:
            settings = self.store.settings()
            policy = settings if kind == "all" else settings["update_streams"][kind]
            if automatic:
                if policy["installation"] != "automatic" or not self.store.users():
                    raise Error("Automatische Installation ist nicht mehr aktiviert.", 409)
                current = time.localtime()
                if current.tm_wday != policy["window_day"] or current.tm_hour != policy["window_hour"]:
                    raise Error("Der Auftrag liegt außerhalb des aktuellen Update-Zeitfensters.", 409)
            else:
                current = self.store.user_record(actor)
                if not current["enabled"] or current["role"] != "admin":
                    raise Error("Administratorrechte sind nicht mehr gültig.", 403)
            arguments = {"repository": settings["repository"], "channel": settings["channel"], "expected_version": expected_version}
            if kind != "all":
                arguments["update_kind"] = kind
            return self.agent.call("update_install", **arguments)

    def housekeeping(self):
        while not self.stop.wait(60):
            if self.demo or not self.store.users():
                continue
            for operation in ("status", "monitoring_check", "backup_scheduled", "storage_maintenance_scheduled"):
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

    def update_check(self, update_kind="all"):
        kind = validate_update_kind(update_kind)
        with self.update_lock:
            settings = self.store.settings()
            arguments = {"repository": settings["repository"], "channel": settings["channel"]}
            if kind != "all":
                arguments["update_kind"] = kind
            result = self.agent.call("update_check", **arguments)
            self.store.set_config(update_cache_key(kind), result)
            return result

    def updater_tick(self):
        # Feature and Debian maintenance bundles use one offer, one policy and
        # one signed A/B installation path. Separate kind queries are retained
        # solely for backwards-compatible API clients.
        settings = self.store.settings()
        if not self.store.users() and not self.demo:
            return
        cached = self.store.config("update", {})
        interval = 86400 if settings["check_interval"] == "daily" else 604800
        if settings["auto_check"] and time.time() - cached.get("checked", 0) >= interval:
            cached = self.update_check()
        current = time.localtime()
        attempt = f"{current.tm_year}-{current.tm_yday}-{cached.get('latest')}"
        if (not self.demo and settings["installation"] == "automatic" and cached.get("available")
                and cached.get("signed") and current.tm_wday == settings["window_day"]
                and current.tm_hour == settings["window_hour"]
                and self.store.config("auto_update_attempt") != attempt
                and not any(job["action"] == "update_install" and job["status"] in ("queued", "running") for job in self.store.jobs())):
            self.store.set_config("auto_update_attempt", attempt)
            expected = cached["latest"]
            self.jobs.submit("system", "update_install", lambda expected=expected:
                self.install_update("system", expected, automatic=True))

    def updater(self):
        while not self.stop.wait(60):
            try:
                self.updater_tick()
            except Exception as exc:
                self.store.audit("system", "update_check", str(exc))


class Handler(RootAccessHTTPMixin, OfficeHTTPMixin, IdentityHTTPMixin, TerminalHTTPMixin, BaseHTTPRequestHandler):
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

    def authentication_address(self):
        # Caddy owns the sole production loopback connection and normalizes XFF.
        # Direct remote requests cannot spoof a rate-limit/session address.
        address = self.client_address[0]
        forwarded = self.headers.get("X-Forwarded-For", "")
        try:
            if self.app.origin and ipaddress.ip_address(address).is_loopback and forwarded and "," not in forwarded:
                return str(ipaddress.ip_address(forwarded.strip()))
        except ValueError:
            pass
        return address

    def trusted_origins(self):
        getter = getattr(self.app, 'trusted_origins', None)
        return getter() if getter else ({self.app.origin} if self.app.origin else set())

    def request_origin(self):
        candidate = self.headers.get('Origin')
        if candidate and candidate in self.trusted_origins():
            return candidate
        # Only the local reverse proxy can assert the protocol of an API
        # request without an Origin header (for example a session refresh).
        forwarded = self.headers.get('X-Forwarded-Proto')
        if forwarded in ('http', 'https') and ipaddress.ip_address(self.client_address[0]).is_loopback:
            candidate = forwarded + '://' + self.headers.get('Host', '')
            if candidate in self.trusted_origins():
                return candidate
        return self.app.origin or 'http://' + self.headers.get('Host', '')

    def session_cookie(self, token, *, secure=None, max_age=43200):
        secure = self.request_origin().startswith('https://') if secure is None else secure
        return (f'titan_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max_age}'
                + ('; Secure' if secure and not self.app.demo else ''))

    def origin_check(self):
        origin = self.headers.get("Origin")
        if origin:
            expected = self.trusted_origins() or {"http://" + self.headers.get("Host", "")}
            if origin not in expected:
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
        office_page = urllib.parse.urlsplit(self.path).path == "/office_edit.html"
        styles = "'self' 'unsafe-inline'" if office_page else "'self'" + (" 'nonce-" + style_nonce + "'" if style_nonce else "")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src " + styles + "; "
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
                hosts = {urllib.parse.urlsplit(value).netloc for value in self.trusted_origins()}
                if self.headers.get("Host") not in hosts:
                    raise Error("Ungültiger Hostname.", 403)
            function()
        except Error as exc:
            retry = getattr(exc, "retry_after", None)
            if type(retry) is int and 1 <= retry <= 604800 and exc.status == 429:
                self.reply({"error": str(exc), "retry_after": retry}, exc.status, extra={"Retry-After": str(retry)})
            else:
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
        if path == '/api/tunnel-health':
            if set(query) != {'challenge'} or not re.fullmatch(r'[a-f0-9]{32}', query['challenge']):
                raise Error('Ungültige Tunnelprüfung.')
            from .remote_access import proof
            from .web_access import CONFIG, read_config
            if not CONFIG.exists() or self.app.demo:
                raise Error('Fernzugriff nicht eingerichtet.', 404)
            config = read_config(CONFIG)
            if not config.get('remote', {}).get('enabled'):
                raise Error('Fernzugriff deaktiviert.', 404)
            return self.reply({'service': 'Titan', 'challenge': query['challenge'], 'proof': proof(config)})
        if path == "/api/session":
            setup_required = not self.app.store.users() and not self.app.demo
            user = self.user()
            extra = None
            if user and self.request_origin().startswith('https://') and (self.app.origin or '').startswith('https://'):
                # Promote a session used over HTTP as soon as the new HTTPS
                # endpoint is visited, without waiting for another login.
                cookies = SimpleCookie(self.headers.get('Cookie', ''))
                extra = {'Set-Cookie': self.session_cookie(cookies['titan_session'].value)}
            return self.reply({"user": self.user(), "setup_required": setup_required,
                               **({"setup_csrf": self.app.setup_csrf} if setup_required else {}),
                               "demo": self.app.demo, "version": __version__, "stage": __release_stage__,
                               "permissions": permissions(self.app.store, user) if user else {}}, extra=extra)
        if self.office_get(path, query):
            return
        if path.startswith("/api/"):
            user = self.require_user()
            if self.root_access_get(path, user, query):
                return
            if self.identity_get(path, user, query):
                return
            if path in ("/api/shares", "/api/files", "/api/file"):
                if path == "/api/shares" and permissions(self.app.store, user)["apps"]["allowed"]:
                    require_application(self.app.store, user, "apps")
                else:
                    require_application(self.app.store, user, "files")
            if path == "/api/launcher-layout":
                return self.reply(launcher_layout.load(self.app.store, user["name"]))
            if path == "/api/dashboard-layout":
                return self.reply(load_layout(self.app.store, user["name"]))
            if path == "/api/shares":
                shares = self.app.agent.call("shares")
                return self.reply([item for item in shares if user["role"] == "admin" or user["system_user"] in item["readers"] + item["writers"]])
            if path == "/api/files":
                if "recursive" in query and query["recursive"] not in ("0", "1"):
                    raise Error("Rekursive Suche muss 0 oder 1 sein.")
                filters = {key: query[key] for key in ("type", "min_size", "max_size", "modified_after", "modified_before") if key in query}
                if "recursive" in query:
                    filters["recursive"] = query["recursive"] == "1"
                return self.reply(self.file_call(user, share=query["share"], action="list",
                    path=query.get("path", ""), offset=integer(query.get("offset", 0), 0, 2**31-1),
                    limit=integer(query.get("limit", 200), 1, 500), search=query.get("search", ""),
                    **filters))
            if path == "/api/file":
                return self.download(user, query)
            if path == "/api/jobs":
                return self.reply(self.app.store.jobs(None if user["role"] == "admin" else user["name"]))
            if not self.application_route(user, path):
                self.require_user(admin=True)
            if path == '/api/diagnostics':
                if query not in ({}, {'download': '1'}):
                    raise Error('Ungültige Diagnoseoption.')
                return self.reply(diagnostics_report(self.app.agent, self.app.demo), extra={
                    'Content-Disposition': 'attachment; filename="titan-diagnostics.json"'} if query else None)
            if path == '/api/remote-access':
                if query:
                    raise Error('Fernzugriff unterstützt keine zusätzlichen Parameter.')
                if self.app.demo:
                    from .remote_access import validate_remote
                    return self.reply({'remote': validate_remote(None), 'revision': 'demo', 'connectors': [], 'apps': [], 'diagnosis': {}, 'demo': True})
                return self.reply(self.app.agent.call('remote_access'))
            if path == '/api/web-access':
                if query:
                    raise Error('Webzugriff unterstützt keine zusätzlichen Parameter.')
                if self.app.demo:
                    from .web_access import WebAccess
                    return self.reply({**WebAccess(self.app.store.directory / 'web-access').status(), 'demo': True})
                return self.reply(self.app.agent.call('web_access'))
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
                shares = self.app.agent.call("shares")
                return self.reply(shares if user["role"] == "admin" else [share for share in shares if not share.get("blocked") and user["system_user"] in share["readers"] + share["writers"]])
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
                    from .catalog import catalog
                    result = catalog()
                    installed = {item['id'] for item in self.app.agent.call('apps')['installed']}
                    result['installed_recipes'] = [item for item in catalog(include_legacy=True)['apps'] if item['id'] in installed]
                    return self.reply(result)
                return self.reply(self.app.agent.call("catalog"))
            if path in ("/api/package-details", "/api/package-diagnose"):
                if set(query) != {"app"}: raise Error("Genau eine Anwendung auswählen.")
                return self.reply(self.app.agent.call("package_details" if path.endswith("details") else "package_diagnose", app=query["app"]))
            if path == "/api/package-logs":
                if set(query) - {"app", "service", "tail"} or not {"app", "service"} <= set(query):
                    raise Error("Anwendung und Paketdienst auswählen.")
                return self.reply(self.app.agent.call("package_logs", app=query["app"], service=query["service"], tail=integer(query.get("tail", 150), 1, 500)))
            if path == "/api/vm-extensions":
                if set(query) != {"vm"}: raise Error("Genau eine VM auswählen.")
                return self.reply(self.app.agent.call("vm_extensions", vm=query["vm"]))
            if path == "/api/app-details":
                return self.reply(self.app.agent.call("app_details", app=query["app"], tail=integer(query.get("tail", 150), 1, 500)))
            if path == "/api/users":
                accounts = [account for account in self.app.agent.call("accounts", smb_status=True) if not account.get("removed")]
                return self.reply({"web": self.app.store.users(), "system": accounts, "service_user": "titan-files"})
            if path == "/api/backup/settings":
                if user["role"] != "admin":
                    return self.reply(self.app.agent.call("delegated_backup", action="backup_settings", user=user["system_user"], arguments={}))
                return self.reply(self.app.agent.call("backup_settings"))
            if path == "/api/backups":
                if user["role"] != "admin":
                    return self.reply(self.app.agent.call("delegated_backup", action="backups", user=user["system_user"], arguments={}))
                listing = self.app.agent.call("backups")
                result = {"items": listing} if isinstance(listing, list) else listing
                if not isinstance(result, dict):
                    raise Error("Ungültige Backup-Antwort.", 503)
                return self.reply({**result, "settings": self.app.agent.call("backup_settings")})
            if path == "/api/storage/maintenance":
                if query: raise Error("Speicherprüfungen unterstützen keine Optionen.")
                return self.reply(self.app.agent.call("storage_maintenance"))
            if path == "/api/backup/browse":
                if set(query) - {"backup", "path", "offset", "limit"} or "backup" not in query:
                    raise Error("Sicherung auswählen.")
                arguments = {"backup": query["backup"], "path": query.get("path", ""), "offset": integer(query.get("offset", 0), 0, 100000), "limit": integer(query.get("limit", 200), 1, 500)}
                if user["role"] != "admin":
                    return self.reply(self.app.agent.call("delegated_backup", action="backup_browse", user=user["system_user"], arguments=arguments))
                return self.reply(self.app.agent.call("backup_browse", **arguments))
            if path in ("/api/notification/settings", "/api/notifications/settings"):
                if query: raise Error("Benachrichtigungen unterstützen keine Optionen.")
                return self.reply(self.app.agent.call("notification_settings"))
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
            if path == "/api/updates":
                if set(query) - {"kind"}:
                    raise Error("Unbekannte Update-Option.")
                kind = validate_update_kind(query.get("kind", "all"))
                return self.reply(self.app.store.config(update_cache_key(kind), {
                    "current": __version__, "current_stage": __release_stage__, "selection_kind": kind,
                    "channel": self.app.store.settings()["channel"], "available": False}))
            if path == "/api/logs": return self.reply(self.app.store.logs())
            if path == "/api/docker-metrics":
                return self.reply(self.app.agent.call("docker_metrics"))
            if path == "/api/docker-engine":
                return self.reply(self.app.agent.call("docker_engine"))
            if path == "/api/docker-container":
                if set(query)!={"container"}: raise Error("Genau einen Container auswählen.")
                return self.reply(self.app.agent.call("docker_container_details", container=query["container"]))
            if path == "/api/vm-console":
                if set(query)!={"vm"}: raise Error("Genau eine VM auswählen.")
                self.app.agent.call("console", vm=query["vm"])
                return self.reply({"ready":True}, extra={"Cache-Control":"no-store"})
            if path == "/api/vnc":
                self.origin_check()
                return self.websocket(query["vm"])
            operations = {"/api/storage-locations": "storage_locations", "/api/components": "components", "/api/storage": "storage", "/api/apps": "apps", "/api/app-networks": "app_networks", "/api/app-devices": "app_devices", "/api/app-metrics": "app_metrics", "/api/vms": "vms",
                          "/api/snapshots": "snapshots", "/api/vm-options": "vm_options", "/api/isos": "isos", "/api/iso-library": "iso_library"}
            if path in operations:
                return self.reply(self.app.agent.call(operations[path]))
            raise Error("API nicht gefunden.", 404)
        if path.startswith("/novnc/"):
            require_application(self.app.store, self.require_user(), "vms")
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
        path = urllib.parse.urlsplit(self.path).path
        if self.office_post(path):
            return
        self.origin_check()
        body = self.body()
        if path == "/api/setup":
            self.app.rate_limit(self.authentication_address())
            if self.app.demo:
                raise Error("Demo ist bereits eingerichtet.")
            expected = self.trusted_origins() or {"http://" + self.headers.get("Host", "")}
            if self.headers.get("Origin") not in expected or self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
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
            if not {"name", "password"} <= set(body) or set(body) - {"name", "password", "otp"}:
                raise Error("Benutzername, Passwort und optional Sicherheitscode angeben.")
            token, csrf = self.app.store.login(body["name"], body["password"], otp=body.get("otp"),
                address=self.authentication_address(), user_agent=self.headers.get("User-Agent", ""))
            cookie = self.session_cookie(token)
            self.app.store.audit(body["name"], "login")
            return self.reply({"ok": True, "csrf": csrf}, extra={"Set-Cookie": cookie})
        user = self.require_user(mutation=True)
        if self.root_access_post(path, user, body):
            return
        if self.identity_post(path, user, body):
            return
        if path == "/api/launcher-layout":
            return self.reply(launcher_layout.save(self.app.store, user["name"], body))
        if path == "/api/apps/memory-plan":
            require_application(self.app.store, user, "apps")
            if set(body) - {"app", "options"} or "app" not in body:
                raise Error("Anwendung und RAM-Auswahl angeben.")
            options = body.get("options", {})
            if not isinstance(options, dict) or set(options) - {"resource_profile", "office_mode"}:
                raise Error("Ungültige RAM-Auswahl.")
            return self.reply(self.app.agent.call("app_memory_preflight", app=body["app"], options=options))
        if path == "/api/dashboard-layout":
            return self.reply(save_layout(self.app.store, user["name"], body))
        if path == "/api/logout":
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            if "titan_session" in cookie:
                self.app.store.logout(cookie["titan_session"].value)
            if hasattr(self.app, 'disable_root_access'):
                self.app.disable_root_access(user, 'Abgemeldet')
            self.app.close_terminal_owner(terminal_owner(user))
            return self.reply({"ok": True}, extra={"Set-Cookie": self.session_cookie('', max_age=0)})
        if path == "/api/files":
            if body.get("action") not in FILE_ACTIONS:
                raise Error("Ungültige Dateiaktion.")
            if set(body) - {"share", "path", "action", "offset", "size", "limit", "search", "data", "destination", "trash_name", "destination_share", "revision", "confirmation_path", "document_type"}:
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
        application = operation_application(body.get("operation", "")) if path == "/api/actions" else "vms" if path in ("/api/isos", "/api/isos/cancel") else None
        if application:
            require_application(self.app.store, user, application)
        else:
            self.require_user(admin=True)
        if path in ('/api/remote-access', '/api/remote-access/diagnose'):
            if self.app.demo:
                raise Error('Fernzugriff benötigt eine echte Titan-Installation.', 409)
            if path.endswith('/diagnose'):
                if body:
                    raise Error('Verbindungsprüfung benötigt keine zusätzlichen Parameter.')
                result = self.app.agent.call('remote_access_diagnose')
            else:
                if set(body) != {'enabled', 'public_origin', 'connector', 'app_urls', 'expected_revision'}:
                    raise Error('Fernzugriffseinstellungen vollständig angeben.')
                result = self.app.agent.call('remote_access_apply', **body)
            self.app.store.audit(user['name'], 'remote_access_diagnose' if path.endswith('/diagnose') else 'remote_access_apply')
            return self.reply(result)
        if path == '/api/terminal':
            return self.terminal_post(user, body)
        if path in ('/api/web-access', '/api/web-access/confirm', '/api/web-access/cancel'):
            if self.app.demo:
                raise Error('Webports können in der Demo nicht geändert werden.', 409)
            if path == '/api/web-access':
                if set(body) != {'settings', 'expected_revision'}:
                    raise Error('Webeinstellungen und aktuellen Stand angeben.')
                operation, arguments = 'web_access_apply', body
            elif path.endswith('/confirm'):
                if set(body) != {'expected_revision'}:
                    raise Error('Den aktuellen Adresswechsel angeben.')
                operation, arguments = 'web_access_confirm', {**body, 'request_origin': self.headers.get('Origin', '')}
            else:
                if body:
                    raise Error('Zurücknehmen benötigt keine zusätzlichen Parameter.')
                operation, arguments = 'web_access_cancel', {}
            result = self.app.agent.call(operation, **arguments)
            self.app.store.audit(user['name'], operation)
            extra = None
            if operation == 'web_access_apply' and result.get('pending') and result.get('settings', {}).get('mode') == 'http':
                # Browsers cannot replace a Secure cookie from the new HTTP
                # endpoint. The explicit protocol change must replace it on
                # the existing HTTPS endpoint before opening the new address.
                if self.request_origin().startswith('https://'):
                    cookies = SimpleCookie(self.headers.get('Cookie', ''))
                    extra = {'Set-Cookie': self.session_cookie(cookies['titan_session'].value, secure=False)}
            return self.reply(result, extra=extra)
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
        if path in ("/api/notification/settings", "/api/notifications/settings"):
            result = self.app.agent.call("notification_save_settings", **body)
            self.app.store.audit(user["name"], "notification_settings")
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
            if set(body) - {"update_kind"}:
                raise Error("Unbekannte Update-Option.")
            kind = validate_update_kind(body.get("update_kind", "all"))
            return self.reply(self.app.jobs.submit(user["name"], "update_check", lambda: self.app.update_check(kind)), 202)
        if path == "/api/users":
            if not {"name", "password", "role"} <= set(body) or set(body) - {"name", "password", "role", "display_name", "description"}:
                raise Error("Benutzername, Passwort und Rolle sind erforderlich.")
            name = identifier(body["name"])
            password_hash(body["password"])
            if body.get("role") not in ("admin", "user") or name in {item["name"] for item in self.app.store.users()}:
                raise Error("Rolle ungültig oder Benutzer existiert bereits.")
            profile = {field: user_profile_text(body[field], field) for field in ("display_name", "description") if field in body}
            def create():
                return self.app.users.create(user["name"], name, body["password"], body["role"], **profile)
            return self.reply(self.app.jobs.submit(user["name"], "account_create", create), 202)
        if path == "/api/users/update":
            if "name" not in body or set(body) - {"name", "password", "role", "enabled", "display_name", "description"} or len(body) < 2:
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
            operation = body.get("operation")
            if not isinstance(operation, str):
                raise Error("Eine gültige Aktion auswählen.")
            arguments = body.get("arguments", {})
            if operation not in MUTATIONS or not isinstance(arguments, dict):
                raise Error("Aktion nicht erlaubt.")
            if operation == "app_store_add":
                from .store_sources import BIGBEAR
                if arguments.get("url") != BIGBEAR:
                    raise Error("Aktuell wird nur der BigBear-Katalog unterstützt.")
            if operation == "update_install":
                if not {"expected_version"} <= set(arguments) or set(arguments) - {"expected_version", "update_kind"}:
                    raise Error("Erwartete Update-Version erforderlich.")
                validate_update_kind(arguments.get("update_kind", "all"))
                if type(arguments["expected_version"]) is not str or not re.fullmatch(r"v?\d+\.\d+\.\d+(?:-(?:alpha|beta)\.\d+)?", arguments["expected_version"]):
                    raise Error("Ungültige Update-Version.")
            if operation in ("update_rollback", "system_reboot"):
                from .updates import validate_system_action
                validate_system_action(operation, arguments)
            if operation == "system_disk_grow":
                validate_system_disk_growth(arguments)
            if operation == "app_network_create":
                from .app_networks import validate_create
                if "name" not in arguments or set(arguments) - {"name", "subnet", "gateway", "internal"}:
                    raise Error("Netzwerkname und gültige Netzwerkeinstellungen sind erforderlich.")
                validate_create(**arguments)
            if operation == "app_network_remove":
                from .app_networks import network_name
                if set(arguments) != {"name", "confirmation"}:
                    raise Error("Genau ein Netzwerk zum Entfernen auswählen.")
                network_name(arguments["name"])
                if arguments["confirmation"] != arguments["name"]:
                    raise Error("Netzwerkentfernung muss bestätigt werden.")
            if operation == "share_user_permission":
                if set(arguments) != {"name", "user", "permission"} or arguments["permission"] not in ("none", "read", "write"):
                    raise Error("Freigabe, Benutzer und gültiges Zugriffsrecht sind erforderlich.")
                identifier(arguments["name"])
                identifier(arguments["user"])
            if operation_application(operation) == "backups" and user["role"] != "admin":
                from .backup_authorization import web_authorize
                web_authorize(self.app.store, self.app.agent, user, operation, arguments)
            return self.reply(self.app.jobs.submit(user["name"], operation,
                              lambda: self.app.admin_action(user["name"], operation, arguments), resources=job_resources(operation, arguments)), 202)
        raise Error("API nicht gefunden.", 404)

    def file_call(self, user, **arguments):
        require_application(self.app.store, user, "files")
        if arguments.get("share") == "@system":
            if user["role"] != "admin":
                raise Error("Systemdateizugriff erfordert Administratorrechte.", 403)
            arguments.pop("share")
            if getattr(self.app, 'root_access_active', lambda _: False)(user):
                return self.root_system_file_call(user, arguments)
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
                if not current:
                    return
                try:
                    require_application(self.app.store, current, "vms")
                except Error:
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
        parser.error("Produktivbetrieb benötigt eine konfigurierte HTTP-/HTTPS-Webadresse und einen lokalen Reverse-Proxy.")
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

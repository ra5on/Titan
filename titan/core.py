import base64
import contextlib
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import threading
import time
import unicodedata


class Error(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


_PROFILE_UNSET = object()
_PROFILE_FIELDS = {"display_name": ("Anzeigename", 96), "description": ("Beschreibung", 256)}


def user_profile_text(value, field):
    """Accept optional, single-line UTF-8 profile text without hidden controls."""
    label, maximum = _PROFILE_FIELDS[field]
    if not isinstance(value, str) or len(value) > maximum:
        raise Error(f"{label} darf höchstens {maximum} Zeichen enthalten.")
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in value):
        raise Error(f"{label} enthält ungültige Steuerzeichen.")
    return value.strip()


@contextlib.contextmanager
def configuration_lock(directory):
    """Coordinate web account commits and root configuration snapshots."""
    directory = Path(directory)
    path = directory / "account-changes.lock"
    owner = directory.stat().st_uid
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        if os.geteuid() == 0:
            os.fchown(fd, owner, -1)
    except FileExistsError:
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != owner or info.st_mode & 0o077:
            raise Error("Unsichere Sperrdatei für Kontokonfiguration.", 503)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,30}", value):
        raise Error("Name: 1–31 Zeichen, Kleinbuchstaben, Ziffern, _ oder -.")
    return value


def integer(value, minimum, maximum):
    if isinstance(value, bool):
        raise Error("Ungültiger Zahlenwert.")
    try:
        result = int(value)
    except (ValueError, TypeError):
        raise Error("Ungültiger Zahlenwert.")
    if not minimum <= result <= maximum:
        raise Error(f"Wert muss zwischen {minimum} und {maximum} liegen.")
    return result


def password_hash(password, salt=None):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise Error("Passwort muss 12–256 Zeichen lang sein.")
    if any(char in password for char in ("\n", "\r", "\x00")):
        raise Error("Passwort enthält ungültige Zeichen.")
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return salt + ":" + digest.hex()


def password_matches(password, stored):
    try:
        return hmac.compare_digest(password_hash(password, stored.split(":")[0]), stored)
    except (Error, ValueError, AttributeError):
        return False


# Unknown usernames still perform one password verification, matching existing
# accounts; generating a fresh dummy hash on every request doubled their work.
_DUMMY_PASSWORD_HASH = password_hash("invalid-password", salt="0" * 32)


def atomic_json(path, value, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + secrets.token_hex(6))
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


DEFAULT_SETTINGS = {
    "hostname": "Titan", "repository": "ra5on/Titan", "auto_check": True,
    "check_interval": "daily", "channel": "stable", "installation": "manual",
    "window_day": 6, "window_hour": 3, "allow_reboot": False,
}

UPDATE_POLICY_KEYS = frozenset({"auto_check", "check_interval", "installation", "window_day", "window_hour"})


def update_policy(value):
    if not isinstance(value, dict) or set(value) != UPDATE_POLICY_KEYS:
        raise Error("Vollständige Einstellungen für den Update-Bereich erforderlich.")
    if type(value["auto_check"]) is not bool:
        raise Error("Ungültiger Update-Schalter.")
    if value["check_interval"] not in ("daily", "weekly") or value["installation"] not in ("manual", "automatic"):
        raise Error("Ungültige Update-Einstellung.")
    return {**value, "window_day": integer(value["window_day"], 0, 6),
            "window_hour": integer(value["window_hour"], 0, 23)}


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        with configuration_lock(self.directory):
            pass
        self.path = self.directory / "titan.sqlite3"
        self.lock = threading.RLock()
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (name TEXT PRIMARY KEY, password TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'user')), system_user TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
                    display_name TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, username TEXT NOT NULL,
                    csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, time REAL NOT NULL,
                    username TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, time REAL NOT NULL,
                    username TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL,
                    result TEXT NOT NULL);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
            if "enabled" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1))")
            for field in _PROFILE_FIELDS:
                if field not in columns:
                    db.execute(f"ALTER TABLE users ADD COLUMN {field} TEXT NOT NULL DEFAULT ''")
            from .security import initialize_security
            initialize_security(db)
            db.execute("UPDATE jobs SET status='failed', result=? WHERE status IN ('queued','running')",
                       (json.dumps({"error": "Dienst wurde während des Auftrags neu gestartet."}),))
        os.chmod(self.path, 0o600)
        self.setup_file = self.directory / "setup-token"
        # Older releases used a manually copied bootstrap code. It no longer
        # authorizes setup and is not needed for new or existing installations.
        self.setup_file.unlink(missing_ok=True)

    @contextlib.contextmanager
    def connection(self):
        with self.lock:
            db = sqlite3.connect(self.path, timeout=15)
            db.row_factory = sqlite3.Row
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    def users(self):
        with self.connection() as db:
            return [{**dict(row), "enabled": bool(row["enabled"])} for row in db.execute(
                "SELECT name, role, system_user, enabled, display_name, description FROM users ORDER BY name")]

    def user_record(self, name):
        with self.connection() as db:
            row = db.execute("SELECT * FROM users WHERE name=?", (identifier(name),)).fetchone()
            if not row:
                raise Error("Benutzer nicht gefunden.", 404)
            return {**dict(row), "enabled": bool(row["enabled"])}

    def validate_user_update(self, name, password=None, role=None, enabled=None,
                             display_name=_PROFILE_UNSET, description=_PROFILE_UNSET):
        current = self.user_record(name)
        if password is not None:
            password_hash(password)
        if role is not None and role not in ("admin", "user"):
            raise Error("Ungültige Rolle.")
        if enabled is not None and not isinstance(enabled, bool):
            raise Error("Kontostatus muss ein Schalter sein.")
        for field, value in (("display_name", display_name), ("description", description)):
            if value is not _PROFILE_UNSET:
                user_profile_text(value, field)
        updated = {**current, "role": current["role"] if role is None else role,
                   "enabled": current["enabled"] if enabled is None else enabled}
        if current["enabled"] and current["role"] == "admin" and (
                not updated["enabled"] or updated["role"] != "admin"):
            if sum(item["enabled"] and item["role"] == "admin" for item in self.users()) <= 1:
                raise Error("Der letzte aktive Administrator muss erhalten bleiben.", 409)
        return current

    def update_user(self, name, password=None, role=None, enabled=None, before_commit=None, system_user=None,
                    display_name=_PROFILE_UNSET, description=_PROFILE_UNSET):
        # Validation and the update share the same lock, including the last-admin check.
        with self.lock:
            current = self.validate_user_update(name, password, role, enabled, display_name, description)
            hashed = current["password"] if password is None else password_hash(password)
            selected_role = current["role"] if role is None else role
            selected_enabled = current["enabled"] if enabled is None else enabled
            selected_system_user = current["system_user"] if system_user is None else identifier(system_user)
            selected_display_name = current["display_name"] if display_name is _PROFILE_UNSET else user_profile_text(display_name, "display_name")
            selected_description = current["description"] if description is _PROFILE_UNSET else user_profile_text(description, "description")
            changed = (hashed, selected_role, selected_enabled, selected_system_user) != (
                current["password"], current["role"], current["enabled"], current["system_user"])
            with self.connection() as db:
                db.execute("UPDATE users SET password=?,role=?,enabled=?,system_user=?,display_name=?,description=? WHERE name=?",
                           (hashed, selected_role, int(selected_enabled), selected_system_user,
                            selected_display_name, selected_description, name))
                if changed:
                    db.execute("DELETE FROM sessions WHERE username=?", (name,))
                if before_commit:
                    before_commit(current)
            return {"ok": True, "name": name, "sessions_revoked": changed}

    def create_user(self, name, password, role, system_user, before_commit=None, display_name="", description=""):
        name = identifier(name)
        system_user = identifier(system_user)
        if role not in ("admin", "user"):
            raise Error("Ungültige Rolle.")
        hashed = password_hash(password)
        display_name = user_profile_text(display_name, "display_name")
        description = user_profile_text(description, "description")
        with self.connection() as db:
            try:
                db.execute("INSERT INTO users(name,password,role,system_user,enabled,display_name,description) VALUES (?,?,?,?,1,?,?)",
                           (name, hashed, role, system_user, display_name, description))
            except sqlite3.IntegrityError:
                raise Error("Benutzer existiert bereits.", 409)
            if before_commit:
                before_commit()

    def setup(self, name, password, system_user="titan-files", before_commit=None):
        name = identifier(name)
        system_user = identifier(system_user)
        hashed = password_hash(password)
        with configuration_lock(self.directory), self.connection() as db:
            # Serialize the emptiness check and insert across threads, Store
            # instances and processes. Any existing account closes first setup.
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise Error("Ersteinrichtung ist abgeschlossen. Bitte anmelden.", 409)
            db.execute("INSERT INTO users(name,password,role,system_user,enabled) VALUES (?,?,'admin',?,1)",
                       (name, hashed, system_user))
            if before_commit:
                before_commit()
        self.setup_file.unlink(missing_ok=True)

    def login(self, name, password, otp=None, address="", user_agent=""):
        from .security import record_login, verify_factor
        from .login_protection import blocked, blocked_error, capacity_delay, failure, settings, source_address
        valid_name = isinstance(name, str) and 1 <= len(name) <= 64
        if not valid_name:
            # Malformed names still count as failed attempts for their source.
            # The placeholder cannot be a Titan username and bounds persistence.
            name = "[ungültiger Benutzername]"
        accepted = False
        delay = 0
        address = source_address(address)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            now = time.time()
            policy = settings(db)
            delay = blocked(db, policy, name, address, now) or capacity_delay(db, policy, name, address)
            if not delay:
                row = db.execute("SELECT * FROM users WHERE name=?", (name,)).fetchone()
                stored = row["password"] if row else _DUMMY_PASSWORD_HASH
                valid = password_matches(password, stored)
                if valid_name and row and valid and row["enabled"]:
                    accepted = verify_factor(db, name, otp)
                if not accepted:
                    failure(db, policy, name, address, now)
            record_login(db, name, accepted, address, user_agent)
            if accepted:
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                db.execute("DELETE FROM sessions WHERE expires < ?", (now,))
                db.execute("INSERT INTO sessions(token,username,csrf,expires,created,last_seen,address,user_agent) VALUES (?,?,?,?,?,?,?,?)",
                           (hashlib.sha256(token.encode()).hexdigest(), name, csrf, now + 43200, now, now,
                            str(address)[:64], str(user_agent)[:256]))
        if delay:
            raise blocked_error(delay)
        if not accepted:
            raise Error("Benutzername, Passwort oder Sicherheitscode ist falsch.", 401)
        return token, csrf

    def session(self, token):
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connection() as db:
            row = db.execute("SELECT users.name, users.role, users.system_user, sessions.csrf FROM sessions "
                             "JOIN users ON users.name=sessions.username WHERE token=? AND expires>? AND users.enabled=1",
                             (digest, time.time())).fetchone()
            if row:
                db.execute("UPDATE sessions SET last_seen=? WHERE token=? AND last_seen<?", (time.time(), digest, time.time()-30))
            return dict(row) if row else None

    def logout(self, token):
        with self.connection() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def config(self, key, default=None):
        with self.connection() as db:
            row = db.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_config(self, key, value):
        with self.connection() as db:
            db.execute("INSERT INTO config VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, json.dumps(value)))

    def settings(self):
        # Image updates only stage a deployment. A saved legacy setting must
        # never authorize restarting a NAS with active guests or containers.
        settings = {**DEFAULT_SETTINGS, **self.config("settings", {}), "allow_reboot": False}
        legacy = {key: settings[key] for key in UPDATE_POLICY_KEYS}
        defaults = {key: DEFAULT_SETTINGS[key] for key in UPDATE_POLICY_KEYS}
        saved = settings.get("update_streams", {})
        settings["update_streams"] = {"titan": {**legacy, **saved.get("titan", {})},
                                      "system": {**defaults, **saved.get("system", {})}}
        return settings

    def save_settings(self, value):
        allowed = set(DEFAULT_SETTINGS) | {"update_streams"}
        if set(value) - allowed:
            raise Error("Unbekannte Einstellung.")
        settings = {**self.settings(), **value}
        if "update_streams" in value:
            streams = value["update_streams"]
            if not isinstance(streams, dict) or set(streams) != {"titan", "system"}:
                raise Error("Titan und System als getrennte Update-Bereiche angeben.")
            settings["update_streams"] = {kind: update_policy(streams[kind]) for kind in ("titan", "system")}
            # Legacy clients and exported settings retain the Titan policy.
            settings.update(settings["update_streams"]["titan"])
        elif UPDATE_POLICY_KEYS.intersection(value):
            settings["update_streams"]["titan"] = {**settings["update_streams"]["titan"],
                **{key: value[key] for key in UPDATE_POLICY_KEYS if key in value}}
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", settings["repository"]):
            raise Error("Repository muss als owner/name angegeben werden.")
        for key in ("auto_check", "allow_reboot"):
            if not isinstance(settings[key], bool):
                raise Error("Ungültiger Schalter.")
        if settings["allow_reboot"]:
            raise Error("Titan-Systemupdates lösen keinen automatischen Neustart aus.")
        for key, choices in {"channel": ("stable", "beta", "alpha"), "check_interval": ("daily", "weekly"),
                             "installation": ("manual", "automatic")}.items():
            if settings[key] not in choices:
                raise Error("Ungültige Update-Einstellung.")
        settings["window_day"] = integer(settings["window_day"], 0, 6)
        settings["window_hour"] = integer(settings["window_hour"], 0, 23)
        settings["update_streams"] = {kind: update_policy(settings["update_streams"][kind])
                                      for kind in ("titan", "system")}
        if not isinstance(settings["hostname"], str) or not 1 <= len(settings["hostname"]) <= 64:
            raise Error("Ungültiger Anzeigename.")
        self.set_config("settings", settings)
        return settings

    def audit(self, user, action, detail=""):
        with self.connection() as db:
            db.execute("INSERT INTO audit(time,username,action,detail) VALUES (?,?,?,?)",
                       (time.time(), user, action, str(detail)[:2000]))
            db.execute("DELETE FROM audit WHERE id < (SELECT COALESCE(MAX(id),0)-10000 FROM audit)")

    def logs(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 100")]

    def jobs(self, user=None):
        with self.connection() as db:
            query = "SELECT * FROM jobs"
            args = ()
            if user:
                query += " WHERE username=?"
                args = (user,)
            rows = db.execute(query + " ORDER BY time DESC LIMIT 50", args)
            return [{**dict(row), "result": json.loads(row["result"])} for row in rows]


class OperationCoordinator:
    """Exclusive maintenance, shared independent work, and ordered object locks.

    Unknown mutations keep the old exclusive behavior. A caller must explicitly
    provide resources to allow concurrent work. Restore/storage operations can
    therefore wait for all live work without racing another object's lifecycle.
    """
    def __init__(self):
        self.condition = threading.Condition()
        self.readers = 0
        self.writer = False
        self.waiting_writers = 0
        self.resources = {}

    @contextlib.contextmanager
    def hold(self, resources=None):
        exclusive = resources is None
        keys = sorted(set(resources or ()))
        with self.condition:
            if exclusive:
                self.waiting_writers += 1
                try:
                    self.condition.wait_for(lambda: not self.writer and not self.readers)
                    self.writer = True
                finally:
                    self.waiting_writers -= 1
            else:
                self.condition.wait_for(lambda: not self.writer and not self.waiting_writers)
                self.readers += 1
            locks = []
            for key in keys:
                entry = self.resources.setdefault(key, [threading.RLock(), 0])
                entry[1] += 1
                locks.append((key, entry[0]))
        try:
            with contextlib.ExitStack() as stack:
                for _, lock in locks:
                    stack.enter_context(lock)
                yield
        finally:
            with self.condition:
                for key, _ in locks:
                    entry = self.resources[key]
                    entry[1] -= 1
                    if not entry[1]:
                        del self.resources[key]
                if exclusive:
                    self.writer = False
                else:
                    self.readers -= 1
                self.condition.notify_all()


APP_RESOURCE_OPERATIONS = frozenset({"app_install", "app_action", "package_repair"})


def job_resources(operation, arguments):
    """The small audited set of jobs that can run beside other app work."""
    if operation in APP_RESOURCE_OPERATIONS:
        if operation == "app_action" and arguments.get("action") not in {"start", "stop", "restart", "remove", "logs"}:
            return None  # backups/upgrades still require exclusive maintenance
        app = arguments.get("app")
        if isinstance(app, str) and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", app):
            return ("app:" + app,)
    if operation == "docker_container_action":
        value = arguments.get("container")
        if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value):
            return ("container:" + value,)
    if operation == "docker_container_batch":
        values = arguments.get("containers")
        if isinstance(values, list) and 1 <= len(values) <= 64 and all(isinstance(v, str) and re.fullmatch(r"[a-f0-9]{64}", v) for v in values):
            return tuple("container:" + v for v in sorted(set(values)))
    return None


class Jobs:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.coordinator = OperationCoordinator()
        self.slots = threading.BoundedSemaphore(4)
        self.security_slots = threading.BoundedSemaphore(2)

    def submit(self, user, action, function, security=False, resources=None):
        slots = self.security_slots if security else self.slots
        if not slots.acquire(blocking=False):
            raise Error("Zwei Kontoänderungen laufen bereits. Bitte kurz warten." if security else
                        "Vier Aufträge laufen bereits. Bitte kurz warten.", 429)
        job = secrets.token_hex(12)
        try:
            with self.store.connection() as db:
                db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)", (job, time.time(), user, action, "queued", "{}"))
        except Exception:
            slots.release()
            raise
        def work():
            try:
                # Only audited independent object work is shared; maintenance
                # remains exclusive. Revocation has its existing separate lane.
                with contextlib.nullcontext() if security else self.coordinator.hold(resources):
                    with self.store.connection() as db:
                        db.execute("UPDATE jobs SET status='running',result=? WHERE id=?", (json.dumps({"started_at": time.time()}), job))
                    result = function()
                status = "failed" if isinstance(result, dict) and result.get("ok") is False else "completed"
                self.store.audit(user, action, "Fehlgeschlagen; Details im Auftrag" if status == "failed" else "Erfolgreich")
            except Exception as exc:
                result, status = {"error": str(exc)}, "failed"
                self.store.audit(user, action, str(exc))
            finally:
                with self.store.connection() as db:
                    db.execute("UPDATE jobs SET status=?,result=? WHERE id=?", (status, json.dumps(result), job))
                slots.release()
        threading.Thread(target=work, daemon=True).start()
        return {"job": job}

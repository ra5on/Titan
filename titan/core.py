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


class Error(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


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
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)));
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
                "SELECT name, role, system_user, enabled FROM users ORDER BY name")]

    def user_record(self, name):
        with self.connection() as db:
            row = db.execute("SELECT * FROM users WHERE name=?", (identifier(name),)).fetchone()
            if not row:
                raise Error("Benutzer nicht gefunden.", 404)
            return {**dict(row), "enabled": bool(row["enabled"])}

    def validate_user_update(self, name, password=None, role=None, enabled=None):
        current = self.user_record(name)
        if password is not None:
            password_hash(password)
        if role is not None and role not in ("admin", "user"):
            raise Error("Ungültige Rolle.")
        if enabled is not None and not isinstance(enabled, bool):
            raise Error("Kontostatus muss ein Schalter sein.")
        updated = {**current, "role": current["role"] if role is None else role,
                   "enabled": current["enabled"] if enabled is None else enabled}
        if current["enabled"] and current["role"] == "admin" and (
                not updated["enabled"] or updated["role"] != "admin"):
            if sum(item["enabled"] and item["role"] == "admin" for item in self.users()) <= 1:
                raise Error("Der letzte aktive Administrator muss erhalten bleiben.", 409)
        return current

    def update_user(self, name, password=None, role=None, enabled=None, before_commit=None, system_user=None):
        # Validation and the update share the same lock, including the last-admin check.
        with self.lock:
            current = self.validate_user_update(name, password, role, enabled)
            hashed = current["password"] if password is None else password_hash(password)
            selected_role = current["role"] if role is None else role
            selected_enabled = current["enabled"] if enabled is None else enabled
            selected_system_user = current["system_user"] if system_user is None else identifier(system_user)
            changed = (hashed, selected_role, selected_enabled, selected_system_user) != (
                current["password"], current["role"], current["enabled"], current["system_user"])
            with self.connection() as db:
                db.execute("UPDATE users SET password=?,role=?,enabled=?,system_user=? WHERE name=?",
                           (hashed, selected_role, int(selected_enabled), selected_system_user, name))
                if changed:
                    db.execute("DELETE FROM sessions WHERE username=?", (name,))
                if before_commit:
                    before_commit(current)
            return {"ok": True, "name": name, "sessions_revoked": changed}

    def create_user(self, name, password, role, system_user, before_commit=None):
        name = identifier(name)
        system_user = identifier(system_user)
        if role not in ("admin", "user"):
            raise Error("Ungültige Rolle.")
        hashed = password_hash(password)
        with self.connection() as db:
            try:
                db.execute("INSERT INTO users(name,password,role,system_user,enabled) VALUES (?,?,?,?,1)",
                           (name, hashed, role, system_user))
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

    def login(self, name, password):
        with self.connection() as db:
            row = db.execute("SELECT * FROM users WHERE name=?", (name,)).fetchone()
            # Check credentials and create the session under one lock: a concurrent
            # account block cannot race between authentication and session creation.
            stored = row["password"] if row else password_hash("invalid-password")
            valid = password_matches(password, stored)
            if not row or not valid or not row["enabled"]:
                raise Error("Benutzername oder Passwort ist falsch.", 401)
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES (?,?,?,?)",
                       (hashlib.sha256(token.encode()).hexdigest(), name, csrf, time.time() + 43200))
        return token, csrf

    def session(self, token):
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connection() as db:
            row = db.execute("SELECT users.name, users.role, users.system_user, sessions.csrf FROM sessions "
                             "JOIN users ON users.name=sessions.username WHERE token=? AND expires>? AND users.enabled=1",
                             (digest, time.time())).fetchone()
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
        return {**DEFAULT_SETTINGS, **self.config("settings", {}), "allow_reboot": False}

    def save_settings(self, value):
        allowed = set(DEFAULT_SETTINGS)
        if set(value) - allowed:
            raise Error("Unbekannte Einstellung.")
        settings = {**self.settings(), **value}
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


class Jobs:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(4)
        self.security_slots = threading.BoundedSemaphore(2)

    def submit(self, user, action, function, security=False):
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
                with self.store.connection() as db:
                    db.execute("UPDATE jobs SET status='running' WHERE id=?", (job,))
                # Serialize mutations so storage/app/user operations do not race each other.
                with contextlib.nullcontext() if security else self.lock:
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

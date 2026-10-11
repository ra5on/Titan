"""App-scoped browser access; a package never receives a Titan login session.

Tickets are single-use and last 30 seconds. App sessions remain tied to the
original NAS session, so logout, account disable and permission changes revoke
access immediately. Only hashes are persisted, including across WebUI restarts.
"""
import hashlib
import re
import secrets
import time
from http.cookies import SimpleCookie

from .core import Error
from .identity import require_application

APP = re.compile(r'[a-z][a-z0-9_-]{0,79}')
TOKEN = re.compile(r'[A-Za-z0-9_-]{43}')


def digest(value):
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise Error('App-Anmeldung ist ungültig.', 401)
    return hashlib.sha256(value.encode()).hexdigest()


def app_id(value):
    if not isinstance(value, str) or not APP.fullmatch(value):
        raise Error('Ungültige App-ID.')
    return value


def cookie_name(app):
    return 'titan_app_' + app_id(app)


def upstream_cookies(raw):
    """Do not expose any NAS/app gateway credential to a package backend."""
    if not isinstance(raw, str) or len(raw) > 16384 or '\r' in raw or '\n' in raw:
        raise Error('Ungültige App-Cookies.', 400)
    cookie = SimpleCookie()
    try:
        cookie.load(raw)
    except Exception:
        raise Error('Ungültige App-Cookies.', 400) from None
    return '; '.join(value.OutputString() for name, value in cookie.items()
                     if not name.lower().startswith(('titan_', '__host-titan', '__secure-titan')))


class AppAccess:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock
        with store.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS app_access (
                    token TEXT PRIMARY KEY, app TEXT NOT NULL, parent TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('ticket','session')),
                    expires REAL NOT NULL, origin TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS app_access_parent ON app_access(parent);
            ''')

    def _parent(self, db, parent):
        row = db.execute('''SELECT users.name, users.role, users.system_user,
            sessions.csrf, sessions.expires FROM sessions JOIN users
            ON users.name=sessions.username WHERE sessions.token=?
            AND sessions.expires>? AND users.enabled=1''', (parent, self.clock())).fetchone()
        if not row:
            raise Error('Bitte in Titan erneut anmelden.', 401)
        user = dict(row)
        require_application(self.store, user, 'apps')
        return user

    def _prune(self, db):
        db.execute('DELETE FROM app_access WHERE expires<=? OR parent NOT IN (SELECT token FROM sessions)',
                   (self.clock(),))

    def issue(self, app, parent_token, origin=""):
        if origin:
            from .office_gateway import url_origin
            import urllib.parse
            url_origin(urllib.parse.urlsplit(origin))
        app_id(app)
        parent = digest(parent_token)
        ticket = secrets.token_urlsafe(32)
        with self.store.connection() as db:
            user = self._parent(db, parent)
            self._prune(db)
            # Repeated opens cannot grow the store without bound.
            db.execute("DELETE FROM app_access WHERE parent=? AND app=? AND kind='ticket'", (parent, app))
            db.execute('INSERT INTO app_access VALUES (?,?,?,?,?,?)',
                       (digest(ticket), app, parent, 'ticket', min(user['expires'], self.clock()+30), origin))
        return ticket

    def redeem(self, app, ticket):
        app_id(app)
        key = digest(ticket)
        token = secrets.token_urlsafe(32)
        with self.store.connection() as db:
            # Serialize across processes as well as Store threads. A competing
            # redemption must see the deletion, never consume the same ticket.
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM app_access WHERE token=? AND app=? AND kind='ticket' AND expires>?",
                             (key, app, self.clock())).fetchone()
            if not row:
                raise Error('App-Link ist abgelaufen oder wurde bereits verwendet. App in Titan erneut öffnen.', 401)
            user = self._parent(db, row['parent'])
            db.execute('DELETE FROM app_access WHERE token=?', (key,))
            # One browser grant per NAS login and app; a new open revokes the
            # old token while other NAS login sessions remain independent.
            db.execute("DELETE FROM app_access WHERE parent=? AND app=? AND kind='session'", (row['parent'], app))
            db.execute('INSERT INTO app_access VALUES (?,?,?,?,?,?)',
                       (digest(token), app, row['parent'], 'session', user['expires'], row['origin']))
        return token

    def authorize(self, app, token):
        app_id(app)
        with self.store.connection() as db:
            row = db.execute("SELECT parent, origin FROM app_access WHERE token=? AND app=? AND kind='session' AND expires>?",
                             (digest(token), app, self.clock())).fetchone()
            if not row:
                raise Error('App in Titan öffnen, um dich anzumelden.', 401)
            return {**self._parent(db, row['parent']), 'app_origin': row['origin']}

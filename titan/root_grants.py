"""Root mode leases confirmed by the privileged agent itself.

The web service asks for an administrator's password before root mode. This
module repeats that check inside the agent, against the stored password hash,
so a compromised web process cannot open a root terminal or reach system
files without knowing an administrator password.
"""
from pathlib import Path
import sqlite3
import threading
import time
from .core import Error, password_matches

MAX_GRANTS = 64
MAX_MINUTES = 30
FAILURES = 5
WINDOW = 300


class RootGrantMixin:
    web_database = Path('/var/lib/titan/titan.sqlite3')

    def _root_grant_state(self):
        if not hasattr(self, '_root_grants'):
            self._root_grants, self._root_failures, self._root_grant_lock = {}, {}, threading.Lock()
        return self._root_grants, self._root_failures, self._root_grant_lock

    def _root_administrator(self, name, password):
        """True when the web account is an enabled administrator with this password."""
        try:
            database = sqlite3.connect('file:' + str(self.web_database) + '?mode=ro', uri=True, timeout=5)
        except sqlite3.Error:
            raise Error('Die Kontodatenbank ist für den Systemdienst nicht lesbar.', 503) from None
        try:
            row = database.execute('SELECT password,role,enabled FROM users WHERE name=?', (name,)).fetchone()
        except sqlite3.Error:
            raise Error('Die Kontodatenbank ist für den Systemdienst nicht lesbar.', 503) from None
        finally:
            database.close()
        return bool(row and row[2] and row[1] == 'admin' and password_matches(password, row[0]))

    def op_root_grant(self, owner, name, password, minutes=15):
        if (not isinstance(owner, str) or not 1 <= len(owner) <= 256 or not isinstance(name, str) or not 1 <= len(name) <= 64
                or not isinstance(password, str) or not 1 <= len(password) <= 1024 or type(minutes) is not int or not 1 <= minutes <= MAX_MINUTES):
            raise Error('Ungültige Root-Freigabe.')
        grants, failures, lock = self._root_grant_state()
        now = time.monotonic()
        with lock:
            recent = [moment for moment in failures.get(name, []) if now - moment < WINDOW]
            failures[name] = recent
            if len(recent) >= FAILURES:
                raise Error('Zu viele fehlgeschlagene Root-Freigaben. Bitte einige Minuten warten.', 429)
        if not self._root_administrator(name, password):
            with lock:
                failures.setdefault(name, []).append(now)
                if len(failures) > 256:
                    failures.clear()
            raise Error('Der Systemdienst konnte die Administratoranmeldung nicht bestätigen.', 403)
        with lock:
            for key in [key for key, deadline in grants.items() if deadline <= now]:
                del grants[key]
            if owner not in grants and len(grants) >= MAX_GRANTS:
                raise Error('Zu viele aktive Administratorfreigaben.', 429)
            grants[owner] = now + minutes * 60
            failures.pop(name, None)
        return {'ok': True}

    def op_root_revoke(self, owner):
        grants, _, lock = self._root_grant_state()
        with lock:
            grants.pop(owner, None)
        return {'ok': True}

    def require_root_grant(self, owner):
        grants, _, lock = self._root_grant_state()
        with lock:
            deadline = grants.get(owner) if isinstance(owner, str) else None
        if deadline is None or deadline <= time.monotonic():
            raise Error('Root-Modus ist im Systemdienst nicht freigegeben. Im Administratormodus erneut anmelden.', 403)

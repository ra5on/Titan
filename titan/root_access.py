"""Short-lived root administration bound to one freshly authenticated web login.

The web process never changes Unix credentials. Only the existing local agent
runs trusted PTY/file workers, and an isolated demo never reaches host root.
"""
import threading
import time
import urllib.parse

from .core import Error, password_matches
from .security import record_login, verify_factor
from .terminal_http import terminal_owner


class RootAccessApplicationMixin:
    def initialize_root_access(self):
        self.root_access_grants = {}
        self.root_access_lock = threading.RLock()

    def _root_user_active(self, user):
        if user.get('role') not in (None, 'admin'):
            return False
        return self._terminal_user_active(user)

    def root_access_active(self, user):
        if not hasattr(self, 'root_access_grants'):
            return False
        owner = terminal_owner(user)
        expired = False
        with self.root_access_lock:
            grant = self.root_access_grants.get(owner)
            if not grant:
                return False
            if time.monotonic() >= grant['deadline'] or not self._root_user_active(user):
                self.root_access_grants.pop(owner, None)
                expired = True
        if expired:
            self.close_root_terminal_owner(owner)
            self.store.audit(user['name'], 'root_access_expired', 'Root-Modus beendet')
            return False
        return True

    def root_access_status(self, user):
        if user.get('role') != 'admin' or not self._root_user_active(user):
            raise Error('Root-Modus erfordert eine aktive Administratoranmeldung.', 403)
        enabled = self.root_access_active(user)
        with self.root_access_lock:
            grant = self.root_access_grants.get(terminal_owner(user), {}) if enabled else {}
        with self.store.connection() as db:
            factor = db.execute('SELECT enabled FROM second_factors WHERE username=?', (user['name'],)).fetchone()
        return {'enabled': enabled, 'expires': grant.get('expires'),
                'remaining_seconds': max(0, int(grant.get('deadline', 0) - time.monotonic())) if enabled else 0,
                'two_factor_required': bool(factor and factor['enabled']), 'demo': self.demo,
                'default_minutes': 15, 'maximum_minutes': 30}

    def enable_root_access(self, user, body, address='', user_agent=''):
        from .login_protection import blocked, blocked_error, capacity_delay, failure, settings, source_address
        if user.get('role') != 'admin' or not self._root_user_active(user):
            raise Error('Root-Modus erfordert eine aktive Administratoranmeldung.', 403)
        if not isinstance(body, dict) or set(body) - {'password', 'otp', 'minutes'} or 'password' not in body:
            raise Error('Aktuelles Passwort und gegebenenfalls Sicherheitscode angeben.')
        password, minutes = body['password'], body.get('minutes', 15)
        if not isinstance(password, str) or not password or len(password) > 1024:
            raise Error('Aktuelles Passwort angeben.')
        if type(minutes) is not int or not 1 <= minutes <= 30:
            raise Error('Root-Modus kann für 1 bis 30 Minuten aktiviert werden.')
        accepted, delay = False, 0
        address = source_address(address)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            now = time.time()
            policy = settings(db)
            delay = blocked(db, policy, user['name'], address, now) or capacity_delay(db, policy, user['name'], address)
            if not delay:
                row = db.execute('SELECT password,role,enabled FROM users WHERE name=?', (user['name'],)).fetchone()
                valid = row and row['enabled'] and row['role'] == 'admin' and (self.demo or password_matches(password, row['password']))
                accepted = bool(valid and verify_factor(db, user['name'], body.get('otp'), now))
                if not accepted:
                    failure(db, policy, user['name'], address, now)
            record_login(db, user['name'], accepted, address, user_agent)
        if delay:
            raise blocked_error(delay)
        if not accepted:
            self.store.audit(user['name'], 'root_access_denied', 'Erneute Anmeldung fehlgeschlagen')
            raise Error('Passwort oder Sicherheitscode ist falsch.', 403)
        # Do not authorize a login revoked while its password hash was checked.
        if not self._root_user_active(user):
            raise Error('Administratoranmeldung ist nicht mehr gültig.', 403)
        owner = terminal_owner(user)
        with self.root_access_lock:
            if owner not in self.root_access_grants and len(self.root_access_grants) >= 64:
                raise Error('Zu viele aktive Administratorfreigaben.', 429)
            self.root_access_grants[owner] = {'name': user['name'], 'csrf': user['csrf'],
                'expires': time.time() + minutes * 60, 'deadline': time.monotonic() + minutes * 60}
        self._start_terminal_reaper()
        self.store.audit(user['name'], 'root_access_enabled', f'Root-Modus für {minutes} Minuten' + (' · isolierte Demo' if self.demo else ''))
        return self.root_access_status(user)

    def disable_root_access(self, user, reason='Root-Modus beendet'):
        owner = terminal_owner(user)
        with self.root_access_lock:
            grant = self.root_access_grants.pop(owner, None)
        self.close_root_terminal_owner(owner)
        if grant:
            self.store.audit(user['name'], 'root_access_disabled', reason)
        return {'enabled': False, 'expires': None, 'remaining_seconds': 0, 'demo': self.demo}

    def require_root_access(self, user):
        if user.get('role') != 'admin' or not self.root_access_active(user):
            raise Error('Root-Modus ist nicht aktiv oder abgelaufen. Im Administratormodus erneut anmelden.', 403)

    def root_access_deadline(self, user):
        """Same-host monotonic lease, enforced again by the privileged agent."""
        self.require_root_access(user)
        with self.root_access_lock:
            grant = self.root_access_grants.get(terminal_owner(user))
            if not grant or grant['deadline'] <= time.monotonic():
                raise Error('Root-Modus ist nicht mehr aktiv.', 403)
            return grant['deadline']

    def close_root_terminal_owner(self, owner):
        with self.terminal_sessions_lock:
            keys = [key for key, entry in self.terminal_sessions.items() if key[0] == owner and entry.get('root')]
        for session_owner, session_id in keys:
            self.close_terminal_session(session_owner, session_id)

    def reap_root_access(self):
        with self.root_access_lock:
            users = [dict(value, role='admin') for value in self.root_access_grants.values()]
        for user in users:
            self.root_access_active(user)


class RootAccessHTTPMixin:
    def root_access_get(self, path, user, query):
        if path not in ('/api/root-access', '/api/root-terminal/output'):
            return False
        self.require_user(admin=True)
        if path == '/api/root-access':
            if urllib.parse.urlsplit(self.path).query:
                raise Error('Root-Modus unterstützt keine zusätzlichen Parameter.')
            self.reply(self.app.root_access_status(user))
        else:
            self.origin_check()
            pairs = urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query, keep_blank_values=True)
            if len(pairs) != 1 or pairs[0][0] != 'id':
                raise Error('Genau eine Root-Terminalsitzung angeben.')
            self.app.require_root_access(user)
            self.terminal_stream(user, dict(pairs), root_mode=True)
        return True

    def root_access_post(self, path, user, body):
        if path not in ('/api/root-access', '/api/root-terminal'):
            return False
        self.require_user(admin=True, mutation=True)
        if path == '/api/root-terminal':
            # Close remains possible after the grant expires, for cleanup.
            if body.get('action') != 'close':
                self.app.require_root_access(user)
            self.terminal_post(user, body, root_mode=True)
        elif body == {'enabled': False}:
            self.reply(self.app.disable_root_access(user))
        else:
            self.reply(self.app.enable_root_access(user, body, self.authentication_address(), self.headers.get('User-Agent', '')))
        return True

    def root_system_file_call(self, user, arguments):
        self.app.require_root_access(user)
        if self.app.demo:
            return demo_root_file(self.app.agent, **arguments)
        return self.app.agent.call('root_system_file', **arguments)


def demo_root_file(demo, action, path='', **arguments):
    """Only the demo's generated filesystem; never '/', even for a root label."""
    from .system_files import ALLOWED, SYSTEM_SHARE, operate_system
    if action not in ALLOWED or set(arguments) - ALLOWED[action]:
        raise Error('Ungültige Systemdateiaktion oder zusätzliche Parameter.')
    destination_system = action == 'rename'
    if action in ('copy', 'move'):
        target = arguments.pop('destination_share', None) or SYSTEM_SHARE
        destination_system = target == SYSTEM_SHARE
        if not destination_system:
            if target not in demo._share_paths:
                raise Error('Zielfreigabe nicht verfügbar.', 403)
            arguments['destination_root'] = str(demo._share_paths[target])
    return operate_system(str(demo._system_path), action, path,
        system_path_root=str(demo._system_path), destination_system=destination_system,
        root_access=True, **arguments)

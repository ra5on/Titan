"""Local two-factor authentication and inspectable, revocable web sessions.

TOTP uses RFC 6238 / RFC 4226 (SHA-1, 30 seconds, six digits). Codes are
accepted once, including recovery codes, in the same database transaction.
Secrets never leave this module except during password-confirmed enrollment.
"""
import base64
import hashlib
import hmac
import re
import secrets
import struct
import time
import urllib.parse
from .core import Error, password_matches


def totp(secret, counter, digits=6):
    key = base64.b32decode(secret + '=' * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    number = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7fffffff
    return str(number % 10 ** digits).zfill(digits)


def recovery_digest(value):
    return hashlib.sha256(value.strip().replace('-', '').upper().encode()).hexdigest()


def initialize_security(db):
    from .login_protection import initialize as initialize_login_protection
    db.executescript('''
        CREATE TABLE IF NOT EXISTS second_factors (username TEXT PRIMARY KEY,
          secret TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 0,
          last_counter INTEGER NOT NULL DEFAULT -1, pending TEXT NOT NULL DEFAULT '', pending_expires REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS recovery_codes (username TEXT NOT NULL, digest TEXT NOT NULL,
          PRIMARY KEY(username,digest));
        CREATE TABLE IF NOT EXISTS login_events (id INTEGER PRIMARY KEY, time REAL NOT NULL,
          username TEXT NOT NULL, success INTEGER NOT NULL, address TEXT NOT NULL, user_agent TEXT NOT NULL);
    ''')
    columns = {row[1] for row in db.execute('PRAGMA table_info(sessions)')}
    for field, definition in {'created': 'REAL NOT NULL DEFAULT 0', 'last_seen': 'REAL NOT NULL DEFAULT 0',
                              'address': "TEXT NOT NULL DEFAULT ''", 'user_agent': "TEXT NOT NULL DEFAULT ''"}.items():
        if field not in columns:
            db.execute(f'ALTER TABLE sessions ADD COLUMN {field} {definition}')
    initialize_login_protection(db)


def record_login(db, username, success, address='', user_agent=''):
    # UI displays escaped text; strip controls and cap lengths before persistence.
    clean = lambda value, maximum: ''.join(char for char in str(value) if ord(char) >= 32)[:maximum]
    db.execute('INSERT INTO login_events(time,username,success,address,user_agent) VALUES (?,?,?,?,?)',
               (time.time(), clean(username, 64), int(success), clean(address, 64), clean(user_agent, 256)))
    db.execute('DELETE FROM login_events WHERE id < (SELECT COALESCE(MAX(id),0)-2000 FROM login_events)')


def verify_factor(db, name, code, now=None):
    factor = db.execute('SELECT * FROM second_factors WHERE username=? AND enabled=1', (name,)).fetchone()
    if not factor:
        return True
    if not isinstance(code, str) or len(code) > 64:
        return False
    now = time.time() if now is None else now
    if re.fullmatch(r'[0-9]{6}', code):
        counter = int(now // 30)
        for candidate in (counter, counter - 1, counter + 1):
            if candidate > factor['last_counter'] and hmac.compare_digest(totp(factor['secret'], candidate), code):
                db.execute('UPDATE second_factors SET last_counter=? WHERE username=?', (candidate, name))
                return True
    digest = recovery_digest(code)
    deleted = db.execute('DELETE FROM recovery_codes WHERE username=? AND digest=?', (name, digest)).rowcount
    return bool(deleted)


class Security:
    def __init__(self, store, demo=False):
        self.store, self.demo = store, demo
        from .login_protection import LoginProtection
        self.login_protection = LoginProtection(store)

    def _password(self, db, name, password):
        row = db.execute('SELECT password,enabled FROM users WHERE name=?', (name,)).fetchone()
        if not row or not row['enabled'] or (not self.demo and not password_matches(password, row['password'])):
            raise Error('Das aktuelle Passwort ist falsch.', 403)

    def overview(self, actor, token='', all_users=False):
        with self.store.connection() as db:
            factor = db.execute('SELECT enabled FROM second_factors WHERE username=?', (actor,)).fetchone()
            remaining = db.execute('SELECT COUNT(*) FROM recovery_codes WHERE username=?', (actor,)).fetchone()[0]
            condition, args = ('', ()) if all_users else (' AND username=?', (actor,))
            sessions = [dict(row) for row in db.execute('SELECT substr(token,1,32) AS id,username,created,last_seen,address,user_agent,expires FROM sessions WHERE expires>?' + condition + ' ORDER BY last_seen DESC', (time.time(), *args))]
            current = hashlib.sha256(token.encode()).hexdigest()[:32] if token else ''
            for item in sessions:
                item['current'] = bool(current and hmac.compare_digest(item['id'], current))
            events = [dict(row) for row in db.execute('SELECT * FROM login_events' + ('' if all_users else ' WHERE username=?') + ' ORDER BY id DESC LIMIT 100', () if all_users else (actor,))]
            result = {'two_factor': bool(factor and factor['enabled']), 'recovery_remaining': remaining,
                      'sessions': sessions, 'login_events': events, 'all_users': all_users}
            if all_users:
                result['two_factor_user_count'] = db.execute('SELECT COUNT(*) FROM second_factors f JOIN users u ON u.name=f.username WHERE f.enabled=1 AND u.enabled=1').fetchone()[0]
            return result

    def begin(self, actor, password):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._password(db, actor, password)
            current = db.execute('SELECT enabled FROM second_factors WHERE username=?', (actor,)).fetchone()
            if current and current['enabled']:
                raise Error('Zwei-Faktor-Anmeldung ist bereits aktiv.', 409)
            secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')
            db.execute('INSERT INTO second_factors(username,pending,pending_expires) VALUES (?,?,?) ON CONFLICT(username) DO UPDATE SET pending=excluded.pending,pending_expires=excluded.pending_expires', (actor, secret, time.time() + 600))
            label = urllib.parse.quote('Titan:' + actor, safe='')
            return {'secret': secret, 'uri': f'otpauth://totp/{label}?secret={secret}&issuer=Titan&algorithm=SHA1&digits=6&period=30', 'expires_in': 600}

    def confirm(self, actor, password, code, current_token=None):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._password(db, actor, password)
            current = db.execute('SELECT * FROM second_factors WHERE username=?', (actor,)).fetchone()
            counter = int(time.time() // 30)
            valid_code = isinstance(code, str) and re.fullmatch(r'[0-9]{6}', code)
            match = next((value for value in (counter, counter - 1, counter + 1) if current and current['pending'] and valid_code and hmac.compare_digest(totp(current['pending'], value), code)), None)
            if not current or current['enabled'] or current['pending_expires'] < time.time() or match is None:
                raise Error('Sicherheitscode falsch oder Einrichtung abgelaufen.', 403)
            db.execute("UPDATE second_factors SET secret=pending,enabled=1,last_counter=?,pending='',pending_expires=0 WHERE username=?", (match, actor))
            current_hash = hashlib.sha256(current_token.encode()).hexdigest() if current_token else ''
            db.execute('DELETE FROM sessions WHERE username=? AND token<>?', (actor, current_hash))
            codes = self._new_codes(db, actor)
        self.store.audit(actor, 'two_factor_enabled')
        return {'ok': True, 'recovery_codes': codes, 'sessions_revoked': True}

    @staticmethod
    def _new_codes(db, actor):
        db.execute('DELETE FROM recovery_codes WHERE username=?', (actor,))
        values = [secrets.token_hex(10).upper() for _ in range(10)]
        codes = ['-'.join(value[i:i+5] for i in range(0,20,5)) for value in values]
        db.executemany('INSERT INTO recovery_codes VALUES (?,?)', [(actor, recovery_digest(code)) for code in codes])
        return codes

    def disable(self, actor, password, code, current_token=None):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._password(db, actor, password)
            if not verify_factor(db, actor, code):
                raise Error('Sicherheitscode ist falsch oder wurde bereits benutzt.', 403)
            db.execute('DELETE FROM second_factors WHERE username=?', (actor,))
            db.execute('DELETE FROM recovery_codes WHERE username=?', (actor,))
            current_hash = hashlib.sha256(current_token.encode()).hexdigest() if current_token else ''
            db.execute('DELETE FROM sessions WHERE username=? AND token<>?', (actor, current_hash))
        self.store.audit(actor, 'two_factor_disabled')
        return {'ok': True, 'sessions_revoked': True}

    def recoveries(self, actor, password, code):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._password(db, actor, password)
            factor = db.execute('SELECT enabled FROM second_factors WHERE username=?', (actor,)).fetchone()
            if not factor or not factor['enabled'] or not verify_factor(db, actor, code):
                raise Error('Ein gültiger Sicherheitscode ist erforderlich.', 403)
            codes = self._new_codes(db, actor)
        self.store.audit(actor, 'recovery_codes_changed')
        return {'ok': True, 'recovery_codes': codes}

    def revoke(self, actor, session_id, admin=False):
        if not isinstance(session_id, str) or not re.fullmatch(r'[a-f0-9]{32}', session_id):
            raise Error('Ungültige Sitzungskennung.')
        with self.store.connection() as db:
            query = 'DELETE FROM sessions WHERE substr(token,1,32)=?'
            args = (session_id,)
            if not admin:
                query += ' AND username=?'
                args += (actor,)
            if not db.execute(query, args).rowcount:
                raise Error('Sitzung nicht gefunden.', 404)
        self.store.audit(actor, 'session_revoked', session_id)
        return {'ok': True}

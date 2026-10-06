"""Persistent protection for Titan web logins, without global account lockout.

An IP rule counts failed logins across usernames. The account rule applies to
one username and source IP, so an attacker cannot deny that account access from
another device. Both are evaluated inside Store.login's SQLite write transaction.
This is application login protection, not a host firewall or an SMB policy.
"""
import copy
import hashlib
import ipaddress
import json
import math
import re
import secrets
import time

from .core import Error, configuration_lock


DEFAULTS = {
    'schema': 1,
    'ip': {'enabled': True, 'attempts': 5, 'window_minutes': 5, 'block_minutes': 15},
    'account': {'enabled': True, 'attempts': 5, 'window_minutes': 5, 'block_minutes': 15},
}
CONFIG_KEY = 'login_protection'
MAX_TRACKERS = 4096
BLOCK_MESSAGE = 'Anmeldung vorübergehend gesperrt. Bitte später erneut versuchen.'
SCOPE_NOTE = ('Der Anmeldeschutz gilt für die Titan-Webanmeldung. Kontoschutz gilt je '
              'Konto und IP-Adresse; Anmeldungen von anderen IP-Adressen bleiben möglich.')


def initialize(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS login_protection_failures (
          kind TEXT NOT NULL CHECK(kind IN ('ip','account')), address TEXT NOT NULL,
          username TEXT NOT NULL, timestamps TEXT NOT NULL, updated REAL NOT NULL,
          PRIMARY KEY(kind,address,username));
        CREATE INDEX IF NOT EXISTS login_protection_failures_updated
          ON login_protection_failures(updated);
        CREATE TABLE IF NOT EXISTS login_protection_blocks (
          id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('ip','account')),
          address TEXT NOT NULL, username TEXT NOT NULL, blocked_at REAL NOT NULL,
          expires REAL NOT NULL, reason TEXT NOT NULL, UNIQUE(kind,address,username));
        CREATE INDEX IF NOT EXISTS login_protection_blocks_expires
          ON login_protection_blocks(expires);
    ''')


def validate_settings(value):
    if not isinstance(value, dict) or set(value) != {'schema', 'ip', 'account'} or type(value['schema']) is not int or value['schema'] != 1:
        raise Error('Ungültige Einstellungen für den Anmeldeschutz.')
    result = {'schema': 1}
    for kind in ('ip', 'account'):
        rule = value[kind]
        if not isinstance(rule, dict) or set(rule) != {'enabled', 'attempts', 'window_minutes', 'block_minutes'} or type(rule['enabled']) is not bool:
            raise Error('Ungültige Einstellungen für den Anmeldeschutz.')
        for field, maximum in (('attempts', 100), ('window_minutes', 1440), ('block_minutes', 10080)):
            if type(rule[field]) is not int or not 1 <= rule[field] <= maximum:
                raise Error(f'Anmeldeschutz: {field} muss eine ganze Zahl zwischen 1 und {maximum} sein.')
        result[kind] = dict(rule)
    return result


def settings(db):
    row = db.execute('SELECT value FROM config WHERE key=?', (CONFIG_KEY,)).fetchone()
    return validate_settings(json.loads(row[0])) if row else copy.deepcopy(DEFAULTS)


def revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def source_address(value):
    # No caller-controlled aliases or IPv4-mapped IPv6 aliases split a bucket.
    try:
        address = ipaddress.ip_address(value)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return str(address)
    except (ValueError, TypeError):
        return 'unknown'


def cleanup(db, policy, now):
    db.execute('DELETE FROM login_protection_blocks WHERE expires<=?', (now,))
    longest = max(rule['window_minutes'] * 60 for kind, rule in policy.items() if kind != 'schema')
    db.execute('DELETE FROM login_protection_failures WHERE updated<=?', (now - longest,))


def blocked(db, policy, username, address, now):
    cleanup(db, policy, now)
    candidates = db.execute('SELECT kind,expires FROM login_protection_blocks WHERE address=? '
                            'AND (kind=\'ip\' OR username=?) AND expires>?', (address, username, now))
    delays = [math.ceil(row['expires'] - now) for row in candidates if policy[row['kind']]['enabled']]
    return max(delays, default=0)


def failure(db, policy, username, address, now):
    """Record one failed password/factor result; never extend an existing block."""
    for kind in ('ip', 'account'):
        rule = policy[kind]
        if not rule['enabled']:
            continue
        subject = '' if kind == 'ip' else username
        key = (kind, address, subject)
        row = db.execute('SELECT timestamps FROM login_protection_failures WHERE kind=? AND address=? AND username=?', key).fetchone()
        stamps = [stamp for stamp in json.loads(row[0]) if now - rule['window_minutes'] * 60 < stamp <= now] if row else []
        stamps.append(now)
        if len(stamps) >= rule['attempts']:
            # Existing active blocks are never evicted to free space. The normal
            # path can hold at most one block for each bounded failure tracker.
            if db.execute('SELECT COUNT(*) FROM login_protection_blocks').fetchone()[0] >= MAX_TRACKERS:
                continue
            reason = f"{rule['attempts']} fehlgeschlagene Anmeldungen innerhalb von {rule['window_minutes']} Minuten"
            db.execute('INSERT INTO login_protection_blocks(id,kind,address,username,blocked_at,expires,reason) '
                       'VALUES (?,?,?,?,?,?,?) ON CONFLICT(kind,address,username) DO NOTHING',
                       (secrets.token_hex(16), *key, now, now + rule['block_minutes'] * 60, reason))
            db.execute('DELETE FROM login_protection_failures WHERE kind=? AND address=? AND username=?', key)
        elif row or db.execute('SELECT COUNT(*) FROM login_protection_failures').fetchone()[0] < MAX_TRACKERS:
            db.execute('INSERT INTO login_protection_failures(kind,address,username,timestamps,updated) VALUES (?,?,?,?,?) '
                       'ON CONFLICT(kind,address,username) DO UPDATE SET timestamps=excluded.timestamps,updated=excluded.updated',
                       (*key, json.dumps(stamps[-100:]), now))


def capacity_delay(db, policy, username, address):
    """Fail closed for a new source when bounded state is saturated."""
    rules = [(kind, '' if kind == 'ip' else username) for kind in ('ip', 'account') if policy[kind]['enabled']]
    if not rules:
        return 0
    if db.execute('SELECT COUNT(*) FROM login_protection_blocks').fetchone()[0] >= MAX_TRACKERS:
        return 60
    if db.execute('SELECT COUNT(*) FROM login_protection_failures').fetchone()[0] >= MAX_TRACKERS:
        for kind, subject in rules:
            if not db.execute('SELECT 1 FROM login_protection_failures WHERE kind=? AND address=? AND username=?', (kind, address, subject)).fetchone():
                return 60
    return 0


def blocked_error(delay):
    error = Error(BLOCK_MESSAGE, 429)
    error.retry_after = min(604800, max(1, int(delay)))
    return error


class LoginProtection:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _admin(db, actor):
        row = db.execute('SELECT role,enabled FROM users WHERE name=?', (actor,)).fetchone()
        if not row or not row['enabled'] or row['role'] != 'admin':
            raise Error('Administratorrechte erforderlich.', 403)

    @staticmethod
    def _overview(db, policy, now):
        cleanup(db, policy, now)
        blocks = [{**dict(row), 'type': row['kind'], 'remaining_seconds': max(0, math.ceil(row['expires'] - now))}
                  for row in db.execute('SELECT id,kind,address,username,blocked_at,expires,reason '
                                        'FROM login_protection_blocks WHERE expires>? ORDER BY expires DESC,id LIMIT 200', (now,))
                  if policy[row['kind']]['enabled']]
        return {'settings': policy, 'revision': revision(policy), 'blocks': blocks,
                'blocked_count': db.execute('SELECT COUNT(*) FROM login_protection_blocks WHERE expires>?', (now,)).fetchone()[0],
                'scope_note': SCOPE_NOTE}

    def overview(self, actor):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._admin(db, actor)
            return self._overview(db, settings(db), time.time())

    def save(self, actor, value, expected_revision):
        policy = validate_settings(value)
        if not isinstance(expected_revision, str) or not re.fullmatch('[a-f0-9]{64}', expected_revision):
            raise Error('Aktuellen Stand des Anmeldeschutzes angeben.')
        with configuration_lock(self.store.directory), self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._admin(db, actor)
            if not secrets.compare_digest(revision(settings(db)), expected_revision):
                raise Error('Anmeldeschutz wurde zwischenzeitlich geändert. Bitte Ansicht neu laden.', 409)
            for kind in ('ip', 'account'):
                if not policy[kind]['enabled']:
                    db.execute('DELETE FROM login_protection_blocks WHERE kind=?', (kind,))
                    db.execute('DELETE FROM login_protection_failures WHERE kind=?', (kind,))
            db.execute('INSERT INTO config(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       (CONFIG_KEY, json.dumps(policy)))
            result = self._overview(db, policy, time.time())
        self.store.audit(actor, 'login_protection_changed')
        return result

    def unblock(self, actor, block_id):
        if not isinstance(block_id, str) or not re.fullmatch('[a-f0-9]{32}', block_id):
            raise Error('Gültige Anmeldesperre auswählen.')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._admin(db, actor)
            policy = settings(db)
            cleanup(db, policy, time.time())
            row = db.execute('SELECT kind,address,username FROM login_protection_blocks WHERE id=?', (block_id,)).fetchone()
            if not row:
                raise Error('Anmeldesperre ist bereits aufgehoben oder abgelaufen.', 404)
            db.execute('DELETE FROM login_protection_blocks WHERE id=?', (block_id,))
            db.execute('DELETE FROM login_protection_failures WHERE kind=? AND address=? AND username=?', tuple(row))
            result = {'ok': True, **self._overview(db, policy, time.time())}
        self.store.audit(actor, 'login_protection_unblocked', f"{row['kind']} {row['address']} {row['username']}")
        return result

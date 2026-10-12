"""Titan-owned Guacamole sessions: same-origin, CSRF protected, login scoped."""
import codecs
import hashlib
import logging
import secrets
import select
import socket
import threading
import time
import urllib.parse

from .core import Error, integer
from .identity import require_application
from .guacamole_protocol import Frames, Instructions, frame, handshake, instruction, websocket_accept
from .desktop_runtime import PORT, IDENTITY


def owner(user):
    return hashlib.sha256((user['name'] + '\0' + user['csrf']).encode()).hexdigest()


def validate_create(body):
    if set(body) != {'kind', 'target', 'width', 'height'} or body['kind'] not in ('app', 'vm'):
        raise Error('App oder VM und Fenstergröße angeben.')
    if not isinstance(body['target'], str) or not 1 <= len(body['target']) <= 128:
        raise Error('Ungültiges Sitzungsziel.')
    for key, lower, upper in (('width', 640, 2560), ('height', 480, 1600)):
        if type(body[key]) is not int:
            raise Error('Fenstergröße muss eine ganze Zahl sein.')
        integer(body[key], lower, upper)
    return body


class DesktopApplicationMixin:
    def initialize_desktops(self):
        self.desktops = {}
        self.desktop_lock = threading.RLock()
        self.desktop_creating = threading.Lock()
        self.desktop_reaper = None

    def desktop_active(self, entry):
        try:
            if not self.demo:
                with self.store.connection() as db:
                    row = db.execute('SELECT 1 FROM sessions WHERE username=? AND csrf=? AND expires>?',
                                     (entry['user']['name'], entry['user']['csrf'], time.time())).fetchone()
                if not row:
                    return False
            require_application(self.store, entry['user'], 'apps' if entry['kind'] == 'app' else 'vms')
            return not self.stop.is_set()
        except Exception:
            return False

    def desktop_entry(self, user, id):
        if not isinstance(id, str) or not IDENTITY.fullmatch(id):
            raise Error('Ungültige Sitzung.')
        with self.desktop_lock:
            entry = self.desktops.get(id)
        if not entry or entry['owner'] != owner(user):
            raise Error('Sitzung nicht gefunden.', 404)
        if entry['created'] == 0:
            raise Error('Sitzung wird beendet.', 410)
        if not self.desktop_active(entry):
            raise Error('Anmeldung oder Berechtigung ist nicht mehr gültig.', 403)
        return entry

    def desktop_create(self, user, body):
        body = validate_create(body)
        require_application(self.store, user, 'apps' if body['kind'] == 'app' else 'vms')
        if self.demo:
            raise Error('Die Demo startet keine Fernsitzungen. Dafür ist eine Titan-Installation erforderlich.', 409)
        with self.desktop_creating:
            with self.desktop_lock:
                candidates = [(id, entry) for id, entry in self.desktops.items() if
                              entry['owner'] == owner(user) and entry['kind'] == body['kind'] and
                              entry['target'] == body['target'] and entry['created'] != 0]
            for id, entry in candidates:
                running = entry['kind'] == 'vm' or self.agent.call('desktop_probe', id=id).get('running')
                if not running or not self.desktop_active(entry):
                    self.desktop_close(id)
                    continue
                with self.desktop_lock:
                    if self.desktops.get(id) is entry and entry['created'] != 0:
                        entry['touched'] = time.monotonic()
                        return {'id': id}
            with self.desktop_lock:
                if len(self.desktops) >= 8 or sum(e['owner'] == owner(user) for e in self.desktops.values()) >= 4:
                    raise Error('Maximal vier Sitzungen pro Anmeldung und acht insgesamt. Eine Sitzung beenden.', 429)
            id = secrets.token_hex(32)
            endpoint = self.agent.call('desktop_open', id=id, **body)
            entry = {'owner': owner(user), 'user': dict(user), **body, 'endpoint': endpoint,
                     'created': time.monotonic(), 'touched': time.monotonic(), 'stream': None}
            with self.desktop_lock:
                self.desktops[id] = entry
                if self.desktop_reaper is None:
                    self.desktop_reaper = threading.Thread(target=self._desktop_reap_loop, daemon=True, name='titan-desktop-sessions')
                    self.desktop_reaper.start()
            if not self.desktop_active(entry):
                self.desktop_close(id)
                raise Error('Anmeldung wurde während des Starts beendet.', 403)
            self.store.audit(user['name'], 'desktop_open', body['kind'] + ':' + body['target'])
            return {'id': id}

    def desktop_close(self, id):
        with self.desktop_lock:
            entry = self.desktops.pop(id, None)
        if entry:
            stream = entry['stream']
            if stream:
                try:
                    stream.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            if entry['kind'] == 'app':
                try:
                    self.agent.call('desktop_close', id=id)
                except Error:
                    # Retain a tombstone so the reaper retries cleanup.
                    entry['created'] = 0
                    with self.desktop_lock:
                        self.desktops[id] = entry

    def close_desktop_owner(self, user):
        with self.desktop_lock:
            ids = [id for id, entry in self.desktops.items() if entry['owner'] == owner(user)]
        for id in ids:
            self.desktop_close(id)

    def reap_desktops(self):
        with self.desktop_lock:
            now = time.monotonic()
            ids = [id for id, entry in self.desktops.items() if entry['created'] == 0 or not self.desktop_active(entry) or
                   now - entry['created'] > 8 * 3600 or entry['stream'] is None and now - entry['touched'] > 15 * 60]
        for id in ids:
            self.desktop_close(id)

    def _desktop_reap_loop(self):
        while not self.stop.wait(2):
            self.reap_desktops()
        self.close_all_desktops()

    def close_all_desktops(self):
        with self.desktop_lock:
            ids = list(self.desktops)
        for id in ids:
            self.desktop_close(id)


class DesktopHTTPMixin:
    def desktop_get(self, path, user, query):
        if path == '/api/desktops/status':
            if query:
                raise Error('Sitzungsstatus benötigt keine Optionen.')
            self.reply(self.app.agent.call('desktop_status'))
            return True
        if path == '/api/desktops/stream':
            if set(query) != {'id'}:
                raise Error('Genau eine Sitzung auswählen.')
            self.desktop_stream(user, query['id'])
            return True
        return False

    def desktop_post(self, path, user, body):
        if path == '/api/desktops/files':
            if set(body) != {'id', 'transfer'}:
                raise Error('Sitzung und Dateiaktion angeben.')
            entry = self.app.desktop_entry(user, body['id'])
            if entry['kind'] != 'app':
                raise Error('Dateiübertragung ist für Browser-Sitzungen verfügbar.', 409)
            self.reply(self.app.agent.call('desktop_files', **body))
            return True
        if path == '/api/desktops':
            self.reply(self.app.desktop_create(user, body))
            return True
        if path == '/api/desktops/close':
            if set(body) != {'id'}:
                raise Error('Genau eine Sitzung auswählen.')
            self.app.desktop_entry(user, body['id'])
            self.app.desktop_close(body['id'])
            self.reply({'ok': True})
            return True
        return False

    def desktop_stream(self, user, id):
        self.origin_check()
        if not self.headers.get('Origin'):
            raise Error('Origin fehlt.', 403)
        accept = websocket_accept(self.headers)
        entry = self.app.desktop_entry(user, id)
        with self.app.desktop_lock:
            if entry['stream'] is not None:
                raise Error('Diese Sitzung ist bereits in einem Fenster geöffnet.', 409)
            entry['stream'] = self.connection
        accepted = False
        upstream = None
        try:
            upstream = socket.create_connection(('127.0.0.1', PORT), timeout=10)
            if entry['kind'] == 'vm':
                entry['endpoint'] = self.app.agent.call('desktop_open', id=id, kind='vm', target=entry['target'], width=entry['width'], height=entry['height'])
            handshake(upstream, entry['endpoint'], entry['width'], entry['height'])
            self.app.desktop_entry(user, id)
            self.send_response(101)
            for key, value in {'Upgrade': 'websocket', 'Connection': 'Upgrade', 'Sec-WebSocket-Accept': accept,
                               'Sec-WebSocket-Protocol': 'guacamole', 'Cache-Control': 'no-store'}.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.flush()
            self.close_connection = True
            accepted = True
            self.connection.settimeout(5)
            upstream.settimeout(5)
            self.connection.sendall(frame(instruction('', id)))
            frames, parser = Frames(), Instructions()
            decoder = codecs.getincrementaldecoder('utf-8')('strict')
            checked = ping = time.monotonic()
            while not self.app.stop.is_set():
                now = time.monotonic()
                if now - checked >= 2:
                    self.app.desktop_entry(user, id)
                    entry['touched'] = now
                    checked = now
                if now - ping >= 15:
                    self.connection.sendall(frame(b'titan', 9)); ping = now
                ready, _, _ = select.select([self.connection, upstream], [], [], 1)
                for stream in ready:
                    data = stream.recv(65536)
                    if not data:
                        return
                    if stream is upstream:
                        text = decoder.decode(data)
                        if text:
                            self.connection.sendall(frame(text.encode()))
                    else:
                        for opcode, payload in frames.feed(data):
                            if opcode == 8:
                                return
                            if opcode == 9:
                                self.connection.sendall(frame(payload, 10))
                            if opcode != 1:
                                continue
                            for values in parser.feed(payload):
                                # No select/connect/require or arbitrary guacd
                                # parameters can pass the authenticated gateway.
                                if values[0] == '' and values[1:2] == ['ping']:
                                    self.connection.sendall(frame(instruction(*values)))
                                elif values[0] in ('sync', 'mouse', 'key', 'size', 'clipboard', 'blob', 'end', 'ack', 'nop', 'disconnect'):
                                    upstream.sendall(instruction(*values))
                                else:
                                    raise Error('Nicht erlaubte Sitzungsanweisung.', 403)
        except (OSError, UnicodeError, Error) as error:
            if not accepted:
                raise
            # Our protocol errors contain fixed messages, never remote payloads.
            logging.info('Desktop stream closed (%s): %s', type(error).__name__, str(error) if isinstance(error, Error) else 'connection interrupted')
        finally:
            if upstream:
                upstream.close()
            with self.app.desktop_lock:
                if entry['stream'] is self.connection:
                    entry['stream'] = None
                    entry['touched'] = time.monotonic()
            if accepted:
                try:
                    self.connection.sendall(frame(b'\x03\xe8', 8))
                except OSError:
                    pass

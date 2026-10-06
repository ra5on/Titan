"""Authenticated SSE output and CSRF-checked terminal input, without URL credentials."""
import base64
import binascii
import json
import re
import threading
import time

from .core import Error, integer


def terminal_owner(user):
    # The CSRF value is independently random for every login session. It never
    # appears in terminal URLs, audit details or PTY environment variables.
    return user['name'] + '.' + user['csrf']


def terminal_body(user, body):
    allowed = {'create': {'cols', 'rows'}, 'write': {'id', 'data'},
               'resize': {'id', 'cols', 'rows'}, 'close': {'id'}}
    action = body.get('action')
    if type(action) is not str or action not in allowed or set(body) - (allowed[action] | {'action'}):
        raise Error('Ungültige Terminalaktion oder zusätzliche Parameter.')
    arguments = {key: value for key, value in body.items() if key != 'action'}
    if action != 'create':
        if type(arguments.get('id')) is not str or not re.fullmatch(r'[a-f0-9]{64}', arguments['id']):
            raise Error('Ungültige Terminalsitzung.')
    if action in ('create', 'resize'):
        if action == 'resize' and not {'cols', 'rows'} <= arguments.keys():
            raise Error('Terminalgröße vollständig angeben.')
        if any(type(arguments.get(key, default)) is not int for key, default in (('cols', 100), ('rows', 30))):
            raise Error('Terminalgröße muss aus ganzen Zahlen bestehen.')
        arguments['cols'] = integer(arguments.get('cols', 100), 20, 500)
        arguments['rows'] = integer(arguments.get('rows', 30), 5, 200)
    if action == 'write':
        if type(arguments.get('data')) is not str or len(arguments['data']) > 22000:
            raise Error('Terminaleingabe ist zu groß oder ungültig.')
        try:
            data = base64.b64decode(arguments['data'], validate=True)
        except (ValueError, binascii.Error):
            raise Error('Terminaleingabe ist kein gültiges Base64.') from None
        if len(data) > 16384:
            raise Error('Terminaleingabe ist zu groß.')
    return 'terminal_' + action, {'owner': terminal_owner(user), **arguments}


class TerminalApplicationMixin:
    """Keep created PTYs tied to a still-valid administrator login.

    Registry entries contain trusted login metadata and timestamps only.  The
    agent owns terminal bytes and processes.  Lazy reaper startup keeps ordinary
    application instances without a terminal free of extra background threads.
    """

    def initialize_terminals(self):
        self.terminal_sessions = {}
        self.terminal_sessions_lock = threading.RLock()
        self._terminal_reaper_stop = threading.Event()
        self._terminal_reaper = None
        self._terminal_shutdown = False

    def _terminal_user_active(self, user):
        try:
            if self.demo:
                current = self.store.user_record(user['name'])
                return (user['csrf'] == 'demo-only' and current['enabled'] and
                        current['role'] == 'admin')
            with self.store.connection() as db:
                return db.execute(
                    "SELECT 1 FROM sessions JOIN users ON users.name=sessions.username "
                    "WHERE sessions.username=? AND sessions.csrf=? AND sessions.expires>? "
                    "AND users.enabled=1 AND users.role='admin'",
                    (user['name'], user['csrf'], time.time())).fetchone() is not None
        except Exception:
            # An unverifiable administrator login cannot retain a data PTY.
            return False

    def _start_terminal_reaper(self):
        with self.terminal_sessions_lock:
            if self._terminal_reaper is not None or self._terminal_shutdown:
                return
            self._terminal_reaper = threading.Thread(
                target=self._terminal_reaper_loop, name='titan-terminal-logins', daemon=True)
            self._terminal_reaper.start()

    def track_terminal(self, user, session_id):
        if type(session_id) is not str or not re.fullmatch(r'[a-f0-9]{64}', session_id):
            raise Error('Terminaldienst hat eine ungültige Sitzung geliefert.', 503)
        owner = terminal_owner(user)
        key = (owner, session_id)
        failure = None
        with self.terminal_sessions_lock:
            entry = self.terminal_sessions.get(key)
            if entry is None and len(self.terminal_sessions) >= 4:
                failure = Error('Maximale Anzahl an Terminalsitzungen erreicht.', 429)
            elif entry is None:
                now = time.monotonic()
                entry = self.terminal_sessions[key] = {
                    'name': user['name'], 'csrf': user['csrf'],
                    'created': now, 'activity': now, 'closing': False}
            if self._terminal_shutdown or self.stop.is_set():
                failure = Error('Terminaldienst wird beendet.', 503)
            elif not self._terminal_user_active(user):
                failure = Error('Administratoranmeldung ist nicht mehr gültig.', 403)
            elif entry is not None and entry['closing']:
                failure = Error('Terminalsitzung wird beendet.', 410)
            if failure is not None and entry is not None:
                entry['closing'] = True
        self._start_terminal_reaper()
        if failure is not None:
            self.close_terminal_session(owner, session_id)
            raise failure

    def touch_terminal(self, owner, session_id):
        with self.terminal_sessions_lock:
            entry = self.terminal_sessions.get((owner, session_id))
            if entry is not None and not entry['closing']:
                entry['activity'] = time.monotonic()

    def forget_terminal(self, owner, session_id):
        with self.terminal_sessions_lock:
            self.terminal_sessions.pop((owner, session_id), None)

    def close_terminal_session(self, owner, session_id):
        with self.terminal_sessions_lock:
            entry = self.terminal_sessions.get((owner, session_id))
            if entry is not None:
                entry['closing'] = True
        try:
            self.agent.call('terminal_close', owner=owner, id=session_id)
        except Error as exc:
            if exc.status not in (404, 410):
                return False
        except Exception:
            return False
        self.forget_terminal(owner, session_id)
        return True

    def close_terminal_owner(self, owner):
        with self.terminal_sessions_lock:
            keys = [key for key in self.terminal_sessions if key[0] == owner]
            for key in keys:
                self.terminal_sessions[key]['closing'] = True
        for session_owner, session_id in keys:
            self.close_terminal_session(session_owner, session_id)

    def reap_terminals(self):
        with self.terminal_sessions_lock:
            now = time.monotonic()
            keys = []
            for key, entry in self.terminal_sessions.items():
                if (entry['closing'] or now - entry['activity'] >= 15 * 60 or
                        now - entry['created'] >= 8 * 60 * 60 or
                        not self._terminal_user_active(entry)):
                    entry['closing'] = True
                    keys.append(key)
        for owner, session_id in keys:
            self.close_terminal_session(owner, session_id)

    def _terminal_reaper_loop(self):
        try:
            while not self._terminal_reaper_stop.wait(2):
                if self.stop.is_set():
                    break
                self.reap_terminals()
        finally:
            self.close_all_terminals()

    def close_all_terminals(self):
        with self.terminal_sessions_lock:
            self._terminal_shutdown = True
            self._terminal_reaper_stop.set()
            keys = list(self.terminal_sessions)
            for key in keys:
                self.terminal_sessions[key]['closing'] = True
            reaper = self._terminal_reaper
        for owner, session_id in keys:
            self.close_terminal_session(owner, session_id)
        if reaper is not None and reaper is not threading.current_thread():
            reaper.join(timeout=5)


class TerminalHTTPMixin:
    def terminal_post(self, user, body):
        operation, arguments = terminal_body(user, body)
        result = self.app.agent.call(operation, **arguments)
        if operation == 'terminal_create':
            session_id = result.get('id') if isinstance(result, dict) else None
            try:
                self.app.track_terminal(user, session_id)
                self.app.store.audit(user['name'], operation, 'Terminalsitzung geöffnet')
                return self.reply(result)
            except Exception:
                if type(session_id) is str and re.fullmatch(r'[a-f0-9]{64}', session_id):
                    self.app.close_terminal_session(arguments['owner'], session_id)
                raise
        if operation == 'terminal_close':
            self.app.forget_terminal(arguments['owner'], arguments['id'])
        elif operation == 'terminal_write' and arguments['data']:
            self.app.touch_terminal(arguments['owner'], arguments['id'])
        if operation in ('terminal_create', 'terminal_close'):
            self.app.store.audit(user['name'], operation, 'Terminalsitzung geöffnet' if operation == 'terminal_create' else 'Terminalsitzung geschlossen')
        return self.reply(result)

    def terminal_stream(self, user, query):
        if set(query) != {'id'}:
            raise Error('Terminalsitzung angeben.')
        _, arguments = terminal_body(user, {'action': 'close', 'id': query['id']})
        key = (arguments['owner'], arguments['id'])
        with self.app.terminal_stream_lock:
            if key in self.app.terminal_streams:
                raise Error('Die Terminalsitzung ist bereits verbunden.', 409)
            self.app.terminal_streams.add(key)
        accepted = False
        owned = False
        try:
            pending = self.app.agent.call('terminal_poll', **arguments, timeout=0)
            owned = True
            self.app.track_terminal(user, arguments['id'])
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
            self.close_connection = True
            accepted = True
            last_ping = time.monotonic()
            while not self.app.stop.is_set():
                current = self.user()
                if not current or current['role'] != 'admin' or terminal_owner(current) != arguments['owner']:
                    self.terminal_event('exit', {'error': 'Terminalsitzung beendet: Anmeldung oder Administratorrechte nicht mehr gültig.'})
                    return
                result = pending if pending is not None else self.app.agent.call('terminal_poll', **arguments, timeout=0.5)
                pending = None
                current = self.user()
                if not current or current['role'] != 'admin' or terminal_owner(current) != arguments['owner']:
                    self.terminal_event('exit', {'error': 'Terminalsitzung beendet: Anmeldung oder Administratorrechte nicht mehr gültig.'})
                    return
                if result.get('data'):
                    self.terminal_event('output', {'data': result['data']})
                if result.get('eof'):
                    self.terminal_event('exit', {'exit_code': result.get('exit_code')})
                    return
                if time.monotonic() - last_ping >= 10:
                    self.wfile.write(b': heartbeat\n\n')
                    self.wfile.flush()
                    last_ping = time.monotonic()
                # Bound output delivery, even when an administrator runs "yes".
                self.app.stop.wait(0.05)
        except OSError:
            pass
        except Error as exc:
            if not accepted:
                raise
            try:
                self.terminal_event('exit', {'error': str(exc)})
            except OSError:
                pass
        finally:
            with self.app.terminal_stream_lock:
                self.app.terminal_streams.discard(key)
            if owned:
                self.app.close_terminal_session(arguments['owner'], arguments['id'])

    def terminal_event(self, name, value):
        self.wfile.write(('event: ' + name + '\ndata: ' + json.dumps(value, ensure_ascii=True) + '\n\n').encode())
        self.wfile.flush()

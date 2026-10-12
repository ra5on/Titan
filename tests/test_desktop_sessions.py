from email.message import Message
import io
import json
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from titan.core import Error, Store
from titan.desktop_sessions import DesktopApplicationMixin, validate_create
from titan.server import Handler


class App(DesktopApplicationMixin):
    pass


class DesktopAuthorizationTests(unittest.TestCase):
    def test_current_policy_and_database_session_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            app = App()
            app.stop = threading.Event(); app.demo = False
            app.store = Store(directory)
            app.store.create_user('member', 'Disposable-session-test-123!', 'user', 'member')
            token, csrf = app.store.login('member', 'Disposable-session-test-123!')
            entry = {'user': app.store.session(token), 'kind': 'app'}
            self.assertFalse(app.desktop_active(entry))
            app.store.set_config('identity', {'schema':1, 'groups':[], 'users':{'member':{'applications':{'apps':True}}}})
            self.assertTrue(app.desktop_active(entry))
            entry['kind'] = 'vm'
            self.assertFalse(app.desktop_active(entry))
            entry['kind'] = 'app'
            app.store.set_config('identity', {'schema':1, 'groups':[], 'users':{}})
            self.assertFalse(app.desktop_active(entry))
            app.store.set_config('identity', {'schema':1, 'groups':[], 'users':{'member':{'applications':{'apps':True}}}})
            app.store.logout(token)
            self.assertFalse(app.desktop_active(entry))


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.user = {'name':'patrick', 'csrf':'first-login', 'role':'admin'}
        self.app = App()
        self.app.stop = threading.Event()
        self.app.demo = False
        self.app.origin = None
        self.app.store = SimpleNamespace(audit=Mock(), session=lambda token: self.user if token == 'valid' else None)
        self.app.agent = Mock()
        self.app.agent.call.return_value = {'protocol':'vnc', 'hostname':'127.0.0.1', 'port':5900, 'password':'secret', 'running': True}
        self.app.initialize_desktops()
        self.app.desktop_reaper = True
        self.app.desktop_active = lambda entry: True
        self.enterContext(patch('titan.desktop_sessions.require_application'))
        self.body = {'kind':'app', 'target':'titan-immich', 'width':1000, 'height':700}

    def test_reuse_owner_limits_and_no_endpoint_secrets(self):
        first = self.app.desktop_create(self.user, self.body)
        self.assertEqual(set(first), {'id'})
        self.assertEqual(self.app.desktop_create(self.user, self.body), first)
        self.assertEqual(sum(call.args[0] == 'desktop_open' for call in self.app.agent.call.call_args_list), 1)
        other = self.app.desktop_create({**self.user, 'csrf':'second-login'}, self.body)
        self.assertNotEqual(first, other)
        with self.assertRaises(Error) as error:
            self.app.desktop_entry(self.user, other['id'])
        self.assertEqual(error.exception.status, 404)
        for target in ('two', 'three', 'four'):
            self.app.desktop_create(self.user, {**self.body, 'target':target})
        with self.assertRaises(Error) as error:
            self.app.desktop_create(self.user, {**self.body, 'target':'five'})
        self.assertEqual(error.exception.status, 429)

    def test_revoke_close_and_idle_cleanup(self):
        first = self.app.desktop_create(self.user, self.body)['id']
        self.app.desktops[first]['touched'] = time.monotonic() - 901
        self.app.reap_desktops()
        self.assertNotIn(first, self.app.desktops)
        self.app.agent.call.assert_called_with('desktop_close', id=first)
        second = self.app.desktop_create(self.user, self.body)['id']
        connection = Mock(); self.app.desktops[second]['stream'] = connection
        self.app.desktop_active = lambda entry: False
        self.app.reap_desktops()
        connection.shutdown.assert_called_once()
        self.assertNotIn(second, self.app.desktops)

    def test_dead_browser_after_agent_restart_gets_a_new_session(self):
        first = self.app.desktop_create(self.user, self.body)['id']
        self.app.agent.call.return_value['running'] = False
        second = self.app.desktop_create(self.user, self.body)['id']
        self.assertNotEqual(first, second)
        self.assertNotIn(first, self.app.desktops)

    def test_cleanup_failure_is_retried(self):
        id = self.app.desktop_create(self.user, self.body)['id']
        self.app.agent.call.side_effect = Error('temporarily unavailable')
        self.app.desktop_close(id)
        self.assertIn(id, self.app.desktops)
        self.app.agent.call.side_effect = None
        self.app.reap_desktops()
        self.assertNotIn(id, self.app.desktops)

    def test_no_caller_chosen_network_endpoint(self):
        for body in ({**self.body, 'hostname':'evil'}, {**self.body, 'password':'secret'},
                     {**self.body, 'width':True}, {**self.body, 'kind':'rdp'}, {**self.body, 'height':20000}):
            with self.subTest(body=body), self.assertRaises(Error):
                validate_create(body)

    def handler(self, method, path, body=None, cookie='valid', csrf='first-login', origin='http://titan.test'):
        handler = object.__new__(Handler)
        handler.server = SimpleNamespace(app=self.app)
        handler.command = method; handler.path = path
        handler.client_address = ('127.0.0.1', 1234)
        handler.close_connection = False
        handler.headers = Message()
        for key, value in {'Host':'titan.test', 'Cookie':'titan_session=' + cookie, 'X-CSRF-Token':csrf}.items():
            handler.headers[key] = value
        if origin:
            handler.headers['Origin'] = origin
        payload = json.dumps(body or {}).encode()
        handler.headers['Content-Length'] = str(len(payload))
        handler.rfile = io.BytesIO(payload); handler.wfile = io.BytesIO()
        handler.send_response = Mock(); handler.send_header = Mock(); handler.end_headers = Mock()
        return handler

    def test_http_requires_login_csrf_and_same_origin(self):
        for options, status in [({'cookie':'invalid'},401), ({'csrf':'invalid'},403), ({'origin':'https://evil.test'},403)]:
            handler = self.handler('POST', '/api/desktops', self.body, **options)
            handler.do_POST()
            handler.send_response.assert_called_with(status)
        self.app.agent.call.assert_not_called()

    def test_websocket_requires_origin_before_any_connection(self):
        id = self.app.desktop_create(self.user, self.body)['id']
        handler = self.handler('GET', '/api/desktops/stream?id=' + id, origin=None)
        handler.do_GET()
        handler.send_response.assert_called_with(403)


if __name__ == '__main__':
    unittest.main()

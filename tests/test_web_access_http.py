"""Real HTTP routes: endpoint changes, trust, roles and cookie transitions."""
from http.client import HTTPConnection
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
import json
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from titan.core import atomic_json
from titan.server import Application, Handler
from titan.web_access import initial_config


class WebAccessHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.agent = Mock()
        with patch('titan.server.AgentClient', return_value=self.agent):
            self.app = Application(self.temp.name, origin='https://nas.test')
        self.app.store.create_user('admin', 'long-disposable-password', 'admin', 'admin')
        self.app.store.create_user('reader', 'long-disposable-password', 'user', 'reader')
        self.tokens = {name:self.app.store.login(name, 'long-disposable-password') for name in ('admin', 'reader')}
        self.origins = {'https://nas.test', 'http://nas.test:8080'}
        self.app.trusted_origins = lambda: self.origins
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.app = self.app
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.result = {'origin':'http://nas.test:8080', 'settings':{'mode':'http','http_port':8080,'https_port':443},'pending':True,'revision':'new'}
        self.agent.call.return_value = self.result

    def close(self):
        self.app.stop.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, body=None, actor='admin', origin='https://nas.test', **overrides):
        from urllib.parse import urlsplit
        headers = {'Host':urlsplit(origin).netloc, 'Origin':origin, 'Content-Type':'application/json'}
        if actor:
            token, csrf = self.tokens[actor]
            headers.update(Cookie='titan_session='+token, **{'X-CSRF-Token':csrf})
        headers.update(overrides)
        headers = {key:value for key,value in headers.items() if value is not None}
        client = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            client.request('POST' if body is not None else 'GET', path, json.dumps(body) if body is not None else None, headers)
            response = client.getresponse()
            return response.status, json.loads(response.read()), response.headers
        finally:
            client.close()

    def test_change_requires_admin_csrf_and_trusted_host_origin(self):
        body = {'settings':self.result['settings'],'expected_revision':'old'}
        for options, expected in (({'actor':None},401),({'actor':'reader'},403),({'X-CSRF-Token':'wrong'},403),
                                  ({'Host':'evil.test'},403),({'Origin':'https://evil.test'},403),({'Sec-Fetch-Site':'cross-site'},403)):
            with self.subTest(options=options):
                self.assertEqual(self.request('/api/web-access', body, **options)[0], expected)
        self.agent.call.assert_not_called()
        self.assertEqual(self.request('/api/web-access', {**body,'request_origin':'https://evil.test'})[0],400)
        self.assertEqual(self.request('/api/web-access', body)[0],200)
        self.agent.call.assert_called_once_with('web_access_apply', **body)

    def test_confirmation_origin_is_from_request_and_not_caller_json(self):
        self.assertEqual(self.request('/api/web-access/confirm', {'expected_revision':'new','request_origin':'http://nas.test:8080'})[0],400)
        self.assertEqual(self.request('/api/web-access/confirm', {'expected_revision':'new'}, origin='http://nas.test:8080')[0],200)
        self.agent.call.assert_called_once_with('web_access_confirm', expected_revision='new',request_origin='http://nas.test:8080')
        self.assertEqual(self.request('/api/web-access/cancel', {})[0],200)

    def test_http_and_https_logins_and_logout_have_correct_cookie_flags(self):
        for address, secure in (('https://nas.test', True), ('http://nas.test:8080',False)):
            with self.subTest(address=address):
                status, value, headers = self.request('/api/login', {'name':'admin','password':'long-disposable-password'}, actor=None, origin=address)
                self.assertEqual(status,200)
                cookie = SimpleCookie(headers['Set-Cookie'])['titan_session']
                self.assertEqual(bool(cookie['secure']),secure)
                self.assertTrue(cookie['httponly'])
                self.assertEqual(cookie['samesite'],'Strict')
                status, _, headers = self.request('/api/logout', {}, origin=address)
                self.assertEqual(status,200)
                self.assertEqual(bool(SimpleCookie(headers['Set-Cookie'])['titan_session']['secure']),secure)
                self.tokens['admin'] = self.app.store.login('admin','long-disposable-password')

    def test_explicit_http_change_transfers_cookie_then_https_refresh_promotes(self):
        def apply(operation, **arguments):
            self.app.origin = 'http://nas.test:8080'
            return self.result
        self.agent.call.side_effect = apply
        status, _, headers = self.request('/api/web-access', {'settings':self.result['settings'],'expected_revision':'old'})
        self.assertEqual(status,200)
        cookie = SimpleCookie(headers['Set-Cookie'])['titan_session']
        self.assertFalse(cookie['secure'])
        self.assertEqual(cookie.value,self.tokens['admin'][0])
        # Visiting the previous HTTPS endpoint during a downgrade must not
        # re-promote the cookie and lock the administrator out of HTTP.
        self.assertIsNone(self.request('/api/session')[2].get('Set-Cookie'))
        self.assertEqual(self.request('/api/session', origin='http://nas.test:8080')[1]['user']['name'],'admin')
        self.app.origin = 'https://nas.test'
        headers = self.request('/api/session', Origin=None, **{'X-Forwarded-Proto':'https'})[2]
        self.assertTrue(SimpleCookie(headers['Set-Cookie'])['titan_session']['secure'])

    def test_public_config_controls_current_and_pending_trusted_addresses(self):
        from pathlib import Path
        path = Path(self.temp.name)/'web-access.json'
        config = initial_config('nas.test')
        old = initial_config('nas.test', 'https://nas.test:5000')
        config['pending'] = {'previous':old,'deadline':12345}
        atomic_json(path,config)
        del self.app.trusted_origins
        with patch('titan.web_access.CONFIG',path):
            self.assertEqual(self.app.origin,'https://nas.test')
            self.assertEqual(self.app.trusted_origins(),{'https://nas.test','https://nas.test:5000'})
            self.assertEqual(self.request('/api/web-access',origin='https://nas.test:5000')[0],200)
            self.assertEqual(self.request('/api/web-access',origin='http://nas.test:8080')[0],403)

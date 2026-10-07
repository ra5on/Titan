"""Real HTTP routes: endpoint changes, trust, roles and cookie transitions."""
from http.client import HTTPConnection
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
import base64
import json
import tempfile
import threading
import time
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

    def test_remote_settings_require_admin_csrf_exact_arguments_and_trusted_origin(self):
        body = {'enabled': True, 'public_origin': 'https://nas.example.com', 'connector': '',
                'app_urls': {}, 'expected_revision': 'old'}
        for options, expected in (({'actor':None},401),({'actor':'reader'},403),
                ({'X-CSRF-Token':'wrong'},403),({'Host':'evil.test'},403),({'Origin':'https://evil.test'},403)):
            with self.subTest(options=options):
                self.assertEqual(self.request('/api/remote-access', body, **options)[0], expected)
        self.assertEqual(self.request('/api/remote-access', {**body, 'sources':['0.0.0.0/0']})[0],400)
        self.assertEqual(self.request('/api/remote-access', actor='reader')[0],403)
        self.agent.call.assert_not_called()
        self.assertEqual(self.request('/api/remote-access', body)[0],200)
        self.agent.call.assert_called_once_with('remote_access_apply', **body)
        self.assertEqual(self.request('/api/remote-access/diagnose', {'url':'https://evil.test'})[0],400)
        self.assertEqual(self.request('/api/remote-access/diagnose', {})[0],200)
        self.agent.call.assert_called_with('remote_access_diagnose')

    def tunnel_body(self):
        token = base64.b64encode(json.dumps({'a': 'a' * 32, 't': '2c9069cd-5cf1-470f-9ddd-df156d3f2c57',
            's': base64.b64encode(b'disposable-test-secret-with-entropy').decode()}).encode()).decode()
        return {'token': token, 'public_origin': '', 'expected_revision': 'current-revision'}

    def wait_job(self, identifier):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            job = next(row for row in self.app.store.jobs() if row['id'] == identifier)
            if job['status'] not in ('running', 'queued'):
                return job
            time.sleep(.01)
        self.fail('job did not complete')

    def test_tunnel_setup_requires_admin_csrf_trusted_origin_and_exact_safe_arguments(self):
        body = self.tunnel_body()
        for options, expected in (({'actor':None},401),({'actor':'reader'},403),
                ({'X-CSRF-Token':'wrong'},403),({'Host':'evil.test'},403),({'Origin':'https://evil.test'},403),
                ({'Sec-Fetch-Site':'cross-site'},403)):
            with self.subTest(options=options):
                self.assertEqual(self.request('/api/remote-access/tunnel', body, **options)[0], expected)
        for invalid in ({**body, 'extra': True}, {**body, 'token': 'cloudflared run --token ' + body['token']},
                {**body, 'public_origin': 'http://nas.example.com'}, {**body, 'expected_revision': []}):
            self.assertEqual(self.request('/api/remote-access/tunnel', invalid)[0], 400)
        self.agent.call.assert_not_called()
        self.assertEqual(self.app.store.jobs(), [])

    def test_tunnel_job_response_database_and_audit_never_contain_token(self):
        body = self.tunnel_body()
        entered, release = threading.Event(), threading.Event()
        def execute(operation, **arguments):
            self.assertEqual(operation, 'remote_access_tunnel')
            self.assertEqual(arguments, body)
            entered.set()
            self.assertTrue(release.wait(3))
            return {'ok': True, 'setup': {'phase': 'needs_domain', 'needs_domain': True}}
        self.agent.call.side_effect = execute
        status, response, _ = self.request('/api/remote-access/tunnel', body)
        self.assertEqual(status, 202)
        self.assertEqual(set(response), {'job'})
        try:
            self.assertTrue(entered.wait(2))
            status, jobs, _ = self.request('/api/jobs')
            self.assertEqual(status, 200)
            self.assertNotIn(body['token'], json.dumps(jobs))
        finally:
            release.set()
        job = self.wait_job(response['job'])
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['action'], 'remote_access_tunnel')
        self.assertNotIn(body['token'], json.dumps(job))
        self.assertNotIn(body['token'].encode(), self.app.store.path.read_bytes())
        with self.app.store.connection() as db:
            audit = [tuple(row) for row in db.execute('SELECT action,detail FROM audit')]
        self.assertNotIn(body['token'], json.dumps(audit))

    def test_queued_tunnel_job_rechecks_revoked_admin_permissions(self):
        captured = []
        def submit(user, action, function, **kwargs):
            captured.append(function)
            return {'job': 'held-job'}
        self.app.jobs.submit = submit
        self.assertEqual(self.request('/api/remote-access/tunnel', self.tunnel_body())[0], 202)
        with self.app.store.connection() as db:
            db.execute('UPDATE users SET enabled=0 WHERE name=?', ('admin',))
        from titan.core import Error
        with self.assertRaises(Error) as error:
            captured[0]()
        self.assertEqual(error.exception.status, 403)
        self.agent.call.assert_not_called()

    def test_health_is_bounded_challenge_only_and_absent_when_disabled(self):
        from pathlib import Path
        from titan.remote_access import proof, validate_remote
        path = Path(self.temp.name)/'web-access.json'
        config = initial_config('nas.test')
        config['remote'] = {**validate_remote(None), 'enabled':True,
            'public_origin':'https://nas.example.com', 'service_url':'http://127.0.0.1:5102'}
        atomic_json(path,config)
        with patch('titan.web_access.CONFIG',path):
            for query in ('', '?challenge=short', '?challenge='+'a'*32+'&extra=1'):
                self.assertEqual(self.request('/api/tunnel-health'+query, actor=None)[0],400)
            status, value, _ = self.request('/api/tunnel-health?challenge='+'a'*32, actor=None)
            self.assertEqual(status,200)
            self.assertEqual(value,{'service':'Titan','challenge':'a'*32,'proof':proof(config)})
            config['remote']['enabled']=False
            atomic_json(path,config)
            self.assertEqual(self.request('/api/tunnel-health?challenge='+'a'*32, actor=None)[0],404)

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

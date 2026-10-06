from http.server import ThreadingHTTPServer
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from titan.server import Application, Handler


class LoginProtectionHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(self.temp.name)
        self.app.store.create_user('admin', 'admin-password-long', 'admin', 'admin')
        self.app.store.create_user('reader', 'reader-password-long', 'user', 'reader')
        self.sessions = {name: self.app.store.login(name, name + '-password-long', address='192.0.2.200') for name in ('admin', 'reader')}
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.app = self.app; self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.app.origin = self.url

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.temp.cleanup()

    def request(self, path, body=None, actor='admin', csrf=True, origin=None, forwarded=None):
        headers = {'Content-Type': 'application/json', 'Origin': self.url if origin is None else origin}
        if actor:
            token, code = self.sessions[actor]
            headers['Cookie'] = 'titan_session=' + token
            headers['X-CSRF-Token'] = code if csrf else 'wrong'
        if forwarded is not None:
            headers['X-Forwarded-For'] = forwarded
        request = urllib.request.Request(self.url + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            response = urllib.request.urlopen(request)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read()), dict(response.headers)

    def configure(self, **rules):
        data = self.request('/api/security/login-protection')[1]
        for kind, fields in rules.items(): data['settings'][kind].update(fields)
        result = self.request('/api/security/login-protection', {'settings': data['settings'], 'expected_revision': data['revision']})
        self.assertEqual(result[0], 200)
        return result[1]

    def login(self, name='reader', password='wrong-password-long', address='198.51.100.7'):
        return self.request('/api/login', {'name': name, 'password': password}, actor=None, forwarded=address)

    def test_overview_admin_only_and_no_query_options(self):
        self.assertEqual(self.request('/api/security/login-protection', actor=None)[0], 401)
        self.assertEqual(self.request('/api/security/login-protection', actor='reader')[0], 403)
        self.assertEqual(self.request('/api/security/login-protection?all=1')[0], 400)
        self.assertEqual(self.request('/api/security/login-protection')[0], 200)
        self.assertNotIn('login_protection', self.request('/api/security', actor='reader')[1])

    def test_mutation_requires_admin_csrf_origin_and_exact_schema(self):
        data = self.request('/api/security/login-protection')[1]
        body = {'settings': data['settings'], 'expected_revision': data['revision']}
        self.assertEqual(self.request('/api/security/login-protection', body, actor='reader')[0], 403)
        self.assertEqual(self.request('/api/security/login-protection', body, csrf=False)[0], 403)
        self.assertEqual(self.request('/api/security/login-protection', body, origin='http://attacker.test')[0], 403)
        self.assertEqual(self.request('/api/security/login-protection', {**body, 'extra': True})[0], 400)
        self.assertEqual(self.request('/api/security/login-protection', {'settings': data['settings']})[0], 400)
        self.assertEqual(self.request('/api/security/login-protection')[1]['revision'], data['revision'])

    def test_persistent_block_response_has_safe_retry_and_no_account_details(self):
        self.configure(ip={'attempts': 2, 'block_minutes': 1}, account={'enabled': False})
        self.assertEqual(self.login()[0], 401)
        self.assertEqual(self.login(name='nobody')[0], 401)
        status, body, headers = self.login(password='reader-password-long')
        self.assertEqual(status, 429)
        self.assertGreater(body['retry_after'], 0)
        self.assertLessEqual(body['retry_after'], 60)
        self.assertEqual(headers['Retry-After'], str(body['retry_after']))
        self.assertEqual(set(body), {'error', 'retry_after'})
        self.assertNotIn('Set-Cookie', headers)
        blocks = self.request('/api/security/login-protection')[1]['blocks']
        self.assertEqual(blocks[0]['address'], '198.51.100.7')
        self.assertEqual(blocks[0]['username'], '')

    def test_valid_logins_do_not_hit_legacy_all_attempts_limit(self):
        for _ in range(12):
            self.assertEqual(self.login(password='reader-password-long')[0], 200)
        self.assertEqual(self.request('/api/security/login-protection')[1]['blocks'], [])

    def test_account_source_scope_does_not_lock_different_ip(self):
        self.configure(ip={'enabled': False}, account={'attempts': 1})
        self.assertEqual(self.login()[0], 401)
        self.assertEqual(self.login(password='reader-password-long')[0], 429)
        self.assertEqual(self.login(password='reader-password-long', address='198.51.100.8')[0], 200)
        self.assertEqual(self.login(name='admin', password='admin-password-long')[0], 200)

    def test_manual_unblock_requires_admin_and_csrf(self):
        self.configure(ip={'attempts': 1}, account={'enabled': False})
        self.login()
        block_id = self.request('/api/security/login-protection')[1]['blocks'][0]['id']
        path = '/api/security/login-protection/unblock'
        self.assertEqual(self.request(path, {'id': block_id}, actor='reader')[0], 403)
        self.assertEqual(self.request(path, {'id': block_id}, csrf=False)[0], 403)
        self.assertEqual(self.request(path, {'id': block_id, 'address': 'anything'})[0], 400)
        status, result, _ = self.request(path, {'id': block_id})
        self.assertEqual(status, 200); self.assertTrue(result['ok']); self.assertEqual(result['blocks'], [])
        self.assertEqual(self.login(password='reader-password-long')[0], 200)
        self.assertEqual(self.request(path, {'id': block_id})[0], 404)

    def test_stale_settings_get_conflict_without_overwrite(self):
        stale = self.request('/api/security/login-protection')[1]
        self.configure(ip={'attempts': 8})
        self.assertEqual(self.request('/api/security/login-protection', {'settings': stale['settings'], 'expected_revision': stale['revision']})[0], 409)
        self.assertEqual(self.request('/api/security/login-protection')[1]['settings']['ip']['attempts'], 8)

    def test_forwarded_address_only_trusted_behind_configured_loopback_proxy(self):
        fake = type('Fake', (), {})()
        fake.app = self.app; fake.client_address = ('203.0.113.5', 1000)
        fake.headers = {'X-Forwarded-For': '198.51.100.7'}
        self.assertEqual(Handler.authentication_address(fake), '203.0.113.5')
        fake.client_address = ('127.0.0.1', 1000)
        self.assertEqual(Handler.authentication_address(fake), '198.51.100.7')
        fake.headers = {'X-Forwarded-For': '198.51.100.7, 203.0.113.5'}
        self.assertEqual(Handler.authentication_address(fake), '127.0.0.1')
        self.app.origin = None; fake.headers = {'X-Forwarded-For': '198.51.100.7'}
        self.assertEqual(Handler.authentication_address(fake), '127.0.0.1')


if __name__ == '__main__':
    unittest.main()

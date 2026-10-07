"""Real generated Caddy tunnel routes against Titan's real HTTP handler."""
import copy
from http.client import HTTPConnection
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from titan.core import atomic_json
from titan.remote_access import proof, tunnel_caddy, validate_remote
from titan.server import Application, Handler
from titan.web_access import initial_config


_CADDY = os.environ.get('TITAN_TEST_CADDY') or shutil.which('caddy')


class CapturingHandler(Handler):
    def do_GET(self):
        self.server.received.append({'path': self.path, 'headers': dict(self.headers)})
        super().do_GET()
    def do_POST(self):
        self.server.received.append({'path': self.path, 'headers': dict(self.headers)})
        super().do_POST()


@unittest.skipUnless(_CADDY, 'Real remote proxy acceptance requires Caddy; BigBear CI supplies it.')
class RemoteProxyTests(unittest.TestCase):
    bridge = False

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='titan-remote-proxy-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {**initial_config('192.168.10.18'), 'revision': 'real-proxy-test',
            'remote': {**validate_remote(None), 'enabled': True, 'public_origin': 'https://nas.example.com',
                'service_url': 'http://127.0.0.1:5102'}}
        if self.bridge:
            self.config['remote'].update(sources=['172.30.10.0/24'], interface='br-123456789abc',
                service_url='http://172.30.10.1:5102')
        self.config_path = self.root / 'web-access.json'
        atomic_json(self.config_path, self.config)
        self.enterContext(patch('titan.web_access.CONFIG', self.config_path))
        with patch('titan.server.AgentClient', return_value=Mock()):
            self.app = Application(str(self.root / 'state'), origin='https://192.168.10.18')
        self.password = 'disposable-proxy-password'
        self.app.store.create_user('admin', self.password, 'admin', 'admin')
        self.backend = ThreadingHTTPServer(('127.0.0.1', 0), CapturingHandler)
        self.backend.app, self.backend.received, self.backend.daemon_threads = self.app, [], True
        self.backend_thread = threading.Thread(target=self.backend.serve_forever,
            kwargs={'poll_interval': .01}, daemon=True)
        self.backend_thread.start()
        self.addCleanup(self.close_backend)
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0))
            self.proxy_port = reserved.getsockname()[1]
        # Keep generated matchers and headers intact; use disposable ports so
        # acceptance never reserves or modifies the real Titan installation.
        text = tunnel_caddy(self.config).replace('127.0.0.1:5001', '127.0.0.1:' + str(self.backend.server_port))
        text = text.replace(':5102', ':' + str(self.proxy_port))
        source = self.root / 'Caddyfile'
        source.write_text('{\n    admin off\n    auto_https off\n}\n' + text)
        self.logs = (self.root / 'caddy.log').open('w+')
        self.addCleanup(self.logs.close)
        self.process = subprocess.Popen([_CADDY, 'run', '--config', str(source), '--adapter', 'caddyfile'],
            stdout=self.logs, stderr=subprocess.STDOUT,
            env={**os.environ, 'XDG_DATA_HOME': str(self.root / 'data'), 'XDG_CONFIG_HOME': str(self.root / 'config')})
        self.addCleanup(self.close_proxy)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.logs.seek(0)
                self.fail('Disposable Caddy exited: ' + self.logs.read()[-4000:])
            try:
                if self.request('/api/session')[0] == 200: break
            except (OSError, TimeoutError):
                pass
            time.sleep(.02)
        else:
            self.fail('Disposable Caddy did not become available.')
        self.backend.received.clear()

    def close_proxy(self):
        if self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=3)

    def close_backend(self):
        self.app.stop.set()
        self.backend.shutdown(); self.backend.server_close(); self.backend_thread.join(3)

    def request(self, path, body=None, *, host='nas.example.com', source='127.0.0.1', headers=None):
        client = HTTPConnection('127.0.0.1', self.proxy_port, timeout=3, source_address=(source, 0))
        try:
            client.request('POST' if body is not None else 'GET', path,
                json.dumps(body) if body is not None else None,
                {'Host': host, 'Content-Type': 'application/json', **(headers or {})})
            response = client.getresponse()
            payload = response.read(1024 * 1024)
            return response.status, payload, response.headers
        finally:
            client.close()

    def test_real_proxy_requires_selected_host_and_actual_connector_source(self):
        for host, source, headers in (('192.168.10.18', '127.0.0.1', {}),
                ('evil.example.com', '127.0.0.1', {}), ('nas.example.com', '127.0.0.2', {}),
                ('nas.example.com', '127.0.0.2', {'X-Forwarded-For': '127.0.0.1'})):
            with self.subTest(host=host, source=source):
                before = len(self.backend.received)
                status, _, response_headers = self.request('/api/session', host=host, source=source, headers=headers)
                self.assertEqual(status, 403)
                self.assertIsNone(response_headers.get('Location'))
                self.assertEqual(len(self.backend.received), before)
        self.assertEqual(self.request('/api/session')[0], 200)

    def test_real_proxy_preserves_public_host_forces_https_and_never_redirects_to_private_nas(self):
        challenge = 'a' * 32
        status, body, headers = self.request('/api/tunnel-health?challenge=' + challenge,
            headers={'X-Forwarded-Proto': 'http'})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'service': 'Titan', 'challenge': challenge, 'proof': proof(self.config)})
        self.assertIsNone(headers.get('Location'))
        received = self.backend.received[-1]['headers']
        self.assertEqual(received['Host'], 'nas.example.com')
        self.assertEqual(received['X-Forwarded-Proto'], 'https')
        self.assertNotIn('192.168.10.18', body.decode())

    def test_actual_login_and_session_through_proxy_keep_secure_cookie_and_origin_checks(self):
        status, body, headers = self.request('/api/login', {'name': 'admin', 'password': self.password},
            headers={'Origin': 'https://nas.example.com'})
        self.assertEqual(status, 200, body)
        cookie = SimpleCookie(headers['Set-Cookie'])['titan_session']
        self.assertTrue(cookie['secure'])
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Strict')
        status, body, _ = self.request('/api/session', headers={'Cookie': 'titan_session=' + cookie.value})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['user']['name'], 'admin')
        status, _, _ = self.request('/api/login', {'name': 'admin', 'password': self.password},
            headers={'Origin': 'https://evil.example.com'})
        self.assertEqual(status, 403)

    def test_origin_changes_take_effect_without_restarting_http_backend(self):
        self.assertEqual(self.request('/api/session')[0], 200)
        disabled = copy.deepcopy(self.config)
        disabled['remote']['enabled'] = False
        atomic_json(self.config_path, disabled)
        self.assertEqual(self.request('/api/session')[0], 403)
        self.assertEqual(self.app.trusted_origins(), {'https://192.168.10.18'})
        atomic_json(self.config_path, self.config)
        self.assertEqual(self.request('/api/session')[0], 200)


class RemoteBridgeProxyTests(RemoteProxyTests):
    bridge = True


if __name__ == '__main__':
    unittest.main()

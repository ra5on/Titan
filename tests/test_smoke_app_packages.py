"""Safe diagnostics for the isolated Cloudflared LAN lifecycle acceptance test."""
import base64
import importlib.util
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest
from unittest.mock import Mock

from titan.core import Error

spec = importlib.util.spec_from_file_location('titan_app_packages_smoke',
    Path(__file__).resolve().parents[1] / 'scripts/smoke-app-packages.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class CloudflaredLanProbeTests(unittest.TestCase):
    def test_cloudflared_ci_runs_both_real_authentication_modes(self):
        import yaml
        root = Path(__file__).resolve().parents[1]
        for name in ('bigbear.yml', 'app-packages.yml'):
            with self.subTest(workflow=name):
                workflow = yaml.safe_load((root / '.github/workflows' / name).read_text())
                job = workflow['jobs']['cloudflared-web']
                self.assertEqual(set(job['strategy']['matrix']['auth']), {'disabled', 'password'})
                steps = [step for step in job['steps'] if 'smoke-app-packages.py' in step.get('run', '')]
                self.assertEqual(len(steps), 1)
                self.assertIn('--cloudflared-auth', steps[0]['run'])
                self.assertIn('${{ matrix.auth }}', steps[0]['run'])
                self.assertTrue(any('systemctl start firewalld' in step.get('run', '') for step in job['steps']))
                self.assertTrue(any('ip netns add titan-ci-client' in step.get('run', '') for step in job['steps']))
                if name == 'app-packages.yml':
                    checkout = next(step for step in job['steps'] if step.get('uses', '').startswith('actions/checkout@'))
                    self.assertEqual(checkout['with']['ref'], '${{ inputs.source_ref || github.sha }}')
                    self.assertTrue(any('test_remote_access' in step.get('run', '') for step in job['steps']))

    def test_real_configuration_http_check_accepts_both_modes_and_detects_mismatch(self):
        credentials = base64.b64encode(b'admin:private-password').decode()
        class ConfigHandler(BaseHTTPRequestHandler):
            require_auth = False
            requests = []
            def log_message(self, *arguments): pass
            def do_GET(self):
                auth = self.headers.get('Authorization')
                self.requests.append(auth)
                status = 401 if self.require_auth and auth != 'Basic ' + credentials else 200
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{}')
        server = ThreadingHTTPServer(('127.0.0.1', 0), ConfigHandler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            url = 'http://127.0.0.1:' + str(server.server_port) + '/config'
            smoke.check_cloudflared_api(url)
            self.assertEqual(ConfigHandler.requests, [None])
            with self.assertRaisesRegex(Error, 'allowed unauthenticated access'):
                smoke.check_cloudflared_api(url, credentials)
            ConfigHandler.require_auth = True
            ConfigHandler.requests.clear()
            smoke.check_cloudflared_api(url, credentials)
            self.assertEqual(ConfigHandler.requests, [None, 'Basic ' + credentials])
            with self.assertRaisesRegex(Error, 'returned HTTP 401'):
                smoke.check_cloudflared_api(url)
        finally:
            server.shutdown(); server.server_close(); worker.join(3)

    def test_image_package_gate_uses_same_validated_bigbear_revision(self):
        import yaml
        root = Path(__file__).resolve().parents[1]
        ordinary = yaml.safe_load((root / '.github/workflows/bigbear.yml').read_text())
        image_gate = yaml.safe_load((root / '.github/workflows/app-packages.yml').read_text())
        self.assertEqual(smoke.bigbear_revision(image_gate['env']['BIGBEAR_REVISION']), ordinary['env']['BIGBEAR_REVISION'])
        runtime_steps = [step for step in image_gate['jobs']['package']['steps'] if 'smoke-app-packages.py' in step.get('run','')]
        self.assertEqual(len(runtime_steps), 1)
        self.assertIn('--bigbear-revision "$BIGBEAR_REVISION"', runtime_steps[0]['run'])

    def test_only_current_status_and_allowlisted_headers_are_reported(self):
        run = Mock(return_value='HTTP/1.1 100 Continue\r\nContent-Type: old-type\r\n\r\n'
            'HTTP/1.1 401 Unauthorized\r\nContent-Type: text/plain; charset=utf-8\r\n'
            'WWW-Authenticate: Basic realm="cloudflared"\r\n'
            'Set-Cookie: session=private-value\r\nX-Private: do-not-print\r\n'
            '\r\nTITAN_HTTP_STATUS:401\n')
        result = smoke.cloudflared_lan_probe(run, 'http://10.254.254.1:14333/config')
        self.assertEqual(result, {'http_status': '401', 'content_type': 'text/plain; charset=utf-8',
            'www_authenticate': 'Basic realm="cloudflared"'})
        self.assertNotIn('private', json.dumps(result))
        command = run.call_args.args[0]
        self.assertEqual(command[:5], ['ip', 'netns', 'exec', 'titan-ci-client', 'curl'])
        self.assertEqual(command[command.index('--noproxy') + 1], '*')
        self.assertEqual(command[command.index('--proto') + 1], '=http')
        self.assertNotIn('-L', command)

    def test_authenticated_lan_probe_keeps_credentials_out_of_argv_and_diagnostics(self):
        credentials = base64.b64encode(b'admin:private-password').decode()
        run = Mock(return_value='HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
            'WWW-Authenticate: ' + credentials + '\r\n\r\nTITAN_HTTP_STATUS:200\n')
        result = smoke.cloudflared_lan_probe(run, 'http://10.254.254.1:14333/config', credentials)
        self.assertEqual(result['http_status'], '200')
        self.assertNotIn(credentials, ' '.join(run.call_args.args[0]))
        self.assertIn('Authorization: Basic ' + credentials, run.call_args.kwargs['input'])
        self.assertNotIn(credentials, json.dumps(result))
        self.assertEqual(result['www_authenticate'], '[redacted]')
        with self.assertRaises(Error):
            smoke.cloudflared_lan_probe(run, 'http://10.254.254.1:14333/config', 'bad\nconfig')


if __name__ == '__main__':
    unittest.main()

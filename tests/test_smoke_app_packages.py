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
    def test_legacy_cloudflared_auth_modes_are_only_gates_for_frozen_legacy_apps(self):
        import yaml
        root=Path(__file__).resolve().parents[1]
        workflow=yaml.safe_load((root/'.github/workflows/app-packages.yml').read_text())
        job=workflow['jobs']['legacy-cloudflared-web']
        self.assertEqual(job['if'], "needs.source.outputs.mode == 'legacy'")
        self.assertEqual(set(job['strategy']['matrix']['auth']), {'disabled','password'})
        self.assertTrue(any('--cloudflared-auth' in step.get('run','') for step in job['steps']))
        self.assertTrue(any('test_remote_access' in step.get('run','') for step in job['steps']))
        main=yaml.safe_load((root/'.github/workflows/bigbear.yml').read_text())
        self.assertNotIn('BIGBEAR_REVISION',main.get('env',{}))
        self.assertEqual(main['jobs']['native-apps']['uses'],'./.github/workflows/app-packages.yml')
        for name in ('cloudflared-token','compose-fixture'):
            self.assertEqual(workflow['jobs'][name]['if'], "needs.source.outputs.mode == 'native'")

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

    def test_only_legacy_gates_use_an_explicit_bigbear_revision(self):
        import yaml
        root=Path(__file__).resolve().parents[1]
        workflow=yaml.safe_load((root/'.github/workflows/app-packages.yml').read_text())
        self.assertRegex(smoke.bigbear_revision(workflow['env']['BIGBEAR_REVISION']),r'^[a-f0-9]{40}$')
        for name,job in workflow['jobs'].items():
            commands='\n'.join(step.get('run','') for step in job.get('steps',[]))
            if '--bigbear-revision' in commands:
                self.assertTrue(name.startswith('legacy-'))
                self.assertEqual(job['if'], "needs.source.outputs.mode == 'legacy'")
            if name in ('cloudflared-token','compose-fixture'):
                self.assertNotIn('bigbear:',commands)

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

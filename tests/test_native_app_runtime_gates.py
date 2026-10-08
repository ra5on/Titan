"""Acceptance helpers use real local transports and refuse local Docker runs."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

from titan.core import Error

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NativeGateTests(unittest.TestCase):
    def test_dns_gate_checks_real_udp_and_fragmented_tcp_answers_without_upstream_dns(self):
        smoke = script('smoke-app-packages.py')
        for tcp in (False, True):
            with self.subTest(tcp=tcp), socket.socket(socket.AF_INET, socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as server:
                server.bind(('127.0.0.1', 0))
                server.settimeout(3)
                if tcp: server.listen(1)
                failures = []
                def respond():
                    try:
                        if tcp:
                            connection, _ = server.accept()
                            with connection:
                                length = struct.unpack('!H', connection.recv(2))[0]
                                query = connection.recv(length)
                                answer = query[:2] + struct.pack('!HHHHH', 0x8180, 1, 1, 0, 0) + query[12:] + b'\xc0\x0c' + struct.pack('!HHIH', 1, 1, 60, 4) + socket.inet_aton('192.0.2.123')
                                connection.sendall(struct.pack('!H', len(answer))[:1])
                                connection.sendall(struct.pack('!H', len(answer))[1:] + answer[:10])
                                connection.sendall(answer[10:])
                        else:
                            query, peer = server.recvfrom(4096)
                            answer = query[:2] + struct.pack('!HHHHH', 0x8180, 1, 1, 0, 0) + query[12:] + b'\xc0\x0c' + struct.pack('!HHIH', 1, 1, 60, 4) + socket.inet_aton('192.0.2.123')
                            server.sendto(answer, peer)
                    except Exception as error:
                        failures.append(error)
                thread = threading.Thread(target=respond, daemon=True)
                thread.start()
                self.assertTrue(smoke.adguard_dns_probe(server.getsockname()[1], tcp))
                thread.join(3)
                self.assertFalse(failures)

    def test_upstream_adguard_wizard_keeps_web3000_and_requires_auth_for_local_rewrite(self):
        smoke = script('smoke-app-packages.py')
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                calls.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length']))), self.headers.get('Authorization')))
                self.send_response(200)
                self.end_headers()
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            auth = smoke.adguard_setup('http://127.0.0.1:' + str(server.server_port), 'disposable-password-for-test')
            self.assertEqual(calls[0][0], '/control/install/configure')
            self.assertEqual(calls[0][1]['web'], {'ip': '0.0.0.0', 'port': 3000})
            self.assertEqual(calls[0][1]['dns'], {'ip': '0.0.0.0', 'port': 53})
            self.assertIsNone(calls[0][2])
            self.assertEqual(calls[1], ('/control/rewrite/add', {'domain': 'titan-smoke.invalid', 'answer': '192.0.2.123'}, 'Basic ' + auth))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)

    def test_tailscale_gate_refuses_unconfirmed_nonci_and_nonroot_before_any_command(self):
        smoke = script('smoke-tailscale.py')
        for confirmed, ci, uid in ((False, 'true', 0), (True, '', 0), (True, 'true', 1000)):
            argv = ['smoke-tailscale'] + (['--confirm-disposable-runner'] if confirmed else [])
            with self.subTest(confirmed=confirmed, ci=ci, uid=uid), patch.dict(os.environ, {'GITHUB_ACTIONS': ci}), \
                    patch.object(smoke.os, 'geteuid', return_value=uid), patch.object(sys, 'argv', argv), \
                    patch.object(smoke, 'command') as command, contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                smoke.main()
            self.assertEqual(error.exception.code, 2)
            command.assert_not_called()


class CloudflareDockerRecoveryGateTests(unittest.TestCase):
    def setUp(self):
        self.smoke = script('smoke-cloudflare-token.py')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.control = self.root / 'apps' / self.smoke.CONNECTOR
        self.control.mkdir(parents=True)
        self.config = self.root / 'config'
        (self.config / 'credentials').mkdir(parents=True)
        self.data = self.root / 'data'
        self.data.mkdir()
        for path, content in ((self.control / 'compose.json', b'compose'),
                              (self.control / 'options.json', b'private options'),
                              (self.config / 'credentials/token', b'dummy credential')):
            path.write_bytes(content)
            path.chmod(0o600)
        self.host = SimpleNamespace(directory=self.root,
            managed_app=Mock(return_value={'data': str(self.data)}),
            _app_config_path=Mock(return_value=self.config),
            _app_container=Mock(side_effect=[{'Id': 'a' * 64, 'State': {'Running': False}},
                                             {'Id': 'b' * 64, 'State': {'Running': False}}]))
        self.stage = 'before'
        self.breakage = ''
        self.calls = []
        self.waits = []

    def request(self, path, body=None):
        self.calls.append((path, body))
        if path == '/api/actions':
            self.stage = 'missing'
            marker = self.data / 'docker-removal-smoke.txt'
            if self.breakage == 'data':
                marker.write_bytes(b'data lost')
            if self.breakage == 'config':
                (self.control / 'options.json').write_bytes(b'configuration lost')
            return {'job': 'remove'}
        if path == '/api/app-install':
            self.stage = 'recreated'
            return {'job': 'install'}
        if path == '/api/docker-engine':
            return {'available': True, 'containers': []}
        if path == '/api/app-install?app=' + self.smoke.CONNECTOR:
            installed = self.stage != 'missing' or self.breakage == 'stale-status'
            return {'installed': installed, 'configured': installed, 'status': 'failed',
                    'revision': self.stage, 'resumable': False,
                    'runtime': {'state': 'stopped' if installed else 'missing', 'public_origin': '',
                                'cloudflare_connected': self.breakage == 'false-ready' and self.stage == 'recreated',
                                'public_ready': False}}
        self.fail('Unexpected acceptance request: ' + path)

    def wait_job(self, identifier, expect_failure=False):
        self.waits.append((identifier, expect_failure))
        return {'result': {'app_removed': True, 'data_retained': True}}

    def run_gate(self):
        return self.smoke.verify_docker_remove_reinstall(self.host, self.request, self.wait_job, 'dummy credential')

    def test_docker_removal_and_store_reinstall_are_checked_without_live_cloudflare(self):
        proof = self.run_gate()
        self.assertTrue(all(proof.values()))
        self.assertEqual(self.calls[1], ('/api/actions', {'operation': 'docker_container_action',
            'arguments': {'container': 'a' * 64, 'action': 'remove'}}))
        install = next(body for path, body in self.calls if path == '/api/app-install')
        self.assertEqual(install['expected_revision'], 'missing')
        self.assertEqual(install['options'], {'tunnel_token': 'dummy credential', 'public_origin': ''})
        self.assertEqual(self.waits, [('remove', False), ('install', True)])

    def test_stale_installed_status_blocks_reinstallation_gate(self):
        self.breakage = 'stale-status'
        with self.assertRaisesRegex(Error, 'still reports'):
            self.run_gate()
        self.assertFalse(any(path == '/api/app-install' for path, _ in self.calls))

    def test_configuration_or_data_loss_fails_the_gate_before_reinstallation(self):
        for breakage in ('data', 'config'):
            with self.subTest(breakage=breakage):
                # Each gate creates its own data marker, exactly as the
                # disposable runner does; a second pass must start clean.
                (self.data / 'docker-removal-smoke.txt').unlink(missing_ok=True)
                self.stage, self.breakage = 'before', breakage
                self.host._app_container.side_effect = [{'Id': 'a' * 64, 'State': {'Running': False}}]
                self.calls.clear()
                with self.assertRaisesRegex(Error, 'retained'):
                    self.run_gate()
                self.assertFalse(any(path == '/api/app-install' for path, _ in self.calls))

    def test_reinstallation_requires_a_fresh_safely_stopped_container(self):
        self.host._app_container.side_effect = [{'Id': 'a' * 64, 'State': {'Running': False}},
                                               {'Id': 'a' * 64, 'State': {'Running': False}}]
        with self.assertRaisesRegex(Error, 'fresh connector'):
            self.run_gate()

    def test_dummy_token_cannot_produce_a_false_external_connection_proof(self):
        self.breakage = 'false-ready'
        with self.assertRaisesRegex(Error, 'working external tunnel'):
            self.run_gate()


if __name__ == '__main__':
    unittest.main()

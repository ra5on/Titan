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
import threading
import unittest
from unittest.mock import patch

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


if __name__ == '__main__':
    unittest.main()

"""App readiness is distinct from running; probes are local, bounded and cached."""
import copy
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from titan.app_networks import app_readiness, _http_probe, _probe_cached
from titan import app_networks
from titan.catalog import APPS


class AppReachabilityTests(unittest.TestCase):
    def setUp(self):
        self.host = SimpleNamespace(directory=Path('/tmp/titan-readiness-unit'))
        self.record = {'id': 'jellyfin', 'port': 18096, 'scheme': 'http', 'installed': time.time() - 1000}
        self.container = {'Id': 'a' * 64, 'State': {'Status': 'running', 'Running': True,
            'StartedAt': '2020-01-01T00:00:00Z'}, 'HostConfig': {'NetworkMode': 'bridge'},
            'NetworkSettings': {'Ports': {'8096/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '18096'}]}}}
        self.summary = {'endpoints': [{'address': '192.168.10.18', 'port': 18096, 'scope': 'lan', 'url': 'http://192.168.10.18:18096'}]}

    def readiness(self):
        return app_readiness(self.host, self.container, self.record, self.summary)

    def test_running_container_is_not_ready_until_actual_http_answers(self):
        with patch('titan.app_networks._probe_cached', return_value={'pending': True}) as probe:
            self.assertEqual(self.readiness()['web_state'], 'initializing')
            self.assertFalse(self.readiness()['web_available'])
            # The public-looking LAN endpoint does not become a remote request.
            self.assertEqual(probe.call_args[0][1][:3], ('127.0.0.1', 18096, 'http'))
        with patch('titan.app_networks._probe_cached', return_value={'ok': True, 'http_status': 401, 'checked_at': 123}):
            result = self.readiness()
            self.assertTrue(result['web_available'])
            self.assertEqual(result['web_checked_at'], 123)
            self.assertEqual(result['web_http_status'], 401)

    def test_failed_http_diagnostic_distinguishes_startup_from_old_failure(self):
        with patch('titan.app_networks._probe_cached', return_value={'ok': False, 'message': 'Port nicht erreichbar'}):
            self.assertEqual(self.readiness()['web_state'], 'error')
            self.container['State'].pop('StartedAt')
            self.record['changed'] = time.time()
            self.assertEqual(self.readiness()['web_state'], 'initializing')
            self.record['last_error'] = 'start failed'
            self.assertEqual(self.readiness()['web_state'], 'error')

    def test_stopped_missing_headless_and_unhealthy_never_probe(self):
        with patch('titan.app_networks._probe_cached') as probe:
            self.container['State']['Status'] = 'exited'
            self.assertEqual(self.readiness()['web_state'], 'stopped')
            self.assertEqual(app_readiness(self.host, None, self.record, None)['web_state'], 'missing')
            self.container['State']['Status'] = 'running'
            with patch.dict(APPS, {'jellyfin': {**APPS['jellyfin'], 'web_available': False, 'port': 0}}):
                self.assertEqual(self.readiness()['web_state'], 'background')
                self.assertFalse(self.readiness()['web_available'])
            self.container['State']['Health'] = {'Status': 'unhealthy'}
            self.assertEqual(self.readiness()['web_state'], 'error')
            probe.assert_not_called()

    def test_loopback_only_service_never_offers_browser_launch(self):
        self.summary['endpoints'][0].update(address='127.0.0.1', scope='loopback')
        self.container['NetworkSettings']['Ports']['8096/tcp'][0]['HostIp'] = '127.0.0.1'
        with patch('titan.app_networks._probe_cached', return_value={'ok': True, 'message': 'ready'}):
            result = self.readiness()
            self.assertFalse(result['web_available'])
            self.assertIn('nur lokal', result['web_message'])

    def test_bound_lan_address_and_dynamic_host_port_are_used_exactly(self):
        self.container['NetworkSettings']['Ports']['8096/tcp'][0]['HostIp'] = '192.168.10.18'
        with patch('titan.app_networks._probe_cached', return_value={'pending': True}) as probe:
            self.readiness()
            self.assertEqual(probe.call_args[0][1][0], '192.168.10.18')
        self.record.update(id='qbittorrent', port=18080)
        self.container['HostConfig']['NetworkMode'] = 'host'
        self.summary['endpoints'][0]['port'] = 18080
        with patch('titan.app_networks._probe_cached', return_value={'pending': True}) as probe:
            self.readiness()
            self.assertEqual(probe.call_args[0][1][:2], ('127.0.0.1', 18080))

    def test_explicit_trusted_hostname_is_only_http_header_never_dns_dial_target(self):
        self.record['id'] = 'titan-nextcloud-office'
        self.host._app_options = lambda app: {'nas_host': 'nas.example.test'}
        self.container['NetworkSettings']['Ports'] = {str(APPS[self.record['id']]['port']) + '/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '18096'}]}
        with patch('titan.app_networks._probe_cached', return_value={'pending': True}) as probe:
            self.readiness()
            self.assertEqual(probe.call_args[0][1][0], '127.0.0.1')
            self.assertEqual(probe.call_args[0][1][-1], 'nas.example.test')

    def test_cache_is_nonblocking_bounded_deduplicated_and_restart_sensitive(self):
        release = threading.Event()
        key = ('cache-test', time.monotonic())
        with patch('titan.app_networks._http_probe', side_effect=lambda *args: (release.wait(2), {'ok': True})[1]) as probe:
            before = time.monotonic()
            try:
                for _ in range(50):
                    self.assertTrue(_probe_cached(key, ('127.0.0.1', 12345, 'http'))['pending'])
                self.assertLess(time.monotonic() - before, .3)
                deadline = time.monotonic() + 1
                while probe.call_count == 0 and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(probe.call_count, 1)
                self.container['State']['StartedAt'] = '2026-01-01T00:00:00Z'
                with patch('titan.app_networks._probe_cached', return_value={'pending': True}) as cached:
                    self.readiness()
                    original = cached.call_args[0][0]
                    self.container['State']['StartedAt'] = '2026-01-02T00:00:00Z'
                    self.readiness()
                    self.assertNotEqual(original, cached.call_args[0][0])
            finally:
                release.set()
        deadline = time.monotonic() + 2
        while app_networks._PROBE_CACHE.get(key, {}).get('pending') and time.monotonic() < deadline:
            time.sleep(.01)
        with app_networks._PROBE_LOCK:
            app_networks._PROBE_CACHE.pop(key, None)

    def probe_server(self, response, delay=0):
        server = socket.socket()
        server.bind(('127.0.0.1', 0))
        server.listen(1)
        port = server.getsockname()[1]
        def serve():
            try:
                connection, _ = server.accept()
                with connection:
                    connection.recv(4096)
                    if delay:
                        time.sleep(delay)
                    connection.sendall(response)
            except OSError:
                pass
            finally:
                server.close()
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        return port

    def test_real_http_status_auth_redirect_and_errors_without_redirect_follow(self):
        for status, expected in ((200, True), (302, True), (401, True), (403, True), (503, False), (404, False)):
            with self.subTest(status=status):
                port = self.probe_server(f'HTTP/1.1 {status} Test\r\nLocation: http://169.254.169.254/\r\nContent-Length: 0\r\n\r\n'.encode())
                self.assertEqual(_http_probe('127.0.0.1', port, 'http')['ok'], expected)

    def test_slow_or_non_http_responses_have_a_strict_deadline(self):
        port = self.probe_server(b'HTTP/1.1 200 OK\r\n\r\n', delay=1.2)
        before = time.monotonic()
        self.assertFalse(_http_probe('127.0.0.1', port, 'http')['ok'])
        self.assertLess(time.monotonic() - before, 1.15)
        port = self.probe_server(b'not an HTTP server\r\n')
        self.assertFalse(_http_probe('127.0.0.1', port, 'http')['ok'])
        with patch('titan.app_networks.socket.create_connection') as connect:
            self.assertFalse(_http_probe('127.0.0.1', 80, 'http', '/\r\nInjected: bad')['ok'])
            connect.assert_not_called()


if __name__ == '__main__':
    unittest.main()

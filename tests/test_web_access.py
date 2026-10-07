import copy
import json
from pathlib import Path
import tempfile
import unittest
import threading
from unittest.mock import Mock, patch

from titan.core import Error, atomic_json
from titan.web_access import WebAccess, WebAccessMixin, allowed_origins, caddy_config, initial_config, read_config, reserved_ports, validate_settings


class Timer:
    def __init__(self, delay, callback):
        self.delay, self.callback, self.cancelled = delay, callback, False

    def cancel(self):
        self.cancelled = True


class WebAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.now = 1000
        self.timers, self.commands, self.firewalls = [], [], []
        self.occupied, self.failure = set(), None
        initial = initial_config('192.168.10.18')
        atomic_json(self.directory / 'web-access.json', initial, mode=0o644)
        self.manager = WebAccess(self.directory, run=self.command, clock=lambda: self.now, schedule=self.schedule,
                                 firewall=lambda ports: self.firewalls.append(ports) or {'available': True, 'managed_rules': len(ports)})

    def command(self, command, timeout=0):
        self.commands.append(command)
        if self.failure and command[0] == self.failure:
            self.failure = None
            raise Error('Disposable command failed', 503)
        if command[0] == 'ss':
            return 'LISTEN 0 128 0.0.0.0:8080' if int(command[-1].split(':')[-1]) in self.occupied else ''
        return ''

    def schedule(self, delay, callback):
        timer = Timer(delay, callback)
        self.timers.append(timer)
        return timer

    def apply(self, **changes):
        current = self.manager.status()
        return self.manager.apply({**current['settings'], **changes}, current['revision'])

    def test_defaults_https_redirect_preserves_uri_and_internal_office(self):
        config = self.manager.config()
        text = caddy_config(config)
        self.assertIn('https://192.168.10.18 {', text)
        self.assertIn('http://192.168.10.18 {', text)
        self.assertIn('redir https://192.168.10.18{uri} 308', text)
        self.assertIn('header_up Host 192.168.10.18', text)
        self.assertEqual(reserved_ports(self.manager.path), {80, 443, 5001, 5101})

    def test_custom_ports_old_endpoint_survives_until_confirmation(self):
        result = self.apply(http_port=8080, https_port=8443)
        self.assertEqual(result['origin'], 'https://192.168.10.18:8443')
        self.assertTrue(result['pending'])
        self.assertEqual(result['deadline'], 1120)
        text = (self.directory / 'Caddyfile').read_text()
        self.assertIn('https://192.168.10.18 {', text)
        self.assertIn('redir https://192.168.10.18:8443{uri} 308', text)
        self.assertEqual(allowed_origins(self.manager.config()), {'https://192.168.10.18', result['origin']})
        self.assertFalse(any(command[:2] == ['systemctl', 'restart'] for command in self.commands))
        self.timers[0].callback()
        self.assertIn(['systemctl', 'restart', 'titan-proxy.service'], self.commands)
        with self.assertRaisesRegex(Error, 'neue Webadresse'):
            self.manager.confirm(result['revision'], 'https://192.168.10.18')
        done = self.manager.confirm(result['revision'], result['origin'])
        self.assertTrue(done['pending'])
        self.assertTrue(done['confirming'])
        self.timers[-1].callback()
        self.assertFalse(self.manager.status()['pending'])
        self.assertNotIn('https://192.168.10.18 {', (self.directory / 'Caddyfile').read_text())
        self.assertEqual(allowed_origins(self.manager.config()), {result['origin']})
        self.assertEqual(self.manager.path.stat().st_mode & 0o777, 0o644)
        self.assertFalse(any('reload' in command for command in self.commands))

    def test_unconfirmed_change_restores_after_timeout_and_agent_restart(self):
        previous = self.manager.status()
        result = self.apply(https_port=8443)
        self.now = 1130
        resumed = WebAccess(self.directory, run=self.command, clock=lambda: self.now, schedule=self.schedule)
        resumed.resume()
        self.assertEqual(self.timers[-1].delay, 0)
        self.timers[-1].callback()
        restored = resumed.status()
        self.assertEqual(restored['settings'], previous['settings'])
        self.assertFalse(restored['pending'])
        self.assertIn('nicht rechtzeitig', restored['last_error'])
        with self.assertRaises(Error):
            resumed.confirm(result['revision'], result['origin'])

    def test_occupied_internal_and_invalid_ports_leave_previous_config(self):
        before = self.manager.path.read_bytes()
        self.occupied = {8080}
        with self.assertRaisesRegex(Error, 'bereits verwendet'):
            self.apply(http_port=8080)
        for value in (True, 0, 65536, 5001, 5101, '443'):
            with self.assertRaises(Error):
                self.apply(https_port=value)
        with self.assertRaises(Error):
            self.apply(https_port=80)
        self.assertEqual(self.manager.path.read_bytes(), before)

    def test_failed_validation_or_activation_recovers_working_config(self):
        before = self.manager.status()['settings']
        self.failure = 'runuser'
        with self.assertRaises(Error):
            self.apply(https_port=8443)
        self.assertEqual(self.manager.status()['settings'], before)
        self.assertEqual(self.timers, [])
        result = self.apply(https_port=8443)
        self.failure = 'systemctl'
        self.timers[0].callback()
        self.assertEqual(self.manager.status()['settings'], before)
        self.assertFalse(self.manager.status()['pending'])
        self.assertIn('aktiviert', self.manager.status()['last_error'])

    def test_http_only_and_old_revision_cannot_override_pending_change(self):
        result = self.apply(mode='http')
        self.assertEqual(result['origin'], 'http://192.168.10.18')
        self.assertNotIn('redir ', (self.directory / 'Caddyfile').read_text())
        with self.assertRaises(Error):
            self.manager.apply(result['settings'], 'old-revision')
        with self.assertRaises(Error):
            self.manager.apply(result['settings'], result['revision'])
        self.manager.rollback()
        self.assertEqual(self.manager.status()['settings']['mode'], 'https')

    def test_stopped_app_tcp_reservations_block_web_change_under_shared_lock(self):
        class Agent(WebAccessMixin):
            def __init__(self):
                self.app_config_lock = threading.RLock()
                self._web_access = Mock()
            def load(self, name, default):
                return [{'id': 'jellyfin', 'name': 'Jellyfin', 'port': 8080, 'network': {'mode': 'default'}}]
            def _app_options(self, app):
                return {}
        agent = Agent()
        with self.assertRaisesRegex(Error, 'Jellyfin'):
            agent.op_web_access_apply({'mode': 'http', 'http_port': 8080, 'https_port': 443}, 'revision')
        agent.web_access.apply.assert_not_called()
        # UDP-only services do not occupy a TCP listener with the same number.
        with patch('titan.catalog.published_ports', return_value=[{'host': 8080, 'target': 8080, 'protocol': 'udp'}]):
            agent.web_access.apply.side_effect = lambda *args: self.assertTrue(agent.app_config_lock._is_owned())
            agent.op_web_access_apply({'mode': 'http', 'http_port': 8080, 'https_port': 443}, 'revision')
        agent.web_access.apply.assert_called_once()

    def test_manual_legacy_manager_persists_working_endpoint_and_stable_revision(self):
        self.manager.path.unlink()
        manager = WebAccess(self.directory, previous_origin='https://192.168.10.18:5000', host='192.168.10.18',
                            run=self.command, schedule=self.schedule, clock=lambda: self.now)
        first, second = manager.status(), manager.status()
        self.assertEqual(first['origin'], 'https://192.168.10.18:5000')
        self.assertEqual(first['revision'], second['revision'])
        self.assertEqual(read_config(manager.path)['settings']['https_port'], 5000)
        self.assertEqual(initial_config('nas.local', 'http://nas.local:443')['settings']['http_port'], 443)
        self.assertEqual(initial_config('nas.local', 'https://nas.local:80')['settings']['https_port'], 80)
        changed = manager.apply({**first['settings'], 'https_port': 8443}, first['revision'])
        self.assertEqual(changed['previous_origin'], first['origin'])

    def test_rollback_restart_failure_retains_recovery_and_retries_with_backoff(self):
        self.apply(https_port=8443)
        self.now = 1130
        self.failure = 'systemctl'
        with self.assertRaisesRegex(Error, 'Webdienst konnte nicht starten'):
            self.manager.rollback()
        self.assertTrue(self.manager.status()['pending'])
        self.assertEqual(self.timers[-1].delay, 15)
        self.timers[-1].callback()
        self.assertFalse(self.manager.status()['pending'])

    def test_no_private_lan_never_removes_baseline_firewall_service(self):
        previous = self.manager.status()['settings']
        self.manager.firewall = lambda ports: {'available': True, 'managed_rules': 0, 'warnings': ['No LAN']}
        with self.assertRaisesRegex(Error, 'privates LAN'):
            self.apply(https_port=8443)
        self.assertEqual(self.manager.status()['settings'], previous)
        self.assertFalse(any('--remove-service=titan' in command for command in self.commands))

    def test_confirm_firewall_failure_keeps_pending_and_retry_recovers(self):
        result = self.apply(https_port=8443)
        firewalls = self.manager.firewall
        def failed(ports):
            if {item['host'] for item in ports} == {80, 8443}:
                raise Error('cleanup failure')
            return firewalls(ports)
        self.manager.firewall = failed
        with self.assertRaisesRegex(Error, 'cleanup failure'):
            self.manager.confirm(result['revision'], result['origin'])
        self.assertTrue(self.manager.status()['pending'])
        self.assertFalse(self.manager.status()['confirming'])
        self.assertIn('https://192.168.10.18 {', (self.directory / 'Caddyfile').read_text())
        self.manager.firewall = firewalls
        self.manager.confirm(result['revision'], result['origin'])
        self.timers[-1].callback()
        self.assertFalse(self.manager.status()['pending'])

    def test_confirm_activation_survives_agent_restart_and_failure_remains_retryable(self):
        result = self.apply(https_port=8443)
        self.manager.confirm(result['revision'], result['origin'])
        self.assertTrue(read_config(self.manager.path)['pending']['confirmed'])
        resumed = WebAccess(self.directory, run=self.command, clock=lambda: self.now, schedule=self.schedule,
                            firewall=self.manager.firewall)
        resumed.resume()
        self.failure = 'systemctl'
        self.timers[-1].callback()
        self.assertTrue(resumed.status()['pending'])
        self.assertFalse(resumed.status()['confirming'])
        self.assertIn('Aktivierung fehlgeschlagen', resumed.status()['last_error'])
        resumed.confirm(result['revision'], result['origin'])
        self.timers[-1].callback()
        self.assertFalse(resumed.status()['pending'])

    def test_rollback_starts_old_listener_even_when_firewall_cleanup_fails(self):
        before = self.manager.status()['settings']
        self.apply(https_port=8443)
        self.manager.firewall = lambda ports: (_ for _ in ()).throw(Error('firewall unavailable'))
        restored = self.manager.rollback()
        self.assertEqual(restored['settings'], before)
        self.assertFalse(restored['pending'])
        self.assertIn('Firewallbereinigung', restored['last_error'])
        self.assertIn(['systemctl', 'restart', 'titan-proxy.service'], self.commands)

    def test_legacy_installation_keeps_working_port_and_invalid_config_fails_closed(self):
        value = initial_config('nas.example', 'https://nas.example:5000')
        self.assertEqual(value['settings']['https_port'], 5000)
        value['settings']['mode'] = 'injected\nrespond 200'
        self.manager.path.write_text(json.dumps(value))
        with self.assertRaises(Error):
            read_config(self.manager.path)


if __name__ == '__main__':
    unittest.main()

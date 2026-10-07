"""Remote access validation, public connection bounds and local recovery."""
import copy
import contextlib
import io
import json
from pathlib import Path
import socket
import ssl
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from titan.core import Error, atomic_json
from titan.remote_access import (RemoteAccessMixin, TUNNEL_PORT, probe_public, proof,
    public_url, tunnel_caddy, validate_remote)
from titan.web_access import WebAccess, allowed_origins, caddy_config, initial_config


def remote_settings(*, bridge=False, enabled=True):
    return {**validate_remote(None), 'enabled': enabled,
        'public_origin': 'https://nas.example.com', 'connector': 'cloudflared',
        'app_urls': {'photos': 'https://photos.example.com/library'},
        **({'sources': ['172.30.10.0/24'], 'interface': 'br-123456789abc',
            'service_url': 'http://172.30.10.1:5102'} if bridge else
           {'service_url': 'http://127.0.0.1:5102'})}


def remote_config(**options):
    return {**initial_config('192.168.10.18'), 'revision': 'test-revision',
        'remote': remote_settings(**options)}


class RemoteValidationTests(unittest.TestCase):
    def test_public_https_domain_normalization_and_explicit_application_path(self):
        self.assertEqual(public_url('https://NAS.Example.com:443/'), 'https://nas.example.com')
        self.assertEqual(public_url('https://photos.example.com/library', application=True),
            'https://photos.example.com/library')
        with self.assertRaises(Error):
            public_url('https://nas.example.com/private-path')

    def test_public_addresses_reject_credentials_private_literals_and_unsafe_syntax(self):
        for address in (None, '', [], 123, 'http://nas.example.com', 'https://user:pass@nas.example.com',
                'https://nas.example.com:8443', 'https://nas.example.com?q=secret', 'https://nas.example.com#fragment',
                'https://127.0.0.1', 'https://192.168.10.18', 'https://8.8.8.8', 'https://[::1]',
                'https://nas.local', 'https://nas.localhost', 'https://localhost',
                'https://bad..example.com', 'https://nas.example.com\n', 'https://nas.example.com/ space',
                'https://näs.example.com'):
            with self.subTest(address=address), self.assertRaises(Error):
                public_url(address, application=True)

    def test_remote_configuration_rejects_unbounded_sources_targets_and_unknown_fields(self):
        bad = ({'sources': ['0.0.0.0/0'], 'interface': 'docker0'},
            {'sources': ['8.8.8.0/24'], 'interface': 'docker0'},
            {'sources': ['172.30.10.1/24'], 'interface': 'docker0'},
            {'sources': ['fc00::/64'], 'interface': 'docker0'},
            {'sources': ['172.30.10.0/24'], 'interface': ''},
            {'sources': ['172.30.10.0/24'], 'interface': 'docker0\nrespond 200'},
            {'service_url': 'http://192.168.10.18:5102'},
            {'service_url': 'https://127.0.0.1:5102'},
            {'service_url': 'http://127.0.0.1:5001'},
            {'service_url': 'http://user:pass@127.0.0.1:5102'},
            {'service_url': 'http://[127.0.0.1:5102'},
            {'service_url': 'http://127.0.0.1:5102/path'},
            {'service_url': 'http://127.0.0.1:5102?key=secret'},
            {'enabled': 1}, {'public_origin': ''}, {'unexpected': True},
            {'app_urls': {'invalid\napp': 'https://app.example.com'}})
        for change in bad:
            with self.subTest(change=change), self.assertRaises(Error):
                validate_remote({**remote_settings(), **change})
        self.assertEqual(validate_remote(remote_settings(bridge=True))['service_url'], 'http://172.30.10.1:5102')

    def test_remote_configuration_rejects_wrong_text_types_even_when_disabled(self):
        for field in ('public_origin', 'service_url', 'connector', 'interface'):
            for value in (None, [], {}, 123):
                with self.subTest(field=field, value=value), self.assertRaises(Error):
                    validate_remote({**remote_settings(enabled=False), field: value})

    def test_caddy_host_and_bridge_listeners_require_public_host_and_connector_source(self):
        for bridge in (False, True):
            with self.subTest(bridge=bridge):
                config = remote_config(bridge=bridge)
                text = tunnel_caddy(config)
                self.assertIn('http://:5102 {', text)
                if bridge: self.assertNotIn('bind 127.0.0.1', text)
                else: self.assertIn('bind 127.0.0.1', text)
                self.assertIn('host nas.example.com', text)
                self.assertIn('remote_ip 127.0.0.1/32' + (' 172.30.10.0/24' if bridge else '') + '\n', text)
                self.assertIn('header_up X-Forwarded-Proto https', text)
                self.assertIn('respond 403', text)
                self.assertNotIn('redir ', text)
                self.assertNotIn('0.0.0.0/0', text)
                self.assertNotIn('header_up Host ', text)
        self.assertEqual(tunnel_caddy(remote_config(enabled=False)), '')

    def test_only_enabled_titan_public_origin_is_dynamically_trusted(self):
        config = remote_config()
        self.assertEqual(allowed_origins(config), {'https://192.168.10.18', 'https://nas.example.com'})
        self.assertNotIn('https://photos.example.com', allowed_origins(config))
        config['remote']['enabled'] = False
        self.assertEqual(allowed_origins(config), {'https://192.168.10.18'})
        config['pending'] = {'previous': {**initial_config('192.168.10.18'),
            'settings': {'mode': 'https', 'http_port': 80, 'https_port': 8443}}, 'deadline': 1234}
        self.assertIn('https://192.168.10.18:8443', allowed_origins(config))


class PublicProbeTests(unittest.TestCase):
    def setUp(self):
        self.config = remote_config()
        self.challenge = 'a' * 32
        self.raw, self.secured, self.connection, self.response = Mock(), Mock(), Mock(), Mock()
        self.response.status = 200
        self.response.read.return_value = json.dumps({'service': 'Titan', 'challenge': self.challenge,
            'proof': proof(self.config)}).encode()
        self.connection.getresponse.return_value = self.response
        self.context = Mock()
        self.context.wrap_socket.return_value = self.secured
        self.dns = self.enterContext(patch('titan.remote_access.socket.getaddrinfo',
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.1.1.1', 443))]))
        self.connect = self.enterContext(patch('titan.remote_access.socket.create_connection', return_value=self.raw))
        self.enterContext(patch('titan.remote_access.ssl.create_default_context', return_value=self.context))
        self.https = self.enterContext(patch('titan.remote_access.http.client.HTTPSConnection', return_value=self.connection))
        self.enterContext(patch('titan.remote_access.secrets.token_hex', return_value=self.challenge))

    def test_dns_is_pinned_to_public_address_with_verified_tls_hostname(self):
        self.assertTrue(probe_public(self.config)['ok'])
        self.dns.assert_called_once_with('nas.example.com', 443, type=socket.SOCK_STREAM)
        self.connect.assert_called_once_with(('1.1.1.1', 443), timeout=4)
        self.context.wrap_socket.assert_called_once_with(self.raw, server_hostname='nas.example.com')
        self.assertIs(self.connection.sock, self.secured)
        self.connection.request.assert_called_once_with('GET', '/api/tunnel-health?challenge=' + self.challenge,
            headers={'Host': 'nas.example.com', 'Accept': 'application/json'})
        self.response.read.assert_called_once_with(4097)
        self.connection.close.assert_called_once()

    def test_any_nonpublic_dns_answer_prevents_all_network_connections(self):
        for address in ('0.0.0.0', '127.0.0.1', '10.0.0.1', '169.254.169.254', '192.168.10.18',
                '100.64.0.1', '::1', '::ffff:127.0.0.1', 'fc00::18', 'fe80::1', '224.0.0.1', 'ff02::1', '240.0.0.1'):
            with self.subTest(address=address):
                self.dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.1.1.1', 443)),
                    (socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))]
                self.assertFalse(probe_public(self.config)['ok'])
        self.connect.assert_not_called()
        self.https.assert_not_called()

    def test_redirects_are_reported_without_following_or_forwarding_credentials(self):
        for status in (301, 302, 307, 308, 403, 502):
            with self.subTest(status=status):
                self.response.status = status
                self.connection.request.reset_mock()
                result = probe_public(self.config)
                self.assertFalse(result['ok'])
                self.assertEqual(result['status'], status)
                self.assertEqual(self.connection.request.call_count, 1)
                self.assertEqual(set(self.connection.request.call_args.kwargs['headers']), {'Host', 'Accept'})

    def test_wrong_challenge_revision_or_oversized_response_never_proves_titan(self):
        payloads = [{'service': 'Titan', 'challenge': 'b' * 32, 'proof': proof(self.config)},
            {'service': 'Titan', 'challenge': self.challenge, 'proof': 'old-revision'},
            {'service': 'other', 'challenge': self.challenge, 'proof': proof(self.config)}]
        for payload in [*(json.dumps(value).encode() for value in payloads), b'[]', b'bad json', b'x' * 4097]:
            with self.subTest(payload=payload[:60]):
                self.response.read.return_value = payload
                self.assertFalse(probe_public(self.config)['ok'])

    def test_tls_failure_closes_unwrapped_socket_and_disabled_probe_does_not_resolve(self):
        self.context.wrap_socket.side_effect = ssl.SSLError('untrusted certificate')
        self.assertFalse(probe_public(self.config)['ok'])
        self.raw.close.assert_called_once()
        self.connection.request.assert_not_called()
        self.dns.reset_mock()
        self.config['remote']['enabled'] = False
        self.assertFalse(probe_public(self.config)['ok'])
        self.dns.assert_not_called()


class RemoteSaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.initial = initial_config('192.168.10.18')
        atomic_json(self.root / 'web-access.json', self.initial, mode=0o644)
        self.commands, self.callbacks, self.remote_firewalls = [], [], []
        self.failure, self.occupied = None, False
        self.manager = WebAccess(self.root, run=self.command, schedule=self.schedule,
            firewall=lambda ports: {'available': False},
            remote_firewall=lambda value: self.remote_firewalls.append(copy.deepcopy(value)))
        self.manager._write_runtime(self.initial)

    def command(self, arguments, timeout=0):
        self.commands.append(arguments)
        if arguments[0] == self.failure:
            self.failure = None
            raise Error('Disposable activation failure')
        return 'LISTEN occupied' if arguments[0] == 'ss' and self.occupied else ''

    def schedule(self, delay, callback):
        self.callbacks.append(callback)
        return Mock()

    def save(self, remote=None):
        return self.manager.save_remote(remote or remote_settings(), self.manager.config()['revision'])

    def test_remote_save_keeps_local_settings_and_restarts_only_after_response(self):
        before = self.manager.config()
        self.save()
        self.assertEqual(self.manager.config()['settings'], before['settings'])
        self.assertEqual(self.manager.config()['host'], before['host'])
        self.assertEqual((self.root / 'web.env').read_text(), 'TITAN_ORIGIN=https://192.168.10.18\n')
        self.assertIn('https://192.168.10.18 {', (self.root / 'Caddyfile').read_text())
        self.assertIn('http://:5102 {', (self.root / 'Caddyfile').read_text())
        self.assertIn('bind 127.0.0.1', (self.root / 'Caddyfile').read_text())
        self.assertFalse(any(command[0] == 'systemctl' for command in self.commands))
        self.callbacks[-1]()
        self.assertIn(['systemctl', 'restart', 'titan-proxy.service'], self.commands)

    def test_stale_revision_pending_change_and_occupied_internal_port_leave_local_config(self):
        before = self.manager.path.read_bytes()
        with self.assertRaises(Error):
            self.manager.save_remote(remote_settings(), 'stale')
        self.occupied = True
        with self.assertRaisesRegex(Error, 'belegt'):
            self.save()
        self.assertEqual(self.manager.path.read_bytes(), before)
        self.assertEqual(self.callbacks, [])
        self.occupied = False
        self.manager.apply({**self.initial['settings'], 'https_port': 8443}, self.initial['revision'])
        with self.assertRaises(Error): self.save()

    def test_invalid_caddy_or_remote_firewall_restores_runtime_before_returning_error(self):
        before = self.manager.path.read_bytes()
        self.failure = 'runuser'
        with self.assertRaises(Error): self.save()
        self.assertEqual(self.manager.path.read_bytes(), before)
        self.assertEqual((self.root / 'Caddyfile').read_text(), caddy_config(self.initial))
        self.assertEqual(self.callbacks, [])
        def fail_enabled(value):
            if value and value.get('enabled'): raise Error('remote firewall failed')
        self.manager.remote_firewall = fail_enabled
        with self.assertRaisesRegex(Error, 'remote firewall'): self.save()
        self.assertEqual(self.manager.path.read_bytes(), before)
        self.assertEqual((self.root / 'Caddyfile').read_text(), caddy_config(self.initial))

    def test_failed_restart_restores_local_configuration_and_previous_remote(self):
        self.save()
        self.failure = 'systemctl'
        self.callbacks[-1]()
        config = self.manager.config()
        self.assertEqual(config['settings'], self.initial['settings'])
        self.assertFalse(config.get('remote', {}).get('enabled'))
        self.assertIn('wiederhergestellt', config['last_error'])
        self.assertEqual((self.root / 'Caddyfile').read_text(), caddy_config(config))
        self.assertEqual(sum(command[0] == 'systemctl' for command in self.commands), 2)

    def test_failed_restart_still_restores_local_config_when_firewall_cleanup_fails(self):
        self.save()
        self.manager.remote_firewall = Mock(side_effect=Error('cleanup unavailable'))
        self.failure = 'systemctl'
        try:
            self.callbacks[-1]()
        except Error:
            pass
        config = self.manager.config()
        self.assertFalse(config.get('remote', {}).get('enabled'))
        self.assertEqual(config['settings'], self.initial['settings'])
        self.assertEqual(sum(command[0] == 'systemctl' for command in self.commands), 2)

    def test_obsolete_remote_activation_cannot_restart_a_newer_config(self):
        self.save()
        obsolete = self.callbacks[-1]
        self.save({**remote_settings(), 'public_origin': 'https://other.example.com'})
        obsolete()
        self.assertFalse(any(command[0] == 'systemctl' for command in self.commands))
        self.callbacks[-1]()
        self.assertEqual(sum(command[0] == 'systemctl' for command in self.commands), 1)


class RemoteAgent(RemoteAccessMixin):
    def __init__(self, config=None):
        self.rows = {'apps': [{'id': 'cloudflared', 'name': 'Tunnel'}, {'id': 'photos', 'name': 'Photos'}]}
        self.app_config_lock = threading.RLock()
        self.web_access = Mock()
        self.web_access.config.return_value = config or remote_config()
        self.container = {'HostConfig': {'NetworkMode': 'host'},
            'State': {'Running': True, 'Pid': 2345}, 'NetworkSettings': {'Networks': {}}}
        self.network = {'Id': '123456789abcdef', 'Driver': 'bridge', 'Scope': 'local',
            'IPAM': {'Config': [{'Subnet': '172.30.10.0/24', 'Gateway': '172.30.10.1'}]}}
    def load(self, key, default): return copy.deepcopy(self.rows.get(key, default))
    def save(self, key, value): self.rows[key] = copy.deepcopy(value)
    def managed_app(self, app): return next(row for row in self.rows['apps'] if row['id'] == app)
    def _app_container(self, app, record): return self.container
    def _docker_network(self, name): return copy.deepcopy(self.network)
    def _network_subnets(self, network):
        return [{'subnet': row['Subnet'], 'gateway': row['Gateway'], 'family': 4} for row in network['IPAM']['Config']]


class ConnectorDiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict('titan.catalog.APPS', {'cloudflared': {'image': 'wisdomsky/cloudflared-web:2026.9.3'}}))
        self.agent = RemoteAgent()

    def test_observed_host_and_bridge_endpoints_and_rejection_of_unknown_connector(self):
        host = self.agent._connector_settings('cloudflared')
        self.assertEqual(host, {'sources': [], 'interface': '', 'service_url': 'http://127.0.0.1:5102'})
        self.agent.container['HostConfig']['NetworkMode'] = 'bridge'
        self.agent.container['NetworkSettings']['Networks'] = {'titan-tunnel_default': {}}
        self.assertEqual(self.agent._connector_settings('cloudflared'),
            {'sources': ['172.30.10.0/24'], 'interface': 'br-123456789abc', 'service_url': 'http://172.30.10.1:5102'})
        self.agent.network['Internal'] = True
        with self.assertRaises(Error): self.agent._connector_settings('cloudflared')
        with self.assertRaises(Error): self.agent._connector_settings('photos')

    def test_public_app_urls_are_only_accepted_for_installed_apps(self):
        with self.assertRaises(Error):
            self.agent.op_remote_access_apply(True, 'https://nas.example.com', '',
                {'unknown': 'https://app.example.com'}, 'revision')
        self.agent.web_access.save_remote.assert_not_called()

    def test_remote_firewall_scopes_only_selected_docker_source_with_zone_fallback(self):
        def run(command, timeout=0):
            if command == ['firewall-cmd', '--state']: return 'running'
            if command[1].startswith('--get-zone-of-interface='): raise Error('no zone')
            if command == ['firewall-cmd', '--get-default-zone']: return 'public'
            self.fail('Unexpected unbounded firewall command: ' + repr(command))
        with patch('titan.host.run', side_effect=run), patch('titan.app_firewall.reconcile') as reconcile:
            self.agent._remote_firewall(remote_settings(bridge=True))
        reconcile.assert_called_once_with(self.agent, 'remote-tunnel', [{'host': TUNNEL_PORT, 'protocol': 'tcp'}],
            scopes_override=[{'zone': 'public', 'source': '172.30.10.0/24', 'family': 4, 'address': '172.30.10.1'}])

    def test_inactive_firewall_never_queries_or_opens_a_broad_zone(self):
        with patch('titan.host.run', side_effect=Error('not running')) as run, \
                patch('titan.app_firewall.reconcile', return_value={'available': False}) as reconcile:
            self.assertFalse(self.agent._remote_firewall(remote_settings(bridge=True))['available'])
        run.assert_called_once_with(['firewall-cmd', '--state'], timeout=3)
        reconcile.assert_called_once_with(self.agent, 'remote-tunnel', [{'host': TUNNEL_PORT, 'protocol': 'tcp'}], scopes_override=[])

    def test_loopback_or_disabled_remote_clears_only_remote_firewall_owner(self):
        for remote in (remote_settings(), remote_settings(enabled=False)):
            with self.subTest(remote=remote), patch('titan.host.run') as run, patch('titan.app_firewall.reconcile') as reconcile:
                self.agent._remote_firewall(remote)
                run.assert_not_called()
                reconcile.assert_called_once_with(self.agent, 'remote-tunnel', [], scopes_override=[])

    def test_diagnosis_enters_only_observed_network_namespace_with_public_host(self):
        with patch('titan.host.run', return_value='200\n') as run, \
                patch('titan.remote_access.probe_public', return_value={'ok': True, 'message': 'reachable'}):
            result = self.agent.op_remote_access_diagnose()
        command = run.call_args.args[0]
        self.assertEqual(command[:7], ['nsenter', '-t', '2345', '-n', '--', '/usr/bin/python3', '-c'])
        self.assertIn('127.0.0.1', command[7])
        self.assertIn('nas.example.com', command[7])
        self.assertIn(proof(self.agent.web_access.config()), command[7])
        self.assertIn('r.read(4097)', command[7])
        self.assertNotIn('docker exec', ' '.join(command))
        self.assertEqual(run.call_args.kwargs['timeout'], 5)
        self.assertTrue(result['connected'])
        self.assertTrue(next(check for check in result['checks'] if check['name'] == 'Titan vom Connector erreichbar')['ok'])
        self.assertEqual(self.agent.rows['remote-diagnosis'], result)

    def test_namespace_health_requires_titan_json_and_proof_in_addition_to_http_200(self):
        challenge = 'a' * 32
        config = self.agent.web_access.config()
        expected = {'service': 'Titan', 'challenge': challenge, 'proof': proof(config)}
        response = Mock(status=200)
        connection = Mock()
        connection.getresponse.return_value = response
        def execute_observed_probe(command, timeout=0):
            output = io.StringIO()
            try:
                with contextlib.redirect_stdout(output): exec(command[7], {})
            except (ValueError, TypeError) as exc:
                raise Error('Disposable namespace probe rejected payload') from exc
            return output.getvalue()
        for payload, valid in ((json.dumps(expected).encode(), True), (b'{}', False), (b'', False)):
            with self.subTest(payload=payload), patch('titan.host.run', side_effect=execute_observed_probe), \
                    patch('titan.remote_access.secrets.token_hex', return_value=challenge), \
                    patch('http.client.HTTPConnection', return_value=connection), \
                    patch('titan.remote_access.probe_public', return_value={'ok': False, 'message': 'unavailable'}):
                response.read.return_value = payload
                result = self.agent.op_remote_access_diagnose()
                self.assertEqual(next(check for check in result['checks'] if check['name'] == 'Titan vom Connector erreichbar')['ok'], valid)

    def test_missing_connector_is_reported_without_skipping_public_diagnosis(self):
        with patch.object(self.agent, '_connector_settings', side_effect=Error('Connector disappeared')), \
                patch.object(self.agent, '_app_container', return_value=None), \
                patch('titan.host.run') as run, \
                patch('titan.remote_access.probe_public', return_value={'ok': True, 'message': 'reachable'}) as public:
            result = self.agent.op_remote_access_diagnose()
        self.assertFalse(result['checks'][0]['ok'])
        self.assertIn('Connector disappeared', result['checks'][0]['message'])
        self.assertTrue(result['connected'])
        run.assert_not_called()
        public.assert_called_once()

    def test_stopped_or_invalid_pid_connectors_never_enter_a_namespace(self):
        for state in ({'Running': False, 'Pid': 2345}, {'Running': True, 'Pid': 0},
                {'Running': True, 'Pid': '2345; injected'}, {'Running': True, 'Pid': True}):
            with self.subTest(state=state), patch('titan.host.run') as run, \
                    patch('titan.remote_access.probe_public', return_value={'ok': False, 'message': 'unavailable'}):
                self.agent.container['State'] = state
                self.assertFalse(self.agent.op_remote_access_diagnose()['connected'])
                run.assert_not_called()

    def test_diagnosis_does_not_persist_results_after_configuration_changes(self):
        config = remote_config()
        self.agent.web_access.config.side_effect = [config, {**config, 'revision': 'new'}]
        with patch('titan.host.run', return_value='200'), \
                patch('titan.remote_access.probe_public', return_value={'ok': True, 'message': 'reachable'}):
            self.agent.op_remote_access_diagnose()
        self.assertNotIn('remote-diagnosis', self.agent.rows)


if __name__ == '__main__':
    unittest.main()

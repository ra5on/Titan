"""LAN scoping and ownership preservation against a stateful firewalld fixture."""
import copy
import json
import unittest
from unittest.mock import patch
from titan.app_firewall import reconcile, lan_scopes
from titan.core import Error


class Store:
    def __init__(self):
        self.records = {}
    def load(self, name, default):
        return copy.deepcopy(self.records.get(name, default))
    def save(self, name, value):
        self.records[name] = copy.deepcopy(value)


class AppFirewallTests(unittest.TestCase):
    def setUp(self):
        self.host = Store()
        self.runtime, self.permanent = set(), set()
        self.calls = []
        self.active = True
        self.addresses = [{'ifname': 'enp1s0', 'addr_info': [
            {'local': '192.168.10.18', 'prefixlen': 24}, {'local': 'fd00:123::18', 'prefixlen': 64},
            {'local': '203.0.113.18', 'prefixlen': 24}]},
            {'ifname': 'docker0', 'addr_info': [{'local': '172.17.0.1', 'prefixlen': 16}]},
            {'ifname': 'lo', 'addr_info': [{'local': '127.0.0.1', 'prefixlen': 8}]}]
        patcher = patch('titan.app_firewall._run', side_effect=self.command)
        patcher.start()
        self.addCleanup(patcher.stop)

    def command(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == 'ip':
            return json.dumps(self.addresses)
        if '--state' in args:
            return 'running' if self.active else 'not running'
        if any(value.startswith('--get-zone-of-interface=') for value in args):
            return 'home'
        rules = self.permanent if '--permanent' in args else self.runtime
        rule = next((value.split('=', 1)[1] for value in args if value.startswith(('--query-rich-rule=', '--add-rich-rule=', '--remove-rich-rule='))), None)
        if any(value.startswith('--query-rich-rule=') for value in args):
            if rule not in rules:
                raise Error('no')
            return 'yes'
        if any(value.startswith('--add-rich-rule=') for value in args):
            rules.add(rule)
        if any(value.startswith('--remove-rich-rule=') for value in args):
            rules.remove(rule)
        return 'success'

    def ports(self):
        return [{'host': 14333, 'protocol': 'tcp'}, {'host': 5353, 'protocol': 'udp'}]

    def test_real_needed_protocols_only_lan_source_and_existing_zone_no_reload(self):
        result = reconcile(self.host, 'app:cloudflared-web', self.ports())
        self.assertEqual(result['managed_rules'], 4)
        self.assertEqual(self.runtime, self.permanent)
        self.assertTrue(any('protocol="udp"' in rule for rule in self.runtime))
        self.assertTrue(all('192.168.10.0/24' in rule or 'fd00:123::/64' in rule for rule in self.runtime))
        self.assertFalse(any('203.0.113' in rule or '172.17' in rule for rule in self.runtime))
        self.assertFalse(any('--reload' in args or '--runtime-to-permanent' in args or '--add-port' in ' '.join(args) for args in self.calls))
        self.assertTrue(all('--zone=home' in args for args in self.calls if any('rich-rule=' in arg for arg in args)))

    def test_unassigned_interface_uses_default_zone_for_all_cli_absence_variants(self):
        base = self.command
        self.addresses.append({'ifname': 'titan-ci0', 'addr_info': [{'local': '10.254.254.1', 'prefixlen': 30}]})
        for absent in ('', 'no zone', Error('no zone\n')):
            with self.subTest(absent=str(absent)):
                self.calls.clear()
                def command(args, **kwargs):
                    if '--get-zone-of-interface=enp1s0' in args:
                        self.calls.append(args)
                        if isinstance(absent, Error): raise absent
                        return absent
                    if '--get-default-zone' in args:
                        self.calls.append(args)
                        return 'public\n'
                    return base(args, **kwargs)
                with patch('titan.app_firewall._run', side_effect=command):
                    scopes = lan_scopes()
                    self.assertEqual({row['zone'] for row in scopes if row['source'] == '192.168.10.0/24'}, {'public'})
                    self.assertEqual({row['zone'] for row in scopes if row['source'] == '10.254.254.0/30'}, {'home'})
                    result = reconcile(self.host, 'app:cloudflared-web', [{'host': 14333, 'protocol': 'tcp'}])
                    self.assertEqual(result['managed_rules'], 3)
                rules = [args for args in self.calls if any(arg.startswith('--add-rich-rule=') for arg in args)]
                self.assertTrue(all('--zone=public' in args for args in rules if '192.168.10.0/24' in ' '.join(args)))
                self.assertTrue(all('--zone=home' in args for args in rules if '10.254.254.0/30' in ' '.join(args)))
                self.assertFalse(any('source address="0.0.0.0/0"' in ' '.join(args) for args in self.calls))
                reconcile(self.host, 'app:cloudflared-web', [])

    def test_interface_query_error_does_not_fall_back_or_mutate_rules(self):
        base = self.command
        def command(args, **kwargs):
            if any(arg.startswith('--get-zone-of-interface=') for arg in args):
                raise Error('DBUS_ERROR: access denied')
            return base(args, **kwargs)
        with patch('titan.app_firewall._run', side_effect=command):
            with self.assertRaisesRegex(Error, 'access denied'):
                reconcile(self.host, 'app:cloudflared-web', self.ports())
        self.assertFalse(self.runtime)
        self.assertFalse(self.permanent)
        self.assertFalse(any('--get-default-zone' in args for args in self.calls))

    def test_existing_user_rules_remain_in_each_scope_and_shared_owner_keeps_access(self):
        reconcile(self.host, 'web', self.ports())
        user_runtime = next(iter(self.runtime))
        user_permanent = next(iter(self.permanent))
        self.host.records = {}
        self.runtime = {user_runtime}
        self.permanent = {user_permanent}
        reconcile(self.host, 'app:first', self.ports())
        reconcile(self.host, 'app:second', self.ports())
        reconcile(self.host, 'app:first', [])
        self.assertEqual(len(self.runtime), 4)
        reconcile(self.host, 'app:second', [])
        self.assertEqual(self.runtime, {user_runtime})
        self.assertEqual(self.permanent, {user_permanent})

    def test_restart_repair_and_ip_change_remove_only_retired_owned_subnet_rules(self):
        reconcile(self.host, 'app:test', self.ports())
        self.runtime.clear()  # External firewalld reload removed transient state.
        reconcile(self.host, 'app:test', self.ports())
        self.assertEqual(len(self.runtime), 4)
        self.addresses[0]['addr_info'] = [{'local': '192.168.20.18', 'prefixlen': 24}]
        reconcile(self.host, 'app:test', self.ports())
        self.assertEqual(len(self.runtime), 2)
        self.assertTrue(all('192.168.20.0/24' in rule for rule in self.runtime))
        self.assertEqual(self.runtime, self.permanent)

    def test_loopback_only_ports_and_inactive_firewall_never_open_anything(self):
        reconcile(self.host, 'app:local', [{'host': 18080, 'protocol': 'tcp', 'host_ip': '127.0.0.1'}])
        self.assertFalse(self.runtime)
        self.active = False
        result = reconcile(self.host, 'app:other', self.ports())
        self.assertFalse(result['available'])
        self.assertTrue(result['warnings'])
        self.assertFalse(self.runtime)

    def test_partial_failure_can_retry_without_losing_user_rules(self):
        base = self.command
        def fail(args, **kwargs):
            if '--permanent' in args and any(arg.startswith('--add-rich-rule=') for arg in args):
                raise Error('permanent write failed')
            return base(args, **kwargs)
        with patch('titan.app_firewall._run', side_effect=fail):
            with self.assertRaisesRegex(Error, 'permanent write failed'):
                reconcile(self.host, 'app:test', self.ports())
        self.assertTrue(self.host.load('managed-firewall-v1', {}))
        reconcile(self.host, 'app:test', self.ports())
        self.assertEqual(self.runtime, self.permanent)
        reconcile(self.host, 'app:test', [])
        self.assertFalse(self.runtime)
        self.assertFalse(self.permanent)

    def test_invalid_ledger_fails_before_mutation_and_ipv4_bind_does_not_open_ipv6(self):
        self.host.save('managed-firewall-v1', {'bad': {'rule': '--flush', 'zone': 'home', 'owned': True, 'owners': []}})
        with self.assertRaises(Error):
            reconcile(self.host, 'app:test', self.ports())
        self.assertFalse(self.runtime)
        self.host.records = {}
        reconcile(self.host, 'app:test', [{'host': 14333, 'protocol': 'tcp', 'host_ip': '0.0.0.0'}])
        self.assertEqual(len(self.runtime), 1)
        self.assertIn('family="ipv4"', next(iter(self.runtime)))


if __name__ == '__main__':
    unittest.main()

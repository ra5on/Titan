"""Run first-boot orchestration against a temporary filesystem and command fakes."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('titan_firstboot_fixture', ROOT / 'image/firstboot.py')
firstboot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(firstboot)


class DebianFirstBootTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.commands = []
        self.existing_contexts = False
        self.failure = ''
        self.write('/usr/share/titan/image-info.json', json.dumps({
            'format': 'titan-debian-preview-v1', 'platform': 'debian-preview'}))
        self.write('/usr/share/titan/release-public.pem', 'PUBLIC KEY FIXTURE\n')
        self.write('/etc/samba/smb.conf', '[global]\nworkgroup = FAMILY\n')
        self.write('/sys/fs/selinux/enforce', '1\n')
        self.paths = patch.object(firstboot, 'Path', side_effect=self.path)
        self.runner = patch.object(firstboot, 'run', side_effect=self.command)
        self.identity = patch.object(firstboot.os, 'geteuid', return_value=0)
        self.paths.start(); self.runner.start(); self.identity.start()

    def tearDown(self):
        self.paths.stop(); self.runner.stop(); self.identity.stop()
        self.temporary.cleanup()

    def path(self, value):
        actual = Path(value)
        if actual.is_absolute() and not actual.is_relative_to(self.root):
            return self.root / str(actual).lstrip('/')
        return actual

    def write(self, name, content):
        path = self.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def command(self, arguments, *, check=True):
        self.commands.append(list(arguments))
        if arguments[0] == self.failure:
            raise subprocess.CalledProcessError(1, arguments, stderr='fixture failure')
        if arguments[0] == 'ip':
            return SimpleNamespace(returncode=0, stdout='[{"prefsrc":"192.168.50.12"}]')
        if arguments[:3] == ['semanage', 'fcontext', '-a'] and self.existing_contexts:
            self.assertFalse(check)
            return SimpleNamespace(returncode=1, stdout='')
        return SimpleNamespace(returncode=0, stdout='')

    def start(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            firstboot.main()
        return output.getvalue()

    def test_boot_prepares_accounts_before_state_and_endpoint_uses_current_ip(self):
        message = self.start()
        self.assertEqual(self.commands[:2], [
            ['systemd-sysusers', '/usr/lib/sysusers.d/titan.conf'],
            ['systemd-tmpfiles', '--create', '/usr/lib/tmpfiles.d/titan.conf']])
        self.assertIn('https://192.168.50.12:5000', message)
        env = self.path('/etc/titan/web.env')
        self.assertEqual(env.read_text(), 'TITAN_ORIGIN=https://192.168.50.12:5000\n')
        caddy = self.path('/etc/titan/Caddyfile').read_text()
        self.assertIn('https://192.168.50.12:5000 {', caddy)
        self.assertIn('reverse_proxy 127.0.0.1:5001', caddy)
        self.assertEqual(env.stat().st_mode & 0o777, 0o644)
        self.assertFalse(list(self.root.rglob('.titan-*')))
        self.assertEqual(self.path('/etc/titan/release-public.pem').read_text(), 'PUBLIC KEY FIXTURE\n')
        self.assertFalse(any(command[0] in ('useradd', 'passwd', 'mkfs.ext4', 'mkfs.xfs', 'zpool') for command in self.commands))

    def test_repeated_boot_preserves_shares_and_adds_only_one_samba_include(self):
        shares = self.write('/etc/samba/titan-shares.conf', '[family]\npath = /var/srv/titan/shares/family\n')
        self.start(); self.start()
        text = self.path('/etc/samba/smb.conf').read_text()
        self.assertIn('workgroup = FAMILY', text)
        self.assertEqual(text.count('include = /etc/samba/titan-shares.conf'), 1)
        self.assertEqual(shares.read_text(), '[family]\npath = /var/srv/titan/shares/family\n')

    def test_selinux_module_is_installed_before_contexts_and_existing_rules_are_updated(self):
        self.existing_contexts = True
        self.start()
        module = self.commands.index(['semodule', '-i', '/usr/share/titan/titan-shares.pp',
                                      '/usr/share/titan/titan-proxy.pp'])
        adds = [index for index, command in enumerate(self.commands) if command[:3] == ['semanage', 'fcontext', '-a']]
        changes = [command for command in self.commands if command[:3] == ['semanage', 'fcontext', '-m']]
        self.assertTrue(all(index > module for index in adds))
        self.assertEqual([command[4] for command in changes], ['titan_share_t', 'virt_image_t', 'virt_image_t'])
        self.assertEqual(changes[0][-1], r'/var/srv/titan(/.*)?')
        self.assertEqual(changes[1][-1], r'/var/srv/titan/volumes/[^/]+/vms(/.*)?')
        labels = [command for command in self.commands if command[0] == 'restorecon']
        self.assertEqual(len(labels), 1)
        self.assertNotIn('-R', labels[0])
        self.assertNotIn('-r', labels[0])
        self.assertFalse(any(command[0] in ('setenforce', 'setsebool') for command in self.commands))

    def test_firstboot_stops_before_firewall_on_invalid_configuration(self):
        self.failure = 'runuser'
        with self.assertRaises(subprocess.CalledProcessError):
            self.start()
        self.assertFalse(any(command[0] == 'firewall-cmd' for command in self.commands))
        self.assertFalse(any(command[0] == 'semodule' for command in self.commands))

    def test_https_validation_uses_proxy_identity_and_writable_persistent_storage(self):
        self.start()
        validation = next(command for command in self.commands if command[0] == 'runuser')
        self.assertEqual(validation[:5], ['runuser', '-u', 'titan-proxy', '--', 'env'])
        self.assertIn('XDG_DATA_HOME=/var/lib/titan-proxy', validation)
        self.assertIn('XDG_CONFIG_HOME=/var/lib/titan-proxy', validation)
        self.assertIn('skip_install_trust', self.path('/etc/titan/Caddyfile').read_text())

    def test_failed_selinux_policy_prevents_ready_state_and_firewall_changes(self):
        self.failure = 'semodule'
        with self.assertRaises(subprocess.CalledProcessError):
            self.start()
        self.assertFalse(any(command[0] == 'semanage' for command in self.commands))
        self.assertFalse(any(command[0] == 'firewall-cmd' for command in self.commands))

    def test_invalid_image_or_nonroot_never_runs_privileged_commands(self):
        self.write('/usr/share/titan/image-info.json', '{"platform":"unsupported"}')
        with self.assertRaises(RuntimeError):
            self.start()
        self.assertEqual(self.commands, [])
        with patch.object(firstboot.os, 'geteuid', return_value=1000), self.assertRaises(RuntimeError):
            self.start()
        self.assertEqual(self.commands, [])

    def test_explicit_address_is_respected_without_route_query(self):
        self.write('/etc/titan/address', 'NAS.EXAMPLE\n')
        self.start()
        self.assertEqual(self.path('/etc/titan/web.env').read_text(), 'TITAN_ORIGIN=https://nas.example:5000\n')
        self.assertFalse(any(command[0] == 'ip' for command in self.commands))
        for service in ('titan', 'samba'):
            self.assertIn(['firewall-cmd', '--permanent', '--add-service=' + service], self.commands)
            self.assertIn(['firewall-cmd', '--add-service=' + service], self.commands)


if __name__ == '__main__':
    unittest.main()

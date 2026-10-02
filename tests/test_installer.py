"""Immutable first boot and removal of legacy host installation."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('firstboot',ROOT/'image/firstboot.py')
firstboot=importlib.util.module_from_spec(spec)
spec.loader.exec_module(firstboot)


class FirstBootTests(unittest.TestCase):
    def test_endpoint_is_port_5000_and_has_one_origin(self):
        env,caddy=firstboot.endpoint('192.0.2.31')
        self.assertEqual(env,'TITAN_ORIGIN=https://192.0.2.31:5000\n')
        self.assertIn('https://192.0.2.31:5000 {',caddy)
        self.assertIn('reverse_proxy 127.0.0.1:5001',caddy)
        self.assertIn('tls internal',caddy)

    def test_address_cannot_inject_caddy_or_environment(self):
        for value in ('$(reboot)','a\nTITAN_ORIGIN=http://evil','a:5000','a/b','127.0.0.1',
                      '0.0.0.0','999.999.0.1','a..b','-evil','evil-','a.'+'b'*64,'::1'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                firstboot.endpoint(value)

    def test_dns_names_supported(self):
        self.assertEqual(firstboot.address('NAS.example.lan'),'nas.example.lan')

    def test_legacy_download_installers_fail_without_mutations(self):
        for filename in ('install.sh','bootstrap.sh'):
            result=subprocess.run(['bash',str(ROOT/filename)],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,1)
            self.assertIn('Debian 13',result.stderr)
            self.assertIn('.img',result.stderr)

    def test_image_does_not_contain_instance_credentials(self):
        toml=(ROOT/'legacy/ucore/image/disk.toml').read_text()
        self.assertNotIn('password =',toml)
        self.assertNotIn('ssh_key',toml)
        script=(ROOT/'legacy/ucore/image/install-image.sh').read_text()
        self.assertIn('systemctl disable sshd.service',script)
        self.assertIn('rm -rf /var/*',script)
        self.assertIn('zincati.service bootc-fetch-apply-updates.timer',script)

    def test_firstboot_does_not_relabel_running_vm_disks(self):
        source=(ROOT/'image/firstboot.py').read_text()
        self.assertNotIn("'restorecon', '-R'",source)
        self.assertIn('virt_image_t',source)
        self.assertIn('titan_share_t',source)


class DockerImageConfigurationTests(unittest.TestCase):
    VENDOR_COMMAND = ['/usr/bin/dockerd', '-H', 'fd://',
                      '--containerd=/run/containerd/containerd.sock', '--selinux-enabled',
                      '--userland-proxy-path', '/usr/bin/docker-proxy',
                      '--init-path', '/usr/bin/tini-static']

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.unit = self.root / 'usr/lib/systemd/system/docker.service'
        self.unit.parent.mkdir(parents=True)
        self.unit.write_text('[Unit]\nDescription=Fixture Docker\n[Service]\nExecStart=' +
                             ' \\\n    '.join(self.VENDOR_COMMAND) + '\nType=notify\n')
        self.config = self.root / 'etc/docker/daemon.json'
        self.config.parent.mkdir(parents=True)
        source = (ROOT / 'legacy/ucore/image/install-image.sh').read_text()
        self.code = source.split("python3 - <<'PYDOCKER'\n", 1)[1].split('\nPYDOCKER', 1)[0]
        # Substitute only filesystem access; execute the real build-validation
        # logic against an isolated root and a fake dockerd process.
        self.code = self.code.replace('from pathlib import Path', '')

    def tearDown(self):
        self.temporary.cleanup()

    def execute(self):
        namespace = {'Path': lambda value: self.root / str(value).lstrip('/')}
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(self.code, str(ROOT / 'legacy/ucore/image/install-image.sh'), 'exec'), namespace)

    def test_duplicate_selinux_option_is_removed_and_effective_flags_are_validated_without_starting(self):
        self.config.write_text('{"selinux-enabled":true,"log-driver":"journald","live-restore":true}')
        with patch('subprocess.run') as runner:
            self.execute()
        self.assertEqual(json.loads(self.config.read_text()), {'log-driver': 'journald', 'live-restore': True})
        runner.assert_called_once()
        arguments = runner.call_args.args[0]
        self.assertEqual(arguments, [self.VENDOR_COMMAND[0], '--validate', *self.VENDOR_COMMAND[1:]])
        self.assertTrue(runner.call_args.kwargs['check'])
        self.assertTrue(runner.call_args.kwargs['capture_output'])
        self.assertEqual(runner.call_args.kwargs['timeout'], 30)

    def test_missing_daemon_json_is_not_created_and_vendor_selinux_remains_enabled(self):
        with patch('subprocess.run') as runner:
            self.execute()
        self.assertFalse(self.config.exists())
        self.assertIn('--selinux-enabled', runner.call_args.args[0])
        self.assertIn('--validate', runner.call_args.args[0])

    def test_changed_vendor_selinux_or_socket_flags_block_build_before_execution(self):
        original = self.unit.read_text()
        for old, new in (('--selinux-enabled', '--selinux-enabled=false'), ('fd://', 'tcp://0.0.0.0:2375')):
            self.unit.write_text(original.replace(old, new))
            with self.subTest(flag=old), patch('subprocess.run') as runner:
                with self.assertRaisesRegex(SystemExit, 'vendor flags changed'):
                    self.execute()
                runner.assert_not_called()

    def test_validation_failure_is_fatal_and_does_not_expose_configuration_details(self):
        failure = subprocess.CalledProcessError(1, ['dockerd'], stderr='proxy-password=private-fixture')
        with patch('subprocess.run', side_effect=failure):
            with self.assertRaises(SystemExit) as caught:
                self.execute()
        self.assertIn('configuration validation failed', str(caught.exception))
        self.assertNotIn('private-fixture', str(caught.exception))

    def test_nonobject_daemon_configuration_is_rejected_before_validation(self):
        self.config.write_text('[]')
        with patch('subprocess.run') as runner:
            with self.assertRaisesRegex(SystemExit, 'JSON object'):
                self.execute()
            runner.assert_not_called()

    def test_docker_startup_diagnostics_are_visible_on_the_console(self):
        source = (ROOT / 'legacy/ucore/image/install-image.sh').read_text()
        self.assertIn('if [[ "$task_service" == docker ]]', source)
        self.assertIn('StandardOutput=journal+console', source)
        self.assertIn('StandardError=journal+console', source)

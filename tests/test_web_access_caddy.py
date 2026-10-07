"""Provision generated Caddy configs with the real binary in isolated CI state."""
import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from titan.web_access import caddy_config, initial_config


_CADDY = os.environ.get('TITAN_TEST_CADDY') or shutil.which('caddy')


@unittest.skipUnless(_CADDY, 'Real Caddy validation runs in the disposable cloudflared-web CI job.')
class CaddyConfigurationTests(unittest.TestCase):
    def test_actual_adapter_and_tls_provisioning_for_protocol_ports_and_pending_endpoints(self):
        cases = []
        for host in ('192.168.10.18', 'fd00::18', 'titan.local'):
            base = initial_config(host)
            cases.append(base)
            custom = copy.deepcopy(base)
            custom['settings'].update(http_port=8080, https_port=8443)
            cases.append(custom)
            custom['pending'] = {'previous': copy.deepcopy(base), 'deadline': 1234}
            cases.append(custom)
            http = copy.deepcopy(base)
            http['settings'].update(mode='http', http_port=8080)
            cases.append(http)
            http['pending'] = {'previous': copy.deepcopy(base), 'deadline': 1234}
            cases.append(http)
            upgrade = copy.deepcopy(base)
            upgrade['settings'].update(http_port=8081, https_port=8443)
            upgrade['pending'] = {'previous': copy.deepcopy(http), 'deadline': 1234}
            cases.append(upgrade)
            from test_remote_access import remote_settings
            for bridge in (False, True):
                remote = copy.deepcopy(base)
                remote['remote'] = remote_settings(bridge=bridge)
                cases.append(remote)
        with tempfile.TemporaryDirectory(prefix='titan-caddy-validation-') as folder:
            root = Path(folder)
            environment = {**os.environ, 'XDG_DATA_HOME': str(root / 'data'), 'XDG_CONFIG_HOME': str(root / 'config')}
            for number, config in enumerate(cases):
                with self.subTest(case=number, host=config['host'], mode=config['settings']['mode']):
                    source = root / f'Caddyfile-{number}'
                    source.write_text(caddy_config(config))
                    result = subprocess.run([_CADDY, 'validate', '--config', str(source), '--adapter', 'caddyfile'],
                                            capture_output=True, text=True, env=environment, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stderr[-4000:])
            self.assertFalse((root / 'data/caddy/pki/authorities/local/root.crt').is_symlink())


if __name__ == '__main__':
    unittest.main()

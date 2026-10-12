#!/usr/bin/env python3
"""Real native binary/systemd credential check, only on disposable hosted CI."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'
        or os.environ.get('TITAN_DISPOSABLE_CI') != '1' or os.geteuid() != 0):
    raise SystemExit('Requires an explicitly disposable GitHub-hosted root runner.')

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from titan import system_plugins as plugins
from titan.core import Error
from tests.test_system_plugins import Host, credential

if plugins.ROOT.exists() or plugins.UNIT_PATH.exists():
    raise SystemExit('Refusing to replace an existing native plugin.')


class RuntimeHost(Host):
    def command(self, args, **kwargs):
        result = subprocess.run(args, text=True, capture_output=True, timeout=kwargs.get('timeout', 30))
        if result.returncode: raise Error('Disposable systemd operation failed.')
        return result.stdout


with tempfile.TemporaryDirectory(prefix='titan-native-plugin-') as directory:
    root = Path(directory); root.chmod(0o755)
    agent = root / 'agent'; agent.mkdir(mode=0o700)
    host = RuntimeHost(agent)
    # Stand in for the already-mounted, traversable TITAN-DATA root on a NAS.
    plugins.ROOT.parents[1].mkdir(mode=0o755, exist_ok=True)
    old_mask = os.umask(0o027)
    try:
        plugins.prepare_plugin_root()
        binary = plugins.ROOT / 'cloudflared'
        plugins.download(plugins.offer(), binary)
        version = subprocess.check_output([str(binary), '--version'], text=True, timeout=10).strip()
        assert plugins.VERSION in version
        cached_binary = root / 'checked-cloudflared'
        shutil.copy2(binary, cached_binary)
        secret = credential()
        token_path = agent / 'cloudflare-plugin-token'
        plugins.write_private(token_path, secret.encode())
        plugins.write_private(plugins.UNIT_PATH, plugins.service_unit(token_path).encode(), 0o644)
        host.command(['systemctl', 'daemon-reload'])
        started = time.time()
        host.command(['systemctl', 'start', plugins.UNIT])
        # A syntactically valid, intentionally invalid upstream credential must
        # launch cloudflared without granting a real tunnel or public route.
        deadline = time.monotonic() + 20
        journal = ''
        while time.monotonic() < deadline:
            journal = host.command(['journalctl', '-u', plugins.UNIT, '--since', '@' + str(int(started)), '--no-pager', '-o', 'cat'])
            if 'Starting tunnel' in journal: break
            time.sleep(1)
        assert 'Starting tunnel' in journal, 'Native binary failed to launch under DynamicUser.'
        assert secret not in journal, 'Credential appeared in service journal.'
        assert not plugins.connected(), 'Disposable invalid token must not establish a tunnel.'
        host.save('system-plugins', {'cloudflare': {'installed': True, 'version': plugins.VERSION,
            'sha256': plugins.DIGESTS[plugins.architecture()], 'public_origin': 'https://invalid.example.org'}})
        result = host.op_plugin_action('cloudflare', 'remove', host._plugin_revision(), confirmation='cloudflare')
        assert result['ok'] and not token_path.exists() and not binary.exists() and not plugins.UNIT_PATH.exists()

        # Exercise the production installation transaction, not just the unit
        # generator. Reuse the binary already authenticated by download(). The
        # intentionally invalid credential cannot create a public tunnel; only
        # this disposable negative test uses a shorter readiness deadline.
        def cached_download(candidate, target):
            assert candidate == plugins.offer()
            shutil.copy2(cached_binary, target)
        with patch.object(plugins, 'download', side_effect=cached_download), patch.object(plugins, 'CONNECT_TIMEOUT', 5):
            try:
                host.op_plugin_action('cloudflare', 'install', host._plugin_revision(),
                    {'token': secret, 'public_origin': 'https://invalid.example.org'})
            except Error as error:
                failure = str(error)
                assert any(code in failure for code in ('CF_CONNECT_TIMEOUT', 'CF_TUNNEL_AUTH', 'CF_EDGE_DNS', 'CF_EDGE_TCP', 'CF_EDGE_QUIC')), failure
                assert 'Bisheriger Stand wurde wiederhergestellt' in failure
                assert secret not in failure
            else:
                raise AssertionError('Invalid credential unexpectedly installed a connected tunnel.')
        assert not host._cloudflare_installed()
        assert not host._plugin_service_state('is-active')
        assert not token_path.exists() and not binary.exists() and not plugins.UNIT_PATH.exists()
        print(json.dumps({'ok': True, 'version': version, 'native_systemd': True, 'credential_private': True,
                          'invalid_token_connected': False, 'uninstall': True, 'install_failure_rollback': True}))
    finally:
        os.umask(old_mask)
        if plugins.UNIT_PATH.exists():
            subprocess.run(['systemctl', 'disable', '--now', plugins.UNIT], check=False, capture_output=True)
            plugins.UNIT_PATH.unlink()
            subprocess.run(['systemctl', 'daemon-reload'], check=False, capture_output=True)
        for name in ('cloudflared', 'cloudflared.previous'):
            (plugins.ROOT / name).unlink(missing_ok=True)
        if plugins.ROOT.exists(): plugins.ROOT.rmdir()

#!/usr/bin/env python3
"""Real userspace recipe acceptance with an intentionally invalid auth-key.

Restricted to a disposable GitHub runner. No live account is needed, and this
gate explicitly does not claim a connected tailnet or approved subnet route.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import secrets
import stat
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from titan.core import Error
from titan.host import Host
from titan.native_apps import tailscale_runtime

APP = 'titan-tailscale'


def require(condition, message):
    if not condition:
        raise Error(message)


def command(argv, timeout=120):
    result = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
    require(result.returncode == 0, 'Disposable Tailscale command failed: ' + argv[0])
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-disposable-runner', action='store_true')
    args = parser.parse_args()
    if not args.confirm_disposable_runner or os.environ.get('GITHUB_ACTIONS') != 'true' or os.geteuid() != 0:
        parser.error('Requires root on an explicitly confirmed disposable GitHub runner.')
    require(not command(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=titan-' + APP]).strip(),
            'A pre-existing Tailscale project must never be replaced.')
    try:
        pwd.getpwnam('titan-files')
    except KeyError:
        command(['useradd', '--system', '--no-create-home', '--home-dir', '/nonexistent', '--shell', '/usr/sbin/nologin', 'titan-files'])
    os.umask(0o027)
    credential = 'tskey-auth-invalid-ci-' + secrets.token_hex(24)
    with tempfile.TemporaryDirectory(prefix='titan-tailscale-smoke-') as directory:
        base = Path(directory)
        host = Host(base / 'agent', base / 'shares', base / 'vms', base / 'samba.conf')
        host.directory.chmod(0o700)
        host.share_root.mkdir(mode=0o755)
        forwarding = {path: path.read_text() for path in (Path('/proc/sys/net/ipv4/ip_forward'), Path('/proc/sys/net/ipv6/conf/all/forwarding')) if path.exists()}
        resolv = Path('/etc/resolv.conf').read_bytes()
        try:
            initial = host.dispatch('app_install_status', app=APP)
            try:
                host.dispatch('app_install_run', app=APP, options={'auth_key': credential,
                    'hostname': 'titan-disposable-test', 'subnet_routing': 'enabled', 'subnet_routes': '192.168.240.0/24'},
                    expected_revision=initial['revision'])
            except Error as error:
                require(credential not in str(error), 'Installation error exposed the private auth-key.')
            else:
                raise Error('Invalid Tailscale auth-key must never complete installation.')
            status = host.dispatch('app_install_status', app=APP)
            require(status['status'] == 'failed' and status['resumable'] and not status['runtime']['ready'] and not status['runtime'].get('connected'),
                    'Invalid auth-key falsely reported a ready or connected app.')
            require(status['runtime']['routes_approval'] == 'not_verified', 'External route approval was falsely claimed.')
            steps = {row['id']: row for row in status['steps']}
            require(all(steps[key]['status'] == 'completed' for key in ('docker', 'files', 'pull', 'create')),
                    'The pinned official Tailscale image did not reach actual create/start acceptance.')
            require(steps['start']['status'] == 'failed' or steps['health']['status'] == 'failed',
                    'Failed authentication did not fail the startup/health gate.')
            require(credential not in json.dumps(status) and credential not in host._installation_path(APP).read_text(),
                    'Public status or journal exposed the auth-key.')
            require(stat.S_IMODE(host._installation_path(APP, private=True).stat().st_mode) == 0o600,
                    'Private retry inputs are readable by another account.')
            try:
                host.dispatch('app_install_resume', app=APP, expected_revision=status['revision'])
            except Error:
                pass
            else:
                raise Error('Retry must not turn an invalid credential into a successful installation.')
            repeated = host.dispatch('app_install_status', app=APP)
            require(repeated['status'] == 'failed' and repeated['resumable'] and not repeated['runtime']['ready'] and not repeated['runtime'].get('connected'),
                    'Retry did not retain a truthful failed authentication state.')
            record = host.managed_app(APP)
            container = host._app_container(APP, record)
            require(container is not None and not tailscale_runtime(container)['connected'], 'Invalid credential unexpectedly connected.')
            inspected_raw = command(['docker', 'inspect', '--type', 'container', container['Id']])
            require(credential not in inspected_raw, 'Docker command/environment exposed the auth-key.')
            inspected = json.loads(inspected_raw)[0]
            config = inspected['HostConfig']
            require(config['NetworkMode'] != 'host' and not config.get('Privileged') and not config.get('CapAdd') and not config.get('Devices'),
                    'Userspace recipe unexpectedly requested host privileges/network/TUN.')
            require(not config.get('PortBindings'), 'Tailscale unnecessarily published a host port.')
            require('TS_USERSPACE=true' in inspected['Config']['Env'] and 'TS_AUTHKEY=file:/etc/titan-tailscale/authkey' in inspected['Config']['Env'],
                    'Official image did not retain the userspace/private auth-file configuration.')
            logs = host._app_logs(container, 250)
            lower = logs.lower()
            require('invalid key' in lower or 'invalid auth' in lower or 'authkey' in lower and 'does not exist' in lower,
                    'Official image did not explicitly reject the intentionally invalid auth-key. Network/configuration failures are not an auth acceptance result.')
            require(credential not in logs, 'Official image unexpectedly echoed the private auth-key.')
            require(not any('/etc/titan-tailscale/authkey' in line and ('permission denied' in line.lower() or 'no such file' in line.lower()) for line in logs.splitlines()),
                    'Official image could not read the protected auth-key file.')
            private = Path(record['config_path']) / 'credentials' / 'authkey'
            require(private.read_text() == credential and stat.S_IMODE(private.stat().st_mode) == 0o600 and stat.S_IMODE(private.parent.stat().st_mode) == 0o700,
                    'Auth-key file contents or permissions are wrong.')
            require(all(path.read_text() == value for path, value in forwarding.items()) and Path('/etc/resolv.conf').read_bytes() == resolv,
                    'Userspace app changed host forwarding or DNS settings.')
            host.dispatch('app_action', app=APP, action='stop')
            host.dispatch('app_action', app=APP, action='remove')
            require(private.read_text() == credential, 'Removing the app destroyed retained private configuration.')
            require(not any(row['id'] == APP for row in host.load('apps', [])), 'Removal left the app registered.')
            print(json.dumps({'ok': True, 'official_image_and_compose_verified': True, 'private_auth_file': True,
                'invalid_auth_never_ready': True, 'userspace_without_host_privileges': True,
                'private_input_retry_verified': True,
                'host_forwarding_dns_retained': True, 'external_tailnet_tested': False, 'subnet_route_approval_verified': False,
                'reason': 'An intentionally invalid disposable auth-key is used; no live Tailscale account.'}))
        finally:
            if any(row['id'] == APP for row in host.load('apps', [])):
                host.dispatch('app_action', app=APP, action='remove')


if __name__ == '__main__':
    try:
        main()
    except Error as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None

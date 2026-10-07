#!/usr/bin/env python3
"""Real dedicated-runner acceptance with an intentionally invalid credential.

Only a disposable GitHub runner may run this root/Docker test. It proves that
the pinned official image reads the private token file and that authentication
failure preserves LAN access. It does not claim a working external tunnel.
"""
import argparse
import base64
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import pwd
import secrets
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from titan.cloudflare_tunnel import CONNECTOR, METRICS_PORT, connector_ready
from titan.core import Error
from titan.host import Host
from titan.server import Application, Handler


def require(condition, message):
    if not condition:
        raise Error(message)


def command(argv, timeout=120):
    # No command contains a credential. Still keep upstream output out of the
    # CI failure path; the assertions below identify the precise failed gate.
    result = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
    require(result.returncode == 0, 'Disposable Docker command failed: ' + argv[0])
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-disposable-runner', action='store_true')
    args = parser.parse_args()
    if not args.confirm_disposable_runner or os.environ.get('GITHUB_ACTIONS') != 'true' or os.geteuid() != 0:
        parser.error('Requires root on an explicitly confirmed disposable GitHub runner.')
    name = 'titan-' + CONNECTOR
    require(not command(['docker', 'ps', '-aq', '--filter', 'name=^/' + name + '$']).strip(),
            'A pre-existing connector must never be replaced by acceptance checks.')
    try:
        pwd.getpwnam('titan-files')
    except KeyError:
        command(['useradd', '--system', '--no-create-home', '--home-dir', '/nonexistent',
                 '--shell', '/usr/sbin/nologin', 'titan-files'])
    os.umask(0o027)
    credential = base64.b64encode(json.dumps({'a': secrets.token_hex(16), 't': str(uuid.uuid4()),
        's': base64.b64encode(secrets.token_bytes(32)).decode()}).encode()).decode()
    with tempfile.TemporaryDirectory(prefix='titan-cloudflare-token-smoke-') as directory:
        base = Path(directory)
        host = Host(base / 'agent', base / 'shares', base / 'vms', base / 'samba.conf')
        host.directory.chmod(0o700)
        host.share_root.mkdir(mode=0o755)
        host.web_access._write_runtime(host.web_access.config())
        local_files = {path: path.read_bytes() for path in (host.web_access.path,
            host.web_access.directory / 'Caddyfile', host.web_access.directory / 'web.env')}
        web = Application(base / 'web')
        class LocalAgent:
            def call(self, operation, **arguments):
                return host.dispatch(operation, **arguments)
        web.agent = LocalAgent()
        password = secrets.token_urlsafe(32)
        web.store.create_user('smokeadmin', password, 'admin', 'titan-files')
        session, csrf = web.store.login('smokeadmin', password)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.app, server.daemon_threads = web, True
        origin = 'http://127.0.0.1:' + str(server.server_port)
        web.origin = origin
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        thread.start()
        observed = set()

        def request(path, body=None):
            client = HTTPConnection('127.0.0.1', server.server_port, timeout=15)
            try:
                client.request('GET' if body is None else 'POST', path,
                    json.dumps(body) if body is not None else None,
                    headers={'Host': '127.0.0.1:' + str(server.server_port), 'Origin': origin,
                        'Cookie': 'titan_session=' + session, 'X-CSRF-Token': csrf, 'Content-Type': 'application/json'})
                response = client.getresponse()
                payload = response.read()
                require(credential.encode() not in payload, 'HTTP response exposed the tunnel credential.')
                require(response.status in (200, 202), 'Production HTTP acceptance route failed: ' + path)
                return json.loads(payload)
            finally:
                client.close()

        def wait_job(identifier, expect_failure=False):
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                job = next(row for row in request('/api/jobs') if row['id'] == identifier)
                state = request('/api/remote-access').get('setup', {})
                if state.get('phase'):
                    observed.add(state['phase'])
                if job['status'] not in ('queued', 'running'):
                    require(job['status'] == ('failed' if expect_failure else 'completed'),
                            'Unexpected production job result for disposable token lifecycle.')
                    return job
                time.sleep(.5)
            raise Error('Disposable token lifecycle exceeded its deadline.')

        def action(value):
            return wait_job(request('/api/actions', {'operation': 'app_action',
                'arguments': {'app': CONNECTOR, 'action': value}})['job'])

        try:
            queued = request('/api/remote-access/tunnel', {'token': credential,
                'public_origin': 'https://titan-cloudflare-smoke.invalid',
                'expected_revision': host.web_access.config()['revision']})
            require(set(queued) == {'job'}, 'Tunnel setup did not return the standard job contract.')
            failed = wait_job(queued['job'], expect_failure=True)
            require(credential not in json.dumps(failed), 'Job exposed the tunnel credential.')
            for path, content in local_files.items():
                require(path.read_bytes() == content, 'Failed token authentication changed the LAN/proxy configuration.')
            require(request('/api/remote-access')['setup']['phase'] == 'failed',
                    'The invalid dummy credential did not finish with a failed setup state.')
            record = host.managed_app(CONNECTOR)
            container = host._app_container(CONNECTOR, record)
            require(container is not None and not container['State']['Running'], 'Failed fresh connector was not safely stopped.')
            require(not connector_ready(container), 'Invalid dummy credential falsely reported a connected tunnel.')
            raw = command(['docker', 'inspect', '--type', 'container', container['Id']])
            require(credential not in raw, 'Docker inspect exposed the token in command or environment.')
            inspected = json.loads(raw)[0]
            require(inspected['Config']['User'] == '0:0', 'Private token file cannot be read by the configured image user.')
            require(inspected['HostConfig']['NetworkMode'] == 'host', 'Direct runner did not use the intended Host network.')
            require(inspected['HostConfig']['ReadonlyRootfs'], 'Direct runner root filesystem is writable.')
            require('ALL' in inspected['HostConfig']['CapDrop'], 'Direct runner retains Linux capabilities.')
            require(not inspected['HostConfig'].get('PortBindings'), 'Direct runner unnecessarily publishes a LAN port.')
            require(not any(value.startswith('TUNNEL_TOKEN=') for value in inspected['Config'].get('Env', [])),
                    'Token appeared in container environment.')
            require('--token-file' in inspected['Config']['Cmd'], 'Official runner did not use the token-file argument.')
            private = host._app_config_path(CONNECTOR, record) / 'credentials' / 'token'
            require(private.read_text() == credential and stat.S_IMODE(private.stat().st_mode) == 0o600,
                    'Protected token file contents or permissions are wrong.')
            require(stat.S_IMODE(private.parent.stat().st_mode) == 0o700 and private.stat().st_uid == 0,
                    'Token file is not restricted to the root agent.')
            logs = host._app_logs(container, 500)
            require('starting tunnel' in logs.lower(), 'Pinned official image did not successfully read/parse its token file.')
            require(not any('permission denied' in line.lower() and '/etc/cloudflared/token' in line for line in logs.splitlines()),
                    'Official runner cannot read its private credential mount.')
            require(credential not in logs, 'Official runner unexpectedly echoed the token.')
            # Normal lifecycle remains usable after the guarded setup failure.
            action('start')
            running = host._app_container(CONNECTOR, host.managed_app(CONNECTOR))
            require(running and running['State']['Running'], 'Production app start did not recreate the runner correctly.')
            require(not connector_ready(running), 'Dummy credential became ready after normal app restart.')
            action('stop')
            require(private.read_text() == credential, 'Stopping the runner changed its saved credential.')
            for path in ('/api/apps', '/api/app-details?app=' + CONNECTOR,
                         '/api/package-details?app=' + CONNECTOR,
                         '/api/package-logs?app=' + CONNECTOR + '&service=' + CONNECTOR):
                request(path)
            require(credential.encode() not in web.store.path.read_bytes(), 'Job/audit database contains the tunnel credential.')
            action('remove')
            require(not any(row['id'] == CONNECTOR for row in host.load('apps', [])), 'App removal retained a registered runner.')
            require(not command(['docker', 'ps', '-aq', '--filter', 'name=^/' + name + '$']).strip(),
                    'Production removal left a connector container.')
            require(private.read_text() == credential, 'App removal destroyed retained private configuration.')
            print(json.dumps({'ok': True, 'official_image_token_file_read': True,
                'host_network': True, 'root_0600_token_file': True, 'no_secret_api_argv_env_database': True,
                'invalid_token_never_ready': True, 'failed_setup_lan_preserved': True,
                'normal_start_stop_remove': True, 'external_tunnel_tested': False,
                'reason': 'No live Cloudflare account token is used.', 'observed_phases': sorted(observed)}))
        finally:
            try:
                if any(row['id'] == CONNECTOR for row in host.load('apps', [])):
                    host.dispatch('app_action', app=CONNECTOR, action='remove')
            finally:
                web.stop.set()
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == '__main__':
    try:
        main()
    except Error as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None

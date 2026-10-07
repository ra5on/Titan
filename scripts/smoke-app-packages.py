#!/usr/bin/env python3
"""Real Docker acceptance checks, exclusively on a disposable CI runner."""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import pwd
from http.server import ThreadingHTTPServer
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from titan.app_packages import PACKAGES, prepare_options
from titan.catalog import validate_options
from titan.host import Host
from titan.server import Application, Handler
from titan.core import Error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('package', choices=[*PACKAGES, 'bigbear:adguard-home', 'bigbear:nextcloud', 'bigbear:immich', 'bigbear:cloudflared-web'])
    parser.add_argument('--confirm-disposable-runner', action='store_true')
    args = parser.parse_args()
    if not args.confirm_disposable_runner or os.environ.get('GITHUB_ACTIONS') != 'true':
        parser.error('This test is restricted to an explicitly confirmed disposable GitHub runner.')
    if args.package.startswith('bigbear:'):
        from titan.app_stores import StoreMixin
        from titan.store_sources import BIGBEAR
        from titan.store_recipes import recipes
        from titan.catalog import APPS
        document, _ = StoreMixin.store_document(BIGBEAR)
        _, imported = recipes(document, BIGBEAR)
        suffix = args.package.split(':', 1)[1]
        app, recipe = next((key, value) for key, value in imported.items() if key.endswith('-' + suffix))
        APPS[app] = recipe
    else:
        app, recipe = args.package, PACKAGES[args.package]
    user_options = {f['key']: 'Test-' + os.urandom(16).hex() for f in recipe['install_schema'] if f['type'] == 'password' and not f.get('generated')}
    if app == 'titan-nextcloud-office':
        user_options['office_mode'] = 'enabled'  # exercise the complete optional Office stack
    options = validate_options(app, prepare_options(app, user_options))
    cloudflared_web = args.package == 'bigbear:cloudflared-web'
    app_port = recipe['port'] if recipe.get('default_network') == 'host' else 18080
    for key in options:
        if key.startswith('stack_port_') and '_53_' in key: options[key] = 15053
    if 'nas_host' in options: options['nas_host'] = '127.0.0.1'
    if 'stack_nas_host' in options: options['stack_nas_host'] = 'nas.test'
    secrets = [str(options[f['key']]) for f in recipe['install_schema'] if f['type'] == 'password' and f['key'] in options]
    def run(command, input=None, timeout=600):
        result = subprocess.run(command, input=input, text=True, capture_output=True, timeout=timeout)
        if result.returncode:
            message = (result.stderr or result.stdout)[-3000:]
            for value in secrets: message = message.replace(value, '[redacted]')
            print('Package command failed: ' + message, file=sys.stderr)
            raise Error(message)
        return result.stdout
    with tempfile.TemporaryDirectory(prefix='titan-package-smoke-') as directory:
        base = Path(directory)
        base.chmod(0o755)
        if os.geteuid() != 0:
            raise Error('The disposable Host/HTTP lifecycle check requires root.')
        # Match the installed management agent's directory permissions.
        os.umask(0o027)
        # File workers use the immutable production code location. Install only
        # the package link on this explicitly disposable runner, never repo
        # metadata, signing files, or another checkout.
        code_root = Path('/usr/lib/titan')
        if code_root.exists():
            raise Error('Disposable runtime code location is unexpectedly occupied.')
        code_root.mkdir(mode=0o755)
        (code_root / 'titan').symlink_to(Path(__file__).resolve().parents[1] / 'titan', target_is_directory=True)
        try:
            pwd.getpwnam('titan-files')
        except KeyError:
            run(['useradd', '--system', '--no-create-home', '--home-dir', '/nonexistent', '--shell', '/usr/sbin/nologin', 'titan-files'])
        host = Host(base / 'agent', base / 'shares', base / 'vms', base / 'samba.conf')
        host.directory.chmod(0o700)
        host.share_root.mkdir(mode=0o755)
        files = host.share_root / 'smoke-files'
        files.mkdir(mode=0o755)
        (files / 'available-during-install.txt').write_text('file-manager-remains-responsive')
        host.save('shares', [{'name': 'smoke-files', 'path': str(files), 'readers': ['titan-files'], 'writers': ['titan-files']}])
        web = Application(base / 'web')
        class LocalAgent:
            def call(self, operation, **arguments):
                return host.dispatch(operation, **arguments)
        web.agent = LocalAgent()
        web.users.agent = web.agent
        web.identity.agent = web.agent
        web_password = 'Test-' + os.urandom(24).hex()
        web.store.setup('smokeadmin', web_password)
        token, csrf = web.store.login('smokeadmin', web_password)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.app, server.daemon_threads = web, True
        server_thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        server_thread.start()
        origin = 'http://127.0.0.1:' + str(server.server_port)
        def request(path, body=None, timeout=15):
            headers = {'Cookie': 'titan_session=' + token, 'X-CSRF-Token': csrf, 'Content-Type': 'application/json'}
            value = urllib.request.Request(origin + path, headers=headers, data=json.dumps(body).encode() if body is not None else None)
            try:
                with urllib.request.urlopen(value, timeout=timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as response:
                message = str(json.load(response).get('error', 'HTTP lifecycle failed'))
                for secret in secrets: message = message.replace(secret, '[redacted]')
                raise Error(message) from None
        def submit(operation, arguments):
            return request('/api/actions', {'operation': operation, 'arguments': arguments})['job']
        def wait_job(job, timeout=900):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                value = next(row for row in request('/api/jobs') if row['id'] == job)
                if value['status'] in ('completed', 'failed'):
                    if value['status'] == 'failed':
                        message = str(value['result'].get('error', 'Host lifecycle failed'))
                        for secret in secrets: message = message.replace(secret, '[redacted]')
                        raise Error(message)
                    return value['result']
                time.sleep(.2)
            raise Error('Disposable lifecycle job exceeded its deadline.')
        def action(operation, **arguments):
            return wait_job(submit(operation, arguments))
        def ready():
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                result = request('/api/package-details?app=' + app)
                if result['ready'] and result['primary_available']:
                    return result
                time.sleep(1)
            raise Error('Package Host health validation did not become ready.')
        config = host.directory / 'apps' / app / 'compose.json'
        command = ['docker', 'compose', '--project-name', 'titan-' + app, '-f', str(config)]
        try:
            installed_job = submit('app_install', {'app': app, 'port': app_port, 'options': options})
            # The HTTP file request runs while the production Host is pulling,
            # initializing databases and waiting for health, not after it ends.
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                installing = next(row for row in request('/api/jobs') if row['id'] == installed_job)
                if installing['status'] == 'running': break
                if installing['status'] == 'failed': wait_job(installed_job)
                time.sleep(.05)
            if installing['status'] != 'running':
                raise Error('No running install observed for the concurrent file test.')
            before_list = time.monotonic()
            listing = request('/api/files?share=smoke-files', timeout=5)
            if 'available-during-install.txt' not in {entry['name'] for entry in listing['entries']}:
                raise Error('File manager could not browse during package installation.')
            list_seconds = time.monotonic() - before_list
            wait_job(installed_job)
            definition = json.loads(config.read_text())
            ready()
            installed = next(row for row in host.load('apps', []) if row['id'] == app)
            actual_options = host._app_options(app)
            # Generated secrets on the real install are retained across retries;
            # use these exact private values for the separate Office roundtrip.
            options = actual_options
            secrets.extend(str(options[f['key']]) for f in recipe['install_schema'] if f['type'] == 'password' and f['key'] in options)
            endpoint = '/api/server/ping' if app == 'titan-immich' else '/admin/' if app == 'titan-pihole' else '/status.php' if app == 'titan-nextcloud-office' else '/'
            bigbear_nextcloud = args.package == 'bigbear:nextcloud'
            if bigbear_nextcloud: endpoint = '/index.php/login'
            app_request = urllib.request.Request('http://127.0.0.1:' + str(app_port) + endpoint,
                headers={'Host': 'nas.test:18080'} if bigbear_nextcloud else {})
            for attempt in range(45):
                try:
                    with urllib.request.urlopen(app_request, timeout=5) as response:
                        if response.status != 200: raise Error('App HTTP readiness failed')
                        if bigbear_nextcloud and b'nextcloud' not in response.read(1024 * 1024).lower():
                            raise Error('Nextcloud login page is unavailable under the configured NAS hostname.')
                    break
                except urllib.error.HTTPError as response:
                    if cloudflared_web and response.code == 401:
                        break  # Credentials configured; unauthenticated access denied.
                    if attempt == 44: raise Error('App HTTP readiness failed') from None
                    time.sleep(2)
                except (OSError, Error):
                    if attempt == 44: raise Error('App HTTP readiness failed') from None
                    time.sleep(2)
            if bigbear_nextcloud:
                denied = urllib.request.Request('http://127.0.0.1:18080/index.php/login',
                    headers={'Host': 'untrusted.invalid:18080'})
                try:
                    urllib.request.urlopen(denied, timeout=5).close()
                except urllib.error.HTTPError as error:
                    if error.code != 400: raise Error('Unexpected untrusted-host response.') from None
                else:
                    raise Error('Nextcloud must reject an unconfigured hostname.')
            if cloudflared_web:
                environment = recipe['stack']['services'][recipe['stack']['primary']].get('environment', {})
                def private_value(key):
                    value = environment.get(key, '')
                    return str(actual_options[value[8:]]) if isinstance(value, str) and value.startswith('@option:') else str(value)
                username, password = private_value('BASIC_AUTH_USER'), private_value('BASIC_AUTH_PASS')
                if not username or len(password) < 12:
                    raise Error('Cloudflared Web credentials were not securely configured.')
                class NoRedirect(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self, request, response, code, message, headers, location):
                        return None
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
                credentials = base64.b64encode((username + ':' + password).encode()).decode()
                authenticated = urllib.request.Request('http://127.0.0.1:' + str(app_port) + '/', headers={'Authorization': 'Basic ' + credentials})
                with opener.open(authenticated, timeout=5) as response:
                    if response.status != 200:
                        raise Error('Configured Cloudflared Web credentials cannot open the application.')
            lan_url = 'http://10.254.254.1:' + str(app_port)
            def check_cloudflared_lan(expected=401):
                if not cloudflared_web:
                    return
                response = run(['ip', 'netns', 'exec', 'titan-ci-client', 'curl', '--noproxy', '*',
                    '--connect-timeout', '2', '--max-time', '5', '-s', '-o', '/dev/null', '-w', '%{http_code}', lan_url], timeout=10).strip()
                if response != str(expected):
                    raise Error('Cloudflared Web must be reachable with authentication from the isolated LAN client.')
                state = request('/api/apps')['installed'][0]
                if not state.get('web_available') or state.get('web_state') != 'ready':
                    raise Error('App API did not report verified HTTP readiness.')
                rules = host.load('managed-firewall-v1', {})
                if not any('10.254.254.0/30' in row['rule'] and 'app:' + app in row['owners'] for row in rules.values()):
                    raise Error('No scoped LAN firewall rule was managed for Cloudflared Web.')
            check_cloudflared_lan()
            # A restart must preserve initialized databases and account settings.
            office_gateway = None
            if app == 'titan-nextcloud-office':
                spec = importlib.util.spec_from_file_location('titan_smoke_office_gateway', Path(__file__).with_name('smoke-office-gateway.py'))
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                office_gateway = module.run_office_gateway_smoke(base, options, run)
            dependency = next((item for item in host._app_lifecycle_snapshot(app) if item['Config']['Labels']['com.docker.compose.service'].endswith('-redis')), None)
            single = dependency or host._app_lifecycle_snapshot(app)[0]
            stopped = action('docker_container_action', container=single['Id'], action='stop')
            if stopped['scope'] != 'container' or host.engine_active(host.engine_container(single['Id'])):
                raise Error('Selected container did not stop through the real API.')
            if dependency:
                main = host._app_container(app, host.managed_app(app))
                if not main or main['State']['Status'] != 'running':
                    raise Error('Stopping a dependency silently stopped the entire app.')
            action('docker_container_action', container=single['Id'], action='start')
            ready()
            action('app_action', app=app, action='stop')
            if any(host._app_container_active(item) for item in host._app_lifecycle_snapshot(app)):
                raise Error('Package still has running services after HTTP stop.')
            if cloudflared_web:
                state = next(row for row in request('/api/apps')['installed'] if row['id'] == app)
                if state.get('web_available') or state.get('web_state') != 'stopped':
                    raise Error('Stopped Cloudflared Web still has a launchable status.')
                if any('app:' + app in row['owners'] for row in host.load('managed-firewall-v1', {}).values()):
                    raise Error('Stopped Cloudflared Web retained a managed firewall rule.')
            action('app_action', app=app, action='start')
            ready()
            check_cloudflared_lan()
            action('app_action', app=app, action='restart')
            ready()
            check_cloudflared_lan()
            keep = Path(installed['data']) / 'titan-smoke-retained.txt'
            keep.write_text('persistent-user-data')
            private = host.directory / 'apps' / app / 'options.json'
            private_before = private.read_bytes()
            removed = action('app_action', app=app, action='remove')
            if not removed.get('data_retained') or removed.get('state') != 'removed':
                raise Error('Unexpected package removal result.')
            if keep.read_text() != 'persistent-user-data' or private.read_bytes() != private_before:
                raise Error('Uninstall removed data or changed private configuration.')
            if any(row.get('managed_app') == app for row in request('/api/docker-engine')['containers']):
                raise Error('Managed containers remain after uninstall.')
            if any(row['id'] == app for row in host.load('apps', [])):
                raise Error('Uninstall left the application registered.')
            if cloudflared_web and any('app:' + app in row['owners'] for row in host.load('managed-firewall-v1', {}).values()):
                raise Error('Uninstall retained app firewall access.')
            print(json.dumps({'package': app, 'containers': len(definition['services']), 'ready': True,
                'restart': True, 'host_http_lifecycle': True, 'single_container_stop': True,
                'package_stop_start': True, 'uninstall_data_retained': True,
                **({'isolated_lan_firewall_access': True, 'basic_auth_required': True, 'readiness_verified': True} if cloudflared_web else {}),
                'file_browse_during_install': True, 'file_browse_seconds': round(list_seconds, 3),
                **({'office_gateway': office_gateway} if office_gateway else {})}))
        except Exception:
            if app == 'titan-nextcloud-office':
                log = host.share_root / 'apps' / app / 'nextcloud.log'
                if log.exists():
                    for line in log.read_text(errors='replace').splitlines()[-15:]:
                        try:
                            message = str(json.loads(line).get('message', ''))
                            for value in secrets: message = message.replace(value, '[redacted]')
                            print('Nextcloud: ' + message[:1000], file=sys.stderr)
                        except ValueError:
                            pass
            try:
                diagnostic = run([*command, 'logs', '--no-color', '--tail', '120'], timeout=30)
                for container in run([*command, 'ps', '-aq'], timeout=30).splitlines():
                    diagnostic += run(['docker', 'inspect', '--format', '{{json .State}}', container], timeout=30)
                for value in secrets: diagnostic = diagnostic.replace(value, '[redacted]')
                print(diagnostic[-36000:], file=sys.stderr)
            except Exception:
                pass
            raise
        finally:
            server.shutdown(); server.server_close(); server_thread.join(3)
            web.stop.set()
            # Cleanup remains scoped to this runner's single expected project.
            if config.exists(): run([*command, 'down', '--remove-orphans'], timeout=180)
            (code_root / 'titan').unlink()
            code_root.rmdir()


if __name__ == '__main__': main()

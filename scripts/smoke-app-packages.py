#!/usr/bin/env python3
"""Real Docker acceptance checks, exclusively on a disposable CI runner."""
import argparse
import base64
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import pwd
import re
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


@contextlib.contextmanager
def disposable_backup_disk(base, run):
    """Use a real, separately mounted ext4 device; no production check bypass.

    The sparse backing file lives only on the explicitly disposable runner.
    tmpfs is deliberately rejected by production backup target validation.
    """
    image = base / 'backup-smoke.ext4'
    with image.open('xb') as stream:
        stream.truncate(4 * 1024 ** 3)
    target = Path(tempfile.mkdtemp(prefix='titan-app-backup-', dir='/mnt'))
    target.chmod(0o700)
    loop, mounted = None, False
    try:
        run(['mkfs.ext4', '-F', '-q', str(image)], timeout=60)
        device = run(['losetup', '--find', '--show', str(image)], timeout=30).strip()
        if not re.fullmatch(r'/dev/loop[0-9]+', device):
            raise Error('Disposable backup disk did not receive a valid loop-device identity.')
        loop = device
        run(['mount', '-t', 'ext4', '-o', 'nodev,nosuid', loop, str(target)], timeout=30)
        mounted = True
        yield target
    finally:
        if mounted:
            run(['umount', str(target)], timeout=60)
        if loop:
            run(['losetup', '--detach', loop], timeout=30)
        target.rmdir()
        image.unlink()


def app_backup_restore_smoke(base, host, request, action, ready, app, installed, run, app_port):
    """Real Nextcloud/PostgreSQL restore through production HTTP and Host APIs."""
    config_root = host._app_config_path(app, installed)
    data_root = Path(installed['data'])
    private = host.directory / 'apps' / app / 'options.json'
    options_before = json.loads(private.read_text())
    primary = host._app_container(app, host.managed_app(app))
    if not primary:
        raise Error('Nextcloud primary container is missing before app backup acceptance.')

    def occ(*arguments):
        current = host._app_container(app, host.managed_app(app))
        if not current:
            raise Error('Nextcloud primary container is missing after restore.')
        return run(['docker', 'exec', '--user', 'www-data', current['Id'],
                    'php', '/var/www/html/occ', *arguments], timeout=60).strip()

    before_value = 'snapshot-' + os.urandom(12).hex()
    after_value = 'later-' + os.urandom(12).hex()
    occ('config:app:set', 'titan_backup_smoke', 'snapshot_marker', '--value', before_value)
    if occ('config:app:get', 'titan_backup_smoke', 'snapshot_marker') != before_value:
        raise Error('Nextcloud database acceptance marker was not persisted before backup.')
    sentinels = []
    for root, name, value, mode in ((config_root, '.titan-backup-config-smoke', 'configuration-before', 0o600),
                                     (data_root, '.titan-backup-data-smoke', 'user-data-before', 0o640)):
        path = root / name
        path.write_text(value)
        owner = root.stat()
        os.chown(path, owner.st_uid, owner.st_gid)
        path.chmod(mode)
        sentinels.append((path, value, mode, owner.st_uid, owner.st_gid))
    previous_settings = request('/api/backup/settings')
    with disposable_backup_disk(base, run) as target:
        try:
            # Both settings and lifecycle run through the authenticated HTTP
            # API. The normal root agent validates the mounted target itself.
            request('/api/backup/settings', {'target': str(target), 'shares': [], 'include_config': False,
                'apps': [app], 'app_data': [app], 'auto_backup': False, 'retention': 2})
            backup = action('backup_create', shares=[], include_config=False, apps=[app], app_data=[app])
            if backup.get('type') != 'bundle' or backup.get('apps') != [app] or backup.get('app_data') != [app]:
                raise Error('App backup API did not include explicit app configuration and user data.')
            ready()
            if json.loads(private.read_text()) != options_before:
                raise Error('Cold app backup changed saved private credentials.')
            occ('config:app:set', 'titan_backup_smoke', 'snapshot_marker', '--value', after_value)
            if occ('config:app:get', 'titan_backup_smoke', 'snapshot_marker') != after_value:
                raise Error('Nextcloud database acceptance marker was not changed after backup.')
            for path, _, _, _, _ in sentinels:
                path.write_text('changed-after-backup')
                path.chmod(0o666)
            action('app_action', app=app, action='stop')
            restored = action('backup_app_restore', backup=backup['id'], app=app,
                              confirmation=backup['id'], include_data=True)
            if not restored.get('kept_stopped') or not restored.get('include_data'):
                raise Error('App restore API did not retain the stopped state and selected user data.')
            if any(host._app_container_active(row) for row in host._app_lifecycle_snapshot(app)):
                raise Error('App restore unexpectedly started a container.')
            if json.loads(private.read_text()) != options_before:
                raise Error('App restore changed the saved private credentials.')
            for path, value, mode, uid, gid in sentinels:
                info = path.stat()
                if path.read_text() != value or (info.st_mode & 0o777, info.st_uid, info.st_gid) != (mode, uid, gid):
                    raise Error('App restore did not preserve sentinel contents, Unix owners and permissions.')
            recovery = Path(restored['recovery'])
            recovery_paths = json.loads((recovery / 'recovery.json').read_text())['paths']
            for entry, sentinel in zip(recovery_paths, sentinels):
                if (Path(entry['previous']) / sentinel[0].name).read_text() != 'changed-after-backup':
                    raise Error('App restore did not retain the previous live directory for recovery.')
            if (private.parent / 'restore-pending.json').exists():
                raise Error('Successful app restore left a blocking pending marker.')
            action('app_action', app=app, action='start')
            ready()
            if occ('config:app:get', 'titan_backup_smoke', 'snapshot_marker') != before_value:
                raise Error('Real Nextcloud database state was not restored from the cold backup.')
            check = urllib.request.Request('http://127.0.0.1:' + str(app_port) + '/status.php',
                                           headers={'Host': 'nas.test:' + str(app_port)})
            with urllib.request.urlopen(check, timeout=15) as response:
                status = json.load(response)
                if response.status != 200 or status.get('installed') is not True or status.get('maintenance') is not False:
                    raise Error('Restored Nextcloud did not return an installed, usable HTTP status.')
            return {'external_ext4_target': True, 'http_backup_restore': True, 'explicit_user_data': True,
                    'credentials_retained': True, 'unix_permissions_retained': True, 'recovery_retained': True,
                    'restore_kept_stopped': True, 'nextcloud_database_restored': True, 'restart_http_ready': True}
        finally:
            request('/api/backup/settings', previous_settings)


def cloudflared_lan_probe(run, url, credentials=None):
    """Only report bounded response metadata, never bodies, cookies or secrets."""
    command = ['ip', 'netns', 'exec', 'titan-ci-client', 'curl', '--noproxy', '*',
        '--proto', '=http', '--connect-timeout', '2', '--max-time', '5', '-sS',
        '-D', '-', '-o', '/dev/null', '-w', '\nTITAN_HTTP_STATUS:%{http_code}\n', url]
    # Keep credentials out of argv/process listings and diagnostic output.
    config = None
    if credentials is not None:
        if not re.fullmatch(r'[A-Za-z0-9+/]+={0,2}', credentials):
            raise Error('Invalid test Basic authentication encoding.')
        command.extend(['--config', '-'])
        config = 'header = "Authorization: Basic ' + credentials + '"\n'
    output = run(command, input=config, timeout=10)
    result = {'http_status': 'unknown', 'content_type': '', 'www_authenticate': ''}
    for line in output.splitlines():
        if line.startswith('HTTP/'):
            result['content_type'] = result['www_authenticate'] = ''
        elif line.startswith('TITAN_HTTP_STATUS:'):
            value = line.partition(':')[2]
            if re.fullmatch(r'[0-9]{3}', value): result['http_status'] = value
        else:
            name, separator, value = line.partition(':')
            key = {'content-type': 'content_type', 'www-authenticate': 'www_authenticate'}.get(name.lower())
            if separator and key:
                value = ''.join(char for char in value.strip() if 32 <= ord(char) < 127)
                if credentials: value = value.replace(credentials, '[redacted]')
                result[key] = value[:256]
    return result


def bigbear_revision(value):
    if not re.fullmatch(r'[a-f0-9]{40}', value):
        raise argparse.ArgumentTypeError('BigBear revision must be an exact lowercase 40-character Git commit SHA.')
    return value


def check_cloudflared_api(url, credentials=None):
    """Verify the real configuration API in the selected administration mode."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, response, code, message, headers, location):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    if credentials:
        # Static HTML is public upstream, so exercise its protected API.
        try:
            opener.open(url, timeout=5).close()
        except urllib.error.HTTPError as response:
            if response.code != 401:
                raise Error('Cloudflared Web protected API denied with HTTP ' + str(response.code) + ' instead of 401.') from None
        else:
            raise Error('Cloudflared Web protected API allowed unauthenticated access.')
    request = urllib.request.Request(url, headers={'Authorization': 'Basic ' + credentials} if credentials else {})
    try:
        with opener.open(request, timeout=5) as response:
            if response.status != 200 or not isinstance(json.load(response), dict):
                raise Error('Cloudflared Web configuration API is unavailable in the selected authentication mode.')
    except urllib.error.HTTPError as response:
        raise Error('Cloudflared Web configuration API returned HTTP ' + str(response.code) + ' in the selected authentication mode.') from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('package', choices=[*PACKAGES, 'bigbear:adguard-home', 'bigbear:nextcloud', 'bigbear:immich', 'bigbear:cloudflared-web'])
    parser.add_argument('--confirm-disposable-runner', action='store_true')
    parser.add_argument('--bigbear-revision', type=bigbear_revision, metavar='SHA',
        help='Use one verified BigBear commit without anonymous GitHub API branch lookup.')
    parser.add_argument('--cloudflared-auth', choices=['disabled', 'password'],
        help='Cloudflared administration login mode; the default installation leaves it disabled.')
    parser.add_argument('--app-backup-smoke', action='store_true',
        help='Exercise a real external cold backup and Nextcloud database restore through the HTTP APIs.')
    args = parser.parse_args()
    if args.bigbear_revision is not None and not args.package.startswith('bigbear:'):
        parser.error('--bigbear-revision requires a BigBear package.')
    cloudflared_web = args.package == 'bigbear:cloudflared-web'
    if args.cloudflared_auth is not None and not cloudflared_web:
        parser.error('--cloudflared-auth requires bigbear:cloudflared-web.')
    if args.app_backup_smoke and args.package != 'bigbear:nextcloud':
        parser.error('--app-backup-smoke requires bigbear:nextcloud.')
    cloudflared_auth = args.cloudflared_auth or 'disabled'
    if not args.confirm_disposable_runner or os.environ.get('GITHUB_ACTIONS') != 'true':
        parser.error('This test is restricted to an explicitly confirmed disposable GitHub runner.')
    if args.package.startswith('bigbear:'):
        from titan.app_stores import StoreMixin
        from titan.store_sources import BIGBEAR
        from titan.store_recipes import recipes
        from titan.catalog import APPS
        document, _ = StoreMixin.store_document(BIGBEAR, bigbear_revision=args.bigbear_revision)
        if args.bigbear_revision: print('BigBear catalog revision: ' + args.bigbear_revision)
        _, imported = recipes(document, BIGBEAR)
        suffix = args.package.split(':', 1)[1]
        app, recipe = next((key, value) for key, value in imported.items() if key.endswith('-' + suffix))
        APPS[app] = recipe
    else:
        app, recipe = args.package, PACKAGES[args.package]
    user_options = {f['key']: 'Test-' + os.urandom(16).hex() for f in recipe['install_schema'] if f['type'] == 'password' and not f.get('generated')}
    if cloudflared_web and cloudflared_auth == 'disabled':
        environment = recipe['stack']['services'][recipe['stack']['primary']].get('environment', {})
        password_option = environment.get('BASIC_AUTH_PASS', '')
        if not password_option.startswith('@option:'):
            raise Error('Cloudflared Web optional administration password field is missing.')
        user_options.pop(password_option[8:], None)
    if app == 'titan-nextcloud-office':
        user_options['office_mode'] = 'enabled'  # exercise the complete optional Office stack
    options = validate_options(app, prepare_options(app, user_options))
    app_port = recipe['port'] if recipe.get('default_network') == 'host' else 18080
    for key in options:
        if key.startswith('stack_port_') and '_53_' in key: options[key] = 15053
    if 'nas_host' in options: options['nas_host'] = '127.0.0.1'
    if 'stack_nas_host' in options: options['stack_nas_host'] = 'nas.test'
    secrets = [str(options[f['key']]) for f in recipe['install_schema'] if f['type'] == 'password' and options.get(f['key'])]
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
            secrets.extend(str(options[f['key']]) for f in recipe['install_schema'] if f['type'] == 'password' and options.get(f['key']))
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
                service = definition['services'][app]
                if (recipe.get('default_network') != 'host' or installed.get('network', {}).get('mode') != 'host'
                        or service.get('network_mode') != 'host' or service.get('ports') or service.get('networks')):
                    raise Error('Cloudflared Web did not retain the upstream host network.')
                environment = recipe['stack']['services'][recipe['stack']['primary']].get('environment', {})
                def private_value(key):
                    value = environment.get(key, '')
                    return str(actual_options[value[8:]]) if isinstance(value, str) and value.startswith('@option:') else str(value)
                username, password = private_value('BASIC_AUTH_USER'), private_value('BASIC_AUTH_PASS')
                if cloudflared_auth == 'password' and (not username or len(password) < 12):
                    raise Error('Cloudflared Web credentials were not securely configured.')
                if cloudflared_auth == 'disabled' and (password != '' or service['environment'].get('BASIC_AUTH_PASS') != ''):
                    raise Error('Cloudflared Web disabled authentication requires an actual empty password.')
                credentials = base64.b64encode((username + ':' + password).encode()).decode() if password else None
                if credentials: secrets.append(credentials)
                protected_url = 'http://127.0.0.1:' + str(app_port) + '/config'
                check_cloudflared_api(protected_url, credentials)
                cloudflared_private_before = (host.directory / 'apps' / app / 'options.json').read_bytes()
            lan_url = 'http://10.254.254.1:' + str(app_port)
            def check_cloudflared_lan():
                if not cloudflared_web:
                    return
                checks = [('/', '200', None), ('/config', '401' if credentials else '200', None)]
                if credentials: checks.append(('/config', '200', credentials))
                for path, expected, auth in checks:
                    diagnostic = cloudflared_lan_probe(run, lan_url + path, auth)
                    if (diagnostic['http_status'] != expected or
                            expected == '401' and not diagnostic['www_authenticate'].lower().startswith('basic')):
                        raise Error('Cloudflared Web isolated LAN check failed for ' + path + '; expected HTTP ' + expected +
                                    '; received ' + json.dumps(diagnostic, sort_keys=True))
                check_cloudflared_api(protected_url, credentials)
                if (host.directory / 'apps' / app / 'options.json').read_bytes() != cloudflared_private_before:
                    raise Error('Cloudflared Web lifecycle changed saved administration credentials.')
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
            app_backup = (app_backup_restore_smoke(base, host, request, action, ready, app, installed, run, app_port)
                          if args.app_backup_smoke else None)
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
                **({'isolated_lan_firewall_access': True, 'basic_auth_required': bool(credentials),
                    'authentication_mode': cloudflared_auth, 'host_network_verified': True,
                    'credentials_retained': True, 'readiness_verified': True} if cloudflared_web else {}),
                'file_browse_during_install': True, 'file_browse_seconds': round(list_seconds, 3),
                **({'app_backup_restore': app_backup} if app_backup else {}),
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

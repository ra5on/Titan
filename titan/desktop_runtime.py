"""Optional Guacamole runtime; fixed images, private VNC endpoints, no host shell API."""
import hashlib
from functools import wraps
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import threading
import time
import xml.etree.ElementTree as ET

from .core import Error, integer

VERSION = '1.6.0-titan1'
GUACD = 'guacamole/guacd:1.6.0@sha256:8974eaa9ba32f713daf311e7cc8cd7e4cdfba1edea39eed75524e78ef4b08f4f'
SERVICE = 'titan-guacd'
PORT = 4822
LABEL = 'org.titan.desktop'
CONTEXT = Path(__file__).parent / 'session_browser'
IDENTITY = re.compile(r'[a-f0-9]{64}\Z')


def serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._desktop_lifecycle_lock:
            return method(self, *args, **kwargs)
    return call


def recipe_revision():
    value = GUACD.encode()
    for path in sorted(CONTEXT.iterdir()):
        if path.is_file():
            value += path.name.encode() + path.read_bytes()
    return hashlib.sha256(value).hexdigest()


class DesktopRuntimeMixin:
    _desktop_lifecycle_lock = threading.RLock()

    def _desktop_command(self, args, **kwargs):
        from .host import run
        return run(args, **kwargs)

    def _desktop_container(self, name):
        try:
            rows = json.loads(self._desktop_command(['docker', 'container', 'inspect', name], timeout=15))
        except Error:
            return None
        item = rows[0]
        if item.get('Config', {}).get('Labels', {}).get(LABEL) != '1':
            raise Error('Der Containername wird von einem anderen Dienst verwendet.', 409)
        return item

    def desktop_status(self):
        installed = self._plugin_state().get('guacamole', {})
        container = self._desktop_container(SERVICE) if installed else None
        return {'id': 'guacamole', 'name': 'Browser und VM-Sitzungen',
                'description': 'Apache Guacamole mit einem Browser auf dem NAS. Apps und VMs direkt in Titan bedienen.',
                'installed': bool(installed), 'running': bool(container and container.get('State', {}).get('Running')),
                'version': installed.get('version'), 'latest': VERSION, 'beta': True,
                'update_available': bool(installed) and installed.get('recipe') != recipe_revision()}

    def op_desktop_status(self):
        return self.desktop_status()

    def _desktop_plugin(self, action, options):
        if options:
            raise Error('Dieses Plugin benötigt keine Zugangsdaten oder Optionen.')
        state = self._plugin_state()
        previous = state.get('guacamole')
        if action == 'check':
            return {'ok': True, 'message': 'Die freigegebene Plugin-Version wird mit Titan gepflegt.'}
        if action in ('install', 'update'):
            revision = recipe_revision()
            image = 'titan-session-browser:' + revision[:16]
            try:
                self._desktop_command(['docker', 'pull', GUACD], timeout=600)
                self._desktop_command(['docker', 'build', '--pull', '--no-cache', '--tag', image, str(CONTEXT)], timeout=1800)
                # Resolve the locally built tag once; sessions use only this immutable ID.
                browser = json.loads(self._desktop_command(['docker', 'image', 'inspect', image]))[0]['Id']
                if not re.fullmatch(r'sha256:[a-f0-9]{64}', browser):
                    raise Error('Browser-Image konnte nicht geprüft werden.')
                self._desktop_activate(state, revision, browser)
            except Exception:
                if not previous and self._desktop_container(SERVICE):
                    self._desktop_command(['docker', 'rm', '-f', SERVICE])
                raise Error('Guacamole konnte nicht eingerichtet werden. Docker, Internetzugang und freien Speicher prüfen.', 503) from None
            return {'ok': True, 'message': 'Browser und VM-Sitzungen sind bereit. Öffne eine App oder VM in Titan.'}
        return self._desktop_control(action)

    @serialized
    def _desktop_activate(self, state, revision, browser):
        if not self._desktop_container(SERVICE):
            self._desktop_command(['docker', 'run', '-d', '--name', SERVICE, '--label', LABEL + '=1',
                '--network', 'host', '--restart', 'unless-stopped', '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges:true', '--pids-limit', '256', '--memory', '512m',
                '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m', '--entrypoint', '/opt/guacamole/sbin/guacd',
                GUACD, '-f', '-b', '127.0.0.1', '-l', str(PORT), '-L', 'warning'])
        else:
            self._desktop_command(['docker', 'start', SERVICE])
        self._desktop_wait(PORT)
        state['guacamole'] = {'version': VERSION, 'recipe': revision, 'browser': browser}
        self.save('system-plugins', state)

    @serialized
    def _desktop_control(self, action):
        state = self._plugin_state()
        if not state.get('guacamole'):
            raise Error('Plugin ist nicht installiert.', 409)
        if action in ('stop', 'remove'):
            self._desktop_remove_browsers()
            if self._desktop_container(SERVICE):
                self._desktop_command(['docker', 'stop', SERVICE])
            if action == 'remove':
                if self._desktop_container(SERVICE):
                    self._desktop_command(['docker', 'rm', SERVICE])
                state.pop('guacamole', None); self.save('system-plugins', state)
            return {'ok': True, 'message': 'Sitzungen beendet. Browserdaten der Sitzungen wurden gelöscht.'}
        self._desktop_command(['docker', 'start', SERVICE])
        self._desktop_wait(PORT)
        return {'ok': True, 'message': 'Guacamole gestartet.'}

    @staticmethod
    def _desktop_wait(port, vnc=False):
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.2) as stream:
                    if not vnc:
                        return
                    banner = b''
                    while len(banner) < 12:
                        part = stream.recv(12 - len(banner))
                        if not part:
                            break
                        banner += part
                    if re.fullmatch(rb'RFB [0-9]{3}\.[0-9]{3}\n', banner):
                        return
            except OSError:
                pass
            time.sleep(0.1)
        raise Error('Sitzungsdienst ist nicht erreichbar.', 503)

    @serialized
    def _desktop_remove_browsers(self):
        names = self._desktop_command(['docker', 'ps', '-a', '--filter', 'label=' + LABEL + '=1', '--format', '{{.Names}}']).splitlines()
        for name in names:
            if name.startswith('titan-browser-') and IDENTITY.fullmatch(name[14:]):
                self.op_desktop_close(name[14:])

    def _desktop_browser_capacity(self):
        # Enforce the limit in the agent as well: a crashed/restarted web
        # process must not multiply the number of still running containers.
        names = self._desktop_command(['docker', 'ps', '-a', '--filter', 'label=' + LABEL + '=1', '--format', '{{.Names}}']).splitlines()
        active = 0
        for name in names:
            if name.startswith('titan-browser-') and IDENTITY.fullmatch(name[14:]):
                item = self._desktop_container(name)
                if item and item.get('State', {}).get('Running'):
                    active += 1
                else:
                    self.op_desktop_close(name[14:])
        if active >= 8:
            raise Error('Acht Browsersitzungen sind aktiv. Eine Sitzung beenden; nach einem Dienstabsturz das Plugin stoppen und starten.', 429)

    def _desktop_app_url(self, app):
        from .catalog import APPS
        record = self.managed_app(app)
        container = self._app_container(app, record)
        if not container or not container.get('State', {}).get('Running'):
            raise Error('Die App muss laufen.', 409)
        if app == 'titan-tailscale':
            return 'https://login.tailscale.com/admin/'
        recipe = APPS[app]
        target = record['port'] if recipe.get('dynamic_web_port') else recipe.get('port')
        if not target or recipe.get('web_available') is False:
            raise Error('Diese App besitzt keine Weboberfläche.', 409)
        from .app_networks import app_web_host
        trusted_host = app_web_host(self, record)
        if trusted_host:
            return f"{record.get('scheme', 'http')}://{trusted_host}:{integer(record['port'], 1, 65535)}" + recipe.get('web_path', '')
        # Use an actual, running, managed container endpoint. Never accept a URL
        # or a port supplied by the HTTP caller.
        networks = container.get('NetworkSettings', {}).get('Networks', {})
        addresses = [item.get('IPAddress') for item in networks.values() if item.get('IPAddress')]
        if addresses:
            import ipaddress
            address = str(ipaddress.ip_address(addresses[0]))
            # Join the same Docker network: user-defined bridges reject traffic
            # from another bridge by default.
            return f"{record.get('scheme', 'http')}://{address}:{integer(target, 1, 65535)}" + recipe.get('web_path', '')
        return f"{record.get('scheme', 'http')}://host.docker.internal:{integer(record['port'], 1, 65535)}" + recipe.get('web_path', '')

    @serialized
    def op_desktop_open(self, id, kind, target, width, height):
        if not isinstance(id, str) or not IDENTITY.fullmatch(id) or kind not in ('app', 'vm'):
            raise Error('Ungültige Sitzung.')
        width, height = integer(width, 640, 2560), integer(height, 480, 1600)
        if not self.desktop_status()['running']:
            raise Error('Das Plugin „Browser und VM-Sitzungen“ im App Store installieren oder starten.', 409)
        if kind == 'vm':
            from .host import run
            vm = self.vm_id(target)
            root = ET.fromstring(run(['virsh', 'dumpxml', vm]))
            graphics = root.find("./devices/graphics[@type='vnc']")
            if graphics is None or graphics.get('listen') != '127.0.0.1':
                raise Error('Die VM benötigt eine lokale VNC-Konsole.', 409)
            return {'protocol': 'vnc', 'hostname': '127.0.0.1',
                    'port': integer(graphics.get('port', '-1'), 5900, 65535), 'password': graphics.get('passwd', '')}
        url = self._desktop_app_url(target)
        self._desktop_browser_capacity()
        record = self.managed_app(target)
        container = self._app_container(target, record)
        networks = container.get('NetworkSettings', {}).get('Networks', {})
        network = next(iter(networks), 'bridge')
        if network in ('host', 'none'):
            network = 'bridge'
        image = self._plugin_state()['guacamole']['browser']
        name = 'titan-browser-' + id
        folder = self.directory / 'desktop-credentials'
        from .system_plugins import secure_directory
        secure_directory(folder, 0o700)
        password = secrets.token_urlsafe(8)[:8]
        # RFB reverses the bits of each fixed key byte before standard DES.
        # VNC's standard password-file encoding. Password bytes use stdin,
        # never Docker environment, argv, API responses or application logs.
        encoded = subprocess.run(['openssl', 'enc', '-des-ecb', '-provider', 'legacy', '-provider', 'default',
                                  '-K', 'e84ad660c4721ae0', '-nopad'], input=password.encode(), capture_output=True, check=True).stdout
        credential = folder / id
        fd = os.open(credential, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o400)
        with os.fdopen(fd, 'wb') as output:
            output.write(encoded)
        os.chown(credential, 1000, 1000)
        try:
            self._desktop_command(['docker', 'run', '-d', '--name', name, '--label', LABEL + '=1',
                '--network', network, '--add-host', 'host.docker.internal:host-gateway',
                '--publish', '127.0.0.1::5900', '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges:true', '--security-opt', 'seccomp=' + str(CONTEXT / 'seccomp.json'),
                '--pids-limit', '256', '--memory', '1536m', '--cpus', '2', '--shm-size', '256m',
                '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m',
                '--tmpfs', '/home/browser:rw,nosuid,nodev,uid=1000,gid=1000,size=512m',
                '--mount', f'type=bind,src={credential},dst=/run/titan-vnc,readonly',
                '-e', 'APP_URL=' + url, '-e', 'WIDTH=' + str(width), '-e', 'HEIGHT=' + str(height),
                '--entrypoint', '/usr/bin/tini', image, '--', '/usr/bin/timeout', '8h', '/usr/local/bin/titan-browser'])
            item = self._desktop_container(name)
            binding = item['NetworkSettings']['Ports']['5900/tcp'][0]
            if binding['HostIp'] != '127.0.0.1':
                raise Error('Sitzungsport ist nicht lokal gebunden.', 503)
            port = integer(binding['HostPort'], 1024, 65535)
            self._desktop_wait(port, vnc=True)
            return {'protocol': 'vnc', 'hostname': '127.0.0.1', 'port': port, 'password': password}
        except Exception:
            self.op_desktop_close(id)
            raise Error('Browser konnte nicht starten. Docker, freien Arbeitsspeicher und Chromium-Sandbox prüfen.', 503) from None

    @serialized
    def op_desktop_probe(self, id):
        if not isinstance(id, str) or not IDENTITY.fullmatch(id):
            raise Error('Ungültige Sitzung.')
        item = self._desktop_container('titan-browser-' + id)
        return {'running': bool(item and item.get('State', {}).get('Running'))}

    @serialized
    def op_desktop_close(self, id):
        if not isinstance(id, str) or not IDENTITY.fullmatch(id):
            raise Error('Ungültige Sitzung.')
        name = 'titan-browser-' + id
        if self._desktop_container(name):
            self._desktop_command(['docker', 'rm', '-f', name])
        (self.directory / 'desktop-credentials' / id).unlink(missing_ok=True)
        return {'ok': True}

    def op_desktop_files(self, id, transfer):
        if not isinstance(id, str) or not IDENTITY.fullmatch(id) or not isinstance(transfer, dict):
            raise Error('Ungültige Sitzung oder Dateiaktion.')
        allowed = {'list': {'action'}, 'read': {'action', 'name', 'offset'}, 'write': {'action', 'name', 'offset', 'data'}}
        verb = transfer.get('action')
        if not isinstance(verb, str) or verb not in allowed or set(transfer) != allowed[verb]:
            raise Error('Ungültige Dateiaktion.')
        payload = json.dumps(transfer)
        if len(payload) > 380000:
            raise Error('Dateiblock zu groß.', 413)
        name = 'titan-browser-' + id
        container = self._desktop_container(name)
        if not container or not container.get('State', {}).get('Running'):
            raise Error('Browsersitzung ist beendet.', 410)
        result = json.loads(self._desktop_command(['docker', 'exec', '-i', name, 'python3', '/usr/local/bin/titan-session-files.py'], input=payload, timeout=30))
        if result.get('error'):
            raise Error(result['error'], 409)
        return result

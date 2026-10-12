"""Optional host plugins. Fixed vendors and operations; never arbitrary scripts.

Executables are downloaded only after an administrator requests installation.
Cloudflare's token stays in an agent-owned file and reaches systemd through a
credential file, never through argv, a job result, or the browser status API.
"""
import errno
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import re
import secrets
import ssl
import stat
import time
import urllib.request

from .core import Error
from .cloudflare_tunnel import validate_token
from .remote_access import public_url, validate_remote

CONNECTOR = 'plugin-cloudflare'
UNIT = 'titan-cloudflare-plugin.service'
# TITAN-DATA is already mounted here before systemd, on both A/B slots.
# Adding a new bind-mount entry would break older initialized installations.
ROOT = Path('/var/lib/titan-system/plugins/cloudflare')
UNIT_PATH = Path('/etc/systemd/system') / UNIT
METRICS_PORT = 5104
# cloudflared's automatic QUIC -> HTTP/2 fallback includes connection timeouts
# and exponential retries. The former 25s deadline could stop it before TCP.
CONNECT_TIMEOUT = 180
VERSION = '2026.10.0'
DIGESTS = {
    'amd64': 'd33ff2d14475178d2012c2c56beba87389ac5ded27649519f198a7d3134a99db',
    'arm64': 'e6422b9d4f72d3194bc5a38676f13667c06666523217b842a877d72a80b5ac08',
}

# Only these fixed texts reach jobs, audit records and the browser. Never copy
# vendor stderr/journal messages: they may contain credentials or request data.
FAILURES = {
    'CF_DOWNLOAD': 'Cloudflared konnte nicht von GitHub heruntergeladen werden. Internetzugang und DNS des NAS prüfen.',
    'CF_DOWNLOAD_TLS': 'Das TLS-Zertifikat des Cloudflared-Downloads konnte nicht geprüft werden. Systemzeit und Zertifikate des NAS prüfen.',
    'CF_DOWNLOAD_CHECKSUM': 'Der Cloudflared-Download stimmt nicht mit der geprüften SHA-256-Summe überein.',
    'CF_DOWNLOAD_LIMIT': 'Der Cloudflared-Download überschreitet die erlaubte Größe oder Dauer.',
    'CF_STORAGE_FULL': 'Im Systembereich ist kein freier Speicher für das Plugin verfügbar.',
    'CF_FILES': 'Die lokalen Plugin-Dateien konnten nicht eingerichtet werden. Speicher und Dateirechte prüfen.',
    'CF_SERVICE_START': 'Der lokale Cloudflare-Dienst konnte nicht gestartet werden.',
    'CF_SERVICE_EXEC': 'Systemd konnte das Cloudflared-Programm nicht ausführen. Dateirechte und Ausführbarkeit des Plugin-Speichers prüfen.',
    'CF_SERVICE_CREDENTIAL': 'Systemd konnte dem Cloudflare-Dienst die geschützte Token-Datei nicht bereitstellen.',
    'CF_METRICS_PORT': 'Der lokale Cloudflare-Prüfport 5104 ist bereits belegt. Den anderen Dienst prüfen.',
    'CF_TUNNEL_AUTH': 'Cloudflare hat die Tunnel-Anmeldung abgelehnt. Den aktuellen Tunnel-Token aus dem Cloudflare-Konto verwenden.',
    'CF_EDGE_DNS': 'Der Cloudflare-Dienst konnte die Tunnel-Server nicht per DNS auflösen. Den DNS-Resolver des NAS prüfen.',
    'CF_EDGE_TCP': 'Der Cloudflare-Dienst meldet einen TCP-Verbindungsfehler. Ausgehende Verbindungen zu Cloudflare auf TCP-Port 7844 prüfen.',
    'CF_EDGE_QUIC': 'Der Cloudflare-Dienst meldet QUIC-Verbindungsfehler; eine Verbindung wurde nicht bestätigt. Ausgehende Verbindungen zu Cloudflare auf UDP- und TCP-Port 7844 prüfen.',
    'CF_CONNECT_TIMEOUT': 'Die Verbindung zu Cloudflare wurde innerhalb von drei Minuten nicht bestätigt. Dienst und Internetzugang des NAS prüfen.',
    'CF_LOCAL_ROUTE': 'Der Tunnel ist verbunden, aber Titan konnte seinen lokalen Tunnel-Zugang nicht aktivieren. Webadresswechsel, Proxy und Port 5102 prüfen.',
    'CF_DOCKER_MIGRATION': 'Der bisherige Docker-Tunnel konnte beim Umstieg nicht geprüft oder gestoppt werden.',
    'CF_SAVE_STATE': 'Der Plugin-Stand konnte nicht dauerhaft gespeichert werden.',
}


class PluginFailure(Error):
    def __init__(self, code):
        self.code = code
        super().__init__(FAILURES[code], 503)


def architecture():
    value = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine())
    if not value:
        raise Error('Cloudflare ist für diese Architektur nicht freigegeben.')
    return value


def offer(version=VERSION, digest=None):
    arch = architecture()
    if not isinstance(version, str) or not re.fullmatch(r'20[0-9]{2}\.[0-9]{1,2}\.[0-9]+', version):
        raise Error('Ungültige Cloudflare-Version.')
    digest = DIGESTS[arch] if digest is None else digest
    if not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise Error('Cloudflare-Prüfsumme fehlt oder ist ungültig.')
    return {'version': version, 'sha256': digest, 'architecture': arch,
            'url': f'https://github.com/cloudflare/cloudflared/releases/download/{version}/cloudflared-linux-{arch}'}


def latest_offer():
    request = urllib.request.Request('https://api.github.com/repos/cloudflare/cloudflared/releases/latest',
                                     headers={'User-Agent': 'Titan-System-Plugins', 'Accept': 'application/vnd.github+json'})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read(2 * 1024 * 1024 + 1)
        if len(payload) > 2 * 1024 * 1024:
            raise ValueError()
        release = json.loads(payload)
        if release.get('draft') or release.get('prerelease'):
            raise ValueError()
        name = 'cloudflared-linux-' + architecture()
        asset = next(item for item in release['assets'] if item['name'] == name)
        digest = asset['digest']
        if not isinstance(digest, str) or not digest.startswith('sha256:'):
            raise ValueError()
        result = offer(release['tag_name'], digest[7:])
        if asset['browser_download_url'] != result['url']:
            raise ValueError()
        return result
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration):
        raise Error('Cloudflare-Update konnte nicht über das offizielle GitHub-Release geprüft werden. Bisheriger Stand bleibt erhalten.', 503) from None


def secure_directory(path, mode=0o755):
    path.mkdir(mode=mode, parents=True, exist_ok=True)
    for item in (path, path.parent):
        metadata = item.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
            raise Error('Plugin-Verzeichnis ist nicht gegen Änderungen durch andere Benutzer geschützt.', 403)


def write_private(path, data, mode=0o600):
    secure_directory(path.parent, 0o700)
    if path.is_symlink():
        raise Error('Plugin-Datei darf kein symbolischer Link sein.', 403)
    temporary = path.parent / ('.plugin-' + secrets.token_hex(12))
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_owned(path, *, private=False):
    """Do not follow links or trust files writable by another account."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError:
        raise Error('Plugin-Datei ist nicht sicher installiert.', 403) from None
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & (0o077 if private else 0o022)):
            raise Error('Plugin-Datei ist nicht sicher installiert.', 403)
        return stream.read()


def prepare_plugin_root():
    # The agent has umask 0027. Public executable directories must still be
    # traversable by the service's DynamicUser; credentials live elsewhere.
    secure_directory(ROOT.parent)
    ROOT.parent.chmod(0o755)
    secure_directory(ROOT)
    ROOT.chmod(0o755)


def download(candidate, path):
    expected = offer(candidate['version'], candidate['sha256'])
    if candidate != expected:
        raise Error('Plugin-Angebot passt nicht zur Architektur oder Downloadquelle.', 409)
    secure_directory(path.parent)
    try:
        request = urllib.request.Request(expected['url'], headers={'User-Agent': 'Titan-System-Plugins'})
        digest = hashlib.sha256()
        total = 0
        deadline = time.monotonic() + 300
        with urllib.request.urlopen(request, timeout=60) as response, path.open('xb') as target:
            if not response.geturl().startswith('https://'):
                raise Error('Plugin-Download benötigt HTTPS.')
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > 128 * 1024 * 1024 or time.monotonic() > deadline:
                    raise PluginFailure('CF_DOWNLOAD_LIMIT')
                digest.update(chunk); target.write(chunk)
            target.flush(); os.fsync(target.fileno())
        if total < 1024 * 1024 or digest.hexdigest() != expected['sha256']:
            raise PluginFailure('CF_DOWNLOAD_CHECKSUM')
        path.chmod(0o755)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def service_unit(token_path):
    # token_path comes from the fixed agent state directory, never request input.
    if not re.fullmatch(r'/[a-zA-Z0-9_./-]+', str(token_path)):
        raise Error('Agent-Speicherpfad ist für den Dienst nicht geeignet.')
    return f'''[Unit]
Description=Titan Cloudflare Tunnel Plugin
After=network-online.target titan-web.service
Wants=network-online.target
RequiresMountsFor={ROOT}
ConditionPathExists={token_path}

[Service]
Type=simple
DynamicUser=yes
LoadCredential=tunnel-token:{token_path}
ExecStart={ROOT}/cloudflared tunnel --no-autoupdate --metrics 127.0.0.1:{METRICS_PORT} run --token-file %d/tunnel-token
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
CapabilityBoundingSet=
UMask=0077

[Install]
WantedBy=multi-user.target
'''


def connected():
    connection = http.client.HTTPConnection('127.0.0.1', METRICS_PORT, timeout=2)
    try:
        connection.request('GET', '/ready')
        response = connection.getresponse(); response.read(4096)
        return response.status == 200
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


class SystemPluginsMixin:
    def _cloudflare_failure(self, phase, exception):
        if isinstance(exception, PluginFailure):
            return exception.code
        if isinstance(exception, OSError) and exception.errno in (errno.ENOSPC, errno.EDQUOT):
            return 'CF_STORAGE_FULL'
        if phase == 'CF_DOWNLOAD':
            reason = getattr(exception, 'reason', exception)
            if isinstance(reason, ssl.SSLError):
                return 'CF_DOWNLOAD_TLS'
        if phase not in ('CF_SERVICE_START', 'CF_CONNECT_TIMEOUT'):
            return phase
        # Inspect the failing invocation before rollback stops/removes the unit.
        # Properties and journal text remain local; only a fixed code escapes.
        try:
            output = self.command(['systemctl', 'show', UNIT,
                '--property=InvocationID,ExecMainStatus,Result'], timeout=5)
            properties = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
            if properties.get('ExecMainStatus') == '203':
                return 'CF_SERVICE_EXEC'
            if properties.get('ExecMainStatus') == '243':
                return 'CF_SERVICE_CREDENTIAL'
            invocation = properties.get('InvocationID', '')
            if re.fullmatch(r'[a-f0-9]{32}', invocation):
                journal = self.command(['journalctl', '_SYSTEMD_INVOCATION_ID=' + invocation,
                    '--no-pager', '--output=cat', '--lines=60'], timeout=5)[-65536:].lower()
                if 'unauthorized: invalid tunnel secret' in journal or 'unauthorized: failed to get tunnel' in journal:
                    return 'CF_TUNNEL_AUTH'
                if 'error looking up cloudflare edge ips' in journal:
                    return 'CF_EDGE_DNS'
                if re.search(r'dial tcp [^\n]*:7844[^\n]*(?:i/o timeout|network is unreachable|connection refused)', journal):
                    return 'CF_EDGE_TCP'
                if 'failed to dial to edge with quic' in journal:
                    return 'CF_EDGE_QUIC'
            if properties.get('Result') in ('exit-code', 'signal', 'core-dump', 'resources', 'start-limit-hit'):
                return 'CF_SERVICE_START'
        except Exception:
            # Diagnostic failure must never prevent restoration of the old state.
            pass
        return phase

    def _plugin_service_state(self, query):
        try:
            return self.command(['systemctl', query, UNIT], timeout=10).strip() in ('active', 'enabled')
        except Error:
            return False

    def _plugin_state(self):
        return self.load('system-plugins', {})

    def _plugin_revision(self):
        return hashlib.sha256(json.dumps(self._plugin_state(), sort_keys=True).encode()).hexdigest()

    def _cloudflare_installed(self):
        return bool(self._plugin_state().get('cloudflare', {}).get('installed'))

    def op_plugins(self):
        state = self._plugin_state()
        cf = state.get('cloudflare', {})
        candidate = state.get('cloudflare_offer') or offer()
        nvidia = self.nvidia_component()
        installed = self._cloudflare_installed()
        running = installed and self._plugin_service_state('is-active')
        nvidia_version = None
        if nvidia['requested']:
            try:
                nvidia_version = self.command(['dpkg-query', '-W', '-f=${Version}', 'nvidia-driver-cuda'], timeout=10).strip() or None
            except Error:
                pass
        return {'revision': self._plugin_revision(), 'items': [
            {'id': 'cloudflare', 'name': 'Cloudflare Tunnel', 'description': 'Titan über einen verwalteten Debian-Dienst erreichbar machen.',
             'installed': installed, 'version': cf.get('version'), 'latest': candidate['version'],
             'update_available': installed and tuple(map(int, candidate['version'].split('.'))) > tuple(map(int, cf['version'].split('.'))),
             'running': running, 'connected': connected() if running else False,
             'public_origin': cf.get('public_origin', ''), 'service_url': 'http://127.0.0.1:5102',
             'docker_installed': any(item['id'] == 'titan-cloudflared' for item in self.load('apps', [])),
             'checked_at': state.get('cloudflare_checked'), 'beta': True},
            {'id': 'nvidia', 'name': 'NVIDIA-Treiber', 'description': 'GPU-Beschleunigung für Apps; Download erst bei Installation.',
             **nvidia, 'installed': nvidia['requested'], 'running': nvidia['available'], 'beta': True,
             'version': nvidia_version, 'latest': state.get('nvidia_offer'),
             'update_available': state.get('nvidia_update', False), 'checked_at': state.get('nvidia_checked')},
        ]}

    def op_plugin_action(self, plugin, action, expected_revision, options=None, confirmation=None):
        if plugin not in ('cloudflare', 'nvidia') or action not in ('check', 'install', 'update', 'remove', 'start', 'stop'):
            raise Error('Unbekanntes Plugin oder ungültige Aktion.')
        if expected_revision != self._plugin_revision():
            raise Error('Plugin-Stand wurde geändert. Ansicht aktualisieren.', 409)
        options = {} if options is None else options
        if not isinstance(options, dict):
            raise Error('Plugin-Einstellungen müssen ein Objekt sein.')
        if action == 'remove' and confirmation != plugin:
            raise Error('Deinstallation ausdrücklich bestätigen.')
        if plugin == 'nvidia':
            return self._nvidia_plugin(action, options)
        if action == 'check':
            if options: raise Error('Updateprüfung benötigt keine Einstellungen.')
            state = self._plugin_state()
            state.update(cloudflare_offer=latest_offer(), cloudflare_checked=time.time())
            self.save('system-plugins', state)
            return {'ok': True, 'message': 'Cloudflare-Updates geprüft.'}
        if action in ('install', 'update'):
            return self._install_cloudflare(action, options)
        if options: raise Error('Diese Aktion benötigt keine Einstellungen.')
        if not self._cloudflare_installed(): raise Error('Plugin ist nicht installiert.', 409)
        if action == 'remove':
            config = self.web_access.config()
            remote = validate_remote(config.get('remote'))
            if remote['enabled'] and remote['connector'] == CONNECTOR:
                self.web_access.save_remote({**remote, 'enabled': False}, config['revision'], wait=True)
            self.command(['systemctl', 'disable', '--now', UNIT])
            UNIT_PATH.unlink(missing_ok=True)
            self.command(['systemctl', 'daemon-reload'])
            (self.directory / 'cloudflare-plugin-token').unlink(missing_ok=True)
            for name in ('cloudflared', 'cloudflared.previous'):
                (ROOT / name).unlink(missing_ok=True)
            state = self._plugin_state(); state.pop('cloudflare', None); self.save('system-plugins', state)
            return {'ok': True, 'message': 'Cloudflare-Plugin und lokaler Token entfernt. Den Tunnel im Cloudflare-Konto bei Bedarf separat löschen.'}
        self.command(['systemctl', action, UNIT])
        return {'ok': True, 'message': 'Cloudflare-Dienst gestartet.' if action == 'start' else 'Cloudflare-Dienst gestoppt.'}

    def _install_cloudflare(self, action, options):
        if set(options) - {'token', 'public_origin', 'replace_docker'}:
            raise Error('Ungültige Cloudflare-Einstellungen.')
        if type(options.get('replace_docker', False)) is not bool:
            raise Error('Docker-Umstieg ausdrücklich bestätigen.')
        state = self._plugin_state(); original_state = dict(state); previous = state.get('cloudflare', {})
        candidate = state.get('cloudflare_offer') or offer()
        if action == 'update' and not previous.get('installed'):
            raise Error('Plugin zuerst installieren.', 409)
        token_path = self.directory / 'cloudflare-plugin-token'
        old_token = read_owned(token_path, private=True)
        token = validate_token(options['token']) if options.get('token') else None
        if not token and not old_token: raise Error('Cloudflare-Tunnel-Token fehlt.')
        address = public_url(options.get('public_origin') or previous.get('public_origin', ''))
        legacy = any(item['id'] == 'titan-cloudflared' for item in self.load('apps', []))
        if legacy and not previous.get('installed') and not options.get('replace_docker'):
            raise Error('Der Docker-Tunnel ist vorhanden. Den Umstieg auf den Debian-Dienst ausdrücklich bestätigen.', 409)
        config = self.web_access.config()
        if config.get('pending'): raise Error('Zuerst den laufenden Webadresswechsel abschließen.', 409)
        remote = validate_remote(config.get('remote'))
        if remote['enabled'] and remote['connector'] not in ('', CONNECTOR, 'titan-cloudflared'):
            raise Error('Ein anderer Fernzugriff ist aktiv. Diesen zuerst unter Fernzugriff deaktivieren.', 409)
        prepare_plugin_root()
        stage = ROOT / ('.download-' + secrets.token_hex(12))
        binary = ROOT / 'cloudflared'; backup = ROOT / ('.previous-' + secrets.token_hex(12))
        old_unit = read_owned(UNIT_PATH)
        was_running = self._plugin_service_state('is-active') if old_unit else False
        was_enabled = self._plugin_service_state('is-enabled') if old_unit else False
        legacy_running = False; legacy_stopped = False; remote_changed = False
        installed_binary = False; moved_binary = False; token_changed = False; unit_changed = False; service_changed = False
        phase = 'CF_DOWNLOAD'
        try:
            download(candidate, stage)
            if legacy and options.get('replace_docker'):
                phase = 'CF_DOCKER_MIGRATION'
                record = self.managed_app('titan-cloudflared')
                container = self._app_container('titan-cloudflared', record)
                legacy_running = bool(container and container.get('State', {}).get('Running'))
            if old_unit:
                phase = 'CF_SERVICE_START'
                service_changed = True
                self.command(['systemctl', 'stop', UNIT])
            phase = 'CF_FILES'
            if binary.exists():
                read_owned(binary)
                binary.replace(backup); moved_binary = True
            stage.replace(binary); installed_binary = True
            if token:
                write_private(token_path, token.encode()); token_changed = True
            write_private(UNIT_PATH, service_unit(token_path).encode(), 0o644)
            unit_changed = True
            phase = 'CF_SERVICE_START'
            self.command(['systemctl', 'daemon-reload'])
            if self.command(['ss', '-H', '-ltn', 'sport = :' + str(METRICS_PORT)], timeout=5).strip():
                raise PluginFailure('CF_METRICS_PORT')
            service_changed = True
            self.command(['systemctl', 'enable', '--now', UNIT])
            phase = 'CF_CONNECT_TIMEOUT'
            deadline = time.monotonic() + CONNECT_TIMEOUT
            while not connected():
                if time.monotonic() >= deadline:
                    raise Error('Cloudflare-Verbindung nicht bestätigt.', 503)
                time.sleep(1)
            phase = 'CF_LOCAL_ROUTE'
            desired = {**remote, 'enabled': True, 'public_origin': address, 'connector': CONNECTOR,
                       'sources': [], 'interface': '', 'service_url': 'http://127.0.0.1:5102'}
            self.web_access.save_remote(desired, config['revision'], wait=True); remote_changed = True
            if legacy_running:
                phase = 'CF_DOCKER_MIGRATION'
                legacy_stopped = True
                self.op_app_action('titan-cloudflared', 'stop')
            phase = 'CF_SAVE_STATE'
            state['cloudflare'] = {'installed': True, 'version': candidate['version'], 'sha256': candidate['sha256'], 'public_origin': address}
            self.save('system-plugins', state)
        except Exception as exception:
            # No token or vendor output appears in the failure result.
            failure = self._cloudflare_failure(phase, exception)
            message = 'Cloudflare-Plugin: ' + FAILURES[failure] + ' Fehlercode: ' + failure + '.'
            errors = []
            def undo(callback):
                try: callback()
                except Exception: errors.append(True)
            if service_changed:
                undo(lambda: self.command(['systemctl', 'stop', UNIT]))
                if not was_enabled: undo(lambda: self.command(['systemctl', 'disable', UNIT]))
            if installed_binary: undo(lambda: binary.unlink(missing_ok=True))
            if moved_binary: undo(lambda: backup.replace(binary))
            if token_changed:
                undo(lambda: write_private(token_path, old_token) if old_token is not None else token_path.unlink(missing_ok=True))
            if unit_changed:
                undo(lambda: write_private(UNIT_PATH, old_unit, 0o644) if old_unit is not None else UNIT_PATH.unlink(missing_ok=True))
                undo(lambda: self.command(['systemctl', 'daemon-reload']))
            if service_changed and was_enabled: undo(lambda: self.command(['systemctl', 'enable', UNIT]))
            if service_changed and was_running: undo(lambda: self.command(['systemctl', 'start', UNIT]))
            if remote_changed:
                undo(lambda: self.web_access.save_remote(remote, self.web_access.config()['revision'], wait=True))
            if legacy_stopped: undo(lambda: self.op_app_action('titan-cloudflared', 'start'))
            undo(lambda: self.save('system-plugins', original_state))
            if errors:
                raise Error(message + ' Rücksetzung unvollständig. Dienste und Fernzugriff lokal prüfen.', 503) from None
            raise Error(message + ' Bisheriger Stand wurde wiederhergestellt.', 503) from None
        finally:
            stage.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)
        try:
            confirmed = self.op_remote_access_diagnose()['connected']
        except Exception:
            confirmed = False
        return {'ok': True, 'connected': confirmed, 'message': 'Cloudflare-Dienst installiert. ' +
                ('Öffentlicher Titan-Zugang bestätigt.' if confirmed else 'In Cloudflare als Ziel HTTP und 127.0.0.1:5102 eintragen. Die öffentliche Adresse bleibt HTTPS; ihr Titan-Zugang ist noch nicht bestätigt.')}

    def _nvidia_plugin(self, action, options):
        # Implemented through the existing fixed Debian component helper.
        if action in ('start', 'stop'):
            raise Error('Treiber lassen sich installieren, aktualisieren oder entfernen.')
        if set(options) - {'accept_license'} or (action in ('install', 'update') and options.get('accept_license') is not True):
            raise Error('NVIDIA-Lizenzbedingungen vor der Installation bestätigen.')
        from .components import run_plugin_component
        result = run_plugin_component(self, action)
        state = self._plugin_state()
        if action == 'check':
            state.update(nvidia_offer=result.get('candidate'), nvidia_update=result.get('update_available', False), nvidia_checked=time.time())
        elif action == 'remove':
            state.pop('nvidia', None); state.pop('nvidia_update', None)
        else:
            state['nvidia'] = {'version': result.get('version')}; state['nvidia_update'] = False
        self.save('system-plugins', state)
        return result

    def op_plugins_restore(self):
        """Recreate the optional service after a system-slot switch; no download."""
        if self._cloudflare_installed():
            prepare_plugin_root()
            binary = read_owned(ROOT / 'cloudflared')
            if not binary or hashlib.sha256(binary).hexdigest() != self._plugin_state()['cloudflare'].get('sha256'):
                raise Error('Cloudflare-Plugin fehlt im persistenten Speicher. Im Appstore erneut installieren.')
            read_owned(self.directory / 'cloudflare-plugin-token', private=True)
            # Existing units survive through /etc's persistent overlay. Do not
            # undo an explicit Stop just because the Titan agent was restarted.
            if read_owned(UNIT_PATH) is None:
                write_private(UNIT_PATH, service_unit(self.directory / 'cloudflare-plugin-token').encode(), 0o644)
                self.command(['systemctl', 'daemon-reload'])
                self.command(['systemctl', 'enable', '--now', UNIT])
        return {'ok': True}

"""Explicit public addresses and a source-restricted local tunnel endpoint."""
import hashlib
import http.client
import ipaddress
import json
import re
import secrets
import socket
import ssl
import time
import urllib.parse

from .core import Error

TUNNEL_PORT = 5102


def public_url(value, *, application=False):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) <= 32 or ord(c) >= 127 for c in value):
        raise Error('Eine gültige öffentliche HTTPS-Adresse angeben.')
    try:
        url = urllib.parse.urlsplit(value)
        if (url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment or
                url.port not in (None, 443) or url.query or (not application and url.path not in ('', '/'))):
            raise ValueError()
        from .web_access import hostname
        host = hostname(url.hostname)
        if ':' in host or '.' not in host or host.endswith(('.local', '.localhost')):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
    except (ValueError, Error):
        raise Error('Öffentliche HTTPS-Domain ohne Zugangsdaten, Port, Abfrage oder Fragment angeben.') from None
    return 'https://' + host + (url.path if application else '')


def validate_remote(value):
    if value is None:
        return {'enabled': False, 'public_origin': '', 'connector': '', 'app_urls': {}, 'sources': [], 'interface': '', 'service_url': ''}
    keys = {'enabled', 'public_origin', 'connector', 'app_urls', 'sources', 'interface', 'service_url'}
    if not isinstance(value, dict) or set(value) != keys or type(value['enabled']) is not bool:
        raise Error('Ungültige Fernzugriffseinstellungen.')
    result = dict(value)
    if not isinstance(value['public_origin'], str) or not isinstance(value['service_url'], str):
        raise Error('Webadressen müssen Text sein.')
    if value['public_origin']:
        result['public_origin'] = public_url(value['public_origin'])
    if value['enabled'] and not value['public_origin']:
        raise Error('Für Fernzugriff eine öffentliche HTTPS-Adresse angeben.')
    if not isinstance(value['connector'], str) or (value['connector'] and not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', value['connector'])):
        raise Error('Ungültiger Tunnel-Connector.')
    if not isinstance(value['app_urls'], dict) or len(value['app_urls']) > 128:
        raise Error('Ungültige öffentliche App-Adressen.')
    result['app_urls'] = {}
    for app, address in value['app_urls'].items():
        if not isinstance(app, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', app):
            raise Error('Ungültige App-Kennung.')
        result['app_urls'][app] = public_url(address, application=True)
    if not isinstance(value['sources'], list) or len(value['sources']) > 8:
        raise Error('Ungültige Connector-Netze.')
    for source in value['sources']:
        try:
            network = ipaddress.IPv4Network(source, strict=True)
            if not any(network.subnet_of(ipaddress.ip_network(block)) for block in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
                raise ValueError()
        except (ValueError, TypeError):
            raise Error('Nur beobachtete private Docker-Netze sind für den Connector zulässig.') from None
    if not isinstance(value['interface'], str) or (value['interface'] and not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,64}', value['interface'])):
        raise Error('Ungültige Connector-Schnittstelle.')
    if value['sources'] and not value['interface']:
        raise Error('Docker-Schnittstelle fehlt.')
    if value['service_url']:
        try:
            target = urllib.parse.urlsplit(value['service_url'])
            if target.scheme != 'http' or target.port != TUNNEL_PORT or target.username or target.password or target.path or target.query or target.fragment:
                raise ValueError()
            address = ipaddress.IPv4Address(target.hostname)
            if not address.is_loopback and not any(address in ipaddress.ip_network(source) for source in value['sources']):
                raise ValueError()
        except (ValueError, TypeError):
            raise Error('Ungültige lokale Tunnel-Zieladresse.') from None
    if value['enabled'] and not value['service_url']:
        raise Error('Lokale Tunnel-Zieladresse fehlt.')
    return result


def tunnel_caddy(config):
    remote = validate_remote(config.get('remote'))
    if not remote['enabled']:
        return ''
    # HTTPS terminates at Cloudflare. The dedicated listener never redirects
    # to a private NAS address; only explicitly selected connector sources pass.
    host = urllib.parse.urlsplit(remote['public_origin']).netloc
    bind = '' if remote['sources'] else '    bind 127.0.0.1\n'
    sources = ' '.join(['127.0.0.1/32', *remote['sources']])
    return (f'http://:{TUNNEL_PORT} {{\n{bind}'
            f'    @connector {{\n        remote_ip {sources}\n        host {host}\n    }}\n'
            '    handle @connector {\n        reverse_proxy 127.0.0.1:5001 {\n'
            '            header_up X-Forwarded-Proto https\n        }\n    }\n'
            '    handle {\n        respond 403\n    }\n}\n')


def proof(config):
    return hashlib.sha256((config['revision'] + validate_remote(config.get('remote'))['public_origin']).encode()).hexdigest()


def probe_public(config):
    """TLS-verified, pinned public DNS connection; no credentials or redirects."""
    remote = validate_remote(config.get('remote'))
    if not remote['enabled']:
        return {'ok': False, 'message': 'Fernzugriff ist deaktiviert.'}
    host = urllib.parse.urlsplit(remote['public_origin']).hostname
    connection = None
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(row[4][0] for row in answers))
        if not addresses or any(not ipaddress.ip_address(address).is_global or ipaddress.ip_address(address).is_multicast or ipaddress.ip_address(address).is_reserved for address in addresses):
            return {'ok': False, 'message': 'Die öffentliche Domain zeigt nicht ausschließlich auf öffentliche Adressen. DNS prüfen.'}
        raw = socket.create_connection((addresses[0], 443), timeout=4)
        try:
            secured = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        except Exception:
            raw.close()
            raise
        connection = http.client.HTTPSConnection(host, timeout=4)
        connection.sock = secured
        challenge = secrets.token_hex(16)
        connection.request('GET', '/api/tunnel-health?challenge=' + challenge, headers={'Host': host, 'Accept': 'application/json'})
        response = connection.getresponse()
        payload = response.read(4097)
        if response.status != 200:
            messages = {403: 'Domain/Host-Prüfung oder Cloudflare-Zugriffsregel blockiert den Zugang.',
                        502: 'Der Tunnel erreicht den Zieldienst nicht. Netzwerk, Port und Protokoll prüfen.',
                        301: 'Weiterleitung statt Tunnel-Zugang. Die angezeigte Tunnel-Zieladresse verwenden.',
                        302: 'Weiterleitung oder Cloudflare Access verlangt eine Anmeldung.',
                        308: 'HTTP/HTTPS-Weiterleitung. Die angezeigte Tunnel-Zieladresse verwenden.'}
            return {'ok': False, 'status': response.status, 'message': messages.get(response.status, 'Öffentlicher Zugang antwortet mit HTTP ' + str(response.status) + '.')}
        data = json.loads(payload) if len(payload) <= 4096 else {}
        ok = data == {'service': 'Titan', 'challenge': challenge, 'proof': proof(config)}
        return {'ok': ok, 'status': 200, 'message': 'Öffentliche HTTPS-Adresse erreicht dieses Titan.' if ok else 'Die Domain liefert nicht den Prüfendpunkt dieses Titan. Route oder Cloudflare Access prüfen.'}
    except ssl.SSLError:
        return {'ok': False, 'message': 'Das öffentliche TLS-Zertifikat konnte nicht bestätigt werden.'}
    except (OSError, ValueError, http.client.HTTPException):
        return {'ok': False, 'message': 'Öffentliche Adresse nicht erreichbar. DNS, Tunnel und Zieladresse prüfen.'}
    finally:
        if connection:
            connection.close()


class RemoteAccessMixin:
    def _remote_setup_update(self, phase, message, *, running=False, needs_domain=False):
        from .cloudflare_tunnel import CONNECTOR
        state = {'phase': phase, 'message': message, 'running': running, 'needs_domain': needs_domain,
                 'connector': CONNECTOR, 'service_url': f'http://127.0.0.1:{TUNNEL_PORT}', 'updated_at': time.time()}
        self.save('remote-tunnel-setup', state)
        return state

    def _remote_setup_status(self):
        from .cloudflare_tunnel import CONNECTOR, connector_ready
        stored = self.load('remote-tunnel-setup', {})
        if not stored:
            return {}
        # Explicit allowlist: private options, Docker inspect and tokens are
        # never part of HTTP status, jobs, diagnostics or browser persistence.
        result = {key: stored[key] for key in ('phase', 'message', 'running', 'needs_domain', 'connector', 'service_url', 'updated_at') if key in stored}
        if stored.get('running') and not getattr(self, '_remote_setup_active', False):
            result.update(running=False, phase='interrupted', message='Tunnel-Einrichtung durch Dienstneustart unterbrochen. Erneut einrichten oder vorhandene App starten.')
        result.update(connector_running=False, cloudflare_connected=False)
        if any(row['id'] == CONNECTOR for row in self.load('apps', [])):
            try:
                record = self.managed_app(CONNECTOR)
                container = self._app_container(CONNECTOR, record)
                result['service_url'] = self._connector_settings(CONNECTOR)['service_url']
                result['connector_running'] = bool(container and container.get('State', {}).get('Running'))
                result['cloudflare_connected'] = connector_ready(container)
                if not result.get('running') and result.get('phase') in ('ready', 'needs_route', 'needs_domain', 'disconnected', 'disabled', 'stopped'):
                    config = self.web_access.config()
                    remote = validate_remote(config.get('remote'))
                    diagnosis = self.load('remote-diagnosis', {})
                    if not result['connector_running']:
                        result.update(phase='stopped', message='Der verwaltete Tunnel-Connector ist gestoppt. In Docker oder der App-Verwaltung starten.')
                    elif not result['cloudflare_connected']:
                        result.update(phase='disconnected', message='Der Connector läuft, aber eine aktuelle Verbindung zu Cloudflare ist nicht bestätigt. Token, Internetzugang und Port 7844 prüfen.')
                    elif not result.get('needs_domain') and (not remote['enabled'] or remote['connector'] != CONNECTOR):
                        result.update(phase='disabled', message='Der lokale Zugang dieses Connectors ist deaktiviert oder ein anderer Connector ist ausgewählt. Gespeicherte Einstellungen bleiben erhalten.')
                    elif result.get('phase') == 'ready' and (diagnosis.get('revision') != config['revision'] or not diagnosis.get('connected')):
                        result.update(phase='needs_route', message='Connector verbunden. Öffentlichen Zugang nach der Einstellungsänderung erneut prüfen.')
            except Error:
                if not result.get('running'):
                    result.update(phase='blocked', message='Der verwaltete Connector benötigt eine Prüfung in Docker oder der App-Verwaltung.')
        elif not result.get('running') and result.get('phase') not in ('failed', 'interrupted'):
            result.update(phase='removed', message='Der verwaltete Tunnel-Connector ist nicht installiert. Mit einem Tunnel-Token erneut einrichten.')
        return result

    def _remote_connectors(self):
        from .catalog import APPS
        result = []
        for record in self.load('apps', []):
            recipe = APPS.get(record['id'], {})
            if 'cloudflared' in str(recipe.get('image', '')).lower():
                result.append({'id': record['id'], 'name': record.get('name', record['id'])})
        return result

    def op_remote_access(self):
        config = self.web_access.config()
        remote = validate_remote(config.get('remote'))
        return {'remote': remote, 'revision': config['revision'], 'connectors': self._remote_connectors(),
                'apps': [{'id': row['id'], 'name': row.get('name', row['id'])} for row in self.load('apps', [])],
                'setup': self._remote_setup_status(),
                'diagnosis': self.load('remote-diagnosis', {}) if remote['enabled'] and self.load('remote-diagnosis', {}).get('revision') == config['revision'] else {}}

    def op_remote_access_tunnel(self, token, public_origin, expected_revision):
        """Install/rotate one owned runner; existing connectors stay untouched."""
        from .cloudflare_tunnel import CONNECTOR, METRICS_PORT, connector_ready, prepare_runtime, validate_token
        from .catalog import validate_options
        from .core import atomic_json
        from .host import run
        token = validate_token(token)
        if not isinstance(public_origin, str):
            raise Error('Eine öffentliche HTTPS-Adresse angeben oder das Feld leer lassen.')
        address = public_url(public_origin) if public_origin else ''
        with self.app_config_lock:
            config = self.web_access.config()
            if not isinstance(expected_revision, str) or config['revision'] != expected_revision or config.get('pending'):
                raise Error('Webeinstellungen geändert oder Adresswechsel aktiv. Ansicht aktualisieren.', 409)
            previous_remote = validate_remote(config.get('remote'))
            address = address or previous_remote['public_origin']
            existing = next((row for row in self.load('apps', []) if row['id'] == CONNECTOR), None)
            old_options, was_running, desired, changed, remote_saved = None, False, None, False, False
            if existing:
                existing = self.managed_app(CONNECTOR)
                container = self._app_container(CONNECTOR, existing)
                if container and container.get('State', {}).get('Status') == 'paused':
                    raise Error('Pausierten Tunnel-Connector zuerst in Docker fortsetzen oder stoppen.', 409)
                old_options = self._app_options(CONNECTOR)
                was_running = bool(container and container.get('State', {}).get('Running'))
            self._remote_setup_active = True
            phase = 'preparing'
            try:
                self._remote_setup_update(phase, 'Docker und geschützte Tunnel-Einrichtung werden vorbereitet.', running=True)
                if not self.docker_component().get('available'):
                    self.op_component_install('docker')
                if not was_running and (not existing or existing.get('network', {}).get('mode') == 'host'):
                    if run(['ss', '-H', '-ltn', 'sport = :' + str(METRICS_PORT)], timeout=5).strip():
                        raise Error('Der lokale Cloudflare-Prüfport ist bereits belegt.', 409)
                phase = 'installing'
                self._remote_setup_update(phase, 'Cloudflare-Connector wird installiert oder mit dem neuen Token gestartet.', running=True)
                changed = True
                if existing:
                    options = validate_options(CONNECTOR, {**old_options, 'tunnel_token': token})
                    atomic_json(self.directory / 'apps' / CONNECTOR / 'options.json', options)
                    self.op_app_action(CONNECTOR, 'restart' if was_running else 'start')
                else:
                    self.op_app_install(CONNECTOR, 0, options={'tunnel_token': token}, network={'mode': 'host'}, storage_id='system')
                phase = 'connecting'
                self._remote_setup_update(phase, 'Connector gestartet. Verbindung zu Cloudflare wird geprüft.', running=True)
                deadline = time.monotonic() + 25
                while True:
                    record = self.managed_app(CONNECTOR)
                    container = self._app_container(CONNECTOR, record)
                    if connector_ready(container):
                        break
                    if time.monotonic() >= deadline:
                        raise Error('Cloudflare-Verbindung konnte nicht bestätigt werden.', 503)
                    time.sleep(1)
                if not address:
                    self._remote_setup_update('needs_domain',
                        'Connector mit Cloudflare verbunden. Öffentlichen Hostnamen im Cloudflare-Konto auf das angezeigte HTTP-Ziel richten und die HTTPS-Adresse in Titan speichern. Der lokale Tunnel-Zugang wird erst mit dieser Adresse aktiviert.',
                        needs_domain=True)
                    return {'ok': True, **self.op_remote_access()}
                phase = 'configuring'
                self._remote_setup_update(phase, 'Lokaler Tunnel-Zugang, Proxy und begrenzte Firewallregeln werden eingerichtet.', running=True)
                desired = validate_remote({**previous_remote, 'enabled': True, 'public_origin': address,
                    'connector': CONNECTOR, **self._connector_settings(CONNECTOR)})
                self.web_access.save_remote(desired, expected_revision, wait=True)
                remote_saved = True
                self.save('remote-diagnosis', {})
                if validate_remote(self.web_access.config().get('remote')) != desired:
                    raise Error('Der lokale Tunnel-Zugang konnte nicht aktiviert werden.', 503)
                phase = 'checking'
                self._remote_setup_update(phase, 'Öffentliche HTTPS-Adresse wird mit diesem Titan abgeglichen.', running=True)
                diagnosis = self.op_remote_access_diagnose()
                self._remote_setup_update('ready' if diagnosis['connected'] else 'needs_route',
                    'Tunnel und öffentlicher Titan-Zugang sind geprüft.' if diagnosis['connected'] else
                    'Connector verbunden und lokales Ziel eingerichtet. Die öffentliche Cloudflare-Route ist noch nicht bestätigt; Hostname und HTTP-Ziel im Cloudflare-Konto prüfen, danach Verbindung erneut prüfen.')
                return {'ok': True, **self.op_remote_access()}
            except Exception:
                # No upstream error string can carry a token into a job/audit.
                # Restore a rotated credential and its previous lifecycle;
                # fresh failed runners remain managed but safely stopped.
                restored = True
                try:
                    current = self.web_access.config()
                    if remote_saved and validate_remote(current.get('remote')) == desired:
                        self.web_access.save_remote(previous_remote, current['revision'], wait=True)
                except Exception:
                    restored = False
                try:
                    if changed and any(row['id'] == CONNECTOR for row in self.load('apps', [])):
                        self.op_app_action(CONNECTOR, 'stop')
                        if old_options is not None:
                            atomic_json(self.directory / 'apps' / CONNECTOR / 'options.json', old_options)
                            if was_running:
                                self.op_app_action(CONNECTOR, 'start')
                            else:
                                prepare_runtime(self, existing)
                except Exception:
                    restored = False
                messages = {'preparing': 'Docker oder der lokale Prüfport ist nicht bereit. Komponentenstatus und Port 5103 prüfen.',
                    'installing': 'Cloudflare-Connector konnte nicht gestartet werden. Docker, Speicher und Internetzugang prüfen.',
                    'connecting': 'Keine Verbindung zu Cloudflare bestätigt. Tunnel-Token und ausgehenden TCP/UDP-Port 7844 prüfen.',
                    'configuring': 'Der lokale Tunnel-Zugang konnte nicht aktiviert werden. Proxy und Firewall prüfen.',
                    'checking': 'Die abschließende Verbindungsprüfung konnte nicht ausgeführt werden.'}
                message = messages[phase] + (' Bisheriger Token und Connector-Zustand wurden wiederhergestellt.' if existing and restored else '')
                if not restored:
                    message += ' Wiederherstellung der Tunnel-Einstellungen unvollständig; App-, Proxy- und Firewallstatus prüfen.'
                self._remote_setup_update('failed', message)
                raise Error(message, 503) from None
            finally:
                self._remote_setup_active = False

    def _connector_settings(self, connector):
        if not connector:
            return {'sources': [], 'interface': '', 'service_url': f'http://127.0.0.1:{TUNNEL_PORT}'}
        if connector not in {item['id'] for item in self._remote_connectors()}:
            raise Error('Einen installierten Cloudflared-Connector wählen.')
        record = self.managed_app(connector)
        container = self._app_container(connector, record)
        if not container:
            raise Error('Der Connector-Container fehlt. App zuerst einrichten.', 409)
        if container.get('HostConfig', {}).get('NetworkMode') == 'host':
            return {'sources': [], 'interface': '', 'service_url': f'http://127.0.0.1:{TUNNEL_PORT}'}
        names = list((container.get('NetworkSettings') or {}).get('Networks') or {})
        for name in names:
            item = self._docker_network(name)
            if item.get('Driver') != 'bridge' or item.get('Scope', 'local') != 'local' or item.get('Internal'):
                continue
            subnets = [row for row in self._network_subnets(item) if row['family'] == 4 and row['gateway']]
            if subnets:
                interface = (item.get('Options') or {}).get('com.docker.network.bridge.name') or ('docker0' if name == 'bridge' else 'br-' + item['Id'][:12])
                return {'sources': [row['subnet'] for row in subnets], 'interface': interface,
                        'service_url': f'http://{subnets[0]["gateway"]}:{TUNNEL_PORT}'}
        raise Error('Kein geeignetes privates Docker-Bridge-Netz am Connector erkannt. Host-Netz oder eigenes Bridge-Netz verwenden.', 409)

    def _remote_firewall(self, value):
        from .app_firewall import reconcile
        from .host import run
        remote = validate_remote(value)
        scopes = []
        if remote['enabled'] and remote['sources']:
            try:
                active = run(['firewall-cmd', '--state'], timeout=3).strip() == 'running'
            except Error:
                active = False
            if not active:
                return reconcile(self, 'remote-tunnel', [{'host': TUNNEL_PORT, 'protocol': 'tcp'}], scopes_override=[])
            try:
                zone = run(['firewall-cmd', '--get-zone-of-interface=' + remote['interface']], timeout=3).strip()
            except Error as exc:
                if str(exc).strip() != 'no zone':
                    raise
                zone = 'no zone'
            if zone in ('', 'no zone'):
                zone = run(['firewall-cmd', '--get-default-zone'], timeout=3).strip()
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', zone):
                raise Error('Docker-Firewallzone konnte nicht geprüft werden.', 503)
            scopes = [{'zone': zone, 'source': source, 'family': 4, 'address': urllib.parse.urlsplit(remote['service_url']).hostname} for source in remote['sources']]
        return reconcile(self, 'remote-tunnel', [{'host': TUNNEL_PORT, 'protocol': 'tcp'}] if scopes else [], scopes_override=scopes)

    def op_remote_access_apply(self, enabled, public_origin, connector, app_urls, expected_revision):
        with self.app_config_lock:
            installed = {row['id'] for row in self.load('apps', [])}
            if not isinstance(app_urls, dict) or set(app_urls) - installed:
                raise Error('Öffentliche Adressen können nur installierten Apps zugeordnet werden.')
            remote = validate_remote({'enabled': enabled, 'public_origin': public_origin, 'connector': connector, 'app_urls': app_urls,
                                      **(self._connector_settings(connector) if enabled else {'sources': [], 'interface': '', 'service_url': ''})})
            self.web_access.save_remote(remote, expected_revision)
            self.save('remote-diagnosis', {})
            from .cloudflare_tunnel import CONNECTOR
            if connector == CONNECTOR and enabled and self.load('remote-tunnel-setup', {}):
                self._remote_setup_update('needs_route', 'Lokaler Tunnel-Zugang gespeichert. Öffentliche Cloudflare-Route mit „Verbindung prüfen“ bestätigen.')
            return self.op_remote_access()

    def op_remote_access_diagnose(self):
        from .host import run
        config = self.web_access.config()
        remote = validate_remote(config.get('remote'))
        checks = []
        if remote['enabled']:
            try:
                current = self._connector_settings(remote['connector'])
                same = all(current[key] == remote[key] for key in ('sources', 'interface', 'service_url'))
                message = 'Ziel und Docker-Netz stimmen überein.' if same else 'Das Connector-Netz hat sich geändert. Fernzugriff erneut speichern.'
            except Error as exc:
                same, message = False, str(exc)
            checks.append({'name': 'Connector-Netzwerk', 'ok': same, 'message': message})
            record = next((row for row in self.load('apps', []) if row['id'] == remote['connector']), None)
            container = self._app_container(remote['connector'], record) if record else None
            active = bool(container and container.get('State', {}).get('Running'))
            checks.append({'name': 'Connector läuft', 'ok': active if record else None, 'message': 'Container läuft. Die Tunnelverbindung wird separat durch den öffentlichen Test geprüft.' if active else 'Extern verwalteter Connector: Status nicht ermittelt.' if not record else 'Connector zuerst starten.'})
            if active:
                pid = container['State'].get('Pid')
                if type(pid) is int and pid > 0:
                    # Only the observed container PID enters a network namespace;
                    # host Python remains available even in distroless images.
                    challenge = secrets.token_hex(16)
                    expected = {'service': 'Titan', 'challenge': challenge, 'proof': proof(config)}
                    script = ('import http.client,json; c=http.client.HTTPConnection(' + repr(urllib.parse.urlsplit(remote['service_url']).hostname) + ',' + str(TUNNEL_PORT) + ',timeout=3);'
                              'c.request("GET",' + repr('/api/tunnel-health?challenge=' + challenge) + ',headers={"Host":' + repr(urllib.parse.urlsplit(remote['public_origin']).netloc) + '});r=c.getresponse();b=r.read(4097);'
                              'print("200" if r.status==200 and len(b)<=4096 and json.loads(b)==' + repr(expected) + ' else "invalid")')
                    try:
                        ok = run(['nsenter', '-t', str(pid), '-n', '--', '/usr/bin/python3', '-c', script], timeout=5).strip() == '200'
                    except Error:
                        ok = False
                    checks.append({'name': 'Titan vom Connector erreichbar', 'ok': ok, 'message': 'Lokales Tunnel-Ziel erreichbar.' if ok else 'Docker-Netz, Firewall oder Tunnel-Ziel prüfen. Fernzugriff nach Netzwerkänderungen erneut speichern.'})
        public = probe_public(config)
        checks.append({'name': 'Öffentliche HTTPS-Adresse', **public})
        result = {'checks': checks, 'checked_at': time.time(), 'revision': config['revision'],
                  'connected': public['ok'], 'message': public['message']}
        if self.web_access.config()['revision'] == config['revision']:
            self.save('remote-diagnosis', result)
            from .cloudflare_tunnel import CONNECTOR
            if (remote['enabled'] and remote['connector'] == CONNECTOR and self.load('remote-tunnel-setup', {})
                    and not getattr(self, '_remote_setup_active', False)):
                self._remote_setup_update('ready' if public['ok'] else 'needs_route',
                    'Tunnel und öffentlicher Titan-Zugang sind geprüft.' if public['ok'] else
                    'Die öffentliche Cloudflare-Route ist noch nicht bestätigt. Hostname und HTTP-Ziel im Cloudflare-Konto prüfen.')
        return result

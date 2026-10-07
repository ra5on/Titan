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
                'diagnosis': self.load('remote-diagnosis', {}) if remote['enabled'] and self.load('remote-diagnosis', {}).get('revision') == config['revision'] else {}}

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
        return result

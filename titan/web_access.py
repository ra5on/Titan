"""Root-owned web endpoint configuration with a timed, reversible changeover.

Only the local management agent writes this configuration. The unprivileged
HTTP service reads its public origins to validate Host/Origin during a change.
"""
import copy
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import threading
import time
import urllib.parse

from .core import Error, atomic_json

CONFIG = Path('/etc/titan/web-access.json')
DEFAULTS = {'mode': 'https', 'http_port': 80, 'https_port': 443}
INTERNAL_PORTS = {5001, 5101, 5102}
CONFIRM_SECONDS = 120


def validate_settings(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise Error('Protokoll, HTTP-Port und HTTPS-Port vollständig angeben.')
    if value['mode'] not in ('http', 'https'):
        raise Error('HTTP oder HTTPS auswählen.')
    for key in ('http_port', 'https_port'):
        if type(value[key]) is not int or not 1 <= value[key] <= 65535 or value[key] in INTERNAL_PORTS:
            raise Error('Einen freien Port zwischen 1 und 65535 auswählen. Interne Titan-Ports sind reserviert.')
    if value['http_port'] == value['https_port']:
        raise Error('HTTP und HTTPS benötigen unterschiedliche Ports.')
    return dict(value)


def hostname(value):
    if not isinstance(value, str) or len(value) > 253:
        raise Error('Ungültige Webadresse.')
    try:
        address = ipaddress.ip_address(value)
        if address.is_unspecified or address.is_multicast:
            raise ValueError()
        return str(address)
    except ValueError:
        if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', value) or any(not part or len(part) > 63 or part.startswith('-') or part.endswith('-') for part in value.split('.')):
            raise Error('Ungültige Webadresse.') from None
        return value.lower()


def origin(host, settings):
    host = hostname(host)
    host = '[' + host + ']' if ':' in host else host
    scheme = settings['mode']
    port = settings[scheme + '_port']
    return scheme + '://' + host + ((':' + str(port)) if port != (443 if scheme == 'https' else 80) else '')


def listen_ports(settings):
    return {settings['http_port']} | ({settings['https_port']} if settings['mode'] == 'https' else set())


def read_config(path=CONFIG):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict) or value.get('schema') != 1:
        raise Error('Ungültige Webzugriffskonfiguration.', 503)
    from .remote_access import validate_remote
    validate_remote(value.get('remote'))
    hostname(value.get('host'))
    validate_settings(value.get('settings'))
    pending = value.get('pending')
    if pending:
        if not isinstance(pending, dict) or not isinstance(pending.get('deadline'), (int, float)) or not isinstance(pending.get('previous'), dict):
            raise Error('Ungültiger Webzugriffswechsel.', 503)
        validate_settings(pending['previous'].get('settings'))
        hostname(pending['previous'].get('host'))
    return value


def allowed_origins(value):
    result = {origin(value['host'], value['settings'])}
    if value.get('pending'):
        old = value['pending']['previous']
        result.add(origin(old['host'], old['settings']))
    from .remote_access import validate_remote
    remote = validate_remote(value.get('remote'))
    if remote['enabled']:
        result.add(remote['public_origin'])
    return result


def reserved_ports(path=CONFIG):
    try:
        config = read_config(path)
        result = listen_ports(config['settings'])
        if config.get('pending'):
            result |= listen_ports(config['pending']['previous']['settings'])
        return result | INTERNAL_PORTS
    except (OSError, ValueError, Error):
        return {80, 443, 5000} | INTERNAL_PORTS


def caddy_config(value):
    """Explicit redirects retain the URI and always use the configured TLS port."""
    host, settings = hostname(value['host']), validate_settings(value['settings'])
    main = origin(host, settings)
    authority = '[' + host + ']' if ':' in host else host
    sites = {main: settings['mode']}
    if value.get('pending'):
        previous = value['pending']['previous']
        old_origin = origin(previous['host'], previous['settings'])
        # A previous HTTP endpoint becomes the new HTTPS redirect if its port
        # is reused; it must not create a duplicate Caddy listener/site.
        if old_origin != 'http://' + authority + (':' + str(settings['http_port']) if settings['http_port'] != 80 else '') or settings['mode'] != 'https':
            sites[old_origin] = previous['settings']['mode']
    result = '{\n    admin off\n    auto_https disable_redirects\n    skip_install_trust\n}\n'
    for address, scheme in sites.items():
        result += address + ' {\n'
        if scheme == 'https':
            result += '    tls internal\n'
        result += '    reverse_proxy 127.0.0.1:5001\n}\n'
    if settings['mode'] == 'https':
        authority = '[' + host + ']' if ':' in host else host
        http = 'http://' + authority + (':' + str(settings['http_port']) if settings['http_port'] != 80 else '')
        result += http + ' {\n    redir ' + main + '{uri} 308\n}\n'
    result += ('http://:5101 {\n    @office path /office/internal/*\n    handle @office {\n'
               '        reverse_proxy 127.0.0.1:5001 {\n            header_up Host ' + urllib.parse.urlsplit(main).netloc + '\n'
               '        }\n    }\n    handle {\n        respond 404\n    }\n}\n')
    from .remote_access import tunnel_caddy
    result += tunnel_caddy(value)
    return result


def initial_config(host, previous_origin=None):
    settings = dict(DEFAULTS)
    if previous_origin:
        parsed = urllib.parse.urlsplit(previous_origin)
        if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password:
            # Existing installations keep their working address until the
            # administrator chooses new ports, avoiding occupied-app lockouts.
            settings['mode'] = parsed.scheme
            settings[parsed.scheme + '_port'] = parsed.port or (443 if parsed.scheme == 'https' else 80)
            if settings['http_port'] == settings['https_port']:
                if settings['mode'] == 'https':
                    settings['http_port'] = 80 if settings['https_port'] != 80 else 8080
                else:
                    settings['https_port'] = 443 if settings['http_port'] != 443 else 8443
    return {'schema': 1, 'host': hostname(host), 'settings': validate_settings(settings), 'revision': secrets.token_hex(16)}


class WebAccess:
    def __init__(self, directory='/etc/titan', run=None, host='titan.local', clock=time.time, schedule=None, firewall=None, previous_origin=None, remote_firewall=None):
        self.directory = Path(directory)
        self.path = self.directory / 'web-access.json'
        self.run = run
        self.host = hostname(host)
        self.clock = clock
        self.lock = threading.RLock()
        self.timer = None
        self.schedule = schedule or self._schedule
        self.firewall = firewall
        self.previous_origin = previous_origin
        self.remote_firewall = remote_firewall

    @staticmethod
    def _schedule(delay, callback):
        timer = threading.Timer(delay, callback)
        timer.daemon = True
        timer.start()
        return timer

    def config(self):
        try:
            return read_config(self.path)
        except FileNotFoundError:
            # Root manager may be used on an updated/manual installation before
            # firstboot has created this file. Preserve the existing endpoint
            # and persist one revision so status/apply cannot disagree.
            self.directory.mkdir(parents=True, exist_ok=True)
            config = initial_config(self.host, self.previous_origin)
            atomic_json(self.path, config, mode=0o644)
            return config

    def status(self):
        with self.lock:
            config = self.config()
            pending = config.get('pending')
            result = {key: copy.deepcopy(config[key]) for key in ('settings', 'revision', 'host')}
            result.update(origin=origin(config['host'], config['settings']), pending=bool(pending),
                          redirect=config['settings']['mode'] == 'https',
                          certificate={'mode': 'internal', 'label': 'Automatisches lokales Titan-Zertifikat'})
            if pending:
                old = pending['previous']
                result.update(deadline=pending['deadline'], previous_origin=origin(old['host'], old['settings']),
                              confirming=pending.get('confirmed') is True)
            if config.get('last_error'):
                result['last_error'] = config['last_error']
            return result

    def _write_text(self, name, text):
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.directory / ('.' + name + '.' + secrets.token_hex(8))
        try:
            with temporary.open('x') as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o644)
            temporary.replace(self.directory / name)
        finally:
            temporary.unlink(missing_ok=True)

    def _write_runtime(self, config):
        self._write_text('Caddyfile', caddy_config(config))
        self._write_text('web.env', 'TITAN_ORIGIN=' + origin(config['host'], config['settings']) + '\n')

    def _validate(self):
        if self.run:
            self.run(['runuser', '-u', 'titan-proxy', '--', 'env', 'XDG_DATA_HOME=/var/lib/titan-proxy',
                      'XDG_CONFIG_HOME=/var/lib/titan-proxy', 'caddy', 'validate', '--config', str(self.directory / 'Caddyfile'), '--adapter', 'caddyfile'], timeout=20)

    def _restart(self):
        if self.run:
            self.run(['systemctl', 'restart', 'titan-proxy.service'], timeout=30)

    def _firewall(self, config):
        if self.remote_firewall:
            self.remote_firewall(config.get('remote'))
        ports = listen_ports(config['settings'])
        if config.get('pending'):
            ports |= listen_ports(config['pending']['previous']['settings'])
        xml = '<service><short>Titan</short><description>Titan Webzugriff</description>' + ''.join('<port protocol="tcp" port="' + str(port) + '"/>' for port in sorted(ports)) + '</service>\n'
        self._write_text('titan-firewall.xml', xml)
        if self.firewall:
            result = self.firewall([{'host': port, 'protocol': 'tcp'} for port in sorted(ports)])
            previous = config.get('pending', {}).get('previous')
            new_ports = ports - (listen_ports(previous['settings']) if previous else ports)
            if result.get('available') and not result.get('managed_rules', 0) and new_ports:
                raise Error('Kein privates LAN-Netz für die neue Webadresse erkannt. Bestehender Zugriff bleibt erhalten; Firewallzone und NAS-Netz prüfen.', 409)
            if result.get('available') and result.get('managed_rules', 0) > 0 and self.run:
                # Replace the initial service only after the bounded rules are
                # active. Never reload/flush the firewall while apps run.
                for permanent in (False, True):
                    prefix = ['firewall-cmd'] + (['--permanent'] if permanent else [])
                    listed = self.run(prefix + ['--list-services'], timeout=10)
                    if 'titan' in listed.split():
                        self.run(prefix + ['--remove-service=titan'], timeout=10)

    def _check_ports(self, settings, previous):
        if not self.run:
            return
        old_ports = listen_ports(previous['settings'])
        for port in listen_ports(settings) - old_ports:
            occupied = self.run(['ss', '-H', '-ltn', 'sport = :' + str(port)], timeout=5)
            if occupied.strip():
                raise Error('Port ' + str(port) + ' wird bereits verwendet. Einen anderen Port auswählen.', 409)
        # Do not stage HTTP and HTTPS on the same port with different protocols.
        if settings['mode'] != previous['settings']['mode']:
            old_primary = previous['settings'][previous['settings']['mode'] + '_port']
            new_primary = settings[settings['mode'] + '_port']
            if old_primary == new_primary:
                raise Error('Beim Protokollwechsel einen anderen Port wählen, damit die bisherige Adresse zur Wiederherstellung erreichbar bleibt.', 409)

    def apply(self, settings, expected_revision):
        settings = validate_settings(settings)
        with self.lock:
            old = self.config()
            if old['revision'] != expected_revision:
                raise Error('Die Webeinstellungen haben sich geändert. Ansicht aktualisieren.', 409)
            if old.get('pending'):
                raise Error('Den laufenden Adresswechsel zuerst bestätigen oder zurücknehmen.', 409)
            if old['settings'] == settings:
                return self.status()
            self._check_ports(settings, old)
            new = {**old, 'settings': settings, 'revision': secrets.token_hex(16),
                   'pending': {'previous': old, 'deadline': self.clock() + CONFIRM_SECONDS}}
            new.pop('last_error', None)
            try:
                self._write_runtime(new)
                self._validate()
                self._firewall(new)
                atomic_json(self.path, new, mode=0o644)
            except Exception:
                self._write_runtime(old)
                self._firewall(old)
                raise
            # Return the new address before restarting the reverse proxy.
            revision = new['revision']
            self.schedule(0.8, lambda: self._activate(revision))
            self._watch(new)
            return self.status()

    def save_remote(self, remote, expected_revision):
        from .remote_access import TUNNEL_PORT, validate_remote
        with self.lock:
            old = self.config()
            if old['revision'] != expected_revision or old.get('pending'):
                raise Error('Webeinstellungen geändert oder Adresswechsel aktiv. Ansicht aktualisieren.', 409)
            remote = validate_remote(remote)
            if remote['enabled'] and not old.get('remote', {}).get('enabled') and self.run:
                if self.run(['ss', '-H', '-ltn', 'sport = :' + str(TUNNEL_PORT)], timeout=5).strip():
                    raise Error('Der interne Tunnel-Port ist bereits belegt.', 409)
            new = {**old, 'remote': remote, 'revision': secrets.token_hex(16)}
            new.pop('last_error', None)
            try:
                self._write_runtime(new)
                self._validate()
                self._firewall(new)
                atomic_json(self.path, new, mode=0o644)
            except Exception:
                self._write_runtime(old)
                self._firewall(old)
                raise
            def activate():
                with self.lock:
                    if self.config()['revision'] != new['revision']:
                        return
                    try:
                        self._restart()
                    except Exception:
                        restored = {**old, 'revision': secrets.token_hex(16), 'last_error': 'Fernzugriff konnte nicht aktiviert werden. Bisherige Konfiguration wiederhergestellt.'}
                        self._write_runtime(restored)
                        atomic_json(self.path, restored, mode=0o644)
                        try:
                            self._firewall(restored)
                        except Exception:
                            restored['last_error'] += ' Firewallbereinigung fehlgeschlagen; lokalen Zugriff prüfen.'
                            atomic_json(self.path, restored, mode=0o644)
                        self._restart()
            self.schedule(0.8, activate)
            return self.status()

    def _activate(self, revision):
        with self.lock:
            current = self.config()
            if current['revision'] != revision or not current.get('pending'):
                return
            try:
                self._restart()
            except Exception as exc:
                self.rollback('Die neue Webadresse konnte nicht aktiviert werden: ' + str(exc)[:300])

    def _watch(self, config):
        if self.timer:
            self.timer.cancel()
        if config.get('pending'):
            revision = config['revision']
            self.timer = self.schedule(max(0, config['pending']['deadline'] - self.clock()), lambda: self._expire(revision))

    def resume(self):
        with self.lock:
            config = self.config()
            self._watch(config)
            if self.remote_firewall:
                self.remote_firewall(config.get('remote'))
            if config.get('pending', {}).get('confirmed'):
                self.schedule(0.8, lambda: self._activate_confirmed(config['revision']))

    def _expire(self, revision):
        with self.lock:
            current = self.config()
            if current['revision'] == revision and current.get('pending'):
                self.rollback('Die neue Adresse wurde nicht rechtzeitig bestätigt. Die vorherige Einstellung wurde wiederhergestellt.')

    def confirm(self, expected_revision, request_origin):
        with self.lock:
            current = self.config()
            if not current.get('pending') or current['revision'] != expected_revision:
                raise Error('Kein passender Adresswechsel zu bestätigen.', 409)
            if request_origin != origin(current['host'], current['settings']):
                raise Error('Die neue Webadresse öffnen und dort den Zugriff bestätigen.', 409)
            if current['pending']['deadline'] <= self.clock():
                self.rollback('Bestätigungsfrist abgelaufen.')
                raise Error('Bestätigungsfrist abgelaufen. Die vorherige Adresse ist wieder aktiv.', 409)
            if current['pending'].get('confirmed'):
                return self.status()
            final = copy.deepcopy(current)
            final.pop('pending')
            try:
                self._write_runtime(final)
                self._validate()
                self._firewall(final)
            except Exception as exc:
                # A partial cleanup must not destroy the recovery snapshot.
                diagnostics = ['Bestätigung fehlgeschlagen: ' + str(exc)[:300]]
                for restore in (lambda: self._write_runtime(current), lambda: self._firewall(current)):
                    try:
                        restore()
                    except Exception as restore_error:
                        diagnostics.append(str(restore_error)[:200])
                current['last_error'] = ' · '.join(diagnostics)
                atomic_json(self.path, current, mode=0o644)
                raise Error(current['last_error'], 503) from None
            # Keep recovery persistent until the delayed restart succeeds. The
            # response is delivered before Caddy can close its HTTP connection.
            current['pending']['confirmed'] = True
            current['pending']['deadline'] = self.clock() + 30
            current.pop('last_error', None)
            atomic_json(self.path, current, mode=0o644)
            self._watch(current)
            self.schedule(0.8, lambda: self._activate_confirmed(current['revision']))
            return self.status()

    def _activate_confirmed(self, revision):
        with self.lock:
            current = self.config()
            if current['revision'] != revision or not current.get('pending', {}).get('confirmed'):
                return
            final = copy.deepcopy(current)
            final.pop('pending')
            try:
                self._write_runtime(final)
                self._validate()
                self._restart()
                atomic_json(self.path, final, mode=0o644)
                if self.timer:
                    self.timer.cancel()
            except Exception as exc:
                current['pending'].pop('confirmed', None)
                current['last_error'] = 'Aktivierung fehlgeschlagen; bisherigen Zugriff wiederherstellen: ' + str(exc)[:300]
                for restore in (lambda: self._write_runtime(current), lambda: self._firewall(current), self._restart):
                    try:
                        restore()
                    except Exception as restore_error:
                        current['last_error'] += ' · ' + str(restore_error)[:200]
                atomic_json(self.path, current, mode=0o644)
                self._watch(current)

    def rollback(self, reason='Adresswechsel zurückgenommen.'):
        with self.lock:
            current = self.config()
            if not current.get('pending'):
                return self.status()
            previous = copy.deepcopy(current['pending']['previous'])
            previous['revision'] = secrets.token_hex(16)
            previous['last_error'] = reason
            diagnostics = []
            try:
                self._write_runtime(previous)
            except Exception as exc:
                # Keep pending when even restoring the config failed. A later
                # retry still has the complete known-working snapshot.
                current['last_error'] = reason + ' · Konfiguration konnte nicht wiederhergestellt werden: ' + str(exc)[:300]
                atomic_json(self.path, current, mode=0o644)
                try:
                    self._restart()
                except Exception:
                    pass
                raise Error(current['last_error'], 503) from None
            try:
                self._firewall(previous)
            except Exception as exc:
                diagnostics.append('Firewallbereinigung fehlgeschlagen: ' + str(exc)[:300])
            # Firewall cleanup failure must never prevent the working listener
            # from coming back. Existing scoped extra ports alone serve no app.
            try:
                self._restart()
            except Exception as exc:
                current['last_error'] = reason + ' · Bisheriger Webdienst konnte nicht starten: ' + str(exc)[:300]
                atomic_json(self.path, current, mode=0o644)
                if self.timer:
                    self.timer.cancel()
                # Persistent service failure must not create a zero-delay timer
                # loop after the original confirmation deadline has expired.
                self.timer = self.schedule(15, lambda: self._expire(current['revision']))
                raise Error(current['last_error'], 503) from None
            if diagnostics:
                previous['last_error'] += ' · ' + ' · '.join(diagnostics)
            atomic_json(self.path, previous, mode=0o644)
            if self.timer:
                self.timer.cancel()
            return self.status()


class WebAccessMixin:
    @property
    def web_access(self):
        if not hasattr(self, '_web_access'):
            from .host import run
            directory = '/etc/titan' if str(self.directory) == '/var/lib/titan-agent' else self.directory / 'web-access'
            previous_origin = os.environ.get('TITAN_ORIGIN', '')
            previous_env = Path(directory) / 'web.env'
            if not previous_origin and previous_env.is_file():
                if previous_env.stat().st_size > 8192:
                    raise Error('Die bisherige Webkonfiguration ist ungültig.', 503)
                previous_origin = next((line.split('=', 1)[1] for line in previous_env.read_text().splitlines() if line.startswith('TITAN_ORIGIN=')), '')
            host = urllib.parse.urlsplit(previous_origin).hostname or socket.gethostname()
            from .app_firewall import reconcile
            self._web_access = WebAccess(directory, run=run, host=host, previous_origin=previous_origin,
                                         firewall=lambda ports: reconcile(self, 'web', ports), remote_firewall=getattr(self, '_remote_firewall', None))
            self._web_access.resume()
        return self._web_access

    def op_web_access(self):
        return self.web_access.status()

    def op_web_access_apply(self, settings, expected_revision):
        settings = validate_settings(settings)
        from .catalog import APPS, published_ports
        from .app_networks import selection
        # Share the same reservation lock as installation and settings changes.
        # A stopped package still owns its ports for its next start.
        with self.app_config_lock:
            requested = listen_ports(settings)
            for record in self.load('apps', []):
                if record.get('id') not in APPS:
                    raise Error('Eine installierte App-Vorlage fehlt. Portbelegung zuerst prüfen.', 409)
                ports = published_ports(record['id'], record['port'], self._app_options(record['id']),
                                        host_mode=selection(record.get('network'))['mode'] == 'host')
                if requested.intersection(value['host'] for value in ports if value['protocol'] == 'tcp'):
                    raise Error('Ein gewählter Webport ist für die installierte App ' + record.get('name', record['id']) + ' reserviert. Auch gestoppte Apps behalten ihre Ports.', 409)
            return self.web_access.apply(settings, expected_revision)

    def op_web_access_confirm(self, expected_revision, request_origin):
        return self.web_access.confirm(expected_revision, request_origin)

    def op_web_access_cancel(self):
        return self.web_access.rollback()

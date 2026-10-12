"""Stateful plugin demo; never downloads binaries or changes host services."""
import hashlib
import json
import time
from .core import Error
from .remote_access import public_url
from .cloudflare_tunnel import validate_token


class DemoPluginsMixin:
    def plugins(self):
        if not hasattr(self, '_plugins'):
            self._plugins = [
                {'id': 'guacamole', 'name': 'Browser und VM-Sitzungen', 'description': 'Apache Guacamole mit einem Browser auf dem NAS.', 'installed': False, 'running': False, 'version': None, 'latest': '1.6.0-titan1', 'update_available': False, 'beta': True},
                {'id': 'cloudflare', 'name': 'Cloudflare Tunnel', 'description': 'Optionaler Debian-Dienst für den Fernzugriff.', 'installed': False, 'running': False, 'connected': False, 'version': None, 'latest': '2026.10.0', 'update_available': False, 'public_origin': '', 'service_url': 'http://127.0.0.1:5102', 'docker_installed': False, 'beta': True},
                {'id': 'nvidia', 'name': 'NVIDIA-Treiber', 'description': 'GPU-Beschleunigung für Apps.', 'installed': False, 'running': False, 'version': None, 'latest': '595.71.05', 'update_available': False, 'card': True, 'passthrough': False, 'beta': True},
            ]
        revision = hashlib.sha256(json.dumps(self._plugins, sort_keys=True).encode()).hexdigest()
        return {'demo': True, 'revision': revision, 'items': self._plugins}

    def plugin_action(self, plugin, action, expected_revision, options=None, confirmation=None):
        data = self.plugins()
        item = next((item for item in data['items'] if item['id'] == plugin), None)
        if item is None or action not in ('check', 'install', 'update', 'remove', 'start', 'stop'):
            raise Error('Unbekanntes Plugin oder ungültige Aktion.')
        if expected_revision != data['revision']: raise Error('Plugin-Stand wurde geändert.', 409)
        options = {} if options is None else options
        if not isinstance(options, dict): raise Error('Plugin-Einstellungen müssen ein Objekt sein.')
        allowed = {'token', 'public_origin', 'replace_docker'} if plugin == 'cloudflare' else {'accept_license'} if plugin == 'nvidia' else set()
        if set(options) - allowed or (action not in ('install', 'update') and options):
            raise Error('Ungültige Plugin-Einstellungen.')
        if plugin == 'nvidia' and action in ('start', 'stop'):
            raise Error('Treiber lassen sich installieren, aktualisieren oder entfernen.')
        if action in ('update', 'remove', 'start', 'stop') and not item['installed']:
            raise Error('Plugin ist nicht installiert.', 409)
        if action == 'check': item['checked_at'] = time.time()
        elif action in ('install', 'update'):
            if plugin == 'cloudflare':
                if not item['installed'] or options.get('token'): validate_token(options.get('token'))
                item['public_origin'] = public_url(options.get('public_origin') or item['public_origin'])
            elif plugin == 'nvidia' and options.get('accept_license') is not True:
                raise Error('NVIDIA-Lizenzbedingungen bestätigen.')
            version = item['version'] if plugin == 'cloudflare' and action == 'install' and item['installed'] else item['latest']
            item.update(installed=True, running=True, version=version, update_available=version != item['latest'])
        elif action == 'remove':
            if confirmation != plugin: raise Error('Deinstallation ausdrücklich bestätigen.')
            item.update(installed=False, running=False, connected=False, version=None, public_origin='')
        else: item['running'] = action == 'start'
        return {'ok': True, 'message': 'Demo: Plugin-Aktion simuliert. Keine Pakete, Dienste oder Tunnel geändert.'}

    def desktop_status(self):
        return {**next(item for item in self.plugins()['items'] if item['id'] == 'guacamole'), 'demo': True}

"""Explicitly trusted, bounded GitHub catalog imports; no arbitrary Compose execution."""
import hashlib
import json
import re
import urllib.parse
import urllib.request
from .core import Error, integer
from .catalog import APPS, catalog


def text(value, limit=200):
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(c) < 32 for c in value):
        raise Error('Katalog enthält ungültigen Text.')
    return value


def store_url(value):
    value = text(value, 1000)
    url = urllib.parse.urlsplit(value)
    if (url.scheme != 'https' or url.netloc != 'raw.githubusercontent.com' or url.query or url.fragment
            or not re.fullmatch(r'/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+\.json', url.path)
            or '..' in url.path.split('/')):
        raise Error('Direkte HTTPS-URL einer Titan-Katalogdatei auf raw.githubusercontent.com angeben.')
    return value


def recipes(document, source):
    if not isinstance(document, dict) or set(document) != {'schema', 'name', 'apps'} or document['schema'] != 1:
        raise Error('Titan-AppStore-Schema 1 benötigt: schema, name und apps. CasaOS-Archive sind noch nicht direkt kompatibel.')
    name = text(document['name'], 80)
    if not isinstance(document['apps'], list) or not 1 <= len(document['apps']) <= 100:
        raise Error('Ein Store benötigt 1 bis 100 Apps.')
    result = {}
    prefix = 's' + hashlib.sha256(source.encode()).hexdigest()[:10] + '-'
    for item in document['apps']:
        allowed = {'id', 'name', 'description', 'image', 'port', 'default_port', 'mount', 'memory', 'documentation', 'login_note', 'environment', 'config_mount', 'ports', 'settings'}
        required = {'id', 'name', 'description', 'image', 'port', 'documentation', 'login_note'}
        if not isinstance(item, dict) or set(item) - allowed or required - set(item):
            raise Error('App enthält fehlende oder nicht unterstützte Felder.')
        slug = text(item['id'], 18)
        if not re.fullmatch('[a-z][a-z0-9_-]{0,17}', slug):
            raise Error('Ungültige App-ID.')
        identifier = prefix + slug
        if identifier in result:
            raise Error('Doppelte App-ID.')
        image = text(item['image'], 250)
        if not re.fullmatch(r'[a-z0-9][a-z0-9./_-]*(?::[A-Za-z0-9_.-]+|@sha256:[a-f0-9]{64})', image):
            raise Error('Container-Image mit explizitem Tag oder SHA256-Digest angeben.')
        mount = item.get('mount', '/data')
        if mount is not None and (not isinstance(mount, str) or not re.fullmatch(r'/[a-zA-Z0-9_/-]{1,80}', mount) or mount.startswith(('/proc', '/sys', '/dev', '/etc', '/config'))):
            raise Error('Ungültiges Datenziel im Container.')
        memory = item.get('memory', '1g')
        if not isinstance(memory, str) or not re.fullmatch(r'(?:[1-9]|1[0-6])g', memory):
            raise Error('RAM-Limit muss zwischen 1g und 16g liegen.')
        documentation = text(item['documentation'], 1000)
        if not documentation.startswith('https://') or urllib.parse.urlsplit(documentation).username:
            raise Error('HTTPS-Dokumentationslink erforderlich.')
        environment = item.get('environment', {})
        if not isinstance(environment, dict) or len(environment) > 32 or any(not re.fullmatch('[A-Z_][A-Z0-9_]{0,63}', key) for key in environment):
            raise Error('Ungültige Umgebungsvariablen.')
        environment = {key: text(value, 1000).replace('$', '$$') for key, value in environment.items()}
        if type(item.get('config_mount', True)) is not bool:
            raise Error('config_mount muss true oder false sein.')
        port = integer(item['port'], 1, 65535)
        fields, extra = [], []
        ports = item.get('ports', [])
        settings = item.get('settings', [])
        if not isinstance(ports, list) or len(ports) > 8 or not isinstance(settings, list) or len(settings) > 16:
            raise Error('Maximal acht zusätzliche Ports und 16 App-Einstellungen.')
        for index, entry in enumerate(ports):
            if not isinstance(entry, dict) or set(entry) != {'target', 'published', 'protocol'} or entry['protocol'] not in ('tcp', 'udp'):
                raise Error('Port benötigt target, published und protocol (tcp oder udp).')
            target, published = integer(entry['target'], 1, 65535), integer(entry['published'], 1024, 65535)
            key = f'port_{index}'
            fields.append({'key': key, 'label': f'Port {target}/{entry["protocol"]}', 'type': 'number',
                           'default': published, 'min': 1024, 'max': 65535, 'required': True})
            extra.append({'option': key, 'target': target, 'protocol': entry['protocol']})
        for index, entry in enumerate(settings):
            if not isinstance(entry, dict) or set(entry) != {'env', 'label', 'default', 'secret'} or type(entry['secret']) is not bool:
                raise Error('App-Einstellung benötigt env, label, default und secret.')
            if not isinstance(entry['env'], str) or not re.fullmatch('[A-Z_][A-Z0-9_]{0,63}', entry['env']) or entry['env'] in {'PUID', 'PGID'}:
                raise Error('Ungültige einstellbare Umgebungsvariable.')
            if any(field.get('env') == entry['env'] for field in fields):
                raise Error('Doppelte einstellbare Umgebungsvariable.')
            default = entry['default']
            if default != '':
                text(default, 1000)
            if entry['secret'] and default:
                raise Error('Persönliche Geheimnisse dürfen nicht im öffentlichen Store vorbelegt werden.')
            fields.append({'key': f'setting_{index}', 'label': text(entry['label'], 80), 'env': entry['env'],
                           'type': 'password' if entry['secret'] else 'text', 'default': default,
                           'min_length': 1 if entry['secret'] else 0, 'max_length': 1000, 'required': True})
        result[identifier] = {'name': text(item['name'], 80), 'description': text(item['description'], 500),
            'image': image, 'port': port, 'default_port': integer(item.get('default_port', max(port, 8080)), 1024, 65535),
            'mount': mount, 'memory': memory, 'environment': environment, 'config_mount': item.get('config_mount', True),
            'category': 'Eigene Stores', 'color': '#6478db', 'symbol': '▦', 'documentation': documentation,
            'first_login': {'mode': 'setup', 'instructions': text(item['login_note'], 2000)},
            'note': text(item['login_note'], 2000), 'store_name': name, 'store_url': source,
            'install_schema': fields, 'extra_ports': extra}
    return name, result


class StoreMixin:
    def initialize_app_stores(self):
        for store in self.load('app-stores', []):
            _, parsed = recipes(store['document'], store_url(store['url']))
            APPS.update(parsed)

    def op_catalog(self):
        return catalog()

    def op_app_stores(self):
        return {'stores': [{'id': row['id'], 'name': row['name'], 'url': row['url'], 'apps': len(row['document']['apps'])}
                           for row in self.load('app-stores', [])]}

    def op_app_store_add(self, url, trusted=False):
        if trusted is not True:
            raise Error('Vertrauen in den Store ausdrücklich bestätigen.')
        url = store_url(url)
        stores = self.load('app-stores', [])
        if any(row['url'] == url for row in stores):
            raise Error('Store ist bereits hinzugefügt. Vorlagen bleiben bis zum Entfernen unverändert.', 409)
        if len(stores) >= 20:
            raise Error('Maximal 20 eigene Stores.')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise Error('Katalog-Weiterleitungen sind nicht erlaubt.')
        try:
            with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(url, headers={'User-Agent': 'Titan-AppStore/1'}), timeout=15) as response:
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise Error('Katalog ist größer als 1 MiB.')
            document = json.loads(raw)
        except (OSError, ValueError) as exc:
            raise Error('Katalog konnte nicht geladen werden: ' + type(exc).__name__) from None
        name, parsed = recipes(document, url)
        identifier = hashlib.sha256(url.encode()).hexdigest()[:10]
        self.save('app-stores', stores + [{'id': identifier, 'name': name, 'url': url, 'document': document}])
        APPS.update(parsed)
        return {'ok': True, 'name': name, 'apps': len(parsed)}

    def op_app_store_remove(self, store):
        stores = self.load('app-stores', [])
        found = next((row for row in stores if row['id'] == store), None)
        if found is None:
            raise Error('Store nicht gefunden.', 404)
        _, parsed = recipes(found['document'], found['url'])
        if any(row['id'] in parsed for row in self.load('apps', [])):
            raise Error('Zuerst die installierten Apps dieses Stores entfernen. Deren Daten bleiben erhalten.', 409)
        self.save('app-stores', [row for row in stores if row['id'] != store])
        for identifier in parsed:
            APPS.pop(identifier, None)
        return {'ok': True}

"""Validate deployment data shared by bundled and imported stores."""
import hashlib
import re
import urllib.parse
from .core import Error, integer

def text(value, limit=200):
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(c) < 32 for c in value):
        raise Error('Katalog enthält ungültigen Text.')
    return value


def recipes(document, source):
    if not isinstance(document, dict) or set(document) != {'schema', 'name', 'apps'} or document['schema'] != 1:
        raise Error('Titan-AppStore-Schema 1 benötigt: schema, name und apps. CasaOS-Archive sind noch nicht direkt kompatibel.')
    name = text(document['name'], 80)
    if not isinstance(document['apps'], list) or not 1 <= len(document['apps']) <= 400:
        raise Error('Ein Store benötigt 1 bis 400 Apps.')
    result = {}
    prefix = 's' + hashlib.sha256(source.encode()).hexdigest()[:10] + '-'
    for item in document['apps']:
        allowed = {'id', 'name', 'category', 'scheme', 'description', 'image', 'port', 'default_port', 'mount', 'memory', 'documentation', 'login_note', 'environment', 'config_mount', 'ports', 'settings','stack','stack_fields','stack_ports','default_network'}
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
        scheme = item.get('scheme', 'http')
        if scheme not in ('http', 'https'): raise Error('Web-Schema muss http oder https sein.')
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
        stack_extra = {}
        if 'stack' in item:
            from .compose_templates import validate_stack
            stack_extra = {'stack': validate_stack(item['stack'])}
            if item.get('default_network','default') not in ('default','host') or item.get('default_network')=='host' and len(item['stack']['services'])>1: raise Error('Ungültiges Standardnetz.')
            stack_extra['default_network']=item.get('default_network','default')
            # These fields are adapter-generated; validate all keys and limits.
            stack_fields=item.get('stack_fields',[])
            if not isinstance(stack_fields,list) or len(stack_fields)>64: raise Error('Zu viele Container-Einstellungen.')
            keys=set()
            for field in stack_fields:
                if not isinstance(field,dict) or set(field)-{'key','label','type','default','required','min','max','min_length','max_length'} or not re.fullmatch(r'stack_[a-zA-Z0-9_-]{1,100}',field.get('key','')) or field['key'] in keys or field.get('type') not in ('text','password','number'): raise Error('Ungültige Container-Einstellung.')
                keys.add(field['key']); text(field.get('label'),100)
                if type(field.get('required')) is not bool: raise Error('Ungültige Pflichtangabe.')
                if field['type']=='number':
                    if field.get('min')!=1024 or field.get('max')!=65535: raise Error('Ungültiger Portbereich.')
                    integer(field.get('default'),1024,65535)
                elif not isinstance(field.get('default'),str) or len(field['default'])>1000 or field.get('max_length')!=1000 or field.get('min_length') not in (0,1) or field['type']=='password' and field['default']: raise Error('Ungültige Container-Textvorgabe.')
            ports=item.get('stack_ports',[])
            if not isinstance(ports,list) or len(ports)>32 or any(not isinstance(p,dict) or set(p)!={'option','target','protocol','service'} or p['option'] not in keys or p['protocol'] not in ('tcp','udp') or p['service'] not in item['stack']['services'] for p in ports): raise Error('Ungültige Container-Verbindungsports.')
            for service in item['stack']['services'].values():
                for value in service.get('environment',{}).values():
                    if value.startswith('@option:') and value[8:] not in keys: raise Error('Container-Einstellung fehlt.')
            for mapping in ports:
                if not any(p['target']==mapping['target'] and p['protocol']==mapping['protocol'] for p in item['stack']['services'][mapping['service']].get('ports',[])): raise Error('Container-Port fehlt.')
            fields.extend(stack_fields);extra.extend(ports)
        result[identifier] = {'name': text(item['name'], 80), 'description': text(item['description'], 500),
            'image': image, 'port': port, 'scheme': scheme, 'default_port': integer(item.get('default_port', max(port, 8080)), 1024, 65535),
            'mount': mount, 'memory': memory, 'environment': environment, 'config_mount': item.get('config_mount', True),
            'category': text(item.get('category', 'LinuxServer.io' if source.startswith('https://api.linuxserver.io/') else 'Eigene Stores'), 80), 'color': '#6478db', 'symbol': '▦', 'documentation': documentation,
            'first_login': {'mode': 'documentation' if source.startswith(('https://api.linuxserver.io/', 'https://github.com/', 'https://codeload.github.com/')) else 'setup', 'instructions': text(item['login_note'], 2000), 'documentation': documentation},
            **({'upstream_name': image.split('/')[-1].split(':')[0]} if image.startswith('lscr.io/linuxserver/') else {}),
            'note': text(item['login_note'], 2000), 'store_name': name, 'store_url': source,
            'install_schema': fields, 'extra_ports': extra, **stack_extra}
    return name, result



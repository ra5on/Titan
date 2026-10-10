"""Independent reader for the public Umbrel package format.

Catalog packages are data. No exports or lifecycle hooks run on the NAS. A
pinned inventory accounts for every manifest, including packages requiring
additional runtime support; those must never become installable by omission.
"""
import copy
import base64
import hashlib
import io
import json
import posixpath
import re
import stat
import zipfile

from .core import Error

REPOSITORY = 'getumbrel/umbrel-apps'
URL = 'https://github.com/' + REPOSITORY
MAX_ARCHIVE = 32 * 1024**2
MAX_UNPACKED = 128 * 1024**2
ID = r'[a-z0-9][a-z0-9-]{0,79}'


def read_yaml(raw):
    """Bound YAML graph expansion, including legitimate Compose merge anchors."""
    import yaml
    if len(raw) > 256 * 1024:
        raise Error('App-Datei überschreitet 256 KiB.')
    class Loader(yaml.SafeLoader):
        pass
    def mapping(loader, node, deep=False):
        explicit = set()
        for key, _ in node.value:
            if key.tag == 'tag:yaml.org,2002:merge':
                continue
            value = loader.construct_object(key, deep=False)
            if not isinstance(value, (str, int, float, bool)) or value in explicit:
                raise Error('Doppelte oder ungültige YAML-Schlüssel.')
            explicit.add(value)
        loader.flatten_mapping(node)
        return dict(loader.construct_pairs(node, deep=deep))
    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    # Bound nesting before PyYAML recursively constructs the document.
    depth = aliases = nodes = 0
    try:
        for event in yaml.parse(raw):
            nodes += 1
            if isinstance(event, (yaml.events.MappingStartEvent, yaml.events.SequenceStartEvent)):
                depth += 1
            elif isinstance(event, (yaml.events.MappingEndEvent, yaml.events.SequenceEndEvent)):
                depth -= 1
            elif isinstance(event, yaml.events.AliasEvent):
                aliases += 1
            if depth > 32 or aliases > 128 or nodes > 12000:
                raise Error('App-Datei ist zu komplex.')
        value = yaml.load(raw, Loader=Loader)
        budget = [20000]
        def walk(item, parents):
            budget[0] -= 1
            if budget[0] < 0 or id(item) in parents:
                raise Error('Zyklische oder zu große YAML-Verweise.')
            if isinstance(item, (dict, list)):
                children = item.values() if isinstance(item, dict) else item
                for child in children:
                    walk(child, parents | {id(item)})
            elif item is not None and not isinstance(item, (str, int, float, bool)):
                raise Error('Nicht unterstützter YAML-Wert.')
        walk(value, set())
        if not isinstance(value, dict):
            raise Error('App-Datei muss ein Objekt enthalten.')
        return value
    except (yaml.YAMLError, RecursionError, ValueError, TypeError) as exc:
        raise Error('Ungültige App-YAML-Datei.') from exc


def installation_order(packages, requested, installed=()):
    """Topological order; missing/cyclic dependencies fail before mutations."""
    result, done = [], set(installed)
    def visit(name, parents):
        if name in parents:
            raise Error('Zyklische App-Abhängigkeit: ' + name)
        if name in done:
            return
        if name not in packages:
            raise Error('App-Abhängigkeit fehlt im Katalog: ' + str(name))
        for dependency in packages[name]['dependencies']:
            visit(dependency, parents | {name})
        done.add(name)
        result.append(name)
    for name in requested:
        visit(name, set())
    return result


def archive_inventory(raw, revision):
    if not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise Error('Umbrel-Katalog benötigt eine eindeutige Git-Version.')
    if len(raw) > MAX_ARCHIVE:
        raise Error('Umbrel-Katalog ist zu groß.')
    packages, files = {}, {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) > 20000 or sum(row.file_size for row in members) > MAX_UNPACKED:
                raise Error('Umbrel-Katalog entpackt zu groß.')
            roots = set()
            for row in members:
                parts = row.filename.rstrip('/').split('/')
                if any(part in ('', '.', '..') for part in parts) or row.filename.startswith('/') or '\\' in row.filename:
                    raise Error('Unsicherer Katalogpfad.')
                roots.add(parts[0])
                # Repository tooling is not an app package and is never consumed.
                if len(parts) > 1 and parts[1].startswith('.'):
                    continue
                mode = row.external_attr >> 16
                if stat.S_ISLNK(mode) or row.flag_bits & 1:
                    raise Error('Verknüpfte oder verschlüsselte Katalogdatei.')
                if row.is_dir():
                    continue
                path = '/'.join(parts[1:])
                if path in files:
                    raise Error('Doppelte Katalogdatei.')
                files[path] = row
            if len(roots) != 1:
                raise Error('Katalog benötigt ein eindeutiges Wurzelverzeichnis.')
            for path, row in sorted(files.items()):
                match = re.fullmatch('(' + ID + ')/umbrel-app.yml', path)
                if not match:
                    continue
                name = match[1]
                if row.file_size > 256 * 1024:
                    raise Error('App-Manifest ist zu groß.')
                metadata = read_yaml(archive.read(row))
                if metadata.get('id') != name:
                    raise Error('App-ID stimmt nicht mit dem Paketverzeichnis überein: ' + name)
                dependencies = metadata.get('dependencies', [])
                if not isinstance(dependencies, list) or len(dependencies) > 100 or any(not isinstance(x, str) or not re.fullmatch(ID, x) for x in dependencies) or len(set(dependencies)) != len(dependencies):
                    raise Error('Ungültige App-Abhängigkeiten: ' + name)
                compose_path = name + '/docker-compose.yml'
                if compose_path not in files or files[compose_path].file_size > 256 * 1024:
                    raise Error('Compose-Datei fehlt oder ist zu groß: ' + name)
                compose = read_yaml(archive.read(files[compose_path]))
                assets = {p[len(name)+1:]: {'size': item.file_size, 'sha256': hashlib.sha256(archive.read(item)).hexdigest(),
                          'content': base64.b64encode(archive.read(item)).decode('ascii'),
                          'mode': 0o755 if (item.external_attr >> 16) & 0o111 else 0o644}
                          for p, item in files.items() if p.startswith(name + '/')}
                packages[name] = {'metadata': metadata, 'compose': compose, 'dependencies': dependencies, 'files': assets}
            if not 1 <= len(packages) <= 1000:
                raise Error('Umbrel-Katalog benötigt 1 bis 1000 Apps.')
            # Check each closure, not just the selected installation.
            for name in packages:
                installation_order(packages, [name])
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise Error('Ungültiges Umbrel-Katalogarchiv.') from exc
    return {'revision': revision, 'archive_sha256': hashlib.sha256(raw).hexdigest(), 'packages': packages}


def fetch_inventory(revision=None):
    from .store_sources import download
    if revision is None:
        reference = json.loads(download('https://api.github.com/repos/' + REPOSITORY + '/git/ref/heads/master', 128 * 1024))
        revision = reference.get('object', {}).get('sha')
    if not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise Error('Umbrel-Katalogversion ist nicht eindeutig.')
    return archive_inventory(download('https://codeload.github.com/' + REPOSITORY + '/zip/' + revision, MAX_ARCHIVE), revision)


def translate(package, name):
    """Translate only complete, self-contained deployments; never drop hooks."""
    from .compose_templates import translate as translate_compose, UnsupportedTemplate
    from .store_sources import line
    meta = package['metadata']
    if str(meta.get('manifestVersion')) not in ('1', '1.0', '1.1', '1.2', '2', '2.0'):
        raise UnsupportedTemplate('Unbekannte Manifest-Version.', 'manifest_version')
    required = [p for p in package['files'] if p == 'exports.sh' or p.startswith('hooks/')]
    if required:
        raise UnsupportedTemplate('App benötigt vorbereitende Paketschritte: ' + ', '.join(required), 'package_steps')
    if package['dependencies']:
        raise UnsupportedTemplate('App benötigt gemeinsam eingerichtete Dienste: ' + ', '.join(package['dependencies']), 'app_dependencies')
    # Seeded files must be installed byte-for-byte, not replaced by directories.
    assets = [p for p, info in package['files'].items()
              if p not in ('umbrel-app.yml', 'docker-compose.yml')
              and not (p.endswith('/.gitkeep') and info['size'] == 0)]
    document = copy.deepcopy(package['compose'])
    if set(document) - {'version', 'name', 'services', 'volumes', 'networks'}:
        raise UnsupportedTemplate('Zusätzliche Compose-Funktionen erforderlich.', 'compose_features')
    services = document.get('services')
    if not isinstance(services, dict):
        raise Error('App-Dienste fehlen.')
    proxy = services.pop('app_proxy', None)
    if not isinstance(proxy, dict) or set(proxy) != {'environment'}:
        raise UnsupportedTemplate('Besonderer App-Zugang erforderlich.', 'app_proxy')
    env = proxy['environment']
    if not isinstance(env, dict) or set(env) - {'APP_HOST', 'APP_PORT', 'PROXY_AUTH_ADD'}:
        raise UnsupportedTemplate('Besondere Proxy-Konfiguration erforderlich.', 'app_proxy')
    if str(env.get('PROXY_AUTH_ADD', '')).lower() != 'false':
        raise UnsupportedTemplate('App benötigt einen durch Titan geschützten Zugang.', 'proxy_auth')
    if meta.get('requiresHttps'):
        raise UnsupportedTemplate('App benötigt einen geprüften HTTPS-Zugang.', 'https')
    if meta.get('path') not in (None, '', '/'):
        raise UnsupportedTemplate('App benötigt einen besonderen Einstiegspfad.', 'web_path')
    host = env.get('APP_HOST')
    primary = next((key for key in services if host in (key, name + '_' + key + '_1')), None)
    if primary is None:
        raise UnsupportedTemplate('App-Zieldienst ist nicht eindeutig.', 'app_proxy')
    try:
        target = int(env['APP_PORT'])
        published = int(meta['port'])
    except (TypeError, ValueError, KeyError) as exc:
        raise Error('App-Webport fehlt.') from exc
    if not 1 <= target <= 65535 or not 1024 <= published <= 65535:
        raise Error('Ungültiger App-Webport.')
    runtime_options = {}
    for key, service in services.items():
        if not isinstance(service, dict):
            raise Error('Ungültiger App-Dienst.')
        if service.get('network_mode'):
            raise UnsupportedTemplate('App benötigt einen besonderen Netzwerkzugang.', 'network')
        service.setdefault('container_name', name + '_' + key + '_1')
        # Only app-private mounts are mapped. No arbitrary host path is accepted.
        for mapping in service.get('volumes', []):
            if not isinstance(mapping, str):
                raise UnsupportedTemplate('Besondere Dateizuordnung erforderlich.', 'mount')
            source = mapping.split(':')[0]
            if not re.fullmatch(r'\$\{APP_DATA_DIR\}/[a-zA-Z0-9_./-]+', source) or '..' in source.split('/'):
                raise UnsupportedTemplate('App benötigt zusätzliche Speicherzuordnungen.', 'mount')
        environment = service.get('environment', {})
        if isinstance(environment, list):
            try: environment = dict(item.split('=', 1) for item in environment)
            except (ValueError, TypeError) as exc: raise Error('Ungültige App-Umgebung.') from exc
            service['environment'] = environment
        if isinstance(environment, dict):
            for env_key, value in environment.items():
                match = re.fullmatch(r'\$(?:\{(APP_SEED|APP_PASSWORD)\}|(APP_SEED|APP_PASSWORD))', str(value))
                if match and env_key not in ('PUID', 'PGID'):
                    kind = (match[1] or match[2]).removeprefix('APP_').lower()
                    runtime_options[(key, env_key)] = 'stack_umbrel_' + kind
                    environment[env_key] = 'titan-private-runtime-value'
        # The general Compose adapter exposes unresolved variables as inputs.
        # That is inappropriate for a seamless Umbrel install: reject instead.
        def variables(value):
            if isinstance(value, str):
                stripped = value.replace('${APP_DATA_DIR}', '').replace('$$', '')
                if re.search(r'\$(?:\{|[A-Za-z_])', stripped):
                    raise UnsupportedTemplate('App benötigt Laufzeitvariablen.', 'runtime_variables')
            elif isinstance(value, dict):
                for item in value.values(): variables(item)
            elif isinstance(value, list):
                for item in value: variables(item)
        variables(service)
    services[primary].setdefault('ports', []).append(str(published) + ':' + str(target))
    document['x-casaos'] = {'main': primary, 'port_map': str(published), 'title': meta.get('name', name), 'description': meta.get('tagline') or meta.get('description')}
    result = translate_compose(document, name, REPOSITORY)
    if runtime_options:
        for (service, key), option in runtime_options.items():
            result['stack']['services'][service]['environment'][key] = '@option:' + option
        used = {value[8:] for service in result['stack']['services'].values()
                for value in service.get('environment', {}).values() if value.startswith('@option:')}
        result['stack_fields'] = [field for field in result['stack_fields'] if field['type'] == 'number' or field['key'] in used]
        for option in sorted(set(runtime_options.values())):
            generated = option == 'stack_umbrel_seed'
            result['stack_fields'].append({'key': option, 'label': 'Interner App-Schlüssel' if generated else 'App-Passwort',
                'type': 'password', 'default': '', 'required': True, 'min_length': 12, 'max_length': 1000,
                **({'generated': True} if generated else {})})
    # Every stateful volume belongs to the app's private configuration and backup.
    # Do not redirect a database /data directory into a user-facing shared folder.
    sources = []
    for key, service in result['stack']['services'].items():
        for mount, original in zip(service.get('mounts', []), services[key].get('volumes', [])):
            source = posixpath.normpath(original.split(':')[0].removeprefix('${APP_DATA_DIR}/'))
            sources.append(source)
            # Stable across YAML service/volume reordering, shared across services,
            # and distinct when an upstream update actually changes a data path.
            mount['slot'] = 'umbrel-' + hashlib.sha256(source.encode()).hexdigest()[:20]
    if any(a != b and (a == '.' or b.startswith(a + '/')) for a in sources for b in sources):
        raise UnsupportedTemplate('Verschachtelte App-Verzeichnisse benötigen eine gemeinsame Speicherabbildung.', 'nested_mounts')
    if assets:
        from .umbrel_files import validate
        seeded = []
        for path in assets:
            owners = [source for source in sources if path == source or path.startswith(source + '/')]
            if len(set(owners)) != 1:
                raise UnsupportedTemplate('Paketdatei gehört nicht zu genau einem App-Speicher: ' + path, 'package_files')
            source = owners[0]; info = package['files'][path]
            if 'content' not in info:
                raise UnsupportedTemplate('Paketdatei fehlt im gespeicherten Katalog. Katalog erneut laden.', 'package_files')
            seeded.append({'slot': 'umbrel-' + hashlib.sha256(source.encode()).hexdigest()[:20],
                           'path': path[len(source):].lstrip('/'),
                           'sha256': info['sha256'], 'content': info['content'], 'mode': info.get('mode', 0o644)})
        # This upstream default is public. Give each fresh Donetick instance
        # its own signing identity; retained config is never rewritten.
        for row in seeded:
            if name == 'donetick' and row['path'] == 'selfhosted.yaml':
                row['personalize'] = 'yaml-jwt-secret'
        validate(seeded)
        result['seed_files'] = seeded
    if any(field['type'] != 'number' and field['key'] not in runtime_options.values() for field in result['stack_fields']):
        raise UnsupportedTemplate('App benötigt automatisch verwaltete Zugangsdaten.', 'credentials')
    result.update(version=line(meta.get('version') or 'unbekannt', 80), category=line(meta.get('category', 'Apps'), 80),
                  documentation=URL + '/tree/' + package.get('revision', 'master') + '/' + name,
                  login_note='App öffnen und die Einrichtung im Browser abschließen. ' + line(meta.get('description'), 1500))
    if 'stack_umbrel_password' in runtime_options.values():
        username = line(meta.get('defaultUsername', ''), 80)
        result['login_note'] = ('Mit ' + (username + ' und ' if username else '') +
            'dem bei der Installation gewählten App-Passwort anmelden. ' + result['login_note'])[:1900]
    return result


def compile_inventory(inventory):
    from .store_recipes import recipes
    from .store_sources import line
    accepted, blocked = [], []
    for name, original in inventory['packages'].items():
        try:
            package = {**original, 'revision': inventory['revision']}
            result = translate(package, name)
            recipes({'schema': 1, 'name': 'Umbrel', 'apps': [result]}, URL)
            accepted.append(result)
        except (Error, ValueError, KeyError, TypeError, AttributeError) as exc:
            blocked.append({'id': name, 'name': line(original['metadata'].get('name', name), 80),
                            'code': getattr(exc, 'code', 'package_format'), 'reason': line(str(exc), 500)})
    return {'schema': 1, 'name': 'Umbrel', 'apps': accepted}, blocked

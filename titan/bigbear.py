"""Runtime adapter for BigBear Dockge metadata and bounded Compose stacks.

No upstream templates or artwork are bundled with Titan. Downloads are pinned
to one Git commit; accepted recipes are then persisted by StoreMixin.
"""
import copy
import io
import json
import re
import zipfile

from .core import Error
from .store_sources import line, localized

URL = 'https://github.com/bigbeartechworld/big-bear-dockge'
REPOSITORY = 'bigbeartechworld/big-bear-dockge'


def translate(document, metadata, label):
    from .compose_templates import translate as compose_translate
    if not isinstance(document, dict) or not isinstance(metadata, dict):
        raise Error('Compose-Datei oder App-Metadaten fehlen.')
    if set(document) - {'services', 'networks', 'volumes', 'name', 'version', 'x-casaos'}:
        raise Error('Zusätzliche Compose-Funktionen benötigen eine eigene Vorlage.')
    # All services must share one private network. Never silently collapse
    # external networks, host namespaces or isolated network segments.
    networks = document.get('networks', {}) or {}
    if not isinstance(networks, dict) or len(networks) > 1:
        raise Error('Mehrere getrennte Netze benötigen eine eigene Vorlage.')
    for definition in networks.values():
        if definition and (not isinstance(definition, dict) or set(definition) - {'driver'} or definition.get('driver', 'bridge') != 'bridge'):
            raise Error('Externes oder besonderes Netzwerk nicht unterstützt.')
    used_networks = set()
    for service in (document.get('services') or {}).values():
        if not isinstance(service, dict):
            raise Error('Ungültiger Stack-Dienst.')
        value = service.get('networks', [])
        if isinstance(value, dict):
            if any(options for options in value.values()):
                raise Error('Statische Netzwerkoptionen benötigen eine eigene Vorlage.')
        elif not isinstance(value, list):
            raise Error('Ungültige Netzwerkzuordnung.')
        used_networks.update(value)
    if len(used_networks) > 1:
        raise Error('Getrennte Dienstnetze nicht unterstützt.')
    if used_networks and any(not service.get('networks') for service in document['services'].values()):
        raise Error('Gemischte Dienstnetze nicht unterstützt.')
    for definition in (document.get('volumes') or {}).values():
        if definition and (not isinstance(definition, dict) or set(definition) - {'name', 'driver'} or definition.get('driver', 'local') != 'local'):
            raise Error('Externe oder besondere Volumes nicht unterstützt.')
    source = copy.deepcopy(document)
    meta = source.setdefault('x-casaos', {})
    if not isinstance(meta, dict):
        raise Error('Ungültige App-Metadaten.')
    meta.update(title={'de_DE': line(localized(metadata.get('name')) or label, 80)},
                description={'de_DE': line(localized(metadata.get('description')))},
                port_map=str(metadata.get('port') or meta.get('port_map') or ''))
    if label == 'adguard-home':
        # A fresh AdGuard installation serves its setup wizard on port 3000.
        meta['port_map'] = '3000'
        service = next((service for service in source['services'].values() if service['image'].startswith('adguard/adguardhome:')), None)
        if service is not None:
            service.setdefault('ports', []).append('3000:3000')
    if label == 'immich':
        for service in source['services'].values():
            if service['image'].startswith('ghcr.io/immich-app/immich-server:v3.'):
                # The v3 server uses /data; the catalog still maps its v1 path.
                service['volumes'] = [mapping.replace(':/usr/src/app/upload', ':/data') if isinstance(mapping, str) else mapping for mapping in service.get('volumes', [])]
    result = compose_translate(source, label, REPOSITORY)
    if label == 'immich':
        result['stack']['services'][result['stack']['primary']]['memory'] = '2g'
    if label == 'adguard-home':
        result['login_note'] = 'Beim ersten Öffnen den Einrichtungsassistenten abschließen. Den Webport im Assistenten auf 3000 belassen oder anschließend den App-Link anpassen.'
    result['documentation'] = 'https://github.com/' + REPOSITORY + '/tree/main/Apps/' + label
    result['category'] = 'BigBear'
    return result


def archive_document(raw):
    import yaml
    apps, skipped = [], []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        files = archive.infolist()
        if len(files) > 12000 or sum(row.file_size for row in files) > 32 * 1024 ** 2:
            raise Error('BigBear-Archiv ist zu groß.')
        names = {row.filename for row in files}
        if len(names) != len(files):
            raise Error('Doppelte Archivdateien.')
        entries = {}
        for row in files:
            match = re.fullmatch(r'(?:[A-Za-z0-9_.-]+/)?(Apps/[A-Za-z0-9_-]+/(?:compose\.ya?ml|metadata\.json))', row.filename)
            if match:
                key = match[1]
                if key in entries: raise Error('Doppelte Vorlagendateien.')
                entries[key] = row
        for path, row in entries.items():
            if not path.endswith(('compose.yaml', 'compose.yml')): continue
            label = path.split('/')[1]
            try:
                metadata_path = 'Apps/' + label + '/metadata.json'
                if metadata_path not in entries or row.file_size > 128 * 1024 or entries[metadata_path].file_size > 32 * 1024:
                    raise Error('Vorlage zu groß oder Metadaten fehlen.')
                source = archive.read(row)
                if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for token in yaml.scan(source)):
                    raise Error('YAML-Verweise nicht unterstützt.')
                apps.append(translate(yaml.safe_load(source), json.loads(archive.read(entries[metadata_path])), label))
            except (Error, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError) as exc:
                skipped.append({'name': label, 'reason': line(str(exc), 200)})
    if not apps:
        raise Error('Keine unterstützten BigBear-Stacks gefunden.')
    return {'schema': 1, 'name': 'BigBear', 'apps': apps}, skipped


def fetch():
    from .store_sources import download
    reference = json.loads(download('https://api.github.com/repos/' + REPOSITORY + '/git/ref/heads/main', 128 * 1024))
    commit = reference.get('object', {}).get('sha', '')
    if not re.fullmatch('[a-f0-9]{40}', commit):
        raise Error('BigBear-Version ist nicht eindeutig.')
    # One bounded archive avoids hundreds of requests and mixed revisions.
    raw = download('https://codeload.github.com/' + REPOSITORY + '/zip/' + commit, 16 * 1024 ** 2)
    return archive_document(raw)

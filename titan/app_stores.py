"""Explicitly trusted, bounded GitHub catalog imports; no arbitrary Compose execution."""
import hashlib
import copy
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
from .core import Error, integer
from .catalog import APPS, catalog
from .store_sources import PRESETS, LINUXSERVER, fetch_document
from .store_recipes import text, recipes


def store_url(value):
    value = text(value, 1000)
    if re.fullmatch(r'https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value): return value
    if value == LINUXSERVER or re.fullmatch(r'https://codeload.github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/zip/refs/heads/[A-Za-z0-9_.-]+', value):
        return value
    url = urllib.parse.urlsplit(value)
    if (url.scheme != 'https' or url.netloc != 'raw.githubusercontent.com' or url.query or url.fragment
            or not re.fullmatch(r'/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+\.json', url.path)
            or '..' in url.path.split('/')):
        raise Error('Direkte HTTPS-URL einer Titan-Katalogdatei auf raw.githubusercontent.com angeben.')
    return value


class StoreMixin:
    def store_records(self):
        # New stack fields must never reach a previous version's startup parser.
        # Keep both old source registries intact for a system rollback.
        records = self.load('app-store-sources-v2', None)
        if records is None: records = self.load('app-store-sources', None)
        result=copy.deepcopy(records if records is not None else self.load('app-stores', []))
        for store in result:
            if 'icewhaletech/casaos-appstore' in store.get('url','').lower(): store.update(enabled=False, retired=True)
        return result

    def save_store_records(self, records):
        self.save('app-store-sources-v2', records)

    def initialize_app_stores(self):
        document = json.loads((Path(__file__).parent / 'titan-app-store.json').read_text())
        _, parsed = recipes(document, LINUXSERVER)
        for app in parsed.values(): app.update(titan_recipe=True,store_name='Titan AppStore',catalog_status='preparation')
        own=set(parsed);owned_recipes=dict(parsed)
        APPS.update(parsed)
        for store in self.store_records():
            _, parsed = recipes(store['document'], store_url(store['url']))
            for key,item in parsed.items():
                if key in own:item.update(owned_recipes[key])
            APPS.update(parsed)
            if store.get('retained'):
                _, archived = recipes({**store['document'], 'apps':store['retained']}, store['url'])
                APPS.update(archived)

    def op_catalog(self):
        result = catalog()
        installed = {row['id'] for row in self.load('apps', [])}
        result['apps'] = [app for app in result['apps'] if not app.get('store_url') or app.get('titan_recipe') or app['id'] in installed or app.get('store_url','').startswith('https://raw.githubusercontent.com/ra5on/Titan/')]
        for app in result['apps']:
            app['store_name']='Titan AppStore' if not app.get('store_url') or app.get('titan_recipe') else 'Bereits installiert'
        result['source']='Titan AppStore'
        return result

    def op_app_stores(self):
        return {'stores':[{'id':'titan','name':'Titan AppStore','enabled':True,'apps':len(self.op_catalog()['apps']),'skipped':[]}], 'presets':[]}

    def op_app_store_toggle(self, store, enabled):
        if type(enabled) is not bool:
            raise Error('Store-Auswahl ist ungültig.')
        stores = self.store_records()
        if store == 'linuxserver' and not any(row['url'] == LINUXSERVER for row in stores):
            document = json.loads((Path(__file__).parent / 'titan-app-store.json').read_text())
            stores.append({'id':'linuxserver','name':'LinuxServer.io','url':LINUXSERVER,'document':document})
        found = next((row for row in stores if row['id'] == store), None)
        if found is None: raise Error('Store nicht gefunden.', 404)
        found['enabled'] = enabled
        self.save_store_records( stores)
        return {'ok': True, 'enabled': enabled}

    def op_app_store_refresh(self, store):
        stores = self.store_records()
        found = next((row for row in stores if row['id'] == store), None)
        if store == 'linuxserver' and found is None:
            return self.op_app_store_add(LINUXSERVER, trusted=True)
        if found is None: raise Error('Store nicht gefunden.', 404)
        document, skipped = self.store_document(found['url'])
        name, parsed = recipes(document, found['url'])
        installed = {row['id'] for row in self.load('apps', [])}
        retained = []
        for app in found['document']['apps'] + found.get('retained', []):
            _, old_recipe = recipes({**found['document'], 'apps':[app]}, found['url'])
            key = next(iter(old_recipe))
            if key in installed and key not in parsed and app not in retained: retained.append(app)
        found.update(document=document, skipped=skipped, name=name, retained=retained)
        self.save_store_records( stores)
        old = {key for key, value in APPS.items() if value.get('store_url') == found['url']}
        installed = {row['id'] for row in self.load('apps', [])}
        for key in old - set(parsed) - installed:
            APPS.pop(key, None)
        APPS.update(parsed)
        return {'ok': True, 'apps': len(parsed), 'skipped': len(skipped)}

    @staticmethod
    def store_document(url):
        try:
            document, skipped = fetch_document(url)
            if url == LINUXSERVER or url.startswith(('https://codeload.github.com/', 'https://github.com/')):
                valid = []
                for app in document['apps']:
                    if url == LINUXSERVER and any(row['image'] == app['image'] and not row.get('store_url') for row in APPS.values()): continue
                    try: recipes({**document, 'apps':[app]}, url)
                    except Error as exc: skipped.append({'name': app['name'], 'reason': str(exc)})
                    else: valid.append(app)
                # Retain chosen defaults across refreshes; assign free defaults
                # to newly discovered templates without changing internal ports.
                used = {5000, 5001}
                for row in APPS.values():
                    used.add(row.get('default_port', row['port']))
                    used.update(field.get('default') for field in row.get('install_schema', []) if field['type'] == 'number')
                candidate = 18000
                prefix = 's' + hashlib.sha256(url.encode()).hexdigest()[:10] + '-'
                for app in valid:
                    previous = APPS.get(prefix + app['id'], {})
                    if previous:
                        app['default_port'] = previous['default_port']
                    else:
                        while candidate in used: candidate += 1
                        app['default_port'] = candidate
                        used.add(candidate)
                    for index, entry in enumerate(app.get('ports', [])):
                        prior = next((field for field in previous.get('install_schema', []) if field['key'] == f'port_{index}'), None)
                        if prior: entry['published'] = prior['default']
                        else:
                            while candidate in used: candidate += 1
                            entry['published'] = candidate
                            used.add(candidate)
                document['apps'] = valid
                if url == LINUXSERVER:
                    curated = {row.get('upstream_name', key) for key, row in APPS.items() if not row.get('store_url')}
                    skipped = [row for row in skipped if row['name'] not in curated]
            return document, skipped
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise Error('Store konnte nicht geladen werden: ' + type(exc).__name__) from None

    def op_app_store_add(self, url, trusted=False):
        if trusted is not True:
            raise Error('Vertrauen in den Store ausdrücklich bestätigen.')
        url = store_url(url)
        if 'icewhaletech/casaos-appstore' in url.lower(): raise Error('Der CasaOS-Store wird nicht mehr angeboten. LinuxServer.io bleibt der Standard.')
        stores = self.store_records()
        if any(row['url'] == url for row in stores):
            raise Error('Store ist bereits hinzugefügt. Vorlagen bleiben bis zum Entfernen unverändert.', 409)
        if len(stores) >= 20:
            raise Error('Maximal 20 eigene Stores.')
        document, skipped = self.store_document(url)
        name, parsed = recipes(document, url)
        identifier = hashlib.sha256(url.encode()).hexdigest()[:10]
        self.save_store_records( stores + [{'id': identifier, 'name': name, 'url': url, 'document': document, 'enabled': True, 'skipped': skipped}])
        APPS.update(parsed)
        return {'ok': True, 'name': name, 'apps': len(parsed)}

    def op_app_store_remove(self, store):
        stores = self.store_records()
        found = next((row for row in stores if row['id'] == store), None)
        if found is None:
            raise Error('Store nicht gefunden.', 404)
        if found['url'] == LINUXSERVER:
            raise Error('Der Standardstore kann deaktiviert, aber nicht entfernt werden.', 409)
        _, parsed = recipes({**found['document'], 'apps':found['document']['apps'] + found.get('retained', [])}, found['url'])
        if any(row['id'] in parsed for row in self.load('apps', [])):
            raise Error('Zuerst die installierten Apps dieses Stores entfernen. Deren Daten bleiben erhalten.', 409)
        self.save_store_records( [row for row in stores if row['id'] != store])
        for identifier in parsed:
            APPS.pop(identifier, None)
        return {'ok': True}

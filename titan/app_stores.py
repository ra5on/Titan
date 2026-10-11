"""Local app offers and read compatibility for installed legacy Compose recipes."""
import hashlib
import copy
import json
from pathlib import Path
import re
import threading
from datetime import datetime, timezone
import urllib.parse
import urllib.request
from .core import Error
from .catalog import APPS, catalog
from .store_sources import LINUXSERVER, BIGBEAR, fetch_document
from .store_recipes import text, recipes

ADAPTER_REVISION = 5

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
    def _catalog_guard(self):
        # Created lazily for small in-memory hosts used by tools/tests too.
        if not hasattr(self, '_catalog_lock'): self._catalog_lock = threading.RLock()
        return self._catalog_lock

    def _automatic_catalog_enabled(self):
        return False

    def ensure_app_catalog(self):
        # External catalog imports were retired. Startup and reads are local.
        return None

    def catalog_status(self):
        return {'state':'ready','automatic':False,'error':None,'accepted':1,
                'skipped':0,'total':1,'cached':False,'retry_at':0,'attempts':0,
                'reasons':[],'skipped_apps':[]}

    def store_records(self):
        # New stack fields must never reach a previous version's startup parser.
        # Keep both old source registries intact for a system rollback.
        records = self.load('app-store-sources-v4', None)
        if records is None: records = self.load('app-store-sources-v3', None)
        if records is None: records = self.load('app-store-sources-v2', None)
        if records is None: records = self.load('app-store-sources', None)
        result=copy.deepcopy(records if records is not None else self.load('app-stores', []))
        for store in result:
            if 'icewhaletech/casaos-appstore' in store.get('url','').lower(): store.update(enabled=False, retired=True)
        return result

    def save_store_records(self, records):
        self.save('app-store-sources-v4', records)

    def initialize_app_stores(self):
        # Read only recipes needed by already installed apps. Preserve the old
        # registries verbatim so updates and rollback never erase app data.
        installed = {row['id'] for row in self.load('apps', [])}
        bundled = json.loads((Path(__file__).parent / 'titan-app-store.json').read_text())
        _, parsed = recipes(bundled, LINUXSERVER)
        APPS.update({key:recipe for key,recipe in parsed.items() if key in installed})
        for store in self.store_records():
            document = {**store['document'], 'apps':store['document']['apps'] + store.get('retained', [])}
            # Retained recipes may repeat a current ID. Parse separately, with
            # the retained installed version winning as in earlier releases.
            for items in (store['document']['apps'], store.get('retained', [])):
                if items:
                    _, parsed = recipes({**document,'apps':items}, store_url(store['url']))
                    APPS.update({key:recipe for key,recipe in parsed.items() if key in installed})
        from .app_credentials import private_recipe
        for key, recipe in self.load('installed-app-recipes-v1', {}).items():
            if key in installed:
                APPS[key] = private_recipe(recipe)
        from .native_catalog import load_ci_fixtures
        load_ci_fixtures(self)
        from .umbrel_store import load, activate
        _, offers = load(self)
        activate(self, offers)

    def op_catalog(self):
        with self._catalog_guard():
            result = catalog()
            installed = {row['id'] for row in self.load('apps', [])}
            result['installed_recipes'] = [app for app in catalog(include_legacy=True)['apps'] if app['id'] in installed]
            result['store_status'] = self.catalog_status()
            result['skipped'] = []
            from .umbrel_store import status
            result['umbrel'] = status(self)
        return result

    def op_app_stores(self):
        return {'stores':[{'id':'titan','name':'Titan Apps','enabled':True,'apps':len(catalog()['apps']),'skipped':[]}],
                'presets':[],'catalog_status':self.catalog_status()}

    def _legacy_app_store_toggle(self, store, enabled):
        if type(enabled) is not bool:
            raise Error('Store-Auswahl ist ungültig.')
        with self._catalog_guard():
            stores = self.store_records()
            if store == 'linuxserver' and not any(row['url'] == LINUXSERVER for row in stores):
                document = json.loads((Path(__file__).parent / 'titan-app-store.json').read_text())
                stores.append({'id':'linuxserver','name':'LinuxServer.io','url':LINUXSERVER,'document':document})
            found = next((row for row in stores if row['id'] == store), None)
            if found is None and store == 'bigbear' and not enabled:
                state = self.load('app-store-bootstrap-v1', {})
                self.save('app-store-bootstrap-v1', {**state,'disabled':True,'state':'disabled'})
                return {'ok':True,'enabled':False}
            if found is not None:
                found['enabled'] = enabled
                self.save_store_records(stores)
                if found['url'] == BIGBEAR:
                    state = self.load('app-store-bootstrap-v1', {})
                    self.save('app-store-bootstrap-v1', {**state, 'disabled':not enabled})
        if found is None and store == 'bigbear' and enabled:
            return self._legacy_app_store_add(BIGBEAR, trusted=True)
        if found is None: raise Error('Store nicht gefunden.', 404)
        return {'ok': True, 'enabled': enabled}

    def _legacy_app_store_refresh(self, store):
        stores = self.store_records()
        found = next((row for row in stores if row['id'] == store), None)
        if store == 'linuxserver' and found is None:
            return self._legacy_app_store_add(LINUXSERVER, trusted=True)
        if store == 'bigbear' and found is None:
            return self._legacy_app_store_add(BIGBEAR, trusted=True)
        if found is None: raise Error('Store nicht gefunden.', 404)
        document, skipped = self.store_document(found['url'])
        name, parsed = recipes(document, found['url'])
        with self._catalog_guard(), getattr(self,'app_config_lock',self._catalog_guard()):
            stores = self.store_records()
            found = next((row for row in stores if row['id'] == store), None)
            if found is None: raise Error('Store wurde während der Aktualisierung entfernt.', 409)
            installed = {row['id'] for row in self.load('apps', [])}
            retained = []
            for app in found['document']['apps'] + found.get('retained', []):
                _, old_recipe = recipes({**found['document'], 'apps':[app]}, found['url'])
                key = next(iter(old_recipe))
                if key in installed and app not in retained: retained.append(app)
            found.update(document=document, skipped=skipped, name=name, retained=retained, loaded_at=datetime.now(timezone.utc).isoformat(), adapter_revision=ADAPTER_REVISION)
            self.save_store_records(stores)
            old = {key for key, value in APPS.items() if value.get('store_url') == found['url']}
            for key in old - set(parsed) - installed: APPS.pop(key, None)
            for app in retained:
                _, frozen = recipes({**found['document'], 'apps':[app]}, found['url'])
                parsed.update(frozen)
            snapshots = self.load('installed-app-recipes-v1', {})
            from .app_credentials import private_recipe
            parsed.update({key:private_recipe(recipe) for key,recipe in snapshots.items() if key in installed and recipe.get('store_url') == found['url']})
            APPS.update(parsed)
        return {'ok': True, 'apps': len(parsed), 'skipped': len(skipped)}

    @staticmethod
    def store_document(url, *, bigbear_revision=None):
        try:
            if bigbear_revision is not None:
                if url != BIGBEAR: raise Error('Eine feste BigBear-Version ist nur für den BigBear-Katalog zulässig.')
                from .bigbear import fetch
                document, skipped = fetch(bigbear_revision)
            else:
                document, skipped = fetch_document(url)
            if url == LINUXSERVER or url.startswith(('https://codeload.github.com/', 'https://github.com/')):
                valid = []
                for app in document['apps']:
                    if url == LINUXSERVER and any(row['image'] == app['image'] and not row.get('store_url') for row in APPS.values()): continue
                    try: recipes({**document, 'apps':[app]}, url)
                    except Error as exc: skipped.append({'name': app['name'], 'reason': str(exc),'code':getattr(exc,'code','template_format'),'requirements':getattr(exc,'requirements',[])})
                    else: valid.append(app)
                document['apps'] = valid
                if url == LINUXSERVER:
                    curated = {row.get('upstream_name', key) for key, row in APPS.items() if not row.get('store_url')}
                    skipped = [row for row in skipped if row['name'] not in curated]
            return document, skipped
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise Error('Store konnte nicht geladen werden: ' + type(exc).__name__) from None

    def _legacy_app_store_add(self, url, trusted=False):
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
        identifier = 'bigbear' if url == BIGBEAR else hashlib.sha256(url.encode()).hexdigest()[:10]
        with self._catalog_guard(), getattr(self,'app_config_lock',self._catalog_guard()):
            stores = self.store_records()
            already = next((row for row in stores if row['url'] == url), None)
            if already is not None:
                # An automatic download completed while the explicit fetch ran.
                return {'ok':True,'name':already['name'],'apps':len(already['document']['apps']),'skipped':len(already.get('skipped',[]))}
            self.save_store_records(stores + [{'id': identifier, 'name': name, 'url': url, 'document': document, 'enabled': True, 'skipped': skipped, 'loaded_at':datetime.now(timezone.utc).isoformat(), 'adapter_revision':ADAPTER_REVISION}])
            if url == BIGBEAR:
                state = self.load('app-store-bootstrap-v1', {})
                self.save('app-store-bootstrap-v1', {**state,'state':'ready','disabled':False,'error':None})
            APPS.update(parsed)
        return {'ok': True, 'name': name, 'apps': len(parsed), 'skipped':len(skipped)}

    def _legacy_app_store_remove(self, store):
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
        if found['url'] == BIGBEAR:
            state = self.load('app-store-bootstrap-v1', {})
            self.save('app-store-bootstrap-v1', {**state,'disabled':True,'state':'disabled'})
        for identifier in parsed:
            APPS.pop(identifier, None)
        return {'ok': True}

    def op_app_store_add(self, url, trusted=False):
        raise Error('Externe AppStores wurden entfernt. Nutze die eigenen Titan-Apps.', 410)

    def op_app_store_refresh(self, store):
        if store == 'umbrel':
            from .umbrel_store import refresh
            return refresh(self)
        raise Error('Externe AppStores wurden entfernt. Nutze die eigenen Titan-Apps.', 410)

    def op_app_store_toggle(self, store, enabled):
        raise Error('Externe AppStores wurden entfernt. Nutze die eigenen Titan-Apps.', 410)

    def op_app_store_remove(self, store):
        raise Error('Externe AppStores wurden entfernt. Bestehende Apps bleiben in Docker verwaltbar.', 410)

"""Explicitly trusted, bounded GitHub catalog imports; no arbitrary Compose execution."""
import hashlib
import copy
import json
from pathlib import Path
import re
import threading
import time
from collections import Counter
from datetime import datetime, timezone
import urllib.parse
import urllib.request
from .core import Error, integer
from .catalog import APPS, catalog
from .store_sources import PRESETS, LINUXSERVER, BIGBEAR, fetch_document
from .store_recipes import text, recipes

ADAPTER_REVISION = 4

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
        # Development/demo/test hosts must never contact external services merely
        # by being constructed. Production starts the same non-blocking worker
        # on agent startup and on catalog reads; custom hosts can opt in.
        return getattr(self, 'catalog_auto_bootstrap', getattr(self, 'directory', None) == Path('/var/lib/titan-agent'))

    def ensure_app_catalog(self):
        if not self._automatic_catalog_enabled(): return
        if getattr(self, 'directory', None) and (self.directory / 'config-restore.lock').exists(): return
        with self._catalog_guard():
            found = next((row for row in self.store_records() if row.get('url') == BIGBEAR), None)
            state = self.load('app-store-bootstrap-v1', {})
            if state.get('disabled') or found and (not found.get('enabled', True) or found.get('adapter_revision') == ADAPTER_REVISION):
                return
            if getattr(self, '_catalog_worker', None) and self._catalog_worker.is_alive(): return
            now = time.time()
            # At most three automatic attempts in one day, including restarts.
            attempts = state.get('attempts', 0) if now - state.get('attempted_at', 0) < 86400 else 0
            if attempts >= 3 or now < state.get('retry_at', 0): return
            self.save('app-store-bootstrap-v1', {**state, 'state':'loading', 'attempts':attempts+1, 'attempted_at':now, 'error':None})
            self._catalog_worker = threading.Thread(target=self._bootstrap_app_catalog, name='titan-catalog-bootstrap', daemon=True)
            self._catalog_worker.start()

    def _bootstrap_app_catalog(self):
        try:
            document, skipped = self.store_document(BIGBEAR)
            name, parsed = recipes(document, BIGBEAR)
            with self._catalog_guard():
                state = self.load('app-store-bootstrap-v1', {})
                stores = self.store_records()
                # A user may disable/remove the source while it is downloading.
                existing = next((row for row in stores if row.get('url') == BIGBEAR), None)
                if state.get('disabled') or existing and (not existing.get('enabled',True) or existing.get('adapter_revision') == ADAPTER_REVISION): return
                if getattr(self, 'directory', None) and (self.directory / 'config-restore.lock').exists(): return
                loaded_at = datetime.now(timezone.utc).isoformat()
                # Serialize the short write with app recipe/config publication,
                # never hold that lock during the network download.
                lock = getattr(self, 'app_config_lock', self._catalog_guard())
                with lock:
                    record = {'id':'bigbear','name':name,'url':BIGBEAR,'document':document,'enabled':True,'skipped':skipped,'loaded_at':loaded_at,'adapter_revision':ADAPTER_REVISION}
                    if existing:
                        installed_ids = {row['id'] for row in self.load('apps', [])}
                        retained = []
                        for item in existing['document']['apps'] + existing.get('retained', []):
                            _, previous = recipes({**existing['document'],'apps':[item]}, BIGBEAR)
                            if set(previous) & installed_ids and item not in retained: retained.append(item)
                        record['retained'] = retained
                        stores = [record if row.get('url') == BIGBEAR else row for row in stores]
                    else: stores = stores + [record]
                    self.save_store_records(stores)
                    installed = {row['id'] for row in self.load('apps', [])}
                    present = {key for key, recipe in APPS.items() if recipe.get('store_url') == BIGBEAR}
                    for key in present - set(parsed) - installed: APPS.pop(key, None)
                    APPS.update({key: recipe for key, recipe in parsed.items() if key not in installed})
                self.save('app-store-bootstrap-v1', {**state,'state':'ready','error':None,'retry_at':0,'last_success':loaded_at})
        except Exception as exc:
            with self._catalog_guard():
                state = self.load('app-store-bootstrap-v1', {})
                attempts = state.get('attempts', 1)
                delay = 60 if attempts == 1 else 300
                message = str(exc) if isinstance(exc, Error) else 'Katalog nicht erreichbar (' + type(exc).__name__ + ').'
                self.save('app-store-bootstrap-v1', {**state,'state':'error','error':message[:300], 'retry_at':time.time()+delay})
                if attempts < 3 and not state.get('disabled'):
                    timer = threading.Timer(delay, self.ensure_app_catalog)
                    timer.daemon = True
                    self._catalog_retry = timer
                    timer.start()

    def catalog_status(self):
        state = self.load('app-store-bootstrap-v1', {})
        found = next((row for row in self.store_records() if row.get('url') == BIGBEAR), None)
        skipped = found.get('skipped', []) if found else []
        accepted = len(found.get('document', {}).get('apps', [])) if found else 0
        labels = {'permissions':'Zusätzliche Berechtigungen oder Geräte','host_mount':'Zugriff auf Hostdateien oder Docker-Socket','runtime_options':'Zusätzliche Laufzeitoptionen','network':'Besondere Netzwerkeinrichtung','ports':'Besondere Portzuordnung','web_port':'Webzugang nicht eindeutig','container_user':'Container-Benutzer muss aufgelöst werden','dependencies':'Besondere Dienstabhängigkeiten','template_format':'Vorlagenformat benötigt Anpassung','unsupported':'Weitere Einrichtung erforderlich'}
        counts = Counter(row.get('code','template_format') for row in skipped)
        status = state.get('state','idle') if not found or found.get('adapter_revision') != ADAPTER_REVISION and state.get('state') in ('loading','error') else 'ready'
        if state.get('disabled') or found and not found.get('enabled',True): status = 'disabled'
        return {'state':status,'automatic':True,'error':state.get('error') if status=='error' else None,
                'last_success':found.get('loaded_at') if found else state.get('last_success'),
                'attempts':state.get('attempts',0),'accepted':accepted,'skipped':len(skipped),'total':accepted+len(skipped),
                'cached':bool(found),
                'retry_at':state.get('retry_at',0) if status=='error' else 0,
                'reasons':[{'code':code,'reason':labels.get(code,code),'count':count} for code,count in counts.most_common()],
                'skipped_apps':skipped}

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

        installed = {row['id'] for row in self.load('apps', [])}
        from .app_credentials import private_recipe
        for key, recipe in self.load('installed-app-recipes-v1', {}).items():
            if key in installed: APPS[key] = private_recipe(recipe)
        self.ensure_app_catalog()

    def op_catalog(self):
        self.ensure_app_catalog()
        with self._catalog_guard():
            result = catalog()
            enabled = {row['url'] for row in self.store_records() if row.get('enabled', True)}
            result['apps'] = [app for app in result['apps'] if not app.get('imported_stack') or app.get('store_url') in enabled]
            installed = {row['id'] for row in self.load('apps', [])}
            result['installed_recipes'] = [app for app in catalog(include_legacy=True)['apps'] if app['id'] in installed]
            result['store_status'] = self.catalog_status()
            result['skipped'] = result['store_status']['skipped_apps']
        return result

    def op_app_stores(self):
        self.ensure_app_catalog()
        return {'stores':[{'id':'titan','name':'Titan AppStore','enabled':True,'apps':len(catalog()['apps']),'skipped':[]}] + [{'id':row['id'],'name':row['name'],'url':row['url'],'enabled':row.get('enabled',True),'apps':len(row['document']['apps']),'skipped':row.get('skipped',[])} for row in self.store_records()], 'presets':PRESETS, 'catalog_status':self.catalog_status()}

    def op_app_store_toggle(self, store, enabled):
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
            return self.op_app_store_add(BIGBEAR, trusted=True)
        if found is None: raise Error('Store nicht gefunden.', 404)
        return {'ok': True, 'enabled': enabled}

    def op_app_store_refresh(self, store):
        stores = self.store_records()
        found = next((row for row in stores if row['id'] == store), None)
        if store == 'linuxserver' and found is None:
            return self.op_app_store_add(LINUXSERVER, trusted=True)
        if store == 'bigbear' and found is None:
            return self.op_app_store_add(BIGBEAR, trusted=True)
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
        if found['url'] == BIGBEAR:
            state = self.load('app-store-bootstrap-v1', {})
            self.save('app-store-bootstrap-v1', {**state,'disabled':True,'state':'disabled'})
        for identifier in parsed:
            APPS.pop(identifier, None)
        return {'ok': True}

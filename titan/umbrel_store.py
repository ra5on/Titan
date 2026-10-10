"""Persist and expose Umbrel catalog offers without replacing installed recipes."""
import copy
from datetime import datetime, timezone

from .core import Error
from .umbrel_catalog import URL, compile_inventory, fetch_inventory
from .store_recipes import recipes

CACHE = 'umbrel-catalog-v1'


def load(host):
    saved = host.load(CACHE, None)
    if saved is None:
        return None, {}
    if not isinstance(saved, dict) or saved.get('schema') != 1:
        raise Error('Gespeicherter Umbrel-Katalog ist ungültig.')
    document = saved.get('document')
    parsed = recipes(document, URL)[1] if document and document.get('apps') else {}
    for recipe in parsed.values():
        recipe.update(umbrel_catalog=True, catalog_revision=saved['revision'])
    return saved, parsed


def activate(host, parsed):
    from .catalog import APPS
    host._umbrel_offer_ids = frozenset(parsed)
    installed = {row['id'] for row in host.load('apps', [])}
    stale = {key for key, recipe in APPS.items() if recipe.get('umbrel_catalog')}
    for key in stale - set(parsed) - installed:
        APPS.pop(key, None)
    # Installed snapshots remain authoritative until an explicit update.
    APPS.update({key: recipe for key, recipe in parsed.items() if key not in installed})


def refresh(host):
    inventory = fetch_inventory()
    document, blocked = compile_inventory(inventory)
    saved = {'schema': 1, 'revision': inventory['revision'],
             'archive_sha256': inventory['archive_sha256'], 'document': document,
             'blocked': blocked, 'total': len(inventory['packages']),
             'loaded_at': datetime.now(timezone.utc).isoformat()}
    parsed = recipes(document, URL)[1] if document['apps'] else {}
    for recipe in parsed.values():
        recipe.update(umbrel_catalog=True, catalog_revision=saved['revision'])
    with host._catalog_guard(), getattr(host, 'app_config_lock', host._catalog_guard()):
        host.save(CACHE, saved)
        activate(host, parsed)
    return {'ok': True, 'apps': len(parsed), 'blocked': len(blocked), 'revision': saved['revision']}


def status(host):
    saved = host.load(CACHE, None)
    if not saved:
        return {'id': 'umbrel', 'name': 'Umbrel', 'loaded': False, 'apps': 0,
                'total': 0, 'blocked': [], 'url': URL}
    return {'id': 'umbrel', 'name': 'Umbrel', 'loaded': True, 'url': URL,
            'revision': saved['revision'], 'loaded_at': saved['loaded_at'],
            'apps': len(saved['document']['apps']), 'total': saved['total'],
            'blocked': copy.deepcopy(saved['blocked'])}


def update_offer(host, app):
    """Image updates preserve storage, network, settings and service identities.

    Package topology migrations need a separate migration contract. Never move
    an existing database to a freshly generated mount slot during an update.
    """
    from .catalog import APPS
    current = APPS.get(app, {})
    if not current.get('umbrel_catalog'):
        return None
    _, offers = load(host)
    target = offers.get(app)
    if target is None:
        raise Error('Diese App ist im aktuellen Katalog nicht für Updates verfügbar.', 409)
    def layout(recipe):
        stack = copy.deepcopy(recipe['stack'])
        for service in stack['services'].values():
            service.pop('image', None)
        return {key: recipe.get(key) for key in ('port', 'install_schema', 'extra_ports', 'default_network', 'mount', 'config_mount', 'memory')}, stack
    if layout(current) != layout(target):
        raise Error('Das Appupdate verändert Speicher oder Einrichtung und benötigt noch eine geprüfte Migration.', 409)
    return target

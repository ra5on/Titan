"""Per-account appearance of the interface: transparency, dock and start page."""
import re
from .core import Error

TOOLS = ('home', 'store', 'files', 'vms', 'settings')
WIDGETS = ('cpu', 'ram', 'storage')
SIZES = ('small', 'medium', 'large')
# Dock and start page entries: a built-in tool, an installed app or a virtual machine.
ENTRY = re.compile(r'(?:tool:(?:home|store|files|vms|settings)|app:[a-zA-Z0-9_-]{1,64}|vm:[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})\Z')
DEFAULT = {'transparency': 40, 'dock_size': 'medium', 'dock': ['tool:' + name for name in TOOLS],
           'widgets': list(WIDGETS), 'hidden_apps': [], 'pinned_vms': []}


def _entries(value, limit, pattern, message):
    if (not isinstance(value, list) or len(value) > limit or len(set(value)) != len(value)
            or any(not isinstance(item, str) or not pattern.fullmatch(item) for item in value)):
        raise Error(message)
    return list(value)


def validate(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULT):
        raise Error('Unbekannte Darstellungseinstellung.')
    result = {**DEFAULT, **value}
    if type(result['transparency']) is not int or not 0 <= result['transparency'] <= 100:
        raise Error('Transparenz muss zwischen 0 und 100 liegen.')
    if result['dock_size'] not in SIZES:
        raise Error('Ungültige Dock-Größe.')
    result['dock'] = _entries(result['dock'], 16, ENTRY, 'Ungültige oder doppelte Dock-Einträge.')
    # Settings must stay reachable, otherwise the dock could not be restored.
    if 'tool:settings' not in result['dock']:
        raise Error('Die Einstellungen müssen im Dock bleiben.')
    if (not isinstance(result['widgets'], list) or len(set(result['widgets'])) != len(result['widgets'])
            or any(item not in WIDGETS for item in result['widgets'])):
        raise Error('Ungültige Widget-Auswahl.')
    result['widgets'] = list(result['widgets'])
    result['hidden_apps'] = _entries(result['hidden_apps'], 128, re.compile(r'[a-zA-Z0-9_-]{1,64}\Z'), 'Ungültige App-Auswahl.')
    result['pinned_vms'] = _entries(result['pinned_vms'], 32, re.compile(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\Z'), 'Ungültige VM-Auswahl.')
    return result


def load(store, user):
    try:
        return validate(store.config('interface-layout:' + user, {}))
    except (Error, ValueError, TypeError):
        return validate({})


def save(store, user, value):
    result = validate(value)
    store.set_config('interface-layout:' + user, result)
    return result

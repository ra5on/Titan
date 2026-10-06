"""Small dashboard preferences scoped to the authenticated web account."""
from .core import Error

TILES = ("tools", "storage", "resources", "health", "apps", "shares", "vms")


def layout_key(username):
    return "dashboard-layout:" + username


def normalize_order(value):
    if (not isinstance(value, list) or len(value) > len(TILES)
            or any(not isinstance(item, str) or item not in TILES for item in value)
            or len(set(value)) != len(value)):
        raise Error("Ungültige Dashboard-Kacheln oder doppelte Kacheln.")
    return value + [item for item in TILES if item not in value]


def load_layout(store, username):
    try:
        value = store.config(layout_key(username), {})
        order = normalize_order(value.get("order", []))
    except (Error, ValueError, TypeError, AttributeError):
        order = list(TILES)
        value = {}
    result = {"order": order}
    for key in ("hidden", "wide"):
        if isinstance(value, dict) and key in value:
            try: result[key] = validate_subset(value[key])
            except Error: result[key] = []
    if isinstance(value, dict) and 'sizes' in value:
        try: result['sizes'] = validate_sizes(value['sizes'])
        except Error: result['sizes'] = {}
    return result


def validate_sizes(value):
    if not isinstance(value, dict) or len(value)>len(TILES): raise Error('Ungültige Kachelgrößen.')
    for key, size in value.items():
        if key not in TILES or not isinstance(size, dict) or set(size)!={'columns','height'} or type(size['columns']) is not int or not 1<=size['columns']<=4 or type(size['height']) is not int or not 0<=size['height']<=1600: raise Error('Ungültige Kachelgröße.')
    return value


def validate_subset(value):
    if not isinstance(value,list) or len(value)>len(TILES) or any(not isinstance(item,str) or item not in TILES for item in value) or len(set(value))!=len(value): raise Error("Ungültige Kachelauswahl.")
    return value


def save_layout(store, username, value):
    if not isinstance(value, dict) or "order" not in value or set(value) - {"order","hidden","wide","sizes"}:
        raise Error("Nur die Reihenfolge der Dashboard-Kacheln angeben.")
    result = {"order": normalize_order(value["order"])}
    for key in ("hidden", "wide"):
        if key in value: result[key] = validate_subset(value[key])
    if 'sizes' in value: result['sizes'] = validate_sizes(value['sizes'])
    store.set_config(layout_key(username), result)
    return result

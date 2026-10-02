"""Small dashboard preferences scoped to the authenticated web account."""
from .core import Error

TILES = ("storage", "resources", "health", "apps", "shares", "vms")


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
    return {"order": order}


def save_layout(store, username, value):
    if not isinstance(value, dict) or set(value) != {"order"}:
        raise Error("Nur die Reihenfolge der Dashboard-Kacheln angeben.")
    result = {"order": normalize_order(value["order"])}
    store.set_config(layout_key(username), result)
    return result

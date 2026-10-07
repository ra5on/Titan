"""Version app state without teaching an older system new recipe semantics.

The v1 files remain an intentionally restricted view for rollback. New apps
whose network/permissions/headless features need the new parser stay in v2.
No containers or app data are changed by this metadata compatibility layer.
"""
import copy
import json
from pathlib import Path
import re

from .core import atomic_json
from .app_credentials import private_recipe


def legacy_recipe(value):
    """Return an old-parser-compatible snapshot, or None (fail closed)."""
    if not isinstance(value, dict) or value.get('web_available') is False or value.get('web_host_ip'):
        return None
    recipe = copy.deepcopy(value)
    recipe.pop('web_available', None)
    recipe.pop('web_host_ip', None)
    if not isinstance(recipe.get('port'), int) or recipe['port'] < 1:
        return None
    if any(mapping.get('host_ip') for mapping in recipe.get('extra_ports', [])):
        return None
    stack = recipe.get('stack')
    if not stack:
        return recipe
    if not isinstance(stack, dict) or set(stack) != {'primary', 'services'} or not isinstance(stack['services'], dict) or not 1 <= len(stack['services']) <= 8:
        return None
    allowed = {'image','environment','mounts','command','entrypoint','depends_on','ports','healthcheck','memory','shm_size','user','aliases'}
    for service in stack['services'].values():
        if not isinstance(service, dict): return None
        # Explicitly spelling the old managed default needs no newer behavior.
        if service.get('restart') == 'unless-stopped': service.pop('restart')
        if set(service) - allowed: return None
        if len(service.get('aliases', [])) > 4 or len(service.get('mounts', [])) > 16 or len(service.get('ports', [])) > 16: return None
        if len(service.get('depends_on', [])) > 8: return None
        if any(set(mapping) != {'target','published','protocol'} for mapping in service.get('ports', [])): return None
        if any(not isinstance(service[key], str) or not re.fullmatch(r'[1-9][0-9]{0,3}[mg]', service[key]) for key in ('memory','shm_size') if key in service): return None
        if 'user' in service and not re.fullmatch(r'[0-9]{1,9}(?::[0-9]{1,9})?', service['user']): return None
        health = service.get('healthcheck')
        if health is not None:
            if not isinstance(health, dict) or set(health) - {'test','interval','timeout','start_period','retries'}: return None
            if not isinstance(health.get('test'), list) or any(not isinstance(part, str) or len(part)>1000 for part in health['test']): return None
            if any(not re.fullmatch(r'[1-9][0-9]{0,3}(?:ms|s|m|h)', str(health[key])) for key in ('interval','timeout','start_period') if key in health): return None
            if 'retries' in health and (type(health['retries']) is not int or not 1 <= health['retries'] <= 20): return None
    from .compose_templates import validate_stack
    from .core import Error
    try: validate_stack(stack)
    except (Error, ValueError, KeyError, TypeError, AttributeError): return None
    return recipe


def _read(path, default):
    return json.loads(path.read_text()) if path.exists() else copy.deepcopy(default)


def _newer(legacy, modern):
    return legacy.exists() and modern.exists() and legacy.stat().st_mtime_ns > modern.stat().st_mtime_ns


def _recipe_registry(directory):
    return load_state(directory, 'installed-app-recipes-v1', {})


def _compatible_ids(directory, candidates):
    from .catalog import APPS
    snapshots = _recipe_registry(directory)
    recipes = {**APPS, **snapshots}
    return {key for key in candidates if key in recipes and legacy_recipe(recipes[key]) is not None}


def load_state(directory, name, default):
    directory = Path(directory)
    if name in ('installed-app-recipes-v1', 'installed-app-recipes-v2'):
        modern, legacy = directory/'installed-app-recipes-v2.json', directory/'installed-app-recipes-v1.json'
        if not modern.exists(): return {key:private_recipe(value) for key,value in _read(legacy, default).items()}
        values = _read(modern, default)
        if _newer(legacy, modern):
            old = _read(legacy, {})
            # Old images can install/remove compatible applications. Keep their
            # changed snapshots while retaining definitions only v2 understands.
            values = {key:value for key,value in values.items() if legacy_recipe(value) is None}
            values.update({key:value for key,value in old.items() if legacy_recipe(value) is not None})
        return {key:private_recipe(value) for key,value in values.items()}
    if name in ('apps', 'apps-v2'):
        modern, legacy = directory/'apps-v2.json', directory/'apps.json'
        if not modern.exists(): return _read(legacy, default)
        values = _read(modern, default)
        if _newer(legacy, modern):
            old = _read(legacy, [])
            compatible = _compatible_ids(directory, {row.get('id') for row in values + old})
            values = [row for row in values if row.get('id') not in compatible]
            values.extend(row for row in old if row.get('id') in compatible)
        return values
    return _read(directory/(name+'.json'), default)


def save_state(directory, name, value):
    directory = Path(directory)
    if name in ('installed-app-recipes-v1', 'installed-app-recipes-v2'):
        old = {key:recipe for key,raw in value.items() if (recipe:=legacy_recipe(raw)) is not None}
        # Publish the old readable view first. A restart between these atomic
        # writes is reconciled as a legacy change on the next new-image read.
        atomic_json(directory/'installed-app-recipes-v1.json', old)
        atomic_json(directory/'installed-app-recipes-v2.json', value)
        return
    if name in ('apps', 'apps-v2'):
        compatible = _compatible_ids(directory, {row.get('id') for row in value})
        atomic_json(directory/'apps.json', [row for row in value if row.get('id') in compatible])
        atomic_json(directory/'apps-v2.json', value)
        return
    atomic_json(directory/(name+'.json'), value)

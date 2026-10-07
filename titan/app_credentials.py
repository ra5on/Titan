"""Infer private option metadata without modifying installed container settings."""
import copy
import re


def secret_name(value):
    return isinstance(value, str) and bool(re.search(
        r'password|passphrase|secret|token|api.?key|(?:^|_)(?:pass|passwd|credentials)(?:_|$)', value, re.I))


def private_recipe(value):
    """Repair older adapter descriptors so API settings/logs hide credentials.

    Saved option values and the Compose stack stay unchanged. In particular,
    loading an installed snapshot must never rotate a running app's password.
    """
    if not isinstance(value, dict): return value
    recipe = copy.deepcopy(value)
    private = set()
    for service in recipe.get('stack', {}).get('services', {}).values():
        for key, env in service.get('environment', {}).items():
            if secret_name(key) and isinstance(env, str) and env.startswith('@option:'):
                private.add(env[8:])
    for field in recipe.get('install_schema', []):
        label = str(field.get('label', '')).split(' · ', 1)[0]
        if field.get('type') == 'password' or field.get('key') in private or any(secret_name(field.get(key)) for key in ('key', 'env')) or secret_name(label):
            field.update(type='password', default='')
            if 'display_default' in field: field['display_default'] = ''
    return recipe

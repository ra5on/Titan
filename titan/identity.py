"""User groups, explicit overrides and application authorization.

Host identity metadata is authoritative for SMB. The web database stores the
same validated policy for immediate server-side application authorization.
"""
import copy
import hashlib
import json
from .core import Error, configuration_lock, identifier, user_profile_text

APPLICATIONS = {'files': 'Dateimanager', 'apps': 'Apps und Docker', 'vms': 'Virtuelle Maschinen', 'backups': 'Datensicherung'}
DEFAULT_APPLICATIONS = {'files': True, 'apps': False, 'vms': False, 'backups': False}


def policy_revision(policy):
    return hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def empty_policy():
    return {'schema': 1, 'groups': [], 'users': {}}


def validate_policy(value, users, shares):
    if not isinstance(value, dict) or set(value) != {'schema', 'groups', 'users'} or value['schema'] != 1:
        raise Error('Ungültige Gruppen- und Berechtigungskonfiguration.')
    names = {item['name'] for item in users}
    share_names = {item['name'] for item in shares}
    if not isinstance(value['groups'], list) or len(value['groups']) > 100 or not isinstance(value['users'], dict) or set(value['users']) - names:
        raise Error('Unbekannte Benutzer oder zu viele Gruppen.')
    def rights(item):
        if not isinstance(item, dict) or set(item) - {'applications', 'shares'}:
            raise Error('Ungültige Berechtigungen.')
        apps, folders = item.get('applications', {}), item.get('shares', {})
        if not isinstance(apps, dict) or set(apps) - set(APPLICATIONS) or any(type(permission) is not bool for permission in apps.values()):
            raise Error('Anwendungsrechte müssen Schalter sein.')
        if not isinstance(folders, dict) or set(folders) - share_names or any(permission not in ('none', 'read', 'write') for permission in folders.values()):
            raise Error('Ungültige Freigaberechte.')
        return {'applications': dict(apps), 'shares': dict(folders)}
    result = empty_policy()
    seen = set()
    for group in value['groups']:
        if not isinstance(group, dict) or set(group) - {'name', 'description', 'members', 'applications', 'shares'}:
            raise Error('Ungültige Gruppe.')
        name = identifier(group.get('name'))
        members = group.get('members', [])
        if name in seen or not isinstance(members, list) or len(members) > 1000 or any(not isinstance(member, str) or member not in names for member in members):
            raise Error('Gruppenname doppelt oder Mitglied unbekannt.')
        seen.add(name)
        result['groups'].append({'name': name, 'description': user_profile_text(group.get('description', ''), 'description'), 'members': sorted(set(members)), **rights({key: group[key] for key in ('applications', 'shares') if key in group})})
    result['users'] = {name: rights(item) for name, item in value['users'].items()}
    return result


def effective_application(policy, name, application):
    direct = policy.get('users', {}).get(name, {}).get('applications', {})
    if application in direct:
        return {'allowed': direct[application], 'source': 'Benutzer', 'inherited': False}
    groups = [group for group in policy.get('groups', []) if name in group['members'] and application in group.get('applications', {})]
    # Any group denial takes precedence; an explicit user override is visible.
    if groups:
        allowed = all(group['applications'][application] for group in groups)
        return {'allowed': allowed, 'source': ', '.join(group['name'] for group in groups), 'inherited': True}
    return {'allowed': DEFAULT_APPLICATIONS[application], 'source': 'Standard', 'inherited': True}


def effective_share(policy, name, share, system_user=None):
    direct = policy.get('users', {}).get(name, {}).get('shares', {})
    if share['name'] in direct:
        return {'permission': direct[share['name']], 'source': 'Benutzer', 'inherited': False}
    groups = [group for group in policy.get('groups', []) if name in group['members'] and share['name'] in group.get('shares', {})]
    if groups:
        permissions = [group['shares'][share['name']] for group in groups]
        permission = 'none' if 'none' in permissions else 'write' if 'write' in permissions else 'read'
        return {'permission': permission, 'source': ', '.join(group['name'] for group in groups), 'inherited': True}
    system_user = system_user or name
    permission = 'write' if system_user in share.get('writers', []) else 'read' if system_user in share.get('readers', []) else 'none'
    return {'permission': permission, 'source': 'Freigabe', 'inherited': True}


def permissions(store, user):
    if user.get('role') == 'admin':
        return {application: {'allowed': True, 'source': 'Administrator', 'inherited': True} for application in APPLICATIONS}
    policy = store.config('identity', empty_policy())
    return {application: effective_application(policy, user['name'], application) for application in APPLICATIONS}


def require_application(store, user, application):
    try:
        current = store.user_record(user['name'])
    except Error as error:
        if error.status == 404:
            raise Error('Berechtigung ist nicht mehr gültig.', 403) from None
        raise
    if not current['enabled'] or not permissions(store, current)[application]['allowed']:
        raise Error(f'Kein Zugriff auf {APPLICATIONS[application]}.', 403)
    return current


class Identity:
    def __init__(self, store, agent, demo=False):
        self.store, self.agent, self.demo = store, agent, demo

    def overview(self):
        users, shares = self.store.users(), self.agent.call('shares')
        policy = self.store.config('identity', empty_policy())
        baseline = self.agent.call('identity_baseline')
        homes = self.agent.call('identity_homes')
        def share_right(user, share):
            owner = next((name for name, home in homes.items() if home['share'] == share['name']), None)
            if owner:
                return {'permission': 'write' if user['system_user'] == owner else 'none', 'source': 'Persönlicher Ordner', 'inherited': True}
            return effective_share(policy, user['name'], baseline.get(share['name'], share), user['system_user'])
        return {'policy': policy, 'revision': policy_revision(policy), 'homes': homes, 'applications': APPLICATIONS, 'users': users, 'shares': shares,
                'effective': {user['name']: {'applications': permissions(self.store, user),
                    'shares': {share['name']: share_right(user, share) for share in shares}} for user in users},
                'capabilities': self.agent.call('identity_capabilities')}

    def apply(self, actor, value):
        with configuration_lock(self.store.directory), self.store.lock:
            current = self.store.user_record(actor)
            if not current['enabled'] or current['role'] != 'admin':
                raise Error('Administratorrechte erforderlich.', 403)
            value = copy.deepcopy(value)
            expected = value.pop('expected_revision', None) if isinstance(value, dict) else None
            if expected is not None and expected != policy_revision(self.store.config('identity', empty_policy())):
                raise Error('Gruppenrechte wurden inzwischen geändert. Ansicht aktualisieren und Änderungen erneut prüfen.', 409)
            users = self.store.users()
            policy = validate_policy(value, users, self.agent.call('shares'))
            old = self.store.config('identity', empty_policy())
            # The host independently validates managed identities before touching ACLs.
            self.agent.call('identity_apply', policy=policy, users=[{'name': item['name'], 'system_user': item['system_user']} for item in users])
            try:
                self.store.set_config('identity', policy)
            except Exception:
                self.agent.call('identity_apply', policy=old, users=[{'name': item['name'], 'system_user': item['system_user']} for item in users])
                raise
            # Permissions are re-evaluated on every request and inside queued actions.
            self.store.audit(actor, 'identity_update')
            return {'ok': True}

    def remove_user(self, name):
        policy = copy.deepcopy(self.store.config('identity', empty_policy()))
        policy['users'].pop(name, None)
        for group in policy['groups']:
            group['members'] = [member for member in group['members'] if member != name]
        self.store.set_config('identity', policy)

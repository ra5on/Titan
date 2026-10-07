"""Root boundary for group ACL materialization, personal folders and ZFS quotas."""
import hashlib
import re
import shutil
from .core import Error, identifier, integer
from .identity import APPLICATIONS, effective_share, empty_policy, validate_policy


class IdentityHostMixin:
    def op_delegated_backup(self, action, user, arguments):
        operation = action
        from .backup_authorization import host_call
        return host_call(self, operation, identifier(user), arguments)

    def op_identity_capabilities(self):
        return {'groups': True, 'homes': True, 'quota_backends': ['zfs'] if shutil.which('zfs') else [],
                'quota_notice': 'Benutzerquoten werden für verwaltete ZFS-Datasets angeboten. Ext4/XFS benötigen aktivierte und geprüfte Kernel-Quoten und werden derzeit nicht angeboten.',
                'applications': APPLICATIONS}

    def identity_baseline(self):
        baseline = self.load('identity-baseline', {})
        changed = False
        for share in self.op_shares():
            if share['name'] not in baseline:
                baseline[share['name']] = {'name': share['name'], 'readers': list(share['readers']), 'writers': list(share['writers'])}
                changed = True
        if changed:
            self.save('identity-baseline', baseline)
        return baseline

    def op_identity_baseline(self):
        with self.account_lock:
            return self.identity_baseline()

    def op_identity_apply(self, policy, users):
        if not isinstance(users, list) or len(users) > 1000 or any(not isinstance(user, dict) or set(user) != {'name', 'system_user'} for user in users):
            raise Error('Ungültige Benutzerzuordnung.')
        with self.account_lock:
            seen = set()
            for user in users:
                identifier(user['name']); identifier(user['system_user'])
                if user['name'] in seen:
                    raise Error('Benutzerzuordnung ist doppelt.')
                seen.add(user['name'])
                if user['system_user'] != 'titan-files':
                    self.managed_account(user['system_user'])
            shares = self.op_shares()
            policy = validate_policy(policy, users, shares)
            # A legacy web user's service UID is never assigned group/personal rights.
            legacy = {user['name'] for user in users if user['system_user'] == 'titan-files'}
            if any(name in legacy and item.get('shares') for name, item in policy['users'].items()) or any(set(group['members']) & legacy and group['shares'] for group in policy['groups']):
                raise Error('Ältere Dienstidentitäten benötigen zuerst einen persönlichen SMB-Zugang.')
            baseline = self.identity_baseline()
            homes = self.load('identity-homes', {})
            private_shares = {home['share'] for home in homes.values()}
            if any(set(group['shares']) & private_shares for group in policy['groups']) or any(set(item['shares']) & private_shares for item in policy['users'].values()):
                raise Error('Persönliche Ordner haben feste private Rechte und werden nicht über Gruppen verteilt.')
            old = self.load('identity', empty_policy())
            changed = []
            try:
                for share in shares:
                    readers = [member for member in baseline[share['name']]['readers'] if member == 'titan-files' or member not in {user['system_user'] for user in users}]
                    writers = [member for member in baseline[share['name']]['writers'] if member == 'titan-files' or member not in {user['system_user'] for user in users}]
                    home_owner = next((name for name, item in homes.items() if item['share'] == share['name']), None)
                    if home_owner:
                        readers, writers = [], []
                    for user in users:
                        if user['system_user'] == 'titan-files':
                            continue
                        permission = 'write' if user['system_user'] == home_owner else 'none' if home_owner else effective_share(policy, user['name'], baseline[share['name']], user['system_user'])['permission']
                        if permission == 'write': writers.append(user['system_user'])
                        elif permission == 'read': readers.append(user['system_user'])
                    readers, writers = sorted(set(readers)-set(writers)), sorted(set(writers))
                    if readers != share['readers'] or writers != share['writers']:
                        self._update_share_rights(share['name'], readers, writers)
                        changed.append(share)
                self.save('identity', policy)
                self.save('identity-users', users)
            except Exception:
                failures = []
                for share in reversed(changed):
                    try: self._update_share_rights(share['name'], share['readers'], share['writers'])
                    except Exception: failures.append(share['name'])
                if failures:
                    raise Error('Gruppenrechte konnten nicht vollständig zurückgesetzt werden. Betroffene Freigaben prüfen: '+', '.join(failures), 500) from None
                self.save('identity', old)
                raise
            return {'ok': True, 'updated_shares': [share['name'] for share in changed]}

    def identity_direct_permission(self, share, user, permission):
        # Existing per-user editors become explicit overrides, never inherited grants.
        policy = self.load('identity', empty_policy())
        web_name = next((item['name'] for item in self.load('identity-users', []) if item['system_user'] == user), None)
        if web_name is not None:
            policy.setdefault('users', {}).setdefault(web_name, {'applications': {}, 'shares': {}}).setdefault('shares', {})[share] = permission
            self.save('identity', policy)
        baseline = self.identity_baseline()
        record = baseline[share]
        record['readers'] = [name for name in record['readers'] if name != user]
        record['writers'] = [name for name in record['writers'] if name != user]
        if permission == 'read': record['readers'].append(user)
        elif permission == 'write': record['writers'].append(user)
        self.save('identity-baseline', baseline)

    def identity_remove_account(self, name):
        policy = self.load('identity', empty_policy())
        web_name = next((item['name'] for item in self.load('identity-users', []) if item['system_user'] == name), name)
        policy['users'].pop(web_name, None)
        for group in policy['groups']:
            group['members'] = [member for member in group['members'] if member != web_name]
        self.save('identity-users', [item for item in self.load('identity-users', []) if item['system_user'] != name])
        self.save('identity', policy)
        baseline = self.load('identity-baseline', {})
        for share in baseline.values():
            for field in ('readers', 'writers'):
                share[field] = [member for member in share[field] if member != name]
        self.save('identity-baseline', baseline)
        for key in ('identity-homes', 'identity-quotas'):
            records = self.load(key, {})
            records.pop(name, None)
            self.save(key, records)

    def identity_remove_share(self, name):
        policy = self.load('identity', empty_policy())
        for group in policy['groups']:
            group['shares'].pop(name, None)
        for user in policy['users'].values():
            user['shares'].pop(name, None)
        self.save('identity', policy)
        baseline = self.load('identity-baseline', {})
        baseline.pop(name, None)
        self.save('identity-baseline', baseline)
        homes = self.load('identity-homes', {})
        self.save('identity-homes', {user: home for user, home in homes.items() if home['share'] != name})
        datasets = {share.get('dataset') for share in self.op_shares() if share.get('dataset')}
        quotas = self.load('identity-quotas', {})
        self.save('identity-quotas', {user: {dataset: limit for dataset, limit in limits.items() if dataset in datasets} for user, limits in quotas.items()})

    def op_identity_homes(self):
        return self.load('identity-homes', {})

    def op_identity_home(self, name):
        name = identifier(name)
        with self.account_lock:
            record, account = self.managed_account(name)
            if not record['enabled']:
                raise Error('Persönliche Ordner erfordern ein aktives Benutzerkonto.')
            homes = self.load('identity-homes', {})
            if name in homes:
                share = next((item for item in self.op_shares() if item['name'] == homes[name]['share']), None)
                if not share:
                    raise Error('Persönlicher Ordner fehlt; gespeicherte Daten zuerst prüfen.', 409)
                return {'ok': True, **homes[name]}
            share_name = 'home-' + name[:18] + '-' + hashlib.sha256(name.encode()).hexdigest()[:6]
            self.op_share_create(share_name, [], [name])
            share = next(item for item in self.op_shares() if item['name'] == share_name)
            homes[name] = {'share': share_name, 'path': share['path'], 'user': name}
            self.save('identity-homes', homes)
            return {'ok': True, **homes[name]}

    def quota_targets(self):
        if not shutil.which('zfs'):
            return []
        targets = {}
        for share in self.op_shares():
            dataset = share.get('dataset')
            if not dataset or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:/-]{0,255}', dataset):
                continue
            try:
                kind = self.command(['zfs', 'get', '-H', '-o', 'value', 'type', dataset]).strip()
                if kind != 'filesystem': continue
            except Error:
                continue
            targets[dataset] = {'id': dataset, 'label': share['name'], 'path': share['path'], 'backend': 'zfs', 'supported': True}
        return list(targets.values())

    def op_user_quotas(self, name):
        _, account = self.managed_account(name)
        targets = []
        for target in self.quota_targets():
            try:
                values = self.command(['zfs', 'get', '-H', '-p', '-o', 'value', f'userused@{account.pw_uid},userquota@{account.pw_uid}', target['id']]).strip().splitlines()
                if len(values) != 2 or not values[0].isdigit() or (values[1] != 'none' and not values[1].isdigit()):
                    raise Error('ZFS-Quotenstatus ist ungültig.')
                targets.append({**target, 'used_bytes': int(values[0]), 'limit_bytes': 0 if values[1] == 'none' else int(values[1])})
            except Error as exc:
                targets.append({**target, 'supported': False, 'error': str(exc)})
        return {'name': name, 'targets': targets, 'notice': self.op_identity_capabilities()['quota_notice']}

    def op_user_quota(self, name, target, limit_bytes):
        _, account = self.managed_account(name)
        if type(limit_bytes) is not int or not isinstance(target, str):
            raise Error('Speicherlimit muss eine ganze Byteanzahl sein.')
        limit_bytes = integer(limit_bytes, 0, 2**63-1)
        if target not in {item['id'] for item in self.quota_targets()}:
            raise Error('Quoten sind nur auf vorhandenen verwalteten ZFS-Datasets verfügbar.', 409)
        self.command(['zfs', 'set', f'userquota@{account.pw_uid}={limit_bytes if limit_bytes else "none"}', target])
        actual = self.op_user_quotas(name)
        saved = next(item for item in actual['targets'] if item['id'] == target)
        if not saved['supported'] or saved['limit_bytes'] != limit_bytes:
            raise Error('ZFS hat die Benutzerquote nicht bestätigt.', 503)
        settings = self.load('identity-quotas', {})
        settings.setdefault(name, {})[target] = limit_bytes
        self.save('identity-quotas', settings)
        return {'ok': True, 'quota': saved}

    def _restore_user_quota(self, name, target, limit_bytes, known_targets):
        """Restore properties from validated backup/previous metadata only.

        A removed share can still have its earlier quota on the retained dataset;
        this private helper allows clearing it without publishing an HTTP/RPC op.
        """
        name=identifier(name)
        if target not in known_targets or not isinstance(target,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:/-]{0,255}',target) or type(limit_bytes) is not int or not 0<=limit_bytes<2**63:
            raise Error('Ungültige gesicherte Quotenänderung.')
        _,account=self.managed_account(name)
        if self.command(['zfs','get','-H','-o','value','type',target]).strip()!='filesystem':
            raise Error('Gesichertes ZFS-Dataset ist nicht verfügbar.',409)
        self.command(['zfs','set',f'userquota@{account.pw_uid}={limit_bytes if limit_bytes else "none"}',target])
        value=self.command(['zfs','get','-H','-p','-o','value',f'userquota@{account.pw_uid}',target]).strip()
        if (0 if value in ('none','-') else integer(value,0,2**63-1))!=limit_bytes:
            raise Error('Gesicherte ZFS-Quote wurde nicht bestätigt.',503)

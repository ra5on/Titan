"""Identity and security routes with authorization at both HTTP and job execution."""
from http.cookies import SimpleCookie
from .core import Error
from .identity import APPLICATIONS, require_application, permissions


READ_APPLICATIONS = {
    '/api/catalog': 'apps', '/api/apps': 'apps', '/api/app-details': 'apps', '/api/app-networks': 'apps',
    '/api/app-devices': 'apps', '/api/app-metrics': 'apps', '/api/docker-engine': 'apps',
    '/api/docker-metrics': 'apps', '/api/docker-container': 'apps',
    '/api/vms': 'vms', '/api/vm-usb': 'vms', '/api/vm-options': 'vms', '/api/vm-image-info': 'vms',
    '/api/isos': 'vms', '/api/iso-library': 'vms', '/api/vm-console': 'vms', '/api/vnc': 'vms',
    '/api/managed-shares': 'backups', '/api/backups': 'backups', '/api/backup/settings': 'backups', '/api/backup/browse': 'backups',
    '/api/package-logs': 'apps', '/api/package-details': 'apps', '/api/package-diagnose': 'apps', '/api/vm-extensions': 'vms',
}


def operation_application(operation):
    if not isinstance(operation, str):
        return None
    if operation.startswith(('docker_', 'app_', 'package_')) and not operation.startswith('app_store_'):
        return 'apps'
    if operation.startswith(('vm_', 'iso_')):
        return 'vms'
    if operation in ('backup_create', 'backup_verify', 'backup_restore', 'backup_restore_selection'):
        return 'backups'
    return None


class IdentityHTTPMixin:
    def application_route(self, user, path):
        if path in ('/api/storage-locations', '/api/status'):
            candidates = ('apps', 'vms', 'backups') if path == '/api/storage-locations' else ('apps', 'vms')
            for candidate in candidates:
                if permissions(self.app.store, user)[candidate]['allowed']:
                    require_application(self.app.store, user, candidate)
                    return True
            return False
        application = READ_APPLICATIONS.get(path)
        if application:
            require_application(self.app.store, user, application)
            return True
        return False

    def identity_get(self, path, user, query):
        if path == '/api/security/login-protection':
            self.require_user(admin=True)
            if query: raise Error('Anmeldeschutz unterstützt keine Optionen.')
            self.reply(self.app.security.login_protection.overview(user['name']))
            return True
        if path == '/api/permissions':
            self.reply({'applications': permissions(self.app.store, user)})
            return True
        if path == '/api/identity':
            self.require_user(admin=True)
            if query: raise Error('Benutzerübersicht unterstützt keine Optionen.')
            self.reply(self.app.identity.overview())
            return True
        if path == '/api/identity/home':
            require_application(self.app.store, user, 'files')
            homes = self.app.agent.call('identity_homes')
            self.reply({'home': homes.get(user['system_user']), 'legacy': user['system_user'] == 'titan-files'})
            return True
        if path == '/api/identity/quotas':
            self.require_user(admin=True)
            if set(query) != {'name'}: raise Error('Benutzer auswählen.')
            record = self.app.store.user_record(query['name'])
            if record['system_user'] == 'titan-files': raise Error('Dienstidentitäten erhalten keine persönliche Quote.', 409)
            self.reply(self.app.agent.call('user_quotas', name=record['system_user']))
            return True
        if path == '/api/security':
            if set(query) - {'all'} or query.get('all', '0') not in ('0', '1'): raise Error('Ungültige Sicherheitsoption.')
            all_users = query.get('all') == '1'
            if all_users: self.require_user(admin=True)
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            token = cookie['titan_session'].value if 'titan_session' in cookie else ''
            data = self.app.security.overview(user['name'], token, all_users)
            data['checks'] = [
                {'id': 'https', 'ok': bool(self.app.origin and self.app.origin.startswith('https://')), 'label': 'Verschlüsselte Webverbindung', 'action': 'HTTPS beim NAS-Zugang einrichten.'},
                {'id': 'two_factor', 'ok': data['two_factor'], 'label': 'Zwei-Faktor-Anmeldung', 'action': 'Authenticator-App einrichten und Wiederherstellungscodes sicher speichern.'},
                {'id': 'recovery', 'ok': not data['two_factor'] or data['recovery_remaining'] > 2, 'label': 'Wiederherstellungscodes verfügbar', 'action': 'Neue Wiederherstellungscodes erzeugen.'}]
            self.reply(data)
            return True
        return False

    def identity_post(self, path, user, body):
        if path == '/api/security/login-protection':
            self.require_user(admin=True)
            if set(body) != {'settings', 'expected_revision'}: raise Error('Einstellungen und aktuellen Stand angeben.')
            self.reply(self.app.security.login_protection.save(user['name'], body['settings'], body['expected_revision']))
            return True
        if path == '/api/security/login-protection/unblock':
            self.require_user(admin=True)
            if set(body) != {'id'}: raise Error('Anmeldesperre auswählen.')
            self.reply(self.app.security.login_protection.unblock(user['name'], body['id']))
            return True
        if path == '/api/identity':
            self.require_user(admin=True)
            self.reply(self.app.jobs.submit(user['name'], 'identity_update', lambda: self.app.identity.apply(user['name'], body), security=True), 202)
            return True
        if path == '/api/identity/home':
            if set(body) - {'name'}: raise Error('Ungültige Ordneroption.')
            require_application(self.app.store, user, 'files')
            name = body.get('name', user['name'])
            if name != user['name']: self.require_user(admin=True)
            def create():
                current = self.app.store.user_record(user['name'])
                require_application(self.app.store, current, 'files')
                if name != user['name'] and current['role'] != 'admin': raise Error('Administratorrechte erforderlich.', 403)
                target = self.app.store.user_record(name)
                if target['system_user'] == 'titan-files': raise Error('Zuerst einen persönlichen SMB-Zugang einrichten.', 409)
                return self.app.agent.call('identity_home', name=target['system_user'])
            self.reply(self.app.jobs.submit(user['name'], 'identity_home', create, security=True), 202)
            return True
        if path == '/api/identity/quotas':
            self.require_user(admin=True)
            if set(body) != {'name', 'target', 'limit_bytes'}: raise Error('Benutzer, Speicherbereich und Limit angeben.')
            target = self.app.store.user_record(body['name'])
            self.reply(self.app.jobs.submit(user['name'], 'user_quota', lambda: self.app.admin_action(user['name'], 'user_quota', {'name': target['system_user'], 'target': body['target'], 'limit_bytes': body['limit_bytes']}), security=True), 202)
            return True
        if path == '/api/security/sessions/revoke':
            if set(body) != {'id'}: raise Error('Sitzung auswählen.')
            self.reply(self.app.security.revoke(user['name'], body['id'], admin=user['role'] == 'admin'))
            return True
        if not path.startswith('/api/security/'):
            return False
        functions = {'/api/security/totp/begin': (self.app.security.begin, {'password'}),
                     '/api/security/totp/confirm': (self.app.security.confirm, {'password', 'code'}),
                     '/api/security/totp/disable': (self.app.security.disable, {'password', 'code'}),
                     '/api/security/recovery': (self.app.security.recoveries, {'password', 'code'})}
        if path in functions:
            function, fields = functions[path]
            if set(body) != fields: raise Error('Aktuelles Passwort und gegebenenfalls Sicherheitscode angeben.')
            self.app.rate_limit(self.authentication_address())
            arguments = dict(body)
            if path in ('/api/security/totp/confirm', '/api/security/totp/disable'):
                cookie = SimpleCookie(self.headers.get('Cookie', ''))
                arguments['current_token'] = cookie['titan_session'].value if 'titan_session' in cookie else None
            self.reply(function(user['name'], **arguments))
            return True
        return False

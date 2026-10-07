"""First-party Compose installation journals; never persist public credentials."""
import hashlib
import json
import secrets
import threading
import time

from .core import Error, atomic_json

STEPS = [('docker', 'Docker prüfen'), ('files', 'Dateien, Token und Compose erstellen'),
         ('pull', 'Container-Image laden'), ('create', 'Container erstellen'),
         ('start', 'Container starten'), ('connection', 'Cloudflare-Verbindung prüfen'),
         ('proxy', 'Lokalen Tunnel-Zugang einrichten'), ('public_check', 'Öffentlichen Zugang prüfen')]
_LOCAL = threading.local()


def validate_app(app):
    from .cloudflare_tunnel import CONNECTOR
    if app != CONNECTOR:
        raise Error('Diese App ist nicht für den eigenen Titan-Installer freigegeben.', 404)
    return app


def validate_options(options):
    from .cloudflare_tunnel import validate_token
    from .remote_access import public_url
    if not isinstance(options, dict) or set(options) - {'tunnel_token', 'public_origin'} or 'tunnel_token' not in options:
        raise Error('Tunnel-Token und optional die öffentliche HTTPS-Adresse angeben.')
    token = validate_token(options['tunnel_token'])
    address = options.get('public_origin', '')
    if not isinstance(address, str):
        raise Error('Die öffentliche HTTPS-Adresse muss Text sein.')
    return {'tunnel_token': token, 'public_origin': public_url(address) if address else ''}


def progress(host, app, step, status='running', message=''):
    """Only this thread's accepted installer may report command completion."""
    context = getattr(_LOCAL, 'installation', None)
    if context and context['host'] is host and context['app'] == app and not context.get('suspended'):
        host._installation_step(app, step, status, message)


def suspend_progress(host):
    context = getattr(_LOCAL, 'installation', None)
    if context and context['host'] is host:
        context['suspended'] = True


def active_install(host, app):
    context = getattr(_LOCAL, 'installation', None)
    return bool(context and context['host'] is host and context['app'] == app and
                context['operation'] == 'install' and not context.get('suspended'))


class AppInstallationMixin:
    def _installation_path(self, app, private=False):
        validate_app(app)
        parent = self.directory / 'app-installations'
        if parent.exists() or parent.is_symlink():
            import os
            import stat
            metadata = parent.lstat()
            if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022):
                raise Error('Installationsverzeichnis ist nicht geschützt.', 503)
        return parent / (app + ('.inputs.json' if private else '.json'))

    def _installation_read(self, app):
        path = self._installation_path(app)
        if not path.exists():
            return {'schema': 1, 'app': app, 'revision': 'initial', 'status': 'idle', 'operation': 'install',
                    'installation': '', 'current_step': '', 'started_at': None, 'finished_at': None,
                    'updated_at': None, 'message': '', 'steps': [dict(id=key, label=label, status='pending',
                    message='', started_at=None, finished_at=None) for key, label in STEPS]}
        try:
            if path.is_symlink() or not path.is_file():
                raise ValueError()
            value = json.loads(path.read_text())
            if (value.get('schema') != 1 or value.get('app') != app or
                    value.get('status') not in ('idle', 'running', 'failed', 'completed') or
                    value.get('operation') not in ('install', 'address') or
                    not isinstance(value.get('revision'), str) or not isinstance(value.get('steps'), list) or
                    [row.get('id') for row in value['steps']] != [key for key, _ in STEPS] or
                    any(row.get('status') not in ('pending', 'running', 'completed', 'failed', 'skipped') for row in value['steps'])):
                raise ValueError()
            return value
        except (OSError, ValueError, TypeError, AttributeError):
            raise Error('Gespeicherte Installationsschritte sind beschädigt. App-Status prüfen.', 503) from None

    def _installation_write(self, app, value):
        value.update(revision=secrets.token_hex(16), updated_at=time.time())
        path = self._installation_path(app)
        path.parent.mkdir(mode=0o700, exist_ok=True)
        atomic_json(path, value)

    def _installation_revision(self, journal):
        return hashlib.sha256((journal['revision'] + ':' + self.web_access.config()['revision']).encode()).hexdigest()[:32]

    def _installation_step(self, app, step, status='running', message=''):
        value = self._installation_read(app)
        row = next(item for item in value['steps'] if item['id'] == step)
        now = time.time()
        if status == 'running':
            row.update(started_at=now, finished_at=None)
            value['current_step'] = step
        elif status in ('completed', 'failed', 'skipped'):
            row['finished_at'] = now
        row.update(status=status, message=message)
        self._installation_write(app, value)

    def _installation_inputs(self, app):
        path = self._installation_path(app, private=True)
        try:
            metadata = path.lstat()
            import os
            import stat
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid() or
                    metadata.st_mode & 0o077 or metadata.st_nlink != 1):
                raise ValueError()
            value = json.loads(path.read_text())
            if value.get('operation') == 'install' and set(value) == {'operation', 'options'}:
                return {'operation': 'install', 'options': validate_options(value['options'])}
            if value.get('operation') == 'address' and set(value) == {'operation', 'public_origin'}:
                from .remote_access import public_url
                return {'operation': 'address', 'public_origin': public_url(value['public_origin'])}
            raise ValueError()
        except (OSError, ValueError, TypeError, AttributeError, Error):
            raise Error('Private Installationsangaben fehlen oder sind unsicher. Token erneut eingeben.', 409) from None

    def op_app_install_status(self, app):
        from .cloudflare_tunnel import CONNECTOR, connector_ready
        from .remote_access import validate_remote
        app = validate_app(app)
        journal = self._installation_read(app)
        context_active = getattr(self, '_installation_active', set())
        if journal['status'] == 'running' and app not in context_active:
            journal = {**journal, 'status': 'interrupted', 'message': 'Installation durch Dienstneustart unterbrochen. Schritte prüfen und fortsetzen.'}
            journal['steps'] = [dict(row, status='failed', message='Durch Dienstneustart unterbrochen.') if row['status'] == 'running' else row for row in journal['steps']]
        config = self.web_access.config()
        remote = validate_remote(config.get('remote'))
        installed = any(row['id'] == app for row in self.load('apps', []))
        state, connected = 'missing', False
        if installed:
            try:
                record = self.managed_app(app)
                container = self._app_container(app, record)
                state = 'running' if container and container.get('State', {}).get('Running') else 'stopped'
                connected = connector_ready(container)
            except Error:
                state = 'blocked'
        setup = self._remote_setup_status()
        diagnosis = self.load('remote-diagnosis', {})
        public_ready = bool(connected and remote['enabled'] and remote['connector'] == CONNECTOR and
                            diagnosis.get('revision') == config['revision'] and diagnosis.get('connected'))
        resumable = False
        if journal['status'] in ('interrupted', 'failed'):
            try:
                self._installation_inputs(app)
                resumable = True
            except Error:
                pass
        public = {key: journal.get(key) for key in ('app', 'status', 'operation', 'installation', 'current_step',
                  'started_at', 'finished_at', 'updated_at', 'message')}
        public['steps'] = [{key: row.get(key) for key in ('id', 'label', 'status', 'message', 'started_at', 'finished_at')} for row in journal['steps']]
        return {**public, 'revision': self._installation_revision(journal), 'resumable': resumable,
                'installed': installed, 'available': True, 'demo': False, 'setup': setup,
                'remote': remote, 'remote_revision': config['revision'],
                'diagnosis': diagnosis if diagnosis.get('revision') == config['revision'] else {},
                'runtime': {'state': state, 'cloudflare_connected': connected, 'public_origin': remote['public_origin'],
                    'public_ready': public_ready, 'service_url': setup.get('service_url', 'http://127.0.0.1:5102'),
                    'enabled': remote['enabled'], 'message': setup.get('message', '')}}

    def _run_app_installation(self, app, expected_revision, inputs=None, resume=False):
        app = validate_app(app)
        with self.app_config_lock:
            journal = self._installation_read(app)
            if not isinstance(expected_revision, str) or expected_revision != self._installation_revision(journal):
                raise Error('Installationsstand geändert. Ansicht aktualisieren.', 409)
            if app in getattr(self, '_installation_active', set()):
                raise Error('Installation läuft bereits. Vorhandene Schritte anzeigen.', 409)
            if resume:
                if journal['status'] not in ('running', 'failed', 'interrupted'):
                    raise Error('Diese Installation muss nicht fortgesetzt werden.', 409)
                inputs = self._installation_inputs(app)
            else:
                private = self._installation_path(app, private=True)
                private.parent.mkdir(mode=0o700, exist_ok=True)
                atomic_json(private, inputs)
            operation = inputs['operation']
            if operation == 'install':
                # Recheck every real postcondition on retry; completed history
                # is never permission to adopt foreign files or containers.
                journal['steps'] = [dict(id=key, label=label, status='pending', message='', started_at=None, finished_at=None) for key, label in STEPS]
            else:
                for row in journal['steps']:
                    if row['id'] in ('proxy', 'public_check'):
                        row.update(status='pending', message='', started_at=None, finished_at=None)
                    elif row['status'] == 'pending':
                        row.update(status='skipped', message='Für diese Adressänderung nicht ausgeführt.', finished_at=time.time())
            journal.update(status='running', operation=operation, installation=secrets.token_hex(16),
                current_step='', started_at=time.time(), finished_at=None, message='Installation wird ausgeführt.')
            self._installation_write(app, journal)
            if not hasattr(self, '_installation_active'):
                self._installation_active = set()
            self._installation_active.add(app)
            web_revision = self.web_access.config()['revision']
        previous_context = getattr(_LOCAL, 'installation', None)
        _LOCAL.installation = {'host': self, 'app': app, 'operation': operation}
        try:
            if operation == 'install':
                options = inputs['options']
                self.op_remote_access_tunnel(options['tunnel_token'], options['public_origin'], web_revision)
            else:
                self.op_remote_access_tunnel_address(inputs['public_origin'], web_revision)
            journal = self._installation_read(app)
            journal.update(status='completed', finished_at=time.time(), message='Installation abgeschlossen. Aktuellen Verbindungsstatus unten prüfen.')
            self._installation_write(app, journal)
            self._installation_path(app, private=True).unlink(missing_ok=True)
            return {'ok': True, **self.op_app_install_status(app)}
        except Exception:
            journal = self._installation_read(app)
            current = journal.get('current_step')
            if current:
                row = next(item for item in journal['steps'] if item['id'] == current)
                if row['status'] == 'running':
                    row.update(status='failed', finished_at=time.time(), message='Schritt fehlgeschlagen. App-Status prüfen und erneut versuchen.')
            journal.update(status='failed', finished_at=time.time(), message='Installation nicht abgeschlossen. Bereits angelegte Daten bleiben erhalten; Schritte prüfen und fortsetzen.')
            self._installation_write(app, journal)
            raise Error(journal['message'], 503) from None
        finally:
            self._installation_active.discard(app)
            _LOCAL.installation = previous_context

    def op_app_install_run(self, app, options, expected_revision):
        return self._run_app_installation(app, expected_revision, {'operation': 'install', 'options': validate_options(options)})

    def op_app_install_resume(self, app, expected_revision):
        return self._run_app_installation(app, expected_revision, resume=True)

    def op_app_install_address(self, app, public_origin, expected_revision):
        from .remote_access import public_url
        return self._run_app_installation(app, expected_revision, {'operation': 'address', 'public_origin': public_url(public_origin)})

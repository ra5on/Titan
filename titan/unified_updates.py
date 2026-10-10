"""One durable user-approved update plan across web-process and system restarts.

The web package goes first: the new process must know how to finish the plan.
No automatic reboot, no unsigned releases and no implicit install of later offers.
"""
import secrets
import time
from . import __version__
from .core import Error
from .updates import version

KEY = 'unified_update'
ACTIVE = {'queued', 'web_starting', 'web_wait', 'system_queued', 'system_running', 'restart_required'}


class UnifiedUpdates:
    def __init__(self, app, clock=time.time, current_version=None):
        self.app, self.clock = app, clock
        self.current_version = current_version or __version__

    def load(self):
        return self.app.store.config(KEY, {'state': 'unchecked', 'message': 'Nach Updates suchen.'})

    def save(self, plan, state=None, message=None, **extra):
        value = {**plan, **extra, 'updated': self.clock()}
        if state is not None: value['state'] = state
        if message is not None: value['message'] = message
        self.app.store.set_config(KEY, value)
        return value

    def active(self):
        return self.load().get('state') in ACTIVE

    def authorize(self, actor, automatic=False, installing=False):
        if automatic:
            settings = self.app.store.settings()
            if actor != 'system' or not self.app.store.users():
                raise Error('Automatische Updateberechtigung ist nicht verfügbar.', 403)
            if installing:
                current = time.localtime(self.clock())
                if (settings['installation'] != 'automatic' or current.tm_wday != settings['window_day']
                        or current.tm_hour != settings['window_hour']):
                    raise Error('Automatisches Update ist deaktiviert oder liegt außerhalb des Zeitfensters.', 403)
            elif not settings['auto_check'] and settings['installation'] != 'automatic':
                raise Error('Automatische Updatesuche ist deaktiviert.', 403)
            return
        record = self.app.store.user_record(actor)
        if not record['enabled'] or record['role'] != 'admin':
            raise Error('Administratorrechte sind nicht mehr gültig.', 403)

    def status(self):
        plan = self.load()
        return {'current': self.current_version, **{key: plan[key] for key in ('id', 'state', 'message', 'updated', 'checked', 'target',
                'restart_required', 'next_digest', 'completed', 'details', 'demo') if key in plan}}

    def check(self, actor, automatic=False):
        with self.app.update_lock:
            self.authorize(actor, automatic=automatic)
            if self.active():
                return self.status()
            settings = self.app.store.settings()
            plan = {'id': secrets.token_hex(24), 'checked': self.clock(), 'completed': [],
                    'repository': settings['repository'], 'channel': settings['channel']}
            errors = []
            try:
                system = self.app.update_check()
                if system.get('error'): errors.append(system['error'])
                if system.get('available') and not system.get('signed'):
                    errors.append('Das verfügbare Update wurde nicht als signiert bestätigt.')
            except Exception as exc:
                system = {}; errors.append(str(exc))
            try:
                web = ({'current': self.current_version, 'available': False} if self.app.demo else
                       self.app.agent.call('web_update_check'))
            except Exception as exc:
                web = {}; errors.append(str(exc))
            # Never turn an unavailable source into a false "up to date" result.
            if errors:
                self.save(plan, 'check_failed', 'Updates konnten nicht vollständig geprüft werden. Erneut versuchen.', details=errors)
                return self.status()
            plan['demo'] = self.app.demo
            plan['system_version'] = system.get('latest') if system.get('available') and system.get('signed') else None
            plan['system_app_version'] = system.get('latest_titan_version')
            plan['web_version'] = (web.get('latest') or {}).get('version') if web.get('available') else None
            plan['web_image'] = (web.get('latest') or {}).get('image') if web.get('available') else None
            plan['base_digest'] = (system.get('booted') or {}).get('digest')
            plan['base_web'] = self.current_version
            targets = [x for x in (plan['web_version'], plan['system_app_version'] if plan['system_version'] else None) if x]
            plan['target'] = max(targets, key=version) if targets else self.current_version
            if system.get('reboot_required') or system.get('reboot_scheduled'):
                self.save(plan, 'existing_restart', 'Ein vorbereitetes Update wartet auf den Neustart.', restart_required=True,
                          next_digest=(system.get('next_boot') or {}).get('digest'))
            elif not self.app.demo and system.get('latest') and not system.get('available'):
                self.save(plan, 'blocked', 'Ein Update ist verfügbar, kann aber noch nicht installiert werden. Systemstatus prüfen.')
            else:
                available = bool(plan['system_version'] or plan['web_version']) and not self.app.demo
                self.save(plan, 'ready' if available else 'current',
                          'Ein Update für Titan ist verfügbar.' if available else 'Titan ist aktuell.' if not self.app.demo else 'Demo: Updates werden nur dargestellt.',
                          restart_required=bool(plan['system_version']))
            return self.status()

    def start(self, actor, plan_id, automatic=False):
        with self.app.update_lock:
            self.authorize(actor, automatic=automatic, installing=True)
            plan = self.load()
            if (self.app.demo or plan.get('id') != plan_id or plan.get('state') != 'ready'
                    or not 0 <= self.clock() - plan.get('checked', 0) <= 1800):
                raise Error('Das Updateangebot ist nicht mehr aktuell. Bitte erneut prüfen.', 409)
            settings = self.app.store.settings()
            if any(plan[key] != settings[key] for key in ('repository', 'channel')):
                raise Error('Updatequelle oder Kanal wurde geändert. Bitte erneut prüfen.', 409)
            self.save(plan, 'queued', 'Update wird gestartet.', actor=actor, automatic=automatic)
            try:
                return self.app.jobs.submit(actor, 'unified_update', self.execute)
            except Exception:
                self.save(self.load(), 'failed', 'Der Updateauftrag konnte nicht gestartet werden. Erneut prüfen.')
                raise

    def failed(self, plan, error):
        message = 'Update konnte nicht abgeschlossen werden: ' + str(error)
        if plan.get('completed'):
            message += ' Bereits abgeschlossene Schritte bleiben installiert. Erneut prüfen führt die übrigen Updates fort.'
        return self.save(plan, 'failed', message)

    def execute(self):
        with self.app.update_lock:
            plan = self.load()
            try:
                if plan.get('state') not in ('queued', 'system_queued'):
                    raise Error('Updateauftrag hat sich geändert.', 409)
                self.authorize(plan['actor'], automatic=plan.get('automatic', False), installing=True)
                settings = self.app.store.settings()
                if any(plan.get(key) != settings[key] for key in ('repository', 'channel')):
                    raise Error('Updatequelle oder Kanal wurde geändert. Bitte erneut prüfen.', 409)
                if plan.get('web_version') and version(self.current_version) < version(plan['web_version']):
                    fresh = self.app.agent.call('web_update_check')
                    if (not fresh.get('available') or (fresh.get('latest') or {}).get('version') != plan['web_version']
                            or (fresh.get('latest') or {}).get('image') != plan['web_image']):
                        raise Error('Das signierte Updateangebot wurde geändert. Bitte erneut prüfen.', 409)
                    # Persist before dispatch: the HTTP process can be stopped at any point.
                    plan = self.save(plan, 'web_starting', 'Titan wird aktualisiert. Die Verbindung kann kurz unterbrochen werden.', web_started=self.clock())
                    self.app.agent.call('web_update_start', action='release', version=plan['web_version'])
                    # Do not write after dispatch: a replacement process may already
                    # have resumed and advanced this durable plan.
                    return {'ok': True, 'continuing': True}
                if plan.get('system_version'):
                    plan = self.save(plan, 'system_running', 'Update wird heruntergeladen, geprüft und vorbereitet.')
                    result = self.app.install_update(plan['actor'], plan['system_version'], unified_token=plan['id'], **({'automatic': True} if plan.get('automatic') else {}))
                    staged = result.get('staged') or {}
                    if not result.get('reboot_required') or not staged.get('digest'):
                        raise Error('Das vorbereitete Update konnte nicht bestätigt werden.', 503)
                    self.save(plan, 'restart_required', 'Update vorbereitet. Zum Abschließen das NAS neu starten.',
                              restart_required=True, next_digest=staged['digest'])
                    return {'ok': True, 'reboot_required': True}
                self.save(plan, 'completed', 'Titan wurde erfolgreich aktualisiert.', restart_required=False)
                return {'ok': True}
            except Exception as exc:
                self.failed(self.load(), exc)
                raise

    def reconcile(self):
        """Called by the updater thread, never by a read-only HTTP request."""
        with self.app.update_lock:
            plan = self.load()
            state = plan.get('state')
            if state not in ACTIVE: return
            try:
                if state in ('web_starting', 'web_wait'):
                    if version(self.current_version) >= version(plan['web_version']):
                        completed = list(dict.fromkeys([*plan.get('completed', []), 'Oberfläche aktualisiert']))
                        if not plan.get('system_version'):
                            self.save(plan, 'completed', 'Titan wurde erfolgreich aktualisiert.', completed=completed, restart_required=False)
                            return
                        self.authorize(plan['actor'], automatic=plan.get('automatic', False), installing=True)
                        plan = self.save(plan, 'system_queued', 'Aktualisierung wird fortgesetzt.', completed=completed)
                        self.app.jobs.submit(plan['actor'], 'unified_update', self.execute)
                    elif self.clock() - plan.get('web_started', self.clock()) > 900:
                        self.failed(plan, 'Die neue Version wurde nicht bestätigt. Die bisherige Oberfläche ist weiter verfügbar.')
                elif state in ('system_running', 'restart_required'):
                    system = self.app.agent.call('system_updates')
                    if (state == 'restart_required' and system.get('health_confirmed')
                            and (system.get('booted') or {}).get('digest') == plan.get('next_digest')
                            and not system.get('reboot_required')):
                        self.save(plan, 'completed', 'Titan wurde erfolgreich aktualisiert.', restart_required=False,
                                  completed=[*plan.get('completed', []), 'System aktualisiert'])
                    elif system.get('last_failure') and not system.get('reboot_required'):
                        self.failed(plan, 'Der neue Systemstand wurde nicht bestätigt; Rückfall und Systemstatus prüfen.')
                    elif system.get('reboot_required'):
                        staged = system.get('staged') or {}
                        if staged.get('version') and version(staged['version']) == version(plan['system_version']):
                            self.save(plan, 'restart_required', 'Update vorbereitet. Zum Abschließen das NAS neu starten.',
                                      next_digest=staged['digest'], restart_required=True)
                    elif state == 'restart_required' and system.get('health_confirmed'):
                        if (system.get('booted') or {}).get('digest') == plan.get('next_digest'):
                            self.save(plan, 'completed', 'Titan wurde erfolgreich aktualisiert.', restart_required=False,
                                      completed=[*plan.get('completed', []), 'System aktualisiert'])
                        else:
                            self.failed(plan, 'Der erwartete Systemstand wurde nicht gestartet. Der vorherige Stand bleibt erhalten.')
                    elif state == 'system_running':
                        progress = self.app.agent.call('update_progress')
                        if progress.get('status') in ('idle', 'completed', 'failed', 'interrupted'):
                            self.failed(plan, progress.get('message') or 'Die Vorbereitung wurde unterbrochen.')
                elif state in ('queued', 'system_queued'):
                    # Jobs are marked failed at process startup. A queued intent is safe to retry;
                    # an interrupted writer is handled above, never blindly re-dispatched.
                    busy = any(j['action'] == 'unified_update' and j['status'] in ('queued', 'running') for j in self.app.store.jobs())
                    if not busy:
                        self.authorize(plan['actor'], automatic=plan.get('automatic', False), installing=True)
                        self.app.jobs.submit(plan['actor'], 'unified_update', self.execute)
            except Exception as exc:
                if isinstance(exc, Error) and exc.status == 403:
                    self.failed(plan, exc)
                else:
                    # RPC outages during reboot are transient; retain the exact planned target.
                    self.save(plan, message='Verbindung zum NAS wird wiederhergestellt. ' + str(exc))

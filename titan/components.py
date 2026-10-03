"""Fixed, administrator-only uCore image component service repair. No arbitrary commands."""
from collections import deque
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import time
from .core import Error
from .virtualization import availability
from .hardware import gpus

HELPER = Path('/usr/share/titan/install-components.sh')
SYSTEM_PATH = '/usr/sbin:/usr/bin:/sbin:/bin'


def run_component_helper(path, component, log_stream, timeout=1800, termination_grace=10):
    arguments = ['/bin/bash', str(path), '--component', component, '--json']
    process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=log_stream, text=True, start_new_session=True,
        env={'PATH': SYSTEM_PATH, 'LC_ALL': 'C.UTF-8'})
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Killing just bash can leave a service operation running after the mutation lock is
        # released. Terminate its entire session before reporting failure.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=termination_grace)
        except subprocess.TimeoutExpired:
            pass
        finally:
            # Descendants can close stdout and outlive an already reaped bash.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.communicate(timeout=termination_grace)
        except subprocess.TimeoutExpired:
            # An escaped child may retain the pipe; never wait without a bound.
            if process.stdout is not None:
                process.stdout.close()
            try:
                process.wait(timeout=termination_grace)
            except subprocess.TimeoutExpired:
                pass
        raise
    return subprocess.CompletedProcess(arguments, process.returncode, output)


class ComponentsMixin:
    def docker_component(self):
        missing = [] if shutil.which('docker', path=SYSTEM_PATH) else ['docker']
        result = {'installed': not missing, 'available': False, 'missing': missing, 'daemon': False, 'compose': False}
        if missing:
            return {**result, 'error': 'Docker fehlt im Titan-Systemimage. Ein vollständiges Titan-Systemimage installieren oder aktualisieren.'}
        from .host import run
        try:
            run(['docker', 'compose', 'version'], timeout=15)
            result['compose'] = True
        except Error:
            result['missing'].append('Docker Compose')
        try:
            run(['docker', 'info', '--format', '{{.ServerVersion}}'], timeout=15)
            result['daemon'] = True
        except Error as exc:
            result['error'] = 'Docker-Dienst ist nicht erreichbar: ' + str(exc)
        result['available'] = result['compose'] and result['daemon']
        if not result['compose']:
            result['error'] = 'Docker Compose fehlt im Titan-Systemimage. Titan-Systemimage aktualisieren.'
        return result

    def op_components(self):
        vm = availability()
        vm['daemon'] = False
        if not vm['missing'] and os.uname().machine in ('x86_64', 'amd64'):
            from .host import run
            try:
                run(['virsh', 'version'], timeout=15)
                vm['daemon'] = True
            except Error as exc:
                vm.update(available=False, error='libvirt ist nicht erreichbar: ' + str(exc))
        return {'components': {'docker': self.docker_component(), 'vms': vm},
                'repair': self.load('component-repair', {}), 'gpus': gpus()}

    def op_component_install(self, component='all'):
        if type(component) is not str or component not in ('all', 'docker', 'vms'):
            raise Error('Ungültige Systemkomponente.')
        path = getattr(self, 'component_helper', HELPER)
        path = Path(path)
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
                raise Error('Komponentenhelfer ist nicht sicher installiert.', 503)
        except OSError:
            raise Error('Komponentenhelfer fehlt im Titan-Systemimage. Titan-Systemimage aktualisieren.', 503) from None
        started = time.time()
        self.save('component-repair', {'running': True, 'component': component, 'started': started, 'phase': 'Vorinstallierte Systemkomponenten prüfen und Dienste einrichten'})
        log = self.directory / 'component-install.log'
        output = ''
        try:
            # The installed helper cannot change IP, Caddy, users, shares or disks.
            with log.open('w') as stream:
                os.chmod(log, 0o600)
                result = run_component_helper(path, component, stream)
            with log.open() as stream:
                output = ''.join(deque(stream, maxlen=60))[-12000:]
            try:
                report = json.loads(result.stdout)
                if not isinstance(report, dict) or not isinstance(report.get('components'), dict):
                    raise ValueError('invalid report')
            except (ValueError, TypeError):
                raise Error('Komponentenhelfer lieferte keinen gültigen Bericht.\n' + output, 503) from None
            if result.returncode or not report.get('ok'):
                raise Error('Komponentenprüfung oder Diensteinrichtung unvollständig.\n' + output, 503)
            warnings = report.get('warnings', [])
            if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
                raise Error('Komponentenhelfer lieferte ungültige Hinweise.', 503)
            warnings = list(warnings)
            if component in ('all', 'vms'):
                warnings += self.prepare_vm_storage_access()
            status = self.op_components()
            selected = ('docker', 'vms') if component == 'all' else (component,)
            for name in selected:
                current = status['components'][name]
                if name == 'docker' and not current['available']:
                    raise Error(current.get('error', 'Docker ist weiterhin nicht bereit.'), 503)
                if name == 'vms' and (not current['installed'] or not current['daemon']):
                    raise Error(current.get('error', 'VM-Komponenten sind weiterhin nicht bereit.'), 503)
                if name == 'vms' and not current['kvm'] and current.get('error'):
                    warnings.append(current['error'])
            report.update(message='Systemkomponenten wurden eingerichtet.', output=output,
                          warnings=list(dict.fromkeys(warnings)), status=status['components'])
            if report['warnings']:
                report['message'] += ' Hinweise zur Virtualisierung beachten.'
            self.save('component-repair', {'running': False, 'ok': True, 'component': component, 'started': started, 'finished': time.time(), 'warnings': report['warnings']})
            return report
        except (Error, OSError, subprocess.TimeoutExpired) as exc:
            self.save('component-repair', {'running': False, 'ok': False, 'component': component,
                      'started': started, 'finished': time.time(), 'error': str(exc)[-4000:]})
            if isinstance(exc, Error):
                raise
            raise Error('Komponentenprüfung fehlgeschlagen: ' + str(exc)[-4000:], 503) from None

"""Independent web updates, executed by systemd so closing the UI is harmless."""
import importlib.util
from pathlib import Path
import re
from .core import Error

CONTROLLER = Path('/usr/share/titan/web-container.py')


def controller():
    if not CONTROLLER.is_file() or not Path('/usr/share/titan/web-image.json').is_file():
        raise Error('Separate Webupdates benötigen die neue Container-Installation.', 409)
    spec = importlib.util.spec_from_file_location('titan_web_controller', CONTROLLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check():
    return controller().check_release()


def start(action, version=None):
    from .host import run
    controller()
    if action not in ('release', 'rollback') or (action == 'release' and not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version or '')):
        raise Error('Ungültiges Webupdate.')
    run(['systemd-run', '--unit=titan-web-switch', '--collect', '--property=Type=exec',
         '/usr/bin/python3', str(CONTROLLER), action, *([version] if action == 'release' else [])])
    return {'ok': True, 'message': 'Webwechsel gestartet. Die Oberfläche verbindet sich anschließend neu.'}

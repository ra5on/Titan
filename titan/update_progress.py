"""Ephemeral, read-only update activity; no invented overall percentage."""
import functools
import json
import logging
from pathlib import Path
import secrets
import threading
import time
from .core import atomic_json

PATH = Path('/run/titan/update-progress.json')
_context = threading.local()
_active = set()


def report(phase, *, received=None, total=None):
    state = getattr(_context, 'state', None)
    if state is None:
        return
    state.update(phase=phase, updated_at=time.time())
    state.pop('received', None)
    state.pop('total', None)
    if received is not None and total is not None:
        state.update(received=received, total=total)
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(PATH, state)
    except OSError:
        logging.getLogger(__name__).warning('Update-Fortschritt konnte nicht gespeichert werden.')


def read():
    try:
        state = json.loads(PATH.read_text())
    except (OSError, ValueError):
        return {'status': 'idle'}
    if state.get('status') == 'running' and state.get('id') not in _active:
        state.update(status='interrupted', message='Die Ausführung wurde unterbrochen. Systemstatus erneut prüfen.')
    state['elapsed'] = max(0, int((time.time() if state.get('status') == 'running' else state.get('updated_at', time.time())) - state.get('started_at', time.time())))
    return state


def tracked(function):
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        token = secrets.token_hex(16)
        _active.add(token)
        _context.state = {'id': token, 'status': 'running', 'started_at': time.time()}
        report('checking')
        try:
            result = function(*args, **kwargs)
            _context.state['status'] = 'completed'
            report('ready')
            return result
        except Exception:
            _context.state.update(status='failed', message='Systemupdate fehlgeschlagen. Details stehen in der Aktivität.')
            report(_context.state['phase'])
            raise
        finally:
            _active.discard(token)
            del _context.state
    return wrapper

"""Locally maintained Compose offers and disposable image-test fixtures."""
import json
import os
from pathlib import Path
import stat

from .core import Error

AVAILABLE_APP_IDS = frozenset({'titan-cloudflared'})
CI_SOURCE = 'https://raw.githubusercontent.com/ra5on/Titan/main/tests/fixtures/runtime-stack-store.json'
CI_FILENAME = 'ci-compose-fixtures.json'


def load_ci_fixtures(host):
    """Root injects this file into the test overlay; no HTTP import can create it."""
    host._ci_fixture_ids = set()
    directory = getattr(host, 'directory', None)
    if directory is None:
        return
    path = Path(directory) / CI_FILENAME
    if not os.path.lexists(path):
        return
    from .catalog import APPS
    from .store_recipes import recipes
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        owner = os.fstat(directory_fd)
        if owner.st_uid != 0 or owner.st_mode & 0o022:
            raise Error('CI-Prüfrezepte benötigen ein privates Root-Verzeichnis.')
        descriptor = os.open(CI_FILENAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        with os.fdopen(descriptor, 'rb') as stream:
            details = os.fstat(stream.fileno())
            if not stat.S_ISREG(details.st_mode) or details.st_uid != 0 or stat.S_IMODE(details.st_mode) != 0o600 or details.st_nlink != 1:
                raise Error('CI-Prüfrezepte benötigen eine private normale Root-Datei.')
            payload = stream.read(256 * 1024 + 1)
        if len(payload) > 256 * 1024:
            raise Error('CI-Prüfrezepte überschreiten die Größenbegrenzung.')
        document = json.loads(payload)
        if not isinstance(document, dict) or set(document) != {'schema', 'disposable', 'document', 'legacy_ids'} or document['schema'] != 1 or document['disposable'] is not True or document['legacy_ids'] != ['heimdall']:
            raise Error('Ungültige private CI-Prüfrezepte.')
        _, parsed = recipes(document['document'], CI_SOURCE)
        if set(parsed) != {'s5f61a2c464-runtime-stack'}:
            raise Error('Nur das eigene Compose-Laufzeitprüfrezept ist zulässig.')
        APPS.update(parsed)
        host._ci_fixture_ids = {'heimdall', *parsed}
    finally:
        os.close(directory_fd)

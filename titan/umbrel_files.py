"""Checked package seed files; existing application state is never overwritten."""
import base64
import binascii
import contextlib
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat

from .core import Error


def validate(rows):
    if not isinstance(rows, list) or len(rows) > 512:
        raise Error('Zu viele App-Paketdateien.')
    decoded, names, total = [], set(), 0
    for row in rows:
        if not isinstance(row, dict) or set(row) - {'slot', 'path', 'sha256', 'content', 'mode', 'personalize'} or not {'slot', 'path', 'sha256', 'content', 'mode'} <= set(row):
            raise Error('Ungültige App-Paketdatei.')
        slot, path = row['slot'], row['path']
        if not isinstance(slot, str) or not re.fullmatch(r'umbrel-[a-f0-9]{20}', slot):
            raise Error('Ungültiger Paketdatei-Speicher.')
        if not isinstance(path, str) or len(path) > 240 or path and (not re.fullmatch(r'[A-Za-z0-9_./-]+', path) or any(p in ('', '.', '..') for p in path.split('/'))):
            raise Error('Unsicherer Paketdateipfad.')
        name = slot + ('/' + path if path else '')
        if name in names or any(name.startswith(other + '/') or other.startswith(name + '/') for other in names):
            raise Error('Überlappende App-Paketdateien.')
        names.add(name)
        if type(row['mode']) is not int or row['mode'] not in (0o644, 0o755):
            raise Error('Ungültige Paketdateirechte.')
        if not isinstance(row['content'], str) or len(row['content']) > 1400000 or not isinstance(row['sha256'], str):
            raise Error('App-Paketdatei ist zu groß oder ungültig.')
        try:
            raw = base64.b64decode(row['content'], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise Error('Ungültiger Paketdateiinhalt.') from exc
        total += len(raw)
        if len(raw) > 1024**2 or total > 8 * 1024**2 or hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise Error('Paketdatei-Prüfsumme oder Größenlimit stimmt nicht.')
        if 'personalize' in row:
            if row['personalize'] != 'yaml-jwt-secret':
                raise Error('Unbekannte Paketdatei-Personalisierung.')
            from .umbrel_catalog import read_yaml
            data = read_yaml(raw)
            if not isinstance(data.get('jwt'), dict) or not isinstance(data['jwt'].get('secret'), str):
                raise Error('Paketdatei enthält keinen unterstützten Sitzungsschlüssel.')
        decoded.append((name, raw, row['mode']))
    return decoded


def install(config, rows, definition, uid, gid):
    """Use pinned directory descriptors and publish each complete file once.

    The installed app owns the files. Subsequent installs preserve its modified
    bytes and permissions; a package refresh never reapplies old defaults.
    """
    decoded = validate(rows)
    if not decoded:
        return
    owners = {}
    config = Path(config)
    for service in definition['services'].values():
        owner = tuple(map(int, service['user'].split(':'))) if service.get('user') else (uid, gid)
        if len(owner) == 1: owner = (owner[0], owner[0])
        for binding in service.get('volumes', []):
            path = Path(binding['source'])
            if path.parent == config:
                # A shared mount must have one agreed initial owner.
                if path.name in owners and owners[path.name] != owner:
                    raise Error('Gemeinsam genutzte Paketdateien benötigen eindeutige Eigentümer.')
                owners[path.name] = owner
    if any(name.split('/')[0] not in owners for name, _, _ in decoded):
        raise Error('Paketdatei ist keinem installierten App-Speicher zugeordnet.')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with contextlib.ExitStack() as root_stack:
        root = os.open(config, flags); root_stack.callback(os.close, root)
        for row, (name, raw, mode) in zip(rows, decoded):
            file_uid, file_gid = owners[name.split('/')[0]]
            with contextlib.ExitStack() as stack:
                parent = root
                parts = name.split('/')
                for part in parts[:-1]:
                    created = False
                    try: os.mkdir(part, 0o755, dir_fd=parent); created = True
                    except FileExistsError: pass
                    child = os.open(part, flags, dir_fd=parent); stack.callback(os.close, child)
                    if created:
                        os.fchown(child, file_uid, file_gid); os.fsync(parent)
                    parent = child
                def existing():
                    try: state = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                    except FileNotFoundError: return False
                    if not stat.S_ISREG(state.st_mode) or state.st_nlink != 1:
                        raise Error('Vorhandene Paketdatei ist keine eigenständige reguläre Datei.')
                    return True
                if existing(): continue
                if row.get('personalize') == 'yaml-jwt-secret':
                    import yaml
                    from .umbrel_catalog import read_yaml
                    document = read_yaml(raw)
                    document['jwt']['secret'] = secrets.token_hex(32)
                    raw = yaml.safe_dump(document, sort_keys=False).encode()
                staging = '.titan-seed-' + secrets.token_hex(16)
                descriptor = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                try:
                    with os.fdopen(descriptor, 'wb') as stream:
                        stream.write(raw); stream.flush()
                        os.fchown(stream.fileno(), file_uid, file_gid)
                        os.fchmod(stream.fileno(), mode); os.fsync(stream.fileno())
                    try:
                        os.link(staging, parts[-1], src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                    except FileExistsError:
                        existing()
                finally:
                    os.unlink(staging, dir_fd=parent); os.fsync(parent)

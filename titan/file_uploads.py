"""Private staged uploads with serialized cancel/commit and no replacement."""
import base64
import binascii
import contextlib
import fcntl
import json
import os
import re
import stat
import time

from .core import Error, integer

DIRECTORY = '.titan-uploads-' + str(os.geteuid())
TTL = 24 * 60 * 60


def _save(fd, value):
    encoded = json.dumps(value, separators=(',', ':')).encode()
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, encoded)
    os.ftruncate(fd, len(encoded))
    os.fsync(fd)


def _regular(fd):
    value = os.fstat(fd)
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1 or value.st_uid != os.geteuid():
        raise Error('Ungültiger privater Upload-Zustand.', 409)


def _mark_complete(private, token):
    """A separate immutable marker cannot corrupt the staged-file journal."""
    fd = os.open(token + '.done', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=private)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(private)


def _recover_complete(state, directory, private, token, owner):
    if state['status'] != 'uploading' or state['offset'] != state['total']:
        return
    try:
        marker = os.stat(token + '.done', dir_fd=private, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISREG(marker.st_mode) or marker.st_size or marker.st_nlink != 1 or marker.st_uid != owner or marker.st_mode & 0o077:
            raise Error('Ungültiger privater Upload-Abschluss.', 409)
        state['status'] = 'complete'
        return
    try:
        os.stat(token + '.part', dir_fd=private, follow_symlinks=False)
    except FileNotFoundError:
        try:
            target = os.stat(state['name'], dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return
        if stat.S_ISREG(target.st_mode) and state.get('identity') == [target.st_dev, target.st_ino] and target.st_size == state['total']:
            state['status'] = 'complete'


@contextlib.contextmanager
def ended_metadata(directory, name):
    """Hold private journals stable while their containing folder is moved."""
    message = 'Dieser Ordner enthält laufende oder ungeklärte Upload-Zwischenstände. Uploads zuerst abschließen oder abbrechen.'
    with contextlib.ExitStack() as locks:
        try:
            private = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            locks.callback(os.close, private)
            value = os.fstat(private)
            if name != '.titan-uploads-' + str(value.st_uid) or value.st_mode & 0o077:
                raise Error(message, 409)
            fcntl.flock(private, fcntl.LOCK_EX | fcntl.LOCK_NB)
            names = set(os.listdir(private))
            journals = {item for item in names if re.fullmatch(r'[a-f0-9]{64}\.json', item)}
            markers = {item for item in names if re.fullmatch(r'[a-f0-9]{64}\.done', item)}
            if names != journals | markers or any(item[:-5] + '.json' not in journals for item in markers):
                raise Error(message, 409)
            records, originals = {}, {}
            for item in sorted(journals):
                fd = os.open(item, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=private)
                locks.callback(os.close, fd)
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != value.st_uid or info.st_nlink != 1 or info.st_mode & 0o077:
                    raise Error(message, 409)
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                state = json.loads(os.read(fd, 4097))
                if (not isinstance(state, dict) or not isinstance(state.get('name'), str) or not state['name'] or '/' in state['name'] or state['name'] in ('.', '..')
                        or type(state.get('total')) is not int or state['total'] < 0 or type(state.get('offset')) is not int or not 0 <= state['offset'] <= state['total']
                        or state.get('status') not in ('pending', 'uploading', 'canceled', 'complete')):
                    raise Error(message, 409)
                _recover_complete(state, directory, private, item[:-5], value.st_uid)
                if state['status'] not in ('complete', 'canceled') or state['status'] == 'complete' and state['offset'] != state['total']:
                    raise Error(message, 409)
                records[item], originals[item] = state, info
            for item in markers:
                info = os.stat(item, dir_fd=private, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_size or info.st_nlink != 1 or info.st_uid != value.st_uid or info.st_mode & 0o077:
                    raise Error(message, 409)
                originals[item] = info
        except (OSError, ValueError, UnicodeError):
            raise Error(message, 409) from None
        yield {'info': value, 'records': records, 'originals': originals}


def _prune(directory):
    # Old abandoned uploads remain private and are reclaimed on later uploads.
    # A live chunk/cancel owns the lock and cannot be reclaimed concurrently.
    cutoff = time.time() - TTL
    for name in os.listdir(directory)[:512]:
        if not re.fullmatch(r'[a-f0-9]{64}\.json', name):
            continue
        try:
            fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                _regular(fd)
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if os.fstat(fd).st_mtime >= cutoff:
                    continue
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(name[:-5] + '.part', dir_fd=directory)
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(name[:-5] + '.done', dir_fd=directory)
                os.unlink(name, dir_fd=directory)
            finally:
                os.close(fd)
        except (OSError, Error):
            continue


def upload(directory, leaf, args):
    token = args.get('upload_id')
    if not isinstance(token, str) or not re.fullmatch(r'[a-f0-9]{64}', token):
        raise Error('Ungültige Upload-Kennung.')
    total = integer(args.get('total'), 0, 2**63 - 1)
    for key in ('finish', 'cancel'):
        if key in args and type(args[key]) is not bool:
            raise Error('Ungültiger Upload-Abschluss.')
    finish, cancel = args.get('finish', False), args.get('cancel', False)
    if finish and cancel:
        raise Error('Upload kann nicht gleichzeitig abgeschlossen und abgebrochen werden.')
    with contextlib.suppress(FileExistsError):
        os.mkdir(DIRECTORY, mode=0o700, dir_fd=directory)
    private = os.open(DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
    try:
        value = os.fstat(private)
        if value.st_uid != os.geteuid() or value.st_mode & 0o077:
            raise Error('Privates Upload-Verzeichnis ist nicht geschützt.', 409)
        fcntl.flock(private, fcntl.LOCK_SH)
        _prune(private)
        fd = os.open(token + '.json', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=private)
        try:
            _regular(fd)
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.lseek(fd, 0, os.SEEK_SET)
            raw = os.read(fd, 4097)
            if len(raw) > 4096:
                raise Error('Ungültiger Upload-Zustand.', 409)
            try:
                state = json.loads(raw) if raw else {'name': leaf, 'total': total, 'offset': 0, 'status': 'pending'}
            except (ValueError, UnicodeError):
                raise Error('Ungültiger Upload-Zustand.', 409) from None
            if not isinstance(state, dict) or state.get('name') != leaf or state.get('total') != total or state.get('status') not in ('pending', 'uploading', 'canceled', 'complete') or type(state.get('offset')) is not int or not 0 <= state['offset'] <= total:
                raise Error('Upload gehört zu einem anderen Ziel.', 409)
            part = token + '.part'
            _recover_complete(state, directory, private, token, os.geteuid())
            if cancel:
                if state['status'] != 'complete':
                    state['status'] = 'canceled'
                    _save(fd, state)
                    with contextlib.suppress(FileNotFoundError):
                        os.unlink(part, dir_fd=private)
                else:
                    with contextlib.suppress(OSError):
                        _mark_complete(private, token)
                return {'atomic': True, 'upload_id': token, 'canceled': state['status'] == 'canceled', 'complete': state['status'] == 'complete', 'offset': state['offset']}
            if state['status'] == 'canceled':
                raise Error('Upload wurde abgebrochen.', 409)
            if state['status'] == 'complete':
                if finish:
                    with contextlib.suppress(OSError):
                        _mark_complete(private, token)
                    return {'atomic': True, 'upload_id': token, 'complete': True, 'offset': total}
                raise Error('Upload ist bereits abgeschlossen.', 409)
            if finish:
                if state['status'] != 'uploading' or state['offset'] != total:
                    raise Error('Upload ist noch nicht vollständig.', 409)
                source = os.open(part, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=private)
                try:
                    _regular(source)
                    if os.fstat(source).st_size != total:
                        raise Error('Upload-Dateigröße stimmt nicht überein.', 409)
                    os.fsync(source)
                    # The ordinary file worker owns this inode, and normal share
                    # permissions apply only once the completed file is exposed.
                    os.fchmod(source, 0o660)
                finally:
                    os.close(source)
                from .files import _rename_no_replace
                _rename_no_replace(private, part, directory, leaf)
                os.fsync(directory)
                with contextlib.suppress(OSError):
                    _mark_complete(private, token)
                # No journal rewrite after publication: a failed/truncated save
                # must never hide a successful commit from the next request.
                return {'atomic': True, 'upload_id': token, 'complete': True, 'offset': total}
            offset = integer(args.get('offset', 0), 0, 2**63 - 1)
            if offset != state['offset']:
                raise Error('Upload-Position stimmt nicht überein.', 409)
            try:
                data = base64.b64decode(args.get('data', ''), validate=True)
            except (ValueError, TypeError, binascii.Error):
                raise Error('Ungültiger Upload-Block.') from None
            if len(data) > 4 * 1024 * 1024 or offset + len(data) > total:
                raise Error('Upload-Block ist zu groß.')
            if not raw:
                try:
                    os.stat(leaf, dir_fd=directory, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise Error('Ziel existiert bereits.', 409)
                stage = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=private)
                state['status'] = 'uploading'
                value = os.fstat(stage)
                state['identity'] = [value.st_dev, value.st_ino]
            else:
                stage = os.open(part, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=private)
            try:
                _regular(stage)
                if os.fstat(stage).st_size != offset:
                    raise Error('Upload-Dateigröße stimmt nicht überein.', 409)
                os.lseek(stage, offset, os.SEEK_SET)
                with os.fdopen(os.dup(stage), 'wb') as stream:
                    stream.write(data)
                os.fsync(stage)
            finally:
                os.close(stage)
            state['offset'] += len(data)
            _save(fd, state)
            return {'atomic': True, 'upload_id': token, 'complete': False, 'offset': state['offset']}
        finally:
            os.close(fd)
    finally:
        os.close(private)

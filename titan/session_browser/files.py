"""Private container-side file transfer. Never follows links or accepts paths."""
import base64
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path('/home/browser/Downloads')
LIMIT = 256 * 1024 * 1024


def transfer(value):
    directory = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        return transfer_at(directory, value)
    finally:
        os.close(directory)


def transfer_at(directory, value):
    action = value.get('action')
    if action == 'list':
        files = []
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_file(follow_symlinks=False) and not entry.name.startswith('.'):
                    info = entry.stat(follow_symlinks=False)
                    files.append({'name':entry.name, 'size':info.st_size})
                if len(files) >= 200:
                    break
        files.sort(key=lambda item: item['name'])
        return {'files':files}
    name = value['name']
    if (not isinstance(name, str) or not name or len(name) > 200 or name.startswith('.') or
            any(char in name for char in '/\\\0') or any(ord(char) < 32 for char in name)):
        raise ValueError('Invalid filename')
    offset = value['offset']
    if type(offset) is not int or not 0 <= offset <= LIMIT:
        raise ValueError('Invalid offset')
    flags = os.O_NOFOLLOW | os.O_NONBLOCK
    if action == 'read':
        fd = os.open(name, os.O_RDONLY | flags, dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
                raise ValueError('File too large or not regular')
            stream.seek(offset)
            return {'data':base64.b64encode(stream.read(256 * 1024)).decode(), 'total':info.st_size}
    if action == 'write':
        data = base64.b64decode(value['data'], validate=True)
        if len(data) > 256 * 1024 or offset + len(data) > LIMIT:
            raise ValueError('File too large')
        fd = os.open(name, os.O_WRONLY | flags | (os.O_CREAT | os.O_EXCL if offset == 0 else 0), 0o600, dir_fd=directory)
        with os.fdopen(fd, 'wb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != offset:
                raise ValueError('File changed')
            stream.seek(offset); stream.write(data)
        return {'offset':offset + len(data)}
    raise ValueError('Invalid action')


if __name__ == '__main__':
    try:
        print(json.dumps(transfer(json.loads(sys.stdin.read(400000)))))
    except Exception:
        print(json.dumps({'error':'Datei konnte nicht übertragen werden. Name, Größe und verfügbaren Sitzungsspeicher prüfen.'}))

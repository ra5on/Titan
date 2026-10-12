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
    action = value.get('action')
    if action == 'list':
        files = []
        for path in sorted(ROOT.iterdir())[:200]:
            info = path.lstat()
            if stat.S_ISREG(info.st_mode) and not path.name.startswith('.'):
                files.append({'name':path.name, 'size':info.st_size})
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
        fd = os.open(ROOT / name, os.O_RDONLY | flags)
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
        fd = os.open(ROOT / name, os.O_WRONLY | flags | (os.O_CREAT | os.O_EXCL if offset == 0 else 0), 0o600)
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

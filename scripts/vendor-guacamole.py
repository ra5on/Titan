"""Vendor the unmodified Apache Guacamole 1.6.0 JavaScript client and notices."""
import hashlib
import io
from pathlib import Path
import tarfile
import urllib.request

VERSION = '1.6.0'
URL = f'https://archive.apache.org/dist/guacamole/{VERSION}/source/guacamole-client-{VERSION}.tar.gz'
root = Path(__file__).resolve().parents[1]
archive = urllib.request.urlopen(URL, timeout=120).read()
checksum = urllib.request.urlopen(URL + '.sha256', timeout=30).read().decode().split()[0]
if hashlib.sha256(archive).hexdigest() != checksum:
    raise SystemExit('Apache source checksum mismatch')
target = root / 'titan/web/vendor/guacamole'
target.mkdir(parents=True, exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as source:
    prefix = f'guacamole-client-{VERSION}/'
    scripts = sorted(m for m in source.getnames() if m.startswith(prefix + 'guacamole-common-js/src/main/webapp/modules/') and m.endswith('.js'))
    if not scripts:
        raise SystemExit('Missing upstream JavaScript modules')
    (target / 'guacamole.js').write_bytes(b'\n'.join(source.extractfile(name).read() for name in scripts))
    for name in ('LICENSE', 'NOTICE'):
        (target / name).write_bytes(source.extractfile(prefix + name).read())
(target / 'SOURCE').write_text(f'Apache Guacamole {VERSION}\n{URL}\nSHA256: {checksum}\nModules concatenated in filename order; no source changes.\n', encoding='utf-8')
print(f'Vendored {len(scripts)} upstream modules')

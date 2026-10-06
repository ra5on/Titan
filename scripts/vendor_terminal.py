#!/usr/bin/env python3
"""Download pinned terminal assets from npm, verifying tarball SHA-512 first."""
import base64
import hashlib
import io
import json
import re
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'titan/web/vendor/terminal'
PACKAGES = (
    {'name': '@xterm/xterm', 'version': '6.0.0',
     'url': 'https://registry.npmjs.org/@xterm/xterm/-/xterm-6.0.0.tgz',
     'integrity': 'sha512-TQwDdQGtwwDt+2cgKDLn0IRaSxYu1tSUjgKarSDkUM0ZNiSRXFpjxEsvc/Zgc5kq5omJ+V0a8/kIM2WD3sMOYg==',
     'files': {'package/lib/xterm.js': 'xterm.js', 'package/css/xterm.css': 'xterm.css', 'package/LICENSE': 'xterm-LICENSE'}},
    {'name': '@xterm/addon-fit', 'version': '0.11.0',
     'url': 'https://registry.npmjs.org/@xterm/addon-fit/-/addon-fit-0.11.0.tgz',
     'integrity': 'sha512-jYcgT6xtVYhnhgxh3QgYDnnNMYTcf8ElbxxFzX0IZo+vabQqSPAjC3c1wJrKB5E19VwQei89QCiZZP86DCPF7g==',
     'files': {'package/lib/addon-fit.js': 'addon-fit.js', 'package/LICENSE': 'addon-fit-LICENSE'}},
)


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    manifest = []
    for package in PACKAGES:
        with urllib.request.urlopen(package['url'], timeout=60) as response:
            data = response.read(16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024:
            raise ValueError('Terminal archive exceeds limit')
        actual = 'sha512-' + base64.b64encode(hashlib.sha512(data).digest()).decode()
        if actual != package['integrity']:
            raise ValueError('Terminal archive integrity mismatch')
        files = {}
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            for source, name in package['files'].items():
                member = archive.getmember(source)
                if not member.isfile() or member.size > 2 * 1024 * 1024:
                    raise ValueError('Invalid terminal asset')
                raw = archive.extractfile(member).read()
                text = raw.decode('utf-8')
                if name == 'xterm.js':
                    # Preserve a strict CSP: each generated xterm stylesheet receives
                    # the response-specific style nonce, never unsafe-inline.
                    pattern = r'(s\.mainDocument|this\._document|document)\.createElement\("style"\)'
                    text, count = re.subn(pattern, lambda match: '((n)=>{const e=n.createElement("style");e.nonce=n.querySelector("meta[name=titan-style-nonce]")?.content||"";return e;})(' + match.group(1) + ')', text)
                    if count != 4:
                        raise ValueError('Pinned xterm style structure changed')
                    raw = text.encode('utf-8')
                (TARGET / name).write_bytes(raw)
                files[name] = hashlib.sha256(raw).hexdigest()
        manifest.append({key: value for key, value in package.items() if key != 'files'} | {'sha256': files, 'patch': 'xterm generated styles use Titan CSP nonce' if package['name']=='@xterm/xterm' else None})
    (TARGET / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Pinned terminal assets verified and saved locally.')


if __name__ == '__main__':
    main()

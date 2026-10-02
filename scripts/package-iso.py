#!/usr/bin/env python3
"""Compress an ISO and split it only when GitHub's per-asset limit requires it."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ASSET_LIMIT = 2147483648
CHUNK_SIZE = 1900 * 1024 * 1024


def fingerprint(path):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'name': path.name, 'sha256': digest, 'size': path.stat().st_size}


def package(iso):
    if not re.fullmatch(r'titan-[0-9A-Za-z.-]+-x86_64\.iso', iso.name) or not iso.is_file() or iso.is_symlink():
        raise ValueError('A regular Titan .iso file is required.')
    original = fingerprint(iso)
    compressed = iso.with_name(iso.name + '.xz')
    if compressed.exists() or list(iso.parent.glob(iso.name + '.xz.part-*')):
        raise ValueError('Refusing to overwrite existing ISO downloads.')
    subprocess.run(['xz', '-T2', '-6', '--keep', '--', str(iso)], check=True)
    combined = fingerprint(compressed)
    parts = []
    if combined['size'] >= ASSET_LIMIT:
        with compressed.open('rb') as stream:
            number = 1
            while True:
                block = stream.read(min(CHUNK_SIZE, 8 * 1024 * 1024))
                if not block:
                    break
                target = compressed.with_name(compressed.name + f'.part-{number:03}')
                remaining = CHUNK_SIZE
                with target.open('xb') as output:
                    while block:
                        output.write(block)
                        remaining -= len(block)
                        if remaining == 0:
                            break
                        block = stream.read(min(remaining, 8 * 1024 * 1024))
                parts.append(fingerprint(target))
                number += 1
        compressed.unlink()
    else:
        parts.append(combined)
    result = {'format': 'titan-iso-download-v1', 'filename': original['name'], 'compression': 'xz',
              'sha256': combined['sha256'], 'size': combined['size'],
              'uncompressed_sha256': original['sha256'], 'uncompressed_size': original['size'], 'parts': parts}
    (iso.parent / 'iso-download.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(f"ISO download prepared: {len(parts)} file(s), each smaller than 2 GiB.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('iso', type=Path)
    args = parser.parse_args()
    package(args.iso)


if __name__ == '__main__':
    main()

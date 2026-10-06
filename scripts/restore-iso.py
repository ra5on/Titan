#!/usr/bin/env python3
"""Verify a Titan release and restore its complete bootable ISO with one command."""
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import shutil
import subprocess


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def restore(directory, manifest):
    iso = manifest.get('iso', {})
    name = iso.get('filename', '')
    if not re.fullmatch(r'titan-[0-9A-Za-z.-]+-x86_64\.iso', name) or iso.get('compression') != 'xz':
        raise ValueError('No supported ISO in the signed manifest.')
    parts = iso.get('parts', [])
    if not parts or len(parts) > 100:
        raise ValueError('Incomplete ISO download description.')
    expected_names = [name + '.xz'] if len(parts) == 1 and parts[0].get('name') == name + '.xz' else [name + f'.xz.part-{number:03}' for number in range(1, len(parts)+1)]
    paths = []
    for part, expected in zip(parts, expected_names):
        if part.get('name') != expected:
            raise ValueError('Unordered or unsafe ISO download filenames.')
        path = directory / expected
        if not path.is_file() or path.is_symlink() or path.stat().st_size != part['size'] or digest(path) != part['sha256']:
            raise ValueError(f'Missing, damaged or unauthentic ISO download: {expected}')
        paths.append(path)
    target = directory / name
    temporary = directory / (name + '.restoring')
    if os.path.lexists(target) or os.path.lexists(temporary):
        raise ValueError('Refusing to replace an existing ISO or temporary file.')
    if shutil.disk_usage(directory).free < iso['uncompressed_size']:
        raise ValueError('Not enough free space for the complete bootable ISO.')
    combined = hashlib.sha256()
    restored = hashlib.sha256()
    compressed_size = written = 0
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=256*1024*1024)
    temporary_identity = None
    try:
        with temporary.open('xb') as output:
            metadata = os.fstat(output.fileno())
            temporary_identity = (metadata.st_dev, metadata.st_ino)
            for path in paths:
                with path.open('rb') as stream:
                    while block := stream.read(1024*1024):
                        combined.update(block)
                        compressed_size += len(block)
                        if decoder.eof:
                            raise ValueError('Unexpected trailing ISO data.')
                        data = decoder.decompress(block, max_length=4*1024*1024)
                        while True:
                            written += len(data)
                            if written > iso['uncompressed_size']:
                                raise ValueError('ISO exceeds its signed size.')
                            restored.update(data)
                            output.write(data)
                            if decoder.eof or decoder.needs_input:
                                break
                            data = decoder.decompress(b'', max_length=4*1024*1024)
            if (not decoder.eof or decoder.unused_data or compressed_size != iso['size']
                    or combined.hexdigest() != iso['sha256'] or written != iso['uncompressed_size']
                    or restored.hexdigest() != iso['uncompressed_sha256']):
                raise ValueError('Restored ISO does not match the signed release.')
        # A hard link publishes the verified file atomically, refusing even a
        # dangling symlink or a destination created after the initial check.
        os.link(temporary, target, follow_symlinks=False)
        temporary.unlink()
    except BaseException:
        if temporary_identity is not None:
            try:
                metadata = temporary.lstat()
                if (metadata.st_dev, metadata.st_ino) == temporary_identity:
                    temporary.unlink()
            except FileNotFoundError:
                pass
        raise
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('.'))
    parser.add_argument('--key', type=Path, default=Path('release-public.pem'), help='Already trusted Titan public signing key')
    args = parser.parse_args()
    try:
        subprocess.run(['openssl', 'pkeyutl', '-verify', '-rawin', '-pubin', '-inkey', str(args.key),
                        '-in', str(args.directory/'manifest.json'), '-sigfile', str(args.directory/'manifest.json.sig')],
                       check=True, capture_output=True, text=True)
        target = restore(args.directory, json.loads((args.directory/'manifest.json').read_text()))
    except (ValueError, KeyError, OSError, lzma.LZMAError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'ISO restoration failed: {error if not isinstance(error, subprocess.CalledProcessError) else "Release signature verification failed."}\n')
    print(f'Verified bootable ISO ready: {target.resolve()}')


if __name__ == '__main__':
    main()

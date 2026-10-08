#!/usr/bin/env python3
"""Verify split, uncompressed source tar bytes without extracting or joining them.

Every indexed source file must occur exactly once. Unlike a permissive tar reader,
this verifier requires the end-of-archive records and reads all remaining padding.
Only index.json, files/<indexed-name>, and their directory entries are allowed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import tarfile


CHUNK = 1024 * 1024
BLOCK = 512
MAX_INDEX = 64 * CHUNK
FILENAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9.+:~_\-]{0,254}')
SHA256 = re.compile(r'[a-f0-9]{64}')


class PartsReader:
    """Read the supplied parts consecutively with bounded reads and one open file."""

    def __init__(self, paths):
        self.paths = iter(Path(path) for path in paths)
        self.current = None
        self.position = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self.current is not None:
            self.current.close()

    def read(self, size):
        if not 0 <= size <= CHUNK:
            raise ValueError('Archive reads must be bounded to one MiB')
        chunks = []
        remaining = size
        while remaining:
            if self.current is None:
                path = next(self.paths, None)
                if path is None:
                    break
                if not stat.S_ISREG(path.lstat().st_mode):
                    raise ValueError('Archive part must be a regular file: ' + str(path))
                self.current = path.open('rb')
            chunk = self.current.read(remaining)
            if not chunk:
                self.current.close()
                self.current = None
                continue
            chunks.append(chunk)
            remaining -= len(chunk)
        result = b''.join(chunks)
        self.position += len(result)
        return result


def exact(reader, size):
    data = reader.read(size)
    if len(data) != size:
        raise ValueError('Truncated source archive')
    return data


def payload(reader, size, collect=False, digest=None):
    """Consume file bytes and block padding; collect only bounded JSON/metadata."""
    pieces = []
    remaining = size
    while remaining:
        data = exact(reader, min(CHUNK, remaining))
        remaining -= len(data)
        if digest is not None:
            digest.update(data)
        if collect:
            pieces.append(data)
    padding = (-size) % BLOCK
    if padding and any(exact(reader, padding)):
        raise ValueError('Nonzero tar member padding')
    return b''.join(pieces) if collect else None


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON object key: ' + key)
        result[key] = value
    return result


def load_json(data):
    def invalid_constant(value):
        raise ValueError('Invalid JSON constant: ' + value)
    return json.loads(data.decode('utf-8'), object_pairs_hook=unique_object,
                      parse_constant=invalid_constant)


def canonical(index):
    return json.dumps(index, sort_keys=True, separators=(',', ':'), allow_nan=False)


def read_index(path):
    pieces = []
    size = 0
    with Path(path).open('rb') as stream:
        while data := stream.read(CHUNK):
            size += len(data)
            if size > MAX_INDEX:
                raise ValueError('Excessive source index')
            pieces.append(data)
    return load_json(b''.join(pieces))


def expected_files(index):
    if not isinstance(index, dict) or not isinstance(index.get('sources'), list) or not index['sources']:
        raise ValueError('Invalid or empty source index')
    expected = {}
    identities = set()
    for source in index['sources']:
        if (not isinstance(source, dict) or source.get('kind') not in ('debian', 'titan-git')
                or not isinstance(source.get('name'), str) or not source['name']
                or not isinstance(source.get('version'), str) or not source['version']
                or not isinstance(source.get('files'), list)):
            raise ValueError('Invalid indexed source')
        identity = (source['kind'], source['name'], source['version'])
        if identity in identities:
            raise ValueError('Duplicate indexed source')
        identities.add(identity)
        if source['kind'] == 'debian' and not source['files']:
            raise ValueError('Debian source has no indexed files')
        names = set()
        for record in source['files']:
            if (not isinstance(record, dict) or set(record) != {'name', 'size', 'sha256'}
                    or not isinstance(record['name'], str) or not FILENAME.fullmatch(record['name'])
                    or type(record['size']) is not int or not 0 <= record['size'] < 2 ** 63
                    or not isinstance(record['sha256'], str) or not SHA256.fullmatch(record['sha256'])):
                raise ValueError('Invalid indexed source file')
            name = record['name']
            if name in names:
                raise ValueError('Duplicate file in indexed source: ' + name)
            names.add(name)
            # Debian source versions can share an unchanged .orig archive.
            if name in expected and expected[name] != record:
                raise ValueError('Conflicting indexed source file: ' + name)
            expected[name] = record
    return expected


def safe_name(name):
    if not name or '\\' in name or '\x00' in name or name.startswith('/'):
        raise ValueError('Unsafe tar member path')
    while name.startswith('./'):
        name = name[2:]
    name = name.rstrip('/')
    if name in ('', '.'):
        return '.'
    if any(part in ('', '.', '..') for part in name.split('/')):
        raise ValueError('Unsafe tar member path: ' + name)
    return name


def parse_pax(data):
    """Accept ordinary per-file POSIX metadata; never links or sparse overrides."""
    result = {}
    position = 0
    allowed = {'path', 'size', 'mtime', 'atime', 'ctime', 'uid', 'gid', 'uname', 'gname'}
    while position < len(data):
        space = data.find(b' ', position)
        if space < 0 or not data[position:space].isdigit() or space - position > 10:
            raise ValueError('Invalid PAX record length')
        length = int(data[position:space])
        end = position + length
        if length < 5 or end > len(data) or space + 1 >= end or data[end - 1:end] != b'\n':
            raise ValueError('Invalid PAX record')
        key, separator, value = data[space + 1:end - 1].partition(b'=')
        key, value = key.decode('utf-8'), value.decode('utf-8')
        if not separator or key not in allowed or key in result or '\x00' in value:
            raise ValueError('Unsupported or duplicate PAX attribute')
        result[key] = value
        position = end
    if not result:
        raise ValueError('Empty PAX extension')
    return result


def verify_archive(index_path, parts):
    if not parts:
        raise ValueError('No source archive parts supplied')
    index = read_index(index_path)
    expected = expected_files(index)
    expected_index = canonical(index)
    seen = set()
    directories = set()
    index_seen = False
    extension = None
    with PartsReader(parts) as reader:
        while True:
            block = exact(reader, BLOCK)
            if not any(block):
                if any(exact(reader, BLOCK)):
                    raise ValueError('Tar end requires two zero blocks')
                if extension is not None:
                    raise ValueError('Tar extension has no following member')
                while data := reader.read(CHUNK):
                    if any(data):
                        raise ValueError('Unexpected data after tar end')
                if reader.position % BLOCK:
                    raise ValueError('Truncated tar block padding')
                break
            try:
                member = tarfile.TarInfo.frombuf(block, 'utf-8', 'strict')
            except (tarfile.HeaderError, UnicodeError, ValueError) as error:
                raise ValueError('Invalid source tar header') from error
            safe_name(member.name)
            if member.size < 0 or member.linkname:
                raise ValueError('Invalid tar member size or link target')
            if member.type in (tarfile.GNUTYPE_LONGNAME, tarfile.XHDTYPE):
                if extension is not None or not 0 < member.size <= CHUNK:
                    raise ValueError('Excessive or repeated tar extension')
                data = payload(reader, member.size, collect=True)
                if member.type == tarfile.GNUTYPE_LONGNAME:
                    if not data.endswith(b'\x00'):
                        raise ValueError('Invalid GNU long name')
                    extension = {'path': data.rstrip(b'\x00').decode('utf-8')}
                else:
                    extension = parse_pax(data)
                continue
            if member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE):
                raise ValueError('Unsupported tar member type: ' + member.name)
            if extension is not None:
                member.name = extension.get('path', member.name)
                if 'size' in extension:
                    size = extension['size']
                    if not re.fullmatch(r'[0-9]{1,19}', size) or int(size) >= 2 ** 63:
                        raise ValueError('Invalid PAX member size')
                    member.size = int(size)
                extension = None
            name = safe_name(member.name)
            if member.isdir():
                if name not in ('.', 'files') or name in directories or member.size:
                    raise ValueError('Unexpected or duplicate tar directory: ' + name)
                directories.add(name)
                continue
            if name == 'index.json':
                if index_seen or member.size > MAX_INDEX:
                    raise ValueError('Duplicate or excessive internal source index')
                internal = load_json(payload(reader, member.size, collect=True))
                if canonical(internal) != expected_index:
                    raise ValueError('Internal and external source indexes differ')
                index_seen = True
                continue
            if not name.startswith('files/') or name[6:] not in expected:
                raise ValueError('Unindexed tar member: ' + name)
            filename = name[6:]
            if filename in seen:
                raise ValueError('Duplicate source tar member: ' + filename)
            record = expected[filename]
            if member.size != record['size']:
                raise ValueError('Source archive size mismatch: ' + filename)
            digest = hashlib.sha256()
            payload(reader, member.size, digest=digest)
            if digest.hexdigest() != record['sha256']:
                raise ValueError('Source archive hash mismatch: ' + filename)
            seen.add(filename)
    if not index_seen or seen != set(expected):
        raise ValueError('Source archive is missing its index or indexed files')
    return {'files': len(seen), 'bytes': sum(item['size'] for item in expected.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', required=True, type=Path)
    parser.add_argument('--parts', required=True, nargs='+', type=Path)
    args = parser.parse_args()
    try:
        result = verify_archive(args.index, args.parts)
    except (OSError, ValueError, UnicodeError) as error:
        parser.exit(1, 'Source archive verification failed: ' + str(error) + '\n')
    print('Verified source archive: {files} files, {bytes} source bytes'.format(**result))


if __name__ == '__main__':
    main()

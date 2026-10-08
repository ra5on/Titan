import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/verify-debian-source-archive.py'
spec = importlib.util.spec_from_file_location('debian_source_archive', SCRIPT)
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


def fixture_index(files):
    return {'format': 'titan-debian-sources-v1', 'titan_source_ref': 'a' * 40,
            'sources': [{'kind': 'debian', 'name': 'example', 'version': '1:2.0-1',
                         'files': [{'name': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                                   for name, data in files.items()]},
                        {'kind': 'titan-git', 'name': 'titan', 'version': 'a' * 40,
                         'url': 'https://github.com/ra5on/Titan/archive/' + 'a' * 40 + '.tar.gz', 'files': []}]}


def tar_bytes(index, files, prefix='', extras=(), format=tarfile.USTAR_FORMAT, internal=None):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w', format=format) as output:
        for name in ('.', 'files'):
            info = tarfile.TarInfo(prefix + name)
            info.type = tarfile.DIRTYPE
            output.addfile(info)
        data = json.dumps(index if internal is None else internal, indent=2).encode()
        entries = [(tarfile.TarInfo(prefix + 'index.json'), data)]
        entries += [(tarfile.TarInfo(prefix + 'files/' + name), data) for name, data in files.items()]
        entries += list(extras)
        for info, data in entries:
            info.size = len(data)
            output.addfile(info, io.BytesIO(data))
    return stream.getvalue()


class DebianSourceArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.files = {'example_2.0.orig.tar.xz': bytes(range(256)) * 12289,
                      'example_2.0-1.dsc': b'Format: 3.0 (quilt)\nSource: example\nVersion: 1:2.0-1\n'}
        self.index = fixture_index(self.files)
        self.index_path = self.root / 'index.json'
        self.index_path.write_text(json.dumps(self.index))

    def parts(self, data, cuts=()):
        positions = (0, *cuts, len(data))
        paths = []
        for number, (start, end) in enumerate(zip(positions, positions[1:])):
            path = self.root / f'part-{number:03}'
            path.write_bytes(data[start:end])
            paths.append(path)
        return paths

    def verify(self, data, cuts=()):
        return archive.verify_archive(self.index_path, self.parts(data, cuts))

    def test_valid_archive_spans_headers_payloads_and_multiple_mib_chunks(self):
        data = tar_bytes(self.index, self.files, prefix='./')
        result = self.verify(data, (91, 1007, 4099, archive.CHUNK + 13, 2 * archive.CHUNK + 23, len(data) - 999))
        self.assertEqual(result, {'files': 2, 'bytes': sum(map(len, self.files.values()))})

    def test_shared_identical_source_archive_is_stored_only_once(self):
        shared = copy.deepcopy(self.index['sources'][0])
        shared['version'] = '1:2.0-2'
        self.index['sources'].append(shared)
        self.index_path.write_text(json.dumps(self.index))
        self.assertEqual(self.verify(tar_bytes(self.index, self.files))['files'], 2)

    def test_internal_json_can_differ_in_whitespace_and_key_order(self):
        reordered = dict(reversed(list(self.index.items())))
        self.assertEqual(self.verify(tar_bytes(self.index, self.files, internal=reordered))['files'], 2)

    def test_missing_last_part_with_source_bytes_fails(self):
        data = tar_bytes(self.index, self.files)
        paths = self.parts(data, (1007, len(data) // 2))
        with self.assertRaisesRegex(ValueError, 'Truncated'):
            archive.verify_archive(self.index_path, paths[:-1])

    def test_missing_or_incomplete_tar_end_fails_even_when_source_files_are_complete(self):
        data = tar_bytes(self.index, self.files)
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as source:
            last = source.getmember('files/example_2.0-1.dsc')
            end = last.offset_data + ((last.size + 511) // 512) * 512
        for truncated in (data[:end], data[:end + 511], data[:end + 512], data[:-1]):
            with self.subTest(length=len(truncated)), self.assertRaises(ValueError):
                self.verify(truncated)

    def test_truncated_member_content_fails(self):
        data = tar_bytes(self.index, self.files)
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as source:
            offset = source.getmember('files/example_2.0.orig.tar.xz').offset_data
        with self.assertRaisesRegex(ValueError, 'Truncated'):
            self.verify(data[:offset + 32])

    def test_source_content_and_size_mismatch_fail(self):
        for content in (b'X' + self.files['example_2.0.orig.tar.xz'][1:], b'short'):
            changed = dict(self.files, **{'example_2.0.orig.tar.xz': content})
            with self.subTest(length=len(content)), self.assertRaisesRegex(ValueError, 'mismatch'):
                self.verify(tar_bytes(self.index, changed))

    def test_duplicate_file_and_duplicate_index_fail(self):
        entries = [(tarfile.TarInfo('files/example_2.0-1.dsc'), self.files['example_2.0-1.dsc']),
                   (tarfile.TarInfo('./index.json'), json.dumps(self.index).encode())]
        for entry in entries:
            with self.subTest(name=entry[0].name), self.assertRaisesRegex(ValueError, 'Duplicate'):
                self.verify(tar_bytes(self.index, self.files, extras=[entry]))

    def test_extra_files_directories_and_missing_indexed_file_fail(self):
        for name in ('unrelated', 'files/unlisted.dsc', 'other/index.json'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.verify(tar_bytes(self.index, self.files, extras=[(tarfile.TarInfo(name), b'extra')]))
        directory = tarfile.TarInfo('extra'); directory.type = tarfile.DIRTYPE
        with self.assertRaises(ValueError):
            self.verify(tar_bytes(self.index, self.files, extras=[(directory, b'')]))
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.verify(tar_bytes(self.index, {'example_2.0-1.dsc': self.files['example_2.0-1.dsc']}))

    def test_symlinks_hardlinks_devices_fifo_and_global_pax_are_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE,
                     tarfile.FIFOTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_SPARSE):
            info = tarfile.TarInfo('files/unsafe')
            info.type = kind
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                info.linkname = '/etc/passwd'
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.verify(tar_bytes(self.index, self.files, extras=[(info, b'')]))

    def test_absolute_backslash_dotdot_and_nested_paths_fail(self):
        for name in ('../outside', './files/../outside', '/index.json', 'files//bad',
                     'files/./bad', 'files/sub/bad', 'files\\bad'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.verify(tar_bytes(self.index, self.files, extras=[(tarfile.TarInfo(name), b'bad')]))

    def test_internal_index_mismatch_and_duplicate_json_keys_fail(self):
        changed = copy.deepcopy(self.index); changed['titan_source_ref'] = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'indexes differ'):
            self.verify(tar_bytes(self.index, self.files, internal=changed))
        self.index_path.write_text('{"sources": [], "sources": []}')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON'):
            self.verify(tar_bytes(self.index, self.files))

    def test_index_rejects_unsafe_conflicting_and_invalid_file_records(self):
        def traversal(v): v['sources'][0]['files'][0]['name'] = '../outside'
        def boolean_size(v): v['sources'][0]['files'][0]['size'] = True
        def bad_hash(v): v['sources'][0]['files'][0]['sha256'] = 'bad'
        def duplicate(v): v['sources'][0]['files'].append(copy.deepcopy(v['sources'][0]['files'][0]))
        def conflict(v):
            source = copy.deepcopy(v['sources'][0]); source['version'] = '1:2.0-2'
            source['files'][0]['sha256'] = 'f' * 64; v['sources'].append(source)
        for mutate in (traversal, boolean_size, bad_hash, duplicate, conflict):
            value = copy.deepcopy(self.index); mutate(value)
            with self.subTest(mutation=mutate.__name__), self.assertRaises(ValueError):
                archive.expected_files(value)

    def test_long_names_work_in_gnu_and_pax_formats(self):
        self.files = {'a' * 150 + '.tar.xz': b'long-name source bytes'}
        self.index = fixture_index(self.files)
        self.index_path.write_text(json.dumps(self.index))
        for format in (tarfile.GNU_FORMAT, tarfile.PAX_FORMAT):
            with self.subTest(format=format):
                self.assertEqual(self.verify(tar_bytes(self.index, self.files, format=format), (1025, 3333))['files'], 1)

    def test_pax_cannot_hide_path_traversal_links_or_sparse_members(self):
        for attributes in ({'path': '../outside'}, {'linkpath': '/etc/passwd'}, {'GNU.sparse.size': '2'}):
            info = tarfile.TarInfo('placeholder'); info.pax_headers = attributes
            with self.subTest(attributes=attributes), self.assertRaises(ValueError):
                self.verify(tar_bytes(self.index, self.files, format=tarfile.PAX_FORMAT, extras=[(info, b'xx')]))

    def test_header_corruption_and_nonzero_or_partial_trailing_data_fail(self):
        data = tar_bytes(self.index, self.files)
        damaged = b'X' + data[1:]
        for value in (damaged, data + b'X' * 512, data + b'\0', data + tar_bytes(self.index, self.files)):
            with self.subTest(length=len(value)), self.assertRaises(ValueError):
                self.verify(value)

    def test_every_underlying_read_is_bounded_and_inputs_are_not_modified(self):
        paths = self.parts(tar_bytes(self.index, self.files), (1007, archive.CHUNK + 13))
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (self.index_path, *paths)}
        original_open = Path.open
        class Guarded:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *_): self.close()
            def close(self): self.stream.close()
            def read(self, size=-1):
                self_case.assertGreaterEqual(size, 0)
                self_case.assertLessEqual(size, archive.CHUNK)
                return self.stream.read(size)
        self_case = self
        def guarded_open(path, mode='r', *args, **kwargs):
            self.assertEqual(mode, 'rb')
            return Guarded(original_open(path, mode, *args, **kwargs))
        with patch.object(Path, 'open', guarded_open):
            self.assertEqual(archive.verify_archive(self.index_path, paths)['files'], 2)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})

    def test_cli_reports_success_and_failure_without_extracting(self):
        paths = self.parts(tar_bytes(self.index, self.files), (1007,))
        command = ['python3', str(SCRIPT), '--index', str(self.index_path), '--parts', *(str(p) for p in paths)]
        good = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertIn('Verified source archive: 2 files', good.stdout)
        paths[-1].write_bytes(paths[-1].read_bytes()[:-1024 * 1024])
        bad = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn('verification failed', bad.stderr)
        self.assertEqual({p.name for p in self.root.iterdir()}, {'index.json', 'part-000', 'part-001'})


if __name__ == '__main__':
    unittest.main()

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace


spec = importlib.util.spec_from_file_location('debian_source_collection', Path(__file__).resolve().parents[1] / 'scripts/collect-debian-sources.py')
sources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sources)
REF = 'a' * 40


def package(name='foo', version='1.0-1+b2', source='foo-source', source_version='1.0-1', built='', static='', arch='amd64', status='installed'):
    return '\t'.join((name, version, arch, status, source, source_version, built, static)) + '\n'


def write_source(directory, name='foo-source', version='1.0-1', signed=False, archive='foo-source_1.0.orig.tar.xz', data=b'original source archive bytes'):
    directory.mkdir(exist_ok=True)
    (directory / archive).write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    descriptor = (f'Format: 3.0 (quilt)\nSource: {name}\nVersion: {version}\nChecksums-Sha256:\n'
                  f' {digest} {len(data)} {archive}\n')
    if signed:
        descriptor = ('-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\n' + descriptor +
                      '\n-----BEGIN PGP SIGNATURE-----\nfixture\n-----END PGP SIGNATURE-----\n')
    (directory / (name + '_' + version.replace(':', '') + '.dsc')).write_text(descriptor)


def fixture_index():
    packages = sources.parse_packages(package(built='embedded (= 2:3.0-1)', static='static-lib (= 4.0-2)') +
                                      package(sources.TITAN_PACKAGE, '0.6.0+debian1'), REF)
    archive = {'name': 'a.tar.xz', 'size': 17, 'sha256': 'b' * 64}
    records = []
    for name, version in sources.source_keys(packages):
        if name == 'titan':
            records.append({'name': name, 'version': version, 'kind': 'titan-git',
                            'url': 'https://github.com/ra5on/Titan/archive/' + REF + '.tar.gz', 'files': []})
        else:
            records.append({'name': name, 'version': version, 'kind': 'debian',
                            'files': [copy.deepcopy(archive), {'name': name + '.dsc', 'size': 35, 'sha256': 'c' * 64}]})
    value = {'format': sources.FORMAT, 'titan_source_ref': REF, 'generated_at': '2026-10-08T12:00:00Z',
             'repositories': copy.deepcopy(sources.REPOSITORIES), 'snapshot_repositories': [],
             'packages': packages, 'sources': records}
    inventory = {'format': 'titan-debian-packages-v1', 'suite': 'trixie', 'architecture': 'amd64',
                 'packages': [{key: item[key] for key in ('name', 'version', 'architecture')} for item in packages]}
    return value, inventory


class DebianSourceCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # APT and downloads are already mocked in collection unit tests. Their
        # Debian keyring fixture must not depend on the Ubuntu runner's packages.
        self.real_is_file = Path.is_file
        keyring = patch.object(Path, 'is_file',
                               new=lambda path: str(path) == sources.KEYRING or self.real_is_file(path))
        keyring.start()
        self.addCleanup(keyring.stop)
        self.available = patch.object(sources, 'available_sources', return_value={('foo-source', '1.0-1'), ('foo-source', '1.0-2')})
        self.available.start()
        self.addCleanup(self.available.stop)

    def test_dpkg_source_version_binNMU_epoch_and_both_embedded_relationships(self):
        raw = package('libfoo:amd64', '2:1.0-1+b2', 'foo', '2:1.0-1',
                      'embedded (= 3.0-1), embedded (= 3.0-1)', 'static-lib (= 4:2.0+ds-2)')
        raw += package('removed', status='config-files')
        parsed = sources.parse_packages(raw, REF)
        self.assertEqual(parsed[0]['source_version'], '2:1.0-1')
        self.assertEqual(parsed[0]['built_using'], [{'source': 'embedded', 'version': '3.0-1'}])
        self.assertEqual(parsed[0]['static_built_using'], [{'source': 'static-lib', 'version': '4:2.0+ds-2'}])
        self.assertEqual(sources.source_keys(parsed), [('embedded', '3.0-1'), ('foo', '2:1.0-1'), ('static-lib', '4:2.0+ds-2')])

    def test_titan_is_documented_by_commit_not_fetched_as_a_debian_source(self):
        parsed = sources.parse_packages(package(sources.TITAN_PACKAGE), REF)
        self.assertEqual((parsed[0]['source'], parsed[0]['source_version']), ('titan', REF))

    def test_binary_fallback_only_when_source_fields_are_omitted(self):
        parsed = sources.parse_packages(package('foo:amd64', '1.0-1', '', ''), REF)
        self.assertEqual((parsed[0]['source'], parsed[0]['source_version']), ('foo', '1.0-1'))

    def test_invalid_package_and_non_exact_embedded_sources_are_rejected(self):
        cases = [package(source='../foo'), package(arch='arm64'), package(version='--unsafe'),
                 package(built='embedded (>= 1)'), package(static='embedded (= 1),'),
                 package() + package(), 'incomplete\n', '']
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                sources.parse_packages(value, REF)

    def test_unpacked_source_archives_are_never_required_and_original_bytes_are_hashed(self):
        directory = self.root / 'download'
        write_source(directory, signed=True)
        records = sources.inspect_download(directory, 'foo-source', '1.0-1')
        self.assertEqual(len(records), 2)
        for record in records:
            self.assertEqual(record['sha256'], hashlib.sha256((directory / record['name']).read_bytes()).hexdigest())

    def test_missing_changed_extra_symlink_and_wrong_source_downloads_fail_closed(self):
        def missing(path): (path / 'foo-source_1.0.orig.tar.xz').unlink()
        def changed(path): (path / 'foo-source_1.0.orig.tar.xz').write_bytes(b'changed')
        def extra(path): (path / 'unrelated').write_bytes(b'extra')
        def symlink(path):
            target = path / 'foo-source_1.0.orig.tar.xz'
            target.unlink(); target.symlink_to('/etc/passwd')
        def wrong_source(path):
            target = next(path.glob('*.dsc')); target.write_text(target.read_text().replace('Source: foo-source', 'Source: another'))
        def wrong_version(path):
            target = next(path.glob('*.dsc')); target.write_text(target.read_text().replace('Version: 1.0-1', 'Version: 1.0-2'))
        def duplicate(path):
            target = next(path.glob('*.dsc')); target.write_text(target.read_text() + 'Source: foo-source\n')
        def traversal(path):
            target = next(path.glob('*.dsc')); target.write_text(target.read_text().replace('foo-source_1.0.orig.tar.xz', '../outside'))
        for index, mutate in enumerate((missing, changed, extra, symlink, wrong_source, wrong_version, duplicate, traversal)):
            directory = self.root / str(index)
            write_source(directory)
            mutate(directory)
            with self.subTest(mutation=mutate.__name__), self.assertRaises(ValueError):
                sources.inspect_download(directory, 'foo-source', '1.0-1')

    def test_apt_configuration_is_isolated_official_signed_and_rejects_insecure_sources(self):
        with patch.dict(sources.os.environ, {'APT_CONFIG': '/unsafe/apt.conf'}):
            environment = sources.apt_environment(self.root / 'apt')
        config = Path(environment['APT_CONFIG']).read_text()
        repositories = (self.root / 'apt/sources.sources').read_text()
        self.assertIn('Dir::Etc::main "/dev/null"', config)
        self.assertIn('Dir::Etc::sourceparts "-"', config)
        self.assertIn('AllowUnauthenticated "false"', config)
        self.assertIn('AllowInsecureRepositories "false"', config)
        self.assertIn('APT::Update::Error-Mode "any"', config)
        self.assertEqual(repositories.count('Types: deb-src'), 2)
        self.assertEqual(repositories.count('Signed-By: ' + sources.KEYRING), 2)
        self.assertNotIn('Trusted:', repositories)
        self.assertNotIn('Types: deb\n', repositories)
        self.assertNotIn('/unsafe/', config)

    def test_download_requests_exact_source_version_without_compiling_or_extracting(self):
        directory = self.root / 'download'
        def download(command, **kwargs):
            self.assertEqual(command, ['apt-get', '--yes', '--download-only', '--only-source', 'source', 'foo-source=1.0-1'])
            self.assertEqual(kwargs['cwd'], directory)
            self.assertTrue(kwargs['check'])
            write_source(directory)
        with patch.object(sources.subprocess, 'run', side_effect=download):
            records = sources.download_source('foo-source', '1.0-1', directory, {})
        self.assertEqual(len(records), 2)

    def test_host_verify_accepts_complete_shared_source_files_and_embedded_sources(self):
        value, inventory = fixture_index()
        self.assertIs(sources.verify_index(value, inventory, REF), value)

    def test_host_verify_rejects_missing_extra_conflicting_or_untrusted_source_coverage(self):
        def omit_source(v): v['sources'].pop(0)
        def omit_binary(v): v['packages'].pop(0)
        def change_binary(v): v['packages'][0]['version'] = '1.0-2'
        def change_arch(v): v['packages'][0]['architecture'] = 'arm64'
        def change_ref(v): v['titan_source_ref'] = 'b' * 40
        def change_titan(v): v['packages'][1]['source_version'] = 'b' * 40
        def exempt_debian(v): v['packages'][0].update(source='titan', source_version=REF)
        def missing_built_using(v): v['packages'][0]['built_using'] = []
        def wrong_built_using(v): v['packages'][0]['built_using'][0]['version'] = '3.0-2'
        def missing_static_source(v): v['sources'] = [s for s in v['sources'] if s['name'] != 'static-lib']
        def missing_dsc(v): v['sources'][0]['files'][1]['name'] = 'a.diff.gz'
        def traversal(v): v['sources'][0]['files'][0]['name'] = '../a.tar.xz'
        def bad_hash(v): v['sources'][0]['files'][0]['sha256'] = 'not-a-hash'
        def conflicting(v): v['sources'][0]['files'][0]['sha256'] = 'd' * 64
        def duplicate_source(v): v['sources'].append(copy.deepcopy(v['sources'][0]))
        def unsafe_repo(v): v['repositories'][0]['uri'] = 'https://example.com/debian'
        def undated(v): v['generated_at'] = '2026-10-08T12:00:00'
        for mutate in (omit_source, omit_binary, change_binary, change_arch, change_ref, change_titan, exempt_debian,
                       missing_built_using, wrong_built_using, missing_static_source, missing_dsc, traversal, bad_hash,
                       conflicting, duplicate_source, unsafe_repo, undated):
            value, inventory = fixture_index(); mutate(value)
            with self.subTest(mutation=mutate.__name__), self.assertRaises(ValueError):
                sources.verify_index(value, inventory, REF)

    def test_collection_is_transactional_dedupes_source_versions_and_preserves_bytes(self):
        raw = package('foo-a', source='foo-source') + package('foo-b', source='foo-source') + package(sources.TITAN_PACKAGE)
        output = self.root / 'result'
        calls = []
        def download(name, version, directory, environment):
            calls.append((name, version))
            write_source(directory, name, version)
            return sources.inspect_download(directory, name, version)
        with patch.object(sources.subprocess, 'check_output', return_value=raw), \
                patch.object(sources.subprocess, 'run') as run, patch.object(sources, 'download_source', side_effect=download):
            result = sources.collect(output, REF)
        self.assertEqual(calls, [('foo-source', '1.0-1')])
        self.assertEqual(run.call_args.args[0], ['apt-get', 'update'])
        self.assertEqual(json.loads((output / 'index.json').read_text()), result)
        self.assertEqual((output / 'files/foo-source_1.0.orig.tar.xz').read_bytes(), b'original source archive bytes')
        self.assertEqual({p.name for p in output.iterdir()}, {'index.json', 'files'})
        self.assertFalse(any(p.name.startswith('.titan-source-collect-') for p in self.root.iterdir()))

    def test_missing_exact_source_never_produces_publishable_output(self):
        output = self.root / 'failed'
        with patch.object(sources.subprocess, 'check_output', return_value=package()), \
                patch.object(sources.subprocess, 'run'), \
                patch.object(sources, 'download_source', side_effect=subprocess.CalledProcessError(100, 'apt-get')):
            with self.assertRaises(subprocess.CalledProcessError): sources.collect(output, REF)
        self.assertFalse(output.exists())
        self.assertFalse(any(p.name.startswith('.titan-source-collect-') for p in self.root.iterdir()))

    def test_collection_without_debian_keyring_stops_before_apt_or_output(self):
        output = self.root / 'missing-keyring'
        with patch.object(sources.subprocess, 'check_output', return_value=package()), \
                patch.object(Path, 'is_file',
                             new=lambda path: str(path) != sources.KEYRING and self.real_is_file(path)), \
                patch.object(sources.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'Official Debian archive keyring is required'):
                sources.collect(output, REF)
        run.assert_not_called()
        self.assertFalse(output.exists())
        self.assertFalse(any(p.name.startswith('.titan-source-collect-') for p in self.root.iterdir()))

    def test_shared_orig_archive_is_stored_once_across_exact_source_versions(self):
        raw = package(built='foo-source (= 1.0-2)')
        output = self.root / 'shared'
        def download(name, version, directory, environment):
            write_source(directory, name, version)
            return sources.inspect_download(directory, name, version)
        with patch.object(sources.subprocess, 'check_output', return_value=raw), \
                patch.object(sources.subprocess, 'run'), patch.object(sources, 'download_source', side_effect=download):
            result = sources.collect(output, REF)
        self.assertEqual(len(result['sources']), 2)
        self.assertEqual(len(list((output / 'files').iterdir())), 3)
        self.assertEqual({s['version'] for s in result['sources']}, {'1.0-1', '1.0-2'})

    def test_conflicting_archive_names_never_produce_publishable_output(self):
        output = self.root / 'conflict'
        def download(name, version, directory, environment):
            write_source(directory, name, version, data=version.encode())
            return sources.inspect_download(directory, name, version)
        with patch.object(sources.subprocess, 'check_output', return_value=package(built='foo-source (= 1.0-2)')), \
                patch.object(sources.subprocess, 'run'), patch.object(sources, 'download_source', side_effect=download):
            with self.assertRaisesRegex(ValueError, 'Conflicting source filenames'):
                sources.collect(output, REF)
        self.assertFalse(output.exists())

    def test_collection_refuses_existing_output_and_inventory_mismatch(self):
        existing = self.root / 'existing'; existing.mkdir(); (existing / 'keep').write_text('preserved')
        with self.assertRaises(ValueError): sources.collect(existing, REF)
        self.assertEqual((existing / 'keep').read_text(), 'preserved')
        value, inventory = fixture_index()
        output = self.root / 'mismatch'
        def download(name, version, directory, environment):
            write_source(directory, name, version)
            return sources.inspect_download(directory, name, version)
        with patch.object(sources.subprocess, 'check_output', return_value=package()), \
                patch.object(sources.subprocess, 'run'), patch.object(sources, 'download_source', side_effect=download):
            with self.assertRaises(ValueError): sources.collect(output, REF, inventory)
        self.assertFalse(output.exists())

    def test_host_cli_is_read_only_and_requires_matching_inventory(self):
        value, inventory = fixture_index()
        index_path, inventory_path = self.root / 'index.json', self.root / 'inventory.json'
        index_path.write_text(json.dumps(value)); inventory_path.write_text(json.dumps(inventory))
        with patch('sys.argv', ['collector', '--verify-index', str(index_path), '--inventory', str(inventory_path), '--titan-source-ref', REF]), \
                patch.object(sources, 'collect', side_effect=AssertionError('must not collect')), patch('builtins.print'):
            sources.main()
        self.assertEqual(json.loads(index_path.read_text()), value)

    def test_snapshot_metadata_selects_official_archive_time_but_never_authenticates_archives(self):
        value = {'package': 'foo-source', 'version': '1.0-1', 'fileinfo': {
            'a' * 40: [{'archive_name': 'debian', 'first_seen': '20250305T084405Z',
                        'name': 'foo-source_1.0-1.dsc', 'path': '/pool/main/f/foo-source'}]}}
        response = SimpleNamespace(geturl=lambda: 'https://snapshot.debian.org/mr/package/foo-source/1.0-1/srcfiles?fileinfo=1',
                                   read=lambda limit: json.dumps(value).encode())
        class Response:
            def __enter__(self): return response
            def __exit__(self, *args): pass
        with patch.object(sources.urllib.request, 'urlopen', return_value=Response()) as request:
            candidates = sources.snapshot_candidates('foo-source', '1.0-1')
        self.assertEqual(request.call_args.args[0], 'https://snapshot.debian.org/mr/package/foo-source/1.0-1/srcfiles?fileinfo=1')
        self.assertEqual(candidates[0], {'uri': 'https://snapshot.debian.org/archive/debian/20250305T084405Z/',
                                        'suites': ['sid'], 'components': ['main'], 'signed_by': sources.KEYRING,
                                        'check_valid_until': False})

    def test_snapshot_metadata_identity_unknown_archive_and_redirect_fail_closed(self):
        base = {'package': 'foo-source', 'version': '1.0-1', 'fileinfo': {
            'a' * 40: [{'archive_name': 'debian', 'first_seen': '20250305T084405Z',
                        'name': 'foo-source_1.0-1.dsc', 'path': '/pool/main/f/foo-source'}]}}
        cases = [(dict(base, version='1.0-2'), 'https://snapshot.debian.org/'),
                 (base, 'https://example.com/'), (base, 'http://snapshot.debian.org/')]
        for field, invalid in (('first_seen', '../../bad'), ('archive_name', 'other'), ('path', '/outside/main/f/foo-source')):
            value = copy.deepcopy(base); value['fileinfo']['a' * 40][0][field] = invalid
            cases.append((value, 'https://snapshot.debian.org/'))
        for value, location in cases:
            response = SimpleNamespace(geturl=lambda: location, read=lambda limit: json.dumps(value).encode())
            class Response:
                def __enter__(self): return response
                def __exit__(self, *args): pass
            with self.subTest(value=value, location=location), \
                    patch.object(sources.urllib.request, 'urlopen', return_value=Response()), self.assertRaises(ValueError):
                sources.snapshot_candidates('foo-source', '1.0-1')

    def test_historical_source_requires_authenticated_apt_update_and_deduplicates_repository(self):
        repo = {'uri': 'https://snapshot.debian.org/archive/debian/20250305T084405Z/',
                'suites': ['sid'], 'components': ['main'], 'signed_by': sources.KEYRING, 'check_valid_until': False}
        historical = sources.SnapshotSources(self.root / 'history')
        def download(name, version, directory, environment):
            config = Path(environment['APT_CONFIG'])
            self.assertIn('Check-Valid-Until: no', (config.parent / 'sources.sources').read_text())
            self.assertIn('AllowUnauthenticated "false"', config.read_text())
            write_source(directory, name, version)
            return sources.inspect_download(directory, name, version)
        with patch.object(sources, 'snapshot_candidates', return_value=[repo]), \
                patch.object(sources.subprocess, 'run') as run, patch.object(sources, 'download_source', side_effect=download):
            historical.download('foo-source', '1.0-1', self.root / 'download1')
            historical.download('foo-source', '1.0-2', self.root / 'download2')
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ['apt-get', 'update'])
        self.assertTrue(run.call_args.kwargs['check'])
        self.assertEqual(list(historical.records.values())[0]['sources'], [
            {'name': 'foo-source', 'version': '1.0-1'}, {'name': 'foo-source', 'version': '1.0-2'}])
        sources.validate_snapshot_repositories(list(historical.records.values()), {('foo-source', '1.0-1'), ('foo-source', '1.0-2')})

    def test_failed_historical_apt_authentication_never_downloads_or_records_a_source(self):
        repo = {'uri': 'https://snapshot.debian.org/archive/debian/20250305T084405Z/',
                'suites': ['sid'], 'components': ['main'], 'signed_by': sources.KEYRING, 'check_valid_until': False}
        historical = sources.SnapshotSources(self.root / 'history')
        with patch.object(sources, 'snapshot_candidates', return_value=[repo]), \
                patch.object(sources.subprocess, 'run', side_effect=subprocess.CalledProcessError(100, 'apt-get')), \
                patch.object(sources, 'download_source') as download:
            with self.assertRaisesRegex(ValueError, 'No authenticated historical'):
                historical.download('foo-source', '1.0-1', self.root / 'not-created')
        download.assert_not_called()
        self.assertEqual(historical.records, {})

    def test_collection_indexes_authenticated_historical_source_and_cleans_apt_state(self):
        repo = {'uri': 'https://snapshot.debian.org/archive/debian/20250305T084405Z/',
                'suites': ['sid'], 'components': ['main'], 'signed_by': sources.KEYRING, 'check_valid_until': False}
        def download(name, version, directory, environment):
            write_source(directory, name, version)
            return sources.inspect_download(directory, name, version)
        output = self.root / 'historical-result'
        with patch.object(sources.subprocess, 'check_output', return_value=package()), \
                patch.object(sources.subprocess, 'run') as run, \
                patch.object(sources, 'available_sources', side_effect=[set(), {('foo-source', '1.0-1')}]), \
                patch.object(sources, 'snapshot_candidates', return_value=[repo]), \
                patch.object(sources, 'download_source', side_effect=download):
            result = sources.collect(output, REF)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(result['snapshot_repositories'], [dict(repo, sources=[{'name': 'foo-source', 'version': '1.0-1'}])])
        self.assertEqual({p.name for p in output.iterdir()}, {'files', 'index.json'})
        self.assertFalse(any(p.name.startswith('.titan-source-collect-') for p in self.root.iterdir()))

    def test_host_verification_rejects_unofficial_or_unmapped_historical_sources(self):
        repo = {'uri': 'https://snapshot.debian.org/archive/debian/20250305T084405Z/',
                'suites': ['sid'], 'components': ['main'], 'signed_by': sources.KEYRING,
                'check_valid_until': False, 'sources': [{'name': 'foo-source', 'version': '1.0-1'}]}
        value, inventory = fixture_index(); value['snapshot_repositories'] = [repo]
        sources.verify_index(value, inventory, REF)
        for field, invalid in (('uri', 'https://example.com/archive/debian/20250305T084405Z/'),
                               ('uri', 'https://snapshot.debian.org/archive/debian/../../'),
                               ('signed_by', '/tmp/untrusted.gpg'), ('suites', ['arbitrary']),
                               ('check_valid_until', True), ('components', ['other']),
                               ('sources', [{'name': 'foo-source', 'version': '1.0-2'}])):
            changed = copy.deepcopy(value); changed['snapshot_repositories'][0][field] = invalid
            with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                sources.verify_index(changed, inventory, REF)


if __name__ == '__main__':
    unittest.main()

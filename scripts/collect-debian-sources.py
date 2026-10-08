#!/usr/bin/env python3
"""Archive exact Debian sources in a disposable guest; never unpack or rebuild them.

The completed output contains index.json and files/*. Collection is transactional:
there is no completed output/index when a source is missing or verification fails.
Host verification reads the index only; archive-part hashes are verified separately.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import urllib.parse
import urllib.request


FORMAT = 'titan-debian-sources-v1'
TITAN_PACKAGE = 'titan-debian-preview'
KEYRING = '/usr/share/keyrings/debian-archive-keyring.gpg'
NAME = re.compile(r'[a-z0-9][a-z0-9+.-]{0,127}')
BINARY_NAME = re.compile(r'[a-z0-9][a-z0-9+.-]{0,127}(?::[a-z0-9_-]{1,32})?')
VERSION = re.compile(r'[0-9][0-9A-Za-z.+:~\-]{0,255}')
REF = re.compile(r'[a-f0-9]{40}')
FILENAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9.+:~_\-]{0,254}')
SHA256 = re.compile(r'[a-f0-9]{64}')
SNAPSHOT_URI = re.compile(r'https://snapshot\.debian\.org/archive/(debian|debian-security)/([0-9]{8}T[0-9]{6}Z)/')
SNAPSHOT_SUITES = {'debian': {'sid', 'trixie', 'trixie-updates', 'bookworm', 'bookworm-updates', 'bullseye', 'bullseye-updates'},
                   'debian-security': {'trixie-security', 'bookworm-security', 'bullseye-security'}}
RELATION = re.compile(r'([a-z0-9][a-z0-9+.-]{0,127})\s*\(\s*=\s*([0-9][0-9A-Za-z.+:~\-]{0,255})\s*\)')
REPOSITORIES = [
    {'uri': 'https://deb.debian.org/debian', 'suites': ['trixie', 'trixie-updates'],
     'components': ['main', 'contrib', 'non-free', 'non-free-firmware'], 'signed_by': KEYRING},
    {'uri': 'https://security.debian.org/debian-security', 'suites': ['trixie-security'],
     'components': ['main', 'contrib', 'non-free', 'non-free-firmware'], 'signed_by': KEYRING},
]
QUERY = ('${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Status}\t'
         '${source:Package}\t${source:Version}\t${Built-Using}\t${Static-Built-Using}\n')


@contextmanager
def libguestfs_network(resolver_path=Path('/etc/resolv.conf')):
    """Temporarily use libguestfs's appliance DNS during this build session only.

    The runtime resolver can be a dangling systemd-resolved symlink because the
    NAS services do not run in virt-customize. Never write through that symlink.
    resolver_path is injectable for isolated tests, not a CLI option.
    """
    resolver = Path(resolver_path)
    if resolver.is_symlink():
        original = ('symlink', os.readlink(resolver), None)
    elif resolver.exists():
        if not resolver.is_file():
            raise ValueError('Appliance resolver must be a regular file or symlink')
        original = ('file', resolver.read_bytes(), stat.S_IMODE(resolver.stat().st_mode))
    else:
        original = ('missing', None, None)
    changed = False
    try:
        default_route = subprocess.check_output(['ip', '-4', 'route', 'show', 'default'], text=True)
        if not default_route.strip():
            subprocess.run(['ip', 'link', 'set', 'eth0', 'up'], check=True)
            subprocess.run(['ip', 'address', 'replace', '169.254.2.15/16', 'dev', 'eth0'], check=True)
            subprocess.run(['ip', 'route', 'replace', 'default', 'via', '169.254.2.2', 'dev', 'eth0'], check=True)
        resolver.unlink(missing_ok=True)
        changed = True
        resolver.write_bytes(b'nameserver 169.254.2.3\n')
        resolver.chmod(0o644)
        yield
    finally:
        if changed:
            resolver.unlink(missing_ok=True)
            if original[0] == 'symlink':
                resolver.symlink_to(original[1])
            elif original[0] == 'file':
                resolver.write_bytes(original[1])
                resolver.chmod(original[2])


def require(pattern, value, label):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError('Invalid ' + label)
    return value


def relationships(raw):
    if not raw.strip():
        return []
    found = set()
    for item in raw.split(','):
        match = RELATION.fullmatch(item.strip())
        if not match:
            raise ValueError('Built-Using requires exact source versions: ' + item)
        found.add(match.groups())
    return [{'source': name, 'version': version} for name, version in sorted(found)]


def parse_packages(raw, titan_ref):
    require(REF, titan_ref, 'Titan source commit')
    packages = []
    seen = set()
    for line in raw.splitlines():
        fields = line.split('\t')
        if len(fields) != 8:
            raise ValueError('Incomplete dpkg source metadata')
        name, version, arch, status, source, source_version, built, static = fields
        if status != 'installed':
            continue
        require(BINARY_NAME, name, 'binary package name')
        require(VERSION, version, 'binary package version')
        if arch not in ('amd64', 'all') or name in seen:
            raise ValueError('Unsupported or duplicate binary package')
        seen.add(name)
        if name == TITAN_PACKAGE:
            source, source_version = 'titan', titan_ref
        else:
            # dpkg's virtual fields resolve omitted Source fields and binNMUs.
            # Never replace an explicitly supplied source version with the binary version.
            source = require(NAME, source or name.split(':')[0], 'source package name')
            source_version = require(VERSION, source_version or version, 'source package version')
        packages.append({'name': name, 'version': version, 'architecture': arch,
                         'source': source, 'source_version': source_version,
                         'built_using': relationships(built), 'static_built_using': relationships(static)})
    if not packages or len(packages) > 5000:
        raise ValueError('Empty or excessive Debian package inventory')
    return sorted(packages, key=lambda item: item['name'])


def source_keys(packages):
    keys = set()
    for item in packages:
        keys.add((item['source'], item['source_version']))
        for field in ('built_using', 'static_built_using'):
            keys.update((part['source'], part['version']) for part in item[field])
    return sorted(keys)


def file_digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def dsc_fields(path):
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Excessive Debian source descriptor')
    text = path.read_text(encoding='utf-8')
    if text.startswith('-----BEGIN PGP SIGNED MESSAGE-----\n'):
        _, separator, text = text.partition('\n\n')
        if not separator or '\n-----BEGIN PGP SIGNATURE-----' not in text:
            raise ValueError('Malformed signed Debian source descriptor')
        text = text.split('\n-----BEGIN PGP SIGNATURE-----', 1)[0]
        text = '\n'.join(line[2:] if line.startswith('- ') else line for line in text.splitlines())
    message = Parser().parsestr(text)
    for field in ('Source', 'Version', 'Checksums-Sha256'):
        if len(message.get_all(field, [])) != 1:
            raise ValueError('Missing or duplicate source descriptor field: ' + field)
    return message


def inspect_download(directory, name, version):
    paths = sorted(directory.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ValueError('Unexpected source download entry')
    descriptors = [path for path in paths if path.name.endswith('.dsc')]
    if len(descriptors) != 1:
        raise ValueError('Expected exactly one Debian source descriptor')
    dsc = descriptors[0]
    fields = dsc_fields(dsc)
    if fields['Source'].strip() != name or fields['Version'].strip() != version:
        raise ValueError('Downloaded source does not match installed source version')
    records = {}
    for line in fields['Checksums-Sha256'].splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 3 or not SHA256.fullmatch(parts[0]) or not parts[1].isdigit():
            raise ValueError('Invalid source checksum record')
        digest, size, filename = parts
        require(FILENAME, filename, 'source filename')
        if filename in records or filename == dsc.name:
            raise ValueError('Duplicate source checksum record')
        path = directory / filename
        if path.is_symlink() or not path.is_file() or path.stat().st_size != int(size) or file_digest(path) != digest:
            raise ValueError('Source archive checksum/size mismatch: ' + filename)
        records[filename] = {'name': filename, 'size': int(size), 'sha256': digest}
    if not records or set(records) | {dsc.name} != {path.name for path in paths}:
        raise ValueError('Missing or unreferenced source archive')
    require(FILENAME, dsc.name, 'source descriptor filename')
    records[dsc.name] = {'name': dsc.name, 'size': dsc.stat().st_size, 'sha256': file_digest(dsc)}
    return [records[key] for key in sorted(records)]


def apt_environment(work, repositories=None):
    """Use no system APT config, sources, hooks or mutable host lists/cache."""
    work.mkdir()
    work.chmod(0o755)
    for child in ('empty-conf', 'lists', 'lists/partial', 'cache', 'cache/archives', 'cache/archives/partial'):
        (work / child).mkdir()
    source_text = ''
    for repo in REPOSITORIES if repositories is None else repositories:
        source_text += ('Types: deb-src\nURIs: ' + repo['uri'] + '\nSuites: ' + ' '.join(repo['suites']) +
                        '\nComponents: ' + ' '.join(repo['components']) + '\nSigned-By: ' + KEYRING + '\n')
        if repo.get('check_valid_until') is False:
            source_text += 'Check-Valid-Until: no\n'
        source_text += '\n'
    sources = work / 'sources.sources'
    sources.write_text(source_text)
    config = work / 'apt.conf'
    config.write_text('\n'.join([
        'Dir::Etc::main "/dev/null";', f'Dir::Etc::parts "{work / "empty-conf"}";',
        f'Dir::Etc::sourcelist "{sources}";', 'Dir::Etc::sourceparts "-";',
        f'Dir::State::lists "{work / "lists"}";', f'Dir::Cache "{work / "cache"}";',
        'Dir::Cache::pkgcache "";', 'Dir::Cache::srcpkgcache "";',
        'APT::Get::AllowUnauthenticated "false";', 'Acquire::AllowInsecureRepositories "false";',
        'Acquire::AllowDowngradeToInsecureRepositories "false";', 'Acquire::Check-Valid-Until "true";',
        'APT::Update::Error-Mode "any";', 'Acquire::Retries "3";', 'Acquire::Languages "none";',
        'Acquire::http::Timeout "30";', 'Acquire::https::Timeout "30";',
    ]) + '\n')
    return dict(os.environ, APT_CONFIG=str(config), LC_ALL='C.UTF-8')


def download_source(name, version, directory, environment):
    require(NAME, name, 'source package name')
    require(VERSION, version, 'source package version')
    directory.mkdir()
    subprocess.run(['apt-get', '--yes', '--download-only', '--only-source', 'source', name + '=' + version],
                   cwd=directory, env=environment, check=True)
    return inspect_download(directory, name, version)


def available_sources(names, environment):
    """Read only the source versions present in the authenticated APT lists."""
    try:
        raw = subprocess.check_output(['apt-cache', 'showsrc', '--only-source'] + sorted(set(names)),
                                      env=environment, text=True)
    except subprocess.CalledProcessError as exc:
        # apt-cache can return 100 for a missing name while reporting other names.
        if exc.returncode != 100 or not isinstance(exc.output, str):
            raise
        raw = exc.output
    available = set()
    for paragraph in raw.strip().split('\n\n'):
        fields = Parser().parsestr(paragraph)
        if fields.get('Package') and fields.get('Version'):
            available.add((require(NAME, fields['Package'], 'APT source name'),
                           require(VERSION, fields['Version'], 'APT source version')))
    return available


def snapshot_candidates(name, version):
    """HTTPS metadata selects times only. APT subsequently authenticates each source.

    Snapshot's SHA1 file IDs are deliberately not used as archive authentication.
    """
    require(NAME, name, 'source package name')
    require(VERSION, version, 'source package version')
    url = ('https://snapshot.debian.org/mr/package/' + urllib.parse.quote(name, safe='') + '/' +
           urllib.parse.quote(version, safe='') + '/srcfiles?fileinfo=1')
    with urllib.request.urlopen(url, timeout=30) as response:
        location = urllib.parse.urlsplit(response.geturl())
        if location.scheme != 'https' or location.hostname != 'snapshot.debian.org':
            raise ValueError('Unexpected Snapshot metadata redirect')
        raw = response.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('Excessive Snapshot metadata')
    value = json.loads(raw)
    if (not isinstance(value, dict) or value.get('package') != name or value.get('version') != version
            or not isinstance(value.get('fileinfo'), dict) or len(value['fileinfo']) > 1000):
        raise ValueError('Snapshot package identity/metadata mismatch')
    candidates = {}
    for records in value['fileinfo'].values():
        if not isinstance(records, list) or len(records) > 1000:
            raise ValueError('Invalid Snapshot file metadata')
        for entry in records:
            if not isinstance(entry, dict):
                raise ValueError('Invalid Snapshot file metadata record')
            if not str(entry.get('name', '')).endswith('.dsc'):
                continue
            archive = entry.get('archive_name')
            if archive not in SNAPSHOT_SUITES:
                continue
            stamp = entry.get('first_seen', entry.get('run', ''))
            if not isinstance(stamp, str) or not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z', stamp):
                raise ValueError('Invalid Snapshot timestamp')
            datetime.strptime(stamp, '%Y%m%dT%H%M%SZ')
            component = re.fullmatch(r'/pool/(?:updates/)?(main|contrib|non-free|non-free-firmware)/[^/]+/[^/]+', str(entry.get('path', '')))
            if not component:
                raise ValueError('Invalid Snapshot Debian pool path')
            stable = next((suite for release, suite in ((13, 'trixie'), (12, 'bookworm'), (11, 'bullseye'))
                           if re.search(r'(?:\+|~)deb' + str(release) + r'u', version)), None)
            if archive == 'debian-security':
                suites = [stable + '-security'] if stable else ['trixie-security']
            else:
                suites = [stable, stable + '-updates', 'sid'] if stable else ['sid', 'trixie']
            for suite in suites:
                key = (archive, stamp, suite, component.group(1))
                candidates[key] = {'uri': 'https://snapshot.debian.org/archive/' + archive + '/' + stamp + '/',
                                   'suites': [suite], 'components': [component.group(1)],
                                   'signed_by': KEYRING, 'check_valid_until': False}
    if not candidates:
        raise ValueError('No official Snapshot source descriptor metadata for ' + name + '=' + version)
    # Keep suite preference (e.g. sid for a normal unstable upload) deterministic.
    return list(candidates.values())


class SnapshotSources:
    def __init__(self, work):
        self.work = work
        work.mkdir()
        self.environments = {}
        self.records = {}

    def download(self, name, version, directory):
        for repo in snapshot_candidates(name, version):
            key = (repo['uri'], tuple(repo['suites']), tuple(repo['components']))
            if key not in self.environments:
                environment = apt_environment(self.work / str(len(self.environments)), [repo])
                self.environments[key] = None
                try:
                    subprocess.run(['apt-get', 'update'], env=environment, check=True)
                except subprocess.CalledProcessError:
                    continue
                self.environments[key] = environment
            environment = self.environments[key]
            if environment is None or (name, version) not in available_sources([name], environment):
                continue
            records = download_source(name, version, directory, environment)
            if key not in self.records:
                self.records[key] = dict(repo, sources=[])
            self.records[key]['sources'].append({'name': name, 'version': version})
            return records
        raise ValueError('No authenticated historical Debian source: ' + name + '=' + version)


def validate_snapshot_repositories(repositories, indexed_sources):
    if not isinstance(repositories, list) or len(repositories) > 15000:
        raise ValueError('Invalid historical repository list')
    seen, mapped = set(), set()
    for repo in repositories:
        if not isinstance(repo, dict) or set(repo) != {'uri', 'suites', 'components', 'signed_by', 'check_valid_until', 'sources'}:
            raise ValueError('Invalid historical repository')
        match = SNAPSHOT_URI.fullmatch(str(repo['uri']))
        if (not match or repo['signed_by'] != KEYRING or repo['check_valid_until'] is not False
                or not isinstance(repo['suites'], list) or len(repo['suites']) != 1
                or repo['suites'][0] not in SNAPSHOT_SUITES[match.group(1)]
                or not isinstance(repo['components'], list) or len(repo['components']) != 1
                or repo['components'][0] not in REPOSITORIES[0]['components']):
            raise ValueError('Unofficial/unauthenticated historical repository')
        datetime.strptime(match.group(2), '%Y%m%dT%H%M%SZ')
        key = (repo['uri'], repo['suites'][0], repo['components'][0])
        if key in seen or not isinstance(repo['sources'], list) or not repo['sources']:
            raise ValueError('Duplicate or unused historical repository')
        seen.add(key)
        for source in repo['sources']:
            if not isinstance(source, dict) or set(source) != {'name', 'version'}:
                raise ValueError('Invalid historical source mapping')
            pair = (require(NAME, source['name'], 'historical source name'),
                    require(VERSION, source['version'], 'historical source version'))
            if pair not in indexed_sources or pair in mapped or pair[0] == 'titan':
                raise ValueError('Unexpected or duplicate historical source mapping')
            mapped.add(pair)


def validate_relations(items):
    if not isinstance(items, list) or len(items) > 5000:
        raise ValueError('Invalid Built-Using list')
    values = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {'source', 'version'}:
            raise ValueError('Invalid Built-Using record')
        values.append((require(NAME, item['source'], 'Built-Using source'),
                       require(VERSION, item['version'], 'Built-Using version')))
    if len(set(values)) != len(values):
        raise ValueError('Duplicate Built-Using record')


def verify_index(index, inventory, titan_ref):
    """Fail closed on incomplete coverage; the caller separately verifies archive bytes."""
    require(REF, titan_ref, 'Titan source commit')
    if (not isinstance(index, dict) or set(index) != {
            'format', 'titan_source_ref', 'generated_at', 'repositories', 'snapshot_repositories', 'packages', 'sources'}
            or index['format'] != FORMAT or index['titan_source_ref'] != titan_ref
            or index['repositories'] != REPOSITORIES):
        raise ValueError('Invalid Debian source index identity/repositories')
    stamp = datetime.fromisoformat(index['generated_at'].replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Source inventory must be dated')
    if (not isinstance(inventory, dict) or inventory.get('format') != 'titan-debian-packages-v1'
            or inventory.get('suite') != 'trixie' or inventory.get('architecture') != 'amd64'
            or not isinstance(inventory.get('packages'), list)):
        raise ValueError('Invalid binary package inventory')
    expected = set()
    for item in inventory['packages']:
        if not isinstance(item, dict) or set(item) != {'name', 'version', 'architecture'}:
            raise ValueError('Invalid binary package inventory record')
        expected.add((require(BINARY_NAME, item['name'], 'binary package name'),
                      require(VERSION, item['version'], 'binary package version'), item['architecture']))
        if item['architecture'] not in ('amd64', 'all'):
            raise ValueError('Unsupported binary package architecture')
    if not expected or len(expected) != len(inventory['packages']):
        raise ValueError('Empty or duplicate binary package inventory')
    packages = index['packages']
    if not isinstance(packages, list) or not 1 <= len(packages) <= 5000:
        raise ValueError('Invalid indexed package list')
    actual = set()
    names = set()
    for item in packages:
        if not isinstance(item, dict) or set(item) != {
                'name', 'version', 'architecture', 'source', 'source_version', 'built_using', 'static_built_using'}:
            raise ValueError('Invalid indexed package record')
        name = require(BINARY_NAME, item['name'], 'binary package name')
        if name in names:
            raise ValueError('Duplicate indexed binary package')
        names.add(name)
        actual.add((name, require(VERSION, item['version'], 'binary package version'), item['architecture']))
        if name == TITAN_PACKAGE:
            if (item['source'], item['source_version']) != ('titan', titan_ref):
                raise ValueError('Titan source commit mismatch')
        else:
            require(NAME, item['source'], 'source name')
            require(VERSION, item['source_version'], 'source version')
            if item['source'] == 'titan':
                raise ValueError('Debian package cannot use Titan source exemption')
        for field in ('built_using', 'static_built_using'):
            validate_relations(item[field])
    if expected != actual:
        raise ValueError('Source index does not cover the exact binary package inventory')
    sources = index['sources']
    if not isinstance(sources, list) or not 1 <= len(sources) <= 15000:
        raise ValueError('Invalid source list')
    seen = set()
    files = {}
    for item in sources:
        if not isinstance(item, dict):
            raise ValueError('Invalid source record')
        name, version = item.get('name'), item.get('version')
        if name == 'titan':
            if (set(item) != {'name', 'version', 'kind', 'url', 'files'} or version != titan_ref
                    or item['kind'] != 'titan-git' or item['files'] != []
                    or item['url'] != 'https://github.com/ra5on/Titan/archive/' + titan_ref + '.tar.gz'):
                raise ValueError('Invalid original Titan source record')
        else:
            if set(item) != {'name', 'version', 'kind', 'files'} or item['kind'] != 'debian':
                raise ValueError('Invalid Debian source record')
            require(NAME, name, 'source name')
            require(VERSION, version, 'source version')
            if not isinstance(item['files'], list) or not 2 <= len(item['files']) <= 1000:
                raise ValueError('Incomplete Debian source files')
            source_names = set()
            for entry in item['files']:
                if not isinstance(entry, dict) or set(entry) != {'name', 'size', 'sha256'}:
                    raise ValueError('Invalid indexed source file')
                filename = require(FILENAME, entry['name'], 'source filename')
                require(SHA256, entry['sha256'], 'source SHA256')
                if type(entry['size']) is not int or not 1 <= entry['size'] <= 100 * 1024**3 or filename in source_names:
                    raise ValueError('Invalid or duplicate indexed source file size/name')
                source_names.add(filename)
                if filename in files and files[filename] != entry:
                    raise ValueError('Conflicting source filenames')
                files[filename] = entry
            if sum(filename.endswith('.dsc') for filename in source_names) != 1:
                raise ValueError('Missing or duplicate indexed source descriptor')
        if (name, version) in seen:
            raise ValueError('Duplicate indexed source')
        seen.add((name, version))
    if seen != set(source_keys(packages)):
        raise ValueError('Missing or unexpected source/Built-Using coverage')
    validate_snapshot_repositories(index['snapshot_repositories'], seen)
    return index


def collect(output, titan_ref, inventory=None):
    require(REF, titan_ref, 'Titan source commit')
    output = Path(output).absolute()
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError('Source output must be a new directory in an existing parent')
    raw = subprocess.check_output(['dpkg-query', '-W', '-f=' + QUERY], text=True, env=dict(os.environ, LC_ALL='C.UTF-8'))
    packages = parse_packages(raw, titan_ref)
    if inventory is None:
        inventory = {'format': 'titan-debian-packages-v1', 'suite': 'trixie', 'architecture': 'amd64',
                     'packages': [{key: item[key] for key in ('name', 'version', 'architecture')} for item in packages]}
    if not Path(KEYRING).is_file():
        raise ValueError('Official Debian archive keyring is required')
    with tempfile.TemporaryDirectory(prefix='.titan-source-collect-', dir=output.parent) as temp:
        work = Path(temp)
        work.chmod(0o755)
        payload = work / 'payload'
        files = payload / 'files'
        files.mkdir(parents=True)
        downloads = work / 'downloads'
        downloads.mkdir()
        environment = apt_environment(work / 'apt')
        subprocess.run(['apt-get', 'update'], env=environment, check=True)
        required = source_keys(packages)
        names = [name for name, version in required if name != 'titan']
        current = available_sources(names, environment) if names else set()
        historical = SnapshotSources(work / 'historical-apt')
        sources, known_files = [], {}
        for position, (name, version) in enumerate(required):
            if (name, version) == ('titan', titan_ref):
                sources.append({'name': name, 'version': version, 'kind': 'titan-git',
                                'url': 'https://github.com/ra5on/Titan/archive/' + titan_ref + '.tar.gz', 'files': []})
                continue
            print('Collecting Debian source ' + name + '=' + version, flush=True)
            directory = downloads / str(position)
            if (name, version) in current:
                records = download_source(name, version, directory, environment)
            else:
                print('Exact version absent from current Sources; checking authenticated Snapshot.', flush=True)
                records = historical.download(name, version, directory)
            for record in records:
                if record['name'] in known_files:
                    if known_files[record['name']] != record:
                        raise ValueError('Conflicting source filenames: ' + record['name'])
                else:
                    shutil.copyfile(directory / record['name'], files / record['name'])
                    known_files[record['name']] = record
            shutil.rmtree(directory)
            sources.append({'name': name, 'version': version, 'kind': 'debian', 'files': records})
        index = {'format': FORMAT, 'titan_source_ref': titan_ref,
                 'generated_at': datetime.now(timezone.utc).isoformat(), 'repositories': REPOSITORIES,
                 'snapshot_repositories': list(historical.records.values()),
                 'packages': packages, 'sources': sources}
        verify_index(index, inventory, titan_ref)
        (payload / 'index.json').write_text(json.dumps(index, indent=2, sort_keys=True) + '\n')
        payload.rename(output)
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--output', type=Path)
    modes.add_argument('--verify-index', type=Path)
    parser.add_argument('--inventory', type=Path)
    parser.add_argument('--titan-source-ref', required=True)
    parser.add_argument('--confirm-disposable-guest', action='store_true')
    parser.add_argument('--libguestfs-network', action='store_true',
                        help='temporarily prepare the disposable libguestfs appliance network during collection')
    args = parser.parse_args()
    if args.libguestfs_network and (args.verify_index or not args.confirm_disposable_guest):
        parser.error('--libguestfs-network requires --output and --confirm-disposable-guest')
    inventory = json.loads(args.inventory.read_text()) if args.inventory else None
    if args.verify_index:
        if inventory is None:
            parser.error('--verify-index requires --inventory')
        index = verify_index(json.loads(args.verify_index.read_text()), inventory, args.titan_source_ref)
        print('Verified source coverage for ' + str(len(index['packages'])) + ' binary packages.')
    else:
        if not args.confirm_disposable_guest:
            parser.error('collection requires --confirm-disposable-guest')
        if args.libguestfs_network:
            with libguestfs_network():
                index = collect(args.output, args.titan_source_ref, inventory)
        else:
            index = collect(args.output, args.titan_source_ref, inventory)
        print('Archived ' + str(len(index['sources'])) + ' exact source records in ' + str(args.output))


if __name__ == '__main__':
    main()

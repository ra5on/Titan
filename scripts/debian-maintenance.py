#!/usr/bin/env python3
"""Plan independent Debian maintenance from signed published Titan releases."""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from titan import __version__, __release_stage__, updates, debian_updates
updates.PUBLIC_KEY = ROOT / 'packaging/release-public.pem'
REPOSITORY = 'ra5on/Titan'
spec = importlib.util.spec_from_file_location('package_state', ROOT / 'scripts/debian-package-state.py')
packages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packages)


def api(path, token=None):
    return updates.strict_json(updates.fetch('https://api.github.com/repos/' + REPOSITORY + '/' + path, token))


def release_list(token=None):
    result = []
    for page in range(1, 6):
        batch = api(f'releases?per_page=100&page={page}', token)
        if not isinstance(batch, list):
            raise ValueError('Invalid public release list')
        result.extend(item for item in batch if isinstance(item, dict) and not item.get('draft'))
        if len(batch) < 100:
            break
    return result


def checked_release(release, token=None):
    manifest, assets = updates.verified_release(release, token)
    debian_updates.validate_manifest(manifest)
    if updates.version(manifest['version']) != updates.version(release['tag_name']):
        raise ValueError('Signed release version differs from GitHub tag')
    return manifest, assets


def checked_inventory(release, token=None, verified=None):
    manifest, assets = verified if verified is not None else checked_release(release, token)
    for name in ('debian-packages.json', 'SHA256SUMS', 'SHA256SUMS.sig'):
        if name not in assets:
            raise ValueError('Release predates package maintenance support')
    sums = updates.fetch(assets['SHA256SUMS'], token, binary=True, maximum=32768)
    signature = updates.fetch(assets['SHA256SUMS.sig'], token, binary=True, maximum=1024)
    with tempfile.TemporaryDirectory(prefix='titan-package-proof-') as temporary:
        root = Path(temporary)
        (root/'sums').write_bytes(sums); (root/'signature').write_bytes(signature)
        subprocess.run(['openssl', 'pkeyutl', '-verify', '-rawin', '-pubin', '-inkey', str(updates.PUBLIC_KEY),
                        '-in', str(root/'sums'), '-sigfile', str(root/'signature')], check=True, capture_output=True)
    records = {}
    for line in sums.decode('ascii').splitlines():
        match = re.fullmatch(r'([a-f0-9]{64})  ([A-Za-z0-9_.+-]+)', line)
        if not match or match[2] in records:
            raise ValueError('Invalid signed checksum list')
        records[match[2]] = match[1]
    data = updates.fetch(assets['debian-packages.json'], token, binary=True, maximum=1024*1024)
    if hashlib.sha256(data).hexdigest() != records.get('debian-packages.json'):
        raise ValueError('Published package inventory checksum mismatch')
    return manifest, packages.validate(updates.strict_json(data))


def allocate_version(app_version, stage, releases, previous=None):
    """Global stable IDs; Alpha/Beta keep their maintenance branch counters."""
    values = []
    for release in releases:
        try:
            values.append(updates.version(release['tag_name']))
        except (KeyError, updates.Error):
            continue
    app = updates.version(app_version)[:3]
    if stage in ('alpha', 'beta'):
        base = updates.version(previous['version'])[:3] if previous else app
        if not previous:
            highest = max(values, default=(0, 0, 0, 0, 0))
            if highest[:3] > base or (highest[:3] == base and highest[3] > updates.STAGES[stage]):
                base = highest[:2] + (highest[2] + 1,)
        counter = max((v[4] for v in values if v[:3] == base and v[3] == updates.STAGES[stage]), default=0) + 1
        return '.'.join(map(str, base)) + '-' + stage + '.' + str(counter)
    if stage != 'stable':
        raise ValueError('Unsupported release stage')
    highest = max((v[:3] for v in values), default=(0, 0, 0))
    base = app if app > highest else highest[:2] + (highest[2] + 1,)
    return '.'.join(map(str, base))


def supported_sources(releases, token=None):
    """Keep the two most recent frozen Titan sources per stage, at most six."""
    groups = {}
    for release in releases:
        if not any(a.get('name') == 'debian-packages.json' for a in release.get('assets', []) if isinstance(a, dict)):
            continue
        manifest, assets = checked_release(release, token)
        metadata = updates.release_metadata(manifest)
        key = (metadata['titan_stage'], metadata['titan_version'], metadata['titan_source_commit'])
        value = {'release': release, 'manifest': manifest, 'assets': assets, 'metadata': metadata}
        if key not in groups or updates.version(manifest['version']) > updates.version(groups[key]['manifest']['version']):
            groups[key] = value
    result = []
    for stage in ('alpha', 'beta', 'stable'):
        entries = [v for k, v in groups.items() if k[0] == stage]
        # The source's commit date distinguishes multiple Titan prereleases with
        # the same bare application version; OS-only release dates do not.
        for value in entries:
            commit = api('git/commits/' + value['metadata']['titan_source_commit'], token)
            if commit.get('sha') != value['metadata']['titan_source_commit']:
                raise ValueError('Application source commit differs from GitHub response')
            stamp = datetime.fromisoformat(commit['committer']['date'].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('Application source commit has no timezone')
            value['source_date'] = stamp.timestamp()
        entries.sort(key=lambda v: (updates.version(v['metadata']['titan_version'])[:3], v['source_date']), reverse=True)
        result.extend(entries[:2])
    # Fetch and hash full inventories only for the retained signed sources.
    # Hundreds of older releases need only their small signed manifest checked.
    for value in result:
        _, value['inventory'] = checked_inventory(value['release'], token, verified=(value['manifest'], value['assets']))
    return result


def prepare_plan(directory, token=None):
    releases = release_list(token)
    sources = supported_sources(releases, token)
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT/'scripts/debian-package-state.py', directory/'package-state.py')
    for i, value in enumerate(sources):
        (directory/f'inventory-{i}.json').write_text(json.dumps(value['inventory']))
    if sources:
        # Only this new disposable container receives APT writes; no host/NAS APT.
        code = ('set -eu; apt-get -o APT::Update::Error-Mode=any -o Acquire::Retries=3 update; '
                'apt-get install -y --no-install-recommends python3 python3-apt ca-certificates; '
                'rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; '
                'printf "Types: deb\\nURIs: https://deb.debian.org/debian\\nSuites: trixie trixie-updates\\nComponents: main contrib non-free non-free-firmware\\nSigned-By: /usr/share/keyrings/debian-archive-keyring.gpg\\n\\nTypes: deb\\nURIs: https://security.debian.org/debian-security\\nSuites: trixie-security\\nComponents: main contrib non-free non-free-firmware\\nSigned-By: /usr/share/keyrings/debian-archive-keyring.gpg\\n" > /etc/apt/sources.list.d/titan-debian.sources; '
                'apt-get -o APT::Update::Error-Mode=any -o Acquire::Retries=3 update; '
                'for f in /work/inventory-*.json; do n=${f##*/}; '
                'python3 /work/package-state.py probe --before "$f" --output "/work/probe-$n"; done')
        subprocess.run(['docker', 'run', '--rm', '--memory=1g', '--pids-limit=256', '-v', str(directory.resolve()) + ':/work', 'debian:13-slim',
                        '/bin/sh', '-c', code], check=True)
    matrix = []
    for i, value in enumerate(sources):
        report = json.loads((directory/f'probe-inventory-{i}.json').read_text())
        updates.release_metadata({**value['manifest'], **report})
        if report['security_summary']['total_packages'] == 0:
            continue
        meta, manifest = value['metadata'], value['manifest']
        version = allocate_version(meta['titan_version'], meta['titan_stage'], releases, previous=manifest)
        releases.append({'tag_name': 'v' + version})
        matrix.append({'version': version, 'source_ref': meta['titan_source_commit'],
                       'app_version': meta['titan_version'], 'app_stage': meta['titan_stage'],
                       'system_revision': meta['system_revision'] + 1, 'previous_tag': value['release']['tag_name'],
                       'changes': report['security_summary']['total_packages'],
                       'security_changes': report['security_summary']['security_packages']})
    return {'include': matrix}


def fetch_previous(tag, directory, token=None, bundle=False):
    updates.version(tag)
    release = api('releases/tags/' + tag, token)
    manifest, inventory = checked_inventory(release, token)
    directory.mkdir(parents=True, exist_ok=True)
    (directory/'previous-packages.json').write_text(json.dumps(inventory))
    (directory/'previous-manifest.json').write_text(json.dumps(manifest))
    if not bundle:
        return manifest
    _, assets = checked_release(release, token)
    info = manifest['bundle']
    path = directory/'previous.raucb'
    if path.exists() or path.is_symlink():
        raise ValueError('Previous bundle output already exists')
    headers = {'Accept': 'application/octet-stream', 'User-Agent': 'Titan-Debian-Maintenance'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    import urllib.request
    request = urllib.request.Request(assets[info['name']], headers=headers)
    digest = hashlib.sha256(); size = 0; deadline = time.monotonic() + 1800
    descriptor, temporary = tempfile.mkstemp(prefix='previous-', suffix='.partial', dir=directory)
    partial = Path(temporary)
    try:
        with os.fdopen(descriptor, 'wb') as target:
            with urllib.request.build_opener(updates.Redirect()).open(request, timeout=30) as response:
                while chunk := response.read(1024*1024):
                    size += len(chunk)
                    if size > info['size'] or time.monotonic() > deadline:
                        raise ValueError('Baseline bundle exceeds signed size/time limit')
                    digest.update(chunk); target.write(chunk)
            if size != info['size'] or digest.hexdigest() != info['sha256']:
                raise ValueError('Baseline bundle hash differs from signed manifest')
        os.link(partial, path)
    finally:
        partial.unlink(missing_ok=True)
    return manifest


def output(name, value):
    target = os.environ.get('GITHUB_OUTPUT')
    if target:
        with open(target, 'a') as stream:
            stream.write(name + '=' + value + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['plan', 'titan', 'previous', 'previous-bundle'])
    parser.add_argument('--directory', type=Path, default=ROOT/'dist/debian-input')
    parser.add_argument('--tag')
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('Requires disposable GitHub Actions runner')
    token = os.environ.get('GH_TOKEN')
    if args.mode == 'titan':
        version = allocate_version(__version__, __release_stage__, release_list(token))
        output('version', version); output('app_version', __version__); output('app_stage', __release_stage__)
        print('Next Titan system release: ' + version)
    elif args.mode in ('previous', 'previous-bundle'):
        if not args.tag:
            parser.error('--tag is required')
        manifest = fetch_previous(args.tag, args.directory, token, bundle=args.mode == 'previous-bundle')
        print('Verified frozen baseline: ' + manifest['version'])
    else:
        # GitHub's schedule timezone handles DST. A delayed runner must still
        # perform the planned daily check instead of silently dropping it.
        matrix = prepare_plan(args.directory, token)
        encoded = json.dumps(matrix, separators=(',', ':'))
        output('matrix', encoded); output('available', 'true' if matrix['include'] else 'false')
        print(encoded)


if __name__ == '__main__':
    main()

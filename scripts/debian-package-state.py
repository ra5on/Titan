#!/usr/bin/env python3
"""Read Debian package state in a disposable builder; never update a live NAS."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

FORMAT = 'titan-debian-packages-v1'
NAME = re.compile(r'[a-z0-9][a-z0-9+.-]{0,127}(?::[a-z0-9_-]{1,32})?')
VERSION = re.compile(r'[0-9A-Za-z.+:~+-]{1,256}')
MAX_PREVIEW_PACKAGES = 20
MAX_PREVIEW_BYTES = 3072
MAX_INVENTORY_BYTES = 1024 * 1024


def validate(value):
    if (not isinstance(value, dict) or set(value) != {'format', 'suite', 'architecture', 'generated_at', 'packages'}
            or value['format'] != FORMAT or value['suite'] != 'trixie' or value['architecture'] != 'amd64'
            or not isinstance(value['generated_at'], str) or not isinstance(value['packages'], list)
            or not 1 <= len(value['packages']) <= 5000):
        raise ValueError('Invalid Debian package inventory')
    names = set()
    for item in value['packages']:
        if (not isinstance(item, dict) or set(item) != {'name', 'version', 'architecture'}
                or not isinstance(item['name'], str) or not NAME.fullmatch(item['name']) or item['name'] in names
                or not isinstance(item['version'], str) or not VERSION.fullmatch(item['version'])
                or item['architecture'] not in ('amd64', 'all')):
            raise ValueError('Invalid Debian package record')
        names.add(item['name'])
    stamp = datetime.fromisoformat(value['generated_at'].replace('Z', '+00:00'))
    if stamp.tzinfo is None or len(json.dumps(value, indent=2).encode()) > MAX_INVENTORY_BYTES:
        raise ValueError('Unbounded or undated Debian package inventory')
    return value


def inventory():
    raw = subprocess.check_output(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Status}\n'], text=True)
    packages = []
    for line in raw.splitlines():
        name, version, architecture, status = line.split('\t')
        if status == 'installed':
            packages.append({'name': name, 'version': version, 'architecture': architecture})
    return validate({'format': FORMAT, 'suite': 'trixie', 'architecture': 'amd64',
                     'generated_at': datetime.now(timezone.utc).isoformat(), 'packages': sorted(packages, key=lambda p: p['name'])})


def security_origin(version):
    return bool(version and any(origin.trusted and origin.origin == 'Debian' and origin.label in ('Debian', 'Debian-Security')
                                and (origin.label == 'Debian-Security' or origin.archive.endswith('-security'))
                                for origin in version.origins))


def candidates(value, cache, compare):
    """Only newer trusted official Debian candidates trigger a maintenance build."""
    changes = []
    for item in validate(value)['packages']:
        name = item['name']
        if name not in cache or cache[name].candidate is None:
            continue
        candidate = cache[name].candidate
        if compare(candidate.version, item['version']) <= 0:
            continue
        origins = [origin for origin in candidate.origins if origin.trusted]
        if not origins or any(origin.origin != 'Debian' or origin.label not in ('Debian', 'Debian-Security') for origin in origins):
            raise ValueError('Non-Debian package candidate refused: ' + name)
        changes.append({'name': name, 'old_version': item['version'], 'new_version': candidate.version,
                        'security': security_origin(candidate)})
    return changes


def summary(changes):
    changes = sorted(changes, key=lambda item: (not item['security'], item['name']))
    preview = []
    for item in changes:
        proposed = preview + [item]
        if len(proposed) > MAX_PREVIEW_PACKAGES or len(json.dumps(proposed, indent=2).encode()) > MAX_PREVIEW_BYTES:
            break
        preview = proposed
    return {'package_changes': preview, 'security_summary': {
        'total_packages': len(changes), 'security_packages': sum(item['security'] for item in changes),
        'checked_at': datetime.now(timezone.utc).isoformat()}}


def actual_changes(before, after, cache, compare=None):
    old = {item['name']: item['version'] for item in validate(before)['packages']}
    changes = []
    for item in validate(after)['packages']:
        previous = old.get(item['name'])
        if previous == item['version'] or item['name'] == 'titan-debian-preview':
            continue
        if previous is not None and compare is not None and compare(item['version'], previous) < 0:
            raise ValueError('Debian package downgrade refused: ' + item['name'])
        candidate = cache[item['name']].candidate if item['name'] in cache else None
        security = previous is not None and candidate is not None and candidate.version == item['version'] and security_origin(candidate)
        changes.append({'name': item['name'], 'old_version': previous, 'new_version': item['version'], 'security': security})
    return summary(changes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['inventory', 'probe', 'changes', 'guard'])
    parser.add_argument('--before', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.mode == 'inventory':
        result = inventory()
    else:
        import apt
        import apt_pkg
        cache = apt.Cache()
        if args.mode == 'probe':
            result = summary(candidates(json.loads(args.before.read_text()), cache, apt_pkg.version_compare))
        elif args.mode == 'guard':
            remaining = candidates(inventory(), cache, apt_pkg.version_compare)
            if remaining:
                raise ValueError('Debian packages remain outdated after build: ' + ', '.join(item['name'] for item in remaining[:20]))
            result = {'ok': True, 'remaining_upgrades': 0}
        else:
            result = actual_changes(json.loads(args.before.read_text()), inventory(), cache, apt_pkg.version_compare)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()

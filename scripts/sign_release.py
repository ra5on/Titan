#!/usr/bin/env python3
"""Sign an OCI update or IMG release, preserving legacy complete ISO downloads."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from titan import __version__, __release_stage__


def fingerprint(path):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    size = path.stat().st_size
    if size >= 2147483648:
        raise ValueError("A release download exceeds GitHub's per-file limit.")
    return {'name': path.name, 'sha256': digest, 'size': size}


def iso_metadata(directory, description, report):
    name = description.get('filename', '')
    if (description.get('format') != 'titan-iso-download-v1' or description.get('compression') != 'xz'
            or not re.fullmatch(r'titan-[0-9A-Za-z.-]+-x86_64\.iso', name)):
        raise ValueError('Invalid ISO download description.')
    parts = description.get('parts', [])
    if not parts or len(parts) > 100:
        raise ValueError('Missing ISO download files.')
    expected = [name+'.xz'] if len(parts) == 1 and parts[0].get('name') == name+'.xz' else [name+f'.xz.part-{i:03}' for i in range(1,len(parts)+1)]
    combined = hashlib.sha256()
    total = 0
    verified = []
    for part, expected_name in zip(parts, expected):
        if part.get('name') != expected_name:
            raise ValueError('Unsafe or unordered ISO filenames.')
        path = directory / expected_name
        if path.is_symlink() or path.resolve().parent != directory.resolve() or not path.is_file():
            raise ValueError('ISO files must be regular files in the release directory.')
        actual = fingerprint(path)
        if actual != part:
            raise ValueError('ISO part differs from its recorded checksum or size.')
        verified.append(actual)
        with path.open('rb') as stream:
            while block := stream.read(1024*1024):
                combined.update(block)
                total += len(block)
    if total != description.get('size') or combined.hexdigest() != description.get('sha256'):
        raise ValueError('Combined ISO download checksum or size is incorrect.')
    if (not isinstance(description.get('uncompressed_size'), int) or description['uncompressed_size'] <= 0
            or not re.fullmatch('[a-f0-9]{64}', str(description.get('uncompressed_sha256', '')))):
        raise ValueError('Missing restored ISO checksum or size.')
    statuses = {}
    for field in ('boot_test','install_test','system_boot_test','runtime_test'):
        value = report.get(field)
        if value not in ('passed','failed','not-run'):
            raise ValueError('Missing explicit ISO verification outcome.')
        statuses[field] = value
    return {**description, 'parts': verified, **statuses}


def sign(key, path, signature):
    subprocess.run(['openssl', 'pkeyutl', '-sign', '-rawin', '-inkey', str(key), '-in', str(path),
                    '-out', str(signature)], check=True)
    subprocess.run(['openssl', 'pkeyutl', '-verify', '-rawin', '-pubin', '-inkey',
                    str(ROOT / 'packaging/release-public.pem'), '-in', str(path), '-sigfile', str(signature)], check=True)


def require_public_release(manifest):
    """Require explicit passed system checks and any installation media checks."""
    if not isinstance(manifest, dict):
        raise ValueError('Missing release manifest.')
    if manifest.get('publication') == 'update-only':
        if any(name in manifest for name in ('asset', 'sha256', 'size', 'iso')):
            raise ValueError('An update-only release cannot describe installation media.')
        assets = manifest.get('assets', [])
        if not isinstance(assets, list) or any(not isinstance(asset, dict) for asset in assets):
            raise ValueError('Invalid update-only release assets.')
        if any(asset.get('kind') in ('raw-image', 'iso-download') for asset in assets):
            raise ValueError('An update-only release cannot include installation media.')
    statuses = [manifest.get('boot_test'), manifest.get('runtime_test')]
    if 'iso' in manifest:
        iso = manifest['iso']
        if not isinstance(iso, dict):
            raise ValueError('Invalid ISO verification report.')
        statuses.extend(iso.get(name) for name in
                        ('boot_test', 'install_test', 'system_boot_test', 'runtime_test'))
    if not all(status == 'passed' for status in statuses):
        raise ValueError('Critical installation media verification incomplete.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--key', required=True)
    parser.add_argument('--directory', default=str(ROOT / 'dist'))
    parser.add_argument('--image', required=True)
    publication = parser.add_mutually_exclusive_group(required=True)
    publication.add_argument('--image-file', help='Compressed installation IMG to include in the release.')
    publication.add_argument('--update-only', action='store_true',
                             help='Sign an OCI system update without an installation download.')
    parser.add_argument('--iso-description')
    parser.add_argument('--iso-test')
    parser.add_argument('--boot-test', required=True, choices=('passed', 'failed'))
    parser.add_argument('--runtime-test', required=True, choices=('passed', 'failed', 'not-run'))
    args = parser.parse_args()
    if bool(args.iso_description) != bool(args.iso_test):
        parser.error('ISO description and ISO test must be provided together.')
    if args.update_only and args.iso_description:
        parser.error('An update-only release cannot include ISO downloads.')
    if not re.fullmatch(r'ghcr\.io/ra5on/titan@sha256:[a-f0-9]{64}', args.image):
        parser.error('Titan image must be referenced by its exact GHCR digest.')
    directory = Path(args.directory)
    raw = None
    assets = []
    if args.image_file:
        asset = Path(args.image_file)
        if (asset.resolve().parent != directory.resolve() or asset.is_symlink() or not asset.is_file()
                or not re.fullmatch(r'titan-[0-9A-Za-z.-]+-x86_64\.img\.xz', asset.name)):
            parser.error('Image file must be a regular compressed Titan .img in the output directory.')
        raw = fingerprint(asset)
        assets.append(dict(raw, kind='raw-image'))
    iso = None
    if args.iso_description:
        iso = iso_metadata(directory, json.loads(Path(args.iso_description).read_text()),
                           json.loads(Path(args.iso_test).read_text()))
        if iso['filename'] != asset.name.removesuffix('.img.xz') + '.iso':
            parser.error('IMG and ISO versions must match.')
        helper = directory / 'restore-iso.py'
        helper.write_bytes((ROOT / 'scripts/restore-iso.py').read_bytes())
        assets.extend(dict(part, kind='iso-download') for part in iso['parts'])
        assets.append(dict(fingerprint(helper), kind='verification-helper'))
    public = directory / 'release-public.pem'
    public.write_bytes((ROOT / 'packaging/release-public.pem').read_bytes())
    assets.append(dict(fingerprint(public), kind='verification-helper'))
    manifest = {'format': 'titan-ucore-image-v1', 'platform': 'ucore-hci',
                'version': __version__, 'release_stage': __release_stage__, 'architecture': 'x86_64',
                'image': args.image,
                'boot_test': args.boot_test, 'runtime_test': args.runtime_test, 'assets': assets}
    if raw is not None:
        manifest.update(asset=raw['name'], sha256=raw['sha256'], size=raw['size'])
    else:
        manifest['publication'] = 'update-only'
    if iso is not None:
        manifest['iso'] = iso
    path = directory / 'manifest.json'
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    sign(args.key, path, directory / 'manifest.json.sig')
    checksums = directory / 'SHA256SUMS'
    sums = ''.join(value['sha256'] + '  ' + value['name'] + '\n' for value in assets)
    if iso is not None:
        sums += iso['uncompressed_sha256'] + '  ' + iso['filename'] + '\n'
    checksums.write_text(sums)
    sign(args.key, checksums, directory / 'SHA256SUMS.sig')
    kind = 'OCI update' if args.update_only else ('IMG and ISO' if iso is not None else 'IMG')
    print(kind + ' manifest and checksums signed and verified.')


if __name__ == '__main__':
    main()

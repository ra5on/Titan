#!/usr/bin/env python3
"""Inspect the builder's embedded OCI and kickstart; optionally make a CI copy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

READY = 'TITAN_ISO_READY: offline payload present; target disk selection required'


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('ISO tool failed: ' + result.stderr[-6000:])
    return result


def check_kickstart(contents, base, image):
    if '%include /run/install/repo/osbuild-base.ks' not in contents:
        raise ValueError('ISO does not use the inspected embedded payload kickstart.')
    if 'text\n' not in contents or READY not in contents:
        raise ValueError('ISO does not contain the interactive Titan installer.')
    for text in (contents, base):
        if re.search(r'^\s*(clearpart|zerombr|autopart|part|partition|raid|volgroup|logvol|ignoredisk|reboot|poweroff)\b', text, re.M):
            raise ValueError('Public ISO contains automatic storage or completion commands.')
        if '--non-interactive' in text:
            raise ValueError('Public ISO must require interactive disk selection.')
    if not re.search(r'^ostreecontainer\s.*--url=?[\"\']?/run/install/repo/container', base, re.M):
        raise ValueError('ISO does not install the local offline OCI payload.')
    if 'bootc switch --mutate-in-place --transport registry ' + image not in base:
        raise ValueError('ISO update reference differs from the signed system image.')


def check_payload(index, manifest_bytes, digest):
    digest_value = digest.removeprefix('sha256:')
    if hashlib.sha256(manifest_bytes).hexdigest() != digest_value:
        raise ValueError('Embedded container manifest does not match the signed OCI digest.')
    descriptors = index.get('manifests', [])
    if not any(value.get('digest') == digest for value in descriptors):
        raise ValueError('ISO index does not reference the signed OCI digest.')
    manifest = json.loads(manifest_bytes)
    if not manifest.get('layers') or not manifest.get('config', {}).get('digest'):
        raise ValueError('ISO contains an incomplete OCI payload manifest.')


def verify_oci_layout(directory, digest):
    """Bind every preserved blob to the exact previously signature-verified image."""
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError('A regular verified OCI directory is required.')
    if any(path.is_symlink() for path in directory.rglob('*')):
        raise ValueError('OCI payload must not contain symlinks.')
    layout = json.loads((directory / 'oci-layout').read_text())
    if layout.get('imageLayoutVersion') != '1.0.0':
        raise ValueError('Unsupported OCI payload layout.')
    manifest_file = directory / 'blobs/sha256' / digest.removeprefix('sha256:')
    manifest_bytes = manifest_file.read_bytes()
    check_payload(json.loads((directory / 'index.json').read_text()), manifest_bytes, digest)
    manifest = json.loads(manifest_bytes)
    for descriptor in [manifest['config'], *manifest['layers']]:
        blob_digest = descriptor.get('digest', '')
        size = descriptor.get('size')
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', blob_digest) or type(size) is not int or size < 0:
            raise ValueError('Invalid OCI payload blob descriptor.')
        blob = directory / 'blobs/sha256' / blob_digest.removeprefix('sha256:')
        if not blob.is_file() or blob.stat().st_size != size:
            raise ValueError('OCI payload blob is missing or has the wrong size.')
        checksum = hashlib.sha256()
        with blob.open('rb') as stream:
            while chunk := stream.read(8 * 1024 * 1024):
                checksum.update(chunk)
        if checksum.hexdigest() != blob_digest.removeprefix('sha256:'):
            raise ValueError('OCI payload blob does not match its signed manifest.')


def replace_payload(iso, directory, digest):
    # Legacy BIB exports decompressed layers from containers-storage, changing
    # their manifest digest. Use the policy-verified, preserved registry OCI
    # instead of accepting a weaker identity check for that transformation.
    verify_oci_layout(directory, digest)
    with tempfile.TemporaryDirectory(prefix='.iso-payload-', dir=iso.parent) as temporary:
        output = Path(temporary) / 'preserved.iso'
        run('xorriso', '-indev', str(iso), '-outdev', str(output),
            '-boot_image', 'any', 'replay', '-rm_r', '/container', '--',
            '-map', str(directory.resolve()), '/container', '-commit')
        refresh_media_checksum(output)
        os.replace(output, iso)


def refresh_media_checksum(iso):
    # Remastering invalidates the Fedora media-test checksum in the ISO PVD.
    run('implantisomd5', '--force', str(iso))
    run('checkisomd5', str(iso))


def test_kickstart(contents):
    # This copy is used only inside a disposable QEMU guest. It is never shipped.
    return contents.replace('text\n', 'text --non-interactive\n', 1) + '''
ignoredisk --only-use=vda
zerombr
clearpart --all --initlabel --disklabel=gpt --drives=vda
part /boot/efi --fstype=efi --size=512 --ondisk=vda
part /boot --fstype=ext4 --size=1024 --ondisk=vda
part / --fstype=xfs --size=20000 --grow --ondisk=vda
poweroff
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('iso', type=Path)
    parser.add_argument('--image', required=True)
    parser.add_argument('--payload-dir', type=Path,
                        help='Embed the exact registry OCI layout already verified by the release policy.')
    parser.add_argument('--test-output', type=Path)
    parser.add_argument('--confirm-disposable-guest', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'ghcr\.io/ra5on/titan@sha256:[a-f0-9]{64}', args.image):
        parser.error('An exact Titan OCI digest is required.')
    if not args.iso.is_file() or args.iso.is_symlink():
        parser.error('A regular ISO file is required.')
    if args.test_output and (os.environ.get('GITHUB_ACTIONS') != 'true' or not args.confirm_disposable_guest):
        parser.error('Unattended copies are limited to explicitly confirmed disposable CI guests.')
    if args.test_output and args.test_output.exists():
        parser.error('Refusing to replace an existing file.')
    with tempfile.TemporaryDirectory(prefix='titan-iso-inspect-') as temporary:
        directory = Path(temporary)
        for name in ('osbuild.ks', 'osbuild-base.ks', 'container/index.json'):
            output = directory / Path(name).name
            run('xorriso', '-osirrox', 'on', '-indev', str(args.iso), '-extract', '/' + name, str(output))
        contents = (directory / 'osbuild.ks').read_text()
        base = (directory / 'osbuild-base.ks').read_text()
        check_kickstart(contents, base, args.image)
        digest = args.image.split('@')[1]
        if args.payload_dir:
            replace_payload(args.iso, args.payload_dir, digest)
            run('xorriso', '-osirrox', 'on', '-indev', str(args.iso), '-extract',
                '/container/index.json', str(directory / 'preserved-index.json'))
            index_file = directory / 'preserved-index.json'
        else:
            index_file = directory / 'index.json'
        manifest_file = directory / 'container-manifest.json'
        run('xorriso', '-osirrox', 'on', '-indev', str(args.iso), '-extract',
            '/container/blobs/sha256/' + digest.split(':')[1], str(manifest_file))
        check_payload(json.loads(index_file.read_text()), manifest_file.read_bytes(), digest)
        if args.test_output:
            kickstart = directory / 'test.ks'
            kickstart.write_text(test_kickstart(contents))
            # Replay the original El Torito/hybrid BIOS and UEFI boot equipment.
            run('xorriso', '-indev', str(args.iso), '-outdev', str(args.test_output),
                '-boot_image', 'any', 'replay', '-map', str(kickstart), '/osbuild.ks', '-commit')
            refresh_media_checksum(args.test_output)
    print('ISO inspected: interactive storage selection, complete local OCI reference, exact Titan digest.')


if __name__ == '__main__':
    main()

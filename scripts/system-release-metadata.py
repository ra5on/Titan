#!/usr/bin/env python3
"""Produce identities and final release metadata from explicit build inputs."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['identity', 'manifest'])
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--accounts', type=Path, required=True)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--rootfs', type=Path)
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--package-changes', type=Path,
                        help='JSON build report containing package_changes and security_summary')
    args = parser.parse_args()
    if args.mode == 'manifest' and any(value is None for value in (args.evidence, args.bundle, args.rootfs)):
        parser.error('manifest requires --evidence, --bundle and --rootfs')
    assert os.environ.get('GITHUB_ACTIONS') == 'true'
    match = re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-(alpha|beta)\.[0-9]+)?', args.version)
    if not match: raise ValueError('Invalid release version')
    stage = match.group(1) or 'stable'
    commit = os.environ.get('TITAN_BUILD_SOURCE_COMMIT', os.environ['GITHUB_SHA'])
    if not re.fullmatch(r'[a-f0-9]{40}', commit): raise ValueError('Invalid build source commit')
    kind = os.environ.get('TITAN_UPDATE_KIND', 'titan')
    if kind == 'system' and any(not os.environ.get(name) for name in
            ('TITAN_APP_VERSION', 'TITAN_APP_STAGE', 'TITAN_APP_SOURCE_COMMIT', 'TITAN_SYSTEM_REVISION')):
        raise ValueError('System-only builds require an explicit frozen Titan identity and system revision')
    app_version = os.environ.get('TITAN_APP_VERSION', args.version.split('-')[0])
    app_stage = os.environ.get('TITAN_APP_STAGE', stage)
    app_commit = os.environ.get('TITAN_APP_SOURCE_COMMIT', commit)
    revision_text = os.environ.get('TITAN_SYSTEM_REVISION', '1')
    if (kind not in ('titan', 'system') or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', app_version)
            or app_stage not in ('alpha', 'beta', 'stable') or not re.fullmatch(r'[a-f0-9]{40}', app_commit)
            or not re.fullmatch(r'[1-9][0-9]{0,9}', revision_text) or int(revision_text) >= 2**31):
        raise ValueError('Invalid separated system/Titan release identity')
    if kind == 'titan' and app_commit != commit:
        raise ValueError('Titan releases must identify the built Titan source commit')
    release_id = 'sha256:' + hashlib.sha256(('Titan A/B v1\n'+commit+'\n'+args.version).encode()).hexdigest()
    info = {'format':'titan-debian-ab-v1', 'platform':'debian-rauc',
            'compatible':'titan-debian13-amd64-ab-v1', 'architecture':'x86_64',
            'state_schema':1, 'release_id':release_id, 'version':args.version,
            'release_stage':stage, 'source_commit':commit, 'system_accounts':json.loads(args.accounts.read_text()),
            'update_kind':kind, 'titan_version':app_version, 'titan_stage':app_stage,
            'titan_source_commit':app_commit, 'system_revision':int(revision_text)}
    report_path = args.package_changes or (Path(os.environ['TITAN_PACKAGE_CHANGES']) if os.environ.get('TITAN_PACKAGE_CHANGES') else None)
    if report_path:
        report = json.loads(report_path.read_text())
        if not isinstance(report, dict) or set(report) != {'package_changes', 'security_summary'}:
            raise ValueError('Invalid package change report')
        info.update(report)
    # Use the updater's exact signed schema before producing an artifact. This
    # catches malformed provenance or summaries in both identity/manifest modes.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from titan.debian_updates import validate_identity
    validate_identity(info)
    if args.mode == 'manifest':
        evidence = json.loads(args.evidence.read_text())
        assert isinstance(evidence, dict) and set(evidence) == {'boot_test','runtime_test','update_test','rollback_test'}
        assert all(evidence.get(k) == 'passed' for k in ('boot_test','runtime_test','update_test','rollback_test'))
        info.update(evidence)
        info['bundle'] = {'name':args.bundle.name, 'size':args.bundle.stat().st_size, 'sha256':digest(args.bundle)}
        info['rootfs_sha256'] = digest(args.rootfs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(info, indent=2) + '\n'
    assert len(encoded.encode()) <= 16384, 'Signed metadata exceeds updater limit'
    args.output.write_text(encoded)
    key = Path(os.environ['RUNNER_TEMP'])/'titan-signing/root.key'
    subprocess.run(['openssl','pkeyutl','-sign','-rawin','-inkey',str(key),'-in',str(args.output),'-out',str(args.output)+'.sig'], check=True)


if __name__ == '__main__':
    main()

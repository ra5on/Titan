#!/usr/bin/env python3
"""Produce identities and final release metadata from explicit build inputs."""
import argparse
import hashlib
import json
import os
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
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--rootfs', type=Path)
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    assert os.environ.get('GITHUB_ACTIONS') == 'true'
    commit = os.environ['GITHUB_SHA']
    release_id = 'sha256:' + hashlib.sha256(('Titan A/B v1\n'+commit+'\n'+args.version).encode()).hexdigest()
    info = {'format':'titan-debian-ab-v1', 'platform':'debian-rauc',
            'compatible':'titan-debian13-amd64-ab-v1', 'architecture':'x86_64',
            'state_schema':1, 'release_id':release_id, 'version':args.version,
            'release_stage':'alpha', 'source_commit':commit}
    if args.mode == 'manifest':
        evidence = json.loads(args.evidence.read_text())
        assert all(evidence.get(k) == 'passed' for k in ('boot_test','runtime_test','update_test','rollback_test'))
        info.update(evidence)
        info['bundle'] = {'name':args.bundle.name, 'size':args.bundle.stat().st_size, 'sha256':digest(args.bundle)}
        info['rootfs_sha256'] = digest(args.rootfs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(info, indent=2) + '\n')
    key = Path(os.environ['RUNNER_TEMP'])/'titan-signing/root.key'
    subprocess.run(['openssl','pkeyutl','-sign','-rawin','-inkey',str(key),'-in',str(args.output),'-out',str(args.output)+'.sig'], check=True)


if __name__ == '__main__':
    main()

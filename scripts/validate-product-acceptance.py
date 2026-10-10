#!/usr/bin/env python3
"""Bind complete product acceptance to the exact NAS image and rescue medium.

The rescue-medium smoke report alone explicitly cannot satisfy this gate.
Reports are produced by acceptance runs, never inferred from passing unit tests.
"""
import hashlib
import json
from pathlib import Path
import re
import sys

REQUIRED = {
    'authenticated_apps_http_websocket', 'app_dependencies_and_seed_files',
    'app_install_update_data_restore', 'qcow2_guest_boot_upload_and_nas_path',
    'replacement_nas_boot_with_changed_controllers', 'replacement_accounts_smb_acl_apps_vm',
    'interrupted_restore_resume', 'unified_signed_update_and_rollback',
}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def validate(directory):
    directory=Path(directory)
    identity=json.loads((directory/'ab-input/image-info.json').read_text())
    report=json.loads((directory/'product-acceptance.json').read_text())
    coverage=json.loads((directory/'umbrel-coverage.json').read_text())
    if (report.get('schema') != 1 or report.get('ok') is not True
            or report.get('scope') != 'installed-nas-and-replacement-recovery'
            or not re.fullmatch(r'[a-f0-9]{40}',str(identity.get('titan_source_commit','')))
            or report.get('source_commit') != identity['titan_source_commit']):
        raise ValueError('Complete acceptance of this exact application commit is missing')
    checks=report.get('checks')
    if not isinstance(checks,dict) or not REQUIRED.issubset(checks) or any(checks[key] is not True for key in REQUIRED):
        raise ValueError('An essential product acceptance check failed or was skipped')
    if (coverage.get('complete') is not True or coverage.get('blocked') != []
            or type(coverage.get('total')) is not int or not 1<=coverage['total']<=1000
            or coverage.get('translated') != coverage['total']
            or not re.fullmatch(r'[a-f0-9]{40}',str(coverage.get('revision','')))
            or not re.fullmatch(r'[a-f0-9]{64}',str(coverage.get('archive_sha256','')))
            or report.get('catalog_revision') != coverage['revision']
            or report.get('catalog_archive_sha256') != coverage['archive_sha256']):
        raise ValueError('The accepted catalogue is incomplete or has another identity')
    # Names are derived from a validated build identity, never from report paths.
    version=identity.get('version','')
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-(?:alpha|beta)\.[0-9]+)?',version):
        raise ValueError('Invalid image identity')
    for key,suffix in (('image_sha256','amd64.img'),('recovery_iso_sha256','recovery-amd64.iso')):
        actual=directory/('titan-'+version+'-'+suffix)
        if report.get(key) != digest(actual):
            raise ValueError('Accepted image or recovery medium differs from the built artifact')
    return True


if __name__=='__main__':
    validate(Path(sys.argv[1]))
    print('Complete product acceptance belongs to this exact image, rescue medium and catalogue.')

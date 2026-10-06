#!/usr/bin/env python3
"""Validate complete, successful VM evidence before signing a public release."""
import json
from pathlib import Path
import sys
import os
import re

RUNTIME={'administrator_setup_login','system_update_state_confirmation','cpu_ram_metrics',
         'smb_multiuser_access','runtime_components','docker_app_lifecycle','docker_custom_network_lifecycle','login_protection','storage_data_boundary',
         'storage_components','custom_service_containment'}
STORAGE_BOUNDARY={'internal_data_resource_ready','default_browser_is_nas_data',
                  'administrator_os_listing_denied','administrator_os_read_denied','administrator_os_write_denied',
                  'data_create_read_edit_delete','stale_revision_rejected','test_file_removed'}
CONTAINMENT={'legacy_root_was_running','legacy_root_was_enabled','legacy_root_stopped','legacy_root_autostart_disabled',
             'unit_file_preserved','api_start_actions_blocked','early_boot_gate_verified','management_requires_gate'}
STORAGE_COMPONENTS={'ext4_tools','xfs_tools','zfs_module_loaded','zfs_module_matches_kernel','zpool_query','zfs_query'}
AB={'baseline_boot_health','proxmox_style_data_growth','signed_update_staged_without_reboot',
    'update_boot_and_preserved_accounts_acls_data','manual_rollback_and_preserved_accounts_acls_data',
    'failed_candidate_fallback_after_reset','factory_defaults_follow_selected_slot'}


def validate(directory):
    directory=Path(directory)
    if (directory/'boot-status').read_text().strip()!='passed':raise ValueError('Boot check did not pass')
    runtime=json.loads((directory/'runtime-test.json').read_text())
    ab=json.loads((directory/'ab-test.json').read_text())
    for result in (runtime,ab):
        if result.get('ok') is not True or result.get('raw_image_unchanged') is not True:
            raise ValueError('Failed checks or modified distributable image')
    checks=runtime.get('checks')
    if not isinstance(checks,list):raise ValueError('Missing runtime checks')
    names=[x['name'] for x in checks]
    if len(set(names))!=len(names):raise ValueError('Ambiguous runtime check names')
    passed={x['name'] for x in checks if x.get('status')=='passed'}
    if not RUNTIME.issubset(passed):raise ValueError('Required runtime check missing or failed')
    if any(x.get('status') not in ('passed','skipped') for x in checks):raise ValueError('Runtime check failed')
    boundary=next(x for x in checks if x['name']=='storage_data_boundary').get('values')
    if (not isinstance(boundary,dict) or set(boundary)!=STORAGE_BOUNDARY or
            any(value is not True for value in boundary.values())):
        raise ValueError('NAS data/OS boundary was not completely verified')
    containment=next(x for x in checks if x['name']=='custom_service_containment').get('values')
    if (not isinstance(containment,dict) or set(containment)!=CONTAINMENT or
            any(value is not True for value in containment.values())):
        raise ValueError('Legacy root service boot containment was not completely verified')
    components=next(x for x in checks if x['name']=='storage_components').get('values')
    component_fields=STORAGE_COMPONENTS|{'kernel','zfs_arc_max_bytes','zfs_arc_min_bytes','zfs_arc_size_bytes'}
    if (not isinstance(components,dict) or set(components)!=component_fields or
            any(components.get(key) is not True for key in STORAGE_COMPONENTS) or
            not isinstance(components['kernel'],str) or not re.fullmatch(r'[a-zA-Z0-9.+_-]{1,128}',components['kernel']) or
            type(components['zfs_arc_max_bytes']) is not int or components['zfs_arc_max_bytes']!=1073741824 or
            type(components['zfs_arc_min_bytes']) is not int or components['zfs_arc_min_bytes']!=134217728 or
            type(components['zfs_arc_size_bytes']) is not int or not 0<=components['zfs_arc_size_bytes']<2**64):
        raise ValueError('Installed storage tools, running-kernel ZFS module or bounded ARC were not verified')
    if not isinstance(ab.get('checks'),list) or not AB.issubset(ab['checks']):
        raise ValueError('Required update/rollback check missing')
    system_only = os.environ.get('TITAN_UPDATE_KIND') == 'system'
    baseline_source = 'published-system-release' if system_only else 'published-release'
    expected_version = os.environ.get('TITAN_PREVIOUS_TAG', '').lstrip('v') if system_only else '0.4.6-alpha.1'
    if (ab.get('baseline_source') != baseline_source or ab.get('baseline_version') != expected_version
            or ab.get('baseline_image_unchanged') is not True or 'published_release_baseline' not in ab['checks']):
        raise ValueError('Update from the expected verified published baseline was not verified')
    if system_only:
        previous=json.loads((directory.parent/'debian-input/previous-manifest.json').read_text())
        if not expected_version or ab.get('baseline_bundle_sha256') != previous['bundle']['sha256']:
            raise ValueError('Published system baseline bundle was not verified')
    return {k:'passed' for k in ('boot_test','runtime_test','update_test','rollback_test')}


if __name__=='__main__':
    root=Path(sys.argv[1]);evidence=validate(root)
    (root/'release-evidence.json').write_text(json.dumps(evidence)+'\n')

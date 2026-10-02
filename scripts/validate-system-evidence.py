#!/usr/bin/env python3
"""Validate complete, successful VM evidence before signing a public release."""
import json
from pathlib import Path
import sys

RUNTIME={'administrator_setup_login','system_update_state_confirmation','cpu_ram_metrics',
         'smb_multiuser_access','runtime_components','docker_app_lifecycle','docker_custom_network_lifecycle'}
AB={'baseline_boot_health','proxmox_style_data_growth','signed_update_staged_without_reboot',
    'update_boot_and_preserved_accounts_acls_data','manual_rollback_and_preserved_accounts_acls_data',
    'failed_candidate_fallback_after_reset'}


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
    if not isinstance(ab.get('checks'),list) or not AB.issubset(ab['checks']):
        raise ValueError('Required update/rollback check missing')
    return {k:'passed' for k in ('boot_test','runtime_test','update_test','rollback_test')}


if __name__=='__main__':
    root=Path(sys.argv[1]);evidence=validate(root)
    (root/'release-evidence.json').write_text(json.dumps(evidence)+'\n')

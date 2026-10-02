#!/bin/bash
# Called only after the real disposable-VM gates; never publishes partial output.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_REPOSITORY:-}" == ra5on/Titan ]] || exit 1
[[ "${TITAN_SYSTEM_VERSION:-}" =~ ^[0-9]+\.[0-9]+\.[0-9]+-(alpha|beta)\.[0-9]+$ ]] || exit 1
task_dir=$(realpath dist/debian-image)
python3 - "$task_dir" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1])
assert (p/'boot-status').read_text().strip()=='passed'
runtime=json.loads((p/'runtime-test.json').read_text())
ab=json.loads((p/'ab-test.json').read_text())
assert runtime['ok'] is True and runtime['raw_image_unchanged'] is True
assert ab['ok'] is True and ab['raw_image_unchanged'] is True
required={'baseline_boot_health','proxmox_style_data_growth','signed_update_staged_without_reboot',
          'update_boot_and_preserved_accounts_acls_data','manual_rollback_and_preserved_accounts_acls_data','failed_candidate_fallback_after_reset'}
assert required.issubset(ab['checks'])
assert all(x['status']=='passed' for x in runtime['checks'] if x['name'] in {'administrator_setup_login','system_update_state_confirmation','cpu_ram_metrics','smb_multiuser_access','runtime_components','docker_app_lifecycle','docker_custom_network_lifecycle'})
(p/'release-evidence.json').write_text(json.dumps({k:'passed' for k in ('boot_test','runtime_test','update_test','rollback_test')})+'\n')
PY
python3 scripts/system-release-metadata.py manifest --version "$TITAN_SYSTEM_VERSION" \
    --output "$task_dir/manifest.json" --bundle "$task_dir/titan-$TITAN_SYSTEM_VERSION-amd64.raucb" \
    --rootfs "$task_dir/bundle/rootfs.ext4" --evidence "$task_dir/release-evidence.json"
cp packaging/release-public.pem "$task_dir/release-public.pem"
cp packaging/rauc-root.pem "$task_dir/rauc-root.pem"
cp docs/TITAN-IMAGE.md "$task_dir/INSTALLATION.md"
cp image/debian/base.json "$task_dir/debian-base.json"
xz -T2 -3 "$task_dir/titan-$TITAN_SYSTEM_VERSION-amd64.img"
[[ $(stat -c %s "$task_dir/titan-$TITAN_SYSTEM_VERSION-amd64.img.xz") -lt 2147483648 ]]
[[ $(stat -c %s "$task_dir/titan-$TITAN_SYSTEM_VERSION-amd64.raucb") -lt 2147483648 ]]
(
    cd "$task_dir"
    sha256sum "titan-$TITAN_SYSTEM_VERSION-amd64.img.xz" "titan-$TITAN_SYSTEM_VERSION-amd64.raucb" \
        manifest.json manifest.json.sig runtime-test.json ab-test.json INSTALLATION.md debian-base.json rauc-root.pem > SHA256SUMS
    openssl pkeyutl -sign -rawin -inkey "$RUNNER_TEMP/titan-signing/root.key" -in SHA256SUMS -out SHA256SUMS.sig
    openssl pkeyutl -verify -rawin -pubin -inkey release-public.pem -in SHA256SUMS -sigfile SHA256SUMS.sig
)
# A tag is immutable once published. A rerun must never replace user downloads.
if gh release view "v$TITAN_SYSTEM_VERSION" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
    echo 'Release already exists; choose a new version instead of replacing downloads.' >&2
    exit 1
fi
gh release create "v$TITAN_SYSTEM_VERSION" --repo "$GITHUB_REPOSITORY" --target "$GITHUB_SHA" --prerelease --latest=false \
    --title "Titan $TITAN_SYSTEM_VERSION · Debian A/B" --notes-file docs/TITAN-IMAGE.md \
    "$task_dir/titan-$TITAN_SYSTEM_VERSION-amd64.img.xz" "$task_dir/titan-$TITAN_SYSTEM_VERSION-amd64.raucb" \
    "$task_dir/manifest.json" "$task_dir/manifest.json.sig" "$task_dir/SHA256SUMS" "$task_dir/SHA256SUMS.sig" \
    "$task_dir/release-public.pem" "$task_dir/rauc-root.pem" "$task_dir/runtime-test.json" "$task_dir/ab-test.json" \
    "$task_dir/INSTALLATION.md" "$task_dir/debian-base.json"

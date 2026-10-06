#!/bin/bash
# Reconstruct a disposable A/B disk from a verified published system bundle.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${1:-}" == --disposable-runner && "${TITAN_UPDATE_KIND:-}" == system ]] || exit 1
export LIBGUESTFS_BACKEND=direct
task_dir=$(realpath dist/debian-baseline)
task_input=$(realpath dist/debian-input)
[[ -f "$task_dir/baseline.img" && ! -L "$task_dir/baseline.img" && -f "$task_input/previous.raucb" ]]
python3 - "$task_input/previous-manifest.json" "$task_input/previous.raucb" <<'PY'
import hashlib,json,os,sys
from pathlib import Path
from titan.debian_updates import validate_manifest
m=validate_manifest(json.loads(Path(sys.argv[1]).read_text()))
assert m['version']==os.environ['TITAN_PREVIOUS_TAG'].lstrip('v')
assert m['titan_version']==os.environ['TITAN_APP_VERSION'] and m['titan_stage']==os.environ['TITAN_APP_STAGE']
assert m['titan_source_commit']==os.environ['TITAN_APP_SOURCE_COMMIT']
p=Path(sys.argv[2]);assert p.stat().st_size==m['bundle']['size']
with p.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==m['bundle']['sha256']
PY
rauc --conf=dist/debian-image/builder-system.conf extract --keyring=packaging/rauc-root.pem "$task_input/previous.raucb" "$task_input/extracted"
[[ -f "$task_input/extracted/rootfs.ext4" && ! -L "$task_input/extracted/rootfs.ext4" && $(stat -c %s "$task_input/extracted/rootfs.ext4") -eq 17179869184 ]]
python3 - "$task_input/previous-manifest.json" "$task_input/extracted/rootfs.ext4" <<'PYROOTFS'
import hashlib,json,sys
from pathlib import Path
manifest=json.loads(Path(sys.argv[1]).read_text())
with Path(sys.argv[2]).open('rb') as stream:
    assert hashlib.file_digest(stream,'sha256').hexdigest()==manifest['rootfs_sha256'], 'Published root filesystem differs from signed manifest'
PYROOTFS
guestfish --ro -a "$task_input/extracted/rootfs.ext4" -m /dev/sda download /usr/share/titan/image-info.json "$task_input/previous-identity.json"
guestfish --ro -a "$task_input/extracted/rootfs.ext4" -m /dev/sda download /usr/share/titan/image-info.json.sig "$task_input/previous-identity.json.sig"
openssl pkeyutl -verify -rawin -pubin -inkey packaging/release-public.pem -in "$task_input/previous-identity.json" -sigfile "$task_input/previous-identity.json.sig"
python3 - "$task_input/previous-manifest.json" "$task_input/previous-identity.json" <<'PYIDENTITY'
import json,sys
from pathlib import Path
from titan.debian_updates import validate_identity
manifest=json.loads(Path(sys.argv[1]).read_text())
identity=validate_identity(json.loads(Path(sys.argv[2]).read_text()))
assert all(manifest.get(key)==value for key,value in identity.items()), 'Published root filesystem identity differs from signed manifest'
PYIDENTITY
# Keep the original published 0.4.6 disk untouched. Its boot/partition layout is
# compatible; slot A is replaced only in this new regular raw test file.
[[ ! -e "$task_dir/system-baseline.img" && ! -L "$task_dir/system-baseline.img" ]]
cp --sparse=always "$task_dir/baseline.img" "$task_dir/system-baseline.img"
guestfish -a "$task_dir/system-baseline.img" run : upload "$task_input/extracted/rootfs.ext4" /dev/sda3 : set-label /dev/sda3 TITAN-A
rm -rf "$task_input/extracted"

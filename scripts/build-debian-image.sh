#!/bin/bash
# CI-only: all mutations occur inside new regular image files via libguestfs.
# Runtime checks cover Docker external network identity before publishing.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${1:-}" == --disposable-runner ]] || { echo 'Requires disposable GitHub Actions runner.' >&2; exit 1; }
export LIBGUESTFS_BACKEND=direct
mkdir -p dist/debian-image
python3 scripts/build-debian-package.py
python3 - <<'PY'
import hashlib,json,urllib.request
from pathlib import Path
v=json.loads(Path('image/debian/base.json').read_text())
p=Path('dist/debian-image/base.qcow2')
with urllib.request.urlopen(v['url'],timeout=120) as source,p.open('wb') as out:
    while data:=source.read(1024*1024):out.write(data)
with p.open('rb') as stream: actual=hashlib.file_digest(stream,'sha512').hexdigest()
assert actual==v['sha512'],'Debian base checksum mismatch'
print('Official Debian base checksum verified.')
PY
task_dir=$(realpath dist/debian-image)
# Debian's generic image has root on partition 1. Verify before expansion.
task_root=$(guestfish --ro -a "$task_dir/base.qcow2" -i inspect-get-roots)
[[ "$task_root" == /dev/sda1 ]] || { echo "Unexpected Debian root layout: $task_root" >&2; exit 1; }
qemu-img create -f qcow2 "$task_dir/titan.qcow2" 16G
virt-resize --expand /dev/sda1 "$task_dir/base.qcow2" "$task_dir/titan.qcow2"
virt-customize -a "$task_dir/titan.qcow2" --memsize 4096 \
    --upload "$(realpath dist/debian/titan-debian-preview_*_amd64.deb):/tmp/titan-preview.deb" \
    --upload "$(realpath image/debian/grow-root.sh):/tmp/titan-grow-root.sh" \
    --upload "$(realpath image/debian/configure-guest.sh):/tmp/titan-configure-guest.sh" \
    --upload "$(realpath scripts/debian-package-state.py):/tmp/titan-package-state.py" \
    --upload "$(realpath scripts/collect-debian-sources.py):/tmp/titan-collect-debian-sources.py" \
    --upload "$(realpath image/debian/zfs-components.py):/tmp/titan-zfs-components.py" \
    --run-command '/bin/bash /tmp/titan-configure-guest.sh' \
    --delete /tmp/titan-configure-guest.sh
qemu-img convert -O raw "$task_dir/titan.qcow2" "$task_dir/titan-debian-preview-20261002-amd64.img"
rm "$task_dir/base.qcow2" "$task_dir/titan.qcow2"

#!/bin/bash
# A real Debian guest used only inside disposable NAS acceptance VMs.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${1:-}" == --disposable-runner ]] || exit 1
export LIBGUESTFS_BACKEND=direct
mkdir -p dist/guest-acceptance
python3 - <<'PY'
import hashlib,json,urllib.request
from pathlib import Path
v=json.loads(Path('image/debian/base.json').read_text())
p=Path('dist/guest-acceptance/debian.qcow2')
with urllib.request.urlopen(v['url'],timeout=120) as source,p.open('xb') as out:
    while data:=source.read(1024*1024):out.write(data)
with p.open('rb') as stream: actual=hashlib.file_digest(stream,'sha512').hexdigest()
assert actual==v['sha512'],'Debian guest checksum mismatch'
PY
virt-customize -a dist/guest-acceptance/debian.qcow2 --memsize 2048 \
    --install qemu-guest-agent \
    --run-command 'touch /etc/cloud/cloud-init.disabled; systemctl enable qemu-guest-agent; apt-get clean; rm -rf /var/lib/apt/lists/*' \
    --truncate /etc/machine-id
qemu-img convert -c -O qcow2 dist/guest-acceptance/debian.qcow2 dist/guest-acceptance/bootable.qcow2
rm dist/guest-acceptance/debian.qcow2
qemu-img check -f qcow2 dist/guest-acceptance/bootable.qcow2
python3 - <<'PY'
import hashlib,json
from pathlib import Path
p=Path('dist/guest-acceptance/bootable.qcow2')
with p.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
(p.parent/'provenance.json').write_text(json.dumps({'base':json.loads(Path('image/debian/base.json').read_text()),'fixture_sha256':digest,'fixture_size':p.stat().st_size})+'\n')
PY

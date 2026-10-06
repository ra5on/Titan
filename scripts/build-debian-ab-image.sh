#!/bin/bash
# Everything below targets new regular image files in a disposable runner.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${1:-}" == --disposable-runner ]] || exit 1
export LIBGUESTFS_BACKEND=direct
: "${TITAN_SYSTEM_VERSION:?}" "${RUNNER_TEMP:?}"
bash scripts/build-debian-image.sh --disposable-runner
task_dir=$(realpath dist/debian-image)
task_work="$task_dir/ab-input"
mkdir -p "$task_work"
cp image/debian/ab/* "$task_work/"
cp packaging/rauc-root.pem "$task_work/"
task_base="$task_dir/titan-debian-preview-20261002-amd64.img"
guestfish --ro -a "$task_base" -i download /etc/passwd "$task_dir/factory-passwd"
guestfish --ro -a "$task_base" -i download /etc/group "$task_dir/factory-group"
python3 - "$task_dir" "$task_work/system-accounts.json" <<'PYACCOUNTS'
import json,sys
from pathlib import Path
p=Path(sys.argv[1])
users={v[0]:{'uid':int(v[2]),'gid':int(v[3])} for line in (p/'factory-passwd').read_text().splitlines() if (v:=line.split(':')) and len(v)==7}
groups={v[0]:int(v[2]) for line in (p/'factory-group').read_text().splitlines() if (v:=line.split(':')) and len(v)==4}
Path(sys.argv[2]).write_text(json.dumps({'users':users,'groups':groups},sort_keys=True)+'\n')
PYACCOUNTS
rm "$task_dir/factory-passwd" "$task_dir/factory-group"
python3 scripts/system-release-metadata.py identity --version "$TITAN_SYSTEM_VERSION" --accounts "$task_work/system-accounts.json" --output "$task_work/image-info.json"
virt-customize -a "$task_base" --memsize 4096 --copy-in "$task_work:/tmp" \
    --run-command 'mv /tmp/ab-input /tmp/titan-ab && /bin/bash /tmp/titan-ab/configure-ab.sh'
task_previous=()
if [[ -f dist/debian-input/previous-packages.json ]]; then
    task_previous=(--upload "$(realpath dist/debian-input/previous-packages.json):/tmp/titan-previous-packages.json")
fi
virt-customize -a "$task_base" --memsize 4096 "${task_previous[@]}" \
    --run-command 'set -eu; python3 /tmp/titan-package-state.py guard --output /tmp/titan-package-guard.json; python3 /tmp/titan-package-state.py inventory --output /usr/share/titan/debian-packages.json; task_before=/tmp/titan-before-packages.json; if test -f /tmp/titan-previous-packages.json; then task_before=/tmp/titan-previous-packages.json; fi; python3 /tmp/titan-package-state.py changes --before "$task_before" --output /tmp/titan-package-changes.json' \
    --run-command 'rm -f /tmp/titan-before-packages.json /tmp/titan-previous-packages.json /tmp/titan-package-state.py; rm -rf /var/lib/apt/lists/*; apt-get clean'
guestfish --ro -a "$task_base" -m /dev/sda1 download /usr/share/titan/debian-packages.json "$task_dir/debian-packages.json"
guestfish --ro -a "$task_base" -m /dev/sda1 download /tmp/titan-package-changes.json "$task_dir/package-changes.json"
# Identity is signed after the measured Debian changes are available. The root
# filesystem receives the same metadata that later goes into the public offer.
TITAN_PACKAGE_CHANGES="$task_dir/package-changes.json" python3 scripts/system-release-metadata.py identity --version "$TITAN_SYSTEM_VERSION" --accounts "$task_work/system-accounts.json" --output "$task_work/image-info.json"
virt-customize -a "$task_base" --memsize 4096 \
    --upload "$task_work/image-info.json:/usr/share/titan/image-info.json" \
    --upload "$task_work/image-info.json.sig:/usr/share/titan/image-info.json.sig" \
    --delete /tmp/titan-package-changes.json --delete /tmp/titan-package-guard.json
task_root=$(guestfish --ro -a "$task_base" run : inspect-os : inspect-get-roots | tail -n 1)
[[ "$task_root" == /dev/sda1 ]] || { echo "Unexpected expanded root: $task_root" >&2; exit 1; }
guestfish --ro -a "$task_base" -m /dev/sda1 download /tmp/titan-BOOTX64.EFI "$task_dir/BOOTX64.EFI"
# Export with no mounted filesystems, then check and size the regular file.
guestfish --ro -a "$task_base" run : download "$task_root" "$task_dir/rootfs.ext4"
bash scripts/prepare-debian-rootfs.sh "$task_dir/rootfs.ext4"
rm "$task_base"
# A 16 GiB slot must hold the complete root filesystem with room for alignment.
[[ $(stat -c %s "$task_dir/rootfs.ext4") -eq 17179869184 ]] || exit 1
task_image="$task_dir/titan-$TITAN_SYSTEM_VERSION-amd64.img"
truncate -s 48G "$task_image"
# 256 MiB ESP, 256 MiB boot, two 16 GiB roots, all remaining space for data.
guestfish -a "$task_image" <<GUEST
run
part-init /dev/sda gpt
part-add /dev/sda p 2048 526335
part-add /dev/sda p 526336 1050623
part-add /dev/sda p 1050624 34605055
part-add /dev/sda p 34605056 68159487
part-add /dev/sda p 68159488 -2048
part-set-name /dev/sda 1 TITAN-EFI
part-set-name /dev/sda 2 TITAN-BOOT
part-set-name /dev/sda 3 TITAN-A
part-set-name /dev/sda 4 TITAN-B
part-set-name /dev/sda 5 TITAN-DATA
part-set-gpt-type /dev/sda 1 C12A7328-F81F-11D2-BA4B-00A0C93EC93B
mkfs vfat /dev/sda1
set-label /dev/sda1 TITAN-EFI
mkfs ext4 /dev/sda2
set-label /dev/sda2 TITAN-BOOT
upload $task_dir/rootfs.ext4 /dev/sda3
set-label /dev/sda3 TITAN-A
mkfs ext4 /dev/sda4
set-label /dev/sda4 TITAN-B
mkfs ext4 /dev/sda5
set-label /dev/sda5 TITAN-DATA
mount /dev/sda2 /
upload image/debian/ab/grub.cfg /grub.cfg
umount-all
mount /dev/sda1 /
mkdir-p /EFI/BOOT
upload $task_dir/BOOTX64.EFI /EFI/BOOT/BOOTX64.EFI
umount-all
GUEST
# Environment is outside both OS slots and writable by GRUB/RAUC.
grub-editenv "$task_dir/grubenv" create
grub-editenv "$task_dir/grubenv" set 'ORDER=A B' A_OK=1 A_TRY=0 B_OK=0 B_TRY=0
guestfish -a "$task_image" -m /dev/sda2 upload "$task_dir/grubenv" /grubenv
mkdir -p "$task_dir/bundle"
cp image/debian/ab/slot-hook.sh "$task_dir/bundle/slot-hook.sh"
chmod 0755 "$task_dir/bundle/slot-hook.sh"
mv "$task_dir/rootfs.ext4" "$task_dir/bundle/rootfs.ext4"
python3 - "$task_work/image-info.json" "$task_dir/bundle/manifest.raucm" <<'PY'
import json,sys
from pathlib import Path
v=json.loads(Path(sys.argv[1]).read_text())
Path(sys.argv[2]).write_text(f'''[update]
compatible={v['compatible']}
version={v['version']}
build={v['release_id']}
[bundle]
format=verity
[hooks]
filename=slot-hook.sh
[image.rootfs]
filename=rootfs.ext4
hooks=post-install
''')
PY
rauc bundle --cert="$RUNNER_TEMP/titan-signing/bundle.pem" --key="$RUNNER_TEMP/titan-signing/bundle.key" "$task_dir/bundle" "$task_dir/titan-$TITAN_SYSTEM_VERSION-amd64.raucb"
# `rauc info` needs an explicit configuration to apply codesign purpose.
python3 - "$task_dir/builder-system.conf" <<'PYCONFIG'
import sys
from pathlib import Path
Path(sys.argv[1]).write_text('[system]\ncompatible=titan-debian13-amd64-ab-v1\nbootloader=noop\n[keyring]\npath='+str(Path('packaging/rauc-root.pem').resolve())+'\ncheck-purpose=codesign\n')
PYCONFIG
rauc --conf="$task_dir/builder-system.conf" info --keyring=packaging/rauc-root.pem "$task_dir/titan-$TITAN_SYSTEM_VERSION-amd64.raucb"

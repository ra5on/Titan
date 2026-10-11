#!/bin/bash
# Read the completed ISO, then collect exact sources in a disposable copy only.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${1:-}" == --disposable-runner ]] || exit 1
: "${TITAN_SYSTEM_VERSION:?}" "${TITAN_APP_SOURCE_COMMIT:?}" "${RUNNER_TEMP:?}"
[[ "$TITAN_APP_SOURCE_COMMIT" =~ ^[a-f0-9]{40}$ ]] || exit 1
task_iso=$(realpath "dist/debian-image/titan-$TITAN_SYSTEM_VERSION-recovery-amd64.iso")
task_output=$(realpath dist/debian-image)
shopt -s nullglob
task_previous=("$task_output"/recovery-sources.tar.part-* "$task_output"/recovery-sources.json "$task_output"/recovery-packages.json)
for task_file in "${task_previous[@]}"; do
    [[ ! -e "$task_file" ]] || { echo 'Recovery source output already exists; refusing mixed runs.' >&2; exit 1; }
done
task_work=$(mktemp -d "$RUNNER_TEMP/titan-recovery-sources.XXXXXX")
trap 'sudo rm -rf "$task_work"' EXIT
task_before=$(sha256sum "$task_iso")
cp scripts/collect-debian-sources.py scripts/debian-package-state.py "$task_work/"
docker run --rm -i --privileged -v "$task_work:/work" -v "$task_iso:/input/recovery.iso:ro" \
    -v "$task_output:/output" -e TITAN_APP_SOURCE_COMMIT debian:13-slim bash -s <<'COLLECT'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends squashfs-tools xorriso ca-certificates
xorriso -osirrox on -indev /input/recovery.iso -extract /live/filesystem.squashfs /work/root.squashfs
unsquashfs -d /work/root /work/root.squashfs
rm /work/root.squashfs
cp /work/collect-debian-sources.py /work/debian-package-state.py /work/root/tmp/
# The image is never modified. Only the temporary extracted copy gets DNS.
rm -f /work/root/etc/resolv.conf
cp /etc/resolv.conf /work/root/etc/resolv.conf
mount --bind /dev /work/root/dev
trap 'umount /work/root/dev' EXIT
chroot /work/root python3 /tmp/debian-package-state.py inventory --output /tmp/recovery-packages.json
chroot /work/root python3 /tmp/collect-debian-sources.py --output /tmp/recovery-sources \
    --inventory /tmp/recovery-packages.json --titan-source-ref "$TITAN_APP_SOURCE_COMMIT" --confirm-disposable-guest
cp /work/root/tmp/recovery-packages.json /output/recovery-packages.json
cp /work/root/tmp/recovery-sources/index.json /output/recovery-sources.json
tar -C /work/root/tmp/recovery-sources -cf - . | \
    split --bytes=1800000000 --numeric-suffixes=0 --suffix-length=3 - /output/recovery-sources.tar.part-
COLLECT
[[ "$(sha256sum "$task_iso")" == "$task_before" ]]
python3 scripts/collect-debian-sources.py --verify-index "$task_output/recovery-sources.json" \
    --inventory "$task_output/recovery-packages.json" --titan-source-ref "$TITAN_APP_SOURCE_COMMIT"
python3 scripts/verify-debian-source-archive.py --index "$task_output/recovery-sources.json" \
    --parts "$task_output"/recovery-sources.tar.part-*

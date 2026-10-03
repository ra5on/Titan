#!/bin/bash
# Called only after the real disposable-VM gates; never publishes partial output.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_REPOSITORY:-}" == ra5on/Titan ]] || exit 1
[[ "${TITAN_SYSTEM_VERSION:-}" =~ ^[0-9]+\.[0-9]+\.[0-9]+-(alpha|beta)\.[0-9]+$ ]] || exit 1
task_dir=$(realpath dist/debian-image)
python3 scripts/validate-system-evidence.py "$task_dir"
python3 scripts/system-release-metadata.py manifest --version "$TITAN_SYSTEM_VERSION" \
    --accounts "$task_dir/ab-input/system-accounts.json" --output "$task_dir/manifest.json" --bundle "$task_dir/titan-$TITAN_SYSTEM_VERSION-amd64.raucb" \
    --rootfs "$task_dir/bundle/rootfs.ext4" --evidence "$task_dir/release-evidence.json"
cp packaging/release-public.pem "$task_dir/release-public.pem"
cp packaging/rauc-root.pem "$task_dir/rauc-root.pem"
cp docs/RELEASE-0.4.10.md "$task_dir/INSTALLATION.md"
cp image/debian/base.json "$task_dir/debian-base.json"
task_image_assets=()
task_image_checks=()
if [[ "${TITAN_UPDATE_ONLY:-false}" != true ]]; then
    xz -T2 -3 "$task_dir/titan-$TITAN_SYSTEM_VERSION-amd64.img"
    [[ $(stat -c %s "$task_dir/titan-$TITAN_SYSTEM_VERSION-amd64.img.xz") -lt 2147483648 ]]
    task_image_assets=("$task_dir/titan-$TITAN_SYSTEM_VERSION-amd64.img.xz")
    task_image_checks=("titan-$TITAN_SYSTEM_VERSION-amd64.img.xz")
fi
[[ $(stat -c %s "$task_dir/titan-$TITAN_SYSTEM_VERSION-amd64.raucb") -lt 2147483648 ]]
(
    cd "$task_dir"
    sha256sum "${task_image_checks[@]}" "titan-$TITAN_SYSTEM_VERSION-amd64.raucb" \
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
    --title "Titan $TITAN_SYSTEM_VERSION · Debian A/B" --notes-file docs/RELEASE-0.4.10.md \
    "${task_image_assets[@]}" "$task_dir/titan-$TITAN_SYSTEM_VERSION-amd64.raucb" \
    "$task_dir/manifest.json" "$task_dir/manifest.json.sig" "$task_dir/SHA256SUMS" "$task_dir/SHA256SUMS.sig" \
    "$task_dir/release-public.pem" "$task_dir/rauc-root.pem" "$task_dir/runtime-test.json" "$task_dir/ab-test.json" \
    "$task_dir/INSTALLATION.md" "$task_dir/debian-base.json"

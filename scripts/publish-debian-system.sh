#!/bin/bash
# Called only after the real disposable-VM gates; never publishes partial output.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_REPOSITORY:-}" == ra5on/Titan ]] || exit 1
[[ "${TITAN_SYSTEM_VERSION:-}" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-(alpha|beta)\.[0-9]+)?$ ]] || exit 1
task_dir=$(realpath dist/debian-image)
if [[ "${TITAN_UPDATE_KIND:-titan}" == system ]]; then
    task_changes=$(python3 - "$task_dir/package-changes.json" <<'PYCHANGES'
import json,sys
from pathlib import Path
value=json.loads(Path(sys.argv[1]).read_text())['security_summary']['total_packages']
assert type(value) is int and value >= 0
print(value)
PYCHANGES
)
    if [[ "$task_changes" -eq 0 ]]; then
        echo 'Verified Debian package state is unchanged; no maintenance release is published.'
        exit 0
    fi
fi
python3 scripts/validate-system-evidence.py "$task_dir"
python3 scripts/collect-debian-sources.py --verify-index "$task_dir/debian-sources.json" \
    --inventory "$task_dir/debian-packages.json" --titan-source-ref "$TITAN_APP_SOURCE_COMMIT"
shopt -s nullglob
task_source_assets=("$task_dir"/debian-sources.tar.part-*)
[[ ${#task_source_assets[@]} -gt 0 ]]
task_source_checks=(debian-sources.json SOURCES.md)
for task_source_index in "${!task_source_assets[@]}"; do
    task_source_part=${task_source_assets[$task_source_index]}
    printf -v task_source_expected 'debian-sources.tar.part-%03d' "$task_source_index"
    [[ "$(basename "$task_source_part")" == "$task_source_expected" ]]
    task_source_size=$(stat -c %s "$task_source_part")
    [[ "$task_source_size" -gt 0 && "$task_source_size" -le 1800000000 ]]
    task_source_checks+=("$task_source_expected")
done
python3 scripts/verify-debian-source-archive.py --index "$task_dir/debian-sources.json" \
    --parts "${task_source_assets[@]}"
cp docs/DEBIAN-SOURCES.md "$task_dir/SOURCES.md"
TITAN_PACKAGE_CHANGES="$task_dir/package-changes.json" python3 scripts/system-release-metadata.py manifest --version "$TITAN_SYSTEM_VERSION" \
    --accounts "$task_dir/ab-input/system-accounts.json" --output "$task_dir/manifest.json" --bundle "$task_dir/titan-$TITAN_SYSTEM_VERSION-amd64.raucb" \
    --rootfs "$task_dir/bundle/rootfs.ext4" --evidence "$task_dir/release-evidence.json"
cp packaging/release-public.pem "$task_dir/release-public.pem"
cp packaging/rauc-root.pem "$task_dir/rauc-root.pem"
if [[ "${TITAN_UPDATE_KIND:-titan}" == system ]]; then
    python3 - "$task_dir/INSTALLATION.md" "$task_dir/package-changes.json" <<'PYNOTES'
import json,os,sys
from pathlib import Path
p=Path(sys.argv[1]); summary=json.loads(Path(sys.argv[2]).read_text())['security_summary']
p.write_text(f"# Titan · Debian-Systempflege {os.environ['TITAN_SYSTEM_VERSION']}\n\n"
             f"Titan {os.environ['TITAN_APP_VERSION']} ({os.environ['TITAN_APP_STAGE']}) bleibt unverändert. "
             f"Dieser signierte Systemstand enthält {summary['total_packages']} Paketänderungen, "
             f"davon {summary['security_packages']} Pakete mit Korrekturen aus Debian-Sicherheitsquellen.\n\n"
             "Systemsteuerung → Updates & Rollback → Jetzt prüfen. "
             "Installation bereitet die zweite Systempartition vor; Neustart wird manuell bestätigt. "
             "Rollback stellt auch den vorherigen Sicherheitsstand wieder her.\n\n"
             "Die vollständige Paketliste und die bestandenen Laufzeit-/Update-/Rollback-Prüfungen sind als Release-Dateien beigefügt.\n")
PYNOTES
    task_release_notes="$task_dir/INSTALLATION.md"
else
    task_release_notes="docs/RELEASE-${TITAN_APP_VERSION:-${TITAN_SYSTEM_VERSION%%-*}}.md"
    [[ -f "$task_release_notes" ]]
    cp "$task_release_notes" "$task_dir/INSTALLATION.md"
fi
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
        manifest.json manifest.json.sig runtime-test.json ab-test.json INSTALLATION.md debian-base.json debian-packages.json rauc-root.pem \
        "${task_source_checks[@]}" > SHA256SUMS
    openssl pkeyutl -sign -rawin -inkey "$RUNNER_TEMP/titan-signing/root.key" -in SHA256SUMS -out SHA256SUMS.sig
    openssl pkeyutl -verify -rawin -pubin -inkey release-public.pem -in SHA256SUMS -sigfile SHA256SUMS.sig
)
# A tag is immutable once published. A rerun must never replace user downloads.
if gh release view "v$TITAN_SYSTEM_VERSION" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
    echo 'Release already exists; choose a new version instead of replacing downloads.' >&2
    exit 1
fi
task_stage=()
if [[ "$TITAN_SYSTEM_VERSION" == *-alpha.* || "$TITAN_SYSTEM_VERSION" == *-beta.* ]]; then task_stage=(--prerelease); fi
gh release create "v$TITAN_SYSTEM_VERSION" --repo "$GITHUB_REPOSITORY" --target "${TITAN_BUILD_SOURCE_COMMIT:-$GITHUB_SHA}" "${task_stage[@]}" --latest=false \
    --title "Titan $TITAN_SYSTEM_VERSION · Debian A/B" --notes-file "$task_release_notes" \
    "${task_image_assets[@]}" "$task_dir/titan-$TITAN_SYSTEM_VERSION-amd64.raucb" \
    "$task_dir/manifest.json" "$task_dir/manifest.json.sig" "$task_dir/SHA256SUMS" "$task_dir/SHA256SUMS.sig" \
    "$task_dir/release-public.pem" "$task_dir/rauc-root.pem" "$task_dir/runtime-test.json" "$task_dir/ab-test.json" \
    "$task_dir/INSTALLATION.md" "$task_dir/debian-base.json" "$task_dir/debian-packages.json" \
    "$task_dir/debian-sources.json" "$task_dir/SOURCES.md" "${task_source_assets[@]}"

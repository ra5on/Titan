#!/bin/bash
# Independent web-only release. System discovery ignores the web-v namespace.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_REPOSITORY:-}" == ra5on/Titan ]] || exit 1
[[ -n "${TITAN_SIGNING_KEY:-}" && -n "${RUNNER_TEMP:-}" ]]
task_dir=$(realpath dist/web-container)
task_version=$(python3 -c 'from titan import __version__; print(__version__)')
[[ "$task_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 1
if gh release view "web-v$task_version" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
    echo 'This immutable web release already exists; increment the version.' >&2
    exit 1
fi
# Collect the exact Debian sources from the shipped container, not the runner.
# The collector verifies signed APT metadata and each source file checksum.
mkdir -p "$task_dir/source-output"
docker run --rm --user 0:0 --entrypoint python3 \
    --mount "type=bind,src=$(realpath scripts/collect-debian-sources.py),dst=/collect.py,readonly" \
    --mount "type=bind,src=$task_dir/source-output,dst=/output" \
    "titan-web:$task_version" /collect.py --output /output/sources \
    --titan-source-ref "$GITHUB_SHA" --confirm-disposable-guest
cp "$task_dir/source-output/sources/index.json" "$task_dir/web-debian-sources.json"
tar -C "$task_dir/source-output/sources" -cf - . | xz -T2 -1 > "$task_dir/web-debian-sources.tar.xz"
[[ $(stat -c %s "$task_dir/web-debian-sources.tar.xz") -lt 2147483648 ]]
umask 077
task_key=$(mktemp "$RUNNER_TEMP/titan-web-signing.XXXXXX")
trap 'rm -f "$task_key" "$task_key.pub"' EXIT
printf '%s\n' "$TITAN_SIGNING_KEY" > "$task_key"
openssl pkey -in "$task_key" -pubout -out "$task_key.pub"
cmp "$task_key.pub" packaging/release-public.pem
xz -T2 -3 -c "$task_dir/web-image.tar" > "$task_dir/web-container.tar.xz"
python3 - "$task_dir" "$GITHUB_SHA" <<'PY'
import hashlib,json,sys
from pathlib import Path
p=Path(sys.argv[1]);image=json.loads((p/'web-image.json').read_text());archive=p/'web-container.tar.xz'
with archive.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
sources=p/'web-debian-sources.tar.xz'
with sources.open('rb') as stream: source_digest=hashlib.file_digest(stream,'sha256').hexdigest()
manifest={'sources':{'name':sources.name,'size':sources.stat().st_size,'sha256':source_digest},'format':'titan-web-v1','source_commit':sys.argv[2],
          'web_container':{**image,'agent_api':1,'state_schema':1,'size':archive.stat().st_size,'sha256':digest}}
(p/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
PY
openssl pkeyutl -sign -rawin -inkey "$task_key" -in "$task_dir/manifest.json" -out "$task_dir/manifest.json.sig"
openssl pkeyutl -verify -rawin -pubin -inkey packaging/release-public.pem -in "$task_dir/manifest.json" -sigfile "$task_dir/manifest.json.sig"
cp packaging/release-public.pem "$task_dir/release-public.pem"
cp docs/WEB-CONTAINER.md "$task_dir/WEB-CONTAINER.md"
gh release create "web-v$task_version" --repo "$GITHUB_REPOSITORY" --verify-tag --latest=false \
    --title "Titan Web $task_version" --notes-file "$task_dir/WEB-CONTAINER.md" \
    "$task_dir/web-container.tar.xz" "$task_dir/web-image.json" "$task_dir/manifest.json" \
    "$task_dir/manifest.json.sig" "$task_dir/release-public.pem" \
    "$task_dir/web-debian-sources.json" "$task_dir/web-debian-sources.tar.xz"

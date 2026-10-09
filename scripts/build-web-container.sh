#!/bin/bash
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true ]] || { echo 'Run on a disposable GitHub Actions builder.' >&2; exit 1; }
task_source=$(realpath "${1:-.}")
task_version=$(cd "$task_source" && python3 -c 'from titan import __version__; print(__version__)')
[[ "$task_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 1
task_revision=$(git -C "$task_source" rev-parse HEAD)
mkdir -p dist/web-container
docker build --file "$task_source/packaging/container/Containerfile" \
    --build-arg "TITAN_VERSION=$task_version" --build-arg "TITAN_REVISION=$task_revision" \
    --tag "titan-web:$task_version" "$task_source"
TITAN_WEB_VERSION="$task_version" bash scripts/smoke-web-container.sh
TITAN_WEB_VERSION="$task_version" python3 scripts/smoke-web-container-lifecycle.py
docker save --output dist/web-container/web-image.tar "titan-web:$task_version"
python3 - "$task_version" <<'PY'
import json, subprocess, sys
from pathlib import Path
image=json.loads(subprocess.check_output(['docker','image','inspect','titan-web:'+sys.argv[1]]))[0]
Path('dist/web-container/web-image.json').write_text(json.dumps({'image':image['Id'],'version':sys.argv[1]})+'\n')
PY

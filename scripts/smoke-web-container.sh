#!/bin/bash
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true ]] || exit 1
task_version=${TITAN_WEB_VERSION:-$(python3 -c 'from titan import __version__; print(__version__)')}
task_data=$(mktemp -d)
chmod 0700 "$task_data"
cleanup() { docker logs titan-web-smoke || true; docker rm -f titan-web-smoke >/dev/null 2>&1 || true; }
trap cleanup EXIT
# Demo exercises the identical HTTP service and persistent SQLite format, with
# a simulated agent. The full NAS image suite supplies the actual agent test.
docker run -d --name titan-web-smoke --user "$(id -u):$(id -g)" --read-only --cap-drop ALL --security-opt no-new-privileges \
    --tmpfs /tmp:rw,nosuid,nodev,size=64m --mount "type=bind,src=$task_data,dst=/var/lib/titan" \
    -p 127.0.0.1:5099:5001 "titan-web:$task_version" --host 0.0.0.0 --port 5001 --demo
for task_try in {1..45}; do
    if curl --fail --silent http://127.0.0.1:5099/api/health > "$task_data/health.json"; then break; fi
    sleep 2
done
python3 - "$task_data/health.json" "$task_version" <<'PY'
import json,sys
v=json.load(open(sys.argv[1])); assert v['version']==sys.argv[2] and v['agent_api']==1
PY
curl --fail --silent http://127.0.0.1:5099/ > "$task_data/index.html"
grep -q '/ui-assets/' "$task_data/index.html"
# Check the route contract of the exact frozen application, including older
# sources used by Debian-only maintenance builds.
python3 - "$task_version" "$task_data/index.html" <<'PY'
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

origin = 'http://127.0.0.1:5099'
opener = urllib.request.build_opener(NoRedirect)
unified = tuple(map(int, sys.argv[1].split('.'))) >= (0, 8, 2)
for route in (('/classic', '/classic/') if unified else ('/classic',)):
    try:
        response = opener.open(origin + route, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        if unified:
            assert response.code == 302 and response.headers.get('Location') == '/', 'Classic must redirect to the unified desktop'
        else:
            assert response.code == 200 and b'shared_polling.js' in response.read(), 'Legacy desktop missing from frozen maintenance source'

index = Path(sys.argv[2]).read_text()
assets = set(re.findall(r'(?:src|href)="(/ui-assets/[^" ]+\.(?:js|css))"', index))
assert any(path.endswith('.js') for path in assets), 'Compiled desktop entry missing'
for path in assets:
    with urllib.request.urlopen(origin + path, timeout=10) as response:
        expected = ('text/javascript', 'application/javascript') if path.endswith('.js') else ('text/css',)
        assert response.status == 200 and response.headers.get_content_type() in expected, 'Invalid desktop asset: ' + path
        assert len(response.read()) > 100, 'Empty desktop asset: ' + path
print('Desktop routes and compiled JavaScript/CSS assets verified.')
PY
docker restart titan-web-smoke
for task_try in {1..30}; do
    if curl --fail --silent http://127.0.0.1:5099/api/health >/dev/null; then break; fi
    sleep 2
done
curl --fail --silent http://127.0.0.1:5099/api/session | python3 -c 'import json,sys; assert json.load(sys.stdin)["setup_required"] is False'
docker exec titan-web-smoke python3 -c 'import os; assert os.getuid()!=0; assert not os.path.exists("/var/run/docker.sock")'

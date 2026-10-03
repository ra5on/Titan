#!/bin/bash
set -euo pipefail
export LC_ALL=C.UTF-8
component=all
json=false
dry_run=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --component) component="${2:?Component required}"; shift 2 ;;
        --json) json=true; shift ;;
        --dry-run) dry_run=true; shift ;;
        *) exit 2 ;;
    esac
done
[[ "$component" =~ ^(all|docker|vms)$ ]] || exit 2
if $dry_run; then echo 'Debian: vorinstallierte Komponenten prüfen; keine Paketinstallation, keine Datenlaufwerke verändern.'; exit 0; fi
[[ "$EUID" == 0 && -d /run/systemd/system ]] || exit 1
/usr/bin/python3 - <<'PY'
import json, platform
from pathlib import Path
info=json.loads(Path('/usr/share/titan/image-info.json').read_text())
osinfo=platform.freedesktop_os_release()
assert osinfo['ID']=='debian' and osinfo['VERSION_ID']=='13'
assert (info['platform'],info['format'])in (('debian-preview','titan-debian-preview-v1'),('debian-rauc','titan-debian-ab-v1'))
PY
source /usr/share/titan/component-functions.sh
failed=0
docker_state=skip
vm_state=skip
if [[ "$component" == all || "$component" == docker ]]; then
    if install_apps >&2; then docker_state=ok; else docker_state=failed; failed=1; fi
fi
if [[ "$component" == all || "$component" == vms ]]; then
    if install_vm_components >&2; then vm_state=ok; else vm_state=failed; failed=1; fi
fi
if $json; then
    python3 - "$docker_state" "$vm_state" <<'PY'
import json,os,sys
values={k:{'ok':v=='ok','state':v} for k,v in zip(('docker','vms'),sys.argv[1:]) if v!='skip'}
warnings=['KVM fehlt: Virtualisierung im BIOS oder Hypervisor aktivieren.'] if sys.argv[2]=='ok' and not os.path.exists('/dev/kvm') else []
print(json.dumps({'ok':all(v['ok'] for v in values.values()),'components':values,'warnings':warnings}))
PY
fi
exit "$failed"

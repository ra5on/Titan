#!/bin/bash
set -euo pipefail
export LC_ALL=C.UTF-8
component=all
json=false
dry=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --component) [[ $# -ge 2 ]] || exit 2; component="$2"; shift 2 ;;
        --json) json=true; shift ;;
        --dry-run) dry=true; shift ;;
        *) printf '%s\n' 'Ungültige Komponentenoption.' >&2; exit 2 ;;
    esac
done
[[ "$component" =~ ^(all|docker|vms)$ ]] || exit 2
if $dry; then
    printf 'Komponenten: %s; vorinstallierte uCore-Komponenten prüfen und Dienste einrichten; keine Datenlaufwerke verändern.\n' "$component"
    exit 0
fi
[[ "$EUID" -eq 0 ]] || { printf '%s\n' 'Komponentenreparatur benötigt root.' >&2; exit 1; }
# Fixed image-baked helper: no package installs or downloaded executable code.
helper_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$helper_root/component-functions.sh"
source /etc/os-release
[[ "$ID" == fedora && -d /run/systemd/system ]] || { printf '%s\n' 'Titan-uCore-HCI mit systemd erforderlich.' >&2; exit 1; }
if ! /usr/bin/python3 - <<'PY'
import json
from pathlib import Path
try:
    info = json.loads(Path('/usr/share/titan/image-info.json').read_text())
    valid = (info.get('format') == 'titan-ucore-image-v1' and info.get('platform') == 'ucore-hci'
             and info.get('architecture') == 'x86_64')
except (OSError, ValueError, AttributeError):
    valid = False
raise SystemExit(0 if valid else 1)
PY
then
    printf '%s\n' 'Ein vollständiges Titan-uCore-HCI-Systemimage ist erforderlich.' >&2
    exit 1
fi
# Diagnostics go to stderr; stdout contains only the final JSON report.
docker_state=skip
vm_state=skip
failed=0
if [[ "$component" == all || "$component" == docker ]]; then
    if install_apps >&2; then docker_state=ok; else docker_state=failed; failed=1; fi
fi
if [[ "$component" == all || "$component" == vms ]]; then
    if install_vm_components >&2; then vm_state=ok; else vm_state=failed; failed=1; fi
fi
if $json; then
    /usr/bin/python3 - "$docker_state" "$vm_state" <<'PY'
import json,os,sys
states=dict(zip(('docker','vms'),sys.argv[1:]))
components={name:{'ok':state=='ok','state':state} for name,state in states.items() if state!='skip'}
warnings=[]
if states['vms']=='ok' and not os.path.exists('/dev/kvm'):
    warnings.append('VM-Komponenten und libvirt sind eingerichtet; /dev/kvm fehlt. Virtualisierung im BIOS/UEFI oder übergeordneten Hypervisor aktivieren.')
print(json.dumps({'ok':all(value['ok'] for value in components.values()),'components':components,'warnings':warnings}))
PY
fi
exit "$failed"

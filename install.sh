#!/bin/bash
set -euo pipefail
printf '%s\n' 'Titan wird als vollständiges Debian 13 Testimage ausgeliefert.' \
    'Das .img in eine neue Proxmox-VM importieren; bestehende NAS-Installationen nicht überschreiben.' \
    'Anleitung: https://github.com/ra5on/Titan/blob/main/docs/DEBIAN-PREVIEW.md' >&2
exit 1

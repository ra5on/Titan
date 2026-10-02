"""Explicit image profiles; never infer support from ID_LIKE or host packages."""
from dataclasses import dataclass
import json
from pathlib import Path
from .core import Error

IMAGE_INFO = Path('/usr/share/titan/image-info.json')

@dataclass(frozen=True)
class Profile:
    name: str
    samba_unit: str
    vm_unit: str
    qemu_user: str
    updates: str

UCORE = Profile('ucore-hci', 'smb.service', 'virtqemud.socket', 'qemu', 'bootc')
DEBIAN = Profile('debian-preview', 'smbd.service', 'libvirtd.socket', 'libvirt-qemu', 'disabled')

DEBIAN_AB = Profile('debian-rauc', 'smbd.service', 'libvirtd.socket', 'libvirt-qemu', 'rauc')

def current(path=None):
    path = IMAGE_INFO if path is None else Path(path)
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        # Existing tests and source-only development predate image profiles.
        # This fallback never enables a Debian install or an update backend.
        return UCORE
    except (OSError, ValueError):
        raise Error('Ungültige Titan-Plattformkennung.', 503) from None
    if not isinstance(data, dict):
        raise Error('Ungültige Titan-Plattformkennung.', 503)
    identity = (data.get('platform'), data.get('format'))
    if identity == ('ucore-hci', 'titan-ucore-image-v1'):
        return UCORE
    if identity == ('debian-preview', 'titan-debian-preview-v1'):
        return DEBIAN
    if identity == ('debian-rauc', 'titan-debian-ab-v1'):
        return DEBIAN_AB
    raise Error('Diese Titan-Systemplattform wird nicht unterstützt.', 503)

"""Read-only checks for the initial amd64 KVM/libvirt integration."""
import os
from pathlib import Path
import re
import shutil
import stat


def availability(device="/dev/kvm", cpuinfo="/proc/cpuinfo", novnc="/usr/share/novnc/core/rfb.js"):
    required = ("virsh", "qemu-img", "qemu-system-x86_64", "websockify")
    missing = [command for command in required if not shutil.which(command, path="/usr/sbin:/usr/bin:/sbin:/bin")]
    if not Path(novnc).is_file():
        missing.append("noVNC")
    result = {"available": False, "installed": not missing, "kvm": False, "missing": missing}
    if os.uname().machine not in ("x86_64", "amd64"):
        return {**result, "error": "Die aktuelle Titan-VM-Integration unterstützt amd64. Das NAS funktioniert auf dieser Architektur ohne VMs."}
    if missing:
        return {**result, "error": "VM-Komponenten fehlen: " + ", ".join(missing) + ". Das Titan-Systemimage ist unvollständig. Ein vollständiges Titan-Systemimage mit QEMU, libvirt und Browserkonsole installieren."}
    try:
        info = Path(device).lstat()
        if not stat.S_ISCHR(info.st_mode):
            return {**result, "error": "/dev/kvm ist kein gültiges KVM-Gerät. Kernelmodule und Virtualisierungseinstellungen prüfen."}
        if not os.access(device, os.R_OK | os.W_OK):
            return {**result, "error": "Der Verwaltungsdienst hat keinen Zugriff auf /dev/kvm. Dienstkonto und KVM-Geräterechte prüfen."}
    except OSError:
        try:
            flags = Path(cpuinfo).read_text()
        except OSError:
            flags = ""
        visible = bool(re.search(r"\b(?:vmx|svm)\b", flags))
        detail = ("Virtualisierungsfunktionen sind sichtbar; die Kernelmodule kvm und kvm_intel/kvm_amd sowie BIOS/UEFI prüfen."
                  if visible else "Intel VT-x/AMD-V im BIOS/UEFI aktivieren. Bei einer VM muss der übergeordnete Hypervisor verschachtelte Virtualisierung freigeben.")
        return {**result, "error": "VM-Pakete sind installiert, aber /dev/kvm fehlt. " + detail + " Die NAS-Funktionen bleiben verfügbar."}
    return {**result, "available": True, "kvm": True}

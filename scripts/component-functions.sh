#!/bin/bash
# The immutable Titan Debian image supplies packages. Runtime repair only
# verifies those programs and activates fixed, already installed services.
# The one exception is the NVIDIA driver: it is proprietary, so the image does
# not ship it. The administrator installs it from NVIDIA's own archive.

prepare_vm_runtime() {
    local task_cpu_info="${1:-/proc/cpuinfo}" task_kvm_device="${2:-/dev/kvm}" task_cpu_module=""
    if grep -Eiq '(^|[[:space:]])vmx([[:space:]]|$)' "$task_cpu_info"; then
        task_cpu_module=kvm_intel
    elif grep -Eiq '(^|[[:space:]])svm([[:space:]]|$)' "$task_cpu_info"; then
        task_cpu_module=kvm_amd
    fi
    if ! modprobe kvm; then
        printf '%s\n' 'Warnung: Das KVM-Kernelmodul konnte nicht geladen werden.' >&2
    fi
    if [[ -n "$task_cpu_module" ]] && ! modprobe "$task_cpu_module"; then
        printf 'Warnung: %s konnte nicht geladen werden.\n' "$task_cpu_module" >&2
    fi
    if [[ ! -c "$task_kvm_device" ]]; then
        if [[ -z "$task_cpu_module" ]]; then
            printf '%s\n' 'Warnung: CPU-Virtualisierung (Intel VT-x/AMD-V) ist nicht sichtbar. Im BIOS/UEFI oder im übergeordneten Hypervisor aktivieren.' >&2
        else
            printf '%s\n' 'Warnung: /dev/kvm fehlt trotz Virtualisierungsfunktion. BIOS/UEFI-Einstellungen und Kernelmodule prüfen.' >&2
        fi
        printf '%s\n' 'VM-Komponenten sind im Systemimage enthalten. Titan startet weiter; virtuelle Maschinen bleiben bis zur verfügbaren KVM-Unterstützung deaktiviert.' >&2
    fi
}

vm_network_active() {
    # --name is machine-readable and does not depend on translated net-info labels.
    LC_ALL=C LANG=C virsh -c qemu:///system net-list --name | grep -Fxq default
}

activate_vm_services() {
    local task_failed=0
    systemctl enable --now libvirtd.socket virtlogd.socket virtlockd.socket || return 1
    if ! LC_ALL=C LANG=C virsh -c qemu:///system net-info default >/dev/null 2>&1; then
        if ! LC_ALL=C LANG=C virsh -c qemu:///system net-define /usr/share/libvirt/networks/default.xml; then
            printf '%s\n' 'Warnung: Das Standardnetzwerk für VMs konnte nicht angelegt werden.' >&2
            return 1
        fi
    fi
    if ! LC_ALL=C LANG=C virsh -c qemu:///system net-autostart default; then
        printf '%s\n' 'Warnung: Automatischer Start des VM-Standardnetzwerks konnte nicht aktiviert werden.' >&2
        task_failed=1
    fi
    if ! vm_network_active; then
        if ! LC_ALL=C LANG=C virsh -c qemu:///system net-start default; then
            # Another manager may have started it since the first query.
            if ! vm_network_active; then
                printf '%s\n' 'Warnung: Das VM-Standardnetzwerk konnte nicht starten; Netzwerkstatus in libvirt prüfen.' >&2
                task_failed=1
            fi
        fi
    fi
    return "$task_failed"
}

install_apps() {
    if ! command -v docker >/dev/null 2>&1; then
        printf '%s\n' 'Docker fehlt im Titan-Systemimage. Ein vollständiges Titan-Debian-Image installieren oder aktualisieren.' >&2
        return 1
    fi
    if ! docker compose version; then
        printf '%s\n' 'Docker Compose fehlt im Titan-Systemimage. Systemimage aktualisieren.' >&2
        return 1
    fi
    systemctl enable --now docker.service || return 1
    if ! docker info --format '{{.ServerVersion}}'; then
        printf '%s\n' 'Docker ist enthalten, aber der Docker-Dienst antwortet nicht. journalctl -u docker -n 60 --no-pager prüfen.' >&2
        return 1
    fi
}

verify_vm_programs() {
    local task_command task_console="${1:-/usr/share/novnc/core/rfb.js}"
    for task_command in virsh qemu-img qemu-system-x86_64 websockify; do
        command -v "$task_command" >/dev/null 2>&1 || { printf 'VM-Programm fehlt im Systemimage: %s\n' "$task_command" >&2; return 1; }
    done
    [[ -f "$task_console" ]] || { printf '%s\n' 'noVNC fehlt im Titan-Systemimage.' >&2; return 1; }
}

install_vm_components() {
    if [[ "$(uname -m)" != x86_64 ]]; then
        printf '%s\n' 'Das aktuelle Titan-Debian-Image unterstützt x86_64.' >&2
        return 1
    fi
    verify_vm_programs || return 1
    prepare_vm_runtime || return 1
    activate_vm_services
}

component_library_end() {
    :
}

NVIDIA_REPOSITORY=https://developer.download.nvidia.com/compute/cuda/repos/debian13/x86_64
NVIDIA_KEY=/usr/share/keyrings/titan-nvidia.asc
NVIDIA_SOURCES=/etc/apt/sources.list.d/titan-nvidia.list
NVIDIA_MARKER=/var/lib/titan-agent/nvidia-component

nvidia_card_present() {
    local task_vendor
    for task_vendor in /sys/bus/pci/devices/*/vendor; do
        [[ -r "$task_vendor" && "$(cat "$task_vendor")" == 0x10de ]] && return 0
    done
    return 1
}

nvidia_ready() {
    command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1 && docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q '"nvidia"'
}

# Packages and kernel module for one kernel. Needs neither a card nor Docker,
# so CI can exercise the archive, the dependencies and the module build.
nvidia_packages() {
    local task_kernel="${1:?Kernel version required}"
    if [[ ! -e "/lib/modules/$task_kernel/build" ]]; then
        printf 'Kernel-Header für %s fehlen im Systemimage. Titan-Systemimage aktualisieren.\n' "$task_kernel" >&2
        return 1
    fi
    install -d -m 0755 /usr/share/keyrings /etc/apt/sources.list.d
    # apt accepts an ASCII-armoured key for signed-by; no extra tool is needed.
    if ! curl -fsSL --retry 3 --max-time 60 "$NVIDIA_REPOSITORY/8793F200.pub" -o "$NVIDIA_KEY.new"; then
        printf '%s\n' 'Der NVIDIA-Paketschlüssel konnte nicht geladen werden. Internetverbindung des NAS prüfen.' >&2
        rm -f "$NVIDIA_KEY.new"
        return 1
    fi
    grep -q 'BEGIN PGP PUBLIC KEY BLOCK' "$NVIDIA_KEY.new" || { rm -f "$NVIDIA_KEY.new"; printf '%s\n' 'NVIDIA lieferte keinen gültigen Paketschlüssel.' >&2; return 1; }
    mv "$NVIDIA_KEY.new" "$NVIDIA_KEY"
    chmod 0644 "$NVIDIA_KEY"
    printf 'deb [signed-by=%s] %s/ /\n' "$NVIDIA_KEY" "$NVIDIA_REPOSITORY" > "$NVIDIA_SOURCES"
    export DEBIAN_FRONTEND=noninteractive
    apt-get -o Acquire::Retries=3 update || return 1
    # Compute-only driver with the open kernel modules that current cards require.
    apt-get install -y --no-install-recommends nvidia-kernel-open-dkms nvidia-driver-cuda nvidia-container-toolkit || return 1
    dkms autoinstall -k "$task_kernel" || return 1
    depmod -a "$task_kernel"
    if ! dkms status -k "$task_kernel" | grep -i '^nvidia' | grep -q installed; then
        printf 'Das NVIDIA-Kernelmodul wurde für %s nicht gebaut.\n' "$task_kernel" >&2
        return 1
    fi
}

install_nvidia() {
    local task_free
    if ! nvidia_card_present; then
        printf '%s\n' 'Keine NVIDIA-Grafikkarte gefunden. Ist die Karte an eine virtuelle Maschine durchgereicht, zuerst die VM ausschalten.' >&2
        return 1
    fi
    if nvidia_ready; then
        install -D -m 0600 /dev/null "$NVIDIA_MARKER"
        return 0
    fi
    task_free=$(df --output=avail -k / | tail -n 1)
    if [[ "$task_free" -lt 4194304 ]]; then
        printf '%s\n' 'Auf dem Systembereich sind weniger als 4 GB frei; der Treiber passt nicht.' >&2
        return 1
    fi
    nvidia_packages "$(uname -r)" || return 1
    if ! modprobe nvidia; then
        printf '%s\n' 'Das NVIDIA-Kernelmodul lässt sich nicht laden. Secure Boot muss ausgeschaltet sein.' >&2
        return 1
    fi
    modprobe nvidia_uvm || true
    nvidia-ctk runtime configure --runtime=docker || return 1
    # Running apps restart with Docker; that is the only way they see the new runtime.
    systemctl restart docker.service || return 1
    if ! nvidia_ready; then
        printf '%s\n' 'Treiber installiert, aber nvidia-smi oder die Docker-Laufzeit antwortet nicht.' >&2
        return 1
    fi
    # Survives system updates: the next system slot reinstalls the driver at boot.
    install -D -m 0600 /dev/null "$NVIDIA_MARKER"
}

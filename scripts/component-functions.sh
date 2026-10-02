#!/bin/bash
# The immutable Titan uCore-HCI image supplies packages. Runtime repair only
# verifies those programs and activates fixed, already installed services.

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
    local task_failed=0 task_socket
    for task_socket in virtqemud virtnetworkd virtstoraged virtlogd virtlockd virtnodedevd virtnwfilterd virtsecretd; do
        if ! systemctl enable --now "$task_socket.socket"; then
            printf 'Warnung: %s.socket konnte nicht starten. Titan-Systemimage und Dienststatus prüfen.\n' "$task_socket" >&2
            task_failed=1
        fi
    done
    [[ "$task_failed" -eq 0 ]] || return 1
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
        printf '%s\n' 'Docker fehlt im Titan-Systemimage. Ein vollständiges Titan-uCore-HCI-Image installieren oder aktualisieren.' >&2
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
        printf '%s\n' 'Das aktuelle Titan-uCore-HCI-Image unterstützt x86_64.' >&2
        return 1
    fi
    verify_vm_programs || return 1
    prepare_vm_runtime || return 1
    activate_vm_services
}

component_library_end() {
    :
}

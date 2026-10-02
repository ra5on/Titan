#!/bin/bash
# The original ISO is never modified. Every target is a newly created VM disk.
set -euo pipefail
export LC_ALL=C.UTF-8
[[ "${GITHUB_ACTIONS:-}" == true ]] || { echo 'ISO installation tests require a disposable GitHub Actions runner.' >&2; exit 1; }
[[ "${3:-}" == --confirm-disposable-guest ]] || { echo 'Explicit disposable-guest confirmation required.' >&2; exit 1; }
task_iso="$(realpath -- "$1")"
task_image="$2"
[[ -f "$task_iso" && ! -b "$task_iso" ]] || { echo 'Regular ISO file required.' >&2; exit 1; }
task_output="$(dirname "$task_iso")"
task_dir="$(mktemp -d "$task_output/.iso-smoke.XXXXXX")"
task_pid=''
task_phase=iso_boot
export TITAN_ISO_BOOT=not-run TITAN_ISO_INSTALL=not-run TITAN_ISO_SYSTEM_BOOT=not-run TITAN_ISO_RUNTIME=not-run
stop_guest() {
    if [[ -n "$task_pid" ]]; then kill "$task_pid" 2>/dev/null || true; wait "$task_pid" 2>/dev/null || true; task_pid=''; fi
}
cleanup() {
    local task_result=$?
    stop_guest
    if [[ "$task_result" != 0 ]]; then
        case "$task_phase" in
            iso_boot) export TITAN_ISO_BOOT=failed ;;
            iso_install) export TITAN_ISO_INSTALL=failed ;;
            system_boot) export TITAN_ISO_SYSTEM_BOOT=failed ;;
            runtime) export TITAN_ISO_RUNTIME=failed ;;
        esac
    fi
    for task_log in public-uefi public-bios install; do
        if [[ -f "$task_dir/$task_log.log" ]]; then
            printf '\n=== %s ===\n' "$task_log" >> "$task_output/iso-console.log"
            cat -- "$task_dir/$task_log.log" >> "$task_output/iso-console.log"
        fi
    done
    if [[ -f "$task_dir/boot-status" ]]; then
        export TITAN_ISO_SYSTEM_BOOT="$(cat "$task_dir/boot-status")"
    fi
    if [[ -f "$task_dir/runtime-test.json" ]]; then
        cp -- "$task_dir/runtime-test.json" "$task_output/iso-runtime-test.json"
        export TITAN_ISO_RUNTIME="$(python3 -c 'import json,sys; print("passed" if json.load(open(sys.argv[1])).get("ok") is True else "failed")' "$task_dir/runtime-test.json")"
    fi
    if [[ -f "$task_dir/boot-console.log" ]]; then cp -- "$task_dir/boot-console.log" "$task_output/iso-system-boot-console.log"; fi
    if [[ -f "$task_dir/boot-http-error.txt" ]]; then cp -- "$task_dir/boot-http-error.txt" "$task_output/iso-http-error.txt"; fi
    python3 - "$task_output/iso-test.json" <<'PY'
import json,os,sys
fields={'boot_test':'TITAN_ISO_BOOT','install_test':'TITAN_ISO_INSTALL',
        'system_boot_test':'TITAN_ISO_SYSTEM_BOOT','runtime_test':'TITAN_ISO_RUNTIME'}
result={name:os.environ[variable] for name,variable in fields.items()}
result['ok']=all(value=='passed' for value in result.values())
result['scope']='BIOS/UEFI interactive boot without disk writes; offline installation to a disposable UEFI VM; installed HTTPS/setup/runtime'
result['limits']=['Human disk-selection interaction and physical hardware are not tested.',
                  'Runtime VM start is skipped when the runner provides no nested KVM.']
open(sys.argv[1],'w').write(json.dumps(result,indent=2)+'\n')
PY
    if [[ "$task_result" != 0 && -f "$task_output/iso-console.log" ]]; then tail -n 100 "$task_output/iso-console.log" >&2; fi
    rm -rf -- "$task_dir"
}
trap cleanup EXIT
task_accel=tcg
task_cpu=max
if [[ -r /dev/kvm && -w /dev/kvm ]]; then task_accel=kvm; task_cpu=host; fi
printf 'ISO tests: %s acceleration; isolated DHCP only, no external network during installation.\n' "$task_accel"
start_guest() {
    local task_cd="$1" task_disk="$2" task_log="$3" task_firmware="$4"
    local task_efi=()
    if [[ "$task_firmware" == uefi ]]; then
        cp /usr/share/OVMF/OVMF_VARS_4M.fd "$task_dir/vars.fd"
        task_efi=(-drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd -drive if=pflash,format=raw,file="$task_dir/vars.fd")
    fi
    qemu-system-x86_64 -accel "$task_accel" -machine q35 -cpu "$task_cpu" -m 4096 -smp 2 \
        -display none -monitor none -serial file:"$task_log" \
        -netdev user,id=isolated,restrict=on -device virtio-net-pci,netdev=isolated \
        "${task_efi[@]}" -drive if=virtio,format=raw,file="$task_disk" -cdrom "$task_cd" -boot order=d &
    task_pid=$!
}
wait_ready() {
    local task_log="$1" task_deadline=$((SECONDS + 1200)) task_next_log=$((SECONDS + 60))
    if [[ "$task_accel" == kvm ]]; then task_deadline=$((SECONDS + 600)); fi
    while (( SECONDS < task_deadline )); do
        kill -0 "$task_pid" 2>/dev/null || return 1
        if [[ -f "$task_log" ]] && grep -q 'TITAN_ISO_READY: offline payload present; target disk selection required' "$task_log"; then return 0; fi
        if (( SECONDS >= task_next_log )); then
            printf 'Waiting for interactive installer (%s).\n' "$(basename "$task_log")"
            tail -n 10 "$task_log" 2>/dev/null || true
            task_next_log=$((SECONDS + 60))
        fi
        sleep 2
    done
    return 1
}
python3 scripts/prepare-iso.py "$task_iso" --image "$task_image"
for task_firmware in uefi bios; do
    truncate -s 32G "$task_dir/public-$task_firmware.img"
    start_guest "$task_iso" "$task_dir/public-$task_firmware.img" "$task_dir/public-$task_firmware.log" "$task_firmware"
    wait_ready "$task_dir/public-$task_firmware.log"
    # Leave the installer at its initial interactive hub; no keys are sent.
    sleep 15
    kill -0 "$task_pid"
    stop_guest
    test "$(stat -c %b "$task_dir/public-$task_firmware.img")" = 0
    ! grep -q 'Install finished' "$task_dir/public-$task_firmware.log"
    printf 'Public ISO %s: installer reached; no target disk writes without selection.\n' "$task_firmware"
    rm -- "$task_dir/public-$task_firmware.img"
done
export TITAN_ISO_BOOT=passed
task_phase=iso_install
python3 scripts/prepare-iso.py "$task_iso" --image "$task_image" \
    --test-output "$task_dir/test-only.iso" --confirm-disposable-guest
truncate -s 32G "$task_dir/installed.img"
start_guest "$task_dir/test-only.iso" "$task_dir/installed.img" "$task_dir/install.log" uefi
task_deadline=$((SECONDS + 2400))
if [[ "$task_accel" == kvm ]]; then task_deadline=$((SECONDS + 1200)); fi
task_next_log=$((SECONDS + 60))
while kill -0 "$task_pid" 2>/dev/null && (( SECONDS < task_deadline )); do
    if (( SECONDS >= task_next_log )); then
        echo 'Waiting for offline installation to the disposable VM disk.'
        tail -n 10 "$task_dir/install.log" 2>/dev/null || true
        task_next_log=$((SECONDS + 60))
    fi
    sleep 2
done
! kill -0 "$task_pid" 2>/dev/null || { echo 'Offline installation did not finish before its deadline.' >&2; exit 1; }
wait "$task_pid"
task_pid=''
grep -q 'Install finished' "$task_dir/install.log"
test "$(stat -c %b "$task_dir/installed.img")" -gt 0
export TITAN_ISO_INSTALL=passed
task_phase=system_boot
rm -- "$task_dir/test-only.iso"
bash scripts/smoke-image.sh "$task_dir/installed.img"
export TITAN_ISO_SYSTEM_BOOT=passed TITAN_ISO_RUNTIME=passed
echo 'ISO installation and installed system passed their boot/runtime checks.'

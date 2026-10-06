#!/bin/bash
# Boot a throwaway overlay. Never boot or alter the distributable raw image.
set -euo pipefail
export LC_ALL=C.UTF-8
task_runtime_options=()
case "${2:-}" in
    "") ;;
    --debian-preview) task_runtime_options+=(--debian-preview) ;;
    --debian-ab) task_runtime_options+=(--debian-ab) ;;
    *) exit 2 ;;
esac
task_image="$(realpath -- "$1")"
test -f "$task_image"  # Never accept a host block device as a smoke image.
if [[ "${2:-}" == --debian-ab ]]; then
    task_machine_id=$(guestfish --ro -a "$task_image" -m /dev/sda3 cat /etc/machine-id)
    [[ -z "$task_machine_id" ]] || { echo 'Distribution image contains a fixed machine ID.' >&2; exit 1; }
fi
task_raw_hash="$(sha256sum -- "$task_image")"
task_raw_hash="${task_raw_hash%% *}"
task_dir="$(mktemp -d /tmp/titan-image-smoke.XXXXXXXX)"
task_pid=''
printf 'failed\n' > "$(dirname "$task_image")/boot-status"
cleanup() {
    local task_status=$?
    if [[ -f "$task_dir/console.log" ]]; then cp -- "$task_dir/console.log" "$(dirname "$task_image")/boot-console.log"; fi
    if [[ -f "$task_dir/curl-error.txt" ]]; then cp -- "$task_dir/curl-error.txt" "$(dirname "$task_image")/boot-http-error.txt"; fi
    if [[ "$task_status" != 0 && -f "$task_dir/console.log" ]]; then tail -n 100 "$task_dir/console.log" >&2; fi
    if [[ -n "$task_pid" ]]; then kill "$task_pid" 2>/dev/null || true; wait "$task_pid" 2>/dev/null || true; fi
    local task_raw_unchanged=false task_after_hash=''
    if task_after_hash="$(sha256sum -- "$task_image")" && [[ "${task_after_hash%% *}" == "$task_raw_hash" ]]; then
        task_raw_unchanged=true
    else
        task_status=1
        printf 'failed\n' > "$(dirname "$task_image")/boot-status"
    fi
    python3 - "$(dirname "$task_image")/runtime-test.json" "$task_raw_unchanged" <<'PY'
import json,sys
from pathlib import Path
path=Path(sys.argv[1]); unchanged=sys.argv[2]=='true'
if path.exists():
    value=json.loads(path.read_text())
    value['raw_image_unchanged']=unchanged
    if not unchanged: value['ok']=False
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
print('Original raw image SHA256 unchanged: '+str(unchanged).lower())
PY
    rm -rf -- "$task_dir"
    exit "$task_status"
}
trap cleanup EXIT
qemu-img create -q -f qcow2 -F raw -b "$task_image" "$task_dir/test.qcow2"
if [[ "${2:-}" == --debian-ab ]]; then
    qemu-img resize -q "$task_dir/test.qcow2" 64G
else
    qemu-img resize -q "$task_dir/test.qcow2" 32G
fi
if [[ "${2:-}" == --debian-ab ]]; then
    # A harmless legacy root unit exists only in this disposable overlay. It
    # deliberately starts before the containment helper, allowing the real
    # boot test to prove stopping a running unit as well as removing autostart.
    # The raw distribution image is never opened for writing.
    task_containment_fixture=$(python3 -c 'import secrets; print("titan-custom-smoke-" + secrets.token_hex(4) + ".service")')
    cat > "$task_dir/legacy-root.service" <<'UNIT'
[Unit]
Description=Disposable Titan legacy root containment proof
DefaultDependencies=no
After=local-fs.target
Before=titan-service-containment.service
[Service]
Type=simple
User=root
ExecStart=/usr/bin/sleep infinity
TimeoutStopSec=5
[Install]
WantedBy=basic.target
UNIT
    guestfish --rw --format=qcow2 -a "$task_dir/test.qcow2" -m /dev/sda3 <<GUEST
upload $task_dir/legacy-root.service /etc/systemd/system/$task_containment_fixture
chmod 0644 /etc/systemd/system/$task_containment_fixture
mkdir-p /etc/systemd/system/basic.target.wants
ln-s ../$task_containment_fixture /etc/systemd/system/basic.target.wants/$task_containment_fixture
GUEST
    task_runtime_options+=(--containment-fixture "$task_containment_fixture")
fi
cp /usr/share/OVMF/OVMF_VARS_4M.fd "$task_dir/vars.fd"
task_accel=tcg
task_cpu=max
if [[ -r /dev/kvm && -w /dev/kvm ]]; then task_accel=kvm; task_cpu=host; fi
printf 'Raw image boot test: %s acceleration.\n' "$task_accel"
qemu-system-x86_64 -accel "$task_accel" -machine q35 -cpu "$task_cpu" -m 3072 -smp 2 \
    -display none -monitor none -qmp unix:"$task_dir/qmp.sock",server=on,wait=off -serial file:"$task_dir/console.log" \
    -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd \
    -drive if=pflash,format=raw,file="$task_dir/vars.fd" \
    -drive id=titan-system,if=virtio,format=qcow2,file="$task_dir/test.qcow2" \
    -netdev user,id=net0,hostfwd=tcp:127.0.0.1:15000-:5000,hostfwd=tcp:127.0.0.1:15080-:18080,hostfwd=tcp:127.0.0.1:15445-:445 -device virtio-net-pci,netdev=net0 &
task_pid=$!
task_deadline=$((SECONDS + 1200))
if [[ "$task_accel" == kvm ]]; then task_deadline=$((SECONDS + 300)); fi
task_next_log=$((SECONDS + 60))
while (( SECONDS < task_deadline )); do
    if ! kill -0 "$task_pid" 2>/dev/null; then break; fi
    if task_http="$(curl --insecure --fail --silent --show-error --noproxy '*' --connect-timeout 2 --max-time 4 \
        --connect-to 10.0.2.15:5000:127.0.0.1:15000 \
        --write-out '%{http_code}' --output "$task_dir/session.json" \
        https://10.0.2.15:5000/api/session 2> "$task_dir/curl-error.txt")"; then
        python3 - "$task_dir/session.json" <<'PY'
import json,sys
value=json.load(open(sys.argv[1]))
from pathlib import Path
import importlib.util,os,re
expected=os.environ.get('TITAN_APP_VERSION')
if expected is None:
    # Older manual preview builds use their trusted local application source.
    # Maintenance must use the frozen identity validated by prepare-system-build.
    assert os.environ.get('TITAN_UPDATE_KIND')!='system', 'Frozen application version is required'
    spec=importlib.util.spec_from_file_location('version',Path.cwd()/'titan/__init__.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    expected=module.__version__
assert isinstance(expected,str) and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',expected), 'Invalid application version'
assert value['version']==expected, 'Guest application differs from the validated source'
assert value.get('setup_required') is True, value
assert value.get('user') is None and value.get('demo') is False, value
print('Clean raw image booted: HTTPS port 5000, initial administrator setup, no baked login.')
PY
        printf 'passed\n' > "$(dirname "$task_image")/boot-status"
        python3 scripts/smoke-runtime.py "${task_runtime_options[@]}" --confirm-disposable-guest --qmp-socket "$task_dir/qmp.sock" --report "$(dirname "$task_image")/runtime-test.json"
        exit 0
    fi
    if (( SECONDS >= task_next_log )); then
        printf 'Waiting for first-boot HTTPS (HTTP %s); transport error and recent guest console:\n' "$task_http"
        tail -n 5 "$task_dir/curl-error.txt" || true
        tail -n 60 "$task_dir/console.log" || true
        task_next_log=$((SECONDS + 60))
    fi
    sleep 5
done
printf '%s\n' 'Raw image failed its first-boot HTTPS smoke test. Public release and automatic updates are blocked, including Alpha; retain diagnostics for a separate disposable Proxmox test.' >&2
exit 1

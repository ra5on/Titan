#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p build/boot-test
cd build/boot-test
scratch=$(mktemp -d)
vm=
cleanup() {
  if [[ -n "$vm" ]]; then kill "$vm" 2>/dev/null || true; wait "$vm" || true; fi
  rm -rf "$scratch"
}
trap cleanup EXIT
qemu-img create -f qcow2 -F raw -b "$(realpath ../umbrelos-amd64.img)" boot.qcow2 96G
cp /usr/share/OVMF/OVMF_VARS_4M.fd vars.fd
accel=tcg
cpu=max
if [[ -r /dev/kvm && -w /dev/kvm ]]; then accel=kvm; cpu=host; fi

boot() {
  local phase=$1 slot
  local disks=()
  shift
  for slot in "$@"; do
    disks+=(-drive "if=none,id=raid$slot,format=qcow2,file=$scratch/raid$slot.qcow2")
    disks+=(-device "ide-hd,drive=raid$slot,bus=raid-ahci.$((slot - 1)),serial=TITANRAID$slot,rotation_rate=7200")
  done
  qemu-system-x86_64 -machine "q35,accel=$accel" -cpu "$cpu" -smp 2 -m 4096 \
    -drive if=pflash,unit=0,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd \
    -drive if=pflash,unit=1,format=raw,file=vars.fd \
    -drive if=none,id=disk,format=qcow2,file=boot.qcow2 -device nvme,drive=disk,serial=TITAN01,bootindex=0 \
    -device ahci,id=raid-ahci "${disks[@]}" \
    -netdev user,id=net,restrict=on,hostfwd=tcp:127.0.0.1:18080-:80 -device virtio-net-pci,netdev=net \
    -object "filter-dump,id=audit,netdev=net,file=$scratch/$phase.pcap" \
    -display none -monitor none -serial "file:$phase-serial.log" &
  vm=$!
}

wait_for_shutdown() {
  for ((attempt=0; attempt<120; attempt++)); do
    if ! kill -0 "$vm" 2>/dev/null; then wait "$vm"; vm=; return; fi
    sleep 1
  done
  echo 'Titan did not power off during the storage test' >&2
  return 1
}

storage_test() {
  node ../../../umbreld/scripts/test-titan-storage.mjs "$1" "$scratch/password" "$scratch/pools.json"
}

boot desktop
TITAN_STORAGE_TEST_PASSWORD_FILE="$scratch/password" node ../../../umbreld/scripts/test-titan-image.mjs "$PWD"
if [[ ${TITAN_EXPECTED_VERSION:-} != 0.1 && ${TITAN_EXPECTED_VERSION:-} != 0.2 ]]; then
  storage_test shutdown
  wait_for_shutdown
  for slot in 1 2 3 4; do qemu-img create -q -f qcow2 "$scratch/raid$slot.qcow2" 6G; done
  boot mirrors 1 2 3 4
  storage_test create
  wait_for_shutdown
  boot degraded 1
  storage_test degraded
fi

# Only extracted destinations are kept. The packet captures can contain session data.
kill "$vm"
wait "$vm" || true
vm=
for capture in "$scratch/"*.pcap; do
  tshark -r "$capture" -T fields -e dns.qry.name -e tls.handshake.extensions_server_name -e http.host
done | tr '\t' '\n' | sed '/^$/d' | sort -uf > network-hosts.txt
if grep -Eiq '(^|\.)(umbrel\.(com|dev)|getumbrel\.github\.io)\.?(:[0-9]+)?$' network-hosts.txt; then
  echo 'The guest attempted to contact an upstream service' >&2
  exit 1
fi

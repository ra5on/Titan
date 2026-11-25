#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p build/boot-test
cd build/boot-test
qemu-img create -f qcow2 -F raw -b "$(realpath ../umbrelos-amd64.img)" boot.qcow2 96G
cp /usr/share/OVMF/OVMF_VARS_4M.fd vars.fd
accel=tcg
cpu=max
if [[ -r /dev/kvm && -w /dev/kvm ]]; then accel=kvm; cpu=host; fi
qemu-system-x86_64 -machine "q35,accel=$accel" -cpu "$cpu" -smp 2 -m 4096 \
  -drive if=pflash,unit=0,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd \
  -drive if=pflash,unit=1,format=raw,file=vars.fd \
  -drive if=none,id=disk,format=qcow2,file=boot.qcow2 -device nvme,drive=disk,serial=TITAN01 \
  -netdev user,id=net,restrict=on,hostfwd=tcp:127.0.0.1:18080-:80 -device virtio-net-pci,netdev=net \
  -object filter-dump,id=audit,netdev=net,file=traffic.pcap \
  -display none -monitor none -serial file:serial.log &
vm=$!
trap 'kill "$vm" 2>/dev/null || true; wait "$vm" || true' EXIT
node ../../../umbreld/scripts/test-titan-image.mjs "$PWD"

# Only extracted destinations are kept. The packet capture can contain session data.
kill "$vm"
wait "$vm" || true
trap - EXIT
tshark -r traffic.pcap -T fields -e dns.qry.name -e tls.handshake.extensions_server_name -e http.host \
  | tr '\t,' '\n' | sed '/^$/d' | sort -uf > network-hosts.txt
rm traffic.pcap
if grep -Eiq '(^|\.)(umbrel\.(com|dev)|getumbrel\.github\.io)\.?(:[0-9]+)?$' network-hosts.txt; then
  echo 'The guest attempted to contact an upstream service' >&2
  exit 1
fi

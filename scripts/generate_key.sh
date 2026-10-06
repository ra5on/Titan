#!/bin/bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -e "$task_root/.secrets/release-private.pem" || -e "$task_root/packaging/release-public.pem" ]]; then
    printf '%s\n' 'Schlüssel existiert bereits; kein Überschreiben.' >&2
    exit 1
fi
mkdir -p "$task_root/.secrets"
chmod 700 "$task_root/.secrets"
umask 077
openssl genpkey -algorithm ED25519 -out "$task_root/.secrets/release-private.pem"
openssl pkey -in "$task_root/.secrets/release-private.pem" -pubout -out "$task_root/packaging/release-public.pem"
chmod 644 "$task_root/packaging/release-public.pem"
printf '%s\n' 'Öffentlicher Schlüssel erstellt. Privater Schlüssel liegt ausschließlich in .secrets/ (gitignored).'

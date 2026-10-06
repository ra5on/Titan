#!/bin/bash
# CI-only signing workspace; private material stays outside published artifacts.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && -n "${RUNNER_TEMP:-}" && -n "${TITAN_SIGNING_KEY:-}" ]] || exit 1
umask 077
task_keys="$RUNNER_TEMP/titan-signing"
mkdir -p "$task_keys"
printf '%s\n' "$TITAN_SIGNING_KEY" > "$task_keys/root.key"
openssl pkey -in "$task_keys/root.key" -pubout -out "$task_keys/public.pem"
cmp "$task_keys/public.pem" packaging/release-public.pem
openssl x509 -in packaging/rauc-root.pem -pubkey -noout > "$task_keys/ca-public.pem"
cmp "$task_keys/public.pem" "$task_keys/ca-public.pem"
openssl ecparam -name prime256v1 -genkey -noout -out "$task_keys/bundle.key"
openssl req -new -key "$task_keys/bundle.key" -out "$task_keys/bundle.csr" -subj '/CN=Titan CI System Bundle'
printf 'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=codeSigning\n' > "$task_keys/leaf.ext"
openssl x509 -req -in "$task_keys/bundle.csr" -CA packaging/rauc-root.pem -CAkey "$task_keys/root.key" \
    -set_serial "$(openssl rand -hex 16 | sed 's/^/0x/')" -days 3650 -extfile "$task_keys/leaf.ext" -out "$task_keys/bundle.pem"
openssl verify -CAfile packaging/rauc-root.pem "$task_keys/bundle.pem"
# RAUC uses CMS; prove the ECDSA leaf signed by our Ed25519 root is accepted.
printf 'Titan signing chain check\n' > "$task_keys/check.txt"
openssl cms -sign -binary -in "$task_keys/check.txt" -signer "$task_keys/bundle.pem" -inkey "$task_keys/bundle.key" -outform DER -out "$task_keys/check.cms"
openssl cms -verify -binary -inform DER -in "$task_keys/check.cms" -content "$task_keys/check.txt" -CAfile packaging/rauc-root.pem -purpose any -out /dev/null

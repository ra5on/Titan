#!/usr/bin/env bash
# Configure only a disposable GitHub-hosted Ubuntu runner, never a Titan NAS.
set -euo pipefail
if [[ "${GITHUB_ACTIONS:-}" != true || "${RUNNER_ENVIRONMENT:-}" != github-hosted ]]; then
  echo 'Requires a disposable GitHub-hosted runner.' >&2
  exit 2
fi
if [[ "$#" -eq 0 ]]; then
  echo 'Specify the build dependencies to install.' >&2
  exit 2
fi
# The runner's Azure mirror can stall after its InRelease fallback. Keep package
# metadata and payloads on the same official HTTPS archive; APT verifies signatures.
if [[ -f /etc/apt/apt-mirrors.txt ]]; then
  printf '%s\n' 'https://archive.ubuntu.com/ubuntu/' | sudo tee /etc/apt/apt-mirrors.txt >/dev/null
fi
if [[ -f /etc/apt/apt-mirrors-security.txt ]]; then
  printf '%s\n' 'https://security.ubuntu.com/ubuntu/' | sudo tee /etc/apt/apt-mirrors-security.txt >/dev/null
fi
apt_options=(-o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30)
sudo apt-get "${apt_options[@]}" -o APT::Update::Error-Mode=any update
sudo apt-get "${apt_options[@]}" install -y "$@"

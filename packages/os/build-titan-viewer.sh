#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p build
docker buildx build --platform linux/amd64 --load -t titan-viewer:build viewer
docker image save titan-viewer:build | gzip -1 > build/titan-viewer.tar.gz
jq -n --arg image "$(docker image inspect -f '{{.Id}}' titan-viewer:build)" \
  --arg sha256 "$(sha256sum build/titan-viewer.tar.gz | cut -d' ' -f1)" \
  --argjson size "$(stat -c %s build/titan-viewer.tar.gz)" \
  '{image:$image,sha256:$sha256,size:$size}' > viewer/image.json

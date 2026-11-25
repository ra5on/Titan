#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
version=$(jq -er .titanVersion ../umbreld/package.json)
[[ $version =~ ^(0|[1-9][0-9]*)\.[0-9]$ && $version != 0.0 ]]
[[ -e ../ui/dist/index.html ]] || { echo 'Build the Titan web UI first.' >&2; exit 1; }
mkdir -p build
docker buildx build --platform linux/amd64 -f titan.Dockerfile \
    --output "type=tar,dest=build/umbrelos-root-amd64.tar" ../..
SKIP_ROOTS=true SKIP_AMD64_MENDER=true SKIP_ARM64=true SKIP_PI=true ./build.sh "$version"
release_dir="build/titan-$version"
mkdir -p "$release_dir"
xz -T2 -c build/umbrelos-amd64.img > "$release_dir/titan-amd64.img.xz"
cp build/umbrelos-amd64.update "$release_dir/titan-amd64.update"
cp build/umbrelos-amd64.update.hash build/titan-amd64.update.hash
RELEASE_TAG="$version" ./create-release-manifest.sh "$release_dir"

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
version=$(jq -er .titanVersion ../umbreld/package.json)
[[ $version =~ ^(0|[1-9][0-9]*)\.[0-9]$ && $version != 0.0 ]]
[[ -e ../ui/dist/index.html ]] || { echo 'Build the Titan web UI first.' >&2; exit 1; }
mkdir -p build
./build-titan-viewer.sh
docker buildx build --platform linux/amd64 -f titan.Dockerfile \
    --output "type=tar,dest=build/umbrelos-root-amd64.tar" ../..
SKIP_ROOTS=true SKIP_AMD64_MENDER=true SKIP_ARM64=true SKIP_PI=true ./build.sh "$version"
# Never mix parts and full bundles left by a previous run.
release_dir=$(mktemp -d "build/.titan-${version}.XXXXXX")
trap 'rm -rf "$release_dir"' EXIT
xz -T2 -c build/umbrelos-amd64.img > "$release_dir/titan-amd64.img.xz"
# GitHub release assets must each be strictly smaller than 2 GiB.
if (( $(stat -c %s build/umbrelos-amd64.update) >= 2147483648 )); then
    split -b 1G -d -a 2 build/umbrelos-amd64.update "$release_dir/titan-amd64.update."
    cp build/umbrelos-amd64.update.hash build/titan-amd64.update.00.hash
else
    cp build/umbrelos-amd64.update "$release_dir/titan-amd64.update"
    cp build/umbrelos-amd64.update.hash build/titan-amd64.update.hash
fi
cp build/titan-viewer.tar.gz "$release_dir/"
RELEASE_TAG="$version" ./create-release-manifest.sh "$release_dir"

# Replace only a completed build's output directory.
rm -rf "build/titan-$version"
mv "$release_dir" "build/titan-$version"

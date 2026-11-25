#!/usr/bin/env python3
"""Export the installed binary and source package versions for a Titan release."""
import argparse
import re
from email.parser import Parser
from pathlib import Path
from urllib.parse import quote


def package_origin(package, source, version, nvidia_packages):
    release = version.split(":")[-1].split("-")[0]
    if package in nvidia_packages:
        if package == "nvidia-kernel-open-dkms":
            return f"https://github.com/NVIDIA/open-gpu-kernel-modules/tree/{release}"
        return "https://developer.download.nvidia.com/compute/cuda/repos/debian13/x86_64/"
    if package in {"libnvidia-container1", "libnvidia-container-tools"}:
        return f"https://github.com/NVIDIA/libnvidia-container/tree/v{release}"
    if package.startswith("nvidia-container-toolkit"):
        return f"https://github.com/NVIDIA/nvidia-container-toolkit/tree/v{release}"
    docker_sources = {
        "containerd.io": "containerd/containerd", "docker-ce": "moby/moby",
        "docker-ce-cli": "docker/cli", "docker-ce-rootless-extras": "moby/moby",
        "docker-buildx-plugin": "docker/buildx", "docker-compose-plugin": "docker/compose",
        "docker-model-plugin": "docker/model-runner",
    }
    if package in docker_sources:
        return f"https://github.com/{docker_sources[package]}/tree/v{release}"
    # The extra avahi patches are shipped in the source tree at packages/os/avahi-patches.
    original = version.removesuffix("+umbrel1")
    return f"https://snapshot.debian.org/package/{quote(source, safe='')}/{quote(original, safe='')}/"


def packages(status):
    for paragraph in status.read_text().strip().split("\n\n"):
        record = Parser().parsestr(paragraph, headersonly=True)
        if record["Status"] == "install ok installed":
            package = record["Package"]
            source_field = record["Source"] or package
            source, source_version = re.fullmatch(r"([\w.+-]+)(?: \(([^)]+)\))?", source_field).groups()
            yield package, record["Version"], source, source_version or record["Version"]
            # Signed kernels and statically linked binaries can name extra sources.
            for field in ("Built-Using", "Static-Built-Using"):
                for name, built_version in re.findall(r"([\w.+-]+) \(= ([^()]+)\)", record[field] or ""):
                    yield package, record["Version"], name, built_version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("system", type=Path)
    parser.add_argument("viewer", type=Path)
    args = parser.parse_args()
    pins = Path(__file__).with_name("nvidia-driver-packages.sha256")
    nvidia = {line.split()[1].split("_")[0] for line in pins.read_text().splitlines() if line}
    print("Komponente\tBinärpaket\tBinärversion\tQuellpaket\tQuellversion\tBezugsquelle")
    for component, status in [("Titan", args.system), ("App-Browser", args.viewer)]:
        for package, version, source, source_version in sorted(packages(status)):
            origin = package_origin(package, source, source_version, nvidia)
            print(component, package, version, source, source_version, origin, sep="\t")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Run Titan's Btrfs volume code against the real kernel and btrfs-progs.

Uses loop devices over temporary image files and must run as root on a
throw-away machine (the CI runner): it mounts below /srv and adds entries to
/etc/fstab. It covers what the unit tests can only simulate: a single volume,
a mirror, a missing disk, the guided replacement and the proactive one.
"""
import hashlib
import os
from pathlib import Path
import re
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from titan.core import Error  # noqa: E402
from titan.host import Host, run  # noqa: E402
from titan.volumes import Volumes  # noqa: E402


def step(text):
    print("\n== " + text, flush=True)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def profiles(target):
    """Block group profiles in use, ignoring the always-single global reserve."""
    lines = [line for line in run(["btrfs", "filesystem", "df", target]).splitlines() if not line.startswith("GlobalReserve")]
    print("\n".join(lines))
    return {line.split(":")[0].split(", ")[1] for line in lines}


def wait_for_replacement(manager, name, seconds=180):
    deadline = time.time() + seconds
    while time.time() < deadline:
        manager.maintain()
        if not manager.record(name).get("replacing"):
            return
        print("  ", manager.inventory()["volumes"][-1]["replacing"], flush=True)
        time.sleep(2)
    raise SystemExit("Replacement did not finish in time.")


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run as root on a throw-away machine.")
    work = Path(tempfile.mkdtemp(prefix="titan-btrfs-"))
    share_root = Path("/srv/titan-check")
    share_root.mkdir(mode=0o755)
    host = Host(work / "agent", share_root, work / "vms", work / "smb.conf")
    manager = Volumes(host, run)
    manager.disk_pattern, manager.disk_types = re.compile(r"/dev/loop[0-9]+\Z"), ("loop",)
    host._volumes = manager

    loops = []
    for index in range(6):
        image = work / f"disk{index}.img"
        with open(image, "wb") as stream:
            stream.truncate(300 * 1024**2 if index == 5 else 1024**3)
        loops.append(run(["losetup", "--find", "--show", str(image)]))
    single, first, second, spare, fresh, small = loops
    print("Loop devices:", loops)

    step("A single Btrfs volume")
    manager.create("einzel", single, "btrfs", "einzel", single)
    row = next(item for item in manager.inventory()["volumes"] if item["name"] == "einzel")
    assert row["mounted"] and not row["mirror"] and row["disks"] == [single], row

    step("A mirror over two disks")
    result = manager.create("spiegel", first, "btrfs", "spiegel", first, [second])
    target = result["path"]
    assert profiles(target) == {"RAID1"}
    row = manager.inventory()["volumes"][-1]
    assert row["mounted"] and row["mirror"] and not row["degraded"] and sorted(row["disks"]) == sorted([first, second]), row
    Path(target, "daten.bin").write_bytes(os.urandom(64 * 1024**2))
    expected = digest(Path(target, "daten.bin"))
    run(["sync"])

    step("One disk disappears, as after a restart with a dead drive")
    run(["umount", target])
    run(["losetup", "--detach", second])
    run(["btrfs", "device", "scan", "--forget"])
    run(["udevadm", "settle"])
    try:
        manager.mount("spiegel")
    except Error as exc:
        assert exc.status == 409, exc
        print("Refused as intended:", exc)
    else:
        raise SystemExit("A mirror with a missing disk was mounted without a replacement.")
    row = manager.inventory()["volumes"][-1]
    assert row["degraded"] and not row["mounted"] and row["state"] == "Laufwerk fehlt", row

    step("A disk that is too small is refused and leaves nothing pending")
    try:
        manager.replace("spiegel", small, "spiegel", small)
    except Error as exc:
        print("Refused as intended:", exc)
    else:
        raise SystemExit("A replacement disk smaller than the lost one was accepted.")
    assert not manager.record("spiegel").get("replacing")

    step("The missing disk is replaced")
    Path(target, "waehrenddessen.txt").write_text("geschrieben mit nur einer Kopie\n")
    print(manager.replace("spiegel", spare, "spiegel", spare)["message"])
    wait_for_replacement(manager, "spiegel")
    record = manager.record("spiegel")
    assert sorted(record["disks"]) == sorted([first, spare]) and not record.get("error"), record
    row = manager.inventory()["volumes"][-1]
    assert row["mounted"] and not row["degraded"] and not row["errors"] and row["state"] == "Eingehängt", row
    assert profiles(target) == {"RAID1"}, "Data written with one disk missing was not mirrored again."
    assert digest(Path(target, "daten.bin")) == expected
    print(run(["btrfs", "filesystem", "show", target]))

    step("A present disk is replaced before it fails")
    print(manager.replace("spiegel", fresh, "spiegel", fresh, first)["message"])
    wait_for_replacement(manager, "spiegel")
    record = manager.record("spiegel")
    assert sorted(record["disks"]) == sorted([spare, fresh]), record
    assert digest(Path(target, "daten.bin")) == expected

    step("The repaired mirror mounts normally again and passes a full check")
    run(["umount", target])
    run(["btrfs", "device", "scan", "--forget"])
    run(["udevadm", "settle"])
    manager.mount("spiegel")
    assert "degraded" not in run(["findmnt", "--noheadings", "--output", "OPTIONS", target])
    print(run(["btrfs", "scrub", "start", "-B", target], include_stderr=True))
    assert manager.mirror_health(manager.record("spiegel")) == {"missing": [], "errors": 0, "replacing": False, "present": sorted([spare, fresh])}
    assert digest(Path(target, "daten.bin")) == expected
    assert manager.scrub_due(manager.record("spiegel"), time.time() + 31 * 86400)
    print("\nAll Btrfs volume checks passed.")


if __name__ == "__main__":
    main()

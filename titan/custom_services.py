"""Early-boot containment of legacy Titan custom services running as UID 0.

This file also runs directly with Python's isolated mode. It deliberately has
no imports from Titan or writable NAS data. Only canonical Titan custom unit
names are acted on; distribution services and user services are left alone.
"""
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import time

CUSTOM_UNIT = re.compile(r"titan-custom-[a-z][a-z0-9_-]{0,30}\.service\Z")
USER_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}\Z")
REPORT_PATH = Path("/run/titan-service-containment/result.json")
REPORT_FORMAT = "titan-custom-service-containment-v1"
MAX_UNITS = 256
MAX_INVENTORY_BYTES = 4 * 1024 * 1024
MAX_REPORT_BYTES = 65536
PROPERTIES = ("Id", "Names", "User", "LoadState", "ActiveState", "UnitFileState", "MainPID")


class ContainmentFailure(Exception):
    """Fixed diagnostic category, never subprocess output or service secrets."""


def identity_uid(value, lookup=None):
    if not isinstance(value, str) or len(value) > 64:
        raise ContainmentFailure("unknown_identity")
    if value == "":
        return 0  # The system manager's default User is root.
    if value.isascii() and value.isdecimal():
        uid = int(value)
        if uid < 2**32 - 1:
            return uid
        raise ContainmentFailure("unknown_identity")
    if not USER_NAME.fullmatch(value):
        raise ContainmentFailure("unknown_identity")
    try:
        uid = (lookup or pwd.getpwnam)(value).pw_uid
    except (KeyError, OSError):
        raise ContainmentFailure("unknown_identity") from None
    if type(uid) is not int or not 0 <= uid < 2**32 - 1:
        raise ContainmentFailure("unknown_identity")
    return uid


def unsafe_custom_identity(name, properties):
    """Unknown identities are denied by the API, including aliases of UID 0."""
    names = {name, properties.get("Id", "")} | set(properties.get("Names", "").split())
    if not any(isinstance(item, str) and item.startswith("titan-custom-") for item in names):
        return False
    try:
        return identity_uid(properties.get("User")) == 0
    except ContainmentFailure:
        return True


def _systemctl(arguments, timeout):
    # The environment and executable are fixed, independent of NAS data.
    try:
        result = subprocess.run(["/usr/bin/systemctl", *arguments], check=False,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C.UTF-8", "SYSTEMD_PAGER": "cat"})
    except (OSError, subprocess.TimeoutExpired):
        raise ContainmentFailure("systemctl_failed") from None
    if result.returncode or len(result.stdout) > MAX_INVENTORY_BYTES:
        raise ContainmentFailure("systemctl_failed")
    try:
        return result.stdout.decode("utf-8")
    except UnicodeError:
        raise ContainmentFailure("invalid_inventory") from None


class Containment:
    def __init__(self, run=None, lookup=None, clock=None, sleep=None, timeout=60):
        self.run = run or _systemctl
        self.lookup = lookup
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.deadline = self.clock() + timeout
        self.blocked = []

    def command(self, arguments):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise ContainmentFailure("containment_timeout")
        return self.run(arguments, timeout=min(10, remaining))

    def inventory(self):
        names = set()
        for command, key in ((["list-unit-files", "--type=service", "--no-pager", "--no-legend", "--output=json"], "unit_file"),
                (["list-units", "--all", "--type=service", "--no-pager", "--no-legend", "--plain", "--output=json"], "unit")):
            output = self.command(command)
            if not isinstance(output, str) or len(output.encode()) > MAX_INVENTORY_BYTES:
                raise ContainmentFailure("invalid_inventory")
            try:
                rows = json.loads(output)
            except (ValueError, TypeError):
                raise ContainmentFailure("invalid_inventory") from None
            if not isinstance(rows, list) or len(rows) > 20000 or any(not isinstance(row, dict) for row in rows):
                raise ContainmentFailure("invalid_inventory")
            for row in rows:
                name = row.get(key)
                if isinstance(name, str) and name.startswith("titan-custom-"):
                    if not CUSTOM_UNIT.fullmatch(name):
                        raise ContainmentFailure("invalid_custom_unit")
                    names.add(name)
                    if len(names) > MAX_UNITS:
                        raise ContainmentFailure("too_many_custom_units")
        return sorted(names)

    def properties(self, name):
        output = self.command(["show", "--no-pager", "--property=" + ",".join(PROPERTIES), "--", name])
        if not isinstance(output, str) or len(output.encode()) > MAX_REPORT_BYTES:
            raise ContainmentFailure("invalid_unit_properties")
        properties = {}
        for line in output.splitlines():
            key, separator, value = line.partition("=")
            if separator and key in PROPERTIES:
                if key in properties or any(ord(char) < 32 or ord(char) == 127 for char in value):
                    raise ContainmentFailure("invalid_unit_properties")
                properties[key] = value
        if set(properties) != set(PROPERTIES) or properties["LoadState"] not in ("loaded", "masked"):
            raise ContainmentFailure("invalid_unit_properties")
        canonical = properties["Id"]
        aliases = properties["Names"].split()
        if not CUSTOM_UNIT.fullmatch(canonical) or any(not CUSTOM_UNIT.fullmatch(alias) for alias in aliases):
            # A custom-looking alias must never cause a distro unit to stop.
            raise ContainmentFailure("foreign_unit_alias")
        if name not in aliases or canonical not in aliases:
            raise ContainmentFailure("invalid_unit_properties")
        if not properties["MainPID"].isascii() or not properties["MainPID"].isdecimal() or len(properties["MainPID"]) > 10:
            raise ContainmentFailure("invalid_unit_properties")
        return properties

    def contain(self):
        units = {}
        # Resolve every identity before any mutation. Unknown/foreign units
        # fail closed; the management agent cannot start on that boot.
        for name in self.inventory():
            properties = self.properties(name)
            if identity_uid(properties["User"], self.lookup) == 0:
                canonical = properties["Id"]
                units[canonical] = {"name": canonical,
                    "was_running": properties["ActiveState"] not in ("inactive", "failed"),
                    "was_enabled": properties["UnitFileState"] in ("enabled", "enabled-runtime")}
        self.blocked = sorted(units.values(), key=lambda item: item["name"])
        if not units:
            return self.result(True)
        names = sorted(units)
        disable_failure = False
        for arguments in (["disable", "--", *names], ["--runtime", "disable", "--", *names]):
            try:
                self.command(arguments)
            except ContainmentFailure:
                disable_failure = True
        # Submit stop without waiting for early-boot jobs requiring basic.target.
        # Even a failed disable must attempt stopping the known legacy units.
        self.command(["--no-block", "stop", "--", *names])
        if disable_failure:
            raise ContainmentFailure("disable_failed")
        while True:
            complete = True
            for name in names:
                properties = self.properties(name)
                if (identity_uid(properties["User"], self.lookup) != 0 or properties["Id"] != name):
                    raise ContainmentFailure("unit_changed_during_containment")
                if (properties["ActiveState"] not in ("inactive", "failed") or properties["MainPID"] != "0"):
                    complete = False
                if properties["UnitFileState"] not in ("disabled", "static", "masked", "masked-runtime", "linked", "linked-runtime"):
                    raise ContainmentFailure("unit_still_enabled")
            if complete:
                return self.result(True)
            if self.clock() + 0.2 >= self.deadline:
                raise ContainmentFailure("stop_timeout")
            self.sleep(0.2)

    def result(self, ok, error=""):
        return {"format": REPORT_FORMAT, "ok": ok, "blocked_units": self.blocked,
                "error_category": error, "checked_at": int(time.time())}


def write_report(value, path=REPORT_PATH):
    """Publish only into a trusted private runtime directory, without symlinks."""
    path = Path(path)
    encoded = (json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if len(encoded) > MAX_REPORT_BYTES:
        raise ContainmentFailure("diagnostic_failed")
    directory = os.open(path.parent, os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    temporary = ".result-" + str(os.getpid()) + "-" + str(time.monotonic_ns())
    try:
        info = os.fstat(directory)
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ContainmentFailure("diagnostic_failed")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
    finally:
        os.close(directory)


def read_report(path=REPORT_PATH, owner=0):
    """Private boot evidence for the administrator's service inventory."""
    try:
        path = Path(path)
        directory = os.open(path.parent, os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(directory)
            if info.st_uid != owner or info.st_mode & 0o077:
                return None
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
        finally:
            os.close(directory)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != owner or info.st_mode & 0o077:
                return None
            data = stream.read(MAX_REPORT_BYTES + 1)
        if len(data) > MAX_REPORT_BYTES:
            return None
        value = json.loads(data)
        if (not isinstance(value, dict) or value.get("format") != REPORT_FORMAT or value.get("ok") is not True or
                not isinstance(value.get("blocked_units"), list) or len(value["blocked_units"]) > MAX_UNITS):
            return None
        names = set()
        for unit in value["blocked_units"]:
            if (not isinstance(unit, dict) or set(unit) != {"name", "was_running", "was_enabled"} or
                    not isinstance(unit["name"], str) or not CUSTOM_UNIT.fullmatch(unit["name"]) or
                    unit["name"] in names or type(unit["was_running"]) is not bool or type(unit["was_enabled"]) is not bool):
                return None
            names.add(unit["name"])
        return value
    except (OSError, ValueError, TypeError):
        return None


def main():
    if os.geteuid() != 0 or not Path("/run/systemd/system").is_dir():
        print("Titan custom-service containment requires the system manager and root.", file=sys.stderr)
        return 1
    guard = Containment()
    try:
        result = guard.contain()
        write_report(result)
    except (ContainmentFailure, OSError) as exc:
        category = str(exc) if isinstance(exc, ContainmentFailure) else "diagnostic_failed"
        try:
            write_report(guard.result(False, category))
        except (ContainmentFailure, OSError):
            pass
        print("Titan custom-service containment failed: " + category + "; management remains unavailable.", file=sys.stderr)
        return 1
    print("Titan custom-service containment verified; legacy root units disabled: " + str(len(guard.blocked)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

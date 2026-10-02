"""Explicit administrator access to the host filesystem, separate from SMB access."""
import contextlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from .core import Error
from .files import operate, parent_fd, DirectoryRoot

SYSTEM_SHARE = "@system"
PROTECTED = {"", "etc", "usr", "var", "home", "boot", "root", "srv", "opt", "run",
             "dev", "proc", "sys", "tmp", "var/tmp", "bin", "sbin", "lib", "lib64", "lib32", "libx32"}
VIRTUAL = {"dev", "proc", "sys"}
ALLOWED = {"list": {"offset", "limit", "search"}, "read": {"offset", "size"},
           "write": {"data", "revision"}, "create": {"data"}, "upload": {"offset", "data"}, "mkdir": set(),
           "rename": {"destination"}, "delete": {"confirmation_path"},
           "copy": {"destination", "destination_share"}, "move": {"destination", "destination_share"}}


def canonical_relative(root, path, parent_only=False):
    if not isinstance(path, str) or len(path) > 4096 or "\x00" in path or ".." in Path(path).parts:
        raise Error("Ungültiger Systempfad.")
    root = Path(root).resolve(strict=True)
    candidate = root / path.lstrip("/")
    if parent_only and candidate != root:
        resolved = candidate.parent.resolve(strict=True) / candidate.name
    else:
        resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise Error("Pfad liegt außerhalb des Systemverzeichnisses.", 403)
    relative = str(resolved.relative_to(root))
    return "" if relative == "." else relative


def virtual(path):
    return bool(Path(path).parts and Path(path).parts[0] in VIRTUAL)


def mount_paths(root):
    if str(Path(root).resolve()) != "/":
        return set()  # Isolated demo/tests never consult or modify the real host tree.
    result = set()
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        fields = line.split()
        if len(fields) > 4:
            value = fields[4]
            for escaped, literal in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
                value = value.replace(escaped, literal)
            result.add(value.lstrip("/"))
    return result


def writable_path(root, path, parent_only=False):
    """Respect the actual mount, including uCore's immutable /usr deployment."""
    candidate = Path(root) / path
    if parent_only and candidate != Path(root):
        candidate = candidate.parent
    while not candidate.exists() and candidate != Path(root):
        candidate = candidate.parent
    try:
        return not bool(os.statvfs(candidate).f_flag & os.ST_RDONLY)
    except OSError:
        return False


def protect_tree(root, path):
    if path in PROTECTED or virtual(path):
        raise Error("Systemhauptverzeichnisse und virtuelle Kerneldateien können hier nicht entfernt oder verschoben werden.", 403)
    for mounted in mount_paths(root):
        if mounted == path or mounted.startswith(path + "/"):
            raise Error("Dieser Ordner ist ein Einhängepunkt oder enthält eingehängte Dateisysteme.", 403)


def operate_system(root, action, path="", system_path_root="/", destination_system=False,
                   canonicalized=False, devices=None, **arguments):
    # Browsing/editing follows ordinary Linux symlinks. New targets and removal
    # retain the leaf itself; all final operations use no-follow descriptors.
    destructive = action in ("delete", "rename", "move")
    relative = path if canonicalized else canonical_relative(system_path_root, path, parent_only=destructive or action == "create")
    if devices:
        root = DirectoryRoot(root, devices)
    if action not in ("list", "read") and virtual(relative):
        raise Error("Virtuelle Kernel- und Gerätedateien sind schreibgeschützt.", 403)
    if action == "read" and virtual(relative):
        raise Error("Virtuelle Kernel- und Gerätedateien können hier nicht geöffnet werden.", 403)
    if action not in ("list", "read", "copy") and not writable_path(system_path_root, relative, parent_only=destructive or action in ("create", "mkdir")):
        raise Error("Dieser Bereich gehört zum schreibgeschützten Titan-Systemimage. Systemsoftware wird über Image-Updates geändert; Daten und Konfigurationen in /var und /etc bleiben bearbeitbar.", 403)
    if destructive:
        protect_tree(system_path_root, relative)
    if action == "delete":
        if arguments.pop("confirmation_path", None) != "/" + relative:
            raise Error("Zum Löschen muss der vollständige angezeigte Pfad bestätigt werden.")
    if "destination" in arguments and (action == "rename" or destination_system):
        if not canonicalized:
            arguments["destination"] = canonical_relative(system_path_root, arguments["destination"], parent_only=True)
        if virtual(arguments["destination"]) or arguments["destination"] in PROTECTED:
            raise Error("Dieses Systemziel kann nicht ersetzt werden.", 403)
        if not writable_path(system_path_root, arguments["destination"], parent_only=True):
            raise Error("Das Ziel liegt im schreibgeschützten Titan-Systemimage.", 403)
    # A symlink may be removed or renamed, without touching its target.
    if destructive:
        with parent_fd(root, relative) as (directory, leaf):
            value = os.stat(leaf, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISLNK(value.st_mode):
                if action == "delete":
                    os.unlink(leaf, dir_fd=directory)
                    return {"ok": True}
                if action == "rename":
                    from .files import _rename_no_replace
                    with parent_fd(root, arguments["destination"]) as (target_fd, target_leaf):
                        _rename_no_replace(directory, leaf, target_fd, target_leaf)
                    return {"ok": True}
                raise Error("Symbolische Links können umbenannt oder gelöscht werden.")
    result = operate(root, action, relative, **({"include_trash": True} if action == "list" else {}), **arguments)
    if action == "list":
        result["path"] = relative
        mounts = mount_paths(system_path_root)
        for entry in result["entries"]:
            child = "/".join(part for part in (relative, entry["name"]) if part)
            writable = writable_path(system_path_root, child)
            entry["mutable"] = writable_path(system_path_root, child, parent_only=True) and child not in PROTECTED and child not in mounts and not virtual(child)
            entry["readable"] = not virtual(child)
            entry["editable"] = writable and not entry["directory"] and not virtual(child)
            if entry["symlink"]:
                try:
                    target = canonical_relative(system_path_root, child)
                    value = (Path(system_path_root) / target).stat()
                    entry["directory"] = stat.S_ISDIR(value.st_mode)
                    entry["readable"] = entry["directory"] or (stat.S_ISREG(value.st_mode) and not virtual(target))
                    entry["editable"] = stat.S_ISREG(value.st_mode) and not virtual(target) and writable_path(system_path_root, target)
                    entry["size"] = value.st_size
                    entry["target"] = "/" + target
                except (Error, OSError, RuntimeError):
                    entry["readable"] = entry["editable"] = False
            elif not entry["directory"]:
                try:
                    mode = (Path(system_path_root) / child).lstat().st_mode
                    entry["readable"] = entry["readable"] and stat.S_ISREG(mode)
                    entry["editable"] = entry["editable"] and stat.S_ISREG(mode)
                except FileNotFoundError:
                    entry["readable"] = entry["editable"] = False
    return result


class SystemFilesMixin:
    system_root = Path("/")

    def op_system_file(self, action, path="", **arguments):
        if action not in ALLOWED or set(arguments) - ALLOWED[action]:
            raise Error("Ungültige Systemdateiaktion oder zusätzliche Parameter.")
        relative = canonical_relative(self.system_root, path, parent_only=action in ("delete", "rename", "move", "create"))
        devices = self._system_volume_ready(relative)
        arguments = dict(arguments)
        with contextlib.ExitStack() as stack:
            root = os.open(self.system_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, root)
            descriptors = [root]
            target_system = False
            if action == "rename":
                arguments["destination"] = canonical_relative(self.system_root, arguments["destination"], parent_only=True)
                devices.update(self._system_volume_ready(arguments["destination"]))
            if action in ("copy", "move"):
                target_share = arguments.pop("destination_share", None) or SYSTEM_SHARE
                if target_share == SYSTEM_SHARE:
                    target_system = True
                    arguments["destination"] = canonical_relative(self.system_root, arguments["destination"], parent_only=True)
                    devices.update(self._system_volume_ready(arguments["destination"]))
                else:
                    target = next((item for item in self.op_shares() if item["name"] == target_share), None)
                    if not target or target.get("blocked"):
                        raise Error("Zielfreigabe ist nicht verfügbar.", 403)
                    target_fd = self.open_share_root(target["path"])
                    stack.callback(os.close, target_fd)
                    descriptors.append(target_fd)
                    arguments["destination_root"] = target_fd
            request = {"root": root, "system": True, "system_path_root": str(self.system_root),
                       "canonicalized": True, "devices": devices,
                       "destination_system": target_system, "action": action, "path": relative, **arguments}
            response = subprocess.run([sys.executable, "-m", "titan.files"], input=json.dumps(request),
                                      text=True, capture_output=True, timeout=300 if action in ("copy", "move", "delete") else 60,
                                      user=0, group=0, extra_groups=[], pass_fds=tuple(descriptors), cwd="/usr/lib/titan",
                                      env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "/usr/lib/titan"})
        try:
            value = json.loads(response.stdout)
        except ValueError:
            raise Error("Systemdateizugriff fehlgeschlagen.")
        if "error" in value:
            raise Error(value["error"], value.get("status", 400))
        return value["result"]

    def _system_volume_ready(self, path):
        candidate = self.system_root / path
        try:
            relative = candidate.relative_to(self.volume_manager.root)
        except ValueError:
            return {}
        if relative.parts:
            device = self.volume_manager.required_path(candidate)
            if device is not None:
                mountpoint = self.volume_manager.root / relative.parts[0]
                return {str(mountpoint.relative_to(self.system_root)): device}
        return {}

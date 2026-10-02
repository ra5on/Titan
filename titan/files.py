"""UID-scoped file operations; admin workers receive verified directory descriptors."""
import base64
import binascii
import contextlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import stat as statmod
import ctypes
import errno
import heapq
import hashlib
from .core import Error, integer

TEXT_LIMIT = 1024 * 1024


class DirectoryRoot:
    """Trusted worker root with expected devices for managed mount points."""
    def __init__(self, descriptor, devices):
        self.descriptor, self.devices = descriptor, devices


def safe_path(root, relative, existing=True):
    root = Path(root).resolve(strict=True)
    if not isinstance(relative, str) or "\x00" in relative:
        raise Error("Ungültiger Pfad.")
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise Error("Pfad liegt außerhalb der Freigabe.", 403)
    candidate = root / relative_path
    # Refuse symlinks, including links within the share. O_NOFOLLOW protects final opens too.
    current = root
    for component in relative_path.parts:
        current = current / component
        if current.is_symlink():
            raise Error("Symbolische Links werden nicht geöffnet.", 403)
    resolved = candidate.resolve(strict=existing)
    if not resolved.is_relative_to(root):
        raise Error("Pfad liegt außerhalb der Freigabe.", 403)
    return resolved


@contextlib.contextmanager
def parent_fd(root, relative):
    # Each ancestor is opened without following symlinks. Directory descriptors
    # remain bound even if another SMB client renames a parent concurrently.
    parts = Path(relative).parts
    if Path(relative).is_absolute() or ".." in parts or "\x00" in relative:
        raise Error("Pfad liegt außerhalb der Freigabe.", 403)
    devices = root.devices if isinstance(root, DirectoryRoot) else {}
    descriptor_root = root.descriptor if isinstance(root, DirectoryRoot) else root
    descriptors = [os.dup(descriptor_root) if type(descriptor_root) is int else os.open(descriptor_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]
    try:
        for index, part in enumerate(parts[:-1]):
            descriptors.append(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptors[-1]))
            expected = devices.get("/".join(parts[:index + 1]))
            if expected is not None and os.fstat(descriptors[-1]).st_dev != expected:
                raise Error("Volume wurde während der Dateiaktion ausgehängt.", 503)
        expected = devices.get("/".join(parts))
        if expected is not None:
            descriptors.append(os.open(parts[-1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptors[-1]))
            if os.fstat(descriptors[-1]).st_dev != expected:
                raise Error("Volume wurde während der Dateiaktion ausgehängt.", 503)
            yield descriptors[-1], "."
            return
        yield descriptors[-1], parts[-1] if parts else "."
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def operate(root, action, path="", **args):
    if action == "trash_list":
        try:
            return operate(root, "list", ".titan-trash", **args)
        except FileNotFoundError:
            return {"entries": [], "total": 0, "offset": 0,
                    "limit": integer(args.get("limit", 200), 1, 500), "has_more": False}
    if action == "restore":
        name = args["trash_name"]
        if not isinstance(name, str) or not name or "/" in name or name in (".", ".."):
            raise Error("Ungültiger Papierkorbeintrag.")
        return operate(root, "rename", ".titan-trash/" + name, destination=args["destination"])
    with parent_fd(root, path) as (directory, leaf):
        return operate_at(root, action, path, directory, leaf, **args)


def _identity(value):
    return value.st_dev, value.st_ino


def _fingerprint(value):
    return _identity(value), value.st_size, value.st_mtime_ns, value.st_ctime_ns


def revision(value):
    return hashlib.sha256(repr(_fingerprint(value)).encode()).hexdigest()


def _text_content(data):
    # Bound the encoded input before allocating the decoded payload.
    if not isinstance(data, str):
        raise Error("Ungültiger Textinhalt.")
    if len(data) > ((TEXT_LIMIT + 2) // 3) * 4:
        raise Error("Der Texteditor unterstützt Dateien bis 1 MiB.")
    try:
        content = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise Error("Ungültiger Textinhalt.")
    if len(content) > TEXT_LIMIT:
        raise Error("Der Texteditor unterstützt Dateien bis 1 MiB.")
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        raise Error("Der Texteditor unterstützt nur UTF-8-Textdateien.")
    if b"\x00" in content:
        raise Error("Binärdateien können nicht im Texteditor gespeichert werden.")
    return content


def _create_file(directory, leaf, data):
    """Create UTF-8 text exclusively in the already-open parent directory."""
    content = _text_content(data)
    try:
        output = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o660, dir_fd=directory)
    except FileExistsError:
        raise Error("Ziel existiert bereits.", 409)
    identity = _identity(os.fstat(output))
    try:
        with os.fdopen(output, "wb") as writer:
            writer.write(content)
            writer.flush()
            os.fsync(writer.fileno())
        os.fsync(directory)
    except OSError:
        # Remove only our incomplete new inode, never a concurrent replacement.
        try:
            if _identity(os.stat(leaf, dir_fd=directory, follow_symlinks=False)) == identity:
                os.unlink(leaf, dir_fd=directory)
        except OSError:
            pass
        raise


def _write_file(directory, leaf, data, expected):
    """Replace a regular text file atomically, preserving ownership and metadata."""
    if not isinstance(expected, str) or not expected:
        raise Error("Dateiversion fehlt. Datei vor dem Bearbeiten erneut öffnen.", 409)
    content = _text_content(data)
    try:
        source = os.open(leaf, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except PermissionError:
        raise Error("Keine Schreibrechte auf diese Datei.", 403)
    temporary = ".titan-edit-" + os.urandom(16).hex()
    created = False
    try:
        value = os.fstat(source)
        if not statmod.S_ISREG(value.st_mode):
            raise Error("Nur reguläre Dateien können bearbeitet werden.")
        if value.st_nlink > 1:
            raise Error("Diese Datei hat mehrere harte Links. Bitte mit einem Systemeditor bearbeiten.")
        if os.geteuid() != 0 and value.st_uid != os.geteuid():
            raise Error("Dateien anderer Benutzer können nur Administratoren bearbeiten, damit die Eigentümerschaft erhalten bleibt.", 403)
        if revision(value) != expected:
            raise Error("Datei wurde inzwischen verändert. Erneut öffnen, bevor du speicherst.", 409)
        output = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
        created = True
        with os.fdopen(output, "wb") as writer:
            writer.write(content)
            writer.flush()
            try:
                os.fchown(writer.fileno(), value.st_uid, value.st_gid)
            except PermissionError:
                raise Error("Dateieigentümer und Gruppe können nur mit Administratorrechten erhalten werden.", 403)
            os.fchmod(writer.fileno(), statmod.S_IMODE(value.st_mode))
            for name in os.listxattr(source):
                os.setxattr(writer.fileno(), name, os.getxattr(source, name))
            os.fsync(writer.fileno())
        if revision(os.fstat(source)) != expected or revision(os.stat(leaf, dir_fd=directory, follow_symlinks=False)) != expected:
            raise Error("Datei wurde während des Speicherns verändert. Erneut öffnen.", 409)
        os.replace(temporary, leaf, src_dir_fd=directory, dst_dir_fd=directory)
        created = False
        os.fsync(directory)
    finally:
        os.close(source)
        if created:
            os.unlink(temporary, dir_fd=directory)


def _inside_directory(destination_fd, source_fd):
    """Inspect descriptor ancestry, independent of concurrent path renames."""
    source = _identity(os.fstat(source_fd))
    current = os.dup(destination_fd)
    try:
        for _ in range(256):
            here = _identity(os.fstat(current))
            if here == source:
                return True
            parent = os.open("..", getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=current)
            if _identity(os.fstat(parent)) == here:
                os.close(parent)
                return False
            os.close(current)
            current = parent
        raise Error("Zielpfad ist zu tief verschachtelt.")
    finally:
        os.close(current)


def _remove_copy(directory, leaf, required_device=None):
    """Clean up an incomplete copy without following a replaced symlink."""
    value = os.stat(leaf, dir_fd=directory, follow_symlinks=False)
    if required_device is not None and value.st_dev != required_device:
        raise Error("Ein eingehängtes Dateisystem kann nicht mitgelöscht werden.", 403)
    if statmod.S_ISDIR(value.st_mode):
        fd = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            for name in os.listdir(fd):
                _remove_copy(fd, name, required_device)
        finally:
            os.close(fd)
        os.rmdir(leaf, dir_fd=directory)
    else:
        os.unlink(leaf, dir_fd=directory)


def _copy_entry(source, leaf, destination, target, records, relative="", depth=0):
    if depth > 128 or len(records) >= 200000:
        raise Error("Kopierauftrag ist zu groß oder zu tief verschachtelt.")
    fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=source)
    created = False
    try:
        before = os.fstat(fd)
        if not (statmod.S_ISREG(before.st_mode) or statmod.S_ISDIR(before.st_mode)):
            raise Error("Nur reguläre Dateien und Ordner können kopiert werden.")
        records[relative] = _fingerprint(before)
        if statmod.S_ISDIR(before.st_mode):
            os.mkdir(target, mode=0o770, dir_fd=destination)
            created = True
            output = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=destination)
            try:
                for name in os.listdir(fd):
                    if name == ".titan-trash":
                        raise Error("Ordner mit einem Papierkorb bitte ohne den Papierkorb kopieren.")
                    _copy_entry(fd, name, output, name, records,
                                relative + "/" + name, depth + 1)
            finally:
                os.close(output)
        else:
            output = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o660, dir_fd=destination)
            created = True
            try:
                with os.fdopen(os.dup(fd), "rb") as reader, os.fdopen(output, "wb") as writer:
                    shutil.copyfileobj(reader, writer, 1024 * 1024)
                    writer.flush()
                    os.fsync(writer.fileno())
            except BaseException:
                raise
        after = os.fstat(fd)
        if _fingerprint(before) != _fingerprint(after):
            raise Error("Die Quelle wurde während des Kopierens verändert. Bitte erneut versuchen.", 409)
        current = os.stat(leaf, dir_fd=source, follow_symlinks=False)
        if _identity(current) != _identity(before):
            raise Error("Die Quelle wurde während des Kopierens ersetzt.", 409)
    except BaseException:
        if created:
            with contextlib.suppress(OSError):
                _remove_copy(destination, target)
        raise
    finally:
        os.close(fd)


def _remove_source(directory, leaf, records, relative=""):
    value = os.stat(leaf, dir_fd=directory, follow_symlinks=False)
    if _fingerprint(value) != records.get(relative):
        raise Error("Die Quelle wurde verändert. Die Kopie bleibt am Ziel erhalten.", 409)
    if statmod.S_ISDIR(value.st_mode):
        fd = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            names = os.listdir(fd)
            if any(relative + "/" + name not in records for name in names):
                raise Error("Die Quelle enthält neue Dateien. Die Kopie bleibt am Ziel erhalten.", 409)
            for name in names:
                _remove_source(fd, name, records, relative + "/" + name)
        finally:
            os.close(fd)
        os.rmdir(leaf, dir_fd=directory)
    else:
        os.unlink(leaf, dir_fd=directory)


def _rename_no_replace(source, leaf, destination, target):
    """Linux's atomic no-overwrite rename also protects against an SMB race."""
    function = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if function is None:
        raise Error("Sicheres Verschieben wird auf diesem System nicht unterstützt.")
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(source, os.fsencode(leaf), destination, os.fsencode(target), 1) != 0:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise Error("Ziel existiert bereits.", 409)
        raise OSError(code, os.strerror(code))


def operate_at(root, action, path, directory, leaf, **args):
    try:
        if statmod.S_ISLNK(os.stat(leaf, dir_fd=directory, follow_symlinks=False).st_mode):
            raise Error("Symbolische Links werden nicht geöffnet.", 403)
    except FileNotFoundError:
        if action not in ("mkdir", "upload", "create"):
            raise
    if action == "list":
        offset = integer(args.get("offset", 0), 0, 2**31 - 1)
        limit = integer(args.get("limit", 200), 1, 500)
        search = args.get("search", "")
        if not isinstance(search, str) or len(search) > 200 or "\x00" in search:
            raise Error("Ungültiger Suchbegriff.")
        search = search.casefold()
        total = 0
        fd = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            def entries():
                nonlocal total
                with os.scandir(fd) as iterator:
                    for entry in iterator:
                        if (entry.name == ".titan-trash" and not args.get("include_trash")) or search not in entry.name.casefold():
                            continue
                        try:
                            value = entry.stat(follow_symlinks=False)
                        except FileNotFoundError:
                            continue
                        total += 1
                        yield {"name": entry.name, "directory": statmod.S_ISDIR(value.st_mode),
                               "symlink": statmod.S_ISLNK(value.st_mode), "size": value.st_size,
                               "modified": value.st_mtime}
            # Bound retained entries; the whole directory is scanned so pagination
            # never silently loses files beyond the former 2,000-entry cutoff.
            result = heapq.nsmallest(offset + limit, entries(),
                                     key=lambda item: (not item["directory"], item["name"].casefold(), item["name"]))
        finally:
            os.close(fd)
        return {"entries": result[offset:offset + limit], "path": path, "total": total,
                "offset": offset, "limit": limit, "has_more": offset + limit < total}
    if action == "read":
        offset = integer(args.get("offset", 0), 0, 2**63 - 1)
        size = integer(args.get("size", 1024 * 1024), 1, 4 * 1024 * 1024)
        fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            if not statmod.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise Error("Nur reguläre Dateien können geöffnet werden.")
            before = os.fstat(stream.fileno())
            total = before.st_size
            stream.seek(offset)
            data = stream.read(size)
            if _fingerprint(before) != _fingerprint(os.fstat(stream.fileno())):
                raise Error("Datei wurde während des Lesens verändert. Bitte erneut öffnen.", 409)
        return {"data": base64.b64encode(data).decode(), "total": total, "name": leaf,
                "revision": revision(before)}
    if leaf == ".":
        raise Error("Die Freigabe selbst kann nicht geändert werden.")
    if action == "create":
        _create_file(directory, leaf, args.get("data", ""))
    elif action == "write":
        _write_file(directory, leaf, args.get("data", ""), args.get("revision"))
    elif action == "delete":
        _remove_copy(directory, leaf, os.fstat(directory).st_dev)
    elif action == "mkdir":
        os.mkdir(leaf, mode=0o770, dir_fd=directory)
    elif action == "upload":
        offset = integer(args.get("offset", 0), 0, 2**63 - 1)
        data = base64.b64decode(args.get("data", ""), validate=True)
        if len(data) > 4 * 1024 * 1024:
            raise Error("Upload-Block zu groß.")
        # New files only; later chunks require the expected offset.
        flags = os.O_WRONLY | os.O_NOFOLLOW | (os.O_CREAT | os.O_EXCL if offset == 0 else 0)
        fd = os.open(leaf, flags | os.O_NONBLOCK, 0o660, dir_fd=directory)
        with os.fdopen(fd, "wb") as stream:
            if not statmod.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise Error("Upload-Ziel ist keine reguläre Datei.")
            if os.fstat(stream.fileno()).st_size != offset:
                raise Error("Upload-Position stimmt nicht mit der Datei überein.", 409)
            stream.seek(offset)
            stream.write(data)
        return {"offset": offset + len(data)}
    elif action in ("copy", "move"):
        destination_root = args.get("destination_root", root)
        with parent_fd(destination_root, args["destination"]) as (destination_fd, destination_leaf):
            if destination_leaf == ".":
                raise Error("Die Zielfreigabe selbst kann nicht ersetzt werden.")
            source = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                source_mode = os.fstat(source).st_mode
                if not (statmod.S_ISDIR(source_mode) or statmod.S_ISREG(source_mode)):
                    raise Error("Nur reguläre Dateien und Ordner können kopiert oder verschoben werden.")
                if statmod.S_ISDIR(source_mode) and _inside_directory(destination_fd, source):
                    raise Error("Ein Ordner kann nicht in sich selbst kopiert oder verschoben werden.")
            finally:
                os.close(source)
            if action == "move":
                try:
                    _rename_no_replace(directory, leaf, destination_fd, destination_leaf)
                    return {"ok": True}
                except OSError as exc:
                    if exc.errno != errno.EXDEV:
                        raise
            records = {}
            _copy_entry(directory, leaf, destination_fd, destination_leaf, records)
            if action == "move":
                _remove_source(directory, leaf, records)
    elif action == "rename":
        with parent_fd(root, args["destination"]) as (destination_fd, destination_leaf):
            try:
                os.stat(destination_leaf, dir_fd=destination_fd, follow_symlinks=False)
                raise Error("Ziel existiert bereits.", 409)
            except FileNotFoundError:
                pass
            _rename_no_replace(directory, leaf, destination_fd, destination_leaf)
    elif action == "trash":
        if path.startswith(".titan-trash/"):
            raise Error("Eintrag liegt bereits im Papierkorb.")
        try:
            operate(root, "mkdir", ".titan-trash")
        except FileExistsError:
            pass
        name = str(time.time_ns()) + "-" + leaf
        with parent_fd(root, ".titan-trash/" + name) as (trash_fd, trash_leaf):
            os.rename(leaf, trash_leaf, src_dir_fd=directory, dst_dir_fd=trash_fd)
        return {"trash_name": name, "original": path}
    else:
        raise Error("Unbekannte Dateiaktion.")
    return {"ok": True}


def worker():
    try:
        request = json.load(sys.stdin)
        destination_devices = request.pop("destination_devices", None)
        if destination_devices:
            request["destination_root"] = DirectoryRoot(request["destination_root"], destination_devices)
        if request.pop("system", False):
            from .system_files import operate_system
            result = operate_system(**request)
        else:
            result = operate(**request)
        print(json.dumps({"result": result}))
    except Exception as exc:
        print(json.dumps({"error": str(exc), "status": getattr(exc, "status", 400)}))


if __name__ == "__main__":
    worker()

"""Bounded, descriptor-based searches under an already authorized file root."""
import heapq
import os
from pathlib import PurePosixPath
import stat
import time

from .core import Error, integer

OPTIONS = {"recursive", "type", "min_size", "max_size", "modified_after", "modified_before"}
EXTENSIONS = {
    "image": {"png", "jpg", "jpeg", "gif", "webp", "svg", "heic", "avif"},
    "document": {"txt", "md", "pdf", "doc", "docx", "odt", "xls", "xlsx", "ods", "ppt", "pptx", "odp", "csv", "rtf"},
    "media": {"mp4", "webm", "mkv", "avi", "mp3", "wav", "ogg", "flac", "m4a", "mov"},
    "archive": {"zip", "tar", "gz", "xz", "7z", "rar", "iso"},
}


def filters(arguments):
    recursive = arguments.get("recursive", False)
    if not isinstance(recursive, bool):
        raise Error("Unterordnersuche muss ein Schalter sein.")
    kind = arguments.get("type", "")
    if kind not in {"", "file", "folder", *EXTENSIONS}:
        raise Error("Ungültiger Dateitypfilter.")
    result = {"recursive": recursive, "type": kind}
    for key in OPTIONS - {"recursive", "type"}:
        value = arguments.get(key)
        result[key] = None if value in (None, "") else integer(value, 0, 2**63 - 1)
    for lower, upper in (("min_size", "max_size"), ("modified_after", "modified_before")):
        if result[lower] is not None and result[upper] is not None and result[lower] > result[upper]:
            raise Error("Der Anfang des Filterbereichs muss vor seinem Ende liegen.")
    return result


def matches(name, value, options, search):
    if search not in name.casefold():
        return False
    directory = stat.S_ISDIR(value.st_mode)
    kind = options["type"]
    if (kind == "folder" and not directory) or (kind == "file" and not stat.S_ISREG(value.st_mode)):
        return False
    if kind in EXTENSIONS and (directory or name.rsplit(".", 1)[-1].lower() not in EXTENSIONS[kind]):
        return False
    for lower, upper, measured in (("min_size", "max_size", value.st_size),
                                  ("modified_after", "modified_before", value.st_mtime)):
        if options[lower] is not None and measured < options[lower]:
            return False
        if options[upper] is not None and measured > options[upper]:
            return False
    return True


def list_directory(fd, path, arguments, *, devices=None, max_entries=50000, seconds=5):
    """Never follow links or silently report a bounded search as complete.

    Workers run with the caller's UID. An unlisted mount is not traversed;
    managed mounts are traversed only when their verified device still matches.
    """
    options = filters(arguments)
    offset = integer(arguments.get("offset", 0), 0, 2**31 - 1)
    limit = integer(arguments.get("limit", 200), 1, 500)
    search = arguments.get("search", "")
    if not isinstance(search, str) or len(search) > 200 or "\x00" in search:
        raise Error("Ungültiger Suchbegriff.")
    search = search.casefold()
    devices = devices or {}
    scanned = total = skipped = 0
    truncated = False
    deadline = time.monotonic() + seconds

    def walk(directory, relative, depth=0):
        nonlocal scanned, total, skipped, truncated
        with os.scandir(directory) as iterator:
            for entry in iterator:
                if scanned >= max_entries or time.monotonic() >= deadline:
                    truncated = True
                    return
                if entry.name.startswith(".titan-uploads-") or entry.name == ".titan-trash" and not arguments.get("include_trash"):
                    continue
                scanned += 1
                child = str(PurePosixPath(relative) / entry.name)
                try:
                    value = entry.stat(follow_symlinks=False)
                except OSError:
                    skipped += 1
                    continue
                is_directory = stat.S_ISDIR(value.st_mode)
                if matches(entry.name, value, options, search):
                    total += 1
                    yield {"name": entry.name, "path": child, "directory": is_directory,
                           "symlink": stat.S_ISLNK(value.st_mode), "size": value.st_size,
                           "modified": value.st_mtime}
                if not options["recursive"] or not is_directory:
                    continue
                if depth >= 63 or child.split("/", 1)[0] in {"proc", "sys", "dev"} and arguments.get("include_trash"):
                    skipped += 1
                    continue
                expected_device = devices.get(child, os.fstat(directory).st_dev)
                if value.st_dev != expected_device:
                    skipped += 1
                    continue
                try:
                    child_fd = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                except OSError:
                    skipped += 1
                    continue
                try:
                    actual = os.fstat(child_fd)
                    if (actual.st_dev, actual.st_ino) != (value.st_dev, value.st_ino):
                        skipped += 1
                        continue
                    yield from walk(child_fd, child, depth + 1)
                finally:
                    os.close(child_fd)
                if truncated:
                    return

    result = heapq.nsmallest(offset + limit, walk(fd, path),
                            key=lambda item: (not item["directory"], item["path"].casefold(), item["path"]))
    return {"entries": result[offset:offset + limit], "path": path, "total": total,
            "offset": offset, "limit": limit, "has_more": offset + limit < total,
            "recursive": options["recursive"], "scanned": scanned, "skipped": skipped,
            "truncated": truncated,
            "warning": "Suche begrenzt. Wähle einen kleineren Ordner oder genauere Filter." if truncated else
                       "Einige geschützte Ordner oder nicht freigegebene Einhängepunkte wurden übersprungen." if skipped else ""}

"""External, explicitly selected backups. This module never mounts or formats disks.

Every archive is self-contained, hashed and extracted manually into a new directory.
Paths and symlinks are checked using directory descriptors rather than tar.extractall.
"""
import contextlib
import datetime
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import sqlite3
import stat
import tarfile
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import pwd

from .core import Error, identifier, integer, atomic_json, configuration_lock


DEFAULTS = {"target": "", "auto_backup": False, "interval": "daily", "window_day": 6,
            "window_hour": 3, "retention": 7, "shares": [], "include_config": True}
BACKUP_ID = re.compile(r"b-[0-9]{8}T[0-9]{6}-[a-f0-9]{12}")
MAX_ENTRIES = 1000000
MAX_BYTES = 100 * 1024 ** 4
MAX_CONFIG = 16 * 1024 ** 2
EXTERNAL_ROOTS = tuple(Path(value) for value in ("/var/mnt", "/var/media", "/mnt", "/media"))


def external_path(value):
    """Accept CoreOS's fixed /mnt and /media aliases, never arbitrary symlinks.

    The resulting path is still opened component by component with NOFOLLOW.
    In particular, do not resolve user-created links beneath an external disk.
    """
    if not isinstance(value, (str, Path)) or not str(value) or len(str(value)) > 4096 or '\x00' in str(value):
        raise Error("Ungültiger absoluter Backupzielpfad.")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise Error("Ungültiger absoluter Backupzielpfad.")
    for alias, canonical in ((Path("/mnt"), Path("/var/mnt")), (Path("/media"), Path("/var/media"))):
        if path.is_relative_to(alias) and alias.is_symlink():
            try:
                link = os.readlink(alias)
            except OSError as exc:
                raise Error("Backupziel wurde während der Pfadprüfung verändert.") from exc
            destination = Path(os.path.normpath(str(alias.parent / link)))
            if destination != canonical:
                raise Error("Backupziel enthält einen unerwarteten Systemlink.")
            path = canonical / path.relative_to(alias)
    return path


@contextlib.contextmanager
def directory_fd(path):
    """Open every path component without following any symlinks."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise Error("Ungültiger absoluter Verzeichnispfad.")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:]:
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = following
        yield fd
    except OSError as exc:
        raise Error("Verzeichnis fehlt oder enthält einen symbolischen Link.") from exc
    finally:
        os.close(fd)


def digest_file(path):
    with directory_fd(Path(path).parent) as parent:
        fd = os.open(Path(path).name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise Error("Backup muss eine reguläre Datei sein.")
            digest = hashlib.sha256()
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
            return digest.hexdigest()


def archive_name(value):
    if not isinstance(value, str) or len(value) > 4096 or "\\" in value or "\x00" in value:
        raise Error("Ungültiger Archivpfad.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise Error("Archiv enthält unsichere Pfade.")
    return path.parts


def fd_json(parent, name, value):
    """Atomic JSON write that never creates a pathname on a fallback filesystem."""
    temporary = name + "." + secrets.token_hex(6)
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass


class Backups:
    def __init__(self, host, run, web_db="/var/lib/titan/titan.sqlite3"):
        self.host, self.run, self.web_db = host, run, Path(web_db)
        self.lock = threading.RLock()

    @contextlib.contextmanager
    def _data_fd(self, path):
        """Pin managed data to its mounted UUID before root reads or writes."""
        expected = self.host.volume_manager.required_path(path)
        with directory_fd(path) as fd:
            if expected is not None and os.fstat(fd).st_dev != expected:
                raise Error("Datenvolume wurde während der Backupaktion ausgehängt.", 503)
            yield fd

    def state(self):
        value = self.host.load("backup-state", {})
        if not re.fullmatch(r"[a-f0-9]{32}", str(value.get("namespace", ""))):
            value = {"namespace": secrets.token_hex(16)}
            self.host.save("backup-state", value)
        return value

    def settings(self):
        return {**DEFAULTS, **self.host.load("backup-settings", {})}

    def validate_settings(self, value):
        if not isinstance(value, dict) or set(value) - set(DEFAULTS):
            raise Error("Unbekannte Backup-Einstellung.")
        result = {**self.settings(), **value}
        for key in ("auto_backup", "include_config"):
            if not isinstance(result[key], bool):
                raise Error("Ungültiger Backup-Schalter.")
        if result["interval"] not in ("daily", "weekly"):
            raise Error("Backupintervall muss täglich oder wöchentlich sein.")
        result["window_day"] = integer(result["window_day"], 0, 6)
        result["window_hour"] = integer(result["window_hour"], 0, 23)
        result["retention"] = integer(result["retention"], 1, 365)
        result["shares"] = self.selected_shares(result["shares"])
        if not result["shares"] and not result["include_config"]:
            raise Error("Mindestens eine Freigabe oder die Konfiguration auswählen.")
        if not isinstance(result["target"], str):
            raise Error("Ungültiges Backupziel.")
        if result["target"]:
            result["target"] = str(self.validate_target(result["target"]))
        elif result["auto_backup"]:
            raise Error("Für automatische Backups zuerst ein eingehängtes externes Ziel auswählen.")
        return result

    def save_settings(self, value):
        with self.lock:
            result = self.validate_settings(value)
            self.host.save("backup-settings", result)
            return result

    def selected_shares(self, names):
        if not isinstance(names, list) or len(names) > 1000 or any(not isinstance(name, str) for name in names) or len(set(names)) != len(names):
            raise Error("Ungültige Freigabenauswahl.")
        known = {item["name"] for item in self.host.op_shares()}
        for name in names:
            identifier(name)
            if name not in known:
                raise Error("Freigabe nicht gefunden: " + name, 404)
        return sorted(names)

    def validate_target(self, target):
        path = external_path(target)
        if not any(path.is_relative_to(root) for root in EXTERNAL_ROOTS):
            raise Error("Ein separat eingehängtes externes Backupziel auswählen.")
        with directory_fd(path) as fd:
            target_info = os.fstat(fd)
        mounted = json.loads(self.run(["findmnt", "--json", "--target", str(path), "--output", "TARGET,SOURCE,FSTYPE,MAJ:MIN,OPTIONS"]))
        root = json.loads(self.run(["findmnt", "--json", "--target", "/", "--output", "TARGET,SOURCE,FSTYPE,MAJ:MIN"]))
        try:
            selected, system = mounted["filesystems"][0], root["filesystems"][0]
            mountpoint = external_path(selected["target"])
            if (not path.is_relative_to(mountpoint) or mountpoint == Path("/") or
                    not any(mountpoint.is_relative_to(base) for base in EXTERNAL_ROOTS) or
                    selected.get("maj:min") == system.get("maj:min") or
                    selected.get("source") == system.get("source") or target_info.st_dev == os.stat("/").st_dev or
                    selected.get("fstype") in ("tmpfs", "overlay", "proc", "sysfs", "devtmpfs") or
                    "ro" in selected.get("options", "").split(",")):
                raise Error("Backupziel muss ein beschreibbares, separat eingehängtes Dateisystem sein; die Systemplatte ist nicht zulässig.")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise Error("Backupziel ist nicht sicher eingehängt.") from exc
        for source in [self.host.share_root, self.host.directory, self.host.vm_root]:
            source = Path(source).absolute()
            if path.is_relative_to(source) or source.is_relative_to(path):
                raise Error("Backupziel darf sich nicht mit den gesicherten Daten überschneiden.")
        for item in self.host.op_shares():
            source = Path(item["path"]).absolute()
            if path.is_relative_to(source) or source.is_relative_to(path):
                raise Error("Backupziel darf keine Quelle enthalten und nicht in einer Freigabe liegen.")
        self._target_identity = (target_info.st_dev, target_info.st_ino)
        return path

    def namespace(self, create=False):
        target = self.validate_target(self.settings()["target"])
        namespace = self.state()["namespace"]
        destination = target / ".titan-backups" / namespace
        with directory_fd(target) as rootfd:
            opened = os.fstat(rootfd)
            if (opened.st_dev, opened.st_ino) != self._target_identity:
                raise Error("Backupziel wurde während der Zielprüfung ausgehängt oder ersetzt.")
            fd = os.dup(rootfd)
            try:
                for component in (".titan-backups", namespace):
                    if create:
                        try:
                            os.mkdir(component, 0o700, dir_fd=fd)
                        except FileExistsError:
                            pass
                    try:
                        following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    except FileNotFoundError:
                        if not create:
                            return destination
                        raise
                    os.close(fd)
                    fd = following
                    info = os.fstat(fd)
                    if info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_dev != self._target_identity[0]:
                        raise Error("Titan-Backupbereich muss dem Verwaltungsdienst gehören und private Unix-Dateirechte unterstützen.")
                expected = {"schema": 1, "namespace": namespace}
                try:
                    markerfd = os.open("owner.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                except FileNotFoundError:
                    if not create:
                        raise Error("Ungültiger Titan-Backupbereich.")
                    fd_json(fd, "owner.json", expected)
                    markerfd = os.open("owner.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                with os.fdopen(markerfd, "r") as stream:
                    markerinfo = os.fstat(stream.fileno())
                    if not stat.S_ISREG(markerinfo.st_mode) or markerinfo.st_size > 1024 or json.load(stream) != expected:
                        raise Error("Backupbereich gehört nicht zu dieser Titan-Installation.")
            finally:
                os.close(fd)
        return destination

    def _target_fd(self, fd):
        if os.fstat(fd).st_dev != self._target_identity[0]:
            raise Error("Backupziel wurde ausgehängt oder durch ein anderes Dateisystem ersetzt.")

    def _last(self, ok, error=None, backup=None):
        state = self.state()
        state["last"] = {"time": time.time(), "ok": ok}
        if error:
            state["last"]["error"] = str(error)[:1000]
        if backup:
            state["last"]["backup"] = backup
        self.host.save("backup-state", state)

    def list(self):
        if not self.settings()["target"]:
            return []
        base = self.namespace()
        if not base.exists():
            return []
        result = []
        with directory_fd(base) as fd:
            self._target_fd(fd)
            for name in os.listdir(fd):
                if BACKUP_ID.fullmatch(name):
                    try:
                        result.append(self.manifest(name, base))
                    except (Error, OSError, ValueError):
                        # Unrecognized/incomplete entries are never eligible for retention.
                        continue
        return sorted(result, key=lambda item: item["created"], reverse=True)

    def manifest(self, backup, base=None):
        if not isinstance(backup, str) or not BACKUP_ID.fullmatch(backup):
            raise Error("Ungültige Backup-ID.")
        base = base or self.namespace()
        path = base / backup
        with directory_fd(path) as fd:
            self._target_fd(fd)
            filefd = os.open("manifest.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            with os.fdopen(filefd, "r") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise Error("Ungültiges Backupmanifest.")
                text = stream.read(MAX_CONFIG + 1)
                if len(text) > MAX_CONFIG:
                    raise Error("Backupmanifest ist zu groß.")
                value = json.loads(text)
            archive = os.stat("archive.tar.gz", dir_fd=fd, follow_symlinks=False)
        if not isinstance(value, dict):
            raise Error("Ungültiges Backupmanifest.")
        if (value.get("schema") != 1 or value.get("id") != backup or value.get("namespace") != self.state()["namespace"] or
                value.get("type") not in ("shares", "vm") or not stat.S_ISREG(archive.st_mode) or
                not re.fullmatch(r"[a-f0-9]{64}", str(value.get("sha256", ""))) or
                not isinstance(value.get("created"), (int, float)) or not math.isfinite(value["created"]) or value["created"] < 0 or
                type(value.get("entries")) is not int or not 0 < value["entries"] <= MAX_ENTRIES or
                type(value.get("unpacked_bytes")) is not int or not 0 <= value["unpacked_bytes"] <= MAX_BYTES or
                value.get("bytes") != archive.st_size or not isinstance(value.get("shares"), list) or
                type(value.get("include_config")) is not bool):
            raise Error("Backupmanifest ist ungültig oder unvollständig.")
        for name in value["shares"]:
            identifier(name)
        if len(set(value["shares"])) != len(value["shares"]):
            raise Error("Backupmanifest enthält doppelte Freigaben.")
        if value["type"] == "vm":
            identifier(value.get("vm_name"))
        return value

    def _config(self, directory):
        # Web account changes stage SQL, mutate Samba through RPC, then commit.
        # Acquire their cross-process lock before the agent's account lock so a
        # snapshot cannot capture an old web hash alongside new SMB credentials.
        coordination = configuration_lock(self.web_db.parent) if self.web_db.exists() else contextlib.nullcontext()
        with coordination, self.host.account_lock:
            self._config_snapshot(directory)

    def _config_snapshot(self, directory):
        directory.mkdir(mode=0o700)
        data = {"schema": 1, "users": [], "config": {}, "agent": {}, "samba": []}
        if self.web_db.exists():
            with directory_fd(self.web_db.parent):
                if self.web_db.is_symlink():
                    raise Error("Konfigurationsdatenbank darf kein symbolischer Link sein.")
            with contextlib.closing(sqlite3.connect(self.web_db.as_uri() + "?mode=ro", uri=True)) as source:
                with contextlib.closing(sqlite3.connect(directory / "titan.sqlite3")) as destination:
                    source.backup(destination)
                    destination.execute("DELETE FROM sessions")
                    destination.execute("DELETE FROM jobs")
                    destination.row_factory = sqlite3.Row
                    data["users"] = [dict(row) for row in destination.execute("SELECT * FROM users")]
                    data["config"] = {row[0]: json.loads(row[1]) for row in destination.execute("SELECT key,value FROM config")
                                      if row[0] in ("settings",)}
                    destination.commit()
            os.chmod(directory / "titan.sqlite3", 0o600)
        for key in ("accounts", "shares", "apps"):
            data["agent"][key] = self.host.load(key, [])
        for account in data["agent"]["accounts"]:
            if not account.get("removed"):
                try:
                    # The root-owned archive contains hashes, never plaintext
                    # passwords. Do not expose command output through API errors.
                    data["samba"].append(self.host.samba_snapshot(account["name"]).strip())
                except Exception:
                    raise Error("SMB-Zugangsdaten konnten nicht gesichert werden.") from None
        atomic_json(directory / "config.json", data)

    def _add_tree(self, archive, source, prefix, totals):
        with self._data_fd(source) as rootfd:
            def recurse(fd, name):
                info = os.fstat(fd)
                node = tarfile.TarInfo(name)
                node.type, node.mode, node.mtime = tarfile.DIRTYPE, 0o770, int(info.st_mtime)
                archive.addfile(node)
                totals[0] += 1
                for entry in sorted(os.listdir(fd)):
                    archive_name(entry)
                    child = os.stat(entry, dir_fd=fd, follow_symlinks=False)
                    if stat.S_ISDIR(child.st_mode):
                        childfd = os.open(entry, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                        try:
                            recurse(childfd, name + "/" + entry)
                        finally:
                            os.close(childfd)
                    elif stat.S_ISREG(child.st_mode):
                        childfd = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                        with os.fdopen(childfd, "rb") as stream:
                            before = os.fstat(stream.fileno())
                            if not stat.S_ISREG(before.st_mode):
                                raise Error("Quelle wurde während des Backups verändert.")
                            item = tarfile.TarInfo(name + "/" + entry)
                            item.size, item.mode, item.mtime = before.st_size, 0o660, int(before.st_mtime)
                            archive.addfile(item, stream)
                            after = os.fstat(stream.fileno())
                            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                                raise Error("Eine Quelldatei wurde während des Backups geändert; Backup erneut starten.")
                            totals[0] += 1
                            totals[1] += before.st_size
                    else:
                        raise Error("Quelle enthält Links oder Spezialdateien; diese werden aus Sicherheitsgründen nicht gesichert.")
                    if totals[0] > MAX_ENTRIES or totals[1] > MAX_BYTES:
                        raise Error("Backup überschreitet die Sicherheitsgrenzen.")
            recurse(rootfd, prefix)

    def create(self, shares=None, include_config=None):
        with self.lock:
            settings = self.settings()
            shares = self.selected_shares(settings["shares"] if shares is None else shares)
            include_config = settings["include_config"] if include_config is None else include_config
            if not isinstance(include_config, bool) or (not shares and not include_config):
                raise Error("Freigaben oder Konfiguration auswählen.")
            records = {item["name"]: item for item in self.host.op_shares()}
            def write(archive, totals, temporary):
                for name in shares:
                    source = Path(records[name]["path"])
                    if not source.is_relative_to(self.host.share_root):
                        raise Error("Freigabe liegt außerhalb des verwalteten Datenbereichs.")
                    self._add_tree(archive, source, "shares/" + name, totals)
                if include_config:
                    self._config(temporary / "config")
                    self._add_tree(archive, temporary / "config", "config", totals)
            return self._create("shares", {"shares": shares, "include_config": include_config}, write)

    def _create(self, kind, details, write):
        destination = None
        try:
            base = self.namespace(create=True)
            backup = "b-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(6)
            destination = base / backup
            with directory_fd(base) as fd:
                self._target_fd(fd)
                os.mkdir(backup, 0o700, dir_fd=fd)
            totals = [0, 0]
            with tempfile.TemporaryDirectory(prefix="backup-", dir=self.host.directory) as temporary:
                with directory_fd(destination) as fd:
                    self._target_fd(fd)
                    outputfd = os.open("archive.tar.gz", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                    with os.fdopen(outputfd, "wb") as stream:
                        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
                            write(archive, totals, Path(temporary))
                        stream.flush()
                        os.fsync(stream.fileno())
            # Fail closed if the target was unmounted during the copy.
            self.namespace()
            manifest = {"schema": 1, "namespace": self.state()["namespace"], "id": backup,
                        "created": time.time(), "type": kind, "entries": totals[0], "unpacked_bytes": totals[1],
                        "bytes": (destination / "archive.tar.gz").stat().st_size,
                        "sha256": digest_file(destination / "archive.tar.gz"), **details}
            with directory_fd(destination) as fd:
                self._target_fd(fd)
                fd_json(fd, "manifest.json", manifest)
            self.verify(backup)
            self._last(True, backup=backup)
            self.retention()
            return manifest
        except Exception as exc:
            self._last(False, exc)
            if destination:
                self._remove(destination, complete=False)
            if isinstance(exc, Error):
                raise
            raise Error("Backup fehlgeschlagen: " + str(exc)) from exc

    def _members(self, archive, manifest):
        seen, required_directories, size = {}, set(), 0
        for member in archive:
            parts = archive_name(member.name)
            ancestors = ["/".join(parts[:index]) for index in range(1, len(parts))]
            if (member.name in seen or any(seen.get(parent) == "file" for parent in ancestors) or
                    (member.isfile() and member.name in required_directories) or
                    not (member.isfile() or member.isdir()) or (member.isdir() and member.size != 0) or member.sparse or
                    member.size < 0 or member.size > MAX_BYTES or
                    (manifest["type"] == "shares" and not ((parts[0] == "shares" and len(parts) >= 2 and parts[1] in manifest["shares"]) or
                     (parts[0] == "config" and manifest.get("include_config") and
                      (parts == ("config",) or parts in (("config", "config.json"), ("config", "titan.sqlite3")))))) or
                    (manifest["type"] == "vm" and parts not in (("vm",), ("vm", "domain.xml"), ("vm", "disk.qcow2"), ("vm", "nvram.fd")))):
                raise Error("Archiv enthält unerwartete Pfade, Links oder Spezialdateien.")
            seen[member.name] = "file" if member.isfile() else "directory"
            required_directories.update(ancestors)
            size += member.size
            if len(seen) > MAX_ENTRIES or size > MAX_BYTES or size > manifest["unpacked_bytes"]:
                raise Error("Archiv überschreitet die angegebenen Sicherheitsgrenzen.")
            yield member, parts
        if len(seen) != manifest["entries"] or size != manifest["unpacked_bytes"]:
            raise Error("Archiv stimmt nicht mit dem Manifest überein.")

    @contextlib.contextmanager
    def _archive(self, backup):
        manifest = self.manifest(backup)
        path = self.namespace() / backup / "archive.tar.gz"
        with directory_fd(path.parent) as fd:
            self._target_fd(fd)
            archivefd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            with os.fdopen(archivefd, "rb") as stream:
                digest = hashlib.sha256()
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                if digest.hexdigest() != manifest["sha256"]:
                    raise Error("Backup-Prüfsumme stimmt nicht; Wiederherstellung verweigert.")
                stream.seek(0)
                with tarfile.open(fileobj=stream, mode="r:gz") as archive:
                    yield manifest, archive

    def verify(self, backup):
        with self.lock:
            try:
                with self._archive(backup) as (manifest, archive):
                    for member, _ in self._members(archive, manifest):
                        if member.isfile():
                            stream = archive.extractfile(member)
                            while stream.read(1024 * 1024):
                                pass
                return {"ok": True, "backup": backup, "files": manifest["entries"], "bytes": manifest["unpacked_bytes"]}
            except (tarfile.TarError, OSError, EOFError) as exc:
                raise Error("Backup ist beschädigt oder unvollständig.") from exc

    def _extract(self, backup, destination, predicate, trim=0):
        self.verify(backup)
        with self._data_fd(destination) as rootfd:
            with self._archive(backup) as (manifest, archive):
                for member, parts in self._members(archive, manifest):
                    if not predicate(parts):
                        continue
                    relative = parts[trim:]
                    if not relative:
                        continue
                    parent = os.dup(rootfd)
                    try:
                        for component in relative[:-1]:
                            try:
                                os.mkdir(component, 0o770, dir_fd=parent)
                            except FileExistsError:
                                pass
                            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                            os.close(parent)
                            parent = following
                        if member.isdir():
                            try:
                                os.mkdir(relative[-1], 0o770, dir_fd=parent)
                            except FileExistsError:
                                existing = os.stat(relative[-1], dir_fd=parent, follow_symlinks=False)
                                if not stat.S_ISDIR(existing.st_mode):
                                    raise Error("Ziel enthält einen unerwarteten Pfad.")
                        else:
                            fd = os.open(relative[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o660, dir_fd=parent)
                            with os.fdopen(fd, "wb") as stream:
                                shutil.copyfileobj(archive.extractfile(member), stream, 1024 * 1024)
                                stream.flush()
                                os.fsync(stream.fileno())
                    finally:
                        os.close(parent)

    def restore(self, backup, share, name):
        with self.lock:
            manifest = self.manifest(backup)
            if manifest["type"] != "shares" or not manifest["shares"]:
                raise Error("Dieses Backup enthält keine Freigabedaten.")
            identifier(share)
            identifier(name)
            record = next((item for item in self.host.op_shares() if item["name"] == share), None)
            if not record:
                raise Error("Zielfreigabe nicht gefunden.", 404)
            if record.get("blocked"):
                raise Error("Die Zielfreigabe ist gesperrt; zuerst den Freigabefehler beheben.", 409)
            self.verify(backup)
            root = Path(record["path"])
            if not root.is_relative_to(self.host.share_root):
                raise Error("Zielfreigabe liegt außerhalb des Datenbereichs.")
            with self._data_fd(root) as fd:
                try:
                    # Keep SMB clients out while files are being extracted.
                    os.mkdir(name, 0o700, dir_fd=fd)
                except FileExistsError:
                    raise Error("Wiederherstellungsordner existiert bereits; vorhandene Daten werden nicht überschrieben.", 409)
            self._extract(backup, root / name, lambda parts: parts[0] == "shares", trim=1)
            self.host.share_acl_transaction({**record, "path": str(root / name)}, record["readers"], record["writers"], lambda: None)
            return {"ok": True, "path": str(root / name), "shares": manifest["shares"],
                    "message": "Daten in neuem Ordner wiederhergestellt; vorhandene Dateien wurden nicht ersetzt."}

    def read_config(self, backup):
        with self.lock:
            manifest = self.manifest(backup)
            if manifest["type"] != "shares" or not manifest.get("include_config"):
                raise Error("Backup enthält keine NAS-Konfiguration.")
            self.verify(backup)
            with self._archive(backup) as (manifest, archive):
                member = archive.getmember("config/config.json")
                if not member.isfile() or member.size > MAX_CONFIG:
                    raise Error("Konfigurationsexport ist ungültig oder zu groß.")
                data = json.load(archive.extractfile(member))
            if not isinstance(data, dict) or data.get("schema") != 1 or set(data) != {"schema", "users", "config", "agent", "samba"}:
                raise Error("Unbekanntes Konfigurationsformat.")
            if not isinstance(data["users"], list) or not isinstance(data["config"], dict) or set(data["config"]) - {"settings"}:
                raise Error("Ungültige Benutzer- oder Systemeinstellungen.")
            names = set()
            for user in data["users"]:
                if not isinstance(user, dict) or set(user) - {"name", "password", "role", "system_user", "enabled"}:
                    raise Error("Ungültiger Benutzer im Konfigurationsexport.")
                identifier(user["name"])
                identifier(user["system_user"])
                if user["name"] in names or user["role"] not in ("admin", "user") or not re.fullmatch(r"[a-f0-9]{32}:[a-f0-9]{128}", str(user["password"])) or user.get("enabled", 1) not in (0, 1):
                    raise Error("Ungültiger Benutzer im Konfigurationsexport.")
                names.add(user["name"])
            if not any(user["role"] == "admin" and user.get("enabled", 1) for user in data["users"]):
                raise Error("Konfiguration muss einen aktiven Administrator enthalten.")
            if not isinstance(data["agent"], dict) or set(data["agent"]) != {"accounts", "shares", "apps"} or any(not isinstance(value, list) for value in data["agent"].values()):
                raise Error("Ungültige Hostkonfiguration.")
            if not isinstance(data["samba"], list) or any(not isinstance(row, str) for row in data["samba"]):
                raise Error("Ungültige SMB-Sicherung.")
            return data

    def restore_config(self, backup, confirmation):
        """Schedule a fixed, root-owned helper so the HTTP reply can finish first."""
        with self.lock:
            if confirmation != backup:
                raise Error("Zur Bestätigung die vollständige Backup-ID eingeben.")
            from .config_restore import validate_config
            data = self.read_config(backup)
            validate_config(self.host, data)
            tickets = self.host.directory / "restore-tickets"
            tickets.mkdir(mode=0o700, exist_ok=True)
            ticket = secrets.token_hex(16)
            path = tickets / (ticket + ".json")
            atomic_json(path, {"schema": 1, "data": data, "created": time.time()})
            marker = self.host.directory / "config-restore.lock"
            try:
                fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "w") as stream:
                    stream.write(ticket)
                self.run(["systemd-run", "--unit=titan-config-restore-" + ticket, "--on-active=3s",
                          "--property=WorkingDirectory=/usr/lib/titan", "/usr/bin/python3", "-m", "titan.config_restore",
                          "--ticket", ticket])
            except Exception:
                path.unlink(missing_ok=True)
                if marker.exists() and marker.read_text() == ticket:
                    marker.unlink(missing_ok=True)
                raise Error("Konfigurationswiederherstellung konnte nicht gestartet werden.") from None
            return {"ok": True, "scheduled": True, "message": "Konfiguration wird auf diesem Host wiederhergestellt. Weboberfläche und SMB werden kurz angehalten; danach mit dem gesicherten Passwort neu anmelden."}

    def export_config(self, backup):
        self.read_config(backup)
        self.host.directory.mkdir(exist_ok=True)
        destination = self.host.directory / ("config-export-" + secrets.token_hex(6))
        destination.mkdir(mode=0o700)
        self._extract(backup, destination, lambda parts: parts[0] == "config", trim=1)
        for file in destination.iterdir():
            file.chmod(0o600)
        return {"ok": True, "path": str(destination), "message": "Geprüfter Export mit Benutzerpassworthashes; Ordner vertraulich behandeln. Sitzungen und laufende Aufträge sind ausgeschlossen."}

    def _remove(self, directory, complete=True):
        try:
            with directory_fd(directory) as fd:
                self._target_fd(fd)
                entries = os.listdir(fd)
                if set(entries) - {"manifest.json", "archive.tar.gz"}:
                    return False
                for name in entries:
                    if not stat.S_ISREG(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode):
                        return False
                for name in entries:
                    os.unlink(name, dir_fd=fd)
            with directory_fd(directory.parent) as fd:
                os.rmdir(directory.name, dir_fd=fd)
            return True
        except (OSError, Error):
            return False

    def retention(self):
        # Independently retain VM backups for each VM, and share backups as a group.
        groups = {}
        for item in self.list():
            key = (item["type"], item.get("vm_name", ""))
            groups.setdefault(key, []).append(item)
        for items in groups.values():
            for item in items[self.settings()["retention"]:]:
                try:
                    self.verify(item["id"])
                except (Error, OSError, ValueError):
                    continue
                self._remove(self.namespace() / item["id"])

    def due(self, now=None):
        settings = self.settings()
        now = datetime.datetime.fromtimestamp(time.time() if now is None else now)
        if not settings["auto_backup"] or now.hour < settings["window_hour"]:
            return False
        if settings["interval"] == "weekly" and now.weekday() != settings["window_day"]:
            return False
        return self.state().get("scheduled_day") != now.strftime("%Y-%m-%d")

    def scheduled(self, now=None):
        with self.lock:
            if not self.due(now):
                return {"due": False}
            state = self.state()
            state["scheduled_day"] = datetime.datetime.fromtimestamp(time.time() if now is None else now).strftime("%Y-%m-%d")
            self.host.save("backup-state", state)
            try:
                return {"due": True, "backup": self.create()}
            except Error as exc:
                return {"due": True, "error": str(exc)}

    def create_vm(self, name, xml, disk):
        """Caller must verify that the managed VM is shut off before invocation."""
        with self.lock:
            identifier(name)
            disk = Path(disk)
            if not isinstance(xml, str) or len(xml) > MAX_CONFIG:
                raise Error("Ungültige verwaltete VM-Dateien.")
            location = self.host.validate_vm_disk_path(name, disk)
            with directory_fd(disk.parent) as parent:
                if os.fstat(parent).st_dev != location["device"]:
                    raise Error("VM-Speicher wurde während der Sicherung ausgehängt.", 503)
                if disk.is_symlink() or not disk.is_file():
                    raise Error("VM-Disk muss eine reguläre Datei sein.")
            image = json.loads(self.run(["qemu-img", "info", "--output=json", str(disk)]))
            if not self.standalone_image(image):
                raise Error("Nur eigenständige qcow2-Disks ohne Backing-Datei können gesichert werden.")
            def write(archive, totals, temporary):
                vm = temporary / "vm"
                vm.mkdir(mode=0o700)
                (vm / "domain.xml").write_text(xml)
                node = ET.fromstring(xml).find('./os/nvram')
                if node is not None:
                    nvram = self.host.vm_nvram_path(name)
                    if node.text != str(nvram): raise Error('UEFI-Speicherpfad ist nicht verwaltet.')
                    if os.path.lexists(nvram):
                        fd = os.open(nvram, os.O_RDONLY | os.O_NOFOLLOW)
                        with os.fdopen(fd, 'rb') as stream:
                            info = os.fstat(stream.fileno())
                            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 16*1024**2: raise Error('UEFI-Speicher ist ungültig.')
                            (vm / 'nvram.fd').write_bytes(stream.read(16*1024**2+1))
                self._add_tree(archive, vm, "vm", totals)
                self.host.validate_vm_disk_path(name, disk)
                with directory_fd(disk.parent) as fd:
                    if os.fstat(fd).st_dev != location["device"]:
                        raise Error("VM-Speicher wurde während der Sicherung ausgehängt.", 503)
                    sourcefd = os.open(disk.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                    with os.fdopen(sourcefd, "rb") as stream:
                        before = os.fstat(stream.fileno())
                        if not stat.S_ISREG(before.st_mode) or before.st_dev != location["device"]:
                            raise Error("VM-Disk besitzt eine unerwartete Speicherkennung.", 409)
                        node = tarfile.TarInfo("vm/disk.qcow2")
                        node.size, node.mode = before.st_size, 0o660
                        archive.addfile(node, stream)
                        after = os.fstat(stream.fileno())
                        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                            raise Error("VM-Disk wurde während des Backups verändert.")
                        totals[0] += 1
                        totals[1] += before.st_size
            return self._create("vm", {"shares": [], "include_config": False, "vm_name": name}, write)

    def verified_vm(self, backup):
        manifest = self.manifest(backup)
        if manifest["type"] != "vm":
            raise Error("Dieses Backup enthält keine VM.")
        self.verify(backup)
        with self._archive(backup) as (_, archive):
            xml = archive.getmember("vm/domain.xml")
            if not xml.isfile() or xml.size > MAX_CONFIG:
                raise Error("Ungültige VM-Definition im Backup.")
            return {**manifest, "xml": archive.extractfile(xml).read().decode("utf-8")}

    def restore_vm_nvram(self, backup, name):
        self.verified_vm(backup)
        with self._archive(backup) as (_, archive):
            try: member = archive.getmember('vm/nvram.fd')
            except KeyError: return
            if not member.isfile() or not 0 < member.size <= 16*1024**2: raise Error('Ungültiger UEFI-Speicher im Backup.')
            destination = self.host.vm_nvram_path(name)
            from .platforms import current
            owner = pwd.getpwnam(current().qemu_user)
            destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                shutil.copyfileobj(archive.extractfile(member), stream)
                os.fchown(stream.fileno(), owner.pw_uid, owner.pw_gid)
                stream.flush()
                os.fsync(stream.fileno())
            return True

    def restore_vm_files(self, backup, name):
        """Return a new image; caller creates a sanitized, new libvirt definition."""
        with self.lock:
            identifier(name)
            self.verified_vm(backup)
            self.host.vm_root.mkdir(parents=True, exist_ok=True, mode=0o755)
            target = self.host.vm_root / (name + ".qcow2")
            with tempfile.TemporaryDirectory(prefix="vm-restore-", dir=self.host.directory) as temporary:
                self._extract(backup, Path(temporary), lambda parts: parts == ("vm", "disk.qcow2"), trim=1)
                source = Path(temporary) / "disk.qcow2"
                image = json.loads(self.run(["qemu-img", "info", "--output=json", str(source)]))
                if not self.standalone_image(image):
                    raise Error("Backup enthält keine eigenständige qcow2-Disk.")
                with directory_fd(self.host.vm_root) as fd:
                    try:
                        targetfd = os.open(target.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o660, dir_fd=fd)
                    except FileExistsError:
                        raise Error("VM-Disk existiert bereits; vorhandene Disk wird nicht ersetzt.", 409)
                    try:
                        with source.open("rb") as src, os.fdopen(targetfd, "wb") as dst:
                            shutil.copyfileobj(src, dst, 1024 * 1024)
                            dst.flush()
                            os.fsync(dst.fileno())
                    except Exception:
                        os.unlink(target.name, dir_fd=fd)
                        raise
            return str(target)

    @staticmethod
    def standalone_image(image):
        def external(value):
            if isinstance(value, dict):
                return any((key in ("backing-filename", "full-backing-filename", "data-file") and bool(item)) or external(item)
                           for key, item in value.items())
            if isinstance(value, list):
                return any(external(item) for item in value)
            return False
        return isinstance(image, dict) and image.get("format") == "qcow2" and not external(image)

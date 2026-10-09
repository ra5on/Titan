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

from .core import valid_password_hash, Error, identifier, integer, atomic_json, configuration_lock, user_profile_text


DEFAULTS = {"target": "", "auto_backup": False, "interval": "daily", "window_day": 6,
            "window_hour": 3, "retention": 7, "shares": [], "include_config": True,
            "apps": [], "app_data": []}
BACKUP_ID = re.compile(r"b-[0-9]{8}T[0-9]{6}-[a-f0-9]{12}")
MAX_ENTRIES = 1000000
MAX_BYTES = 100 * 1024 ** 4
MAX_CONFIG = 16 * 1024 ** 2
EXTERNAL_ROOTS = tuple(Path(value) for value in ("/var/mnt", "/var/media", "/mnt", "/media"))


def external_path(value):
    """Accept the fixed legacy /mnt and /media aliases, never arbitrary symlinks.

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
        self.running = False

    @contextlib.contextmanager
    def _data_fd(self, path):
        """Pin managed data to its mounted UUID before root reads or writes."""
        expected = self.host.storage_locations.required_path(path) if Path(path).is_relative_to(self.host.share_root) and hasattr(self.host, 'storage_locations') else self.host.volume_manager.required_path(path)
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

    @property
    def apps(self):
        from .app_backups import AppBackups
        return AppBackups(self)

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
        result["apps"], result["app_data"] = self.apps.selected(result["apps"], result["app_data"])
        if not result["shares"] and not result["include_config"] and not result["apps"]:
            raise Error("Mindestens eine Freigabe, App oder die Konfiguration auswählen.")
        if not isinstance(result["target"], str):
            raise Error("Ungültiges Backupziel.")
        if result["target"]:
            result["target"] = str(self.validate_target(result["target"], create=True))
        elif result["auto_backup"]:
            raise Error("Für automatische Backups zuerst ein eingehängtes externes Ziel auswählen.")
        return result

    def save_settings(self, value):
        with self.lock:
            previous = self.settings()
            result = self.validate_settings(value)
            self.host.save("backup-settings", result)
            from .backup_freshness import activate
            activate(self.host, result, force=not previous["auto_backup"])
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

    def validate_target(self, target, create=False):
        path = external_path(target)
        if path.is_relative_to(self.host.share_root) and hasattr(self.host, "storage_locations"):
            resource = self.host.storage_locations.validate_path(path, purpose="backups", write=True)
            if resource["id"] == "system":
                raise Error("Für Sicherungen einen separaten Speicherbereich wählen. Der interne Datenspeicher ist kein unabhängiges Sicherungsziel.")
            base = Path(self.host.storage_locations.resolve(resource["id"], purpose="backups", write=True)["path"])
            if not path.is_relative_to(base):
                raise Error("Sicherungen gehören in den Backupordner des ausgewählten Speichers.")
            if self.host.storage_locations.backup_pool_conflict(resource):
                raise Error("Dieser ZFS-Pool enthält Quelldaten in einem seiner Datasets. Für ein unabhängiges Backup einen anderen Pool oder ein anderes Volume wählen.")
            if create and path == base:
                with self.host.storage_locations.fd(resource["id"], purpose="backups", create=True, write=True):
                    pass
            with directory_fd(path) as fd:
                target_info = os.fstat(fd)
                if target_info.st_dev != resource["device"]:
                    raise Error("Der Sicherungsspeicher wurde ausgehängt.", 503)
            # A backup on the same filesystem cannot survive that disk/pool's
            # loss. Test sources, not their shared namespace ancestor.
            sources = [self.host.directory, self.host.vm_root]
            sources += [Path(item["path"]) for item in self.host.op_shares()]
            sources += [Path(item["data"]) for item in self.host.load("apps", []) if item.get("data")]
            sources += [Path(item["config_path"]) for item in self.host.load("apps", []) if item.get("config_path")]
            for source in sources:
                source = Path(source).absolute()
                if path.is_relative_to(source) or source.is_relative_to(path):
                    raise Error("Sicherungsziel und Quelldaten überschneiden sich.")
                if source.exists() and source.stat().st_dev == target_info.st_dev:
                    raise Error("Dieser Speicher enthält Quelldaten. Für ein unabhängiges Backup einen anderen Pool oder ein anderes Volume wählen.")
            self._target_identity = (target_info.st_dev, target_info.st_ino)
            return path
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
        if selected.get("fstype") == "zfs":
            # Different datasets in one pool have different st_dev values.
            # Confirm the mounted dataset and compare its pool GUID with all
            # sources before treating an external mount as independent.
            try:
                source = selected["source"]
                if (not isinstance(source, str) or len(source) > 1024 or
                        not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:-]*(?:/[A-Za-z0-9_][A-Za-z0-9_.:-]*)*", source)):
                    raise ValueError("invalid ZFS dataset identity")
                major, minor = map(int, selected["maj:min"].split(":"))
                if os.makedev(major, minor) != target_info.st_dev:
                    raise ValueError("dataset device changed")
                properties = dict(line.split("\t", 1) for line in self.run(
                    ["zfs", "get", "-H", "-o", "property,value", "mountpoint,mounted", source]).splitlines())
                if properties != {"mountpoint": str(mountpoint), "mounted": "yes"}:
                    raise ValueError("dataset mount properties changed")
                pool = source.split("/", 1)[0]
                guid = self.run(["zpool", "get", "-H", "-o", "value", "guid", pool]).strip()
                if not re.fullmatch(r"[0-9]{1,20}", guid) or int(guid) == 0:
                    raise ValueError("invalid ZFS pool GUID")
                pool_record = {"id": "pool:" + pool, "kind": "pool", "uuid": "zfs:" + guid}
                # Check overlap before resolving sources, including legacy app
                # paths, so a configured external target cannot recurse through
                # its own storage registration during the pool check.
                for source_path in self.host.storage_locations.backup_sources():
                    source_path = Path(source_path).absolute()
                    if path.is_relative_to(source_path) or source_path.is_relative_to(path):
                        raise Error("Sicherungsziel und Quelldaten überschneiden sich.")
                if self.host.storage_locations.backup_pool_conflict(pool_record):
                    raise Error("Dieser ZFS-Pool enthält Quelldaten in einem seiner Datasets. Für ein unabhängiges Backup einen anderen Pool oder ein anderes Volume wählen.")
            except (AttributeError, OSError, ValueError, KeyError, TypeError) as exc:
                raise Error("Das externe ZFS-Sicherungsziel hat keine bestätigte Dataset- und Pool-Kennung; einen sicher eingehängten separaten Pool wählen.", 503) from exc
        for source in [self.host.share_root, self.host.directory, self.host.vm_root]:
            source = Path(source).absolute()
            if path.is_relative_to(source) or source.is_relative_to(path):
                raise Error("Backupziel darf sich nicht mit den gesicherten Daten überschneiden.")
        for item in self.host.op_shares():
            source = Path(item["path"]).absolute()
            if path.is_relative_to(source) or source.is_relative_to(path):
                raise Error("Backupziel darf keine Quelle enthalten und nicht in einer Freigabe liegen.")
        installed = self.host.load("apps", [])
        for item in installed if isinstance(installed, list) else []:
            for key in ("data", "config_path"):
                if item.get(key):
                    source = Path(item[key]).absolute()
                    if path.is_relative_to(source) or source.is_relative_to(path) or source.exists() and source.stat().st_dev == target_info.st_dev:
                        raise Error("Das Sicherungsziel enthält App-Quelldaten. Einen getrennten Datenträger wählen.")
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
        if ok:
            state["last_success"] = dict(state["last"])
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
                value.get("type") not in ("shares", "vm", "bundle") or not stat.S_ISREG(archive.st_mode) or
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
        if value["type"] == "bundle":
            self.apps.validate_manifest(value)
        elif value.get("apps") or value.get("app_data"):
            raise Error("App-Sicherung benötigt ein vollständiges Paketmanifest.")
        if value["type"] == "vm":
            identifier(value.get("vm_name"))
            if "vm_disks" in value:
                disks = value["vm_disks"]
                if not isinstance(disks, list) or not 1 <= len(disks) <= 8:
                    raise Error("Ungültige VM-Laufwerksliste im Backupmanifest.")
                targets = set()
                for index, disk in enumerate(disks):
                    expected = "vm/disk.qcow2" if index == 0 else "vm/disk-" + str(index) + ".qcow2"
                    if not isinstance(disk, dict) or set(disk) != {"archive", "target", "virtual_size"} or disk["archive"] != expected or not isinstance(disk["target"], str) or not re.fullmatch(r"vd[a-z]", disk["target"]) or index == 0 and disk["target"] != "vda" or disk["target"] in targets or type(disk["virtual_size"]) is not int or not 0 < disk["virtual_size"] <= MAX_BYTES:
                        raise Error("VM-Laufwerksmetadaten im Backupmanifest sind ungültig.")
                    targets.add(disk["target"])
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
                                      if row[0] in ("settings", "identity", "login_protection")}
                    tables = {row[0] for row in destination.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    for temporary_table in ("login_protection_failures", "login_protection_blocks"):
                        if temporary_table in tables:
                            destination.execute("DELETE FROM " + temporary_table)
                    if "second_factors" in tables and "recovery_codes" in tables:
                        data["security"] = {"factors": [dict(row) for row in destination.execute(
                            "SELECT username,secret,enabled,last_counter FROM second_factors")],
                            "recoveries": [dict(row) for row in destination.execute("SELECT username,digest FROM recovery_codes")]}
                    destination.commit()
            os.chmod(directory / "titan.sqlite3", 0o600)
        for key in ("accounts", "shares", "apps"):
            data["agent"][key] = self.host.load(key, [])
        root_policy = self.host.load("identity", None)
        web_policy = data["config"].get("identity")
        if root_policy is not None or web_policy is not None:
            from .identity import empty_policy
            # The SQL snapshot is canonical; root may also include internal
            # Linux identity mappings that must be regenerated on restore.
            policy = web_policy if web_policy is not None else empty_policy()
            data["identity"] = {"policy": policy, "baseline": self.host.load("identity-baseline", {}),
                                "homes": self.host.load("identity-homes", {}), "quotas": self.host.load("identity-quotas", {})}
        for account in data["agent"]["accounts"]:
            if not account.get("removed"):
                try:
                    # The root-owned archive contains hashes, never plaintext
                    # passwords. Do not expose command output through API errors.
                    data["samba"].append(self.host.samba_snapshot(account["name"]).strip())
                except Exception:
                    raise Error("SMB-Zugangsdaten konnten nicht gesichert werden.") from None
        atomic_json(directory / "config.json", data)

    def _add_tree(self, archive, source, prefix, totals, preserve=False, allow_links=False):
        nodes, links = {}, {}
        with self._data_fd(source) as rootfd:
            def recurse(fd, name):
                info = os.fstat(fd)
                node = tarfile.TarInfo(name)
                node.type, node.mode, node.mtime = tarfile.DIRTYPE, 0o770, int(info.st_mtime)
                if preserve:
                    node.mode, node.uid, node.gid = stat.S_IMODE(info.st_mode) & 0o777, info.st_uid, info.st_gid
                archive.addfile(node)
                nodes[archive_name(name)] = "directory"
                totals[0] += 1
                for entry in sorted(os.listdir(fd)):
                    if entry.startswith('.titan-uploads-'):
                        continue
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
                            if preserve:
                                item.mode, item.uid, item.gid = stat.S_IMODE(before.st_mode) & 0o777, before.st_uid, before.st_gid
                            archive.addfile(item, stream)
                            nodes[archive_name(item.name)] = "file"
                            after = os.fstat(stream.fileno())
                            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                                raise Error("Eine Quelldatei wurde während des Backups geändert; Backup erneut starten.")
                            totals[0] += 1
                            totals[1] += before.st_size
                    elif allow_links and preserve and stat.S_ISLNK(child.st_mode):
                        # Read the link itself, never its target. Validation uses
                        # only the complete snapshot graph after traversal.
                        target = os.readlink(entry, dir_fd=fd)
                        after = os.stat(entry, dir_fd=fd, follow_symlinks=False)
                        if (child.st_dev, child.st_ino, child.st_mode, child.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_mode, after.st_ctime_ns):
                            raise Error("Ein App-Link wurde während der Sicherung verändert.")
                        item = tarfile.TarInfo(name + "/" + entry)
                        item.type, item.linkname, item.mode = tarfile.SYMTYPE, target, 0o777
                        item.uid, item.gid, item.mtime = child.st_uid, child.st_gid, int(child.st_mtime)
                        archive.addfile(item)
                        parts = archive_name(item.name)
                        nodes[parts], links[parts] = "link", target
                        totals[0] += 1
                    else:
                        # Archive-relative paths aid diagnosis without exposing
                        # host paths, file contents or link targets.
                        raise Error("Quelle enthält einen gesperrten Link oder eine Spezialdatei. Archivpfad: " + json.dumps(name + "/" + entry, ensure_ascii=False))
                    if totals[0] > MAX_ENTRIES or totals[1] > MAX_BYTES:
                        raise Error("Backup überschreitet die Sicherheitsgrenzen.")
            recurse(rootfd, prefix)
        if links:
            self.apps.validate_links(nodes, links)

    def create(self, shares=None, include_config=None, apps=None, app_data=None):
        with self.lock:
            settings = self.settings()
            use_defaults = shares is None and include_config is None and apps is None and app_data is None
            apps, app_data = self.apps.selected(settings["apps"] if use_defaults else [] if apps is None else apps,
                                                settings["app_data"] if use_defaults else [] if app_data is None else app_data)
            shares = self.selected_shares(settings["shares"] if shares is None else shares)
            include_config = settings["include_config"] if include_config is None else include_config
            if not isinstance(include_config, bool) or (not shares and not include_config and not apps):
                raise Error("Freigaben, Apps oder Konfiguration auswählen.")
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
                self.apps.write(archive, totals, temporary, prepared, app_data)
            with self.apps.quiesce(apps) as prepared:
                details = {"shares": shares, "include_config": include_config}
                if apps:
                    details.update(apps=apps, app_data=app_data)
                return self._create("bundle" if apps else "shares", details, write)

    def _create(self, kind, details, write):
        destination = None
        self.running = True
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
            # Retention is part of creating a usable backup. If it fails, the
            # exception path removes this archive, so it must not count as a
            # successful copy or satisfy the automatic plan's deadline.
            self.retention()
            self._last(True, backup=backup)
            from .backup_freshness import completed
            completed(self.host, self.settings(), kind, details)
            return manifest
        except Exception as exc:
            self._last(False, exc)
            if destination:
                self._remove(destination, complete=False)
            if isinstance(exc, Error):
                raise
            raise Error("Backup fehlgeschlagen: " + str(exc)) from exc
        finally:
            self.running = False

    def _members(self, archive, manifest):
        seen, nodes, links, required_directories, size = {}, {}, {}, set(), 0
        vm_members = {("vm",), ("vm", "domain.xml"), ("vm", "disk.qcow2"), ("vm", "nvram.fd")}
        if manifest["type"] == "vm":
            vm_members.update(tuple(disk["archive"].split("/")) for disk in manifest.get("vm_disks", []))
        for member in archive:
            parts = archive_name(member.name)
            ancestors = ["/".join(parts[:index]) for index in range(1, len(parts))]
            app_link = (member.issym() and manifest["type"] == "bundle" and len(parts) >= 4 and
                        parts[0] == "apps" and parts[2] in ("config", "data"))
            if (member.name in seen or any(seen.get(parent) in ("file", "link") for parent in ancestors) or
                    (not member.isdir() and member.name in required_directories) or
                    not (member.isfile() or member.isdir() or app_link) or (not member.isfile() and member.size != 0) or member.sparse or
                    member.size < 0 or member.size > MAX_BYTES or
                    (manifest["type"] in ("shares", "bundle") and not ((parts[0] == "shares" and len(parts) >= 2 and parts[1] in manifest["shares"]) or
                     (parts[0] == "config" and manifest.get("include_config") and
                      (parts == ("config",) or parts in (("config", "config.json"), ("config", "titan.sqlite3")))) or
                     (manifest["type"] == "bundle" and self.apps.allowed_member(parts, manifest)))) or
                    (manifest["type"] == "bundle" and (type(member.uid) is not int or type(member.gid) is not int or
                     not 0 <= member.uid < 2**32 - 1 or not 0 <= member.gid < 2**32 - 1 or member.mode & ~0o777)) or
                    (manifest["type"] == "vm" and parts not in vm_members)):
                raise Error("Archiv enthält unerwartete Pfade, Links oder Spezialdateien.")
            kind = "file" if member.isfile() else "link" if app_link else "directory"
            seen[member.name], nodes[parts] = kind, kind
            if app_link:
                links[parts] = member.linkname
            required_directories.update(ancestors)
            size += member.size
            if len(seen) > MAX_ENTRIES or size > MAX_BYTES or size > manifest["unpacked_bytes"]:
                raise Error("Archiv überschreitet die angegebenen Sicherheitsgrenzen.")
            yield member, parts
        if len(seen) != manifest["entries"] or size != manifest["unpacked_bytes"]:
            raise Error("Archiv stimmt nicht mit dem Manifest überein.")
        if links:
            self.apps.validate_links(nodes, links)
        if manifest["type"] == "bundle":
            for app in manifest["apps"]:
                prefix = "apps/" + app
                if (seen.get(prefix) != "directory" or seen.get(prefix + "/app.json") != "file" or
                        seen.get(prefix + "/config") != "directory" or
                        app in manifest["app_data"] and seen.get(prefix + "/data") != "directory"):
                    raise Error("App-Sicherung ist unvollständig; Konfiguration oder Nutzdaten fehlen.")

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

    def _extract(self, backup, destination, predicate, trim=0, preserve=False):
        self.verify(backup)
        with self._data_fd(destination) as rootfd:
            directories, links = [], []
            with self._archive(backup) as (manifest, archive):
                for member, parts in self._members(archive, manifest):
                    if not predicate(parts):
                        continue
                    relative = parts[trim:]
                    if not relative:
                        if preserve and member.isdir():
                            directories.append((relative, member.uid, member.gid, member.mode))
                        continue
                    if member.issym():
                        if not preserve:
                            raise Error("App-Links benötigen eine Wiederherstellung mit erhaltenen Rechten.")
                        links.append((relative, member.linkname, member.uid, member.gid))
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
                            if preserve:
                                directories.append((relative, member.uid, member.gid, member.mode))
                        else:
                            fd = os.open(relative[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o660, dir_fd=parent)
                            with os.fdopen(fd, "wb") as stream:
                                shutil.copyfileobj(archive.extractfile(member), stream, 1024 * 1024)
                                stream.flush()
                                os.fsync(stream.fileno())
                                if preserve:
                                    os.fchown(stream.fileno(), member.uid, member.gid)
                                    os.fchmod(stream.fileno(), member.mode)
                    finally:
                        os.close(parent)
            # The complete graph has now been validated. Links are leaves and
            # appear only after ordinary entries; never traverse one on write.
            for relative, target, uid, gid in links:
                parent = os.dup(rootfd)
                try:
                    for component in relative[:-1]:
                        following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                        os.close(parent)
                        parent = following
                    os.symlink(target, relative[-1], dir_fd=parent)
                    os.chown(relative[-1], uid, gid, dir_fd=parent, follow_symlinks=False)
                finally:
                    os.close(parent)
            for relative, uid, gid, mode in sorted(directories, key=lambda value: len(value[0]), reverse=True):
                child = os.dup(rootfd)
                try:
                    for component in relative:
                        following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=child)
                        os.close(child)
                        child = following
                    os.fchown(child, uid, gid)
                    os.fchmod(child, mode)
                finally:
                    os.close(child)

    def browse(self, backup, path="", offset=0, limit=200):
        """List user files only; configuration hashes are never exposed here."""
        with self.lock:
            offset, limit = integer(offset, 0, MAX_ENTRIES), integer(limit, 1, 500)
            prefix = archive_name(path) if path else ()
            with self._archive(backup) as (manifest, archive):
                if manifest["type"] not in ("shares", "bundle"):
                    raise Error("Die Dateiansicht ist für Freigabensicherungen verfügbar.")
                entries, found = {}, not prefix
                for member, parts in self._members(archive, manifest):
                    if parts[0] != "shares":
                        continue
                    relative = parts[1:]
                    if relative == prefix:
                        found = member.isdir()
                    if len(relative) <= len(prefix) or relative[:len(prefix)] != prefix:
                        continue
                    child = relative[len(prefix)]
                    direct = len(relative) == len(prefix) + 1
                    candidate = {"name": child, "path": "/".join((*prefix, child)),
                                 "type": "directory" if not direct or member.isdir() else "file",
                                 "size": member.size if direct and member.isfile() else None,
                                 "modified": member.mtime if direct else None}
                    if direct or child not in entries:
                        entries[child] = candidate
                if not found:
                    raise Error("Sicherungsordner nicht gefunden.", 404)
                ordered = sorted(entries.values(), key=lambda item: (item["type"] != "directory", item["name"].casefold()))
                return {"backup": backup, "path": path, "items": ordered[offset:offset + limit],
                        "total": len(ordered), "offset": offset, "limit": limit,
                        "created": manifest["created"], "verified": True}

    def restore_selection(self, backup, paths, share, name):
        """Restore selected files/subtrees to a NEW folder with target share ACLs."""
        with self.lock:
            if (not isinstance(paths, list) or not 1 <= len(paths) <= 1000 or
                    any(not isinstance(path, str) for path in paths) or len(set(paths)) != len(paths)):
                raise Error("Zwischen einer und 1000 unterschiedliche Dateien oder Ordner auswählen.")
            selected = [archive_name(path) for path in paths]
            manifest = self.manifest(backup)
            if manifest["type"] not in ("shares", "bundle") or any(parts[0] not in manifest["shares"] for parts in selected):
                raise Error("Nur gesicherte Freigabedaten können wiederhergestellt werden.")
            identifier(share)
            identifier(name)
            record = next((item for item in self.host.op_shares() if item["name"] == share), None)
            if not record:
                raise Error("Zielfreigabe nicht gefunden.", 404)
            if record.get("blocked"):
                raise Error("Die Zielfreigabe ist gesperrt; zuerst den Freigabefehler beheben.", 409)
            # Validate the complete archive and all selections BEFORE creating
            # any destination. A partial/malicious index must leave no output.
            present = set()
            with self._archive(backup) as (checked, archive):
                for member, parts in self._members(archive, checked):
                    if parts[0] == "shares":
                        present.add(parts[1:])
            if any(parts not in present for parts in selected):
                raise Error("Mindestens eine ausgewählte Datei fehlt in der Sicherung.", 404)
            self.verify(backup)
            root = Path(record["path"])
            if not root.is_relative_to(self.host.share_root):
                raise Error("Zielfreigabe liegt außerhalb des Datenbereichs.")
            with self._data_fd(root) as fd:
                try:
                    os.mkdir(name, 0o700, dir_fd=fd)
                except FileExistsError:
                    raise Error("Wiederherstellungsordner existiert bereits; vorhandene Daten werden nicht überschrieben.", 409)
            destination = root / name
            predicate = lambda parts: parts[0] == "shares" and any(
                parts[1:1 + len(selection)] == selection for selection in selected)
            try:
                self._extract(backup, destination, predicate, trim=1)
                self.host.share_acl_transaction({**record, "path": str(destination)},
                                                record["readers"], record["writers"], lambda: None)
            except Exception:
                # An incomplete restore is kept private for administrator
                # inspection; do not expose it through inherited Samba ACLs.
                with self._data_fd(destination) as fd:
                    os.fchmod(fd, 0o700)
                raise
            return {"ok": True, "path": str(destination), "selected": paths,
                    "message": "Auswahl in einem neuen Ordner wiederhergestellt. Vorhandene Dateien bleiben erhalten."}

    def restore(self, backup, share, name):
        with self.lock:
            manifest = self.manifest(backup)
            if manifest["type"] not in ("shares", "bundle") or not manifest["shares"]:
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
            if manifest["type"] not in ("shares", "bundle") or not manifest.get("include_config"):
                raise Error("Backup enthält keine NAS-Konfiguration.")
            self.verify(backup)
            with self._archive(backup) as (manifest, archive):
                member = archive.getmember("config/config.json")
                if not member.isfile() or member.size > MAX_CONFIG:
                    raise Error("Konfigurationsexport ist ungültig oder zu groß.")
                data = json.load(archive.extractfile(member))
            if not isinstance(data, dict) or data.get("schema") != 1 or (not {"schema", "users", "config", "agent", "samba"}.issubset(data) or set(data) - {"schema", "users", "config", "agent", "samba", "identity", "security"}):
                raise Error("Unbekanntes Konfigurationsformat.")
            if not isinstance(data["users"], list) or not isinstance(data["config"], dict) or set(data["config"]) - {"settings", "identity", "login_protection"}:
                raise Error("Ungültige Benutzer- oder Systemeinstellungen.")
            if "login_protection" in data["config"]:
                from .login_protection import validate_settings
                validate_settings(data["config"]["login_protection"])
            names = set()
            for user in data["users"]:
                if not isinstance(user, dict) or set(user) - {"name", "password", "role", "system_user", "enabled", "display_name", "description"}:
                    raise Error("Ungültiger Benutzer im Konfigurationsexport.")
                identifier(user["name"])
                identifier(user["system_user"])
                if user["name"] in names or user["role"] not in ("admin", "user") or not valid_password_hash(user["password"]) or user.get("enabled", 1) not in (0, 1):
                    raise Error("Ungültiger Benutzer im Konfigurationsexport.")
                for field in ("display_name", "description"):
                    if field in user:
                        user_profile_text(user[field], field)
                names.add(user["name"])
            if not any(user["role"] == "admin" and user.get("enabled", 1) for user in data["users"]):
                raise Error("Konfiguration muss einen aktiven Administrator enthalten.")
            if not isinstance(data["agent"], dict) or set(data["agent"]) != {"accounts", "shares", "apps"} or any(not isinstance(value, list) for value in data["agent"].values()):
                raise Error("Ungültige Hostkonfiguration.")
            if not isinstance(data["samba"], list) or any(not isinstance(row, str) for row in data["samba"]):
                raise Error("Ungültige SMB-Sicherung.")
            if "identity" in data or "security" in data:
                from .config_restore import validate_identity_config
                validate_identity_config(data, self.host)
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
            key = (("bundle", tuple(item["apps"]), tuple(item["shares"]), item["include_config"])
                   if item["type"] == "bundle" else (item["type"], item.get("vm_name", "")))
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

    def create_vm(self, name, xml, disk, disks=None):
        """Caller must verify that the managed VM is shut off before invocation."""
        with self.lock:
            identifier(name)
            disk = Path(disk)
            if not isinstance(xml, str) or len(xml) > MAX_CONFIG:
                raise Error("Ungültige verwaltete VM-Dateien.")
            try:
                document = ET.fromstring(xml)
            except ET.ParseError:
                raise Error("Ungültige verwaltete VM-Definition.") from None
            nodes = document.findall("./devices/disk[@device='disk']")
            if disks is None:
                disks = [{"disk": str(disk), "target": "vda"}]
            if not isinstance(disks, list) or not 1 <= len(disks) <= 8 or len(nodes) != len(disks) or Path(disks[0].get("disk", "")) != disk:
                raise Error("Alle VM-Laufwerke müssen gemeinsam gesichert werden.")
            checked, targets = [], set()
            for index, (node, entry) in enumerate(zip(nodes, disks)):
                source, target = node.find("source"), node.find("target")
                path = Path(entry.get("disk", ""))
                target_name = target.get("dev", "") if target is not None else ""
                if source is None or source.get("file") != str(path) or not re.fullmatch(r"vd[a-z]", target_name) or target_name in targets:
                    raise Error("VM-XML und Laufwerksmetadaten stimmen nicht überein.")
                targets.add(target_name)
                location = self.host.validate_vm_disk_path(name, path, entry.get("storage"), entry.get("storage_uuid"))
                with directory_fd(path.parent) as parent:
                    if os.fstat(parent).st_dev != location["device"]:
                        raise Error("VM-Speicher wurde während der Sicherung ausgehängt.", 503)
                    descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
                    try:
                        info = os.fstat(descriptor)
                        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                            raise Error("VM-Disk muss eine eigenständige reguläre Datei sein.")
                        image = json.loads(self.run(["qemu-img", "info", "--output=json", "/proc/self/fd/" + str(descriptor)], pass_fds=(descriptor,)))
                    finally:
                        os.close(descriptor)
                size = image.get("virtual-size")
                if not self.standalone_image(image) or type(size) is not int or not 0 < size <= MAX_BYTES:
                    raise Error("Nur eigenständige qcow2-Disks ohne Backing-Datei können gesichert werden.")
                checked.append({"path": path, "location": location, "archive": "vm/disk.qcow2" if index == 0 else "vm/disk-" + str(index) + ".qcow2", "target": target_name, "virtual_size": size})
            def write(archive, totals, temporary):
                vm = temporary / "vm"
                vm.mkdir(mode=0o700)
                (vm / "domain.xml").write_text(xml)
                node = document.find('./os/nvram')
                if node is not None:
                    nvram = self.host.vm_instance_nvram_path(name, disk)
                    if node.text != str(nvram): raise Error('UEFI-Speicherpfad ist nicht verwaltet.')
                    if os.path.lexists(nvram):
                        fd = os.open(nvram, os.O_RDONLY | os.O_NOFOLLOW)
                        with os.fdopen(fd, 'rb') as stream:
                            info = os.fstat(stream.fileno())
                            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 16*1024**2: raise Error('UEFI-Speicher ist ungültig.')
                            (vm / 'nvram.fd').write_bytes(stream.read(16*1024**2+1))
                self._add_tree(archive, vm, "vm", totals)
                for entry in checked:
                    path, location = entry["path"], entry["location"]
                    self.host.validate_vm_disk_path(name, path)
                    with directory_fd(path.parent) as fd:
                        if os.fstat(fd).st_dev != location["device"]:
                            raise Error("VM-Speicher wurde während der Sicherung ausgehängt.", 503)
                        sourcefd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                        with os.fdopen(sourcefd, "rb") as stream:
                            before = os.fstat(stream.fileno())
                            if not stat.S_ISREG(before.st_mode) or before.st_dev != location["device"]:
                                raise Error("VM-Disk besitzt eine unerwartete Speicherkennung.", 409)
                            node = tarfile.TarInfo(entry["archive"])
                            node.size, node.mode = before.st_size, 0o660
                            archive.addfile(node, stream)
                            after = os.fstat(stream.fileno())
                            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                                raise Error("VM-Disk wurde während des Backups verändert.")
                            totals[0] += 1
                            totals[1] += before.st_size
            return self._create("vm", {"shares": [], "include_config": False, "vm_name": name,
                                      "vm_disks": [{key: item[key] for key in ("archive", "target", "virtual_size")} for item in checked]}, write)

    def verified_vm(self, backup):
        manifest = self.manifest(backup)
        if manifest["type"] != "vm":
            raise Error("Dieses Backup enthält keine VM.")
        self.verify(backup)
        with self._archive(backup) as (_, archive):
            xml = archive.getmember("vm/domain.xml")
            if not xml.isfile() or xml.size > MAX_CONFIG:
                raise Error("Ungültige VM-Definition im Backup.")
            content = archive.extractfile(xml).read().decode("utf-8")
            document = ET.fromstring(content)
            disks = manifest.get("vm_disks", [{"archive": "vm/disk.qcow2", "target": "vda", "virtual_size": None}])
            nodes = document.findall("./devices/disk[@device='disk']")
            if len(nodes) != len(disks):
                raise Error("VM-Sicherung enthält nicht alle Laufwerke der Definition.")
            for node, disk in zip(nodes, disks):
                target = node.find("target")
                if target is None or target.get("dev") != disk["target"]:
                    raise Error("VM-Archiv und Laufwerksliste widersprechen sich.")
                try:
                    member = archive.getmember(disk["archive"])
                except KeyError:
                    raise Error("Ein VM-Laufwerk fehlt im Archiv.") from None
                if not member.isfile() or member.size <= 0:
                    raise Error("Ungültiges VM-Laufwerk im Archiv.")
            return {**manifest, "xml": content, "disks": disks}

    def restore_vm_nvram(self, backup, name, disk=None):
        self.verified_vm(backup)
        with self._archive(backup) as (_, archive):
            try: member = archive.getmember('vm/nvram.fd')
            except KeyError: return
            if not member.isfile() or not 0 < member.size <= 16*1024**2: raise Error('Ungültiger UEFI-Speicher im Backup.')
            destination = self.host.vm_instance_nvram_path(name, disk) if disk is not None else self.host.vm_nvram_path(name)
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
        """Backward-compatible single-disk entry point."""
        if len(self.verified_vm(backup)["disks"]) != 1:
            raise Error("Mehrdisk-Sicherungen über die vollständige VM-Wiederherstellung übernehmen.")
        return self.restore_vm_bundle(backup, name)["disks"][0]["disk"]

    def restore_vm_bundle(self, backup, name, storage="system"):
        """Restore every disk into new files; never import archive host paths."""
        with self.lock:
            identifier(name)
            verified = self.verified_vm(backup)
            restored, created = [], []
            with self.host.vm_storage_fd(storage, create=True) as (parent, location):
                with self._archive(backup) as (_, archive):
                    try:
                        for index, disk in enumerate(verified["disks"]):
                            filename = name + ("" if index == 0 else "--" + secrets.token_hex(16)) + ".qcow2"
                            target = Path(location["path"]) / filename
                            try:
                                targetfd = os.open(filename, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o660, dir_fd=parent)
                            except FileExistsError:
                                raise Error("VM-Disk existiert bereits; vorhandene Disk wird nicht ersetzt.", 409) from None
                            created.append(filename)
                            try:
                                member = archive.getmember(disk["archive"])
                                with archive.extractfile(member) as source:
                                    remaining = member.size
                                    while remaining:
                                        chunk = source.read(min(1024 * 1024, remaining))
                                        if not chunk:
                                            raise Error("VM-Laufwerk ist im Archiv unvollständig.")
                                        # Preserve sparse gaps rather than allocating
                                        # every zero-filled qcow2 byte on restoration.
                                        if chunk.count(0) == len(chunk):
                                            os.lseek(targetfd, len(chunk), os.SEEK_CUR)
                                        else:
                                            offset = 0
                                            while offset < len(chunk): offset += os.write(targetfd, chunk[offset:])
                                        remaining -= len(chunk)
                                    os.ftruncate(targetfd, member.size)
                                    os.fsync(targetfd)
                                image = json.loads(self.run(["qemu-img", "info", "--output=json", "/proc/self/fd/" + str(targetfd)], pass_fds=(targetfd,)))
                                if not self.standalone_image(image) or disk.get("virtual_size") is not None and image.get("virtual-size") != disk["virtual_size"]:
                                    raise Error("Backup enthält kein passendes eigenständiges qcow2-Laufwerk.")
                            finally:
                                os.close(targetfd)
                            self.host.vm_storage_label(target)
                            restored.append({"disk": str(target), "storage": location["id"], "target": disk["target"], "virtual_size": image.get("virtual-size"), **({"storage_uuid": location["uuid"]} if location.get("uuid") else {})})
                    except Exception:
                        for filename in created:
                            try: os.unlink(filename, dir_fd=parent)
                            except FileNotFoundError: pass
                        raise
            return {"disks": restored, "xml": verified["xml"], "storage": location["id"]}

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

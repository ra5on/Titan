"""Managed Samba accounts and share transactions; files and Linux UIDs are retained."""
from .platforms import current as host_platform
import errno
import json
import os
from pathlib import Path
import pwd
import re
import stat
import tempfile

from .core import Error, identifier, password_hash


PROTECTED = {"root", "titan", "titan-files", "titan-proxy"}


class ManagementMixin:
    def command(self, *args, **kwargs):
        # Resolve at call time so Host's command runner remains the single boundary.
        from .host import run
        return run(*args, **kwargs)

    def op_accounts(self, smb_status=False):
        records = [{**item, "enabled": item.get("enabled", True)} for item in self.load("accounts", [])]
        if type(smb_status) is not bool:
            raise Error("Ungültige SMB-Statusoption.")
        if not smb_status:
            return records
        # Passdb hashes remain confined to the root agent. Only readiness flags
        # are exposed; never put raw passdb output in a response or exception.
        try:
            entries = {}
            output = self.command(["pdbedit", "-L", "-w"])
            for line in output.splitlines():
                fields = line.split(":")
                if len(fields) != 7 or not fields[1].isdigit():
                    continue
                entries[fields[0]] = fields
            for item in records:
                fields = entries.get(item["name"])
                configured = bool(fields and int(fields[1]) == item["uid"])
                password_set = bool(configured and len(fields[3]) == 32 and all(char in "0123456789abcdefABCDEF" for char in fields[3]))
                enabled = bool(configured and "D" not in fields[4] and "N" not in fields[4] and item["enabled"] and not item.get("removed"))
                item.update(smb_configured=configured, smb_enabled=enabled, smb_ready=enabled and password_set)
        except Exception:
            for item in records:
                item.update(smb_configured=None, smb_enabled=None, smb_ready=None,
                            smb_error="SMB-Kontostatus momentan nicht verfügbar.")
        return records

    def managed_account(self, name, allow_removed=False):
        name = identifier(name)
        record = next((item for item in self.op_accounts() if item["name"] == name), None)
        if name in PROTECTED or not record or (record.get("removed") and not allow_removed):
            raise Error("Nur verwaltete Benutzerkonten dürfen geändert werden.", 403)
        try:
            account = pwd.getpwnam(name)
        except KeyError:
            raise Error("Verwalteter Linux-Benutzer fehlt.", 409)
        if account.pw_uid < 1000 or account.pw_uid != record["uid"]:
            raise Error("Linux-Benutzerkennung wurde außerhalb von Titan geändert.", 409)
        return record, account

    def require_active_account(self, name):
        if name == "titan-files":
            return
        record, _ = self.managed_account(name)
        if not record["enabled"]:
            raise Error("Dieses Benutzerkonto ist gesperrt.", 403)

    @staticmethod
    def smb_password(password):
        password_hash(password)
        if any(char in password for char in ("\n", "\r", "\x00")):
            raise Error("Passwort enthält ungültige Zeichen.")

    def op_account_create(self, name, password):
        name = identifier(name)
        self.smb_password(password)
        if name in PROTECTED or any(item["name"] == name for item in self.op_accounts()):
            raise Error("Benutzer existiert bereits oder ist reserviert.", 409)
        try:
            pwd.getpwnam(name)
        except KeyError:
            pass
        else:
            raise Error("Dieser Linux-Benutzer existiert bereits und wird nicht übernommen.")
        self.command(["useradd", "--no-create-home", "--shell", "/usr/sbin/nologin", "--user-group", name])
        try:
            self.command(["smbpasswd", "-s", "-a", name], input=password + "\n" + password + "\n")
            accounts = self.op_accounts()
            accounts.append({"name": name, "uid": pwd.getpwnam(name).pw_uid, "enabled": True})
            self.save("accounts", accounts)
        except Exception:
            try:
                self.command(["smbpasswd", "-x", name])
            except Exception:
                pass  # smbpasswd may have failed before creating its passdb entry.
            self.command(["userdel", name])
            raise Error("Benutzer konnte nicht angelegt werden.", 500) from None
        return {"ok": True}

    def op_account_password(self, name, password):
        return self.op_account_update(name, password=password)

    def op_account_link(self, name, password):
        """Repair a legacy web administrator's missing personal SMB login.

        Called only after the web service verifies the existing web password.
        Repeated attempts reuse a known managed identity; arbitrary existing
        Linux accounts are never adopted. App ownership and the service user's
        password remain unchanged.
        """
        name = identifier(name)
        self.smb_password(password)
        if name in PROTECTED:
            raise Error("Dieser Benutzername ist für ein Dienstkonto reserviert.", 403)
        with self.account_lock:
            existing = next((item for item in self.op_accounts() if item["name"] == name), None)
            if existing:
                record, _ = self.managed_account(name)
                if not record["enabled"]:
                    raise Error("Das zugehörige SMB-Konto ist gesperrt; zuerst den Kontostatus prüfen.", 409)
                self.op_account_password(name, password)
            else:
                self.op_account_create(name, password)
            changed = []
            try:
                for share in self.op_shares():
                    readers, writers = share["readers"], share["writers"]
                    if share.get("blocked") or name in readers + writers or "titan-files" not in readers + writers:
                        continue
                    changed.append((share["name"], list(readers), list(writers)))
                    if "titan-files" in writers:
                        self._update_share_rights(share["name"], readers, sorted(set(writers + [name])))
                    else:
                        self._update_share_rights(share["name"], sorted(set(readers + [name])), writers)
            except Exception:
                for share, readers, writers in reversed(changed):
                    self._update_share_rights(share, readers, writers)
                raise Error("SMB-Zugang ist angelegt; Freigaberechte konnten noch nicht übernommen werden. Passwortänderung erneut versuchen.", 500) from None
        return {"ok": True, "system_user": name, "smb_ready": True}

    def samba_snapshot(self, name):
        record, _ = self.managed_account(name)
        try:
            output = self.command(["pdbedit", "-L", "-w", "-u", name])
            rows = [line for line in output.splitlines() if line.split(":", 1)[0] == name]
            if len(rows) != 1 or len(rows[0].split(":")) != 7 or int(rows[0].split(":")[1]) != record["uid"]:
                raise ValueError("Unexpected passdb entry")
            return rows[0] + "\n"
        except Exception:
            # Never put passdb output or command stderr containing a hash in an API error.
            raise Error("SMB-Konto konnte nicht für die Änderung gesichert werden.", 500) from None

    def restore_samba_snapshot(self, name, snapshot):
        with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, prefix="samba-rollback-", delete=True) as stream:
            os.chmod(stream.name, 0o600)
            stream.write(snapshot)
            stream.flush()
            try:
                self.command(["pdbedit", "-i", "smbpasswd:" + stream.name, "-u", name])
            except Exception:
                raise Error("SMB-Konto konnte nicht zurückgesetzt werden.", 500) from None

    def op_account_update(self, name, password=None, enabled=None):
        record, _ = self.managed_account(name)
        if enabled is not None and type(enabled) is not bool:
            raise Error("Kontostatus muss wahr oder falsch sein.")
        if password is not None:
            self.smb_password(password)
        if enabled is None and password is None:
            return {"ok": True, "enabled": record["enabled"]}
        previous = self.op_accounts()
        active = record["enabled"] if enabled is None else enabled
        updated = [{**item, "enabled": active} if item["name"] == name else item for item in previous]
        snapshot = self.samba_snapshot(name)
        affected = [share["name"] for share in self.op_shares() if name in share["readers"] + share["writers"]]
        try:
            if password is not None:
                self.command(["smbpasswd", "-s", name], input=password + "\n" + password + "\n")
            self.command(["smbpasswd", "-e" if active else "-d", name])
            self.share_config_transaction(self.op_shares(), accounts=updated, close=affected)
            self.save("accounts", updated)
        except Exception:
            try:
                self.restore_samba_snapshot(name, snapshot)
                self.share_config_transaction(self.op_shares(), accounts=previous, close=affected)
            except Exception:
                # A failed rollback must not leave an account silently enabled.
                blocked = [{**item, "enabled": False} if item["name"] == name else item for item in previous]
                self.save("accounts", blocked)
                self.command(["smbpasswd", "-d", name])
                self.share_config_transaction(self.op_shares(), accounts=blocked, close=affected)
                raise Error("SMB-Konto konnte nicht zurückgesetzt werden und wurde gesperrt.", 500) from None
            raise Error("SMB-Konto konnte nicht geändert werden; bisherige Einstellungen wurden zurückgesetzt.", 500) from None
        return {"ok": True, "enabled": active}

    def close_user_shares(self, name):
        for share in self.op_shares():
            if name in share["readers"] + share["writers"]:
                self.command(["smbcontrol", "smbd", "close-share", share["name"]])

    def op_account_set_enabled(self, name, enabled):
        if type(enabled) is not bool:
            raise Error("Kontostatus muss wahr oder falsch sein.")
        return self.op_account_update(name, enabled=enabled)

    def op_account_remove(self, name):
        record, _ = self.managed_account(name, allow_removed=True)
        if not record.get("removed"):
            # Deletion has no rollback to an enabled identity. Persist the block
            # before external commands, and accept an already absent passdb entry.
            self.save("accounts", [{**item, "enabled": False} if item["name"] == name else item
                                   for item in self.op_accounts()])
            samba_names = {line.split(":", 1)[0] for line in self.command(["pdbedit", "-L"]).splitlines()}
            if name in samba_names:
                self.command(["smbpasswd", "-d", name])
            self.command(["usermod", "--lock", name])
            affected = [share["name"] for share in self.op_shares() if name in share["readers"] + share["writers"]]
            self.share_config_transaction(self.op_shares(), close=affected)
        # Remove memberships and ACL access before dropping the Samba identity.
        # Successful share transactions survive retries after a later failure.
        for share in self.op_shares():
            if name in share["readers"] + share["writers"]:
                self._update_share_rights(share["name"],
                    [member for member in share["readers"] if member != name],
                    [member for member in share["writers"] if member != name])
        if record.get("removed"):
            return {"ok": True, "data_retained": True, "linux_account_retained": True}
        # Keep the Linux account, numeric UID, ownership and name tombstone. Reusing
        # a removed UID would give a different person access to retained files.
        samba_names = {line.split(":", 1)[0] for line in self.command(["pdbedit", "-L"]).splitlines()}
        if name in samba_names:
            self.command(["smbpasswd", "-x", name])
        self.save("accounts", [{**item, "enabled": False, "removed": True} if item["name"] == name else item
                               for item in self.op_accounts()])
        return {"ok": True, "data_retained": True, "linux_account_retained": True}

    def op_shares(self):
        return self.load("shares", [])

    def op_shares_access(self):
        warnings = []
        try:
            state = self.command(["systemctl", "show", host_platform().samba_unit, "--property=ActiveState", "--value"], timeout=15)
            active = state.strip() == "active"
            if not active:
                warnings.append("Samba-Dienst ist nicht aktiv.")
        except Error:
            active = None
            warnings.append("Samba-Dienststatus momentan nicht verfügbar.")
        addresses = self._host_addresses()
        firewall = []
        try:
            default_zone = self.command(["firewall-cmd", "--get-default-zone"], timeout=15).strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", default_zone):
                raise Error("Ungültige Standardzone.")
            for interface in sorted({item["interface"] for item in addresses if item.get("scope") == "lan"}):
                try:
                    zone = self.command(["firewall-cmd", "--get-zone-of-interface=" + interface], timeout=15).strip()
                except Error:
                    zone = default_zone  # An unassigned interface uses the default zone.
                if zone in ("", "no zone"):
                    zone = default_zone
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", zone):
                    raise Error("Ungültige Netzwerkschnittstellen-Zone.")
                services = self.command(["firewall-cmd", "--zone=" + zone, "--list-services"], timeout=15).split()
                ports = self.command(["firewall-cmd", "--zone=" + zone, "--list-ports"], timeout=15).split()
                target = self.command(["firewall-cmd", "--zone=" + zone, "--get-target"], timeout=15).strip()
                enabled, port_enabled = "samba" in services, "445/tcp" in ports
                firewall.append({"interface": interface, "zone": zone, "samba_service_enabled": enabled,
                                 "port_445_enabled": port_enabled, "target": target})
                if not enabled and not port_enabled and target != "ACCEPT":
                    warnings.append(f"Firewall-Zone {zone} für {interface} enthält keine Samba-Dienstfreigabe für Port 445. Eigene Firewallregeln gegebenenfalls prüfen.")
        except Error:
            warnings.append("Firewall-Zonen konnten nicht vollständig geprüft werden.")
        return {"host_addresses": addresses, "service_active": active, "port": 445,
                "firewall": firewall, "warnings": warnings}

    def share_members(self, readers, writers, previous=None):
        if not isinstance(readers, list) or not isinstance(writers, list):
            raise Error("Freigaberechte müssen Benutzerlisten sein.")
        if any(not isinstance(name, str) for name in readers + writers):
            raise Error("Ungültiger Benutzername.")
        for name in readers + writers:
            identifier(name)
            if (previous and name != "titan-files" and
                    ((name in readers and name in previous["readers"] + previous["writers"] and name not in writers) or
                     (name in writers and name in previous["writers"]))):
                self.managed_account(name)  # Keep an unchanged, disabled membership.
            else:
                self.require_active_account(name)
        return sorted(set(readers) - set(writers)), sorted(set(writers))

    @staticmethod
    def share_namespace_traversal(fd, owner_uid=None):
        """Allow ACL-authorized users through a root-controlled parent only."""
        info = os.fstat(fd)
        expected_owner = os.geteuid() if owner_uid is None else owner_uid
        if info.st_uid != expected_owner or info.st_mode & 0o022:
            raise Error("Freigabe-Verzeichnisse müssen root gehören und gegen fremde Schreibzugriffe geschützt sein.")
        mode = stat.S_IMODE(info.st_mode)
        if mode & 0o011 != 0o011:
            os.fchmod(fd, mode | 0o011)

    def system_share_path(self, name):
        """Create a share without following a replaced namespace or child."""
        root_fd = os.open(self.share_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if os.fstat(root_fd).st_mode & 0o011 != 0o011:
                self.share_namespace_traversal(root_fd)
            try:
                os.mkdir("shares", 0o751, dir_fd=root_fd)
            except FileExistsError:
                pass
            parent = os.open("shares", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
            try:
                self.share_namespace_traversal(parent)
                try:
                    os.mkdir(name, 0o770, dir_fd=parent)
                except FileExistsError:
                    raise Error("Der Freigabeordner existiert bereits; vorhandene Daten werden nicht übernommen.", 409)
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    owner = pwd.getpwnam("titan-files")
                    os.fchown(child, owner.pw_uid, owner.pw_gid)
                finally:
                    os.close(child)
            finally:
                os.close(parent)
        finally:
            os.close(root_fd)
        return self.share_root / "shares" / name

    def open_share_root(self, path):
        root = self.share_root.resolve()
        candidate = Path(path)
        if not candidate.is_absolute() or any(part in (".", "..") for part in candidate.parts):
            raise Error("Ungültiger Freigabepfad.")
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            raise Error("Freigabepfad liegt außerhalb des Titan-Speichers.")
        required_device = self.volume_manager.required_path(candidate)
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if os.fstat(fd).st_mode & 0o011 != 0o011:
                self.share_namespace_traversal(fd)
            for index, part in enumerate(relative.parts):
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
                if index == 0 and part == "shares" and len(relative.parts) >= 2:
                    self.share_namespace_traversal(fd)
                elif required_device is not None and index == 0 and part == "volumes":
                    self.share_namespace_traversal(fd, self.volume_manager.owner_uid)
                elif required_device is not None and index == 1 and len(relative.parts) >= 4:
                    if os.fstat(fd).st_dev != required_device:
                        raise Error("Volume wurde während des Dateizugriffs ausgehängt.", 503)
                    self.share_namespace_traversal(fd, self.volume_manager.owner_uid)
                elif required_device is not None and index == 2 and part == "shares" and len(relative.parts) >= 4:
                    if os.fstat(fd).st_dev != required_device:
                        raise Error("Volume wurde während des Dateizugriffs ausgehängt.", 503)
                    self.share_namespace_traversal(fd, self.volume_manager.owner_uid)
            if required_device is not None and os.fstat(fd).st_dev != required_device:
                raise Error("Volume wurde während des Dateizugriffs ausgehängt.", 503)
            return fd
        except Exception:
            os.close(fd)
            raise

    @staticmethod
    def open_relative(root_fd, relative):
        parts = Path(relative).parts
        fd = os.dup(root_fd)
        try:
            for index, part in enumerate(parts):
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                if index < len(parts) - 1:
                    flags |= os.O_DIRECTORY
                child = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            return fd
        except Exception:
            os.close(fd)
            raise

    def acl_read(self, fd):
        return self.command(["getfacl", "--omit-header", "--numeric", "--", f"/proc/self/fd/{fd}"], pass_fds=(fd,))

    def acl_write(self, fd, text, directory):
        if directory:
            self.command(["setfacl", "--remove-default", "--", f"/proc/self/fd/{fd}"], pass_fds=(fd,))
        self.command(["setfacl", "--set-file=-", "--", f"/proc/self/fd/{fd}"], input=text + "\n", pass_fds=(fd,))

    def acl_for_members(self, text, readers, writers, directory, owner_uid=None):
        known = {item["uid"] for item in self.op_accounts()}
        known.add(pwd.getpwnam("titan-files").pw_uid)
        members = {pwd.getpwnam(name).pw_uid: ("rwX" if name in writers else "r-X") for name in readers + writers}
        entries = []
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.removeprefix("default:").split(":")
            if len(parts) == 3 and parts[0] == "user" and parts[1].isdigit() and int(parts[1]) in known:
                continue
            if line.startswith("mask:") or line.startswith("default:mask:"):
                continue  # setfacl recomputes masks after changing named entries.
            if line.startswith("user::") and owner_uid in known:
                line = "user::" + members.get(owner_uid, "---")
            entries.append(line)
        if directory and not any(line.startswith("default:") for line in entries):
            entries += ["default:" + line for line in entries if line.split(":")[0] in ("user", "group", "other") and line.split(":")[1] == ""]
            # The default owner is the future file's creator, which may be a
            # different writer from this directory's current owner.
            entries = ["default:user::rwx" if line.startswith("default:user::") else line for line in entries]
        for uid in sorted(known):
            # Explicit deny entries prevent a revoked account inheriting group/other rights.
            permissions = members.get(uid, "---")
            entries.append(f"user:{uid}:{permissions}")
            if directory:
                entries.append(f"default:user:{uid}:{permissions.replace('X', 'x')}")
        return "\n".join(entries)

    def share_acl_transaction(self, record, readers, writers, operation):
        root_fd = self.open_share_root(record["path"])
        changed = []
        # Journal each ACL before changing it. A directory descriptor plus O_NOFOLLOW
        # pins the actual inode; symlink swaps cannot redirect the root command.
        try:
            with tempfile.TemporaryFile(mode="w+t", dir=self.directory) as journal:
                try:
                    for directory, dirs, files, dir_fd in os.fwalk(".", follow_symlinks=False, dir_fd=root_fd):
                        relative_dir = "" if directory == "." else directory.removeprefix("./")
                        for relative in [relative_dir] + [str(Path(relative_dir) / name) for name in files]:
                            try:
                                fd = self.open_relative(root_fd, relative)
                            except OSError as exc:
                                if exc.errno == errno.ELOOP:  # A symlink is deliberately skipped.
                                    continue
                                raise
                            try:
                                info = os.fstat(fd)
                                if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                                    continue
                                original = self.acl_read(fd)
                                offset = journal.tell()
                                journal.write(json.dumps({"path": relative, "dev": info.st_dev, "ino": info.st_ino,
                                                          "directory": stat.S_ISDIR(info.st_mode), "acl": original}) + "\n")
                                journal.flush()
                                changed.append(offset)
                                self.acl_write(fd, self.acl_for_members(original, readers, writers, stat.S_ISDIR(info.st_mode), info.st_uid), stat.S_ISDIR(info.st_mode))
                            finally:
                                os.close(fd)
                    operation()
                except Exception as original_error:
                    rollback_errors = []
                    for offset in reversed(changed):
                        journal.seek(offset)
                        item = json.loads(journal.readline())
                        try:
                            fd = self.open_relative(root_fd, item["path"])
                            try:
                                info = os.fstat(fd)
                                if (info.st_dev, info.st_ino) != (item["dev"], item["ino"]):
                                    raise Error("Datei wurde während der Rechteänderung ersetzt.")
                                self.acl_write(fd, item["acl"], item["directory"])
                            finally:
                                os.close(fd)
                        except Exception:
                            rollback_errors.append(item["path"])
                    if rollback_errors:
                        raise Error("Rechteänderung fehlgeschlagen; nicht alle ACLs konnten zurückgesetzt werden. Freigabe bleibt gesperrt.", 500) from original_error
                    raise
        finally:
            os.close(root_fd)

    def share_config_text(self, shares, accounts=None):
        accounts = self.op_accounts() if accounts is None else accounts
        active = {item["name"] for item in accounts if item.get("enabled", True) and not item.get("removed")} | {"titan-files"}
        config = []
        for share in shares:
            readers = [name for name in share["readers"] if name in active]
            writers = [name for name in share["writers"] if name in active]
            config += [f"[{identifier(share['name'])}]", f"path = {share['path']}", "browseable = yes", "guest ok = no",
                       "access based share enum = yes", "inherit acls = yes",
                       "available = " + ("yes" if (readers or writers) and not share.get("blocked") and share["name"] not in self.suspended_shares else "no"), "read only = yes",
                       "valid users = " + " ".join(readers + writers), "write list = " + " ".join(writers),
                       "create mask = 0660", "directory mask = 0770", ""]
        return "\n".join(config)

    def share_config_transaction(self, shares, accounts=None, close=()):
        with self.account_lock, self.samba_lock:
            destination = self.samba_config
            previous = destination.read_text() if destination.exists() else ""
            destination.write_text(self.share_config_text(shares, accounts))
            try:
                self.command(["testparm", "-s", "/etc/samba/smb.conf"])
                self.command(["systemctl", "reload", host_platform().samba_unit.removesuffix(".service")])
                for name in close:
                    self.command(["smbcontrol", "smbd", "close-share", name])
            except Exception:
                destination.write_text(previous)
                self.command(["systemctl", "reload", host_platform().samba_unit.removesuffix(".service")])
                raise

    def op_share_create(self, name, readers, writers, dataset=None, volume=None):
        name = identifier(name)
        shares = self.op_shares()
        if any(item["name"] == name for item in shares):
            raise Error("Freigabe existiert bereits.")
        readers, writers = self.share_members(readers, writers)
        if not readers and not writers:
            raise Error("Mindestens ein Benutzer ist erforderlich.")
        if dataset and volume:
            raise Error("Entweder ein ZFS-Dataset oder ein Ext4/XFS-Volume wählen.")
        if volume:
            path = self.volume_manager.share_path(volume, name)
        elif dataset:
            self.dataset(dataset)
            path = Path(next(item["mountpoint"] for item in self.op_storage()["datasets"] if item["name"] == dataset))
        else:
            path = self.system_share_path(name)
        fd = self.open_share_root(path)
        os.close(fd)
        if any(item["path"] == str(path) for item in shares):
            raise Error("Dieser Pfad ist bereits freigegeben.")
        record = {"name": name, "path": str(path), "readers": readers, "writers": writers, "dataset": dataset}
        if volume:
            record["volume"] = identifier(volume)
        updated = shares + [record]
        # Fedora enforces SELinux independently of the POSIX ACLs. The image
        # supplies persistent path rules; do not weaken global enforcement.
        if Path("/sys/fs/selinux/enforce").is_file():
            verified = self.open_share_root(path)
            try:
                # Newly mounted filesystems and their intermediate namespaces
                # also need directory labels before smbd/container traversal.
                relative = Path(path).relative_to(self.share_root)
                parents = [str(self.share_root)]
                parent = self.share_root
                for part in relative.parts[:-1]:
                    parent /= part
                    parents.append(str(parent))
                self.command(["restorecon", "-F", "--", *parents])
                self.command(["restorecon", "-R", "-F", "--", str(path)], timeout=300)
            finally:
                os.close(verified)
        def publish():
            self.share_config_transaction(updated)
            try:
                self.save("shares", updated)
            except Exception:
                self.share_config_transaction(shares)
                raise
        self.share_acl_transaction(record, readers, writers, publish)
        return {"ok": True}

    def op_share_update(self, name, readers, writers):
        name = identifier(name)
        record = next((item for item in self.op_shares() if item["name"] == name), None)
        if not record:
            raise Error("Freigabe nicht gefunden.", 404)
        readers, writers = self.share_members(readers, writers, previous=record)
        return self._update_share_rights(name, readers, writers)

    def _update_share_rights(self, name, readers, writers):
        """Apply already validated memberships, including disabled existing users."""
        name = identifier(name)
        shares = self.op_shares()
        record = next((item for item in shares if item["name"] == name), None)
        if not record:
            raise Error("Freigabe nicht gefunden.", 404)
        updated = [{**item, "readers": readers, "writers": writers, "blocked": False} if item["name"] == name else item for item in shares]
        # Pause this share while traversing existing files. New SMB clients cannot
        # race the ACL transaction and old writable handles are closed first.
        with self.account_lock, self.samba_lock:
            self.suspended_shares.add(name)
            try:
                self.share_config_transaction(shares, close=[name])
            except Exception:
                self.suspended_shares.discard(name)
                raise
        def publish():
            with self.account_lock, self.samba_lock:
                self.suspended_shares.discard(name)
                try:
                    self.share_config_transaction(updated, close=[name])
                    self.save("shares", updated)
                except Exception:
                    self.suspended_shares.add(name)
                    self.share_config_transaction(shares, close=[name])
                    raise
        try:
            self.share_acl_transaction(record, readers, writers, publish)
        except Error as exc:
            if exc.status != 500:
                with self.account_lock, self.samba_lock:
                    self.suspended_shares.discard(name)
                    self.share_config_transaction(shares, close=[name])
            else:
                blocked = [{**item, "blocked": True} if item["name"] == name else item for item in shares]
                self.save("shares", blocked)
                self.suspended_shares.discard(name)
                self.share_config_transaction(blocked, close=[name])
            raise
        except Exception:
            with self.account_lock, self.samba_lock:
                self.suspended_shares.discard(name)
                self.share_config_transaction(shares, close=[name])
            raise
        return {"ok": True}

    def op_share_remove(self, name):
        name = identifier(name)
        shares = self.op_shares()
        if not any(item["name"] == name for item in shares):
            raise Error("Freigabe nicht gefunden.", 404)
        updated = [item for item in shares if item["name"] != name]
        self.share_config_transaction(updated, close=[name])
        try:
            self.save("shares", updated)
        except Exception:
            self.share_config_transaction(shares, close=[name])
            raise
        return {"ok": True, "data_retained": True}

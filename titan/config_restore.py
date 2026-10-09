"""Fixed root helper for a validated, same-host NAS configuration restore.

Only Titan-managed UIDs are accepted. It never rewrites passwd/group, mounts
filesystems, executes backed-up commands or imports backed-up libvirt XML.
"""
from .platforms import current as host_platform
import argparse
import contextlib
import json
import os
from pathlib import Path
import pwd
import re
import sqlite3
import stat
import tempfile
import time

from .core import valid_password_hash, Error, Store, atomic_json, identifier, user_profile_text


def validate_config(host, data):
    """Validate independently immediately before stopping any running services."""
    if (not isinstance(data, dict) or data.get("schema") != 1 or not {"schema", "users", "config", "agent", "samba"} <= set(data) or set(data) - {"schema", "users", "config", "agent", "samba", "identity", "security"}):
        raise Error("Unbekanntes Konfigurationsformat.")
    agent = data.get("agent")
    if not isinstance(agent, dict) or set(agent) != {"accounts", "shares", "apps"} or any(not isinstance(value, list) for value in agent.values()):
        raise Error("Ungültige Hostkonfiguration.")
    current_accounts = {item["name"]: item for item in host.op_accounts()}
    accounts = {}
    for item in agent["accounts"]:
        if not isinstance(item, dict) or set(item) - {"name", "uid", "enabled", "removed"}:
            raise Error("Ungültiges Benutzerkonto in der Sicherung.")
        name = identifier(item.get("name"))
        if name in accounts or name not in current_accounts or name in ("root", "titan", "titan-files", "titan-proxy"):
            raise Error("Konfiguration kann nur auf demselben Host mit bekannten Benutzerkonten wiederhergestellt werden.")
        try:
            account = pwd.getpwnam(name)
        except KeyError:
            raise Error("Ein gesicherter Linux-Benutzer fehlt auf diesem Host.") from None
        if (type(item.get("uid")) is not int or item["uid"] != current_accounts[name]["uid"] or
                account.pw_uid != item["uid"] or account.pw_uid == 0 or
                type(item.get("enabled", True)) is not bool or type(item.get("removed", False)) is not bool):
            raise Error("Gesicherte Linux-Benutzerkennung oder Kontostatus stimmt nicht mit diesem Host überein.")
        accounts[name] = item
    users, names = data.get("users"), set()
    if not isinstance(users, list) or not users or len(users) > 1000:
        raise Error("Ungültige Benutzerkonfiguration.")
    for user in users:
        if not isinstance(user, dict) or set(user) - {"name", "password", "role", "system_user", "enabled", "display_name", "description"}:
            raise Error("Ungültiger Webbenutzer.")
        name = identifier(user.get("name"))
        system_user = identifier(user.get("system_user"))
        if (name in names or user.get("role") not in ("admin", "user") or user.get("enabled", 1) not in (0, 1) or
                not valid_password_hash(user.get("password", "")) or
                (system_user != "titan-files" and (system_user not in accounts or accounts[system_user].get("removed")))):
            raise Error("Webbenutzer stimmen nicht mit den gesicherten verwalteten Konten überein.")
        if user.get("enabled", 1) and system_user != "titan-files" and not accounts[system_user].get("enabled", True):
            raise Error("Aktiver Webbenutzer besitzt ein gesperrtes SMB-Konto.")
        for field in ("display_name", "description"):
            if field in user:
                user_profile_text(user[field], field)
        names.add(name)
    if not any(user["role"] == "admin" and user.get("enabled", 1) for user in users):
        raise Error("Konfiguration enthält keinen aktiven Administrator.")
    share_names, paths = set(), set()
    from .backups import directory_fd
    for share in agent["shares"]:
        if not isinstance(share, dict) or set(share) - {"name", "path", "readers", "writers", "dataset", "blocked", "volume", "storage_id"}:
            raise Error("Ungültige Freigabenkonfiguration.")
        name = identifier(share.get("name"))
        path = Path(share.get("path", ""))
        if (name in share_names or str(path) in paths or not path.is_absolute() or ".." in path.parts or
                not path.is_relative_to(host.share_root) or path == host.share_root or any(char in str(path) for char in "\n\r\x00")):
            raise Error("Gesicherte Freigabe liegt außerhalb des verwalteten Datenbereichs.")
        if share.get("volume"):
            volume = identifier(share["volume"])
            host.volume_manager.require(volume)
            if share.get("dataset") or path != host.volume_manager.root / volume / "shares" / name:
                raise Error("Gesicherte Freigabe stimmt nicht mit dem vorhandenen gemounteten Volume überein.")
        if share.get("storage_id") and hasattr(host, "storage_locations"):
            location = host.storage_locations.validate_path(str(path))
            if location["id"] != share["storage_id"]:
                raise Error("Gesicherte Freigabe stimmt nicht mit ihrem Speicherbereich überein.")
        required_device = host.storage_locations.required_path(path) if hasattr(host, "storage_locations") else host.volume_manager.required_path(path) if hasattr(host, "volume_manager") else None
        with directory_fd(path) as descriptor:
            if required_device is not None and os.fstat(descriptor).st_dev != required_device:
                raise Error("Gesichertes Volume wurde ausgehängt.")
        for field in ("readers", "writers"):
            if not isinstance(share.get(field), list) or any(not isinstance(value, str) for value in share[field]):
                raise Error("Ungültige Freigaberechte.")
            for member in share[field]:
                identifier(member)
                if member != "titan-files" and (member not in accounts or accounts[member].get("removed")):
                    raise Error("Freigabe verweist auf ein unbekanntes Benutzerkonto.")
        share_names.add(name)
        paths.add(str(path))
    if not isinstance(data["samba"], list) or len(data["samba"]) > 1000:
        raise Error("Ungültige SMB-Zugangsdaten.")
    samba_names = set()
    for line in data["samba"]:
        fields = line.split(":") if isinstance(line, str) else []
        if (len(fields) != 7 or fields[0] not in accounts or fields[0] in samba_names or
                fields[1] != str(accounts[fields[0]]["uid"]) or
                not all(re.fullmatch(r"[A-Fa-f0-9]{32}|X{32}|\*{32}", fields[index]) for index in (2, 3)) or
                not re.fullmatch(r"\[[ A-Z]{11}\]", fields[4]) or not re.fullmatch(r"LCT-[A-Fa-f0-9]{8}", fields[5]) or fields[6] != ""):
            raise Error("Gesicherte SMB-Zugangsdaten sind ungültig.")
        samba_names.add(fields[0])
    if samba_names != {name for name, item in accounts.items() if not item.get("removed")}:
        raise Error("SMB-Zugangsdaten sind unvollständig.")
    settings = data.get("config")
    if not isinstance(settings, dict) or set(settings) - {"settings", "identity", "login_protection"}:
        raise Error("Ungültige Systemeinstellungen.")
    if "login_protection" in settings:
        from .login_protection import validate_settings
        validate_settings(settings["login_protection"])
    if "settings" in settings:
        with tempfile.TemporaryDirectory(prefix="restore-validate-", dir=host.directory) as temporary:
            Store(temporary).save_settings(settings["settings"])
    # Only import metadata for still-present app installations with matching
    # mounts and ports. A configuration restore never executes a backed-up Compose.
    current_apps = {item["id"]: item for item in host.load("apps", [])}
    for app in agent["apps"]:
        if not isinstance(app, dict) or app.get("id") not in current_apps or any(app.get(key) != current_apps[app["id"]].get(key) for key in ("port", "data", "config_path", "storage_id", "storage_uuid", "scheme", "network", "network_id")):
            raise Error("Eine gesicherte App wurde auf diesem Host geändert oder entfernt; zuerst die Appinstallation abgleichen.")
    validate_identity_config(data, host)
    return data


def validate_identity_config(data, host):
    from .identity import empty_policy, validate_policy
    users = data.get("users", [])
    shares = data.get("agent", {}).get("shares", [])
    accounts = {item["name"] for item in data.get("agent", {}).get("accounts", []) if not item.get("removed")}
    share_map = {item["name"]: item for item in shares}
    identity = data.get("identity")
    web_policy = data.get("config", {}).get("identity")
    if web_policy is not None:
        validate_policy(web_policy, users, shares)
    if identity is not None:
        if not isinstance(identity, dict) or set(identity) != {"policy", "baseline", "homes", "quotas"}:
            raise Error("Ungültige gesicherte Gruppenverwaltung.")
        policy = validate_policy(identity["policy"], users, shares)
        if web_policy is not None and policy != validate_policy(web_policy, users, shares):
            raise Error("Web- und SMB-Gruppenrechte stimmen in der Sicherung nicht überein.")
        for key in ("baseline", "homes", "quotas"):
            if not isinstance(identity[key], dict):
                raise Error("Ungültige gesicherte persönliche Ordner oder Quoten.")
        for name, record in identity["baseline"].items():
            if name not in share_map or not isinstance(record, dict) or set(record) != {"name", "readers", "writers"} or record["name"] != name:
                raise Error("Gesicherte Basisrechte verweisen auf unbekannte Freigaben.")
            for field in ("readers", "writers"):
                if not isinstance(record[field], list) or any(member != "titan-files" and member not in accounts for member in record[field]):
                    raise Error("Gesicherte Basisrechte enthalten unbekannte Benutzer.")
        for name, home in identity["homes"].items():
            if name not in accounts or not isinstance(home, dict) or set(home) != {"share", "path", "user"} or home["user"] != name or home["share"] not in share_map or home["path"] != share_map[home["share"]]["path"]:
                raise Error("Gesicherter persönlicher Ordner passt nicht zu diesem Host.")
            share = share_map[home["share"]]
            if share["readers"] or set(share["writers"]) - {name}:
                raise Error("Persönliche Ordner dürfen keine fremden Benutzer enthalten.")
        private={home['share'] for home in identity['homes'].values()}
        legacy={user['name'] for user in users if user['system_user']=='titan-files'}
        if (any(set(group['shares'])&private or set(group['members'])&legacy and group['shares'] for group in policy['groups']) or
                any(set(item['shares'])&private or name in legacy and item['shares'] for name,item in policy['users'].items())):
            raise Error("Gesicherte Gruppenrechte dürfen persönliche Ordner oder Dienstidentitäten nicht neu verteilen.")
        datasets = {share.get("dataset") for share in shares if share.get("dataset")}
        for name, quotas in identity["quotas"].items():
            if name not in accounts or not isinstance(quotas, dict) or set(quotas) - datasets or any(type(value) is not int or not 0 <= value < 2**63 for value in quotas.values()):
                raise Error("Gesicherte Benutzerquoten sind ungültig.")
    security = data.get("security")
    if security is not None:
        if not isinstance(security, dict) or set(security) != {"factors", "recoveries"} or not isinstance(security["factors"], list) or not isinstance(security["recoveries"], list):
            raise Error("Ungültige gesicherte Zwei-Faktor-Konfiguration.")
        names, enabled = {user["name"] for user in users}, set()
        seen = set()
        for factor in security["factors"]:
            if (not isinstance(factor, dict) or set(factor) != {"username", "secret", "enabled", "last_counter"} or factor["username"] not in names or factor["username"] in seen or factor["enabled"] not in (0, 1) or type(factor["last_counter"]) is not int or not -1 <= factor["last_counter"] < 2**63 or (factor["enabled"] and not re.fullmatch(r"[A-Z2-7]{32}", str(factor["secret"]))) or (not factor["enabled"] and factor["secret"])):
                raise Error("Gesicherter Authenticator ist ungültig.")
            seen.add(factor["username"])
            if factor["enabled"]: enabled.add(factor["username"])
        seen_codes = set()
        for code in security["recoveries"]:
            if (not isinstance(code, dict) or set(code) != {"username", "digest"} or code["username"] not in enabled or not re.fullmatch(r"[a-f0-9]{64}", str(code["digest"])) or (code["username"], code["digest"]) in seen_codes):
                raise Error("Gesicherter Wiederherstellungscode ist ungültig.")
            seen_codes.add((code["username"], code["digest"]))
    return data


def sqlite_snapshot(source, destination):
    with contextlib.closing(sqlite3.connect(Path(source).as_uri() + "?mode=ro", uri=True)) as original:
        with contextlib.closing(sqlite3.connect(destination)) as copy:
            original.backup(copy)


def database_import(path, data):
    """Restore only allowed records into the current schema; revoke sessions."""
    with contextlib.closing(sqlite3.connect(path)) as db, db:
        from .security import initialize_security
        initialize_security(db)
        db.execute("BEGIN IMMEDIATE")
        columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
        if "enabled" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
        for field in ("display_name", "description"):
            if field not in columns:
                db.execute(f"ALTER TABLE users ADD COLUMN {field} TEXT NOT NULL DEFAULT ''")
        db.execute("DELETE FROM sessions")
        db.execute("DELETE FROM jobs")
        db.execute("DELETE FROM users")
        db.execute("DELETE FROM second_factors")
        db.execute("DELETE FROM recovery_codes")
        # A configuration restore imports policy, never historical lockouts.
        db.execute("DELETE FROM login_protection_failures")
        db.execute("DELETE FROM login_protection_blocks")
        for user in data["users"]:
            db.execute("INSERT INTO users(name,password,role,system_user,enabled,display_name,description) VALUES (?,?,?,?,?,?,?)",
                       (user["name"], user["password"], user["role"], user["system_user"], int(user.get("enabled", 1)),
                        user_profile_text(user.get("display_name", ""), "display_name"),
                        user_profile_text(user.get("description", ""), "description")))
        for factor in data.get("security", {}).get("factors", []):
            db.execute("INSERT INTO second_factors(username,secret,enabled,last_counter) VALUES (?,?,?,?)", (factor["username"], factor["secret"], factor["enabled"], factor["last_counter"]))
        for code in data.get("security", {}).get("recoveries", []):
            db.execute("INSERT INTO recovery_codes VALUES (?,?)", (code["username"], code["digest"]))
        db.execute("DELETE FROM config WHERE key='identity'")
        db.execute("DELETE FROM config WHERE key='login_protection'")
        for key, value in data["config"].items():
            db.execute("INSERT INTO config(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))


def quota_properties(host, desired, previous):
    """Apply the full saved quota state, including clearing newer limits."""
    pairs={(name,target) for state in (desired,previous) for name,limits in state.items() for target in limits}
    known_targets={target for _,target in pairs}
    for name,target in sorted(pairs):
        host._restore_user_quota(name,target,desired.get(name,{}).get(target,0),known_targets)
    # Applying properties must not leave zero-valued entries outside the backup.
    host.save('identity-quotas',desired)


def restore(host, data, db_path, run):
    """Transactional same-host restore. Runner is injected for non-host tests."""
    validate_config(host, data)
    db_path = Path(db_path)
    from .backups import directory_fd
    with directory_fd(db_path.parent):
        if not db_path.is_file() or db_path.is_symlink():
            raise Error("Aktuelle Konfigurationsdatenbank fehlt oder ist unsicher.")
    previous = {key: host.load(key, []) for key in ("accounts", "shares", "apps")}
    previous_identity_users = host.load("identity-users", [])
    previous_identity = {key: host.load("identity" + ("-" + key if key != "policy" else ""), {}) for key in ("policy", "baseline", "homes", "quotas")}
    previous_samba = {item["name"]: host.samba_snapshot(item["name"]) for item in previous["accounts"] if not item.get("removed")}
    previous_conf = host.samba_config.read_text() if host.samba_config.exists() else ""
    stopped, success = [], False
    with tempfile.TemporaryDirectory(prefix="restore-rollback-", dir=host.directory) as temporary:
        snapshot = Path(temporary) / "titan.sqlite3"
        atomic_json(Path(temporary) / "recovery.json", {"agent": previous, "samba": previous_samba, "samba_config": previous_conf})
        try:
            for unit in ("titan-web.service", host_platform().samba_unit):
                stopped.append(unit)
                run(["systemctl", "stop", unit])
            sqlite_snapshot(db_path, snapshot)
            restored_accounts = [{**item, "enabled": item.get("enabled", True)} for item in data["agent"]["accounts"]]
            # Newer accounts retain their UIDs but are disabled. Their filesystem
            # ownership is never reassigned to an older restored account.
            restored_names = {item["name"] for item in restored_accounts}
            restored_accounts += [{**item, "enabled": False} for item in previous["accounts"] if item["name"] not in restored_names]
            known = {item["name"]: item for item in restored_accounts}
            host.save("accounts", restored_accounts)
            desired_shares = data["agent"]["shares"]
            desired_paths = {item["path"] for item in desired_shares}
            # Removed shares also have named access revoked on retained files.
            acl_changes = desired_shares + [{**item, "readers": [], "writers": []} for item in previous["shares"] if item["path"] not in desired_paths]
            def apply_records():
                for line in data["samba"]:
                    host.restore_samba_snapshot(line.split(":", 1)[0], line + "\n")
                for name, account in known.items():
                    if account.get("removed") and name not in previous_samba:
                        continue  # Already absent from the current passdb.
                    run(["smbpasswd", "-e" if account.get("enabled", True) else "-d", name])
                host.samba_config.write_text(host.share_config_text(desired_shares, restored_accounts))
                run(["testparm", "-s", "/etc/samba/smb.conf"])
                host.save("shares", desired_shares)
                restored_apps = data["agent"]["apps"]
                restored_ids = {item["id"] for item in restored_apps}
                host.save("apps", restored_apps + [item for item in previous["apps"] if item["id"] not in restored_ids])
                if "identity" in data:
                    for key, value in data["identity"].items():
                        host.save("identity" + ("-" + key if key != "policy" else ""), value)
                    # Reapply kernel-enforced quotas, never only their saved labels.
                    quota_properties(host,data["identity"]["quotas"],previous_identity["quotas"])
                else:
                    from .identity import empty_policy
                    host.save("identity", empty_policy())
                    host.save("identity-baseline", {})
                    host.save("identity-homes", {})
                    host.save("identity-quotas", {})
                    quota_properties(host,{},previous_identity["quotas"])
                host.save("identity-users", [{"name": user["name"], "system_user": user["system_user"]} for user in data["users"]])
                database_import(db_path, data)
            def transaction(index):
                if index == len(acl_changes):
                    return apply_records()
                share = acl_changes[index]
                host.share_acl_transaction(share, share["readers"], share["writers"], lambda: transaction(index + 1))
            transaction(0)
            success = True
        except Exception as exc:
            rollback_failed = isinstance(exc, Error) and exc.status == 500
            for key, value in previous.items():
                try:
                    host.save(key, value)
                except Exception:
                    rollback_failed = True
            try:
                host.save("identity-users", previous_identity_users)
            except Exception:
                rollback_failed = True
            for key, value in previous_identity.items():
                try:
                    host.save("identity" + ("-" + key if key != "policy" else ""), value)
                    if key == "quotas":
                        # Any newly restored quota is explicitly reset on rollback.
                        quota_properties(host,value,data.get("identity",{}).get("quotas",{}))
                except Exception:
                    rollback_failed = True
            for name, text in previous_samba.items():
                try:
                    host.restore_samba_snapshot(name, text)
                except Exception:
                    rollback_failed = True
            try:
                host.samba_config.write_text(previous_conf)
                if snapshot.exists():
                    with contextlib.closing(sqlite3.connect(snapshot)) as original:
                        with contextlib.closing(sqlite3.connect(db_path)) as destination:
                            original.backup(destination)
            except Exception:
                rollback_failed = True
            # Failed ACL rollback already fail-closes the share transaction. Do
            # not restart SMB if recovery cannot be guaranteed.
            if rollback_failed:
                stopped = [unit for unit in stopped if unit != host_platform().samba_unit]
                # Keep a private recovery copy for a local administrator if the
                # automatic rollback could not restore every affected resource.
                Path(temporary).rename(host.directory / ("restore-recovery-" + str(time.time_ns())))
                raise Error("Konfigurationswiederherstellung und Rücksetzung fehlgeschlagen; SMB bleibt zum Schutz der Daten angehalten.", 500) from None
            raise Error("Konfigurationswiederherstellung fehlgeschlagen; bisherige Einstellungen wurden zurückgesetzt.", 500) from None
        finally:
            # No inode replacement of SQLite: retain the web service's UID/GID.
            os.chmod(db_path, 0o600)
            start_errors = []
            for unit in reversed(stopped):
                try:
                    run(["systemctl", "start", unit])
                except Exception:
                    start_errors.append(unit)
            if start_errors:
                raise Error("Dienste konnten nach der Wiederherstellung nicht gestartet werden: " + ", ".join(start_errors) + ". Dienststatus lokal prüfen.", 503) from None
    return {"ok": success}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticket", required=True)
    args = parser.parse_args()
    if os.geteuid() != 0 or not re.fullmatch(r"[a-f0-9]{32}", args.ticket):
        parser.error("Ein gültiges rootseitiges Wiederherstellungsticket ist erforderlich.")
    from .host import Host, run
    host = Host()
    ticket = host.directory / "restore-tickets" / (args.ticket + ".json")
    marker = host.directory / "config-restore.lock"
    try:
        fd = os.open(ticket, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "r") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > 16 * 1024 ** 2:
                raise Error("Unsicheres Wiederherstellungsticket.")
            value = json.load(stream)
        if value.get("schema") != 1 or not 0 <= time.time() - value.get("created", 0) <= 600 or marker.read_text() != args.ticket:
            raise Error("Wiederherstellungsticket fehlt oder ist abgelaufen.")
        restore(host, value["data"], "/var/lib/titan/titan.sqlite3", run)
        host.save("config-restore-result", {"ok": True, "time": time.time()})
    except Exception:
        # Never record backed-up password hashes or passdb command output.
        host.save("config-restore-result", {"ok": False, "time": time.time(), "error": "Konfigurationswiederherstellung fehlgeschlagen; Dienst- und Freigabestatus prüfen."})
        raise SystemExit(1) from None
    finally:
        ticket.unlink(missing_ok=True)
        if marker.exists() and marker.read_text() == args.ticket:
            marker.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

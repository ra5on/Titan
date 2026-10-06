"""Administrative systemd service inventory and creation of isolated custom units.

Only the system manager is addressed. Existing unit files are never edited.
Current Debian/systemd supplies JSON tables for both inventory commands.
"""
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import stat
import tempfile

from .core import Error, identifier, integer
from .custom_services import read_report as containment_report, unsafe_custom_identity


CUSTOM_PREFIX = "titan-custom-"
PROTECTED_SERVICES = frozenset({"titan-agent.service", "titan-web.service", "titan-proxy.service", "titan-service-containment.service"})
SERVICE_ACTIONS = ("start", "stop", "restart", "reload", "reset-failed", "enable", "disable")
MAX_SERVICES = 2000
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_PROPERTIES_BYTES = 65536
MAX_LOG_BYTES = 65536
UNIT_PROPERTIES = (
    "Id", "Names", "Description", "LoadState", "ActiveState", "SubState", "UnitFileState",
    "MainPID", "ExecMainCode", "ExecMainStatus", "Result", "FragmentPath", "User",
    "WorkingDirectory", "Restart", "ActiveEnterTimestamp", "InactiveEnterTimestamp",
    "CanStart", "CanStop", "CanReload", "NeedDaemonReload", "Transient", "Type",
    "NRestarts", "StatusText", "StatusErrno", "MemoryCurrent", "MemoryPeak",
    "CPUUsageNSec", "TasksCurrent", "TriggeredBy", "Triggers", "Requires", "Wants", "After", "Before", "DefaultDependencies",
)
USER_UNIT_ROOTS = (Path("/etc/systemd/user"), Path("/run/systemd/user"),
                   Path("/usr/lib/systemd/user"), Path("/usr/local/lib/systemd/user"))
_UNIT_NAME = re.compile(r"(?:[A-Za-z0-9:_.@-]|\\x[0-9A-Fa-f]{2})+\.service\Z")
_USER_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}\Z")


def _run(*args, **kwargs):
    from .host import run
    return run(*args, **kwargs)


def _text(value, label, limit, empty=True):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value):
        raise Error(f"{label} ist ungültig oder zu lang.")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise Error(f"{label} enthält Steuerzeichen.")
    return value


def service_name(value):
    value = _text(value, "Dienstname", 255, False)
    if value.startswith("-") or not _UNIT_NAME.fullmatch(value):
        raise Error("Ein vollständiger .service-Dienstname ist erforderlich.")
    return value


def _argv_word(value):
    """Quote argv literals. ExecStart's ':' prefix disables dollar expansion."""
    if value == ";":
        return r"\;"
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def _scalar(value):
    # Description and WorkingDirectory are scalar settings, not argv parsers.
    # Their parser preserves internal spaces/backslashes and expands percent.
    # A final backslash would continue the line at the generic config layer.
    if value != value.strip() or value.endswith("\\"):
        raise Error("Beschreibung und Arbeitsverzeichnis dürfen keine Rand-Leerzeichen oder abschließenden Backslash enthalten.")
    return value.replace("%", "%%")


class ServiceManagerMixin:
    service_unit_root = Path("/etc/systemd/system")

    @staticmethod
    def service_users():
        result = {}
        for account in pwd.getpwall():
            name, uid = account.pw_name, account.pw_uid
            regular = 1000 <= uid < 65534 and account.pw_shell not in ("/bin/false", "/sbin/nologin", "/usr/sbin/nologin")
            if _USER_NAME.fullmatch(name) and (uid > 0 and (name == "titan-files" or regular)):
                result[name] = {"name": name, "uid": uid,
                                "label": name + (" (Administrator)" if uid == 0 else "")}
        return sorted(result.values(), key=lambda item: (item["name"] != "titan-files", item["uid"], item["name"]))

    @staticmethod
    def _service_rows(arguments):
        output = _run(arguments, timeout=30)
        if len(output.encode("utf-8")) > MAX_JSON_BYTES:
            raise Error("systemd-Dienstliste überschreitet die zulässige Größe.", 503)
        try:
            rows = json.loads(output)
        except (ValueError, TypeError):
            raise Error("systemd liefert keine gültige JSON-Dienstliste (aktuelles Titan-Debian-Systemimage erforderlich).", 503) from None
        if not isinstance(rows, list) or len(rows) > 20000 or any(not isinstance(row, dict) for row in rows):
            raise Error("systemd liefert eine ungültige Dienstliste.", 503)
        return rows

    def _service_inventory(self):
        files = self._service_rows(["systemctl", "list-unit-files", "--type=service", "--no-pager", "--no-legend", "--output=json"])
        loaded = self._service_rows(["systemctl", "list-units", "--all", "--type=service", "--no-pager", "--no-legend", "--plain", "--output=json"])
        installed, states = {}, {}
        for rows, key, destination in ((files, "unit_file", installed), (loaded, "unit", states)):
            for row in rows:
                name = row.get(key)
                try:
                    service_name(name)
                except Error:
                    continue
                fields = ("state",) if key == "unit_file" else ("load", "active", "sub", "description")
                if any(not isinstance(row.get(field), str) for field in fields):
                    raise Error("systemd liefert ungültige Dienststatusfelder.", 503)
                destination[name] = row
        return installed, states

    @staticmethod
    def _service_summary(name, installed, states, properties=None, contained=False):
        template = name.split("@", 1)[0] + "@.service" if "@" in name else ""
        unit_file, state = installed.get(name, installed.get(template, {})), states.get(name, {})
        props = properties or {}
        active = props.get("ActiveState", state.get("active", "inactive"))
        aliases = set(props.get("Names", "").split()) | {name, props.get("Id", "")}
        protected = bool(aliases & PROTECTED_SERVICES)
        transient = props["Transient"] == "yes" if props.get("Transient") in ("yes", "no") else name not in installed and template not in installed
        unit_state = props.get("UnitFileState", unit_file.get("state", "transient" if transient else "unknown"))
        actions = list(SERVICE_ACTIONS)
        if props.get("CanReload") != "yes" or active != "active":
            actions.remove("reload")
        if unit_state in ("static", "generated", "transient"):
            actions = [action for action in actions if action not in ("enable", "disable")]
        if unit_state.startswith("masked") or props.get("CanStart") == "no":
            actions = [action for action in actions if action not in ("start", "restart", "reload", "enable")]
        if props.get("CanStop") == "no":
            actions = [action for action in actions if action != "stop"]
        if protected:
            actions = [action for action in actions if action in ("start", "enable")]
        if "@.service" in name:
            actions = [action for action in actions if action in ("enable", "disable")]
        unsafe_custom = contained or bool(properties is not None and unsafe_custom_identity(name, props))
        if unsafe_custom:
            actions = [action for action in actions if action in ("stop", "disable", "reset-failed")]
        return {
            "name": name, "description": props.get("Description", state.get("description", ""))[:1024],
            "load": props.get("LoadState", state.get("load", "not-loaded")), "active": active,
            "sub": props.get("SubState", state.get("sub", "dead")), "unit_file_state": unit_state,
            "preset": unit_file.get("preset") or "", "enabled": unit_state in ("enabled", "enabled-runtime"),
            "installed": name in installed, "transient": transient,
            "custom": name.startswith(CUSTOM_PREFIX), "protected": protected,
            "health": "failed" if active == "failed" else "masked" if unit_state.startswith("masked") else active,
            "result": props.get("Result", ""), "exit_code": props.get("ExecMainStatus", ""),
            "needs_reload": props.get("NeedDaemonReload") == "yes",
            "protected_reason": ("Titan-Verwaltungszugang: Stoppen, Neustarten und Deaktivieren sind hier gesperrt." if protected else
                "Älterer eigener Rootdienst deaktiviert; Start und Autostart benötigen ein unprivilegiertes Datenbenutzerkonto." if unsafe_custom else ""),
            "allowed_actions": actions,
        }

    def op_services(self):
        installed, states = self._service_inventory()
        # Keep installed inactive units and actual running/failed transient units,
        # but omit stale not-found references pulled into systemd by dependencies.
        names = set(installed) | {name for name, row in states.items() if row.get("load") != "not-found" and row.get("active") != "inactive"}
        names = sorted(names, key=lambda name: (states.get(name, {}).get("active") != "failed", not name.startswith(CUSTOM_PREFIX), name.casefold()))
        containment = containment_report()
        contained = {item['name'] for item in containment['blocked_units']} if containment else set()
        summaries = [self._service_summary(name, installed, states, contained=name in contained) for name in names]
        counts = {"total": len(summaries), "active": sum(item["active"] == "active" for item in summaries),
                  "failed": sum(item["active"] == "failed" for item in summaries),
                  "enabled": sum(item["enabled"] for item in summaries), "custom": sum(item["custom"] for item in summaries)}
        return {"items": summaries[:MAX_SERVICES], "counts": counts,
                "users": self.service_users(), "total": len(names), "truncated": len(names) > MAX_SERVICES,
                "custom_prefix": CUSTOM_PREFIX,
                "root_containment": {"verified": containment is not None,
                    "units": containment['blocked_units'] if containment else []}}

    @staticmethod
    def _service_properties(name):
        output = _run(["systemctl", "show", "--no-pager", "--property=" + ",".join(UNIT_PROPERTIES), "--", name], timeout=30)
        if len(output.encode("utf-8")) > MAX_PROPERTIES_BYTES:
            raise Error("systemd-Dienstdetails überschreiten die zulässige Größe.", 503)
        properties = {}
        for line in output.splitlines():
            key, separator, value = line.partition("=")
            if separator and key in UNIT_PROPERTIES:
                properties[key] = value
        if not properties.get("Id") or properties.get("LoadState") == "not-found":
            raise Error("Dienst nicht gefunden.", 404)
        return properties

    def _service_resolve(self, service):
        name = service_name(service)
        installed, states = self._service_inventory()
        if name not in installed and (name not in states or states[name].get("load") == "not-found"):
            raise Error("Dienst ist nicht installiert oder geladen.", 404)
        properties = self._service_properties(name)
        return self._service_summary(name, installed, states, properties), properties

    def op_service_details(self, service, tail=100):
        tail = integer(tail, 0, 500)
        summary, properties = self._service_resolve(service)
        logs, logs_error, truncated = "", "", False
        if tail:
            try:
                logs = _run(["journalctl", "--unit=" + summary["name"], "--lines=" + str(tail),
                             "--no-pager", "--output=short-iso", "--no-full", "--truncate-newline", "--quiet"], timeout=30)
                encoded = logs.encode("utf-8")
                truncated = len(encoded) > MAX_LOG_BYTES
                if truncated:
                    logs = encoded[-MAX_LOG_BYTES:].decode("utf-8", errors="ignore")
            except Error as exc:
                logs_error = str(exc)[-2000:]
        def counter(key):
            value = properties.get(key, "")
            # systemd exposes UINT64_MAX / '[not set]' when accounting is off.
            return int(value) if value.isdecimal() and len(value) <= 20 and int(value) < 2 ** 64 - 1 else None
        cpu = counter("CPUUsageNSec")
        metrics = {"main_pid": counter("MainPID"), "restarts": counter("NRestarts"),
                   "memory_bytes": counter("MemoryCurrent"), "memory_peak_bytes": counter("MemoryPeak"),
                   "cpu_seconds": cpu / 1e9 if cpu is not None else None, "tasks": counter("TasksCurrent")}
        relationships = {key: properties.get(prop, "").split()[:128] for key, prop in (
            ("triggered_by", "TriggeredBy"), ("triggers", "Triggers"), ("requires", "Requires"), ("wants", "Wants"), ("after", "After"), ("before", "Before"))}
        return {"service": {**summary, "properties": properties, "metrics": metrics, "relationships": relationships}, "logs": logs,
                "logs_error": logs_error, "logs_truncated": truncated}

    def op_service_action(self, service, command):
        if not isinstance(command, str) or command not in SERVICE_ACTIONS:
            raise Error("Ungültige Dienstaktion.")
        # Direct calls are serialized as well as Host.dispatch callers.
        with self.lock:
            summary, properties = self._service_resolve(service)
            if command in ("start", "restart", "reload", "enable") and unsafe_custom_identity(summary["name"], properties):
                raise Error("Dieser ältere eigene Dienst benötigt ein Datenbenutzerkonto. root-Dienste können hier nur angehalten oder deaktiviert werden.", 403)
            if command not in summary["allowed_actions"]:
                raise Error(summary["protected_reason"] or "Diese Aktion ist im aktuellen Dienstzustand nicht verfügbar.", 403)
            command_error = ""
            try:
                _run(["systemctl", command, "--", summary["name"]], timeout=60)
            except Error as exc:
                command_error = str(exc)[-4000:]
            try:
                properties = self._service_properties(summary["name"])
            except Error as exc:
                return {"ok": False, "service": summary, "command": command,
                        "error": command_error or "Dienststatus nach der Aktion nicht erreichbar.", "status_error": str(exc)[-2000:]}
            updated = {**summary, "active": properties.get("ActiveState", summary["active"]),
                       "sub": properties.get("SubState", summary["sub"]),
                       "unit_file_state": properties.get("UnitFileState", summary["unit_file_state"])}
            updated["enabled"] = updated["unit_file_state"] in ("enabled", "enabled-runtime")
            updated.update(health="failed" if updated["active"] == "failed" else updated["active"],
                           result=properties.get("Result", ""), exit_code=properties.get("ExecMainStatus", ""),
                           needs_reload=properties.get("NeedDaemonReload") == "yes")
            if command_error:
                return {"ok": False, "service": updated, "command": command, "error": command_error}
            if command in ("start", "restart") and properties.get("ActiveState") == "failed":
                reason = properties.get("Result", "failed")[:80]
                exit_code = properties.get("ExecMainStatus", "")[:20]
                return {"ok": False, "service": updated, "command": command,
                        "error": f"Dienst meldet nach {command} einen Fehler ({reason}, Exit-Status {exit_code or 'unbekannt'}). Status und Protokoll prüfen."}
            return {"ok": True, "service": updated, "command": command}

    def op_service_create(self, name, description, program, args="", user="titan-files",
                          working_directory="", autostart=False, start=False):
        name = identifier(name)
        description = _text(description, "Beschreibung", 512, False)
        program = _text(program, "Programm", 4096, False)
        args = _text(args, "Argumente", 8192)
        user = _text(user, "Benutzer", 64, False)
        working_directory = _text(working_directory, "Arbeitsverzeichnis", 4096)
        if not isinstance(autostart, bool) or not isinstance(start, bool):
            raise Error("Autostart und Start müssen boolesche Werte sein.")
        if user not in {entry["name"] for entry in self.service_users()}:
            raise Error("Dienstbenutzer ist nicht als ausführendes Konto verfügbar.")
        try:
            account = pwd.getpwnam(user)
            if account.pw_uid == 0:
                raise Error("Eigene Dienste dürfen nicht als root auf Systemdateien zugreifen.", 403)
        except KeyError:
            raise Error("Dienstbenutzer existiert nicht mehr.") from None
        path = Path(program)
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            raise Error("Programm muss eine vorhandene, ausführbare Datei mit absolutem Pfad sein.")
        if working_directory and (not Path(working_directory).is_absolute() or not Path(working_directory).is_dir()):
            raise Error("Arbeitsverzeichnis muss ein vorhandenes absolutes Verzeichnis sein.")
        if working_directory and hasattr(self, "storage_locations"):
            self.storage_locations.validate_path(working_directory, purpose="files")
        try:
            argv = shlex.split(args, posix=True)
        except ValueError:
            raise Error("Argumente enthalten unausgeglichene Anführungszeichen.") from None
        if len(argv) > 128:
            raise Error("Höchstens 128 Programmargumente sind zulässig.")
        unit_name = CUSTOM_PREFIX + name + ".service"
        contents = "[Unit]\nDescription=" + _scalar(description) + "\nAfter=network.target\n\n[Service]\nType=simple\nUser=" + user + "\n"
        contents += "NoNewPrivileges=true\nCapabilityBoundingSet=\nProtectSystem=strict\nProtectHome=read-only\nPrivateTmp=true\nProtectKernelTunables=true\nProtectKernelModules=true\nProtectControlGroups=true\nRestrictSUIDSGID=true\n"
        if working_directory:
            contents += "WorkingDirectory=" + _scalar(working_directory) + "\nReadWritePaths=" + _argv_word(working_directory) + "\n"
        contents += "ExecStart=:" + " ".join(_argv_word(word) for word in [program, *argv]) + "\nRestart=on-failure\nRestartSec=5s\n\n[Install]\nWantedBy=multi-user.target\n"
        with self.lock:
            installed, states = self._service_inventory()
            if unit_name in installed or unit_name in states:
                raise Error("Dienstname ist bereits durch eine installierte oder geladene Unit belegt.", 409)
            user_roots = list(USER_UNIT_ROOTS)
            for account in pwd.getpwall():
                home = Path(account.pw_dir)
                if home.is_absolute():
                    user_roots += [home / ".config/systemd/user", home / ".local/share/systemd/user"]
            if any(os.path.lexists(path / unit_name) for path in user_roots):
                raise Error("Dienstname ist bereits durch eine Benutzer-Unit belegt.", 409)
            root = Path(self.service_unit_root)
            descriptor = None
            try:
                descriptor = os.open(root, os.O_DIRECTORY | os.O_NOFOLLOW)
                info = os.fstat(descriptor)
                if not root.is_absolute() or info.st_uid != os.geteuid() or info.st_mode & 0o022:
                    raise Error("Das systemd-Unitverzeichnis ist nicht sicher verwaltet.", 503)
                for existing in (unit_name, unit_name + ".d"):
                    try:
                        os.stat(existing, dir_fd=descriptor, follow_symlinks=False)
                    except FileNotFoundError:
                        pass
                    else:
                        raise Error("Eine Datei, ein symbolischer Link oder eine Zusatzkonfiguration belegt bereits den Dienstnamen.", 409)
                # A private staging directory keeps verification files out of
                # systemd's live search path. Hard-link publication is atomic and
                # cannot replace a concurrent file, directory or dangling link.
                with tempfile.TemporaryDirectory(prefix=".titan-verify-", dir=root) as staging:
                    staged = Path(staging) / unit_name
                    with staged.open("x", encoding="utf-8") as stream:
                        stream.write(contents)
                        stream.flush()
                        os.fsync(stream.fileno())
                    staged.chmod(0o644)
                    _run(["systemd-analyze", "verify", str(staged)], timeout=30)
                    try:
                        os.link(staged, unit_name, dst_dir_fd=descriptor, follow_symlinks=False)
                    except FileExistsError:
                        raise Error("Der Dienstname wurde zwischenzeitlich belegt.", 409) from None
                    os.fsync(descriptor)
            except OSError as exc:
                raise Error("Dienstdatei konnte nicht sicher erstellt werden: " + str(exc), 503) from None
            finally:
                if descriptor is not None:
                    os.close(descriptor)
            result = {"ok": True, "created": True, "service": unit_name,
                      "autostart": False, "start": False}
            # Retain only our newly published unit if systemd rejects a later
            # step. The UI can inspect/retry it; never roll back other services.
            try:
                _run(["systemctl", "daemon-reload"], timeout=30)
                if autostart:
                    _run(["systemctl", "enable", "--", unit_name], timeout=60)
                    result["autostart"] = True
                if start:
                    _run(["systemctl", "start", "--", unit_name], timeout=60)
                    result["start"] = True
                    # Type=simple acknowledges start before exec/application
                    # failure can be known. Surface a failure already reported
                    # by systemd instead of calling a failed new unit healthy.
                    properties = self._service_properties(unit_name)
                    result["details"] = {**self._service_summary(unit_name,
                        {unit_name: {"state": "enabled" if result["autostart"] else "disabled"}}, {}, properties),
                        "properties": properties}
                    if properties.get("ActiveState") == "failed":
                        reason = properties.get("Result", "failed")[:80]
                        exit_code = properties.get("ExecMainStatus", "")[:20]
                        result.update(ok=False, start=False,
                            error=f"Dienst wurde angelegt, aber der Start ist fehlgeschlagen ({reason}, Exit-Status {exit_code or 'unbekannt'}). Status und Protokoll prüfen.")
            except Error as exc:
                result.update(ok=False, error=str(exc)[-4000:])
            return result

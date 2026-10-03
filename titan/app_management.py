"""Lifecycle and diagnostics for Titan' curated, persistent Docker apps."""
import json
import os
import re
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time

from .catalog import APPS, compose, published_ports, validate_options
from .core import Error, atomic_json, integer
from .app_networks import AppNetworkMixin, selection


def _run(*args, **kwargs):
    # Keep host command execution central, including its timeout/error handling.
    from .host import run
    return run(*args, **kwargs)


from .app_devices import AppDevicesMixin, validate as validate_devices, devices as app_devices_inventory


from .app_metrics import AppMetricsMixin


class AppMixin(AppMetricsMixin, AppDevicesMixin, AppNetworkMixin):
    def _app_options(self, app):
        """Secrets stay in a separate owner-only file, never in public records."""
        path = self.directory / "apps" / app / "options.json"
        if not path.exists() and not path.is_symlink():
            return validate_options(app)
        if any(part.is_symlink() for part in (self.directory, path.parent.parent, path.parent)):
            raise Error("App-Einstellungen liegen in einem unsicheren Verzeichnis.", 503)
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor) as stream:
                metadata = os.fstat(stream.fileno())
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077 or metadata.st_size > 65536:
                    raise Error("Private App-Einstellungen haben unsichere Dateirechte.", 503)
                return validate_options(app, json.loads(stream.read(65537)))
        except (OSError, ValueError, TypeError):
            raise Error("Private App-Einstellungen fehlen oder sind ungültig.", 503) from None

    def app_storage_ready(self, app, data=None):
        if app not in APPS:
            raise Error("App-Vorlage ist nicht verfügbar.")
        sources = [data] if data else []
        if not data:
            record = next((item for item in self.load("apps", []) if item["id"] == app), None)
            if record and record.get("data"):
                sources.append(record["data"])
            else:
                path = self.directory / "apps" / app / "compose.json"
                if not path.exists() or path.is_symlink():
                    raise Error("App-Konfiguration fehlt oder ist unsicher.", 503)
                service = json.loads(path.read_text())["services"][app]
                for binding in service.get("volumes", []):
                    source = binding.get("source") if isinstance(binding, dict) else binding.split(":", 1)[0]
                    if source:
                        sources.append(source)
        config = self.directory / "apps" / app / "compose.json"
        if not data and config.exists() and not config.is_symlink():
            definition=json.loads(config.read_text())
            for service in definition.get("services",{}).values():
                for binding in service.get("volumes",[]):
                    source=binding.get("source") if isinstance(binding,dict) else binding.split(":",1)[0]
                    if source and Path(source).is_relative_to(self.directory):
                        relative=Path(source).relative_to(self.directory)
                        descriptor=os.open(self.directory,os.O_DIRECTORY|os.O_NOFOLLOW)
                        try:
                            for component in relative.parts:
                                child=os.open(component,os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=descriptor)
                                os.close(descriptor);descriptor=child
                        except OSError:
                            raise Error("App-Konfigurationsverzeichnis fehlt oder enthält einen symbolischen Link.",503) from None
                        finally: os.close(descriptor)
        for source in sources:
            if self.volume_manager.required_path(source) is not None or Path(source).is_relative_to(self.share_root):
                try:
                    descriptor = self.open_share_root(source)
                except OSError:
                    raise Error("App-Datenverzeichnis fehlt oder enthält einen symbolischen Link.", 503)
                os.close(descriptor)

    @staticmethod
    def _app_directory(path, base, owner=None):
        """Create owned directories without following a writable child symlink."""
        path, base = Path(path), Path(base)
        if not path.is_relative_to(base) or path == base or base.is_symlink():
            raise Error("Unsicherer App-Datenpfad.", 403)
        base.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(base, os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in path.relative_to(base).parts:
                try:
                    os.mkdir(component, 0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(component, os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            if owner is not None:
                os.fchown(descriptor, owner.pw_uid, owner.pw_gid)
        except OSError:
            raise Error("App-Verzeichnis fehlt oder enthält einen symbolischen Link.", 403)
        finally:
            os.close(descriptor)

    def managed_app(self, app):
        if app not in APPS:
            raise Error("App-Vorlage ist nicht verfügbar.")
        record = next((dict(item) for item in self.load("apps", []) if item["id"] == app), None)
        if record is None:
            raise Error("App ist nicht installiert.", 404)
        directory = self.directory / "apps" / app
        path = directory / "compose.json"
        if any(item.is_symlink() for item in (self.directory, directory.parent, directory, path, directory / "config")) or not path.is_file() or not (directory / "config").is_dir():
            raise Error("App-Konfiguration fehlt oder ist unsicher.", 503)
        try:
            definition = json.loads(path.read_text())
            service = definition["services"][app]
            from .host import pwd
            owner = pwd.getpwnam("titan-files")
            network = selection(record.get("network"))
            expected = compose(app, str(directory), owner.pw_uid, owner.pw_gid,
                               integer(record["port"], 1 if network["mode"] == "host" else 1024, 65535),
                               str(record["data"]), self._app_options(app), network, record.get("hardware"))
            # Read recipes from older releases, but prevent Docker from silently
            # creating missing bind directories on an unavailable NAS volume.
            normalized = []
            for binding in service.get("volumes", []):
                if isinstance(binding, str):
                    source, target = binding.split(":")
                    binding = {"type": "bind", "source": source, "target": target,
                               "bind": {"create_host_path": False}}
                    if target == "/config":
                        binding["bind"]["selinux"] = "Z"
                normalized.append(binding)
            service["volumes"] = normalized
            if definition != expected:
                raise Error("App-Konfiguration weicht von der verwalteten Vorlage ab.", 403)
            data = Path(record["data"])
            if not data.is_absolute() or not data.is_relative_to(self.share_root) or data == self.share_root:
                raise Error("App-Daten liegen außerhalb des NAS-Datenbereichs.", 403)
        except (KeyError, TypeError, ValueError):
            raise Error("Ungültige App-Konfiguration.", 503)
        return record

    def _app_container_rows(self):
        output = _run(["docker", "ps", "-a", "--no-trunc", "--format", "{{json .}}"], timeout=30)
        try:
            return [json.loads(line) for line in output.splitlines() if line]
        except ValueError:
            raise Error("Docker liefert einen ungültigen Containerstatus.", 503)

    def _app_container(self, app, record, rows=None, options=None, service_key=None):
        service_key = service_key or app
        if rows is None:
            rows = self._app_container_rows()
        row = next((item for item in rows if item.get("Names") == "titan-" + service_key), None)
        if row is None:
            return None
        identifier = row.get("ID", "")
        if not isinstance(identifier, str) or not identifier or not all(char in "0123456789abcdef" for char in identifier):
            raise Error("Docker liefert eine ungültige Container-ID.", 503)
        try:
            result = json.loads(_run(["docker", "inspect", "--type", "container", identifier], timeout=30))
            container = result[0]
            labels = container.get("Config", {}).get("Labels") or {}
            expected_labels = {"io.titan.managed": "true", "io.titan.app": app,
                               "com.docker.compose.project": "titan-" + app,
                               "com.docker.compose.service": service_key}
            if any(labels.get(key) != value for key, value in expected_labels.items()):
                raise Error("Ein fremder Container belegt den App-Namen. Titan verändert ihn nicht.", 409)
            bindings = {binding["Destination"]: binding["Source"] for binding in container.get("Mounts", [])
                        if binding.get("Type") == "bind"}
            from .host import pwd
            owner = pwd.getpwnam("titan-files")
            options = self._app_options(app) if options is None else options
            network = selection(record.get("network"))
            definition = compose(app, str(self.directory / "apps" / app), owner.pw_uid, owner.pw_gid,
                                 record["port"], record["data"], options, network, record.get("hardware"))["services"][service_key]
            expected_bindings = {binding["target"]: binding["source"] for binding in definition["volumes"]}
            host = container.get("HostConfig", {})
            expected_ports = {f"{item['target']}/{item['protocol']}": {str(item["host"])}
                              for item in published_ports(app, record["port"], options, host_mode=network["mode"] == "host") if "service" not in item or (app if item["service"] == APPS[app]["stack"]["primary"] else app+"-"+item["service"].lower()) == service_key} if network["mode"] != "host" else {}
            actual_ports = {}
            for target, publications in (host.get("PortBindings") or {}).items():
                if any(binding.get("HostIp", "") not in ("", "0.0.0.0", "::") for binding in publications or []):
                    raise Error("Container veröffentlicht Ports außerhalb der verwalteten Vorlage.", 409)
                actual_ports[target] = {str(binding["HostPort"]) for binding in publications or []}
            if (container.get("Name") != "/titan-" + service_key or container.get("Id") != identifier or
                    container.get("Config", {}).get("Image") != definition["image"] or
                    bindings != expected_bindings or actual_ports != expected_ports or
                    len(container.get("Mounts", [])) != len(expected_bindings) or
                    host.get("Privileged") or host.get("CapAdd") or
                    (host.get("Devices") or []) != [{"PathOnHost":v.split(":")[0],"PathInContainer":v.split(":")[1],"CgroupPermissions":v.split(":")[2]} for v in definition.get("devices", [])]):
                raise Error("Container und verwaltete App-Konfiguration stimmen nicht überein.", 409)
            expected_requests=definition.get("deploy",{}).get("resources",{}).get("reservations",{}).get("devices",[])
            requests=host.get("DeviceRequests") or []
            if len(requests)!=len(expected_requests) or any(request.get("Driver")!=expected.get("driver") or request.get("DeviceIDs")!=expected.get("device_ids") or request.get("Capabilities")!=[expected.get("capabilities")] or request.get("Count",0)!=0 or request.get("Options") not in ({},None) for request,expected in zip(requests,expected_requests)): raise Error("GPU-Zuordnung stimmt nicht mit der ausgewählten Hardware überein.",409)
            mode = host.get("NetworkMode")
            if network["mode"] == "host":
                if mode != "host":
                    raise Error("Container verwendet nicht das ausgewählte Host-Netzwerk.", 409)
            elif network["mode"] == "bridge":
                expected_name = network.get("name", "bridge")
                # Compose/Engine versions may retain the immutable network ID
                # as NetworkMode for an external network. Accept only the exact
                # ID pinned in our record; attachment and endpoint ID are still
                # checked independently below.
                accepted_modes = {expected_name}
                if record.get("network_id"):
                    accepted_modes.add(record["network_id"])
                if mode not in accepted_modes or set(container.get("NetworkSettings", {}).get("Networks", {})) != {expected_name}:
                    raise Error("Container verwendet nicht das ausgewählte Bridge-Netzwerk.", 409)
                endpoint = container["NetworkSettings"]["Networks"][expected_name]
                if record.get("network_id") and endpoint.get("NetworkID") != record["network_id"]:
                    # Engine stores the requested endpoint at create, but only
                    # fills NetworkID when allocating it on the first start.
                    # SELinux labeling must inspect that container beforehand.
                    # Do not accept missing operational identity after a start,
                    # or a different nonempty identity, even in state=created.
                    state = container.get("State", {})
                    unallocated = (endpoint.get("NetworkID") == "" and
                                   state.get("Status") == "created" and
                                   state.get("StartedAt") in ("0001-01-01T00:00:00Z", "0001-01-01T00:00:00.000000000Z") and
                                   not any(state.get(flag) for flag in ("Running", "Restarting", "Paused")) and
                                   not endpoint.get("EndpointID"))
                    if not unallocated:
                        raise Error("Container-Netzwerk wurde ersetzt oder stimmt nicht mit der App überein.", 409)
                    # A container created against a removed/replaced network
                    # still has its old name. Recheck the actual selected ID.
                    self._app_network_validate(network, app, record)
                if network.get("ipv4_address"):
                    actual_static = (endpoint.get("IPAMConfig") or {}).get("IPv4Address", "")
                    if actual_static != network["ipv4_address"] or (container.get("State", {}).get("Status") in ("running", "restarting") and endpoint.get("IPAddress") != network["ipv4_address"]):
                        raise Error("Container verwendet nicht die konfigurierte feste IPv4-Adresse.", 409)
            else:
                expected_name = "titan-" + app + "_default"
                attached = container.get("NetworkSettings", {}).get("Networks")
                if mode != expected_name or (attached is not None and set(attached) != {expected_name}):
                    raise Error("Container-Netzwerk weicht von der verwalteten Standardvorlage ab.", 409)
            return container
        except (KeyError, IndexError, TypeError, ValueError):
            raise Error("Docker liefert ungültige App-Details.", 503)

    def _app_container_summary(self, container, record=None, networks=None, addresses=None):
        if container is None:
            return None
        state = container.get("State", {})
        ports = []
        for target, bindings in (container.get("NetworkSettings", {}).get("Ports") or {}).items():
            target_port, protocol = target.split("/", 1)
            for binding in bindings or []:
                ports.append({"host": binding.get("HostIp", ""), "port": int(binding["HostPort"]),
                              "target": int(target_port), "protocol": protocol})
        summary = {"id": container["Id"], "name": container["Name"].lstrip("/"),
                "image": container.get("Config", {}).get("Image", ""),
                "state": state.get("Status", "unknown"), "health": state.get("Health", {}).get("Status", ""),
                "restarts": container.get("RestartCount", 0), "exit_code": state.get("ExitCode", 0),
                "error": state.get("Error", ""), "started": state.get("StartedAt", ""),
                "finished": state.get("FinishedAt", ""), "ports": ports}
        if record is not None:
            summary.update(self._app_address_summary(container, record, networks, addresses))
        return summary

    @staticmethod
    def _app_logs(container, tail):
        # Docker sends application stderr to its own stderr. Merge both streams,
        # spool to disk, and only return a bounded tail rather than env/inspect.
        arguments = ["docker", "logs", "--timestamps", "--tail", str(tail), container["Id"]]
        with tempfile.TemporaryFile() as output:
            try:
                result = subprocess.run(arguments, stdout=output, stderr=subprocess.STDOUT,
                                        timeout=30, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C.UTF-8"})
            except (OSError, subprocess.TimeoutExpired):
                raise Error("App-Protokoll ist momentan nicht erreichbar.", 503)
            output.seek(0, os.SEEK_END)
            length = output.tell()
            output.seek(max(0, length - 512 * 1024))
            text = output.read().decode("utf-8", errors="replace")
            if result.returncode:
                raise Error(text[-4000:] or "App-Protokoll konnte nicht gelesen werden.", 503)
            return ("[Protokoll auf die letzten 512 KiB begrenzt]\n" if length > 512 * 1024 else "") + text

    def docker(self, app, *arguments, timeout=600):
        if arguments and arguments[0] in ("up", "restart", "create"):
            self.app_storage_ready(app)
        record = self.managed_app(app)
        container = self._app_container(app, record)
        if arguments and arguments[0] in ("up", "restart", "create"):
            self.app_devices_ready(record)
            network, _ = self._app_network_validate(record.get("network"), app, record)
            if network["mode"] == "host" and not (container and container.get("State", {}).get("Status") in ("running", "restarting")):
                self._host_ports_available(published_ports(app, record["port"], self._app_options(app), host_mode=True))
        path = self.directory / "apps" / app / "compose.json"
        definition = json.loads(path.read_text())
        rows = self._app_container_rows()
        for service_key in definition["services"]:
            if service_key != app: self._app_container(app,record,rows,service_key=service_key)
        bindings = definition["services"][app]["volumes"]
        if any(isinstance(binding, str) for binding in bindings):
            from .host import pwd
            owner = pwd.getpwnam("titan-files")
            atomic_json(path, compose(app, str(path.parent), owner.pw_uid, owner.pw_gid, record["port"], record["data"], self._app_options(app), record.get("network"), record.get("hardware")))
        def invoke(*options):
            return _run(["docker", "compose", "--project-name", "titan-" + app, "-f", str(path), *options], timeout=timeout)
        try:
            command = arguments[0] if arguments else None
            if command in ("up", "restart", "create"): invoke("config", "--quiet")
            if command in ("up", "restart", "create"):
                # Compose's Mount API drops SELinux Z when create_host_path is
                # false. Keep missing-volume protection and label the verified
                # config using the actual new container MCS before it can run.
                options = [option for option in arguments[1:] if option != "-d"] if command != "restart" else ["--no-recreate"]
                created = invoke("create", *options)
                self._app_private_config_label(app, record)
                if command == "create":
                    return created
                return invoke("restart" if command == "restart" else "start")
            return invoke(*arguments)
        except Error as exc:
            message = str(exc)
            options = self._app_options(app)
            for field in APPS[app].get("install_schema", []):
                if field["type"] == "password" and options.get(field["key"]):
                    value = options[field["key"]]
                    message = message.replace(value.replace("$", "$$"), "[ausgeblendet]").replace(value, "[ausgeblendet]")
            raise Error(message, exc.status) from None

    @staticmethod
    def _app_selinux_active():
        # A mounted but permissive policy still needs labels for later enforcing.
        return Path("/sys/fs/selinux/enforce").exists()

    def _app_private_config_label(self, app, record):
        if not self._app_selinux_active() or not APPS[app].get("config_mount", True):
            return
        container = self._app_container(app, record)
        label = container.get("MountLabel") if container else None
        match = re.fullmatch(r"system_u:object_r:container_file_t:s0:c(0|[1-9][0-9]{0,3}),c(0|[1-9][0-9]{0,3})", label) if isinstance(label, str) else None
        if not match or any(int(value) > 1023 for value in match.groups()) or match[1] == match[2]:
            raise Error("Docker liefert kein gültiges privates SELinux-Label für die App-Konfiguration.", 503)
        # An unchanged `compose create` can leave an existing container running.
        # Quiesce its writer before checking hardlinks or relabeling the tree.
        if container.get("State", {}).get("Status") in ("running", "restarting"):
            _run(["docker", "compose", "--project-name", "titan-" + app, "-f",
                  str(self.directory / "apps" / app / "compose.json"), "stop"], timeout=60)
            stopped = self._app_container(app, record)
            if (not stopped or stopped.get("MountLabel") != label or
                    stopped.get("State", {}).get("Status") not in ("created", "exited", "dead", "paused")):
                raise Error("App ist vor der SELinux-Kennzeichnung nicht sicher gestoppt.", 503)
        root = self.directory / "apps" / app / "config"
        if not self.directory.is_absolute():
            raise Error("App-Konfiguration benötigt einen absoluten lokalen Datenpfad.", 403)
        descriptors, identities = [], []
        try:
            descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.append(descriptor)
            parent = self.directory
            for component in ("apps", app, "config"):
                metadata = os.fstat(descriptor)
                if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
                    raise Error("Elternverzeichnis der App-Konfiguration ist nicht geschützt.", 403)
                identities.append((parent, metadata.st_dev, metadata.st_ino))
                descriptor = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                descriptors.append(descriptor)
                parent /= component
            metadata = os.fstat(descriptor)
            identities.append((root, metadata.st_dev, metadata.st_ino))
            self._app_config_no_hardlinks(descriptor)
            for path, device, inode in identities:
                current = os.stat(path, follow_symlinks=False)
                if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (device, inode):
                    raise Error("App-Konfigurationspfad wurde während der Prüfung verändert.", 409)
            # -P and -h never traverse a nested symlink into another host tree.
            # Do not use /proc/self/fd here: it is itself a symlink under -h.
            _run(["chcon", "--recursive", "--no-dereference", "-P", "--", label, str(root)], timeout=120)
            for path, device, inode in identities:
                current = os.stat(path, follow_symlinks=False)
                if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (device, inode):
                    raise Error("App-Konfigurationspfad wurde während der Kennzeichnung verändert.", 409)
            if os.getxattr(descriptor, "security.selinux").decode().rstrip("\0") != label:
                raise Error("Privates SELinux-Label der App-Konfiguration wurde nicht übernommen.", 503)
        except (OSError, UnicodeDecodeError):
            raise Error("App-Konfiguration kann nicht sicher mit ihrem SELinux-Label versehen werden.", 503) from None
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    @staticmethod
    def _app_config_no_hardlinks(descriptor):
        # A hardlink would label the same inode in a separate NAS directory.
        # App writers are stopped; descriptor traversal never follows symlinks.
        def walk(directory, depth):
            if depth > 128:
                raise Error("App-Konfiguration ist für eine sichere Kennzeichnung zu tief verschachtelt.", 503)
            for name in os.listdir(directory):
                metadata = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if not stat.S_ISDIR(metadata.st_mode) and metadata.st_nlink != 1:
                    raise Error("App-Konfiguration enthält Hardlinks; SELinux-Kennzeichnung bleibt gesperrt.", 403)
                if stat.S_ISDIR(metadata.st_mode):
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    try:
                        walk(child, depth + 1)
                    finally:
                        os.close(child)
        walk(descriptor, 0)

    def _app_record_result(self, app, error=None):
        records = self.load("apps", [])
        for record in records:
            if record["id"] == app:
                record["phase"] = "failed" if error else "ready"
                record["last_error"] = str(error)[-4000:] if error else ""
                record["changed"] = time.time()
        self.save("apps", records)

    def op_apps(self):
        records = [dict(record) for record in self.load("apps", [])]
        if not shutil.which("docker", path="/usr/sbin:/usr/bin:/sbin:/bin"):
            for record in records:
                record.update(state="unavailable", status="Docker ist nicht installiert.")
            return {"installed": records, "available": False, "error": "Docker ist nicht installiert."}
        try:
            _run(["docker", "compose", "version"], timeout=15)
            rows = self._app_container_rows()
        except Error as exc:
            for record in records:
                record.update(state="unavailable", status=str(exc))
            return {"installed": records, "available": False, "error": str(exc)}
        addresses = self._host_addresses()
        try:
            networks = {item["Name"]: item for item in self._docker_networks()}
        except Error:
            networks = None
        for record in records:
            try:
                checked = self.managed_app(record["id"])
                container = self._app_container(record["id"], checked, rows)
                summary = self._app_container_summary(container, checked, networks, addresses)
                record.update(state=summary["state"] if summary else "missing", container=summary)
                record["status"] = (summary["health"] or summary["state"]) if summary else "Container fehlt · Starten erneut versuchen"
                if record.get("last_error"):
                    record["status"] += " · Letzte Aktion fehlgeschlagen"
            except Error as exc:
                record.update(state="blocked", status=str(exc), last_error=str(exc))
        return {"installed": records, "available": True}

    def op_app_details(self, app, tail=150):
        tail = integer(tail, 1, 500)
        record = self.managed_app(app)
        warnings = [record["last_error"]] if record.get("last_error") else []
        container = None
        logs = ""
        try:
            container = self._app_container(app, record)
            summary = self._app_container_summary(container, record)
            if container:
                try:
                    logs = self._app_logs(container, tail)
                except Error as exc:
                    warnings.append(str(exc))
            else:
                warnings.append("Container fehlt. Mit Starten kann die Installation erneut versucht werden.")
            record.update(state=summary["state"] if summary else "missing", status=summary["state"] if summary else "Container fehlt")
        except Error as exc:
            summary = None
            record.update(state="blocked", status=str(exc))
            warnings.append(str(exc))
        return {"app": record, "container": summary, "logs": logs, "warnings": warnings,
                "config_path": str(self.directory / "apps" / app / "config"), "data_path": record["data"]}

    def op_app_hardware(self, app, hardware):
        record=self.managed_app(app)
        self.app_storage_ready(app)
        self._app_network_validate(record.get('network'),app,record)
        inventory=app_devices_inventory();ids=validate_devices(hardware,inventory)
        chosen=[item for item in inventory if item['id'] in ids]
        rows=self._app_container_rows()
        path=self.directory/'apps'/app/'compose.json';old=path.read_bytes();definition=json.loads(old)
        for key in definition['services']:
            container=self._app_container(app,record,rows,service_key=key)
            if container and (container.get('State',{}).get('Running') or container.get('State',{}).get('Status') in ('running','paused','restarting')):raise Error('Die App vor dem Ändern der Geräte stoppen.',409)
        from .host import pwd
        owner=pwd.getpwnam('titan-files')
        proposed=compose(app,str(path.parent),owner.pw_uid,owner.pw_gid,record['port'],record['data'],self._app_options(app),record.get('network'),chosen)
        records=self.load('apps',[]);updated=[{**item,'hardware':chosen} if item['id']==app else item for item in records]
        atomic_json(path,proposed);self.save('apps',updated)
        args=['docker','compose','--project-name','titan-'+app,'-f',str(path)]
        try:
            _run([*args,'config','--quiet'])
            _run([*args,'create','--force-recreate'],timeout=600)
        except Error as exc:
            atomic_json(path,json.loads(old));self.save('apps',records)
            try:_run([*args,'create','--force-recreate'],timeout=600)
            except Error:raise Error('Gerätewechsel und Wiederherstellung fehlgeschlagen. Die vorherige Konfiguration wurde gesichert; App-Status prüfen.',503) from None
            raise Error('Gerätewechsel fehlgeschlagen; vorherige Konfiguration wiederhergestellt.',503) from None
        return {'ok':True,'message':'Gerätezuordnung gespeichert. Die App bleibt gestoppt und kann jetzt gestartet werden.'}

    def op_app_install(self, app, port, share=None, options=None, network=None, hardware=None):
        if app not in APPS:
            raise Error("App-Vorlage nicht gefunden.")
        available_devices=app_devices_inventory()
        hardware_ids=validate_devices(hardware,available_devices)
        hardware=[item for item in available_devices if item["id"] in hardware_ids]
        network = selection(network if network is not None else {"mode": APPS[app].get("default_network","default")})
        port = integer(port, 1 if network["mode"] == "host" else 1024, 65535)
        options = validate_options(app, options)
        records = self.load("apps", [])
        if any(item["id"] == app for item in records):
            raise Error("App ist bereits angelegt. In der App-Verwaltung Starten erneut versuchen.", 409)
        publications = published_ports(app, port, options, host_mode=network["mode"] == "host")
        requested = {item["host"] for item in publications}
        reserved = {5000, 5001}
        for item in records:
            reserved.update(publication["host"] for publication in published_ports(item["id"], item["port"], self._app_options(item["id"]), host_mode=selection(item.get("network"))["mode"] == "host"))
        if requested & reserved:
            raise Error("Port ist bereits für Titan oder eine andere App reserviert.", 409)
        _run(["docker", "compose", "version"], timeout=30)
        rows = self._app_container_rows()
        network, network_id = self._app_network_validate(network, app)
        if network["mode"] == "host":
            self._host_ports_available(publications)
        from .host import pwd
        owner = pwd.getpwnam("titan-files")
        path = self.directory / "apps" / app
        data = self.share_root / "apps" / app
        if share:
            selected = next((item for item in self.op_shares() if item["name"] == share), None)
            if not selected or selected.get("blocked") or "titan-files" not in selected["writers"]:
                raise Error("Die App benötigt eine aktive Freigabe mit Schreibrechten für titan-files.")
            data = Path(selected["path"])
            descriptor = self.open_share_root(data)
            os.close(descriptor)
            self.app_storage_ready(app, str(data))
        record = {"id": app, "name": APPS[app]["name"], "port": port, "scheme": APPS[app].get("scheme", "http"),
                  "data": str(data), "installed": time.time(), "phase": "installing", "last_error": "", "network": network, **({"hardware":hardware} if hardware else {})}
        if network_id:
            record["network_id"] = network_id
        self._app_container(app, record, rows, options)
        proposed = compose(app,str(path),owner.pw_uid,owner.pw_gid,port,str(data),options,network,record.get("hardware"))
        for service_key in proposed["services"]:
            if service_key != app: self._app_container(app,record,rows,options,service_key)
        self._app_directory(path / "config", self.directory, owner)
        if not share:
            self._app_directory(data, self.share_root, owner)
        for service in proposed["services"].values():
            for binding in service["volumes"]:
                source = Path(binding["source"])
                if source.is_relative_to(path / "config") and source != path / "config": self._app_directory(source,self.directory,owner)
        atomic_json(path / "options.json", options)
        atomic_json(path / "compose.json", compose(app, str(path), owner.pw_uid, owner.pw_gid, port, str(data), options, network, record.get("hardware")))
        records.append(record)
        self.save("apps", records)
        try:
            output = self.docker(app, "up", "-d")
        except Exception as exc:
            self._app_record_result(app, exc)
            raise
        self._app_record_result(app)
        return {"ok": True, "output": output}

    def op_app_action(self, app, action):
        if action not in ("start", "stop", "restart", "logs", "remove", "update", "backup"):
            raise Error("Ungültige App-Aktion.")
        if action in ("start", "restart", "update", "backup"):
            self.app_storage_ready(app)
        try:
            if action == "start":
                result = {"output": self.docker(app, "up", "-d")}
            elif action == "restart":
                record = self.managed_app(app)
                if not self._app_container(app, record):
                    raise Error("Container fehlt. Bitte zuerst Starten erneut versuchen.", 409)
                result = {"output": self.docker(app, "restart")}
            elif action == "stop":
                result = {"output": self.docker(app, "stop")}
            elif action == "logs":
                return {"output": self.op_app_details(app)["logs"]}
            elif action == "remove":
                output = self.docker(app, "down")
                self.save("apps", [item for item in self.load("apps", []) if item["id"] != app])
                return {"output": output, "data_retained": True}
            elif action == "update":
                record = self.managed_app(app)
                container = self._app_container(app, record)
                running = bool(container and container.get("State", {}).get("Status") in ("running", "restarting"))
                backup = self.op_app_backup(app)
                self.docker(app, "pull")
                output = self.docker(app, "up", "-d") if running else self.docker(app, "create", "--force-recreate")
                result = {"output": output, "backup": backup, "kept_stopped": not running}
            else:
                return self.op_app_backup(app)
        except Exception as exc:
            if action not in ("logs", "backup"):
                self._app_record_result(app, exc)
            raise
        self._app_record_result(app)
        return result

    def op_app_backup(self, app):
        self.app_storage_ready(app)
        record = self.managed_app(app)
        container = self._app_container(app, record)
        running = bool(container and container.get("State", {}).get("Status") in ("running", "restarting"))
        if container and container.get("State", {}).get("Status") == "paused":
            raise Error("Pausierte App zuerst in Docker fortsetzen oder stoppen.", 409)
        if running:
            self.docker(app, "stop")
        destination = self.directory / "backups"
        destination.mkdir(exist_ok=True, mode=0o700)
        backup = destination / f"{app}-{time.time_ns()}.tar.gz"
        try:
            _run(["tar", "-czf", str(backup), "-C", str(self.directory / "apps"), app], timeout=600)
        except Exception:
            backup.unlink(missing_ok=True)
            raise
        finally:
            if running:
                self.docker(app, "up", "-d")
        return {"path": str(backup), "scope": "App-Konfiguration; Nutzdaten separat sichern.", "kept_stopped": not running}

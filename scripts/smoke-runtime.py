#!/usr/bin/env python3
"""Exercise only the disposable CI guest behind the fixed QEMU port forward."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
from http.cookies import SimpleCookie
import http.client
import ipaddress
import json
import math
import os
from pathlib import Path
import secrets
import shlex
import socket
import ssl
import stat
import struct
import subprocess
import re
import sys
import tempfile
import time
from urllib.parse import quote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from titan.catalog import APPS


class SmokeFailure(Exception):
    """A fixed, credential-free diagnostic suitable for publishing."""

    def __init__(self, message, values=None):
        super().__init__(message)
        self.values = values


def action_label(operation, arguments):
    """Publish only known smoke verbs, never identifiers or arbitrary values."""
    operations = {"app_install", "app_action", "app_network_create", "app_network_remove",
                  "vm_create", "vm_action", "vm_remove", "iso_remove", "share_create", "share_remove", "system_disk_grow"}
    if not isinstance(operation, str) or operation not in operations:
        return "runtime_action"
    allowed = {"app_action": {"start", "stop", "remove"}, "vm_action": {"start", "poweroff"}}
    action = arguments.get("action") if isinstance(arguments, dict) else None
    if isinstance(action, str) and action in allowed.get(operation, set()):
        return operation + "/" + action
    return operation


def error_category(result):
    """Classify a bounded error locally and return a closed, public vocabulary."""
    error = result.get("error") if isinstance(result, dict) else None
    if not isinstance(error, str):
        return "unknown"
    error = error[-4000:].casefold()
    categories = (
        ("registry_rate_limit", ("toomanyrequests", "too many requests", "rate limit")),
        ("registry_auth", ("unauthorized", "authentication required", "pull access denied",
                           "requested access to the resource is denied")),
        ("disk_space", ("no space left on device", "disk quota exceeded")),
        ("port_conflict", ("port is already allocated", "address already in use")),
        ("bind_mount", ("invalid mount config", "bind source path does not exist",
                        "error while creating mount source path", "failed to mount", "mount callback failed",
                        "selinux relabeling", "selinux relabelling")),
        ("registry_network", ("no such host", "tls handshake timeout", "tls handshake failure", "x509:",
                              "dial tcp", "connection reset by peer", "i/o timeout")),
        ("container_runtime", ("oci runtime create failed", "failed to create task for container",
                               "failed to create shim task", "cannot connect to the docker daemon",
                               "error during connect")),
        ("config_validation", ("additional property", "validating ",
                               "app-konfiguration weicht von der verwalteten vorlage ab",
                               "container und verwaltete app-konfiguration stimmen nicht überein")),
        ("app_network_validation", ("container-netzwerk weicht von der verwalteten standardvorlage ab",
                                    "container verwendet nicht das ausgewählte",
                                    "container-netzwerk wurde ersetzt",
                                    "container verwendet nicht die konfigurierte feste ipv4-adresse")),
        ("selinux_label", ("docker liefert kein gültiges privates selinux-label",
                           "app-konfiguration kann nicht sicher mit ihrem selinux-label",
                           "privates selinux-label der app-konfiguration wurde nicht übernommen")),
        ("config_parent_permissions", ("elternverzeichnis der app-konfiguration ist nicht geschützt",)),
        ("config_unsafe_path", ("app-konfiguration fehlt oder ist unsicher",
                               "app-einstellungen liegen in einem unsicheren verzeichnis",
                               "app-verzeichnis fehlt oder enthält einen symbolischen link",
                               "app-konfigurationspfad wurde während",
                               "app-konfiguration enthält hardlinks")),
        ("docker_api_schema", ("docker liefert ungültige app-details", "docker liefert eine ungültige container-id",
                               "docker liefert einen ungültigen containerstatus", "docker liefert einen ungültigen netzwerkstatus")),
        ("filesystem_permissions", ("permission denied", "operation not permitted", "read-only file system")),
        ("command_timeout", ("antwortet nicht innerhalb von",)),
        ("missing_component", (" ist nicht installiert.",)),
        ("service_identity", ("getpwnam(): name not found: 'titan-files'",)),
    )
    for category, patterns in categories:
        if any(pattern in error for pattern in patterns):
            return category
    return "unknown"


def app_observation(details):
    """Keep fixed states/counters and log categories; discard all raw details."""
    if not isinstance(details, dict):
        return {"available": False}
    container = details.get("container")
    container = container if isinstance(container, dict) else {}
    app = details.get("app")
    app = app if isinstance(app, dict) else {}
    state = container.get("state", app.get("state"))
    states = {"running", "restarting", "exited", "created", "dead", "paused", "missing", "blocked"}
    state = state if isinstance(state, str) and state in states else "unknown"
    health = container.get("health")
    health = health if isinstance(health, str) and health in {"healthy", "unhealthy", "starting", ""} else "unknown"
    ports = container.get("ports")
    ports = ports if isinstance(ports, list) else []
    published = any(isinstance(item, dict) and item.get("port") == 18080 and
                    item.get("target") == 80 and item.get("protocol") == "tcp" for item in ports[:128])
    logs = details.get("logs")
    logs = logs[-8192:].casefold() if isinstance(logs, str) else ""
    patterns = (
        ("permission_error", ("permission denied", "operation not permitted", "read-only file system")),
        ("nginx_error", ("nginx: [emerg]", "nginx: [error]", "nginx configuration test failed")),
        ("php_error", ("php fatal error", "php parse error", "failed to connect to php")),
        ("database_error", ("sqlstate[", "database is locked", "unable to open database")),
        ("service_start_error", ("unable to start service", "exited with code", "failed with result")),
        ("startup_complete", ("[ls.io-init] done", "ready to handle connections")),
    )
    result = {"available": True, "state": state, "health": health,
              "port_18080_tcp_to_80": published,
              "runtime_error_category": error_category({"error": container.get("error")}),
              "last_error_category": error_category({"error": app.get("last_error")}),
              "log_categories": [category for category, markers in patterns if any(marker in logs for marker in markers)]}
    errors = "\n".join(line for line in logs.splitlines() if any(marker in line for marker in (
        "permission denied", "operation not permitted", "read-only file system", "unable to start service", "exited with code")))
    services = ("init-adduser", "init-envfile", "init-folders", "init-keygen", "init-nginx", "init-php",
                "init-permissions", "init-samples", "init-version-checks", "init-heimdall-config",
                "svc-nginx", "svc-php-fpm", "svc-queue")
    operations = ("mkdir", "chown", "chmod", "lsiown", "cp", "ln", "mv", "install", "rm", "exec", "open", "write",
                  "s6-setuidgid", "s6-applyuidgid")
    result["failed_services"] = [name for name in services if re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", errors)]
    result["error_operations"] = [name for name in operations if re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", errors)]
    result["error_path_scopes"] = [scope for scope in ("/config", "/run", "/app", "/etc", "/var", "/tmp")
                                    if re.search(r"(?:^|[\s'\"(])" + re.escape(scope) + r"(?=/|[\s'\":]|$)", errors)]
    for field, maximum in (("restarts", 10**9), ("exit_code", 255)):
        value = container.get(field)
        result[field] = value if type(value) is int and 0 <= value <= maximum else None
    return result


GUEST_DIAGNOSTIC = r'''
import json,os,pwd,re,stat,subprocess
from pathlib import Path
out={"available":True}
path="/var/lib/titan-agent/apps/heimdall/config"
try:
    metadata=os.stat(path,follow_symlinks=False)
    owner=pwd.getpwnam("titan-files")
    out.update(config_mode=stat.S_IMODE(metadata.st_mode),config_owner_matches=metadata.st_uid==owner.pw_uid,
               config_group_matches=metadata.st_gid==owner.pw_gid,config_is_symlink=stat.S_ISLNK(metadata.st_mode))
except Exception: pass
try:
    out["config_parents_protected"]=all(
        stat.S_ISDIR(metadata.st_mode) and metadata.st_uid==0 and not metadata.st_mode & 0o022
        for metadata in (os.stat(value,follow_symlinks=False) for value in (
            "/var/lib/titan-agent","/var/lib/titan-agent/apps","/var/lib/titan-agent/apps/heimdall")))
except Exception: pass
try:
    out["selinux_enforcing"]=Path("/sys/fs/selinux/enforce").read_text().strip()=="1"
    label=os.getxattr(path,"security.selinux",follow_symlinks=False).decode().rstrip("\0")
    parts=label.split(":")
    allowed={"container_file_t","container_var_lib_t","var_lib_t","default_t","unlabeled_t","titan_share_t"}
    out["config_selinux_type"]=parts[2] if len(parts)>2 and parts[2] in allowed else "other"
except Exception: pass
try:
    command=subprocess.run(["docker","inspect","--type","container","titan-heimdall"],capture_output=True,text=True,timeout=8)
    out["container_present"]=command.returncode==0
    value=json.loads(command.stdout)[0] if command.returncode==0 else {}
    state=value.get("State",{}).get("Status","")
    out["container_state"]=state if state in {"running","restarting","exited","created","dead","paused"} else "missing" if not value else "unknown"
    host=value.get("HostConfig",{})
    mode=host.get("NetworkMode","")
    out["network_mode_category"]=("compose_default" if mode=="titan-heimdall_default" else
        "builtin_bridge" if mode=="bridge" else "host" if mode=="host" else
        "network_id" if isinstance(mode,str) and re.fullmatch(r"[a-f0-9]{12,64}",mode) else "other" if mode else "absent")
    attached=value.get("NetworkSettings",{}).get("Networks") or {}
    out["attached_network_category"]="compose_default" if set(attached)=={"titan-heimdall_default"} else "other" if attached else "none"
    out["network_mode_matches_attached_id"]=any(mode==network.get("NetworkID") for network in attached.values())
    out["attached_network_ids_present"]=bool(attached) and all(
        isinstance(network.get("NetworkID"),str) and re.fullmatch(r"[a-f0-9]{12,64}",network["NetworkID"]) is not None
        for network in attached.values())
    out["smoke_static_ipv4_configured"]=any((network.get("IPAMConfig") or {}).get("IPv4Address")=="172.30.241.10"
        for network in attached.values())
    config=value.get("Config",{})
    labels=config.get("Labels") or {}
    out["container_identity_matches"]=(value.get("Name")=="/titan-heimdall" and
        config.get("Image")=="lscr.io/linuxserver/heimdall:latest" and
        all(labels.get(key)==expected for key,expected in {
            "io.titan.managed":"true","io.titan.app":"heimdall",
            "com.docker.compose.project":"titan-heimdall","com.docker.compose.service":"heimdall"}.items()))
    bindings=host.get("PortBindings") or {}
    out["container_ports_match"]=(set(bindings)=={"80/tcp"} and
        {str(item.get("HostPort")) for item in bindings.get("80/tcp",[]) or []}=={"18080"} and
        all(item.get("HostIp","") in ("","0.0.0.0","::") for item in bindings.get("80/tcp",[]) or []))
    out["container_has_extra_privileges"]=bool(host.get("Privileged") or host.get("Devices") or host.get("CapAdd"))
    mounts=value.get("Mounts") or []
    out["container_mounts_match"]=(len(mounts)==1 and mounts[0].get("Type")=="bind" and
        mounts[0].get("Destination")=="/config" and mounts[0].get("Source")==path)
    mount_label=value.get("MountLabel","")
    match=re.fullmatch(r"system_u:object_r:container_file_t:s0:c(0|[1-9][0-9]{0,3}),c(0|[1-9][0-9]{0,3})",mount_label) if isinstance(mount_label,str) else None
    out["mount_label_valid"]=bool(match and all(int(part)<=1023 for part in match.groups()) and match[1]!=match[2])
    mount=value.get("MountLabel","").split(":")
    out["mount_label_container_file"]=len(mount)>2 and mount[2]=="container_file_t"
    try: out["config_mcs_matches_mount"]=len(parts)>3 and len(mount)>3 and parts[3:]==mount[3:]
    except NameError: pass
    out["config_is_expected_bind"]=any(item.get("Destination")=="/config" and item.get("Source")==path for item in value.get("Mounts",[]))
except Exception: pass
try:
    command=subprocess.run(["curl","--silent","--show-error","--noproxy","*","--connect-timeout","2","--max-time","5",
                            "--output","/dev/null","--write-out","%{http_code} %{content_type}","http://127.0.0.1:18080/"],
                           capture_output=True,text=True,timeout=7)
    code,mime=(command.stdout.strip().split(" ",1)+[""])[:2]
    out["http_status"]=int(code) if code.isdigit() and 100<=int(code)<=599 else None
    mime=mime.partition(";")[0].strip().lower()
    out["content_type"]=mime if mime in {"text/html","text/plain","application/json","application/octet-stream"} else "other"
    out["curl_category"]={0:"http_response",7:"connection_refused",28:"timeout",52:"empty_reply",56:"connection_reset"}.get(command.returncode,"curl_error")
except Exception: out["curl_category"]="unavailable"
print("TITAN_SMOKE_DIAGNOSTIC:"+json.dumps(out,separators=(",",":")))
'''


def guest_observation(value):
    """Validate even the trusted guest result before adding it to artifacts."""
    if not isinstance(value, dict):
        return {"available": False}
    result = {"available": value.get("available") is True}
    for key in ("config_owner_matches", "config_group_matches", "config_is_symlink", "selinux_enforcing",
                "mount_label_container_file", "config_mcs_matches_mount", "config_is_expected_bind",
                "config_parents_protected", "container_present", "container_identity_matches", "container_ports_match",
                "container_has_extra_privileges", "container_mounts_match", "mount_label_valid", "network_mode_matches_attached_id",
                "attached_network_ids_present", "smoke_static_ipv4_configured"):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    for key, allowed in (("config_selinux_type", {"container_file_t", "container_var_lib_t", "var_lib_t", "default_t", "unlabeled_t", "titan_share_t", "other"}),
                         ("content_type", {"text/html", "text/plain", "application/json", "application/octet-stream", "other"}),
                         ("curl_category", {"http_response", "connection_refused", "timeout", "empty_reply", "connection_reset", "curl_error", "unavailable"}),
                         ("container_state", {"running", "restarting", "exited", "created", "dead", "paused", "missing", "unknown"}),
                         ("network_mode_category", {"compose_default", "builtin_bridge", "host", "network_id", "other", "absent"}),
                         ("attached_network_category", {"compose_default", "other", "none"})):
        fallback = {"curl_category": "unavailable", "container_state": "unknown"}.get(key, "other")
        result[key] = value.get(key) if isinstance(value.get(key), str) and value[key] in allowed else fallback
    mode, status = value.get("config_mode"), value.get("http_status")
    result["config_mode"] = mode if type(mode) is int and 0 <= mode <= 0o7777 else None
    result["http_status"] = status if type(status) is int and 100 <= status <= 599 else None
    return result


class VNCWebSocket:
    """Bounded binary WebSocket reader for a single RFB setup, without logs."""

    LIMIT = 1024 * 1024

    def __init__(self, transport, deadline, pending=b""):
        self.transport, self.deadline = transport, deadline
        self.pending, self.rfb = bytearray(pending), bytearray()
        self.frames, self.received, self.fragment = 0, 0, False

    def raw(self, count):
        while len(self.pending) < count:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise SmokeFailure("VM console exceeded its bounded handshake deadline.")
            self.transport.settimeout(min(10, remaining))
            data = self.transport.recv(min(65536, count - len(self.pending)))
            if not data:
                raise SmokeFailure("VM console closed before RFB setup completed.")
            self.pending.extend(data)
        result = bytes(self.pending[:count])
        del self.pending[:count]
        return result

    def send(self, data, opcode=2):
        if len(data) > 125:
            raise SmokeFailure("Invalid bounded console client frame.")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise SmokeFailure("VM console exceeded its bounded handshake deadline.")
        self.transport.settimeout(min(10, remaining))
        mask = secrets.token_bytes(4)
        payload = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
        self.transport.sendall(bytes([0x80 | opcode, 0x80 | len(data)]) + mask + payload)

    def frame(self):
        self.frames += 1
        if self.frames > 128:
            raise SmokeFailure("VM console exceeded the bounded frame count.")
        first, second = self.raw(2)
        final, opcode, length = bool(first & 0x80), first & 15, second & 127
        if first & 0x70 or second & 0x80:
            raise SmokeFailure("VM console returned invalid WebSocket frame flags.")
        if length == 126:
            length = struct.unpack("!H", self.raw(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self.raw(8))[0]
        self.received += length
        if length > self.LIMIT or self.received > self.LIMIT:
            raise SmokeFailure("VM console exceeded the bounded frame size.")
        if opcode >= 8 and (not final or length > 125):
            raise SmokeFailure("VM console returned an invalid control frame.")
        data = self.raw(length)
        if opcode == 9:
            self.send(data, opcode=10)
            return
        if opcode == 10:
            return
        if opcode == 8:
            raise SmokeFailure("VM console closed before RFB setup completed.")
        if opcode == 2 and not self.fragment:
            self.fragment = not final
        elif opcode == 0 and self.fragment:
            self.fragment = not final
        else:
            raise SmokeFailure("VM console did not return a binary RFB stream.")
        self.rfb.extend(data)

    def read(self, count):
        while len(self.rfb) < count:
            self.frame()
        result = bytes(self.rfb[:count])
        del self.rfb[:count]
        return result

    def handshake(self):
        if self.read(12) != b"RFB 003.008\n":
            raise SmokeFailure("VM console did not provide the expected RFB 3.8 protocol.")
        self.send(b"RFB 003.008\n")
        count = self.read(1)[0]
        if count == 0 or 1 not in self.read(count):
            raise SmokeFailure("VM console requires unsupported RFB authentication.")
        # Access is authenticated by the administrator session at the Titan
        # proxy; the underlying VNC listener is restricted to guest loopback.
        self.send(b"\x01")
        if self.read(4) != bytes(4):
            raise SmokeFailure("VM console rejected RFB security negotiation.")
        self.send(b"\x01")
        info = self.read(24)
        width, height = struct.unpack("!HH", info[:4])
        name_length = struct.unpack("!I", info[20:24])[0]
        if not (1 <= width <= 16384 and 1 <= height <= 16384 and
                info[4] in (8, 16, 32) and 1 <= info[5] <= info[4] and name_length <= 4096):
            raise SmokeFailure("VM console returned invalid RFB display metadata.")
        self.read(name_length)
        return {"rfb_protocol": "3.8", "display_width": width, "display_height": height}


class DisposableDiskGrowth:
    """Resize only this smoke's private, named QCOW overlay through QMP."""

    INITIAL = 32 * 1024**3
    EXPANDED = 36 * 1024**3

    def __init__(self, path):
        self.path = Path(path) if path is not None else None

    def grow(self):
        path = self.path
        try:
            if (path is None or not path.is_absolute() or path.name != "qmp.sock" or path.parent.parent != Path("/tmp") or
                    not re.fullmatch(r"titan-image-smoke\.[a-zA-Z0-9_-]{8,64}", path.parent.name)):
                raise SmokeFailure("System-disk smoke requires its own private QMP socket.")
            directory, endpoint = path.parent.lstat(), path.lstat()
            overlay = path.parent / "test.qcow2"
            image = overlay.lstat()
            if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.geteuid() or directory.st_mode & 0o077 or
                    not stat.S_ISSOCK(endpoint.st_mode) or endpoint.st_uid != os.geteuid() or
                    not stat.S_ISREG(image.st_mode) or image.st_uid != os.geteuid()):
                raise SmokeFailure("System-disk smoke QMP or overlay identity is unsafe.")
            deadline = time.monotonic() + 15
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(5)
                connection.connect(str(path))
                with connection.makefile("rb") as stream:
                    def read():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise SmokeFailure("Disposable QMP growth exceeded its bounded deadline.")
                        connection.settimeout(min(5, remaining))
                        line = stream.readline(65537)
                        if not line or len(line) > 65536 or not line.endswith(b"\n"):
                            raise SmokeFailure("Disposable QMP returned an invalid bounded message.")
                        value = json.loads(line)
                        if not isinstance(value, dict):
                            raise SmokeFailure("Disposable QMP returned an invalid message.")
                        return value

                    def command(operation, identifier, arguments=None):
                        request = {"execute": operation, "id": identifier}
                        if arguments is not None:
                            request["arguments"] = arguments
                        connection.sendall(json.dumps(request, separators=(",", ":")).encode() + b"\n")
                        for _ in range(16):
                            value = read()
                            if "event" in value:
                                continue
                            if value.get("id") != identifier or "error" in value or "return" not in value:
                                raise SmokeFailure("Disposable QMP command failed or returned a mismatched response.")
                            return value["return"]
                        raise SmokeFailure("Disposable QMP exceeded its event count.")

                    def disk(value, expected_size):
                        rows = [item for item in value if isinstance(item, dict) and item.get("device") == "titan-system"] if isinstance(value, list) else []
                        inserted = rows[0].get("inserted") if len(rows) == 1 else None
                        details = inserted.get("image") if isinstance(inserted, dict) else None
                        if (not isinstance(details, dict) or inserted.get("ro") is not False or
                                inserted.get("drv") != "qcow2" or inserted.get("file") != str(overlay) or
                                inserted.get("backing_file_depth") != 1 or details.get("format") != "qcow2" or
                                type(details.get("virtual-size")) is not int or details["virtual-size"] != expected_size):
                            raise SmokeFailure("Disposable QMP system drive differs from the expected overlay and capacity.")

                    if not isinstance(read().get("QMP"), dict):
                        raise SmokeFailure("Disposable QMP greeting is unavailable.")
                    command("qmp_capabilities", 1)
                    disk(command("query-block", 2), self.INITIAL)
                    command("block_resize", 3, {"device": "titan-system", "size": self.EXPANDED})
                    disk(command("query-block", 4), self.EXPANDED)
            current = overlay.lstat()
            if (current.st_dev, current.st_ino) != (image.st_dev, image.st_ino):
                raise SmokeFailure("Disposable system overlay identity changed during growth.")
        except SmokeFailure:
            raise
        except (OSError, ValueError, TypeError):
            raise SmokeFailure("Disposable QMP growth is unavailable or returned invalid data.") from None
        return {"overlay_grown": True, "virtual_size_before": self.INITIAL, "virtual_size_after": self.EXPANDED}


class GuestClient:
    HOST = "10.0.2.15:5000"
    ORIGIN = "https://" + HOST

    def __init__(self, qmp_socket=None):
        # The certificate is generated within the throwaway guest. Verification
        # is disabled for this one loopback transport, never a configurable URL.
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.context.check_hostname = False
        self.context.verify_mode = ssl.CERT_NONE
        self.cookie, self.csrf = "", ""
        self.qmp_socket = qmp_socket

    def grow_disposable_system_disk(self):
        return DisposableDiskGrowth(self.qmp_socket).grow()

    def request(self, path, body=None, expected_status=None):
        if not path.startswith("/api/") or "\r" in path or "\n" in path:
            raise SmokeFailure("Invalid test API route.")
        connection = http.client.HTTPSConnection("127.0.0.1", 15000, timeout=30, context=self.context)
        headers = {"Host": self.HOST, "Origin": self.ORIGIN, "Content-Type": "application/json"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        payload = json.dumps(body).encode() if body is not None else None
        try:
            connection.request("POST" if body is not None else "GET", path, payload, headers)
            response = connection.getresponse()
            data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise SmokeFailure("Test API response exceeds the bounded size.")
            if (expected_status is not None and response.status != expected_status or
                    expected_status is None and not 200 <= response.status < 300):
                raise SmokeFailure(f"Test API returned HTTP {response.status}.")
            cookie = response.getheader("Set-Cookie")
            if cookie:
                parsed = SimpleCookie()
                parsed.load(cookie)
                if "titan_session" in parsed:
                    self.cookie = "titan_session=" + parsed["titan_session"].value
            try:
                return json.loads(data)
            except (ValueError, UnicodeDecodeError):
                raise SmokeFailure("Test API returned invalid JSON.") from None
        except (OSError, http.client.HTTPException):
            raise SmokeFailure("Disposable guest API is not reachable.") from None
        finally:
            connection.close()

    def action(self, operation, arguments, timeout=300):
        label = action_label(operation, arguments)
        response = self.request("/api/actions", {"operation": operation, "arguments": arguments})
        return self.wait_job(response, label, timeout)

    def user_create(self, name, password):
        response = self.request("/api/users", {"name": name, "password": password, "role": "user"})
        return self.wait_job(response, "account_create")

    def user_remove(self, name):
        response = self.request("/api/users/remove", {"name": name, "confirmation": name})
        return self.wait_job(response, "user_remove")

    def wait_job(self, response, label, timeout=300):
        identifier = response.get("job") if isinstance(response, dict) else None
        if not isinstance(identifier, str) or not identifier:
            raise SmokeFailure("Action did not return a job identifier.")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            jobs = self.request("/api/jobs")
            if not isinstance(jobs, list):
                raise SmokeFailure("Job API returned an invalid job list.")
            job = next((item for item in jobs if item.get("id") == identifier), None)
            if job is not None:
                if job.get("status") == "failed":
                    # Never publish job outputs: image pull logs and application
                    # logs are unnecessary evidence and can contain secrets.
                    category = error_category(job.get("result"))
                    values = None
                    if label == "app_install":
                        values = {"error_category": category}
                        try:
                            values["app"] = app_observation(self.request("/api/app-details?app=heimdall&tail=50"))
                        except Exception:
                            values["app"] = {"available": False}
                        try:
                            values["guest"] = self.guest_diagnostic()
                        except Exception:
                            values["guest"] = {"available": False}
                    raise SmokeFailure(f"Queued runtime action failed. Operation: {label}; category: {category}.", values)
                if job.get("status") == "completed":
                    result = job.get("result")
                    if not isinstance(result, dict) or result.get("ok") is False:
                        raise SmokeFailure("Runtime action returned an invalid result.")
                    return result
            time.sleep(2)
        raise SmokeFailure("Runtime action exceeded the five-minute job deadline.")

    @staticmethod
    def smb_access(writer, reader, outsider, share):
        """Real SMB against only the disposable guest's fixed port forward."""
        if not isinstance(share, str) or not re.fullmatch(r"smoke-share-[a-f0-9]{8}", share):
            raise SmokeFailure("SMB smoke requires its own test share.")
        for identity in (writer, reader, outsider):
            if (not isinstance(identity, tuple) or len(identity) != 2 or not isinstance(identity[0], str) or
                    not re.fullmatch(r"smoke(?:-[rn])?-[a-f0-9]{8}", identity[0]) or
                    not isinstance(identity[1], str) or not identity[1] or len(identity[1]) > 256 or
                    any(char in identity[1] for char in ("\r", "\n", "\x00"))):
                raise SmokeFailure("SMB smoke requires disposable test identities.")
        payload = b"Titan disposable SMB writer and reader proof.\n"
        with tempfile.TemporaryDirectory(prefix="titan-smb-", dir="/tmp") as directory:
            root = Path(directory)
            upload, writer_download, reader_download = root / "upload.txt", root / "writer.txt", root / "reader.txt"
            upload.write_bytes(payload)
            authentication = []
            for index, (name, password) in enumerate((writer, reader, outsider)):
                path = root / (str(index) + ".auth")
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w") as stream:
                    stream.write("username = " + name + "\npassword = " + password + "\ndomain = WORKGROUP\n")
                authentication.append(path)

            def invoke(index, command=None, listing=False, retry=False):
                arguments = ["smbclient", "-L", "127.0.0.1", "-g"] if listing else ["smbclient", "//127.0.0.1/" + share]
                arguments += ["-I", "127.0.0.1", "-p", "15445", "-m", "SMB3", "-t", "8", "-A", str(authentication[index])]
                if command is not None:
                    arguments += ["-c", command]
                for attempt in range(3 if retry else 1):
                    try:
                        result = subprocess.run(arguments, capture_output=True, text=True, timeout=15,
                            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C.UTF-8"})
                    except subprocess.TimeoutExpired:
                        raise SmokeFailure("SMB request exceeded its bounded deadline.") from None
                    except OSError:
                        raise SmokeFailure("Disposable runner SMB client is unavailable.") from None
                    # Never publish these diagnostics, even for failed logins.
                    output = (result.stdout or "") + (result.stderr or "")
                    if len(output) > 128 * 1024:
                        raise SmokeFailure("SMB response exceeds the bounded diagnostic size.")
                    transport = any(marker in output for marker in ("NT_STATUS_CONNECTION_REFUSED", "NT_STATUS_IO_TIMEOUT",
                        "NT_STATUS_CONNECTION_DISCONNECTED", "NT_STATUS_HOST_UNREACHABLE"))
                    if result.returncode and transport and retry and attempt < 2:
                        time.sleep(1)
                        continue
                    return result.returncode, output
                raise SmokeFailure("SMB transport retry bound was exceeded.")

            status, _ = invoke(0, f'put "{upload}" smoke.txt; get smoke.txt "{writer_download}"', retry=True)
            if status != 0 or not writer_download.is_file() or writer_download.read_bytes() != payload:
                raise SmokeFailure("SMB writer authentication, upload or downloaded file content failed.")
            status, _ = invoke(1, f'get smoke.txt "{reader_download}"')
            if status != 0 or not reader_download.is_file() or reader_download.read_bytes() != payload:
                raise SmokeFailure("SMB read-only account could not download the writer's exact file content.")
            status, output = invoke(1, f'put "{upload}" denied.txt')
            if status == 0 or not any(marker in output for marker in ("NT_STATUS_ACCESS_DENIED", "NT_STATUS_MEDIA_WRITE_PROTECTED")):
                raise SmokeFailure("SMB read-only account did not receive an explicit write denial.")
            status, output = invoke(2, "ls")
            if status == 0 or "NT_STATUS_ACCESS_DENIED" not in output:
                raise SmokeFailure("SMB account without share rights did not receive an explicit connection denial.")
            status, output = invoke(2, listing=True)
            if status != 0 or any(line.split("|")[1:2] == [share] for line in output.splitlines()):
                raise SmokeFailure("SMB share enumeration exposed the private test share to an unauthorized account.")
            status, _ = invoke(0, "del smoke.txt")
            if status != 0:
                raise SmokeFailure("SMB writer could not remove its own test file.")
        return {"writer_read_write": True, "downloaded_content_matches": True,
                "reader_read": True, "reader_write_denied": True, "unauthorized_connect_denied": True,
                "unauthorized_share_hidden": True, "test_file_removed": True}

    def app_http_ready(self, timeout=120):
        """Only the fixed Heimdall publication in this disposable guest."""
        deadline = time.monotonic() + timeout
        observed = {"last_http_status": None, "last_content_type": "unavailable",
                    "last_transport": "unavailable", "response_category": "unavailable"}
        while time.monotonic() < deadline:
            connection = http.client.HTTPConnection("127.0.0.1", 15080, timeout=5)
            try:
                connection.request("GET", "/", headers={"Host": "10.0.2.15:18080"})
                response = connection.getresponse()
                data = response.read(1024 * 1024 + 1)
                content_type = (response.getheader("Content-Type") or "").partition(";")[0].strip().lower()
                observed["last_http_status"] = response.status if type(response.status) is int and 100 <= response.status <= 599 else None
                observed["last_content_type"] = content_type if content_type in {
                    "text/html", "text/plain", "application/json", "application/octet-stream"} else "other"
                observed["last_transport"] = "http_response"
                observed["response_category"] = ("response_too_large" if len(data) > 1024 * 1024 else
                    "unexpected_page" if response.status == 200 and (content_type != "text/html" or b"heimdall" not in data.lower()) else
                    "http_status" if response.status != 200 else "app_page")
                # Do not follow redirects to arbitrary hosts, and require the
                # actual app page rather than a container that merely exists.
                if (response.status == 200 and len(data) <= 1024 * 1024 and
                        content_type == "text/html" and
                        b"heimdall" in data.lower()):
                    return {"http_status": 200, "app_page": True}
            except ConnectionRefusedError:
                observed["last_transport"] = "connection_refused"
            except TimeoutError:
                observed["last_transport"] = "timeout"
            except ConnectionResetError:
                observed["last_transport"] = "connection_reset"
            except OSError:
                observed["last_transport"] = "os_error"
            except http.client.HTTPException:
                observed["last_transport"] = "http_protocol"
            finally:
                connection.close()
            time.sleep(2)
        try:
            observed["app"] = app_observation(self.request("/api/app-details?app=heimdall&tail=50"))
        except Exception:
            observed["app"] = {"available": False}
        observed["guest"] = self.guest_diagnostic()
        raise SmokeFailure("Heimdall HTTP page did not become ready within the bounded deadline.", observed)

    def guest_diagnostic(self):
        """One fixed read-only command through the existing administrator PTY."""
        identifier, connection = None, None
        try:
            created = self.request("/api/terminal", {"action": "create", "cols": 160, "rows": 24})
            identifier = created.get("id") if isinstance(created, dict) else None
            if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{64}", identifier):
                identifier = None
                return {"available": False}
            command = "python3 -c " + shlex.quote(GUEST_DIAGNOSTIC) + "\n"
            self.request("/api/terminal", {"action": "write", "id": identifier,
                         "data": base64.b64encode(command.encode()).decode()})
            deadline = time.monotonic() + 25
            connection = http.client.HTTPSConnection("127.0.0.1", 15000, timeout=25, context=self.context)
            connection.request("GET", "/api/terminal/output?id=" + identifier,
                               headers={"Host": self.HOST, "Origin": self.ORIGIN, "Cookie": self.cookie})
            response = connection.getresponse()
            if response.status != 200:
                return {"available": False}
            received, output = 0, bytearray()
            while time.monotonic() < deadline and received < 128 * 1024 and len(output) <= 64 * 1024:
                line = response.readline(16385)
                received += len(line)
                if not line or len(line) > 16384:
                    break
                if line.startswith(b"data: "):
                    event = json.loads(line[6:])
                    encoded = event.get("data") if isinstance(event, dict) else None
                    if isinstance(encoded, str) and len(encoded) <= 22000:
                        output.extend(base64.b64decode(encoded, validate=True))
                        match = re.search(rb"(?:^|[\r\n])TITAN_SMOKE_DIAGNOSTIC:(\{[^\r\n]{1,8192}\})[\r\n]", output)
                        if match:
                            return guest_observation(json.loads(match[1]))
            return {"available": False}
        except Exception:
            return {"available": False}
        finally:
            if connection is not None:
                connection.close()
            if identifier is not None:
                try:
                    self.request("/api/terminal", {"action": "close", "id": identifier})
                except Exception:
                    pass

    def console_assets(self):
        expected = (("/console.html", b'/console.js'),
                    ("/console.js", b'/novnc/core/rfb.js'),
                    ("/novnc/core/rfb.js", b'RFB'))
        for path, marker in expected:
            connection = http.client.HTTPSConnection("127.0.0.1", 15000, timeout=10, context=self.context)
            try:
                connection.request("GET", path, headers={"Host": self.HOST, "Cookie": self.cookie, "Origin": self.ORIGIN})
                response = connection.getresponse()
                data = response.read(1024 * 1024 + 1)
                if response.status != 200 or len(data) > 1024 * 1024 or marker not in data:
                    raise SmokeFailure("Authenticated VM console or noVNC assets are unavailable.")
            except (OSError, http.client.HTTPException):
                raise SmokeFailure("VM console asset transport is not reachable.") from None
            finally:
                connection.close()
        return {"console_http": True, "novnc_assets": True}

    def console_rfb(self, identifier):
        if not self.cookie or not isinstance(identifier, str) or not identifier or len(identifier) > 128:
            raise SmokeFailure("VM console test requires an authenticated domain identifier.")
        deadline = time.monotonic() + 30
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        expected_accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        try:
            with socket.create_connection(("127.0.0.1", 15000), timeout=10) as raw:
                with self.context.wrap_socket(raw, server_hostname="10.0.2.15") as connection:
                    request = (f"GET /api/vnc?vm={quote(identifier, safe='')} HTTP/1.1\r\n"
                               f"Host: {self.HOST}\r\nOrigin: {self.ORIGIN}\r\nCookie: {self.cookie}\r\n"
                               f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                               "Sec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: binary\r\n\r\n")
                    connection.sendall(request.encode())
                    header = bytearray()
                    while b"\r\n\r\n" not in header:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or len(header) > 16384:
                            raise SmokeFailure("VM console WebSocket headers exceeded the bounded handshake.")
                        connection.settimeout(min(10, remaining))
                        chunk = connection.recv(4096)
                        if not chunk:
                            raise SmokeFailure("VM console WebSocket upgrade closed prematurely.")
                        header.extend(chunk)
                    head, pending = bytes(header).split(b"\r\n\r\n", 1)
                    if len(head) > 16384:
                        raise SmokeFailure("VM console WebSocket headers exceeded the bounded handshake.")
                    lines = head.decode("iso-8859-1").split("\r\n")
                    headers = {}
                    for line in lines[1:]:
                        if ":" not in line:
                            raise SmokeFailure("VM console returned invalid WebSocket headers.")
                        name, value = line.split(":", 1)
                        headers[name.lower()] = value.strip()
                    if (lines[0].split(" ")[1:2] != ["101"] or
                            headers.get("upgrade", "").lower() != "websocket" or
                            "upgrade" not in [item.strip() for item in headers.get("connection", "").lower().split(",")] or
                            headers.get("sec-websocket-accept") != expected_accept or
                            headers.get("sec-websocket-protocol") != "binary"):
                        raise SmokeFailure("Authenticated VM console WebSocket upgrade failed.")
                    result = VNCWebSocket(connection, deadline, pending).handshake()
                    return {"authenticated_websocket": True, **result}
        except (OSError, http.client.HTTPException):
            raise SmokeFailure("VM console WebSocket/RFB transport is not reachable.") from None


class RuntimeSmoke:
    def __init__(self, client):
        self.client = client
        self.report = {"format": "titan-runtime-smoke-v1", "target": "disposable-qemu-overlay",
                       "tested_at": datetime.now(timezone.utc).isoformat(), "ok": False,
                       "checks": [], "limitations": ["VM lifecycle checks do not boot an installed guest operating system.",
                           "Console checks verify noVNC assets and the RFB handshake; browser canvas rendering is not automated.",
                           "Update checks verify live state and rejected confirmations; update/reboot/rollback need a later signed release and a manual Proxmox test.",
                           "SMB checks use the disposable runner's smbclient; Windows/macOS clients, physical disks, RAID recovery and long-term stability need separate tests."]}

    def record(self, name, status, detail, values=None):
        item = {"name": name, "status": status, "detail": detail}
        if values is not None:
            item["values"] = values
        self.report["checks"].append(item)
        print(name + ": " + status, flush=True)
        if status == "failed":
            # The same bounded, closed-vocabulary diagnostic is public in the
            # artifact. Echo it so a blocked artifact download cannot hide it.
            print("TITAN_RUNTIME_FAILURE:" + json.dumps(item, separators=(",", ":"), allow_nan=False), flush=True)

    def run_check(self, name, function):
        try:
            values = function()
            self.record(name, "passed", "Disposable guest API check passed.", values)
            return True
        except SmokeFailure as exc:
            self.record(name, "failed", str(exc), exc.values)
        except Exception:
            # Raw exceptions and API responses may carry request credentials.
            self.record(name, "failed", "Unexpected runtime test failure; inspect the guest separately.")
        return False

    def setup(self):
        session = self.client.request("/api/session")
        if (not isinstance(session, dict) or session.get("setup_required") is not True or
                session.get("demo") is not False or session.get("user") is not None or
                not isinstance(session.get("setup_csrf"), str)):
            raise SmokeFailure("Runtime smoke requires an untouched disposable guest.")
        self.client.csrf = session["setup_csrf"]
        username, password = "smoke-" + secrets.token_hex(4), secrets.token_urlsafe(48)
        self.username, self.password = username, password
        result = self.client.request("/api/setup", {"name": username, "password": password})
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise SmokeFailure("Initial administrator setup failed.")
        login = self.client.request("/api/login", {"name": username, "password": password})
        if not isinstance(login, dict) or login.get("ok") is not True or not isinstance(login.get("csrf"), str):
            raise SmokeFailure("Administrator login failed.")
        self.client.csrf = login["csrf"]
        verified = self.client.request("/api/session")
        if verified.get("setup_required") is not False or (verified.get("user") or {}).get("role") != "admin":
            raise SmokeFailure("Authenticated administrator session is not available.")
        return {"initial_setup": True, "authenticated_admin": True}

    def metrics(self):
        self.client.request("/api/status")
        time.sleep(5.1)
        status = self.client.request("/api/status")
        total, used, available = (status.get(key) for key in ("memory_total", "memory_used", "memory_available"))
        cpu = status.get("cpu_percent")
        if (not all(type(value) is int for value in (total, used, available)) or total <= 0 or
                min(used, available) < 0 or used + available != total):
            raise SmokeFailure("Real RAM metrics are unavailable or inconsistent.")
        if type(cpu) not in (int, float) or not math.isfinite(cpu) or not 0 <= cpu <= 100:
            raise SmokeFailure("Real CPU interval metrics are unavailable or inconsistent.")
        if status.get("demo") is not False or status.get("telemetry_errors", {}).get("cpu") or status.get("telemetry_errors", {}).get("memory"):
            raise SmokeFailure("Guest did not provide valid production CPU/RAM metrics.")
        return {"cpu_percent": cpu, "memory_total": total, "memory_used": used,
                "memory_available": available, "temperature_sensors": len(status.get("temperatures", []))}

    def catalog(self):
        value = self.client.request("/api/catalog")
        apps = value.get("apps") if isinstance(value, dict) else None
        if (not isinstance(value, dict) or set(value) - {"apps", "source", "error"}
                or not isinstance(apps, list) or len(apps) != len(APPS)):
            raise SmokeFailure("App catalog or first-login guidance is incomplete.")
        modes = {mode: 0 for mode in ("default", "generated", "install", "none", "setup")}
        seen = set()
        for app in apps:
            identifier = app.get("id") if isinstance(app, dict) else None
            if not isinstance(identifier, str) or identifier not in APPS or identifier in seen:
                raise SmokeFailure("App catalog contains an unexpected or duplicate template.")
            seen.add(identifier)
            recipe = APPS[identifier]
            allowed = set(recipe) - {"environment"}
            allowed.update(("id", "version", "deprecated", "architectures", "documentation", "install_schema"))
            login = app.get("first_login")
            schema = [{key: entry for key, entry in field.items() if key != "env"}
                      for field in recipe.get("install_schema", [])]
            expected_docs = "https://docs.linuxserver.io/images/docker-" + recipe.get("upstream_name", identifier) + "/"
            if (set(app) - allowed or not isinstance(login, dict) or login != recipe.get("first_login")
                    or login.get("mode") not in modes or not isinstance(login.get("instructions"), str)
                    or not login["instructions"] or not isinstance(login.get("documentation"), str)
                    or not login["documentation"].startswith(expected_docs)
                    or app.get("documentation") != expected_docs or app.get("install_schema") != schema):
                raise SmokeFailure("App catalog first-login guidance or public field boundary is invalid.")
            modes[login["mode"]] += 1
        return {"app_count": len(seen), "first_login_mode_counts": modes, "ok": True}

    def components(self):
        value = self.client.request("/api/components").get("components", {})
        docker, vms = value.get("docker", {}), value.get("vms", {})
        if not all(docker.get(key) is True for key in ("installed", "available", "daemon", "compose")):
            raise SmokeFailure("Docker daemon and Compose are not ready in the guest.")
        if vms.get("installed") is not True or vms.get("daemon") is not True:
            raise SmokeFailure("VM components or the libvirt daemon are not ready in the guest.")
        self.kvm = vms.get("kvm") is True
        if self.kvm and vms.get("available") is not True:
            raise SmokeFailure("KVM is present but VM integration is unavailable.")
        return {"docker_daemon": True, "docker_compose": True, "libvirt_daemon": True, "kvm": self.kvm}

    def system_disk_status(self, expected_size):
        value = self.client.request("/api/system-disk")
        capacities = ("disk_size", "partition_size", "filesystem_size", "filesystem_used", "filesystem_available",
                      "partition_growable_bytes", "filesystem_growable_bytes", "growable_bytes", "partition_start")
        identity = ("disk", "partition", "disk_uuid", "partition_uuid", "filesystem_uuid")
        if (not isinstance(value, dict) or type(value.get("available")) is not bool or value.get("supported") is not True or
                value.get("filesystem") != "xfs" or value.get("mountpoint") != "/var" or
                not isinstance(value.get("revision"), str) or not re.fullmatch(r"[a-f0-9]{64}", value["revision"]) or
                any(type(value.get(key)) is not int or not 0 <= value[key] <= expected_size for key in capacities) or
                any(not isinstance(value.get(key), str) or not value[key] or len(value[key]) > 256 for key in identity) or
                type(value.get("partition_number")) is not int or not 1 <= value["partition_number"] <= 128 or
                value.get("sector_size") not in (512, 4096) or value.get("disk_size") != expected_size or
                not 28 * 1024**3 <= value["filesystem_size"] <= value["partition_size"] or
                not 0 < value["partition_start"] < value["partition_start"] + value["partition_size"] <= expected_size):
            raise SmokeFailure("System-disk live partition and XFS capacity are unavailable or inconsistent.")
        growable = value["partition_growable_bytes"] >= 1024**2 or value["filesystem_growable_bytes"] >= 1024**2
        if value["available"] is not growable:
            raise SmokeFailure("System-disk growth availability disagrees with the live partition and XFS capacity.")
        return value

    def system_disk(self):
        initial = self.system_disk_status(DisposableDiskGrowth.INITIAL)
        if initial["available"] is not False or initial["growable_bytes"] > 8 * 1024**2:
            raise SmokeFailure("First boot did not grow the disposable system partition and XFS filesystem.")
        self.client.request("/api/actions", {"operation": "system_disk_grow", "arguments": {
            "expected_revision": initial["revision"], "confirmation": "INVALID"}}, expected_status=400)
        first_noop = self.client.action("system_disk_grow", {"expected_revision": initial["revision"], "confirmation": "ERWEITERN"})
        if any(first_noop.get(field) is not False for field in ("changed", "partition_grown", "filesystem_grown")):
            raise SmokeFailure("Already grown first-boot system disk was not idempotent.")
        path = "var/tmp/titan-smoke-disk-" + secrets.token_hex(8) + ".txt"
        payload = b"Titan disposable system-disk growth sentinel.\n"
        expected_hash = hashlib.sha256(payload).hexdigest()
        created = False
        identities = ("disk", "partition", "partition_number", "partition_start", "disk_uuid",
                      "partition_uuid", "filesystem_uuid", "sector_size")

        def sentinel():
            value = self.client.request("/api/files", {"share": "@system", "action": "read", "path": path, "offset": 0, "size": 4096})
            try:
                content = base64.b64decode(value["data"], validate=True)
                if value.get("total") != len(payload) or content != payload or hashlib.sha256(content).hexdigest() != expected_hash:
                    raise ValueError
            except (KeyError, ValueError, TypeError):
                raise SmokeFailure("System-disk sentinel content or SHA256 changed during growth.") from None

        try:
            result = self.client.request("/api/files", {"share": "@system", "action": "create", "path": path,
                                         "data": base64.b64encode(payload).decode()})
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise SmokeFailure("System-disk smoke could not create its own sentinel file.")
            created = True
            sentinel()
            overlay = self.client.grow_disposable_system_disk()
            if overlay != {"overlay_grown": True, "virtual_size_before": DisposableDiskGrowth.INITIAL,
                           "virtual_size_after": DisposableDiskGrowth.EXPANDED}:
                raise SmokeFailure("Disposable system overlay growth did not confirm the requested capacity.")
            deadline = time.monotonic() + 45
            while True:
                pending = self.client.request("/api/system-disk")
                if isinstance(pending, dict) and pending.get("disk_size") == DisposableDiskGrowth.EXPANDED:
                    break
                if time.monotonic() >= deadline:
                    raise SmokeFailure("Guest did not observe the expanded disposable disk within its deadline.")
                time.sleep(1)
            pending = self.system_disk_status(DisposableDiskGrowth.EXPANDED)
            if (pending["available"] is not True or any(pending[key] != initial[key] for key in identities) or pending["revision"] == initial["revision"] or
                    pending["partition_size"] != initial["partition_size"] or pending["filesystem_size"] != initial["filesystem_size"] or
                    pending["partition_growable_bytes"] < 3 * 1024**3):
                raise SmokeFailure("Expanded disk did not retain the original system partition and XFS identity.")
            growth = self.client.action("system_disk_grow", {"expected_revision": pending["revision"], "confirmation": "ERWEITERN"})
            if any(growth.get(key) is not True for key in ("changed", "partition_grown", "filesystem_grown")):
                raise SmokeFailure("System-disk action did not grow both the actual partition and XFS filesystem.")
            after = self.system_disk_status(DisposableDiskGrowth.EXPANDED)
            delta = DisposableDiskGrowth.EXPANDED - DisposableDiskGrowth.INITIAL
            if (after["available"] is not False or any(after[key] != initial[key] for key in identities) or after["growable_bytes"] > 8 * 1024**2 or
                    any(not delta - 8 * 1024**2 <= after[key] - initial[key] <= delta + 8 * 1024**2
                        for key in ("partition_size", "filesystem_size"))):
                raise SmokeFailure("System-disk partition or XFS did not gain the expected capacity while preserving identity.")
            sentinel()
            repeated = self.client.action("system_disk_grow", {"expected_revision": after["revision"], "confirmation": "ERWEITERN"})
            if any(repeated.get(field) is not False for field in ("changed", "partition_grown", "filesystem_grown")):
                raise SmokeFailure("Expanded system-disk growth was not idempotent.")
            stable = self.system_disk_status(DisposableDiskGrowth.EXPANDED)
            if any(stable[key] != after[key] for key in identities + ("partition_size", "filesystem_size")):
                raise SmokeFailure("Idempotent growth changed the system layout.")
            sentinel()
            removed = self.client.request("/api/files", {"share": "@system", "action": "delete", "path": path,
                                         "confirmation_path": "/" + path})
            if not isinstance(removed, dict) or removed.get("ok") is not True:
                raise SmokeFailure("System-disk smoke could not remove its own sentinel.")
            created = False
            return {"first_boot_auto_growth": True, "first_boot_idempotent": True, **overlay,
                    "partition_grown": True, "xfs_grown": True, "partition_start_and_uuids_preserved": True,
                    "partition_size_before": initial["partition_size"], "partition_size_after": after["partition_size"],
                    "filesystem_size_before": initial["filesystem_size"], "filesystem_size_after": after["filesystem_size"],
                    "sentinel_sha256_unchanged": True, "sentinel_removed": True, "repeat_growth_idempotent": True}
        finally:
            if created:
                try:
                    self.client.request("/api/files", {"share": "@system", "action": "delete", "path": path,
                                        "confirmation_path": "/" + path})
                except Exception:
                    pass

    def debian_updates(self):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            status = self.client.request('/api/updates/system')
            if status.get('health_confirmed'):
                break
            time.sleep(3)
        if (status.get('platform') != 'debian-rauc' or not status.get('health_confirmed') or
                status.get('rollback_available') or status.get('reboot_required') or
                status.get('booted', {}).get('slot') != 'A'):
            raise SmokeFailure('Debian A/B initial health and slot status failed.')
        return {'initial_slot':'A', 'health_confirmed':True, 'first_install_rollback_unavailable':True}

    def updates(self):
        status = self.client.request("/api/updates/system")
        booted = status.get("booted") if isinstance(status, dict) else None
        digest = booted.get("digest") if isinstance(booted, dict) else None
        if (not isinstance(status, dict) or status.get("platform") != "ucore-hci" or
                status.get("update_kind") != "image" or not isinstance(digest, str) or
                not re.fullmatch(r"sha256:[a-f0-9]{64}", digest) or
                status.get("staged") is not None or status.get("rollback") is not None or
                status.get("rollback_available") is not False or status.get("rollback_queued") is not False or
                status.get("reboot_required") is not False or status.get("automatic_reboot") is not False or
                status.get("reboot_scheduled") is not False):
            raise SmokeFailure("Fresh-image live system update state is unavailable or inconsistent.")
        for operation in ("update_rollback", "system_reboot"):
            self.client.request("/api/actions", {"operation": operation, "arguments": {
                "expected_digest": digest, "confirmation": "INVALID"}}, expected_status=400)
        after = self.client.request("/api/updates/system")
        for key in ("booted", "staged", "rollback", "rollback_queued", "reboot_required", "reboot_scheduled"):
            if after.get(key) != status.get(key):
                raise SmokeFailure("Rejected update action changed the fresh-image system state.")
        return {"live_bootc_status": True, "first_install_rollback_unavailable": True,
                "invalid_rollback_confirmation_rejected": True, "invalid_reboot_confirmation_rejected": True,
                "automatic_reboot": False}

    def smb(self):
        users = self.client.request("/api/users")
        administrator = next((item for item in users.get("web", []) if item.get("name") == self.username), None)
        account = next((item for item in users.get("system", []) if item.get("name") == self.username), None)
        if (not isinstance(administrator, dict) or administrator.get("system_user") != self.username or
                administrator.get("role") != "admin" or administrator.get("enabled") is not True or
                not isinstance(account, dict) or type(account.get("uid")) is not int or account["uid"] < 1000 or
                account.get("enabled") is not True):
            raise SmokeFailure("Initial administrator does not have its own enabled managed SMB identity.")
        access = self.client.request("/api/shares/access")
        if access.get("service_active") is not True or access.get("port") != 445:
            raise SmokeFailure("Real SMB service is not active on its expected guest port.")
        reader = ("smoke-r-" + secrets.token_hex(4), secrets.token_urlsafe(48))
        outsider = ("smoke-n-" + secrets.token_hex(4), secrets.token_urlsafe(48))
        share = "smoke-share-" + secrets.token_hex(4)
        created, share_created = [], False
        try:
            for name, password in (reader, outsider):
                self.client.user_create(name, password)
                created.append(name)
            if any(item.get("name") == share for item in self.client.request("/api/shares")):
                raise SmokeFailure("SMB smoke share already exists; existing data will not be reused.")
            self.client.action("share_create", {"name": share, "readers": [self.username, reader[0]],
                "writers": [self.username]})
            share_created = True
            values = self.client.smb_access((self.username, self.password), reader, outsider, share)
            listing = self.client.request("/api/files?share=" + quote(share, safe="") + "&path=")
            if listing.get("entries") != [] or listing.get("total") != 0:
                raise SmokeFailure("SMB test cleanup or reader write denial left unexpected share files.")
            result = self.client.action("share_remove", {"name": share})
            if result.get("data_retained") is not True:
                raise SmokeFailure("SMB share removal did not retain its expected data directory.")
            share_created = False
            for name in list(created):
                self.client.user_remove(name)
                created.remove(name)
            users = self.client.request("/api/users")
            if any(item.get("name") in {reader[0], outsider[0]} for item in users.get("web", []) + users.get("system", [])):
                raise SmokeFailure("Removed SMB test accounts remain in the enabled user inventory.")
            return {"initial_admin_smb_identity": True, "separate_reader_identity": True,
                    "separate_unauthorized_identity": True, **values, "remove_share": True, "remove_test_users": True}
        finally:
            if share_created:
                try:
                    self.client.action("share_remove", {"name": share})
                except Exception:
                    pass
            for name in created:
                try:
                    self.client.user_remove(name)
                except Exception:
                    pass

    def app_state(self, state):
        inventory = self.client.request("/api/apps")
        if inventory.get("available") is not True:
            raise SmokeFailure("Docker app inventory is unavailable.")
        app = next((item for item in inventory.get("installed", []) if item.get("id") == "heimdall"), None)
        if app is None or app.get("state") != state:
            observed = app_observation({"app": app, "container": (app or {}).get("container")})
            observed["expected_state"] = state
            reasons = {
                "Container verwendet nicht das ausgewählte Bridge-Netzwerk.": "bridge_selection",
                "Container-Netzwerk wurde ersetzt oder stimmt nicht mit der App überein.": "network_identity",
                "Container verwendet nicht die konfigurierte feste IPv4-Adresse.": "static_ipv4",
                "Container und verwaltete App-Konfiguration stimmen nicht überein.": "container_configuration",
            }
            observed["validation_reason"] = reasons.get((app or {}).get("status"), "unknown")
            raise SmokeFailure("Docker app did not reach its expected lifecycle state.", observed)

    def docker(self):
        self.client.action("app_install", {"app": "heimdall", "port": 18080})
        self.app_state("running")
        first_http = self.client.app_http_ready()
        self.client.action("app_action", {"app": "heimdall", "action": "stop"})
        self.app_state("exited")
        self.client.action("app_action", {"app": "heimdall", "action": "start"})
        self.app_state("running")
        restarted_http = self.client.app_http_ready()
        self.client.action("app_action", {"app": "heimdall", "action": "stop"})
        self.client.action("app_action", {"app": "heimdall", "action": "remove"})
        if any(item.get("id") == "heimdall" for item in self.client.request("/api/apps").get("installed", [])):
            raise SmokeFailure("Removed Docker app remains in the managed inventory.")
        return {"app": "heimdall", "install": True, "stop": True, "start": True, "remove": True,
                "initial_http": first_http, "restarted_http": restarted_http}

    def app_network_state(self, name, address):
        inventory = self.client.request("/api/apps")
        app = next((item for item in inventory.get("installed", []) if item.get("id") == "heimdall"), None)
        details = self.client.request("/api/app-details?app=heimdall&tail=1")
        containers = [app.get("container") if isinstance(app, dict) else None,
                      details.get("container") if isinstance(details, dict) else None]
        for container in containers:
            if not isinstance(container, dict) or "public_ip" not in container or container["public_ip"] is not None:
                raise SmokeFailure("Docker network details do not distinguish local endpoints from a public IP.")
            networks = container.get("networks")
            attached = next((item for item in networks if isinstance(item, dict) and item.get("name") == name), None) if isinstance(networks, list) else None
            if (not isinstance(attached, dict) or attached.get("driver") != "bridge" or
                    attached.get("ipv4") != address or attached.get("gateway") != "172.30.241.1"):
                raise SmokeFailure("Docker app did not report its actual custom bridge and requested static IPv4 address.")
            try:
                if ipaddress.ip_address(attached["ipv4"]) not in ipaddress.ip_network("172.30.241.0/24"):
                    raise ValueError
            except ValueError:
                raise SmokeFailure("Docker app returned an invalid custom network address.") from None
            endpoints = container.get("endpoints")
            endpoints = endpoints if isinstance(endpoints, list) else []
            published = False
            for endpoint in endpoints:
                if not isinstance(endpoint, dict) or not isinstance(endpoint.get("url"), str):
                    continue
                try:
                    parsed = urlsplit(endpoint["url"])
                    published = (endpoint.get("scope") == "lan" and endpoint.get("source") == "published" and
                        endpoint.get("address") == "10.0.2.15" and endpoint.get("port") == 18080 and
                        parsed.scheme == "http" and parsed.hostname == "10.0.2.15" and parsed.port == 18080 and
                        parsed.username is None and parsed.password is None and not parsed.query and not parsed.fragment)
                except ValueError:
                    published = False
                if published:
                    break
            if not published:
                raise SmokeFailure("Docker app did not expose its published NAS LAN endpoint.")
        return {"actual_static_ipv4": True, "actual_bridge_gateway": True,
                "published_lan_endpoint": True, "public_ip": None}

    def docker_network(self):
        name, address = "titan-smoke-" + secrets.token_hex(4), "172.30.241.10"
        created, complete = False, False
        try:
            before = self.client.request("/api/app-networks")
            if (not isinstance(before, dict) or before.get("available") is not True or
                    not isinstance(before.get("networks"), list) or "public_ip" not in before or before["public_ip"] is not None or
                    any(item.get("name") == name for item in before["networks"] if isinstance(item, dict))):
                raise SmokeFailure("Docker network inventory is unavailable or the test network already exists.")
            self.client.action("app_network_create", {"name": name, "subnet": "172.30.241.0/24",
                "gateway": "172.30.241.1", "internal": False})
            created = True
            created_inventory = self.client.request("/api/app-networks")
            networks = created_inventory.get("networks", [])
            network = next((item for item in networks if isinstance(item, dict) and item.get("name") == name), None)
            if (created_inventory.get("available") is not True or not isinstance(network, dict) or
                    network.get("driver") != "bridge" or network.get("managed") is not True or
                    network.get("selectable") is not True or network.get("static_ipv4") is not True or
                    network.get("internal") is not False or
                    not any(isinstance(item, dict) and item.get("subnet") == "172.30.241.0/24" and
                            item.get("gateway") == "172.30.241.1" and item.get("family") == 4
                            for item in network.get("subnets", []))):
                raise SmokeFailure("Created Docker bridge, subnet or gateway differs from the actual network inventory.")
            self.client.action("app_install", {"app": "heimdall", "port": 18080,
                "network": {"mode": "bridge", "name": name, "ipv4_address": address}})
            self.app_state("running")
            initial_network = self.app_network_state(name, address)
            initial_http = self.client.app_http_ready()
            self.client.action("app_action", {"app": "heimdall", "action": "stop"})
            self.app_state("exited")
            self.client.action("app_action", {"app": "heimdall", "action": "start"})
            self.app_state("running")
            restarted_network = self.app_network_state(name, address)
            restarted_http = self.client.app_http_ready()
            self.client.action("app_action", {"app": "heimdall", "action": "stop"})
            self.client.action("app_action", {"app": "heimdall", "action": "remove"})
            self.client.action("app_network_remove", {"name": name, "confirmation": name})
            remaining = self.client.request("/api/app-networks").get("networks", [])
            if any(item.get("name") == name for item in remaining if isinstance(item, dict)):
                raise SmokeFailure("Removed test Docker network remains in the actual network inventory.")
            if any(item.get("id") == "heimdall" for item in self.client.request("/api/apps").get("installed", [])):
                raise SmokeFailure("Removed custom-network app remains in the managed inventory.")
            complete = True
            return {"create_bridge": True, "static_ipv4": True, "initial_network": initial_network,
                    "initial_http": initial_http, "restarted_network": restarted_network,
                    "restarted_http": restarted_http, "remove_app": True, "remove_bridge": True}
        finally:
            # Cleanup only resources created by this check, even on a failed
            # assertion. Never remove an arbitrary existing network/container.
            if created and not complete:
                try:
                    apps = self.client.request("/api/apps").get("installed", [])
                    if any(item.get("id") == "heimdall" for item in apps if isinstance(item, dict)):
                        self.client.action("app_action", {"app": "heimdall", "action": "stop"})
                        self.client.action("app_action", {"app": "heimdall", "action": "remove"})
                    self.client.action("app_network_remove", {"name": name, "confirmation": name})
                except Exception:
                    pass

    def vm_state(self, identifier, state):
        inventory = self.client.request("/api/vms")
        vm = next((item for item in inventory.get("vms", []) if item.get("id") == identifier), None)
        if inventory.get("available") is not True or vm is None or vm.get("state") != state:
            raise SmokeFailure("VM did not reach its expected lifecycle state.")

    def vm(self):
        medium = bytes(8192)
        iso = "titan-smoke-device.iso"
        uploaded = self.client.request("/api/isos", {"name": iso, "offset": 0, "total": len(medium),
                                                       "data": base64.b64encode(medium).decode()})
        if uploaded.get("complete") is not True:
            raise SmokeFailure("VM test media upload did not complete.")
        created = self.client.action("vm_create", {"name": "smoke-vm", "cpus": 1, "memory_mb": 512,
                                                      "disk_gb": 8, "iso": iso, "storage": "system"})
        identifier = created.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise SmokeFailure("VM creation did not return a domain identifier.")
        self.vm_state(identifier, "shut off")
        self.client.action("vm_action", {"vm": identifier, "action": "start"})
        self.vm_state(identifier, "running")
        console = {**self.client.console_assets(), **self.client.console_rfb(identifier)}
        self.client.action("vm_action", {"vm": identifier, "action": "poweroff"})
        self.vm_state(identifier, "shut off")
        source = created.get("disk_path")
        if not isinstance(source, str) or not source.startswith("/") or len(source) > 4096:
            raise SmokeFailure("VM creation did not return a managed image path for the clone test.")
        source_route = "/api/vm-image-info?path=" + quote(source, safe="")
        original = self.client.request(source_route)
        if (not isinstance(original, dict) or original.get("format") != "qcow2" or
                original.get("virtual_size") != 8 * 1024**3 or original.get("min_disk_gb") != 8 or
                original.get("source_retained") is not True or not isinstance(original.get("revision"), str) or
                not re.fullmatch(r"[a-f0-9]{64}", original["revision"])):
            raise SmokeFailure("Direct VM image path inspection did not return valid source capacity and metadata.")
        clone = self.client.action("vm_create", {"name": "smoke-image-clone", "cpus": 1, "memory_mb": 512,
            "disk_gb": 8, "disk_image": source, "storage": "system"})
        clone_id = clone.get("id")
        if (not isinstance(clone_id, str) or not clone_id or clone_id == identifier or
                clone.get("source_retained") is not True or clone.get("disk_path") == source):
            raise SmokeFailure("Direct VM image clone did not produce a distinct managed domain and disk.")
        self.vm_state(clone_id, "shut off")
        self.client.action("vm_action", {"vm": clone_id, "action": "start"})
        self.vm_state(clone_id, "running")
        self.client.action("vm_action", {"vm": clone_id, "action": "poweroff"})
        self.vm_state(clone_id, "shut off")
        after = self.client.request(source_route)
        if any(after.get(key) != original.get(key) for key in ("path", "format", "size", "virtual_size", "revision")):
            raise SmokeFailure("The VM image source metadata changed during direct-path cloning or clone startup.")
        if self.client.action("vm_remove", {"vm": clone_id}).get("disk_retained") is not True:
            raise SmokeFailure("VM clone removal did not retain its expected test disk.")
        removed = self.client.action("vm_remove", {"vm": identifier})
        if removed.get("disk_retained") is not True:
            raise SmokeFailure("VM removal did not preserve the expected test disk.")
        self.client.action("iso_remove", {"name": iso})
        if any(item.get("id") == identifier for item in self.client.request("/api/vms").get("vms", [])):
            raise SmokeFailure("Removed VM remains in the managed inventory.")
        return {"define": True, "start": True, "poweroff": True, "undefine": True,
                "console": console, "guest_os_boot": False,
                "direct_image_clone": {"inspect": True, "create": True, "start": True,
                    "poweroff": True, "undefine": True, "source_metadata_unchanged": True}}

    def run(self, debian_preview=False, debian_ab=False):
        if not self.run_check("administrator_setup_login", self.setup):
            return self.report
        self.run_check("app_catalog_first_login", self.catalog)
        if debian_ab:
            self.report['platform'] = 'debian-rauc'
            self.run_check('system_update_state_confirmation', self.debian_updates)
        elif debian_preview:
            self.report['platform'] = 'debian-preview'
            self.report['limitations'].append('Debian preview: A/B updates, rollback and data migration are not implemented. Cloud root growth is not tested by the legacy XFS growth test.')
            self.record('system_update_state_confirmation', 'skipped', 'Debian preview does not offer system updates or rollback.')
        else:
            self.run_check("system_update_state_confirmation", self.updates)
        self.run_check("cpu_ram_metrics", self.metrics)
        if debian_preview or debian_ab:
            self.record('system_disk_growth', 'skipped', 'Legacy XFS/OSTree growth test does not apply to Debian ext4.')
        else:
            self.run_check("system_disk_growth", self.system_disk)
        self.run_check("smb_multiuser_access", self.smb)
        if self.run_check("runtime_components", self.components):
            if self.run_check("docker_app_lifecycle", self.docker):
                self.run_check("docker_custom_network_lifecycle", self.docker_network)
            else:
                self.record("docker_custom_network_lifecycle", "skipped", "Default app lifecycle failed; custom network check cannot safely reuse that app.")
            if self.kvm:
                self.run_check("vm_domain_lifecycle", self.vm)
            else:
                self.record("vm_domain_lifecycle", "skipped", "Nested KVM is unavailable in this disposable guest; VM start requires a Proxmox or hardware test.")
        self.report["ok"] = all(item["status"] != "failed" for item in self.report["checks"])
        return self.report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-disposable-guest", action="store_true")
    parser.add_argument("--debian-preview", action="store_true")
    parser.add_argument("--debian-ab", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("dist/runtime-test.json"))
    parser.add_argument("--qmp-socket", type=Path)
    options = parser.parse_args(argv)
    if os.environ.get("GITHUB_ACTIONS") != "true" or not options.confirm_disposable_guest:
        parser.error("This mutating smoke is restricted to GitHub Actions and an explicitly confirmed disposable QEMU guest.")
    if options.qmp_socket is None:
        parser.error("The disposable image smoke requires its private QMP socket.")
    report = RuntimeSmoke(GuestClient(options.qmp_socket)).run(debian_preview=options.debian_preview, debian_ab=options.debian_ab)
    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

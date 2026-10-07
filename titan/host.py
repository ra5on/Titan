from .vm_metrics import VMMetricsMixin
from .platforms import current as host_platform
import base64
import contextlib
import grp
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from .catalog import APPS, compose
from .core import Error, atomic_json, identifier, integer, password_hash
from .management_host import ManagementMixin
from .vm_management import VMMixin
from .vm_networks import VMNetworkMixin
from .app_stores import StoreMixin
from .vm_usb import USBMixin
from .vm_storage import VMStorageMixin
from .cpu_topology import CpuMixin
from .components import ComponentsMixin
from .terminal_host import TerminalMixin
from .service_manager import ServiceManagerMixin
from .iso_management import IsoMixin
from .app_management import AppMixin
from .services import ServicesMixin
from .system_files import SystemFilesMixin, SYSTEM_SHARE, canonical_relative, virtual, PROTECTED
from .volumes import Volumes
from .virtualization import availability as vm_availability
from .telemetry import Telemetry
from .locations import LocationsMixin
from .office_gateway import OfficeHostMixin
from .identity_host import IdentityHostMixin
from .storage_services import StorageServicesMixin
from .web_access import WebAccessMixin


def run(arguments, input=None, timeout=120, pass_fds=(), include_stderr=False):
    if not shutil.which(arguments[0], path="/usr/sbin:/usr/bin:/sbin:/bin"):
        raise Error(f"{arguments[0]} ist nicht installiert.", 503)
    try:
        result = subprocess.run(arguments, input=input, text=True, capture_output=True,
                                timeout=timeout, pass_fds=pass_fds, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C.UTF-8", "LIBVIRT_DEFAULT_URI": "qemu:///system"})
    except subprocess.TimeoutExpired:
        raise Error(f"{arguments[0]} antwortet nicht innerhalb von {timeout} Sekunden. Dienststatus prüfen.", 503) from None
    except OSError as exc:
        raise Error(f"{arguments[0]} konnte nicht ausgeführt werden: {exc}", 503) from None
    if result.returncode:
        raise Error((result.stderr.strip() or result.stdout.strip() or "Befehl fehlgeschlagen.")[-4000:])
    return (result.stdout + (result.stderr if include_stderr else "")).strip()


from .docker_engine import DockerEngineMixin
from .core import OperationCoordinator, job_resources


class Host(WebAccessMixin, IdentityHostMixin, StorageServicesMixin, OfficeHostMixin, DockerEngineMixin, VMMetricsMixin, VMNetworkMixin, StoreMixin, USBMixin, ManagementMixin, VMMixin, VMStorageMixin, CpuMixin, ComponentsMixin, IsoMixin, AppMixin, ServicesMixin, SystemFilesMixin, TerminalMixin, ServiceManagerMixin, LocationsMixin):
    def __init__(self, directory="/var/lib/titan-agent", share_root="/var/srv/titan", vm_root="/var/lib/libvirt/images/titan", samba_config="/etc/samba/titan-shares.conf"):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.share_root = Path(share_root)
        self.vm_root = Path(vm_root)
        self.samba_config = Path(samba_config)
        self.lock = threading.RLock()
        self.operation_coordinator = OperationCoordinator()
        self.app_config_lock = threading.RLock()
        self.app_memory_lock = threading.RLock()
        self.account_lock = threading.RLock()
        self.samba_lock = threading.RLock()
        self.suspended_shares = set()
        self.console_processes = {}
        self.terminal_lock = threading.RLock()
        self.initialize_app_stores()
        self.telemetry = Telemetry()
        self._volumes = Volumes(self, lambda *args, **kwargs: run(*args, **kwargs))
        self.initialize_services(lambda *args, **kwargs: run(*args, **kwargs))
        repair = self.load('component-repair', {})
        if repair.get('running'):
            self.save('component-repair', {**repair, 'running': False, 'ok': False,
                'finished': time.time(), 'error': 'Komponenteninstallation durch Dienstneustart unterbrochen. Status prüfen und bei Bedarf erneut einrichten.'})
        if self.directory == Path('/var/lib/titan-agent'):
            self.web_access.resume()
            threading.Thread(target=self.reconcile_app_firewall, name='titan-app-firewall', daemon=True).start()

    def load(self, name, default):
        from .app_state import load_state
        return load_state(self.directory, name, default)

    def save(self, name, value):
        from .app_state import save_state
        save_state(self.directory, name, value)

    def dispatch(self, operation, **args):
        method = getattr(self, "op_" + operation, None)
        if not method:
            raise Error("Unbekannte Verwaltungsaktion.")
        if (self.directory / "config-restore.lock").exists() and operation not in ("status", "terminal_close", "root_terminal_close"):
            raise Error("Titan-Konfiguration wird wiederhergestellt. Verwaltungsaktionen sind gesperrt.", 503)
        # Account revocation must remain responsive during large file/VM backups.
        account_ops = {"accounts", "account_create", "account_password", "account_set_enabled", "account_update", "account_remove", "identity_apply", "identity_home", "user_quota"}
        read_ops = {"app_office_runtime", "identity_capabilities", "identity_baseline", "identity_homes", "user_quotas", "storage_maintenance", "backup_browse", "notification_settings", "vm_extensions", "package_details", "package_diagnose", "package_logs", "docker_engine", "docker_metrics", "docker_container_details","services", "service_details", "terminal_create", "terminal_poll", "terminal_write", "terminal_resize", "terminal_close", "components", "status", "storage", "snapshots", "apps", "app_details", "shares", "vms", "vm_options", "vm_usb", "vm_image_details", "cpu_topology", "isos", "iso_library", "update_check",
                    "monitoring", "monitoring_check", "monitoring_ack", "backup_settings", "volumes", "storage_locations", "system_updates", "update_progress", "system_disk", "app_networks", "app_devices", "app_metrics", "shares_access"}
        read_ops |= {'root_terminal_create', 'root_terminal_poll', 'root_terminal_write', 'root_terminal_resize', 'root_terminal_close'}
        file_read = operation in {"file", "admin_file", "system_file", "root_system_file"} and args.get("action") in {"list", "read", "trash_list"}
        share_ops = {"share_create", "share_update", "share_user_permission", "share_remove", "identity_apply", "identity_home", "user_quota"}
        independent = job_resources(operation, args)
        if operation in {"docker_container_action", "docker_container_batch"} and independent is not None:
            # A single member and its package must share the same lifecycle
            # lock. Resolve from immutable IDs, and validate again in the op.
            ids = [args["container"]] if operation == "docker_container_action" else args["containers"]
            keys = set(independent)
            for container in ids:
                row = self.engine_container(container)
                app = self.engine_summary(row).get("managed_app")
                if isinstance(app, str):
                    keys.add("app:" + app)
            independent = tuple(keys)
        if operation in {"app_memory_preflight", "catalog", "app_stores", "web_access", "web_access_confirm", "web_access_cancel"}:
            read_ops.add(operation)
        fast_lane = operation in read_ops or file_read or operation in account_ops or operation in share_ops
        resources = () if fast_lane else independent
        selected_lock = self.account_lock if operation in account_ops or operation in share_ops or file_read else self.lock if resources is None else contextlib.nullcontext()
        # Live reads and revocation never queue behind maintenance. Account/share
        # writes already coordinate with configuration_lock and account_lock;
        # acquiring this gate there would invert the backup flock lock order.
        # Restore is protected by its persistent marker and account_lock below.
        with contextlib.nullcontext() if fast_lane else self.operation_coordinator.hold(resources), selected_lock:
            with self.account_lock if operation in ("backup_config_restore", "share_create", "share_update", "share_user_permission", "share_remove", "identity_apply", "identity_home", "user_quota") else contextlib.nullcontext():
                if (self.directory / "config-restore.lock").exists() and operation not in ("status", "terminal_close", "root_terminal_close"):
                    raise Error("Titan-Konfiguration wird wiederhergestellt. Verwaltungsaktionen sind gesperrt.", 503)
                if operation not in read_ops and operation not in account_ops and operation != "system_reboot":
                    from .updates import scheduled_reboot
                    if scheduled_reboot() is not None:
                        raise Error("Ein Systemneustart ist geplant. Neue Verwaltungsaktionen sind bis nach dem Neustart gesperrt.", 409)
                return method(**args)

    def op_vm_options(self):
        return {**self.vm_storage_options(), "cpu_topology": self.cpu_topology(), "isos": self.op_isos(), "network_options": self.vm_network_choices(), "firmwares": ["bios", "uefi"] if any(Path(p).is_file() for p in ("/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_CODE.fd")) else ["bios"]}

    def op_status(self):
        metrics = self.telemetry.sample()
        details = self.service_status()
        services = {name: value["active"] for name, value in details.items()}
        storage_error = None
        try:
            volumes = self.volume_manager.inventory()["volumes"] if self.volume_manager.records() else []
            mounted = [volume for volume in volumes if volume["mounted"]]
            totals = [{key: volume[key] for key in ('total', 'used')} for volume in mounted]
            zfs = details.get('zfs', {})
            if zfs.get('configured') or zfs.get('active'):
                # Root datasets report usable capacity after RAID overhead.
                # Summing every child would count the same pool repeatedly.
                roots = run(['zfs', 'list', '-H', '-p', '-d', '0', '-t', 'filesystem', '-o', 'name,used,available'], timeout=15)
                for line in roots.splitlines():
                    name, used, available = line.split('\t')
                    used, available = int(used), int(available)
                    if used < 0 or available < 0 or '/' in name:
                        raise Error('Ungültige ZFS-Kapazitätsmessung.')
                    totals.append({'total': used + available, 'used': used})
                if not roots:
                    raise Error('Die eingerichteten ZFS-Datenpools sind nicht erreichbar.')
            if totals:
                storage = {key: sum(item[key] for item in totals) for key in ('total', 'used')}
                storage['scope'] = 'data'
            elif volumes:
                # An offline data volume must not become the system disk's
                # capacity. The health monitor supplies its actionable warning.
                storage = {"total": None, "used": None}
                storage_error = "Die eingerichteten Datenvolumes sind nicht eingehängt."
            else:
                usage = shutil.disk_usage(self.share_root if self.share_root.exists() else "/")
                storage = {"total": usage.total, "used": usage.used, 'scope': 'system'}
        except (Error, OSError, ValueError, KeyError, TypeError) as exc:
            storage = {"total": None, "used": None}
            storage_error = "Speicherstatus momentan nicht verfügbar: " + str(exc)[:300]
        return {"hostname": socket.gethostname(), "uptime": float(Path("/proc/uptime").read_text().split()[0]),
                "load": os.getloadavg()[0], **metrics, "services": services,
                "service_details": details,
                "storage": storage, "storage_error": storage_error}

    def disks(self):
        return json.loads(run(["lsblk", "--json", "--bytes", "--paths", "--output",
                               "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL,SERIAL,UUID,MAJ:MIN,RO"]))["blockdevices"]

    def op_storage(self):
        pools, datasets, status = [], [], "ZFS ist nicht installiert."
        if shutil.which("zpool"):
            try:
                for line in run(["zpool", "list", "-H", "-p", "-o", "name,size,alloc,free,health"]).splitlines():
                    name, size, used, free, health = line.split("\t")
                    pools.append({"name": name, "size": int(size), "used": int(used), "free": int(free), "health": health})
                if pools:
                    status = run(["zpool", "status"])
                    for line in run(["zfs", "list", "-H", "-p", "-t", "filesystem", "-o", "name,used,available,mountpoint"]).splitlines():
                        name, used, available, mountpoint = line.split("\t")
                        datasets.append({"name": name, "used": int(used), "available": int(available), "mountpoint": mountpoint})
                else:
                    status = "Noch kein ZFS-Pool vorhanden."
            except Error as exc:
                status = str(exc)
        return {"disks": self.disks(), "pools": pools, "datasets": datasets, "status": status, "zfs_available":bool(shutil.which("zpool")), **self.volume_manager.inventory()}

    @property
    def volume_manager(self):
        if not hasattr(self, "_volumes"):
            self._volumes = Volumes(self, lambda *args, **kwargs: run(*args, **kwargs))
        return self._volumes

    def op_volumes(self):
        return self.volume_manager.inventory()

    def op_storage_preferences_save(self, default_storage):
        self.storage_locations.resolve(default_storage, purpose="apps", write=True)
        self.save("storage-preferences", {"default_storage": default_storage})
        return {"ok": True, "default_storage": default_storage, "data_moved": False}

    def op_system_disk(self):
        from .system_disk import SystemDisk
        return SystemDisk().status()

    def op_system_disk_grow(self, expected_revision, confirmation):
        from .system_disk import SystemDisk
        return SystemDisk().grow(expected_revision=expected_revision, confirmation=confirmation)

    def op_volume_create(self, name, disk, filesystem="ext4", confirmation_name=None, confirmation_disk=None):
        if any(item["name"] == "volumes" for item in self.op_storage()["pools"]):
            raise Error("Der vorhandene ZFS-Pool volumes belegt den reservierten Volume-Bereich.")
        return self.volume_manager.create(name, disk, filesystem, confirmation_name, confirmation_disk)

    def op_volume_mount(self, name):
        return self.volume_manager.mount(name)

    def op_pool_create(self, name, layout, disks, confirmation):
        name = identifier(name)
        if name in {"volumes", "apps", "shares", "backups", "vms"}:
            raise Error("Dieser Name ist für Titan-Datenbereiche reserviert.")
        if confirmation != name:
            raise Error("Bestätigung muss dem Poolnamen entsprechen.")
        minimum = {"mirror": 2, "raidz1": 3, "raidz2": 4}.get(layout)
        if minimum is None or not isinstance(disks, list) or len(set(disks)) != len(disks) or len(disks) < minimum:
            raise Error("Ungültiges Layout oder zu wenige Laufwerke.")
        available = {disk["name"]: disk for disk in self.disks() if disk["type"] == "disk"}
        # Pool creation accepts only completely blank, unmounted disks; never use -f.
        def occupied(disk):
            return disk.get("fstype") or any(disk.get("mountpoints") or []) or disk.get("children")
        for disk in disks:
            if disk not in available or occupied(available[disk]):
                raise Error("Nur leere, unpartitionierte und ungemountete Laufwerke sind zulässig.")
            signatures = json.loads(run(["wipefs", "--json", "--no-act", disk])).get("signatures", [])
            if signatures:
                raise Error("Das Laufwerk enthält vorhandene Signaturen.")
        if name in {pool["name"] for pool in self.op_storage()["pools"]}:
            raise Error("Pool existiert bereits.")
        mountpoint = self.share_root / name
        run(["zpool", "create", "-o", "ashift=12", "-O", "compression=lz4", "-O", "acltype=posixacl",
             "-O", "xattr=sa", "-O", "mountpoint=" + str(mountpoint), name, layout, *disks])
        remembered = self.load("pools", [])
        if not any(item.get("name") == name for item in remembered):
            self.save("pools", remembered + [{"name": name, "mountpoint": str(mountpoint)}])
        return {"ok": True}

    def dataset(self, name):
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,30}(?:/[a-z][a-z0-9_-]{0,30})*", name):
            raise Error("Ungültiger Datasetname.")
        datasets = self.op_storage()["datasets"]
        if name not in {item["name"] for item in datasets}:
            raise Error("Dataset nicht gefunden.", 404)
        return name

    def op_dataset_create(self, parent, name, quota_gb=0):
        parent = self.dataset(parent)
        name = identifier(name)
        quota = integer(quota_gb, 0, 1000000)
        args = ["zfs", "create", "-o", "compression=lz4"]
        if quota:
            args += ["-o", f"quota={quota}G"]
        run([*args, parent + "/" + name])
        return {"ok": True}

    def op_snapshot_create(self, dataset, name):
        run(["zfs", "snapshot", self.dataset(dataset) + "@" + identifier(name)])
        return {"ok": True}

    def op_snapshots(self):
        if not shutil.which("zfs"):
            return []
        return self.maintenance.snapshots()

    def op_scrub(self, pool):
        if pool not in {item["name"] for item in self.op_storage()["pools"]}:
            raise Error("Pool nicht gefunden.")
        run(["zpool", "scrub", pool])
        return {"ok": True, "message": "Prüflauf gestartet; Fortschritt im Poolstatus."}

    def op_smart(self, disk):
        if disk not in {item["name"] for item in self.disks()}:
            raise Error("Laufwerk nicht gefunden.")
        result = subprocess.run(["smartctl", "-a", "-j", disk], capture_output=True, text=True, timeout=30)
        return json.loads(result.stdout)

    def op_admin_file(self, share, action, path="", **arguments):
        return self._file_operation("titan-files", share, action, path, arguments, True)

    def op_file(self, user, share, action, path="", **arguments):
        return self._file_operation(user, share, action, path, arguments, False)

    def _file_operation(self, user, share, action, path, arguments, _admin):
        allowed = {"list": {"offset", "limit", "search", "recursive", "type", "min_size", "max_size", "modified_after", "modified_before"}, "read": {"offset", "size"},
                   "office_write": {"data", "revision"}, "write": {"data", "revision"}, "create": {"data"}, "create_document": {"document_type"}, "delete": {"confirmation_path"},
                   "upload": {"offset", "data"}, "mkdir": set(), "rename": {"destination"},
                   "trash": set(), "trash_list": {"offset", "limit", "search"}, "restore": {"trash_name", "destination"},
                   "copy": {"destination", "destination_share"}, "move": {"destination", "destination_share"}}
        if action not in allowed or set(arguments) - allowed[action]:
            raise Error("Ungültige Dateiaktion oder zusätzliche Parameter.")
        if action == "delete" and not _admin:
            raise Error("Diese Dateiaktion erfordert Administratorrechte.", 403)
        self.require_active_account(user)
        record = next((item for item in self.op_shares() if item["name"] == share), None)
        if not record:
            raise Error("Freigabe nicht gefunden.", 404)
        if record.get("blocked"):
            raise Error("Freigabe ist bis zur Prüfung der Zugriffsrechte gesperrt.", 403)
        if not _admin and user not in record["readers"] + record["writers"]:
            raise Error("Kein Zugriff auf diese Freigabe.", 403)
        if not _admin and action not in ("list", "read", "trash_list", "copy") and user not in record["writers"]:
            raise Error("Die Freigabe ist schreibgeschützt.", 403)
        source_fd = self.open_share_root(record["path"])
        os.close(source_fd)
        arguments = dict(arguments)
        if action == "delete" and arguments.pop("confirmation_path", None) != share + "/" + path:
            raise Error("Zum Löschen muss der vollständige angezeigte Pfad bestätigt werden.")
        target_system = False
        target_devices = {}
        if action in ("copy", "move"):
            target_share = arguments.pop("destination_share", None) or share
            if target_share == SYSTEM_SHARE and _admin:
                target_system = True
                destination = canonical_relative(self.system_root, arguments["destination"], parent_only=True)
                if virtual(destination) or destination in PROTECTED:
                    raise Error("Dieses Systemziel kann nicht ersetzt werden.", 403)
                target_devices = self._system_volume_ready(destination)
                arguments["destination"] = destination
                arguments["destination_root"] = str(self.system_root)
            else:
                target = next((item for item in self.op_shares() if item["name"] == target_share), None)
                if not target or target.get("blocked") or (not _admin and user not in target["writers"]):
                    raise Error("Keine Schreibrechte auf der Zielfreigabe.", 403)
                target_fd = self.open_share_root(target["path"])
                os.close(target_fd)
                arguments["destination_root"] = target["path"]
        account = pwd.getpwnam("root" if _admin else user)
        with contextlib.ExitStack() as descriptors:
            inherited = []
            root = record["path"]
            if _admin:
                # Administrators use root only within already verified, descriptor-bound shares.
                # No user-controlled absolute path reaches the privileged worker.
                root = self.open_share_root(root)
                descriptors.callback(os.close, root)
                inherited.append(root)
                if "destination_root" in arguments:
                    target = os.open(self.system_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW) if target_system else self.open_share_root(arguments["destination_root"])
                    descriptors.callback(os.close, target)
                    inherited.append(target)
                    arguments["destination_root"] = target
            request = json.dumps({"root": root, "action": action, "path": path,
                                  **({"destination_devices": target_devices} if target_devices else {}), **arguments})
            result = subprocess.run([sys.executable, "-m", "titan.files"], input=request, text=True, capture_output=True,
                                    timeout=300 if action in ("copy", "move") else 60, user=account.pw_uid, group=account.pw_gid,
                                    extra_groups=[] if _admin else os.getgrouplist(user, account.pw_gid),
                                    pass_fds=tuple(inherited), cwd="/usr/lib/titan",
                                    env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "/usr/lib/titan"})
        try:
            response = json.loads(result.stdout)
        except ValueError:
            raise Error("Dateizugriff fehlgeschlagen.")
        if "error" in response:
            raise Error(response["error"], response.get("status", 400))
        return response["result"]

    def op_vms(self):
        capability = vm_availability()
        if not capability["available"]:
            return {**capability, "vms": []}
        records, warnings = [], []
        try:
            ids = run(["virsh", "list", "--all", "--uuid"]).splitlines()
        except Error as exc:
            return {**capability, "available": False, "vms": [], "error": str(exc)}
        for vm_id in ids:
            try:
                root = ET.fromstring(run(["virsh", "dumpxml", vm_id]))
                if not root.findtext("name", "").startswith("titan-"):
                    continue
                record = self.managed_vm(vm_id)
                info = run(["virsh", "dominfo", vm_id])
                records.append({"id": vm_id, "name": record["name"], "state": record["state"],
                                "memory_mb": self.vm_memory_mb(root), "cpus": int(root.findtext("vcpu")),
                                "autostart": bool(re.search(r"^Autostart:\s+enable\s*$", info, re.MULTILINE)),
                                **self.vm_media_info(root), **self.vm_disk_details(record),
                                "cpu_ids": self.vm_cpu_ids(root), "network": self.vm_network_info(root)})
            except (Error, ValueError, ET.ParseError) as exc:
                warnings.append(f"VM {vm_id} konnte nicht geprüft werden: {exc}")
        self.vm_measurements(records)
        return {**capability, "vms": records, "warnings": warnings}

    def vm_network_ready(self):
        try:
            info = run(["virsh", "net-info", "default"])
            if not re.search(r"^Active:\s+yes\s*$", info, re.MULTILINE):
                try:
                    run(["virsh", "net-start", "default"])
                except Error:
                    # A parallel manager can start the network after our query.
                    active = run(["virsh", "net-info", "default"])
                    if not re.search(r"^Active:\s+yes\s*$", active, re.MULTILINE):
                        raise
            run(["virsh", "net-autostart", "default"])
        except Error as exc:
            raise Error(f"VM-Netzwerk 'default' ist nicht bereit. libvirt-Netzwerk auf dem NAS prüfen: {exc}", 503)

    def op_vm_create(self, name, cpus, memory_mb, disk_gb, iso=None, storage="system", disk_image=None, cpu_ids=None, firmware="bios", network=None):
        self.validate_vm_firmware(firmware)
        status = self.op_vms()
        if not status["available"]:
            raise Error(status.get("error", "KVM/libvirt ist nicht verfügbar."), 503)
        name = identifier(name)
        if status.get("warnings"):
            raise Error("Bestehende VM-Definitionen zuerst prüfen: " + "; ".join(status["warnings"]), 409)
        cpus, memory_mb = self.vm_resources(cpus, memory_mb)
        pins = self.validate_vm_cpu_ids(cpus, cpu_ids)
        disk_gb = integer(disk_gb, 8, 10000)
        if iso is not None:
            self.vm_iso_path(iso)
        if not iso and not disk_image:
            raise Error("Installations-ISO oder vorhandenes Laufwerksimage auswählen.")
        location = self.vm_storage_record(storage)
        disk = Path(location["path"]) / (name + ".qcow2")
        metadata = self.directory / ("vm-" + name + ".xml")
        if (os.path.lexists(metadata) or
                name in {item["name"] for item in status["vms"]} or
                any(item["name"] == name for item in self.load("vms", []))):
            raise Error("VM-Name oder Laufwerk existiert bereits.", 409)
        # Retained disks and UEFI variables belong to the deleted VM. A fresh
        # instance gets its own internal filenames; existing files are untouched.
        if os.path.lexists(disk) or os.path.lexists(self.vm_nvram_path(name)):
            self.validate_vm_disk_path(name, disk, exists=False)
            disk = disk.with_name(name + '--' + uuid.uuid4().hex + '.qcow2')
        if "titan-" + name in run(["virsh", "list", "--all", "--name"]).splitlines():
            raise Error("Dieser VM-Name wird bereits von libvirt verwendet. Einen anderen Namen wählen.", 409)
        if network is None:
            self.vm_network_ready()
        qemu = pwd.getpwnam(host_platform().qemu_user)
        created_inode = None
        with self.vm_storage_fd(storage, create=True) as (target, location):
            filename = disk.name
            target_path = "/proc/self/fd/" + str(target) + "/" + filename
            try:
                if disk_image:
                    with self.vm_image_source(disk_image) as (source, source_info):
                        active = self.vm_active_image_paths()
                        before = os.fstat(source)
                        if self.vm_image_is_active(source, active):
                            raise Error("Image wird von einer laufenden VM verwendet; vor dem Import ausschalten.", 409)
                        # Take a private snapshot before parsing an image with
                        # QEMU. A share member may still write the original FD.
                        source_size = self.vm_image_probe(source, source_info["format"])["virtual-size"]
                        # A compressed qcow2 can expand up to its full virtual
                        # capacity. Reserve a conservative copy+conversion bound,
                        # including metadata; reflinks are an optional saving.
                        overhead = max(64 * 1024**2, source_size // 100)
                        required = before.st_size + source_size + overhead
                        if os.fstatvfs(target).f_bavail * os.fstatvfs(target).f_frsize < required:
                            raise Error("Zu wenig freier Speicher für private Image-Kopie und VM-Disk.", 409)
                        with self.vm_private_image(target, source) as private:
                            image_format = "qcow2" if os.pread(private, 4, 0) == b"QFI\xfb" else source_info["format"]
                            info = self.vm_image_info(private, image_format)
                            if disk_gb * 1024**3 < info["virtual-size"]:
                                raise Error("Neue Disk darf nicht kleiner als das ausgewählte Image sein.")
                            free = os.fstatvfs(target)
                            if free.f_bavail * free.f_frsize < info["virtual-size"] + max(64 * 1024**2, info["virtual-size"] // 100):
                                raise Error("Zu wenig freier Speicher für ein vollständig entpacktes Laufwerksimage.", 409)
                            run(["qemu-img", "create", "-f", "qcow2", target_path, str(disk_gb) + "G"], pass_fds=(target,))
                            allocated = os.stat(filename, dir_fd=target, follow_symlinks=False)
                            created_inode = (allocated.st_dev, allocated.st_ino)
                            run(["qemu-img", "convert", "-n", "-f", image_format, "-O", "qcow2",
                                 "/proc/self/fd/" + str(private), target_path], timeout=3600, pass_fds=(private, target))
                            after = os.fstat(source)
                            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                                raise Error("Quellimage wurde während des Imports verändert. Import verworfen.", 409)
                            if disk_gb * 1024**3 > info["virtual-size"]:
                                run(["qemu-img", "resize", "-f", "qcow2", target_path, str(disk_gb) + "G"], pass_fds=(target,))
                else:
                    run(["qemu-img", "create", "-f", "qcow2", target_path, str(disk_gb) + "G"], pass_fds=(target,))
                    allocated = os.stat(filename, dir_fd=target, follow_symlinks=False)
                    created_inode = (allocated.st_dev, allocated.st_ino)
                os.chmod(disk, 0o660, follow_symlinks=False)
                os.chown(disk, qemu.pw_uid, qemu.pw_gid, follow_symlinks=False)
                xml = self.vm_definition(name, cpus, memory_mb, disk, iso, cpu_ids=pins, firmware=firmware)
                if network is not None:
                    root = ET.fromstring(xml)
                    self.apply_vm_network(root, network)
                    self.vm_selected_network_ready(root)
                    xml = ET.tostring(root, encoding="unicode")
                vm_id = self.register_vm_definition(name, xml, virtual_size=disk_gb * 1024**3)
            except Exception as failure:
                if getattr(failure, "retain_vm_files", False):
                    raise
                try:
                    allocated = os.stat(filename, dir_fd=target, follow_symlinks=False)
                    # The directory is root-controlled and the global mutation
                    # lock excludes Titan file writes. Partial qemu allocation is
                    # removed even when create failed before its inode was returned.
                    if created_inode is None or (allocated.st_dev, allocated.st_ino) == created_inode:
                        os.unlink(filename, dir_fd=target)
                except FileNotFoundError:
                    pass
                metadata.unlink(missing_ok=True)
                raise
        return {"ok": True, "id": vm_id, "disk_path": str(disk), "storage": storage,
                "disk_gb": disk_gb, "virtual_size": disk_gb * 1024**3, "cpu_ids": pins,
                "source_retained": bool(disk_image)}

    def op_vm_action(self, vm, action):
        if action == "remove":
            return self.op_vm_remove(vm)
        if action == "start":
            status = self.op_vms()
            if not status["available"]:
                raise Error(status.get("error", "KVM/libvirt ist nicht verfügbar."), 503)
        vm = self.vm_id(vm, check_cpu=action == "start")
        if action in ("start", "resume"):
            from .app_memory import check_vm_start_memory, vm_memory_reservations
            record = self.managed_vm(vm)
            check_vm_start_memory(record["memory_mb"] * 1024**2,
                self._app_inspected_containers(), vms=vm_memory_reservations(run), telemetry=self.telemetry, vm=vm)
        if action == "start":
            self.prepare_vm_storage_access()
            self.vm_selected_network_ready(ET.fromstring(self.managed_vm(vm)["xml"]))
        choices = {"start": ["start"], "shutdown": ["shutdown"], "reboot": ["reboot"],
                   "autostart": ["autostart"], "disable-autostart": ["autostart", "--disable"],
                   "suspend": ["suspend"], "resume": ["resume"], "poweroff": ["destroy"]}
        if action not in choices:
            raise Error("Ungültige VM-Aktion.")
        result = run(["virsh", *choices[action], vm])
        if action in ("shutdown", "poweroff", "start", "reboot"):
            process = self.console_processes.pop(vm, None)
            if process and process[0].poll() is None:
                process[0].terminate()
        return {"output": result}

    def op_console(self, vm):
        vm = self.vm_id(vm)
        root = ET.fromstring(run(["virsh", "dumpxml", vm]))
        graphics = root.find("./devices/graphics[@type='vnc']")
        if graphics is None or not 5900 <= int(graphics.get("port", "-1")) <= 65535:
            raise Error("VM muss laufen und eine VNC-Konsole besitzen.")
        if graphics.get("listen") != "127.0.0.1":
            raise Error("Die VM-Konsole muss an 127.0.0.1 gebunden sein.", 403)
        target = int(graphics.get("port"))
        process = self.console_processes.get(vm)
        if process and process[0].poll() is None and len(process) == 3 and process[2] == target:
            try:
                with socket.create_connection(("127.0.0.1", process[1]), timeout=0.2):
                    return {"port": process[1]}
            except OSError:
                pass
        if process and process[0].poll() is None:
            process[0].terminate()
        self.console_processes.pop(vm, None)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        child = subprocess.Popen(["websockify", f"127.0.0.1:{port}", "127.0.0.1:" + graphics.get("port")],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Python/websockify may start slowly under nested virtualization.
        # Keep startup bounded, but allow the proxy time to become ready.
        for _ in range(300):
            if child.poll() is not None:
                raise Error("VNC-Proxy konnte nicht starten.")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            child.terminate()
            raise Error("VNC-Proxy ist nicht erreichbar.")
        self.console_processes[vm] = (child, port, target)
        return {"port": port}

    def op_update_progress(self):
        from .update_progress import read
        return read()

    def op_system_updates(self):
        from .updates import system_status
        return system_status()

    def op_update_check(self, repository, channel="stable", update_kind="all"):
        from .updates import check, read_token
        return check(repository, channel, read_token(), update_kind)

    def op_update_install(self, repository, channel, expected_version, update_kind="all"):
        from .updates import install
        return install(repository, channel, expected_version, "/var/lib/titan/titan.sqlite3", update_kind)

    def op_update_rollback(self, repository, expected_digest, confirmation):
        from .updates import rollback
        return rollback(repository, expected_digest, confirmation, "/var/lib/titan/titan.sqlite3")

    def op_system_reboot(self, repository, expected_digest, confirmation):
        from .updates import reboot
        return reboot(repository, expected_digest, confirmation, "/var/lib/titan/titan.sqlite3")

    def op_system_shutdown(self, confirmation):
        if confirmation is not True: raise Error("Ausschalten bestätigen.")
        if any(vm["state"] != "shut off" for vm in self.op_vms()["vms"]): raise Error("Virtuelle Maschinen zuerst herunterfahren.", 409)
        run(["shutdown", "-h", "+1", "Titan: bestätigtes Ausschalten"], timeout=15)
        return {"ok": True, "message": "NAS wird in etwa einer Minute ausgeschaltet."}

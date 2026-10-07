"""Bounded options and runtime checks for Titan's own network/photo apps."""
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import secrets
import stat

from .core import Error

PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7'))


def private_address(value):
    try:
        address = ipaddress.ip_address(value)
        if not any(address.version == network.version and address in network for network in PRIVATE_NETWORKS):
            raise ValueError()
        return str(address)
    except (ValueError, TypeError):
        raise Error('Eine private NAS-IP im Heimnetz angeben, z. B. 192.168.1.10.') from None


def validate_recipe_options(app, options):
    if app != 'titan-tailscale':
        return options
    result = dict(options)
    if not re.fullmatch(r'tskey-auth-[A-Za-z0-9_-]{10,117}', result.get('auth_key', '')):
        raise Error('Einen Tailscale Auth-Key einfügen (tskey-auth-…), keinen API-Schlüssel oder Installationsbefehl.')
    if result.get('nas_address'):
        result['nas_address'] = private_address(result['nas_address'])
    enabled = result.get('subnet_routing') == 'enabled'
    raw = result.get('subnet_routes', '')
    if not enabled:
        if raw:
            raise Error('Zum Freigeben von Heimnetzbereichen zuerst „Heimnetz freigeben“ aktivieren.')
        return result
    try:
        routes = [ipaddress.ip_network(value.strip(), strict=True) for value in raw.split(',')]
        if not 1 <= len(routes) <= 8 or len(set(routes)) != len(routes):
            raise ValueError()
        if any(not any(route.version == network.version and route.subnet_of(network) for network in PRIVATE_NETWORKS) for route in routes):
            raise ValueError()
        if any(a.version == b.version and a.overlaps(b) for index, a in enumerate(routes) for b in routes[index + 1:]):
            raise ValueError()
    except (ValueError, TypeError):
        raise Error('Ein bis acht getrennte private CIDR-Netze angeben, z. B. 192.168.1.0/24. Keine Standardroute, öffentlichen oder überlappenden Netze.') from None
    result['subnet_routes'] = ','.join(str(route) for route in routes)
    return result


def advertised_routes(options):
    """Userspace routes to the NAS use its LAN IP, never kernel-only TS_DEST_IP."""
    routes = [ipaddress.ip_network(value) for value in options.get('subnet_routes', '').split(',') if value]
    if options.get('nas_address'):
        address = ipaddress.ip_address(options['nas_address'])
        if not any(address.version == route.version and address in route for route in routes):
            routes.append(ipaddress.ip_network(str(address) + ('/32' if address.version == 4 else '/128')))
    return ','.join(str(route) for route in routes)


def check_requirements(app, resource=None):
    if app != 'titan-immich':
        return
    if resource is not None and resource.get('filesystem') not in ('ext4', 'xfs', 'btrfs', 'zfs'):
        raise Error('Immich benötigt für seine Datenbank einen lokalen Linux-Speicher (ext4, XFS, Btrfs oder ZFS). Netzwerkfreigaben sind dafür nicht geeignet.', 409)
    machine = platform.machine().lower()
    if machine not in ('x86_64', 'amd64', 'aarch64', 'arm64'):
        raise Error('Immich benötigt einen unterstützten 64-Bit-Prozessor (AMD64 oder ARM64).', 409)
    if machine in ('x86_64', 'amd64'):
        try:
            cpu = Path('/proc/cpuinfo').read_text()
        except OSError:
            raise Error('CPU-Anforderungen für Immich konnten nicht geprüft werden.', 503) from None
        # The v3 machine-learning image requires x86-64-v2 on every CPU core.
        required = {'cx16', 'lahf_lm', 'popcnt', 'ssse3', 'sse4_1', 'sse4_2'}
        cores = [set(line.split(':', 1)[1].split()) for line in cpu.splitlines() if line.startswith('flags')]
        if not cores or any(not required <= flags or not ({'pni', 'sse3'} & flags) for flags in cores):
            raise Error('Immich 3 benötigt für die Bilderkennung einen x86-64-v2-Prozessor. Dieser Prozessor erfüllt die Anforderungen nicht.', 409)


def prepare_tailscale_runtime(host, record):
    """Write the auth-key through pinned directories, never Compose or argv."""
    app = 'titan-tailscale'
    key = validate_recipe_options(app, host._app_options(app))['auth_key']
    config = host._app_config_path(app, record)
    temporary = '.authkey-' + secrets.token_hex(12)
    descriptors = []
    try:
        with host.storage_locations.fd(record.get('storage_id', 'system'), purpose='apps', write=True) as (base, resource):
            if config != Path(resource['path']) / app / 'config':
                raise Error('Der private Tailscale-Speicher passt nicht zur verwalteten App.', 403)
            parent = base
            for component in (app, 'config'):
                metadata = os.fstat(parent)
                if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
                    raise Error('Der private Tailscale-Speicher ist nicht geschützt.', 403)
                parent = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                descriptors.append(parent)
            os.fchown(parent, os.geteuid(), os.getegid())
            os.fchmod(parent, 0o700)
            try:
                os.mkdir('credentials', 0o700, dir_fd=parent)
            except FileExistsError:
                pass
            private = os.open('credentials', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            descriptors.append(private)
            metadata = os.fstat(private)
            if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
                raise Error('Tailscale-Zugangsverzeichnis hat unsichere Dateirechte.', 403)
            os.fchmod(private, 0o700)
            try:
                metadata = os.stat('authkey', dir_fd=private, follow_symlinks=False)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077 or metadata.st_nlink != 1:
                    raise Error('Vorhandene Tailscale-Zugangsdatei ist unsicher.', 403)
            except FileNotFoundError:
                pass
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=private)
            try:
                with os.fdopen(fd, 'w') as stream:
                    stream.write(key)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, 'authkey', src_dir_fd=private, dst_dir_fd=private)
                os.fsync(private)
            finally:
                try:
                    os.unlink(temporary, dir_fd=private)
                except FileNotFoundError:
                    pass
    except OSError:
        raise Error('Tailscale-Zugangsdatei konnte nicht sicher vorbereitet werden.', 503) from None
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def tailscale_runtime(container):
    """Inspect an already ownership-verified container, exposing no peers/key."""
    result = {'connected': False, 'addresses': [], 'routes_approval': 'not_verified'}
    if not container or not container.get('State', {}).get('Running'):
        return result
    identifier = container.get('Id', '')
    if not re.fullmatch(r'[a-f0-9]{64}', identifier):
        return result
    try:
        from .host import run
        value = json.loads(run(['docker', 'exec', identifier, 'tailscale', 'status', '--json'], timeout=5))
        addresses = [str(ipaddress.ip_address(address)) for address in value.get('TailscaleIPs', [])]
        result.update(connected=value.get('BackendState') == 'Running' and value.get('Self', {}).get('Online') is True,
                      addresses=addresses[:8])
    except (Error, ValueError, TypeError, AttributeError):
        pass
    return result

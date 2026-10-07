"""The fixed Cloudflare runner and its private token-file preparation."""
import base64
import binascii
import http.client
import json
import os
import re
import secrets
import stat
import uuid

from .core import Error

CONNECTOR = 'titan-cloudflared'
METRICS_PORT = 5103
TOKEN_PATH = '/etc/cloudflared/token'


def validate_token(value):
    """Accept the upstream TunnelToken envelope, never an installation command.

    This is a format check, not cryptographic verification. Cloudflare verifies
    the credential when the runner connects; only /ready confirms that step.
    """
    message = 'Den vollständigen Cloudflare Tunnel-Token einfügen (eyJ…), keinen Installationsbefehl oder API-Token.'
    try:
        if not isinstance(value, str) or not 80 <= len(value) <= 4096 or not re.fullmatch(r'[A-Za-z0-9+/]+={0,2}', value):
            raise ValueError()
        data = json.loads(base64.b64decode(value, validate=True))
        if (not isinstance(data, dict) or not {'a', 't', 's'} <= set(data) or set(data) - {'a', 't', 's', 'e'} or
                not isinstance(data['a'], str) or not re.fullmatch(r'[a-fA-F0-9]{32}', data['a']) or
                not isinstance(data['t'], str) or str(uuid.UUID(data['t'])) != data['t'].lower() or
                uuid.UUID(data['t']).int == 0 or not isinstance(data['s'], str) or
                not 16 <= len(base64.b64decode(data['s'], validate=True)) <= 128 or
                data.get('e', '') != ''):
            # Alternate edge endpoints need an explicitly reviewed recipe;
            # a pasted credential must not choose an arbitrary network target.
            raise ValueError()
    except (ValueError, TypeError, binascii.Error, UnicodeError):
        raise Error(message) from None
    return value


def prepare_runtime(host, record):
    """Pin the selected storage and atomically replace a root-only token file.

    The whole credentials directory is mounted read-only, so token rotation
    also works when Docker retains the existing container's directory mount.
    No credential is placed in Compose, argv, environment or public records.
    """
    token = validate_token(host._app_options(CONNECTOR)['tunnel_token'])
    config = host._app_config_path(CONNECTOR, record)
    temporary = '.token-' + secrets.token_hex(12)
    descriptors = []
    try:
        with host.storage_locations.fd(record.get('storage_id', 'system'), purpose='apps', write=True) as (base, resource):
            from pathlib import Path
            if config != Path(resource['path']) / CONNECTOR / 'config':
                raise Error('Der private Tunnel-Speicher passt nicht zur verwalteten App.', 403)
            parent = base
            for component in (CONNECTOR, 'config'):
                metadata = os.fstat(parent)
                if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
                    raise Error('Der private Tunnel-Speicher ist nicht geschützt.', 403)
                parent = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                descriptors.append(parent)
            # Fresh generic app config is initially owned by titan-files. The
            # dedicated runner needs no user files: lock it to the agent owner.
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
                raise Error('Das Tunnel-Zugangsverzeichnis hat unsichere Dateirechte.', 403)
            os.fchmod(private, 0o700)
            try:
                metadata = os.stat('token', dir_fd=private, follow_symlinks=False)
                if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid() or
                        metadata.st_mode & 0o077 or metadata.st_nlink != 1):
                    raise Error('Die vorhandene Tunnel-Zugangsdatei ist unsicher.', 403)
            except FileNotFoundError:
                pass
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=private)
            try:
                with os.fdopen(fd, 'w') as stream:
                    stream.write(token)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, 'token', src_dir_fd=private, dst_dir_fd=private)
                os.fsync(private)
            finally:
                try:
                    os.unlink(temporary, dir_fd=private)
                except FileNotFoundError:
                    pass
    except OSError:
        raise Error('Die private Tunnel-Zugangsdatei konnte nicht sicher vorbereitet werden.', 503) from None
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def connector_ready(container):
    """Use Cloudflared's documented local connection check, with no redirects."""
    if not container or not container.get('State', {}).get('Running'):
        return False
    if container.get('HostConfig', {}).get('NetworkMode') != 'host':
        pid = container.get('State', {}).get('Pid')
        if type(pid) is not int or pid <= 0:
            return False
        from .host import run
        script = ('import http.client;c=http.client.HTTPConnection("127.0.0.1",' + str(METRICS_PORT) + ',timeout=1);'
                  'c.request("GET","/ready");r=c.getresponse();r.read(4097);print("ready" if r.status==200 else "waiting")')
        try:
            return run(['nsenter', '-t', str(pid), '-n', '--', '/usr/bin/python3', '-c', script], timeout=3).strip() == 'ready'
        except Error:
            return False
    connection = http.client.HTTPConnection('127.0.0.1', METRICS_PORT, timeout=1)
    try:
        connection.request('GET', '/ready')
        response = connection.getresponse()
        response.read(4097)
        return response.status == 200
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()

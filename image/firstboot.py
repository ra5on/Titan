#!/usr/bin/env python3
"""Prepare per-machine state at boot; the distributable image contains no secrets."""
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

# The firstboot entrypoint lives in /usr/share; the installed application lives
# in a root-owned /usr/lib tree rather than the current working directory.
sys.path.insert(0, '/usr/lib/titan')
from titan.web_access import caddy_config, initial_config, origin, read_config, listen_ports


def run(args, *, check=True):
    try:
        return subprocess.run(args, check=check, text=True, capture_output=True, timeout=600,
                              env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C.UTF-8'})
    except subprocess.CalledProcessError as error:
        # Preserve the real diagnostic in the firstboot journal/console.
        if error.stderr:
            print(error.stderr.rstrip(), file=sys.stderr, flush=True)
        raise


def address(value):
    value = value.strip()
    try:
        ip = ipaddress.ip_address(value)
        if ip.version != 4 or ip.is_loopback or ip.is_unspecified or ip.is_multicast:
            raise ValueError('Use a usable IPv4 address or DNS name.')
        return str(ip)
    except ValueError:
        if not re.fullmatch(r'(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', value):
            raise ValueError('Invalid Titan address.') from None
        if re.fullmatch(r'[0-9.]+', value) or any(not part or len(part)>63 or part.startswith('-') or part.endswith('-') for part in value.split('.')):
            raise ValueError('Invalid Titan address.')
        return value.lower()


def detect_address():
    # A route query reads the kernel table; it sends no packets.
    result = run(['ip', '-j', '-4', 'route', 'get', '1.1.1.1'], check=False)
    if result.returncode == 0:
        for route in json.loads(result.stdout):
            value = route.get('prefsrc', route.get('src', ''))
            if value:
                return address(value)
    # A LAN without Internet/default gateway must still be reachable.
    interfaces = json.loads(run(['ip', '-j', '-4', 'addr', 'show', 'scope', 'global']).stdout)
    for interface in interfaces:
        name = interface.get('ifname', '')
        if name.startswith(('lo', 'docker', 'br-', 'virbr', 'veth')) or 'UP' not in interface.get('flags', []):
            continue
        for item in interface.get('addr_info', []):
            if item.get('family') == 'inet' and item.get('scope') == 'global':
                return address(item['local'])
    raise RuntimeError('No primary IPv4 address available yet.')


def atomic(path, content, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.titan-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def endpoint(host, settings=None):
    host = address(host)
    config = initial_config(host)
    if settings is not None:
        config['settings'] = settings
    return 'TITAN_ORIGIN=' + origin(host, config['settings']) + '\n', caddy_config(config)


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Titan first boot requires root.')
    info = json.loads(Path('/usr/share/titan/image-info.json').read_text())
    if (info.get('platform'), info.get('format')) not in (('debian-preview', 'titan-debian-preview-v1'), ('debian-rauc', 'titan-debian-ab-v1')):
        raise RuntimeError('This is not a supported Titan image.')
    if info.get('platform') == 'debian-rauc':
        import pwd, grp
        contract = info['system_accounts']
        for name, identity in contract['users'].items():
            account = pwd.getpwnam(name)
            if (account.pw_uid, account.pw_gid) != (identity['uid'], identity['gid']):
                raise RuntimeError('System account identity changed: ' + name)
        for name, identity in contract['groups'].items():
            if grp.getgrnam(name).gr_gid != identity:
                raise RuntimeError('System group identity changed: ' + name)
        # Never initialize an apparently empty NAS when initramfs persistence
        # failed. All services requiring firstboot remain stopped in that case.
        for mount in ('/var/lib/titan-system', '/etc', '/var/lib/titan', '/var/lib/titan-agent',
                      '/var/lib/titan-proxy', '/var/lib/docker', '/var/lib/containerd',
                      '/var/lib/libvirt', '/var/lib/samba', '/var/srv/titan'):
            run(['mountpoint', '-q', mount])
    run(['systemd-sysusers', '/usr/lib/sysusers.d/titan.conf'])
    run(['systemd-tmpfiles', '--create', '/usr/lib/tmpfiles.d/titan.conf'])
    configured = Path('/etc/titan/address')
    host = address(configured.read_text()) if configured.exists() else detect_address()
    access_path = Path('/etc/titan/web-access.json')
    if access_path.exists():
        access = read_config(access_path)
        if access.get('pending'):
            access = access['pending']['previous']
            access['last_error'] = 'Unbestätigter Webadresswechsel beim Neustart zurückgenommen.'
        access['host'] = host
    else:
        previous_env = Path('/etc/titan/web.env')
        previous_origin = next((line.split('=', 1)[1] for line in previous_env.read_text().splitlines() if line.startswith('TITAN_ORIGIN=')), None) if previous_env.exists() else None
        access = initial_config(host, previous_origin)
    atomic(access_path, json.dumps(access, ensure_ascii=False, indent=2) + '\n')
    env, caddy = endpoint(host, access['settings'])
    atomic('/etc/titan/web.env', env)
    atomic('/etc/titan/Caddyfile', caddy)
    atomic('/etc/titan/release-public.pem', Path('/usr/share/titan/release-public.pem').read_text())
    # Provision TLS with the same identity and persistent storage as the proxy.
    # A sanitized root environment would otherwise use /caddy on read-only /.
    run(['runuser', '-u', 'titan-proxy', '--', 'env',
         'XDG_DATA_HOME=/var/lib/titan-proxy', 'XDG_CONFIG_HOME=/var/lib/titan-proxy',
         'caddy', 'validate', '--config', '/etc/titan/Caddyfile', '--adapter', 'caddyfile'])
    samba = Path('/etc/samba/smb.conf')
    text = samba.read_text() if samba.exists() else '[global]\n'
    include = 'include = /etc/samba/titan-shares.conf'
    if include not in [line.strip() for line in text.splitlines()]:
        atomic(samba, text.rstrip() + '\n\n[global]\n' + include + '\n')
    shares = Path('/etc/samba/titan-shares.conf')
    if not shares.exists():
        atomic(shares, '')
    run(['testparm', '-s', str(samba)])
    if Path('/sys/fs/selinux/enforce').exists():
        run(['semodule', '-i', '/usr/share/titan/titan-shares.pp', '/usr/share/titan/titan-proxy.pp'])
        # Add broad rule first: semanage local rules are evaluated newest first.
        rules = [('titan_share_t', r'/var/srv/titan(/.*)?'),
                 ('virt_image_t', r'/var/srv/titan/volumes/[^/]+/vms(/.*)?'),
                 ('virt_image_t', r'/var/lib/libvirt/images/titan(/.*)?')]
        for label, pattern in rules:
            added = run(['semanage', 'fcontext', '-a', '-t', label, pattern], check=False)
            if added.returncode:
                run(['semanage', 'fcontext', '-m', '-t', label, pattern])
        # Do not recursively relabel existing guests: libvirt owns their MCS labels.
        run(['restorecon', '/etc/titan', '/etc/titan/web.env', '/etc/titan/Caddyfile',
             '/etc/titan/release-public.pem', '/etc/samba/titan-shares.conf',
             '/var/srv/titan', '/var/lib/libvirt/images/titan',
             '/var/lib/libvirt/images/titan/iso'])
    ports = ''.join('<port protocol="tcp" port="' + str(port) + '"/>' for port in sorted(listen_ports(access['settings'])))
    atomic('/etc/firewalld/services/titan.xml', '<service><short>Titan</short>' + ports + '</service>\n')
    # At boot Docker and the Titan services are still ordered behind firstboot.
    run(['firewall-cmd', '--reload'])
    for service in ('titan', 'samba'):
        run(['firewall-cmd', '--permanent', '--add-service=' + service])
        run(['firewall-cmd', '--add-service=' + service])
    # Host services have socket activation. A missing KVM device only disables VMs.
    print('Titan persistent state initialized for ' + origin(host, access['settings']) + '; web services start next.', flush=True)


if __name__ == '__main__':
    main()

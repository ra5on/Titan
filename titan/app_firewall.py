"""Reference-counted firewalld access restricted to directly attached LANs.

Never flush or reload firewalld. A rule already present when first encountered
is recorded as external and is never removed by Titan. The persistent ledger
also keeps overlapping app/web references from removing one another's access.
"""
import ipaddress
import json
import re
import threading
from .core import Error

_LOCK = threading.RLock()
_LEDGER = 'managed-firewall-v1'


def _run(arguments, **kwargs):
    from .host import run
    return run(arguments, **kwargs)


def _query(arguments):
    try:
        return _run(arguments, timeout=3).strip() == 'yes'
    except Error as exc:
        if str(exc).strip() == 'no':
            return False
        raise


def lan_scopes():
    """Use existing interface zones, and explicit source networks, never any/0."""
    entries = json.loads(_run(['ip', '-j', 'address', 'show', 'up'], timeout=3))
    if not isinstance(entries, list) or len(entries) > 256:
        raise Error('LAN-Schnittstellen konnten nicht eindeutig geprüft werden.', 503)
    default = None
    result = []
    for item in entries:
        interface = item.get('ifname', '')
        if (not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,64}', interface) or
                interface.startswith(('lo', 'docker', 'br-', 'veth', 'virbr', 'tun', 'tap', 'wg'))):
            continue
        scopes = []
        for address in item.get('addr_info', []):
            try:
                value = ipaddress.ip_interface(str(address['local']) + '/' + str(address['prefixlen']))
            except (KeyError, ValueError, TypeError):
                continue
            # Only RFC1918 / ULA addresses are automatically classified as LAN.
            # Link-local/public networks require an explicit administrator rule.
            private = (any(value.ip in ipaddress.ip_network(block) for block in
                       ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')) if value.version == 4
                       else value.ip in ipaddress.ip_network('fc00::/7'))
            if private and value.network.prefixlen and not value.ip.is_loopback:
                scopes.append((str(value.network), value.version, str(value.ip)))
        if not scopes:
            continue
        zone = _run(['firewall-cmd', '--get-zone-of-interface=' + interface], timeout=3).strip()
        if zone in ('', 'no zone'):
            if default is None:
                default = _run(['firewall-cmd', '--get-default-zone'], timeout=3).strip()
            zone = default
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', zone):
            raise Error('Die LAN-Firewallzone ist ungültig.', 503)
        result.extend({'zone': zone, 'source': source, 'family': family, 'address': address}
                      for source, family, address in scopes)
    if len(result) > 32:
        raise Error('Zu viele LAN-Netze für eine automatische Firewallfreigabe.', 409)
    return result


def _requested(ports, scopes):
    if not isinstance(ports, list) or len(ports) > 64:
        raise Error('Ungültige Firewall-Portliste.')
    result = {}
    for port in ports:
        if (not isinstance(port, dict) or type(port.get('host')) is not int or
                not 1 <= port['host'] <= 65535 or port.get('protocol') not in ('tcp', 'udp')):
            raise Error('Ungültige Firewall-Portfreigabe.')
        bind = port.get('host_ip', '')
        if not isinstance(bind, str):
            raise Error('Ungültige Port-Bindungsadresse.')
        try:
            bound = ipaddress.ip_address(bind) if bind else None
        except ValueError:
            raise Error('Ungültige Port-Bindungsadresse.') from None
        if bound and bound.is_loopback:
            continue
        for scope in scopes:
            if bound and not bound.is_unspecified and str(bound) != scope['address']:
                continue
            if bound and bound.is_unspecified and bound.version != scope['family']:
                continue
            rule = (f'rule family="ipv{scope["family"]}" source address="{scope["source"]}" '
                    f'port port="{port["host"]}" protocol="{port["protocol"]}" accept')
            key = scope['zone'] + '\n' + rule
            result[key] = {'zone': scope['zone'], 'rule': rule}
    return result


def _valid_rule(row):
    # Treat a damaged ledger as an error, never as permission to delete a rule.
    return (isinstance(row, dict) and re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', str(row.get('zone', ''))) and
            re.fullmatch(r'rule family="ipv[46]" source address="[a-fA-F0-9.:/]+" port port="[0-9]{1,5}" protocol="(?:tcp|udp)" accept', str(row.get('rule', ''))) and
            isinstance(row.get('owners'), list) and all(isinstance(owner, str) for owner in row['owners']) and
            type(row.get('owned')) is bool and
            all(type(row.get(name, row['owned'])) is bool for name in ('runtime_owned', 'permanent_owned')))


def reconcile(host, owner_key, ports):
    """Set one owner's desired access; keep all other owners and external rules.

    Returns diagnostics when firewalld is inactive. An active firewall command
    failure raises, preventing a successful install from claiming LAN access.
    Ledger writes precede mutations, allowing safe retry after a daemon crash.
    """
    if not isinstance(owner_key, str) or not re.fullmatch(r'[a-zA-Z0-9:_.-]{1,128}', owner_key):
        raise Error('Ungültiger Firewall-Eigentümer.')
    with _LOCK:
        try:
            active = _run(['firewall-cmd', '--state'], timeout=3).strip() == 'running'
        except Error:
            active = False
        if not active:
            return {'available': False, 'managed_rules': 0,
                    'warnings': ['firewalld ist nicht aktiv. Titan verändert keine andere Host-Firewall.']}
        scopes = lan_scopes() if ports else []
        desired = _requested(ports, scopes)
        ledger = host.load(_LEDGER, {})
        if not isinstance(ledger, dict) or len(ledger) > 8192 or any(not _valid_rule(row) for row in ledger.values()):
            raise Error('Titan-Firewallzustand ist ungültig; bestehende Regeln bleiben unverändert.', 503)
        for key, row in ledger.items():
            row['owners'] = [owner for owner in row['owners'] if owner != owner_key]
        for key, rule in desired.items():
            if key not in ledger:
                args = ['firewall-cmd', '--zone=' + rule['zone']]
                runtime = _query([*args, '--query-rich-rule=' + rule['rule']])
                permanent = _query([*args, '--permanent', '--query-rich-rule=' + rule['rule']])
                # Preserve runtime/permanent ownership separately: either half
                # may predate Titan, and runtime state can disappear on reload.
                ledger[key] = {**rule, 'owners': [], 'owned': not runtime and not permanent,
                               'runtime_owned': not runtime, 'permanent_owned': not permanent}
            if owner_key not in ledger[key]['owners']:
                ledger[key]['owners'].append(owner_key)
        host.save(_LEDGER, ledger)
        for key, row in list(ledger.items()):
            args = ['firewall-cmd', '--zone=' + row['zone']]
            for permanent, owned_key in ((False, 'runtime_owned'), (True, 'permanent_owned')):
                command = [*args, *(['--permanent'] if permanent else [])]
                owned = row.get(owned_key, row['owned'])
                if not owned:
                    continue
                exists = _query([*command, '--query-rich-rule=' + row['rule']])
                if row['owners'] and not exists:
                    _run([*command, '--add-rich-rule=' + row['rule']], timeout=3)
                elif not row['owners'] and exists:
                    _run([*command, '--remove-rich-rule=' + row['rule']], timeout=3)
            if not row['owners']:
                del ledger[key]
                host.save(_LEDGER, ledger)
        host.save(_LEDGER, ledger)
        warnings = [] if desired or not ports else ['Kein privates LAN-Netz erkannt. Keine öffentlichen Firewallports wurden geöffnet.']
        return {'available': True, 'managed_rules': len(desired), 'warnings': warnings}

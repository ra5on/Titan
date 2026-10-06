"""Bounded package RAM plans and fresh, fail-closed start/install checks.

MemFree is not usable capacity: MemAvailable includes reclaimable page cache.
Container ceilings are explicitly separate from observed consumption. Swap is
shown as a diagnostic, never counted as extra RAM for starting another package.
"""
from pathlib import Path
import math
import re
import shutil
import time
from xml.etree import ElementTree as ET

from .core import Error

MIB = 1024 ** 2
GIB = 1024 ** 3
INSTALL_HEADROOM = 512 * MIB


def vm_overhead(assigned):
    return max(256 * MIB, assigned // 20)


def vm_memory_reservations(run=None, tool_present=None):
    """Future RAM of all active libvirt guests, including paused foreign VMs.

    No virsh means this host cannot have a libvirt guest managed by Titan. An
    installed but unreachable hypervisor is unknown, never an invented zero.
    """
    present = bool(shutil.which('virsh', path='/usr/sbin:/usr/bin:/sbin:/bin')) if tool_present is None else tool_present
    if not present:
        return []
    if run is None:
        from .host import run
    base = ['virsh', '--connect', 'qemu:///system']
    try:
        raw = run([*base, 'list', '--uuid'], timeout=15)
        identifiers = [line.strip().lower() for line in raw.splitlines() if line.strip()]
        if len(identifiers) > 256 or any(not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', identifier) for identifier in identifiers):
            raise ValueError('Ungültige aktive VM-Liste.')
        result = []
        scales = {'b': 1, 'bytes': 1, 'kb': 1000, 'kilobytes': 1000,
                  'k': 1024, 'kib': 1024, 'kibibytes': 1024, 'mb': 1000 ** 2, 'megabytes': 1000 ** 2,
                  'm': MIB, 'mib': MIB, 'mebibytes': MIB, 'gb': 1000 ** 3, 'gigabytes': 1000 ** 3,
                  'g': GIB, 'gib': GIB, 'gibibytes': GIB, 'tb': 1000 ** 4, 'terabytes': 1000 ** 4,
                  't': 1024 ** 4, 'tib': 1024 ** 4, 'tebibytes': 1024 ** 4}
        for identifier in sorted(set(identifiers)):
            xml = run([*base, 'dumpxml', identifier], timeout=15)
            if not isinstance(xml, str) or len(xml) > 1024 * 1024 or '<!DOCTYPE' in xml or '<!ENTITY' in xml:
                raise ValueError('Ungültige VM-Definition.')
            root = ET.fromstring(xml)
            memory = root.find('memory')
            if root.tag != 'domain' or root.findtext('uuid', '').lower() != identifier or memory is None:
                raise ValueError('RAM der aktiven VM fehlt.')
            scale = scales.get(memory.get('unit', 'KiB').lower())
            value = (memory.text or '').strip()
            if scale is None or not re.fullmatch(r'[0-9]{1,18}', value):
                raise ValueError('Ungültige VM-RAM-Kapazität.')
            assigned = int(value) * scale
            if not 0 < assigned <= 2 ** 63 - 1:
                raise ValueError('Ungültige VM-RAM-Kapazität.')
            overhead = vm_overhead(assigned)
            result.append({'id': identifier, 'assigned_bytes': assigned, 'overhead_bytes': overhead, 'limit_bytes': assigned + overhead})
        return result
    except (Error, OSError, ValueError, TypeError, AttributeError, ET.ParseError):
        raise Error('Der RAM-Bedarf laufender virtueller Maschinen ist nicht sicher ermittelbar. Neue Dienste wurden angehalten; libvirt-Verbindung und VM-Status prüfen.', 503) from None


def _vm_limit_total(vms):
    total = 0
    seen = set()
    for vm in vms or []:
        if not isinstance(vm, dict) or not isinstance(vm.get('id'), str) or vm['id'] in seen:
            raise Error('Ungültiges VM-RAM-Budget.', 503)
        assigned, overhead, ceiling = vm.get('assigned_bytes'), vm.get('overhead_bytes'), vm.get('limit_bytes')
        if type(assigned) is not int or assigned <= 0 or type(overhead) is not int or overhead < vm_overhead(assigned) or type(ceiling) is not int or ceiling != assigned + overhead:
            raise Error('VM-RAM-Budget ist nicht vollständig messbar.', 503)
        total += ceiling
        seen.add(vm['id'])
    return total


def limit_bytes(value):
    if type(value) is int:
        return value if 0 < value <= 2 ** 63 - 1 else None
    match = re.fullmatch(r'([1-9][0-9]{0,3})([mg])', str(value))
    return int(match[1]) * (MIB if match[2] == 'm' else GIB) if match else None


def system_reserve(total):
    return min(GIB, max(512 * MIB, int(total * .15)))


def memory_snapshot(proc='/proc'):
    from .telemetry import Telemetry
    probe = Telemetry(proc=proc)
    try:
        result = probe._memory()
    except (OSError, ValueError, KeyError):
        raise Error('Der verfügbare Arbeitsspeicher ist nicht messbar. Die Installation wurde vor dem Download angehalten; Systemstatus prüfen.', 503) from None
    pressure, _ = probe._memory_pressure()
    return {**result, **pressure, 'telemetry_sampled_at': time.time()}


def memory_health(snapshot):
    """A full page cache alone is never a low-memory alarm."""
    total, available = snapshot.get('memory_total'), snapshot.get('memory_available')
    if not isinstance(total, (int, float)) or not isinstance(available, (int, float)) or not 0 <= available <= total or total <= 0:
        return {'level': 'unknown', 'label': 'RAM-Messung nicht verfügbar', 'message': 'Neue Installationen warten auf gültige Messwerte.'}
    reserve = system_reserve(total)
    pressure = snapshot.get('memory_pressure') or {}
    some, full = pressure.get('some_avg10'), pressure.get('full_avg10')
    stalled = ((isinstance(some, (int, float)) and math.isfinite(some) and some >= 20) or
               (isinstance(full, (int, float)) and math.isfinite(full) and full >= 5))
    recent_oom = snapshot.get('memory_oom_kills_delta', 0)
    if available < reserve or stalled:
        return {'level': 'critical', 'label': 'RAM-Engpass', 'message': 'Neue Installationen und zusätzliche Dienste werden angehalten. Laufende Apps bleiben unverändert.'}
    if available < reserve * 2 or isinstance(recent_oom, int) and recent_oom > 0:
        return {'level': 'warning', 'label': 'Wenig RAM-Reserve', 'message': 'Verfügbaren RAM und den Verbrauch der Apps prüfen, bevor weitere Dienste gestartet werden.'}
    return {'level': 'normal', 'label': 'RAM-Reserve vorhanden', 'message': 'Verfügbarer Speicher umfasst auch rückgewinnbaren Dateicache.'}


def package_memory_plan(app, options=None):
    from .app_packages import PACKAGES, RESOURCE_PROFILES, selected_recipe
    from .catalog import APPS
    if app not in APPS:
        raise Error('App-Vorlage nicht gefunden.', 404)
    options = options or {}
    recipe = selected_recipe(app, APPS[app], options)
    stack = recipe.get('stack')
    raw = stack['services'] if stack else {app: recipe}
    members = []
    for name, service in raw.items():
        ceiling = limit_bytes(service.get('memory', recipe['memory']))
        if ceiling is None:
            raise Error('Die App-Vorlage enthält kein gültiges RAM-Limit.', 503)
        members.append({'id': app if not stack or name == stack['primary'] else app + '-' + name.lower(),
            'service': name, 'limit_bytes': ceiling, 'one_shot': name == 'office-init'})
    # The seed container completes before Office starts, so count the larger
    # phase once. Summing both would invent simultaneous resource consumption.
    regular = sum(item['limit_bytes'] for item in members if not item['one_shot'])
    seed = sum(item['limit_bytes'] for item in members if item['one_shot'])
    office = next((item['limit_bytes'] for item in members if item['service'] == 'eurooffice'), 0)
    peak = max(regular, regular - office + seed)
    profile = options.get('resource_profile', 'legacy') if app in PACKAGES else 'legacy'
    return {'profile': profile, 'profile_label': RESOURCE_PROFILES[profile]['label'],
        'office_enabled': bool(office), 'container_count': len(members), 'services': members,
        'steady_limit_bytes': regular, 'startup_limit_bytes': peak,
        'installation_headroom_bytes': INSTALL_HEADROOM,
        'semantics': 'Container-Obergrenzen; kein gemessener oder reservierter Verbrauch.'}


def _container_rows(containers):
    if isinstance(containers, dict):
        return list(containers.values())
    return list(containers or [])


def _active(container):
    state = container.get('State', {})
    return isinstance(state, dict) and (state.get('Running') or state.get('Status') in ('running', 'restarting', 'paused'))


def _remaining(definition, containers):
    """Already running members must not be budgeted twice on a repair/start."""
    rows = _container_rows(containers)
    running = {str(row.get('Name', '')).lstrip('/') for row in rows if _active(row)}
    services = definition.get('services', {})
    required = []
    for key, service in services.items():
        if service.get('container_name', 'titan-' + key) in running:
            continue
        # Compose does not rerun an already successful, unchanged init service.
        if key.endswith('-office-init') and any(str(row.get('Name', '')).lstrip('/') == service.get('container_name') and
                row.get('State', {}).get('Status') == 'exited' and row.get('State', {}).get('ExitCode') == 0 for row in rows):
            continue
        ceiling = limit_bytes(service.get('mem_limit'))
        if ceiling is None:
            raise Error('Für einen zu startenden Dienst fehlt ein gültiges RAM-Limit. App-Einstellungen prüfen.', 409)
        required.append((key, ceiling))
    regular = sum(value for key, value in required if not key.endswith('-office-init'))
    seed = sum(value for key, value in required if key.endswith('-office-init'))
    office = sum(value for key, value in required if key.endswith('-eurooffice'))
    return max(regular, regular - office + seed)


def memory_preflight(snapshot, required_bytes, containers=None, installation=False, vms=None):
    total, available = snapshot.get('memory_total'), snapshot.get('memory_available')
    if type(total) is not int or type(available) is not int or total <= 0 or not 0 <= available <= total:
        raise Error('Gültige RAM-Messwerte fehlen. Neue Dienste wurden nicht gestartet.', 503)
    if type(required_bytes) is not int or required_bytes < 0:
        raise Error('Ungültiges RAM-Budget.', 503)
    reserve = system_reserve(total)
    extra = INSTALL_HEADROOM if installation else 0
    active_limits = [limit_bytes(row.get('HostConfig', {}).get('Memory'))
                     for row in _container_rows(containers) if _active(row)]
    if (required_bytes > 0 or installation) and any(value is None for value in active_limits):
        raise Error('Ein laufender Docker-Container hat kein gültiges RAM-Limit. Vor zusätzlichen Diensten für diesen Container eine endliche RAM-Grenze festlegen oder ihn stoppen. Das Gesamtbudget ist sonst nicht sicher ermittelbar.', 409)
    bounded_running = sum(value or 0 for value in active_limits)
    vm_limits = _vm_limit_total(vms)
    health = memory_health(snapshot)
    required = required_bytes + reserve + extra
    capacity_ok = bounded_running + vm_limits + required <= total
    available_ok = available >= required
    allowed = (required_bytes == 0 and not installation) or (capacity_ok and available_ok and health['level'] != 'critical')
    return {'allowed': allowed, 'health': health, 'available_bytes': available, 'total_bytes': total,
        'package_limit_bytes': required_bytes, 'running_limit_bytes': bounded_running,
        'running_vm_limit_bytes': vm_limits,
        'system_reserve_bytes': reserve, 'installation_headroom_bytes': extra,
        'required_available_bytes': required, 'limits_fit_capacity': capacity_ok,
        'semantics': 'Geprüfte Obergrenzen und Sicherheitsreserve; keine aktuelle RAM-Belegung.'}


def _enforce(result, office=False):
    if result['allowed']:
        return result
    gib = lambda value: f'{value / GIB:.1f}'.replace('.', ',')
    advice = 'Office abwählen oder mehr RAM zuweisen.' if office else 'Andere Apps oder VMs stoppen, ein kleineres RAM-Profil wählen oder mehr RAM zuweisen.'
    reason = 'Der Kernel meldet einen aktuellen RAM-Engpass.' if result['health']['level'] == 'critical' else 'Die Containergrenzen und die NAS-Reserve passen momentan nicht sicher in den Arbeitsspeicher.'
    commitments = f' Laufende Container: {gib(result["running_limit_bytes"])} GiB Obergrenzen; laufende VMs einschließlich Overhead: {gib(result["running_vm_limit_bytes"])} GiB Budget.' if not result['limits_fit_capacity'] else ''
    raise Error(f'{reason} Verfügbar: {gib(result["available_bytes"])} GiB; für diese Aktion einschließlich Reserve erforderlich: {gib(result["required_available_bytes"])} GiB.{commitments} {advice} Es wurden keine neuen Dienste gestartet.', 409)


def check_install_memory(app, options=None, containers=None, telemetry=None, proc='/proc', vms=None):
    plan = package_memory_plan(app, options)
    snapshot = telemetry if isinstance(telemetry, dict) else memory_snapshot(proc)
    vms = vm_memory_reservations() if vms is None else vms
    result = memory_preflight(snapshot, plan['startup_limit_bytes'], containers, installation=True, vms=vms)
    return {**_enforce(result, plan['office_enabled']), 'plan': plan}


def check_start_memory(app, options, definition, containers=None, telemetry=None, proc='/proc', installation=False, vms=None):
    snapshot = telemetry if isinstance(telemetry, dict) else memory_snapshot(proc)
    if telemetry is not None and not isinstance(telemetry, dict) and hasattr(telemetry, 'sample'):
        recent = telemetry.sample()
        snapshot['memory_oom_kills_delta'] = recent.get('memory_oom_kills_delta', 0)
    vms = vm_memory_reservations() if vms is None else vms
    result = memory_preflight(snapshot, _remaining(definition, containers), containers, installation, vms=vms)
    return _enforce(result, any(key.endswith('-eurooffice') for key in definition.get('services', {})))


def check_vm_start_memory(requested_bytes, containers=None, vms=None, telemetry=None, proc='/proc', vm=None):
    if type(requested_bytes) is not int or not 0 < requested_bytes <= 2 ** 63 - 1:
        raise Error('Die RAM-Zuweisung der VM ist nicht sicher ermittelbar.', 503)
    snapshot = telemetry if isinstance(telemetry, dict) else memory_snapshot(proc)
    vms = vm_memory_reservations() if vms is None else vms
    _vm_limit_total(vms)
    required = 0 if vm is not None and any(item.get('id') == vm for item in vms) else requested_bytes + vm_overhead(requested_bytes)
    result = memory_preflight(snapshot, required, containers, vms=vms)
    return _enforce(result)


def check_container_start_memory(memory_limit, containers=None, vms=None, telemetry=None, proc='/proc', container=None, installation=False):
    """Budget manual containers by finite limits and immutable Docker IDs.

    An active target has already contributed its limit to the running budget.
    Names never exempt a stopped/new/replaced container from the additional
    allocation check. Changing an active limit requires stopping it first.
    """
    ceiling = limit_bytes(memory_limit)
    if ceiling is None:
        raise Error('Für diesen Container fehlt ein gültiges RAM-Limit. Vor dem Start oder Neustart eine endliche RAM-Grenze in den Container-Einstellungen festlegen.', 409)
    rows = _container_rows(containers)
    required = ceiling
    if container is not None:
        if not isinstance(container, str) or not re.fullmatch(r'[a-f0-9]{64}', container):
            raise Error('Die Container-ID für die RAM-Prüfung ist ungültig.', 503)
        matches = [row for row in rows if row.get('Id') == container]
        if len(matches) != 1:
            raise Error('Der gewählte Container ist für die RAM-Prüfung nicht eindeutig ermittelbar.', 503)
        target = matches[0]
        if limit_bytes(target.get('HostConfig', {}).get('Memory')) != ceiling:
            raise Error('Die RAM-Grenze des Containers hat sich geändert. Container neu laden und vor einer Änderung seiner RAM-Zuweisung stoppen.', 409)
        if _active(target):
            required = 0
    snapshot = telemetry if isinstance(telemetry, dict) else memory_snapshot(proc)
    vms = vm_memory_reservations() if vms is None else vms
    result = memory_preflight(snapshot, required, rows, installation, vms=vms)
    return _enforce(result)

"""Small support report from explicit status fields; never dump config or logs."""
import math
import time
from . import __version__, __release_stage__


def numeric(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def report(agent, demo=False):
    result = {'format': 'titan-diagnostics-v1', 'version': __version__,
              'stage': __release_stage__, 'generated_at': time.time(), 'demo': bool(demo),
              'system': {}, 'components': {}, 'errors': []}
    try:
        status = agent.call('status')
        result['system'] = {key: numeric(status.get(key)) for key in (
            'uptime', 'cpus', 'load', 'cpu_percent', 'memory_total', 'memory_used',
            'memory_available', 'swap_total', 'swap_used', 'cpu_temperature', 'telemetry_sampled_at')}
        result['system']['services'] = {name: {key: item.get(key) for key in (
            'installed', 'active', 'configured', 'relevant', 'state') if type(item.get(key)) in (bool, str)}
            for name, item in status.get('service_details', {}).items() if isinstance(item, dict)}
    except Exception as exc:
        result['errors'].append({'section': 'system', 'error': type(exc).__name__})
    try:
        components = agent.call('components').get('components', {})
        for name in ('docker', 'vms'):
            item = components.get(name, {})
            result['components'][name] = {key: item[key] for key in (
                'installed', 'available', 'daemon', 'compose', 'kvm') if type(item.get(key)) is bool}
            missing = item.get('missing', [])
            result['components'][name]['missing'] = [str(value)[:100] for value in missing if isinstance(value, str)]
    except Exception as exc:
        result['errors'].append({'section': 'components', 'error': type(exc).__name__})
    return result

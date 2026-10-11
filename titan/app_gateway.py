"""An independently configured Caddy gateway for authentication-only packages."""
import copy
import re
from .app_access import app_id
from .core import Error

IMAGE = 'caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d'


def configuration(app, target, port):
    app_id(app)
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,100}', target) or type(port) is not int or not 1 <= port <= 65535:
        raise Error('Ungültiges App-Gateway-Ziel.')
    return '''{
    admin off
    auto_https off
}
http://:%d {
    route {
        handle /_titan/authorize {
            reverse_proxy host.docker.internal:5101 {
                rewrite /apps/internal/redeem?app=%s&ticket={query.ticket}
                header_up -Cookie
            }
        }
        request_header -X-Titan-Upstream-Cookie
        forward_auth host.docker.internal:5101 {
            uri /apps/internal/verify?app=%s
            copy_headers X-Titan-Upstream-Cookie
        }
        request_header -Cookie
        reverse_proxy %s:%d {
            header_up Cookie {http.request.header.X-Titan-Upstream-Cookie}
            header_up -X-Titan-*
            header_down Set-Cookie "(?i)^(titan_|__host-titan|__secure-titan)[^=]*=.*$" ""
        }
    }
}
''' % (port, app, app, target, port)


def wrap(definition, app, recipe):
    """Keep the app's stateful services private; publish only the auth gateway.

    Called after hardware assignment so devices remain attached to the backend.
    The gateway is the observed primary, using the existing public port contract.
    """
    if not recipe.get('app_gateway'):
        return definition
    result = copy.deepcopy(definition)
    services = result['services']
    if app + '-backend' in services:
        raise Error('App-Dienst kollidiert mit dem geschützten Zugang.')
    backend = services.pop(app)
    if backend.get('network_mode') or set(backend.get('networks', {})) != {'default'}:
        raise Error('Geschützte Apps benötigen ihr isoliertes Standardnetz.')
    target = app + '-backend'
    public = []
    remaining = []
    for mapping in backend.get('ports', []):
        if isinstance(mapping, str) and mapping.endswith(':' + str(recipe['port']) + '/tcp'):
            public.append(mapping)
        else:
            remaining.append(mapping)
    if len(public) != 1 or remaining or any(service.get('ports') for service in services.values()):
        raise Error('Geschützte Apps dürfen keinen zusätzlichen öffentlichen Zugang besitzen.')
    backend['ports'] = []
    backend['container_name'] = 'titan-' + target
    services[target] = backend
    for service in services.values():
        depends = service.get('depends_on')
        if isinstance(depends, dict) and app in depends:
            depends[target] = depends.pop(app)
        elif isinstance(depends, list):
            service['depends_on'] = [target if name == app else name for name in depends]
        if service.get('links'):
            service['links'] = [target + value[len(app):] if value == app or value.startswith(app + ':') else value for value in service['links']]
    services[app] = {
        'image': IMAGE, 'container_name': 'titan-' + app, 'restart': 'unless-stopped',
        'labels': {'io.titan.managed': 'true', 'io.titan.app': app},
        'networks': {'default': {}}, 'extra_hosts': ['host.docker.internal:host-gateway'],
        'ports': public, 'volumes': [], 'read_only': True,
        'tmpfs': ['/tmp', '/data', '/config'], 'cap_drop': ['ALL'],
        # The official binary carries this file capability; dropping its
        # bounding-set entry prevents execve itself, even on an unprivileged port.
        'cap_add': ['NET_BIND_SERVICE'],
        'security_opt': ['no-new-privileges:true'], 'mem_limit': '128m', 'cpus': 1,
        'environment': {'TITAN_GATEWAY_CONFIG': configuration(app, target, recipe['port']).replace('$', '$$')},
        'entrypoint': ['/bin/sh', '-ec'],
        'command': ['printf "%s" "$$TITAN_GATEWAY_CONFIG" > /tmp/Caddyfile; exec caddy run --config /tmp/Caddyfile --adapter caddyfile'],
        'depends_on': {target: {'condition': 'service_started'}},
        'logging': {'driver': 'json-file', 'options': {'max-size': '10m', 'max-file': '3'}},
    }
    return result

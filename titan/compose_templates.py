"""Translate a bounded Compose subset into private Titan app directories."""
import copy
import ipaddress
import re
from .core import Error

NAME=r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}'
IMAGE=r'[a-z0-9][a-z0-9./_-]*(?::[A-Za-z0-9_.-]+(?:@sha256:[a-f0-9]{64})?|@sha256:[a-f0-9]{64})'
MAX_SERVICES = 16
MAX_PORTS = 64


class UnsupportedTemplate(Error):
    """An app-specific requirement, separate from a failed catalog download."""
    def __init__(self, message, code='unsupported', requirements=None):
        super().__init__(message)
        self.code = code
        self.requirements = requirements or []


def memory_size(value):
    """Docker memory units, normalized to integral MiB for Titan's RAM budget."""
    if type(value) is int:
        size = value
    else:
        match = re.fullmatch(r'([0-9]{1,12})(?:\.([0-9]{1,3}))?\s*(b|k|kb|ki|kib|m|mb|mi|mib|g|gb|gi|gib)?', str(value).strip().lower())
        if not match: raise Error('Ungültiges Container-Speicherlimit.')
        from decimal import Decimal
        number = Decimal(match[1] + ('.' + match[2] if match[2] else ''))
        unit = match[3] or 'b'
        factor = 1 if unit == 'b' else 1024 if unit.startswith('k') else 1024 ** 2 if unit.startswith('m') else 1024 ** 3
        size = int(number * factor)
    if not 0 < size <= 64 * 1024 ** 3 or size % (1024 ** 2):
        raise Error('Container-Speicher muss in ganzen MiB zwischen 1 MiB und 64 GiB liegen.')
    return str(size // (1024 ** 3)) + 'g' if size % (1024 ** 3) == 0 else str(size // (1024 ** 2)) + 'm'


def duration(value):
    """Validate bounded compound Go durations without rounding their semantics."""
    value = str(value)
    if len(value) > 48 or not re.fullmatch(r'(?:[0-9]{1,8}(?:\.[0-9]{1,6})?(?:ns|us|µs|ms|s|m|h))+', value):
        raise Error('Ungültiges Healthcheck-/Zeitintervall.')
    from decimal import Decimal
    scales = {'ns': Decimal('0.000000001'), 'us': Decimal('0.000001'), 'µs': Decimal('0.000001'), 'ms': Decimal('.001'), 's': 1, 'm': 60, 'h': 3600}
    seconds = sum(Decimal(number) * scales[unit] for number, unit in re.findall(r'([0-9]+(?:\.[0-9]+)?)(ns|us|µs|ms|s|m|h)', value))
    if not 0 < seconds <= 86400: raise Error('Zeitintervall muss größer als null und höchstens einen Tag lang sein.')
    return value


def host_ip(value):
    if value in (None, ''): return None
    try: address = ipaddress.ip_address(value)
    except ValueError: raise Error('Ungültige Port-Bindeadresse.') from None
    if address.is_multicast: raise Error('Multicast-Adresse ist keine Port-Bindeadresse.')
    return str(address)


def port_mappings(value):
    """Expand only static, equal-length port ranges. Keep loopback bindings."""
    if isinstance(value, int): value = str(value)
    if isinstance(value, str):
        raw, _, protocol = value.partition('/')
        protocol = protocol or 'tcp'
        parts = raw.split(':')
        if len(parts) == 1: published = target = parts[0]; address = None
        elif len(parts) == 2: published, target = parts; address = None
        elif len(parts) == 3: address, published, target = parts
        else: raise UnsupportedTemplate('Dynamische Ports oder diese Bindeadresse benötigen eine eigene Einrichtung.', 'ports')
    elif isinstance(value, dict):
        unknown = set(value) - {'target', 'published', 'protocol', 'host_ip', 'name', 'app_protocol', 'mode'}
        if unknown or value.get('mode', 'ingress') != 'ingress':
            raise UnsupportedTemplate('Besondere Portoptionen: ' + ', '.join(sorted(unknown or {'mode'})), 'ports')
        target = value['target']; published = value.get('published', target)
        protocol = value.get('protocol', 'tcp'); address = value.get('host_ip')
    else: raise Error('Ungültige Portzuordnung.')
    if protocol not in ('tcp', 'udp'): raise UnsupportedTemplate('Nur TCP- und UDP-Ports werden unterstützt.', 'ports')
    address = host_ip(address)
    def sequence(raw):
        if not re.fullmatch(r'[0-9]{1,5}(?:-[0-9]{1,5})?', str(raw)):
            raise UnsupportedTemplate('Dynamischer Port benötigt eine konkrete Portnummer.', 'ports')
        bounds = list(map(int, str(raw).split('-'))); start, end = bounds[0], bounds[-1]
        if not 1 <= start <= end <= 65535 or end - start >= MAX_PORTS:
            raise UnsupportedTemplate('Portbereich muss zwischen 1 und 65535 liegen und höchstens 64 Ports enthalten.', 'ports')
        return range(start, end + 1)
    targets, publications = sequence(target), sequence(published)
    if len(targets) != len(publications): raise UnsupportedTemplate('Interner und externer Portbereich müssen gleich groß sein.', 'ports')
    return [{'target': target, 'published': published, 'protocol': protocol, **({'host_ip': address} if address else {})}
            for target, published in zip(targets, publications)]


def private_networks(document):
    definitions = document.get('networks') or {}
    if not isinstance(definitions, dict) or len(definitions) > 8: raise UnsupportedTemplate('Höchstens acht private App-Netze werden unterstützt.', 'network')
    result = {}
    for name, definition in definitions.items():
        definition = definition or {}
        if not re.fullmatch(NAME, name) or not isinstance(definition, dict): raise Error('Ungültiges App-Netzwerk.')
        if set(definition) - {'driver', 'internal', 'name'} or definition.get('driver', 'bridge') != 'bridge':
            raise UnsupportedTemplate('Externes Netzwerk, IPAM oder besonderer Netzwerktreiber benötigt eine eigene Einrichtung.', 'network', [{'kind': 'network', 'name': name}])
        if type(definition.get('internal', False)) is not bool: raise Error('Ungültige interne Netzwerkeinstellung.')
        # Source names describe a local stack network, not a pre-existing host
        # network. Scope them to this Titan installation to avoid collisions.
        if definition.get('name') and (not isinstance(definition['name'], str) or not re.fullmatch(NAME, definition['name'])): raise Error('Ungültiger Netzwerkname.')
        result[name] = {'driver': 'bridge', **({'internal': True} if definition.get('internal') else {})}
    return result

def validate_stack(value):
    if not isinstance(value,dict) or set(value)-{'primary','services','networks'} or not {'primary','services'} <= set(value) or not isinstance(value['services'],dict) or not 1<=len(value['services'])<=MAX_SERVICES or value['primary'] not in value['services']: raise Error('Ungültiger App-Containerverbund.')
    networks = private_networks(value)
    if len({name.lower() for name in value['services']})!=len(value['services']): raise Error('Container-Namen sind nicht eindeutig.')
    for name,service in value['services'].items():
        if not isinstance(name,str) or not re.fullmatch(NAME,name) or not isinstance(service,dict) or set(service)-{'image','environment','mounts','command','entrypoint','depends_on','ports','healthcheck','memory','shm_size','user','aliases','read_only','init','cap_drop','security_opt','tmpfs','expose','stop_grace_period','stop_signal','tty','stdin_open','working_dir','networks','links','memory_reservation','restart'}: raise Error('Nicht unterstützte Containeroption.')
        if not isinstance(service.get('aliases', []), list) or len(service.get('aliases', [])) > 4 or any(not isinstance(alias, str) or not re.fullmatch(NAME, alias) for alias in service.get('aliases', [])): raise Error('Ungültiger interner Netzwerkname.')
        if not isinstance(service.get('image'),str) or not re.fullmatch(IMAGE,service['image']): raise Error('Ungültiges Container-Image.')
        if 'user' in service and (not isinstance(service['user'], str) or not re.fullmatch(r'[0-9]{1,9}(?::[0-9]{1,9})?', service['user'])): raise Error('Nur numerische Container-Benutzer unterstützt.')
        for key in ('memory', 'shm_size'):
            if key in service: memory_size(service[key])
        if 'memory_reservation' in service: memory_size(service['memory_reservation'])
        for key in ('read_only', 'init', 'tty', 'stdin_open'):
            if key in service and type(service[key]) is not bool: raise Error('Ungültige Containeroption: ' + key)
        for key in ('cap_drop', 'security_opt', 'tmpfs', 'expose', 'links'):
            if key in service and (not isinstance(service[key], list) or len(service[key]) > 32 or any(not isinstance(part, str) or len(part) > 200 for part in service[key])): raise Error('Ungültige Containeroption: ' + key)
        if any(not re.fullmatch(r'(?:ALL|[A-Z][A-Z0-9_]{1,40})', part) for part in service.get('cap_drop', [])): raise Error('Ungültige entzogene Fähigkeit.')
        if any(part != 'no-new-privileges:true' for part in service.get('security_opt', [])): raise Error('Nicht unterstützte Sicherheitsoption.')
        if any(not re.fullmatch(r'/(?:[A-Za-z0-9_.-]+/?)+(?::(?:rw|ro|noexec|nosuid|nodev|size=[1-9][0-9]{0,3}[mg]|mode=0[0-7]{3})(?:,(?:rw|ro|noexec|nosuid|nodev|size=[1-9][0-9]{0,3}[mg]|mode=0[0-7]{3}))*)?', part) or '..' in part.split(':')[0].split('/') or part.startswith(('/proc', '/sys', '/dev', '/run')) for part in service.get('tmpfs', [])): raise Error('Nicht unterstütztes temporäres Dateisystem.')
        if any(not re.fullmatch(r'[0-9]{1,5}(?:/(?:tcp|udp))?', part) or not 1 <= int(part.split('/')[0]) <= 65535 for part in service.get('expose', [])): raise Error('Ungültiger interner Port.')
        if 'stop_grace_period' in service: duration(service['stop_grace_period'])
        if 'stop_signal' in service and not re.fullmatch(r'SIG[A-Z0-9]{1,12}', service['stop_signal']): raise Error('Ungültiges Stoppsignal.')
        if 'working_dir' in service and (not isinstance(service['working_dir'], str) or not re.fullmatch(r'/[A-Za-z0-9_./-]{0,199}', service['working_dir']) or '..' in service['working_dir'].split('/')): raise Error('Ungültiges Arbeitsverzeichnis.')
        if service.get('restart', 'unless-stopped') not in ('unless-stopped', 'always', 'on-failure', 'no'): raise Error('Ungültige Neustartregel.')
        attached = service.get('networks', {})
        if not isinstance(attached, dict) or set(attached) - (set(networks) | {'default'}): raise Error('Ungültige Netzzuordnung.')
        for options in attached.values():
            if not isinstance(options, dict) or set(options) - {'aliases'} or not isinstance(options.get('aliases', []), list) or len(options.get('aliases', [])) > 8 or any(not re.fullmatch(NAME, alias) for alias in options.get('aliases', [])): raise Error('Ungültige Netzwerk-Aliase.')
        for link in service.get('links', []):
            parts = link.split(':')
            if len(parts) > 2 or parts[0] not in value['services'] or any(not re.fullmatch(NAME, part) for part in parts): raise Error('Ungültiger interner Dienstlink.')
        env=service.get('environment',{})
        if not isinstance(env,dict) or len(env)>64 or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',key) or not isinstance(val,str) or len(val)>1000 or '\0' in val for key,val in env.items()): raise Error('Ungültige Container-Umgebung.')
        for mount in service.get('mounts',[]):
            if not isinstance(mount,dict) or set(mount)!={'slot','target','readonly'} or not isinstance(mount['slot'],str) or not re.fullmatch(r'[a-z0-9_-]{1,50}',mount['slot']) or not isinstance(mount['target'],str) or not mount['target'].startswith('/') or '..' in mount['target'].split('/') or '\0' in mount['target'] or len(mount['target'])>200 or mount['target'].startswith(('/proc','/sys','/dev','/run')) or type(mount['readonly']) is not bool: raise Error('Ungültige Container-Dateizuordnung.')
        for key in ('command','entrypoint'):
            command=service.get(key)
            if command is not None and (not isinstance(command,list) or not 1<=len(command)<=64 or any(not isinstance(part,str) or len(part)>2000 or '$' in part.replace('$$', '') or '\0' in part for part in command)): raise Error('Dynamische Container-Kommandos nicht unterstützt.')
        dependencies=service.get('depends_on',[])
        if not isinstance(dependencies,(list,dict)) or len(dependencies)>MAX_SERVICES: raise Error('Ungültige Container-Abhängigkeiten.')
        if isinstance(dependencies,dict):
            for dependency,options in dependencies.items():
                if not isinstance(options,dict) or set(options)!={'condition'} or options['condition'] not in ('service_started','service_healthy','service_completed_successfully'): raise Error('Ungültige Startbedingung.')
                if options['condition']=='service_healthy' and not value['services'].get(dependency,{}).get('healthcheck'): raise Error('Startbedingung benötigt einen Healthcheck.')
        for dependency in dependencies:
            if dependency not in value['services'] or dependency==name: raise Error('Ungültige Container-Abhängigkeit.')
        if not isinstance(service.get("mounts",[]),list) or len(service.get("mounts",[]))>32 or not isinstance(service.get("ports",[]),list) or len(service.get("ports",[]))>MAX_PORTS: raise Error("Zu viele Container-Datei-/Portzuordnungen.")
        for mapping in service.get('ports',[]):
            if not isinstance(mapping,dict) or set(mapping)-{'target','published','protocol','host_ip'} or not {'target','published','protocol'} <= set(mapping) or mapping['protocol'] not in ('tcp','udp') or any(type(mapping[k]) is not int or not 1<=mapping[k]<=65535 for k in ('target','published')): raise Error('Ungültiger Container-Port.')
            if mapping.get('host_ip'): host_ip(mapping['host_ip'])
        if len({(mapping['target'],mapping['protocol']) for mapping in service.get('ports',[])}) != len(service.get('ports',[])):
            raise UnsupportedTemplate('Mehrere Veröffentlichungen desselben Container-Ports benötigen eine eigene Portkonfiguration.', 'ports')
        health=service.get('healthcheck')
        if health is not None:
            if not isinstance(health,dict) or set(health)-{'test','interval','timeout','start_period','start_interval','retries'} or not isinstance(health.get('test'),list) or not health['test'] or health['test'][0] not in ('CMD','CMD-SHELL','NONE') or any(not isinstance(v,str) or '$' in v.replace('$$', '') or len(v)>2000 or '\0' in v for v in health['test']): raise Error('Nicht unterstützter Healthcheck.')
            for key in ('interval','timeout','start_period','start_interval'):
                if key in health: duration(health[key])
            if 'retries' in health and (type(health['retries']) is not int or not 1<=health['retries']<=100): raise Error('Ungültige Healthcheck-Wiederholungen.')
    # Detect dependency cycles before Compose can create partial resources.
    def visit(name,parents):
        if name in parents: raise Error('Zyklische Container-Abhängigkeit.')
        for child in value['services'][name].get('depends_on',[]): visit(child,parents|{name})
    for name in value['services']: visit(name,set())
    return value


def build(app_id, recipe, directory, uid, gid, port, data_path, options, config_path=None):
    from .app_packages import selected_recipe
    recipe = selected_recipe(app_id, recipe, options)
    stack=validate_stack(recipe['stack']);primary=stack['primary']; names={key:app_id if key==primary else app_id+'-'+key.lower() for key in stack['services']};services={}
    for name,template in stack['services'].items():
        identifier=names[name];service={'image':template['image'],'container_name':'titan-'+identifier,'restart':template.get('restart','unless-stopped'),'mem_limit':template.get('memory',recipe['memory']),'cpus':2,'logging':{'driver':'json-file','options':{'max-size':'10m','max-file':'3'}},'labels':{'io.titan.managed':'true','io.titan.app':app_id},'networks':copy.deepcopy(template.get('networks') or {'default':{}}),'environment':{},'volumes':[],'ports':[]}
        for net_options in service['networks'].values():
            net_options['aliases'] = list(dict.fromkeys([name] + template.get('aliases', []) + net_options.get('aliases', [])))
        if any(isinstance(other.get('depends_on'),dict) and other['depends_on'].get(name,{}).get('condition') == 'service_completed_successfully' for other in stack['services'].values()):
            service['restart'] = 'no'
        for key,value in template.get('environment',{}).items():
            if value=='@uid': value=str(uid)
            elif value=='@gid': value=str(gid)
            elif value.startswith('@option:'):
                if value[8:] not in options: raise Error('Private App-Einstellungen fehlen; Installation erneut versuchen.')
                value=str(options[value[8:]])
            service['environment'][key]=value.replace('$','$$')
        for mount in template.get('mounts',[]):
            source=data_path if mount['slot']=='data' else str(config_path or directory+'/config')+'/'+mount['slot']
            service['volumes'].append({'type':'bind','source':str(source),'target':mount['target'],'read_only':mount['readonly'],'bind':{'create_host_path':False}})
        for mapping in template.get('ports',[]):
            published=port if recipe.get('web_available', True) and name==primary and mapping['target']==recipe['port'] and mapping['protocol']=='tcp' else options['stack_port_'+name+'_'+str(mapping['target'])+'_'+mapping['protocol']]
            address = mapping.get('host_ip')
            prefix = ('[' + address + ']' if ':' in address else address) + ':' if address else ''
            service['ports'].append(prefix+str(published)+':'+str(mapping['target'])+'/'+mapping['protocol'])
        for key in ('command','entrypoint','healthcheck','shm_size','user','read_only','init','cap_drop','security_opt','tmpfs','expose','stop_grace_period','stop_signal','tty','stdin_open','working_dir'):
            if key in template: service[key]=copy.deepcopy(template[key])
        if template.get('memory_reservation'): service['mem_reservation'] = template['memory_reservation']
        if template.get('links'):
            service['links'] = [names[part.split(':')[0]] + (':' + part.split(':')[1] if ':' in part else '') for part in template['links']]
        if template.get('depends_on'):
            dependency=template['depends_on']
            service['depends_on']={names[key]:options for key,options in dependency.items()} if isinstance(dependency,dict) else [names[key] for key in dependency]
        services[identifier]=service
    networks = copy.deepcopy(stack.get('networks', {}))
    if networks and any('default' in service['networks'] for service in services.values()): networks.setdefault('default', {'driver':'bridge'})
    return {'services':services, **({'networks':networks} if networks else {})}


def translate(doc,label,repository):
    """Convert source paths to managed slots and expose ports/env as form fields."""
    import shlex
    from .store_sources import line,localized,port,slug,login
    raw=doc.get('services',{})
    if not isinstance(raw,dict) or not 1<=len(raw)<=MAX_SERVICES: raise Error('Maximal 16 Container pro App.')
    meta=doc.get('x-casaos',{})
    web_value = meta.get('port_map', '')
    web = port(web_value)[0] if web_value not in ('', None, 0, '0') else None
    primary=meta.get('main');primary=primary if primary in raw else None
    networks = private_networks(doc)
    translated={};settings=[];extra=[];slots={};setting_groups={}
    for name,source in raw.items():
        ignored={'container_name','restart','labels','deploy','x-casaos','cpu_shares','mem_limit','hostname','network_mode','networks','logging'}
        supported={'image','environment','ports','volumes','command','entrypoint','depends_on','healthcheck','user','shm_size','read_only','init','cap_drop','security_opt','tmpfs','expose','stop_grace_period','stop_signal','tty','stdin_open','working_dir','links'}
        if not isinstance(source,dict): raise Error('Ungültiger Stack-Dienst.')
        unknown = set(source)-ignored-supported
        if unknown:
            requirements = [{'kind': 'devices' if key == 'devices' else 'host_namespace' if key in ('pid','cgroup','ipc') else 'capabilities' if key == 'cap_add' else 'privileged' if key == 'privileged' else 'runtime_option', 'service': name, 'option': key} for key in sorted(unknown)]
            raise UnsupportedTemplate('Zusätzliche Einrichtung erforderlich: ' + ', '.join(sorted(unknown)), 'permissions' if any(row['kind'] != 'runtime_option' for row in requirements) else 'runtime_options', requirements)
        if source.get('network_mode') not in (None,'bridge','host'): raise UnsupportedTemplate('Besonderer Netzwerk-Namensraum erforderlich: ' + str(source['network_mode']), 'network', [{'kind':'network_namespace','service':name,'mode':source['network_mode']}])
        if source.get('network_mode')=='host' and len(raw)>1: raise Error('Host-Netz für Containerverbünde nicht unterstützt.')
        if 'user' in source:
            entry_user = str(source['user'])
            entry_user = ':'.join('0' if part == 'root' else part for part in entry_user.split(':'))
            if not re.fullmatch(r'[0-9]{1,9}(?::[0-9]{1,9})?', entry_user): raise UnsupportedTemplate('Container-Benutzer muss vor Einrichtung der Datenordner aus dem Image aufgelöst werden: ' + entry_user, 'container_user', [{'kind':'container_user','service':name,'user':entry_user}])
        else: entry_user = None
        image=source['image'];image=image if ':' in image or '@' in image else image+':latest';entry={'image':image,'environment':{},'mounts':[],'ports':[]}
        # Upstream environment values may refer to the original container name.
        # Retain it only as DNS inside this stack's private network.
        if source.get('container_name'): entry['aliases'] = [source['container_name']]
        if source.get('hostname'): entry.setdefault('aliases', []).append(source['hostname'])
        if entry_user is not None: entry['user'] = entry_user
        if 'shm_size' in source: entry['shm_size'] = memory_size(source['shm_size'])
        for key in ('read_only','init','cap_drop','tmpfs','expose','stop_grace_period','stop_signal','tty','stdin_open','working_dir','links'):
            if key in source: entry[key] = copy.deepcopy(source[key])
        if 'expose' in entry: entry['expose'] = [str(value) for value in entry['expose']]
        if 'security_opt' in source:
            entry['security_opt'] = ['no-new-privileges:true' if value == 'no-new-privileges' else value for value in source['security_opt']]
        if 'mem_limit' in source: entry['memory'] = memory_size(source['mem_limit'])
        deploy = source.get('deploy') or {}
        if deploy:
            if not isinstance(deploy, dict) or set(deploy) - {'resources'} or set(deploy.get('resources', {})) - {'limits','reservations'}:
                raise UnsupportedTemplate('Zusätzliche Deploy-Regeln benötigen eine eigene Vorlage.', 'runtime_options')
            for key, output in (('limits', 'memory'), ('reservations', 'memory_reservation')):
                definition = deploy.get('resources', {}).get(key) or {}
                if not isinstance(definition, dict) or set(definition) - {'memory'}: raise UnsupportedTemplate('Zusätzliche Ressourcenregeln benötigen eine eigene Vorlage.', 'runtime_options')
                if 'memory' in definition: entry[output] = memory_size(definition['memory'])
        if source.get('restart') is not None:
            entry['restart'] = 'no' if source['restart'] is False else str(source['restart'])
        attached = source.get('networks')
        if attached:
            if isinstance(attached, list): attached = {key:{} for key in attached}
            if not isinstance(attached, dict): raise Error('Ungültige Netzwerkzuordnung.')
            for network, options in attached.items():
                if network not in networks:
                    networks[network] = {'driver':'bridge'}
                if not isinstance(options or {}, dict) or set(options or {}) - {'aliases'}: raise UnsupportedTemplate('Statische IP- oder besondere Netzwerkoptionen benötigen eine eigene Einrichtung.', 'network', [{'kind':'network_options','service':name,'network':network}])
            entry['networks'] = {key: options or {} for key, options in attached.items()}
        for mapping in source.get('ports',[]):
            entry['ports'].extend(port_mappings(mapping))
        if any(mapping['published'] == web and mapping['protocol'] == 'tcp' for mapping in entry['ports']): primary=primary or name
        if source.get('network_mode')=='host' and not entry['ports'] and web: entry['ports']=[{'published':web,'target':web,'protocol':'tcp'}];primary=name
        for mapping in source.get('volumes',[]):
            if isinstance(mapping,str):
                parts=mapping.split(':')
                if len(parts) not in (2,3) or len(parts)==3 and parts[2] not in ('ro','rw'): raise Error('Besondere Volume-Optionen erforderlich.')
                original,target=parts[:2];readonly=len(parts)==3 and parts[2]=='ro'
            elif isinstance(mapping,dict) and not set(mapping)-{'type','source','target','read_only'} and mapping.get('type','bind') in ('bind','volume'): original,target=mapping['source'],mapping['target'];readonly=mapping.get('read_only',False)
            else: raise Error('Nicht unterstützte Dateizuordnung.')
            if original.startswith(('/dev','/proc','/sys','/etc','/var/run','/run','/lib')): raise UnsupportedTemplate('Host-Zugriff erforderlich: ' + original + ' → ' + target, 'host_mount', [{'kind': 'docker_socket' if original == '/var/run/docker.sock' else 'device' if original.startswith('/dev/') else 'host_path', 'service': name, 'source':original,'target':target,'readonly':readonly}])
            # Only the primary application's user files belong in the NAS data
            # directory. Dependency /data volumes (Redis, databases) are private
            # config mounts with their own numeric container owner.
            if original not in slots: slots[original]='data' if name == primary and target in ('/data','/media','/downloads','/files','/storage') and 'data' not in slots.values() else 'mount-'+str(len(slots)+1)
            entry['mounts'].append({'slot':slots[original],'target':target,'readonly':readonly})
        env=source.get('environment',{})
        if isinstance(env,list): env=dict(part.split('=',1) for part in env)
        for key,value in env.items():
            if key=='PUID': entry['environment'][key]='@uid';continue
            if key=='PGID': entry['environment'][key]='@gid';continue
            value='' if value is None else ('true' if value is True else 'false' if value is False else str(value))
            if key=='TZ' and '$' in value.replace('$$', ''): value='Europe/Berlin'
            value=re.sub(r'\$\{[A-Za-z_][A-Za-z0-9_]*:-([^{}]*)\}',r'\1',value)
            from .app_credentials import secret_name
            secret=secret_name(key)
            # Keep literal dependency names/database identifiers paired with
            # upstream commands and healthchecks. Only credentials, unresolved
            # inputs and the app administrator are exposed as form fields.
            if not secret and '$' not in value and key != 'NEXTCLOUD_ADMIN_USER':
                entry['environment'][key] = value
                continue
            # Client and database images use different keys for the same
            # upstream password. Couple only known database-password aliases
            # with an identical source value; keep admin/root secrets separate.
            group_key = 'DATABASE_PASSWORD' if key in ('DB_PASSWORD', 'POSTGRES_PASSWORD', 'MYSQL_PASSWORD', 'MARIADB_PASSWORD') else key
            group=(group_key,value)
            if group not in setting_groups:
                option='stack_env_'+str(len(settings));setting_groups[group]=option
                labels={'POSTGRES_PASSWORD':'Datenbankpasswort','DB_PASSWORD':'Datenbankpasswort','NEXTCLOUD_ADMIN_USER':'Nextcloud Administrator','NEXTCLOUD_ADMIN_PASSWORD':'Nextcloud Admin-Passwort'}
                settings.append({'key':option,'label':labels.get(key,key)+' · '+name,'type':'password' if secret else 'text','default':'' if secret or '$' in value.replace('$$', '') else value,'required':True,'min_length':1 if secret or '$' in value.replace('$$', '') else 0,'max_length':1000})
            entry['environment'][key]='@option:'+setting_groups[group]
        for key in ('command','entrypoint'):
            if key in source: entry[key]=shlex.split(source[key]) if isinstance(source[key],str) else source[key]
        if 'healthcheck' in source:
            health = copy.deepcopy(source['healthcheck'])
            if not isinstance(health, dict): raise Error('Ungültiger Healthcheck.')
            if health.get('disable') is True: health = {'test':['NONE']}
            elif isinstance(health.get('test'), str): health['test'] = ['CMD-SHELL', health['test']]
            entry['healthcheck'] = health
        depends=source.get('depends_on',[])
        if isinstance(depends, dict):
            for options in depends.values():
                if not isinstance(options, dict) or set(options)-{'condition','restart','required'} or options.get('restart') or options.get('required') is False: raise UnsupportedTemplate('Optionale oder automatisch neu gestartete Abhängigkeiten benötigen eine eigene Vorlage.', 'dependencies')
            entry['depends_on']={key:{'condition':options.get('condition','service_started')} for key,options in depends.items()}
        else: entry['depends_on'] = depends
        translated[name]=entry
    if primary is None and web:
        candidates = [(name, mapping) for name, service in translated.items() for mapping in service['ports'] if mapping['target']==web and mapping['protocol']=='tcp']
        if len(candidates) == 1: primary = candidates[0][0]
    main_port=next((p for p in translated.get(primary, {}).get('ports', []) if p['published']==web and p['protocol']=='tcp'),None)
    if main_port is None and primary and web:
        candidates = [mapping for mapping in translated[primary]['ports'] if mapping['target']==web and mapping['protocol']=='tcp']
        if len(candidates) == 1: main_port = candidates[0]
    if web and main_port is None and any(mapping['protocol']=='tcp' for service in translated.values() for mapping in service['ports']):
        raise UnsupportedTemplate('Der angegebene Webport gehört zu keinem eindeutigen TCP-Dienst.', 'web_port')
    web_available = main_port is not None
    primary = primary or next(iter(translated))
    for name,service in translated.items():
        for mapping in service['ports']:
            if name==primary and mapping is main_port: continue
            key='stack_port_'+name+'_'+str(mapping['target'])+'_'+mapping['protocol']
            settings.append({'key':key,'label':name+' · Port '+str(mapping['target'])+'/'+mapping['protocol'],'type':'number','default':mapping['published'],'min':1,'max':65535,'required':True})
            extra.append({'option':key,'target':mapping['target'],'protocol':mapping['protocol'],'service':name, **({'host_ip':mapping['host_ip']} if mapping.get('host_ip') else {})})
    stack=validate_stack({'primary':primary,'services':translated, **({'networks':networks} if networks else {})})
    title=line(localized(meta.get('title')) or label,80)
    return {'id':slug(label),'name':title,'description':line(localized(meta.get('description'))),'image':translated[primary]['image'],'port':main_port['target'] if main_port else 0,'default_port':max(1024,web) if web_available else 0,'web_available':web_available, **({'web_host_ip':main_port['host_ip']} if main_port and main_port.get('host_ip') else {}),'scheme':'https' if meta.get('scheme')=='https' else 'http','mount':None,'config_mount':True,'documentation':'https://github.com/'+repository,'login_note':login(title) if web_available else 'Dieser Dienst besitzt keine Weboberfläche. Einrichtung, Protokolle und Verbindungen verwaltest du in Titan; die Anleitung beschreibt die Nutzung.','default_network':'host' if raw[primary].get('network_mode')=='host' else 'default','stack':stack,'stack_fields':settings,'stack_ports':extra}

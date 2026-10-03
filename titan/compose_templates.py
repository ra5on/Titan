"""Translate a bounded Compose subset into private Titan app directories."""
import copy
import re
from .core import Error

NAME=r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}'
IMAGE=r'[a-z0-9][a-z0-9./_-]*(?::[A-Za-z0-9_.-]+|@sha256:[a-f0-9]{64})'

def validate_stack(value):
    if not isinstance(value,dict) or set(value)!={'primary','services'} or not isinstance(value['services'],dict) or not 1<=len(value['services'])<=8 or value['primary'] not in value['services']: raise Error('Ungültiger App-Containerverbund.')
    if len({name.lower() for name in value['services']})!=len(value['services']): raise Error('Container-Namen sind nicht eindeutig.')
    for name,service in value['services'].items():
        if not isinstance(name,str) or not re.fullmatch(NAME,name) or not isinstance(service,dict) or set(service)-{'image','environment','mounts','command','entrypoint','depends_on','ports','healthcheck'}: raise Error('Nicht unterstützte Containeroption.')
        if not isinstance(service.get('image'),str) or not re.fullmatch(IMAGE,service['image']): raise Error('Ungültiges Container-Image.')
        env=service.get('environment',{})
        if not isinstance(env,dict) or len(env)>64 or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',key) or not isinstance(val,str) or len(val)>1000 or '\0' in val for key,val in env.items()): raise Error('Ungültige Container-Umgebung.')
        for mount in service.get('mounts',[]):
            if not isinstance(mount,dict) or set(mount)!={'slot','target','readonly'} or not isinstance(mount['slot'],str) or not re.fullmatch(r'[a-z0-9_-]{1,50}',mount['slot']) or not isinstance(mount['target'],str) or not mount['target'].startswith('/') or '..' in mount['target'].split('/') or '\0' in mount['target'] or len(mount['target'])>200 or mount['target'].startswith(('/proc','/sys','/dev','/run')) or type(mount['readonly']) is not bool: raise Error('Ungültige Container-Dateizuordnung.')
        for key in ('command','entrypoint'):
            command=service.get(key)
            if command is not None and (not isinstance(command,list) or not 1<=len(command)<=64 or any(not isinstance(part,str) or len(part)>2000 or '$' in part or '\0' in part for part in command)): raise Error('Dynamische Container-Kommandos nicht unterstützt.')
        dependencies=service.get('depends_on',[])
        if not isinstance(dependencies,(list,dict)) or len(dependencies)>8: raise Error('Ungültige Container-Abhängigkeiten.')
        if isinstance(dependencies,dict):
            for dependency,options in dependencies.items():
                if not isinstance(options,dict) or set(options)!={'condition'} or options['condition'] not in ('service_started','service_healthy','service_completed_successfully'): raise Error('Ungültige Startbedingung.')
                if options['condition']=='service_healthy' and not value['services'].get(dependency,{}).get('healthcheck'): raise Error('Startbedingung benötigt einen Healthcheck.')
        for dependency in dependencies:
            if dependency not in value['services'] or dependency==name: raise Error('Ungültige Container-Abhängigkeit.')
        if not isinstance(service.get("mounts",[]),list) or len(service.get("mounts",[]))>16 or not isinstance(service.get("ports",[]),list) or len(service.get("ports",[]))>16: raise Error("Zu viele Container-Datei-/Portzuordnungen.")
        for mapping in service.get('ports',[]):
            if not isinstance(mapping,dict) or set(mapping)!={'target','published','protocol'} or mapping['protocol'] not in ('tcp','udp') or any(type(mapping[k]) is not int or not 1<=mapping[k]<=65535 for k in ('target','published')): raise Error('Ungültiger Container-Port.')
        health=service.get('healthcheck')
        if health is not None:
            if not isinstance(health,dict) or set(health)-{'test','interval','timeout','start_period','retries'} or not isinstance(health.get('test'),list) or not health['test'] or health['test'][0] not in ('CMD','CMD-SHELL','NONE') or any(not isinstance(v,str) or '$' in v or len(v)>1000 for v in health['test']): raise Error('Nicht unterstützter Healthcheck.')
            for key in ('interval','timeout','start_period'):
                if key in health and not re.fullmatch(r'[1-9][0-9]{0,3}(?:ms|s|m|h)',str(health[key])): raise Error('Ungültiges Healthcheck-Intervall.')
            if 'retries' in health and (type(health['retries']) is not int or not 1<=health['retries']<=20): raise Error('Ungültige Healthcheck-Wiederholungen.')
    # Detect dependency cycles before Compose can create partial resources.
    def visit(name,parents):
        if name in parents: raise Error('Zyklische Container-Abhängigkeit.')
        for child in value['services'][name].get('depends_on',[]): visit(child,parents|{name})
    for name in value['services']: visit(name,set())
    return value


def build(app_id, recipe, directory, uid, gid, port, data_path, options):
    stack=validate_stack(recipe['stack']);primary=stack['primary']; names={key:app_id if key==primary else app_id+'-'+key.lower() for key in stack['services']};services={}
    for name,template in stack['services'].items():
        identifier=names[name];service={'image':template['image'],'container_name':'titan-'+identifier,'restart':'unless-stopped','mem_limit':recipe['memory'],'cpus':2,'logging':{'driver':'json-file','options':{'max-size':'10m','max-file':'3'}},'labels':{'io.titan.managed':'true','io.titan.app':app_id},'networks':{'default':{'aliases':[name]}},'environment':{},'volumes':[],'ports':[]}
        for key,value in template.get('environment',{}).items():
            if value=='@uid': value=str(uid)
            elif value=='@gid': value=str(gid)
            elif value.startswith('@option:'): value=str(options[value[8:]])
            service['environment'][key]=value.replace('$','$$')
        for mount in template.get('mounts',[]):
            source=data_path if mount['slot']=='data' else directory+'/config/'+mount['slot']
            service['volumes'].append({'type':'bind','source':str(source),'target':mount['target'],'read_only':mount['readonly'],'bind':{'create_host_path':False}})
        for mapping in template.get('ports',[]):
            published=port if name==primary and mapping['target']==recipe['port'] and mapping['protocol']=='tcp' else options['stack_port_'+name+'_'+str(mapping['target'])+'_'+mapping['protocol']]
            service['ports'].append(str(published)+':'+str(mapping['target'])+'/'+mapping['protocol'])
        for key in ('command','entrypoint','healthcheck'):
            if key in template: service[key]=copy.deepcopy(template[key])
        if template.get('depends_on'):
            dependency=template['depends_on']
            service['depends_on']={names[key]:options for key,options in dependency.items()} if isinstance(dependency,dict) else [names[key] for key in dependency]
        services[identifier]=service
    return {'services':services}


def translate(doc,label,repository):
    """Convert source paths to managed slots and expose ports/env as form fields."""
    import shlex
    from .store_sources import line,localized,port,slug,login
    raw=doc.get('services',{})
    if not isinstance(raw,dict) or not 1<=len(raw)<=8: raise Error('Maximal acht Container pro App.')
    meta=doc.get('x-casaos',{});web,_=port(meta.get('port_map',''))
    primary=meta.get('main');primary=primary if primary in raw else None
    translated={};settings=[];extra=[];slots={};setting_groups={}
    for name,source in raw.items():
        ignored={'container_name','restart','labels','deploy','x-casaos','cpu_shares','mem_limit','hostname','network_mode','networks'}
        supported={'image','environment','ports','volumes','command','entrypoint','depends_on','healthcheck'}
        if not isinstance(source,dict) or set(source)-ignored-supported: raise Error('Diese App benötigt zusätzliche Hostrechte oder Laufzeitoptionen.')
        if source.get('network_mode') not in (None,'bridge','host'): raise Error('Besondere Netzwerk-Namensräume erforderlich.')
        if source.get('network_mode')=='host' and len(raw)>1: raise Error('Host-Netz für Containerverbünde nicht unterstützt.')
        image=source['image'];image=image if ':' in image or '@' in image else image+':latest';entry={'image':image,'environment':{},'mounts':[],'ports':[]}
        for mapping in source.get('ports',[]):
            if isinstance(mapping,int): mapping=str(mapping)
            if isinstance(mapping,str):
                parts=mapping.split(':')
                if len(parts)==1: published,target=port(parts[0])[0],port(parts[0])[0];protocol=port(parts[0])[1]
                elif len(parts)==2: published=port(parts[0])[0];target,protocol=port(parts[1])
                elif len(parts)==3 and parts[0] in ('0.0.0.0','127.0.0.1'): published=port(parts[1])[0];target,protocol=port(parts[2])
                else: raise Error('Portbereiche oder dynamische Ports nicht unterstützt.')
            elif isinstance(mapping,dict): published=port(mapping.get('published',mapping['target']))[0];target=port(mapping['target'])[0];protocol=mapping.get('protocol','tcp')
            else: raise Error('Ungültige Portzuordnung.')
            entry['ports'].append({'published':published,'target':target,'protocol':protocol})
            if published==web and protocol=='tcp': primary=primary or name
        if source.get('network_mode')=='host' and not entry['ports']: entry['ports']=[{'published':web,'target':web,'protocol':'tcp'}];primary=name
        for mapping in source.get('volumes',[]):
            if isinstance(mapping,str):
                parts=mapping.split(':')
                if len(parts) not in (2,3) or len(parts)==3 and parts[2] not in ('ro','rw'): raise Error('Besondere Volume-Optionen erforderlich.')
                original,target=parts[:2];readonly=len(parts)==3 and parts[2]=='ro'
            elif isinstance(mapping,dict) and not set(mapping)-{'type','source','target','read_only'} and mapping.get('type','bind') in ('bind','volume'): original,target=mapping['source'],mapping['target'];readonly=mapping.get('read_only',False)
            else: raise Error('Nicht unterstützte Dateizuordnung.')
            if original.startswith(('/dev','/proc','/sys','/etc','/var/run','/run','/lib')): raise Error('Hostdateien erforderlich; explizite USB/GPU-Auswahl separat verwenden.')
            if original not in slots: slots[original]='data' if target in ('/data','/media','/downloads','/files','/storage') and 'data' not in slots.values() else 'mount-'+str(len(slots)+1)
            entry['mounts'].append({'slot':slots[original],'target':target,'readonly':readonly})
        env=source.get('environment',{})
        if isinstance(env,list): env=dict(part.split('=',1) for part in env)
        for key,value in env.items():
            if key=='PUID': entry['environment'][key]='@uid';continue
            if key=='PGID': entry['environment'][key]='@gid';continue
            value='' if value is None else str(value)
            if key=='TZ' and '$' in value: value='Europe/Berlin'
            value=re.sub(r'\$\{[A-Za-z_][A-Za-z0-9_]*:-([^{}]*)\}',r'\1',value)
            secret=bool(re.search(r'password|secret|token|api.?key',key,re.I));group=(key,value)
            if group not in setting_groups:
                option='stack_env_'+str(len(settings));setting_groups[group]=option
                settings.append({'key':option,'label':key+' · '+name,'type':'password' if secret else 'text','default':'' if secret or '$' in value else value,'required':True,'min_length':1 if secret or '$' in value else 0,'max_length':1000})
            entry['environment'][key]='@option:'+setting_groups[group]
        for key in ('command','entrypoint'):
            if key in source: entry[key]=shlex.split(source[key]) if isinstance(source[key],str) else source[key]
        if 'healthcheck' in source: entry['healthcheck']=source['healthcheck']
        depends=source.get('depends_on',[]);entry['depends_on']={key:{'condition':options.get('condition','service_started')} for key,options in depends.items()} if isinstance(depends,dict) else depends
        translated[name]=entry
    if primary is None: raise Error('Kein eindeutiger Webport; App benötigt eine spezielle Vorlage.')
    main_port=next((p for p in translated[primary]['ports'] if p['published']==web and p['protocol']=='tcp'),None)
    if main_port is None: raise Error('Webport gehört nicht zum Hauptcontainer.')
    for name,service in translated.items():
        for mapping in service['ports']:
            if name==primary and mapping is main_port: continue
            key='stack_port_'+name+'_'+str(mapping['target'])+'_'+mapping['protocol']
            settings.append({'key':key,'label':name+' · Port '+str(mapping['target'])+'/'+mapping['protocol'],'type':'number','default':max(1024,mapping['published']),'min':1024,'max':65535,'required':True})
            extra.append({'option':key,'target':mapping['target'],'protocol':mapping['protocol'],'service':name})
    stack=validate_stack({'primary':primary,'services':translated})
    title=line(localized(meta.get('title')) or label,80)
    return {'id':slug(label),'name':title,'description':line(localized(meta.get('description'))),'image':translated[primary]['image'],'port':main_port['target'],'default_port':max(1024,web),'scheme':'https' if meta.get('scheme')=='https' else 'http','mount':None,'config_mount':True,'documentation':'https://github.com/'+repository,'login_note':login(title),'default_network':'host' if raw[primary].get('network_mode')=='host' else 'default','stack':stack,'stack_fields':settings,'stack_ports':extra}

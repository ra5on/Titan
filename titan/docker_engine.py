"""Native administrator Docker workbench; no external UI or telemetry."""
import json
import re
from .core import Error, integer

NAME = r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}'
IMAGE = r'[a-z0-9][a-z0-9./_-]*(?::[A-Za-z0-9_.-]+|@sha256:[a-f0-9]{64})?'


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{64}',value): raise Error('Ungültige Container-ID.')
    return value


def name(value):
    if not isinstance(value,str) or not re.fullmatch(NAME,value): raise Error('Name darf nur Buchstaben, Zahlen, Punkt, Strich und Unterstrich enthalten.')
    return value


class DockerEngineMixin:
    @staticmethod
    def engine_docker(args,**kwargs):
        from .host import run
        return run(['docker',*args],**kwargs)

    def engine_container(self, container):
        container=identifier(container)
        values=json.loads(self.engine_docker(['inspect','--type','container',container]))
        if len(values)!=1 or values[0].get('Id')!=container: raise Error('Container wurde ersetzt. Ansicht aktualisieren.',409)
        return values[0]

    @staticmethod
    def engine_summary(row):
        cfg=row.get('Config',{});state=row.get('State',{});net=row.get('NetworkSettings',{})
        # Never return environment variables or labels containing passwords.
        labels=cfg.get('Labels') or {}
        from .catalog import APPS
        recipe=APPS.get(labels.get('io.titan.app'),{}) if labels.get('io.titan.managed')=='true' else {}
        web_port=recipe.get('port')
        if recipe.get('dynamic_web_port'):
            values=[value.split('=',1)[1] for value in cfg.get('Env') or [] if isinstance(value,str) and value.startswith('WEBUI_PORT=')]
            web_port=int(values[0]) if len(values)==1 and re.fullmatch(r'[0-9]{1,5}',values[0]) and 1<=int(values[0])<=65535 else None
        return {'id':row['Id'],'name':row.get('Name','').lstrip('/'),'image':labels.get('io.titan.original_image') or cfg.get('Image',''),
                'state':state.get('Status','unknown'),'health':state.get('Health',{}).get('Status'),
                'created':row.get('Created'),'restart':row.get('HostConfig',{}).get('RestartPolicy',{}).get('Name'),
                'managed_app':labels.get('io.titan.app') if labels.get('io.titan.managed')=='true' else None,
                'manual':labels.get('io.titan.manual')=='true','web_port':web_port,'network_mode':row.get('HostConfig',{}).get('NetworkMode'),'scheme':recipe.get('scheme','http'),
                'hardware':[v.get('PathOnHost') for v in row.get('HostConfig',{}).get('Devices') or []]+['nvidia:'+v for r in row.get('HostConfig',{}).get('DeviceRequests') or [] if r.get('Driver')=='nvidia' for v in r.get('DeviceIDs') or []],
                'project':labels.get('com.docker.compose.project'), 'service':labels.get('com.docker.compose.service'),
                'networks':[{'name':key,'ipv4':value.get('IPAddress'),'ipv6':value.get('GlobalIPv6Address')} for key,value in net.get('Networks',{}).items()],
                'ports':net.get('Ports') or {},'mounts':[{'type':v.get('Type'),'source':v.get('Source'),'target':v.get('Destination'),'writable':v.get('RW')} for v in row.get('Mounts',[])]}

    def op_docker_engine(self):
        try:
            ids=self.engine_docker(['ps','-aq','--no-trunc']).splitlines()
            if len(ids)>256: raise Error('Mehr als 256 Container: Docker-CLI zur vollständigen Verwaltung verwenden.')
            rows=json.loads(self.engine_docker(['inspect','--type','container',*[identifier(v) for v in ids]])) if ids else []
            def listing(args):
                return [json.loads(line) for line in self.engine_docker(args+['--format','{{json .}}']).splitlines()[:512]]
            return {'available':True,'containers':[self.engine_summary(row) for row in rows],
                    'images':listing(['image','ls','--no-trunc']), 'volumes':listing(['volume','ls']),
                    'networks':listing(['network','ls','--no-trunc']), 'devices':self.op_app_devices()['devices']}
        except (Error,ValueError,KeyError,TypeError) as exc:
            return {'available':False,'error':str(exc),'containers':[],'images':[],'volumes':[],'networks':[]}

    def op_docker_container_details(self, container):
        row=self.engine_container(container)
        logs=self.engine_docker(['logs','--tail','150','--timestamps',identifier(container)],timeout=15,include_stderr=True)
        return {'container':self.engine_summary(row),'logs':logs[-65536:]}

    def op_docker_container_action(self, container, action):
        row=self.engine_container(container);managed=self.engine_summary(row)['managed_app']
        if managed:
            if action not in ('start','stop','restart','remove'): raise Error('Ungültige Container-Aktion.')
            return self.op_app_action(managed, action)
        if action not in ('start','stop','restart','remove'): raise Error('Ungültige Container-Aktion.')
        if action=='remove' and row.get('State',{}).get('Running'): raise Error('Container vor dem Entfernen stoppen.',409)
        args=['rm',container] if action=='remove' else [action,container]
        return {'output':self.engine_docker(args,timeout=120),'ok':True}

    def op_docker_image_pull(self, image):
        if not isinstance(image,str) or not re.fullmatch(IMAGE,image): raise Error('Ungültiger Image-Name.')
        self.engine_docker(['pull',image],timeout=600)
        return {'ok':True,'image':image}

    def op_docker_container_batch(self, containers, action):
        if action not in ('start','stop','restart') or not isinstance(containers,list) or not 1<=len(containers)<=64:
            raise Error('Eine Start-/Stop-/Neustart-Aktion für maximal 64 Container auswählen.')
        ids=[identifier(value) for value in containers]
        if len(set(ids))!=len(ids): raise Error('Container doppelt ausgewählt.')
        # Validate the complete selection before changing anything. Managed
        # multi-container apps use their existing lifecycle once per app.
        rows=[self.engine_container(value) for value in ids]
        completed=[];failed=[];seen=set()
        for row in rows:
            summary=self.engine_summary(row);app=summary['managed_app']
            key=('app',app) if app else ('container',row['Id'])
            if key in seen: continue
            seen.add(key)
            try:
                self.op_docker_container_action(row['Id'],action)
                completed.append(row['Id'])
            except Error as exc:
                failed.append({'container':row['Id'],'error':str(exc)})
        return {'ok':not failed,'completed':completed,'failed':failed}

    def op_docker_resource(self, kind, action, resource):
        if kind not in ('volume','image'): raise Error('Ungültige Docker-Ressource.')
        if kind=='image':
            if action!='remove' or not isinstance(resource,str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',resource): raise Error('Ungültiges Image.')
            return {'output':self.engine_docker(['image','rm',resource])}
        resource=name(resource)
        if action not in ('create','remove'): raise Error('Ungültige Volume-Aktion.')
        # No force removal, no host bind via local-driver options, no pruning.
        return {'output':self.engine_docker(['volume','create' if action=='create' else 'rm',resource])}

    def _engine_create_args(self, config):
        if not isinstance(config,dict) or set(config)-{'name','image','network','ports','environment','volume','target','restart','memory_mb','cpus','command','devices'}: raise Error('Ungültige Container-Einstellungen.')
        container_name='titan-custom-'+name(config.get('name'));image=config.get('image','')
        if not isinstance(image,str) or not re.fullmatch(IMAGE,image): raise Error('Ungültiger Image-Name.')
        network=config.get('network','bridge')
        if network not in ('bridge','host','none'):
            network=name(network)
            info=json.loads(self.engine_docker(['network','inspect',network]))[0]
            if info.get('Driver') not in ('bridge','macvlan','ipvlan'): raise Error('Netzwerktreiber nicht unterstützt.')
        restart=config.get('restart','unless-stopped')
        if restart not in ('no','unless-stopped','always','on-failure'): raise Error('Ungültige Neustartregel.')
        memory=integer(config.get('memory_mb',1024),64,1048576);cpus=integer(config.get('cpus',2),1,1024)
        args=['create','--name',container_name,'--label','io.titan.manual=true','--restart',restart,'--network',network,'--memory',str(memory)+'m','--cpus',str(cpus),'--log-driver','json-file','--log-opt','max-size=10m','--log-opt','max-file=3']
        ports=config.get('ports',[])
        if not isinstance(ports,list) or len(ports)>32: raise Error('Maximal 32 Ports.')
        if network in ('host','none') and ports: raise Error('Host/Ohne Netzwerk benötigt keine Portzuordnungen.')
        used=set()
        for row in ports:
            if not isinstance(row,dict) or set(row)!={'published','target','protocol'} or row['protocol'] not in ('tcp','udp'): raise Error('Ungültige Portzuordnung.')
            external=integer(row['published'],1024,65535);target=integer(row['target'],1,65535)
            if external in (5000,5001) or (external,row['protocol']) in used: raise Error('Port reserviert oder doppelt.')
            used.add((external,row['protocol']));args+=['--publish',f'{external}:{target}/{row["protocol"]}']
        env=config.get('environment',{})
        if not isinstance(env,dict) or len(env)>64: raise Error('Maximal 64 Umgebungsvariablen.')
        for key,value in env.items():
            if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',key) or not isinstance(value,str) or len(value)>2000 or '\0' in value: raise Error('Ungültige Umgebungsvariable.')
            args+=['--env',key+'='+value]
        if config.get('volume'):
            volume=name(config['volume']);details=json.loads(self.engine_docker(['volume','inspect',volume]))[0]
            if details.get('Driver')!='local' or details.get('Options'): raise Error('Nur lokale Volumes ohne Hostpfad-Optionen verwenden.')
            target=config.get('target','/data')
            if not isinstance(target,str) or not re.fullmatch(r'/[a-zA-Z0-9_./-]{1,180}',target) or '..' in target.split('/') or target.startswith(('/proc','/sys','/dev','/run')): raise Error('Ungültiges Datenziel im Container.')
            args+=['--mount',f'type=volume,source={volume},target={target}']
        command=config.get('command',[])
        if not isinstance(command,list) or len(command)>64 or any(not isinstance(part,str) or len(part)>2000 or '\0' in part for part in command): raise Error('Ungültiges Startkommando.')
        from .app_devices import devices, validate
        hardware=devices();selected=validate(config.get('devices',[]),hardware)
        chosen=[row for row in hardware if row['id'] in selected]
        nvidia=[row['id'].split(':',1)[1] for row in chosen if row.get('driver')=='nvidia']
        if nvidia:args+=['--gpus','"device='+','.join(nvidia)+'"']
        groups=set()
        for row in chosen:
            if row.get('path'):args+=['--device',row['path']+':'+row['path']+':rw']
            if type(row.get('group')) is int:groups.add(row['group'])
        for group in sorted(groups):args+=['--group-add',str(group)]
        args+=[image,*command]
        return args

    def op_docker_container_create(self, config):
        args=self._engine_create_args(config)
        # All validation precedes the first mutation. Failure never removes an
        # unrelated name or an existing volume; the stopped container is retryable.
        container=identifier(self.engine_docker(args,timeout=600).strip())
        try:self.engine_docker(['start',container],timeout=120)
        except Error: raise Error('Container angelegt, Start fehlgeschlagen. Logs ansehen und erneut starten.',503) from None
        return {'ok':True,'container':container}

    def op_docker_container_hardware(self, container, devices):
        row=self.engine_container(container)
        if (row.get('Config',{}).get('Labels') or {}).get('io.titan.manual')!='true':
            raise Error('Geräte einer Titan-App unter App-Einstellungen ändern. Fremde Container werden nicht umgebaut.')
        if row.get('State',{}).get('Running'): raise Error('Container vor dem Ändern der Geräte stoppen.',409)
        original=row.get('Name','').lstrip('/')
        if not original.startswith('titan-custom-'): raise Error('Dieser Container wurde nicht mit Titan angelegt.')
        mounts=row.get('Mounts',[])
        if len(mounts)>1 or any(m.get('Type')!='volume' or not m.get('RW') for m in mounts):
            raise Error('Nur Titan-Container mit höchstens einem lokalen Datenvolume können umgebaut werden.')
        host=row.get('HostConfig',{})
        if host.get('Memory',0)<64*1048576 or host.get('NanoCpus',0)<1000000000 or host.get('NanoCpus',0)%1000000000:raise Error('Individuell geänderte Ressourcenlimits können nicht automatisch übernommen werden.')
        networks=row.get('NetworkSettings',{}).get('Networks',{})
        network=host.get('NetworkMode','bridge')
        if network not in ('host','none','bridge','default'):
            if len(networks)!=1: raise Error('Container mit mehreren Netzen benötigen individuelle Konfiguration.')
            network=next(iter(networks))
        if network=='default':network='bridge'
        bindings=[]
        for target,ports in (host.get('PortBindings') or {}).items():
            number,protocol=target.split('/')
            for port in ports or []:
                if port.get('HostIp') not in ('','0.0.0.0',None): raise Error('Individuelle Bindungsadresse kann nicht automatisch übernommen werden.')
                bindings.append({'published':int(port['HostPort']),'target':int(number),'protocol':protocol})
        config={'name':original[len('titan-custom-'):], 'image':row['Config']['Image'], 'network':network,
                'ports':bindings,'devices':devices,'restart':host.get('RestartPolicy',{}).get('Name') or 'no',
                'memory_mb':max(64,int(host.get('Memory',0))//1048576), 'cpus':max(1,int(host.get('NanoCpus',0))//1000000000)}
        if mounts:config.update(volume=mounts[0]['Name'],target=mounts[0]['Destination'])
        self._engine_create_args(config) # Complete validation before first mutation.
        fresh=self.engine_container(container)
        if fresh.get('State',{}).get('Running') or fresh.get('Name')!=row.get('Name'):
            raise Error('Containerzustand hat sich geändert. Ansicht aktualisieren.',409)
        # Preserve the writable layer, image defaults and environment locally.
        # Never export credentials or replace a container owned by another name.
        base=self.engine_summary(row)['image']
        if not re.fullmatch(IMAGE,base):raise Error('Originalimage ist nicht gültig.')
        image=self.engine_docker(['commit','--change','LABEL io.titan.original_image='+base,container],timeout=600).strip()
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise Error('Container-Sicherung konnte nicht geprüft werden.',503)
        backup='titan-previous-'+container[:20]
        self.engine_docker(['rename',container,backup])
        config['image']=image
        try:
            result=self.op_docker_container_create(config)
        except Error:
            ids=self.engine_docker(['ps','-aq','--no-trunc','--filter','name=^/'+original+'$']).splitlines()
            if not ids:self.engine_docker(['rename',container,original])
            raise
        return {**result,'backup_container':container,'message':'Geräte aktualisiert. Der vorherige gestoppte Container bleibt als Sicherung erhalten; das Datenvolume wird weiterverwendet.'}

    def op_docker_metrics(self):
        from .app_metrics import parse_stats, cgroup_memory
        try:
            ids=self.engine_docker(['ps','-aq','--no-trunc']).splitlines()[:256]
            rows=json.loads(self.engine_docker(['inspect','--type','container',*[identifier(v) for v in ids]])) if ids else []
            active=[row['Id'] for row in rows if row.get('State',{}).get('Running')]
            samples=parse_stats(self.engine_docker(['stats','--no-stream','--format','{{json .}}',*active],timeout=20)) if active else {}
            result={}
            for row in rows:
                running=row.get('State',{}).get('Running');sample=samples.get(row.get('Name','').lstrip('/'),{})
                result[row['Id']]={**sample,'memory_bytes':cgroup_memory(row.get('State',{}).get('Pid')) if running else 0,'cpu_percent':sample.get('cpu_percent') if running else 0}
            return {'available':True,'containers':result}
        except Error:return {'available':False,'containers':{}}

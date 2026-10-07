"""Explicitly simulated package and VM extension workflows; no host access."""
import copy
import time
import uuid

from .app_packages import PACKAGES
from .catalog import validate_options
from .core import Error, identifier, integer
from .vm_names import identity as vm_identity


OPERATIONS = frozenset({'app_memory_preflight','package_details','package_diagnose','package_logs','package_repair','package_update','package_settings',
                        'vm_extensions','vm_clone','vm_snapshot_create','vm_snapshot_restore','vm_snapshot_restore_new','vm_snapshot_remove',
                        'vm_disk_add','vm_disk_remove','vm_nic_add','vm_nic_remove','vm_guest_agent','vm_guest_action',
                        'vm_backup','vm_restore'})


class DemoPackagesVMMixin:
    def _demo_extended_vm(self, vm):
        if not hasattr(self, '_demo_vm_hardware'): self._demo_vm_hardware = {}
        item = self.vm(vm)
        state = self._demo_vm_hardware.setdefault(vm, {'disks':[{'disk':item.get('disk_path','/var/lib/libvirt/images/titan/' + item['name'] + '.qcow2'),
                    'target':'vda','storage':item.get('storage','system'),'virtual_size':item.get('virtual_size',32 * 1024 ** 3),'allocated_bytes':2 * 1024 ** 3,'boot':True}],
                    'networks':[{'index':0,**item.get('network',{'mode':'network','source':'default','model':'virtio','mac':'52:54:00:12:34:56','connected':True})}],
                    'snapshots':[],'guest_agent':False})
        return item, state

    def _demo_package(self, app):
        if app not in PACKAGES: raise Error('Paket nicht gefunden.',404)
        item = next((record for record in self.apps if record['id'] == app),None)
        if item is None: raise Error('Paket ist nicht installiert.',404)
        return item

    def demo_packages_vm_call(self, operation, **args):
        if operation not in OPERATIONS: return NotImplemented
        if operation == 'app_memory_preflight':
            from .app_memory import package_memory_plan, memory_preflight
            app, options = args['app'], args.get('options', {})
            if not isinstance(options, dict) or set(options)-{'resource_profile','office_mode'}:
                raise Error('Ungültige RAM-Auswahl.')
            defaults = {'resource_profile':'balanced', **({'office_mode':'disabled'} if app == 'titan-nextcloud-office' else {})}
            plan = package_memory_plan(app, {**defaults, **options})
            return {**memory_preflight({'memory_total':8 * 1024**3, 'memory_available':6 * 1024**3},
                plan['startup_limit_bytes'], installation=True), 'plan':plan, 'demo':True}
        if operation == 'vm_restore':
            saved = self.backup(args['backup'])
            name, label = vm_identity(args['name'])
            if saved['type'] != 'vm': raise Error('Diese Sicherung enthält keine VM.')
            if any((vm['name'] == name or vm.get('display_name',vm['name']) == label) for vm in self.vms): raise Error('VM existiert bereits.',409)
            item = {**copy.deepcopy(saved['vm']), 'id':str(uuid.uuid4()), 'name':name, 'display_name':label, 'state':'shut off', 'autostart':False,
                    'storage':args.get('storage','system'), 'disk_path':'/var/lib/libvirt/images/titan/'+name+'.qcow2', 'cpu_ids':[]}
            self.vms.append(item)
            _, state = self._demo_extended_vm(item['id'])
            if saved.get('hardware'):
                state.update(copy.deepcopy(saved['hardware']))
                state['snapshots']=[]
                for index,disk in enumerate(state['disks']):
                    disk['disk']='/var/lib/libvirt/images/titan/'+name+('' if index==0 else '--'+uuid.uuid4().hex)+'.qcow2'
                    disk['storage']=args.get('storage','system')
                for nic in state['networks']: nic['mac']=''
            return {'ok':True,'demo':True,'id':item['id'],'name':name,'message':'Demo: Alle Laufwerke und VM-Einstellungen wiederhergestellt; VM bleibt ausgeschaltet.'}
        if operation.startswith('package_'):
            app = args['app']
            if operation == 'package_details' and not any(item['id'] == app for item in self.apps):
                if app not in PACKAGES: raise Error('Paket nicht gefunden.',404)
                return {'installed':False,'app':app,'services':[],'phase':'available'}
            item = self._demo_package(app)
            recipe = PACKAGES[app]
            options = self._app_settings.get(app,{})
            if operation == 'package_settings':
                if item['state'] in ('running','paused','restarting'): raise Error('Das gesamte Paket vor der Änderung stoppen.',409)
                editable = {field['key'] for field in recipe['install_schema'] if field['type'] != 'password' and field['key'] != 'username'}
                proposed = args.get('options',{})
                if not isinstance(proposed,dict) or set(proposed)-editable: raise Error('Konten und Passwörter direkt in der Anwendung verwalten.')
                item['port'] = integer(args['port'],1024,65535)
                self._app_settings[app] = validate_options(app,{**options,**proposed})
                return {'ok':True,'demo':True,'message':'Demo: Einstellungen gespeichert; keine Container verändert.'}
            if operation in ('package_update','package_repair'):
                if operation == 'package_repair': item['state'] = 'running'
                item.update(phase='ready',last_error='')
                return {'ok':True,'demo':True,'kept_stopped':item['state']!='running','message':'Demo: Paketaktion simuliert; kein Docker-Zugriff.'}
            services = []
            for index,(name,definition) in enumerate(recipe['stack']['services'].items()):
                primary = name == recipe['stack']['primary']
                once = name == 'office-init'
                running = item['state'] == 'running'
                services.append({'id':app if primary else app+'-'+name,'name':recipe['dependencies'][index],
                    'image':definition['image'],'state':'exited' if once else item['state'],'health':'' if once else 'healthy' if running else '',
                    'ready':once or running,'one_shot':once,'depends_on':[app if key==recipe['stack']['primary'] else app+'-'+key for key in definition.get('depends_on',{})]})
            if operation == 'package_diagnose':
                return {'app':app,'ok':item['state']=='running','repair_available':True,'warnings':[],
                    'checks':[{'id':service['id'],'name':service['name'],'ok':service['ready'],'message':'Demo: '+('Bereit' if service['ready'] else 'Gestoppt')} for service in services],
                    'message':'Demo: Prüfungen und Reparatur sind simuliert.'}
            if operation == 'package_logs':
                if args.get('service') not in {service['id'] for service in services}: raise Error('Dienst gehört nicht zum Paket.',403)
                return {'service':args['service'],'logs':'[Demo] Paketdienst bereit. Keine echten Containerprotokolle.'}
            return {'installed':True,'app':copy.deepcopy(item),'services':services,'ready':item['state']=='running',
                    'phase':'ready' if item['state']=='running' else 'stopped','running_services':sum(service['state']=='running' for service in services),
                    'total_services':len(services),'warnings':[],
                    'login':{'instructions':recipe['first_login']['instructions'],'username':options.get('username',''),'password_selected':any(field['type']=='password' and not field.get('generated') for field in recipe['install_schema'])},
                    'settings':[{'key':field['key'],'label':field['label'],'type':field['type'],'min':field.get('min'),'max':field.get('max'),'value':options.get(field['key'],field.get('default')),'editable':field['key']!='username'} for field in recipe['install_schema'] if field['type']!='password'],
                    'port':item['port'],'data_path':item.get('data','/var/srv/titan/apps/'+app),
                    'update':{'available':False,'backup_required':True,'policy':'approved-titan-recipe','message':'Demo: Vollständige Paketaktualisierung mit vorheriger Sicherung wird simuliert.'}}
        item, state = self._demo_extended_vm(args['vm'])
        if operation == 'vm_extensions':
            configured = state['guest_agent']
            connected = configured and item['state']=='running'
            return {'vm':item['id'],'state':item['state'],'disks':copy.deepcopy(state['disks']),
                    'networks':copy.deepcopy(state['networks']),'snapshots':[{key:record[key] for key in ('id','name','created','disk_count','mode')} for record in state['snapshots']],
                    'guest_agent':{'configured':configured,'connected':connected,'interfaces':[{'name':'eth0','mac':'52:54:00:12:34:56','addresses':['192.168.122.10']}] if connected else [],'message':'Demo: Gastagent verbunden.' if connected else 'QEMU-Gastagent im Gast installieren und aktivieren.'},
                    'snapshot_note':'Demo: Kalte Snapshots enthalten alle Laufwerke; RAM wird nicht gespeichert. Externe Sicherungen werden separat erstellt.',
                    'offline_required':True,'external_backup_available':True}
        if operation == 'vm_guest_action':
            if args.get('action') not in ('shutdown','reboot') or not state['guest_agent'] or item['state']!='running': raise Error('Gastagent ist nicht verbunden.',409)
            if args['action']=='shutdown': item['state']='shut off'
            return {'ok':True,'demo':True,'mode':'agent'}
        if operation in ('vm_snapshot_create','vm_snapshot_restore_new','vm_backup'):
            if type(args.get('shutdown',False)) is not bool: raise Error('Herunterfahren muss Ja oder Nein sein.')
            if args.get('shutdown') and item['state'] in ('running','in shutdown'): item['state']='shut off'
        if item['state']!='shut off': raise Error('Die VM zuerst vollständig herunterfahren.',409)
        if operation == 'vm_backup':
            target=args.get('target') or self.backup_settings['target']
            self.demo_target(target)
            self.backup_settings['target']=target
            record={'id':'b-demo-'+uuid.uuid4().hex[:12],'type':'vm','created':time.time(),
                    'bytes':sum(disk['allocated_bytes'] for disk in state['disks']), 'vm_name':item['name'],
                    'name':item['name'],'vm':copy.deepcopy(item),'hardware':copy.deepcopy({key:value for key,value in state.items() if key!='snapshots'}),
                    'shares':[],'include_config':False,'vm_disks':[{'target':disk['target'],'virtual_size':disk['virtual_size']} for disk in state['disks']]}
            self.backup_records.insert(0,record)
            return {'ok':True,'demo':True,'message':'Demo: Vollständige VM-Sicherung simuliert.','backup':copy.deepcopy(record)}
        if operation == 'vm_guest_agent':
            if not isinstance(args['enabled'],bool): raise Error('Gastagent-Einstellung muss Ja oder Nein sein.')
            state['guest_agent']=args['enabled']
        elif operation in ('vm_clone','vm_snapshot_restore_new'):
            name, label = vm_identity(args['name'])
            if any(vm['name']==name or vm.get('display_name',vm['name'])==label for vm in self.vms): raise Error('VM-Name wird bereits verwendet.',409)
            checkpoint=next((record for record in state['snapshots'] if record['id']==args.get('snapshot')),None) if operation=='vm_snapshot_restore_new' else None
            if operation=='vm_snapshot_restore_new' and checkpoint is None: raise Error('Snapshot nicht gefunden.',404)
            cloned=copy.deepcopy(checkpoint['vm'] if checkpoint else item);cloned.update(id=str(uuid.uuid4()),name=name,display_name=label,disk_path='/var/lib/libvirt/images/titan/'+name+'.qcow2',state='shut off',autostart=False)
            self.vms.append(cloned)
            hardware=copy.deepcopy(checkpoint['hardware'] if checkpoint else state);hardware['snapshots']=[]
            for index,disk in enumerate(hardware['disks']):disk['disk']='/var/lib/libvirt/images/titan/'+name+('' if index==0 else '--'+uuid.uuid4().hex)+'.qcow2'
            for nic in hardware['networks']:nic['mac']=''
            self._demo_vm_hardware[cloned['id']]=hardware
            return {'ok':True,'demo':True,'id':cloned['id'],'name':name,'source_vm':item['id'],'source_preserved':True,
                    'message':'Demo: Eigenständige neue VM simuliert; ursprüngliche VM bleibt erhalten.'}
        elif operation == 'vm_disk_add':
            if state['snapshots']: raise Error('Vor dem Ändern der Laufwerksanzahl Snapshots entfernen.',409)
            if len(state['disks'])>=8: raise Error('Bis zu acht Laufwerke werden unterstützt.')
            size=integer(args['disk_gb'],1,16384)*1024**3
            used={disk['target'] for disk in state['disks']};target=next('vd'+char for char in 'bcdefghijklmnopqrstuvwxyz' if 'vd'+char not in used)
            state['disks'].append({'disk':'/var/lib/libvirt/images/titan/'+item['name']+'--'+uuid.uuid4().hex+'.qcow2','target':target,'storage':args.get('storage','system'),'virtual_size':size,'allocated_bytes':196608,'boot':False})
        elif operation == 'vm_disk_remove':
            if state['snapshots']: raise Error('Vor dem Entfernen des Laufwerks Snapshots entfernen.',409)
            disk=next((disk for disk in state['disks'][1:] if disk['target']==args.get('target')),None)
            if disk is None: raise Error('Nur zusätzliche Laufwerke können getrennt werden.')
            state['disks'].remove(disk)
            return {'ok':True,'demo':True,'disk_retained':True,'disk':disk['disk']}
        elif operation == 'vm_nic_add':
            if len(state['networks'])>=8: raise Error('Bis zu acht Netzwerkkarten werden unterstützt.')
            network=args.get('network',{})
            if not isinstance(network,dict) or network.get('mode') not in ('network','bridge','direct'): raise Error('Verfügbares Netzwerk auswählen.')
            state['networks'].append({'index':len(state['networks']),**network})
        elif operation == 'vm_nic_remove':
            index=integer(args['index'],0,len(state['networks'])-1)
            state['networks'].pop(index)
            for index,network in enumerate(state['networks']): network['index']=index
        elif operation == 'vm_snapshot_create':
            name=args.get('name','')
            if not isinstance(name,str) or not name.strip() or len(name)>80:raise Error('Snapshot-Name muss 1–80 Zeichen enthalten.')
            snapshot={'id':'s-'+uuid.uuid4().hex,'name':name,'created':time.time(),'disk_count':len(state['disks']),'mode':'offline-disks','hardware':copy.deepcopy({key:value for key,value in state.items() if key!='snapshots'}),'vm':copy.deepcopy(item)}
            state['snapshots'].append(snapshot)
            return {'ok':True,'demo':True,'snapshot':{key:snapshot[key] for key in ('id','name','created','disk_count','mode')}}
        elif operation in ('vm_snapshot_restore','vm_snapshot_remove'):
            snapshot=next((record for record in state['snapshots'] if record['id']==args.get('snapshot')),None)
            if snapshot is None:raise Error('Snapshot nicht gefunden.',404)
            if operation=='vm_snapshot_remove':state['snapshots'].remove(snapshot)
            else:
                item.update(copy.deepcopy(snapshot['vm']))
                for key,value in snapshot['hardware'].items():state[key]=copy.deepcopy(value)
        return {'ok':True,'demo':True,'message':'Demo: Änderung gespeichert; keine VM oder Hostdatei verändert.'}

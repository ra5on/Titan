import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from titan.core import Error
from titan.catalog import APPS,compose,published_ports
from titan.store_recipes import recipes
from titan.compose_templates import translate,validate_stack
from titan.app_devices import apply,validate
from titan.vm_metrics import VMMetricsMixin,parse_stats
from titan.dashboard_layout import save_layout,load_layout

class ExtendedDesktopTests(unittest.TestCase):
    def test_stack_preserves_shared_storage_dependencies_and_adjustable_ports(self):
        doc={'services':{'web':{'image':'example/web:1','ports':['8080:80','443:443'],'environment':{'DB_HOST':'db','DB_PASSWORD':'initial'},'volumes':['/DATA/App:/data'],'depends_on':['db']},'db':{'image':'postgres:16','environment':{'POSTGRES_PASSWORD':'initial'},'volumes':['/DATA/DB:/var/lib/postgresql/data']}},'x-casaos':{'port_map':'8080','main':'web','title':'Example'}}
        translated=translate(doc,'example','owner/store')
        parsed=recipes({'schema':1,'name':'Example','apps':[translated]},'https://github.com/owner/store')[1]
        app_id=next(iter(parsed));recipe=parsed[app_id]
        options={field['key']:'private' if field['type']=='password' else field['default'] for field in recipe['install_schema']}
        with patch.dict(APPS,parsed):
            rendered=compose(app_id,'/var/lib/titan-agent/apps/'+app_id,1000,1000,8088,'/var/srv/titan/apps/'+app_id,options)
            main=rendered['services'][app_id];db=rendered['services'][app_id+'-db']
            self.assertEqual(main['depends_on'],[app_id+'-db']);self.assertEqual(db['networks']['default']['aliases'],['db'])
            self.assertIn('8088:80/tcp',main['ports']);self.assertNotIn('/DATA',json.dumps(rendered));self.assertNotIn('initial',json.dumps(recipe))
            self.assertEqual(main['environment']['DB_PASSWORD'],db['environment']['POSTGRES_PASSWORD'])
            self.assertEqual(len(published_ports(app_id,8088,options)),2)
            with self.assertRaises(Error):compose(app_id,'/tmp/app',1,1,8088,'/tmp/data',options,{'mode':'host'})
    def test_template_rejects_privilege_paths_cycles_and_dynamic_commands(self):
        for value in [ {'primary':'web','services':{'web':{'image':'a:1','privileged':True}}}, {'primary':'web','services':{'web':{'image':'a:1','command':['${HOST_TOKEN}']}}}, {'primary':'web','services':{'web':{'image':'a:1','depends_on':['db']},'db':{'image':'b:1','depends_on':['web']}}} ]:
            with self.assertRaises(Error):validate_stack(value)
    def test_devices_are_explicit_and_missing_devices_rejected(self):
        inventory=[{'id':'/dev/ttyUSB0','path':'/dev/ttyUSB0','label':'USB','kind':'usb','group':20}]
        self.assertEqual(validate(['/dev/ttyUSB0'],inventory),['/dev/ttyUSB0'])
        for selection in [['/dev/sda'],['/dev/ttyUSB0','/dev/ttyUSB0'],{'all':True}]:
            with self.assertRaises(Error):validate(selection,inventory)
        definition=apply({'services':{'test':{}}},'test',inventory)
        self.assertEqual(definition['services']['test']['devices'],['/dev/ttyUSB0:/dev/ttyUSB0:rw'])
        self.assertEqual(definition['services']['test']['group_add'],['20']);self.assertNotIn('privileged',definition['services']['test'])
        self.assertEqual(apply({'services':{'test':{}}},'test',[]),{'services':{'test':{}}})
    def test_vm_rates_and_absent_guest_memory_are_honest(self):
        class Host(VMMetricsMixin):
            output="Domain: 'titan-lab'\n cpu.time=1000000000\n balloon.rss=1024\n block.0.rd.bytes=100\n"
            def command(self,*args,**kwargs):return self.output
        host=Host();vm={'id':'id','name':'lab','state':'running','cpus':2,'disk_allocated_bytes':4096}
        with patch('titan.vm_metrics.time.monotonic',return_value=10):host.vm_measurements([vm])
        self.assertIsNone(vm['metrics']['cpu_percent']);self.assertIsNone(vm['metrics']['memory_guest_used_bytes']);self.assertEqual(vm['metrics']['memory_resident_bytes'],1048576)
        host.output="Domain: 'titan-lab'\n cpu.time=3000000000\n block.0.rd.bytes=2100\n balloon.available=2048\n balloon.unused=512\n"
        with patch('titan.vm_metrics.time.monotonic',return_value=12):host.vm_measurements([vm])
        self.assertEqual(vm['metrics']['cpu_percent'],50);self.assertEqual(vm['metrics']['disk_read_bps'],1000);self.assertEqual(vm['metrics']['memory_guest_used_bytes'],1536*1024)
        self.assertIsNone(vm['metrics']['disk_write_bps']);self.assertEqual(parse_stats('Domain: bad\n cpu.time=no'),{})
    def test_single_host_template_retains_network_and_data_destination(self):
        source={'services':{'web':{'image':'example/web:1','network_mode':'host','volumes':['/DATA/Media:/media']}},'x-casaos':{'port_map':'8096'}}
        template=translate(source,'host-app','owner/store')
        self.assertEqual(template['default_network'],'host')
        app_id,recipe=next(iter(recipes({'schema':1,'name':'Test','apps':[template]},'https://github.com/owner/store')[1].items()))
        with patch.dict(APPS,{app_id:recipe}):
            definition=compose(app_id,'/var/lib/titan/apps/'+app_id,1000,1000,8096,'/var/srv/titan/media',{}, {'mode':'host'})
        service=definition['services'][app_id]
        self.assertEqual(service['network_mode'],'host');self.assertNotIn('ports',service);self.assertNotIn('networks',service)
        self.assertEqual(service['volumes'][0]['source'],'/var/srv/titan/media')

    def test_docker_measurements_parse_units_without_inventing_values(self):
        from titan.app_metrics import parse_stats
        values=parse_stats(json.dumps({'Name':'titan-test','CPUPerc':'3.25%','MemUsage':'64MiB / 1GiB','BlockIO':'1.5MB / 2kB'})+'\n'+json.dumps({'Name':'titan-bad','CPUPerc':'NaN%'}))
        self.assertEqual(values['titan-test']['memory_bytes'],64*1024**2)
        self.assertEqual(values['titan-test']['disk_read_bytes'],1500000);self.assertNotIn('titan-bad',values)
        self.assertIsNone(parse_stats(json.dumps({'Name':'titan-test','CPUPerc':'0%'}))['titan-test']['disk_write_bytes'])

    def test_tile_visibility_and_width_persist_per_account(self):
        class Store:
            data={}
            def config(self,key,default):return self.data.get(key,default)
            def set_config(self,key,value):self.data[key]=value
        store=Store();save_layout(store,'one',{'order':['tools'],'hidden':['shares'],'wide':['tools','vms']})
        self.assertEqual(load_layout(store,'one')['hidden'],['shares']);self.assertNotIn('hidden',load_layout(store,'two'))
        for value in [{'order':[],'hidden':['unknown']},{'order':[],'hidden':[{}]},{'order':[],'wide':['vms','vms']}]:
            with self.assertRaises(Error):save_layout(store,'one',value)

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import xml.etree.ElementTree as ET
from titan.app_stores import StoreMixin, recipes, store_url
from titan.store_sources import LINUXSERVER, PRESETS, casaos_document, linuxserver_document
from titan.core import Error
from titan.host import Host
from titan.catalog import APPS

class SourcesTests(unittest.TestCase):
    def image(self, **config):
        return {'name':'example','stable':True,'description':'Example web app', 'config':{'ports':[{'internal':'8080','external':'8080','desc':'Web UI','optional':False}], **config}}

    def convert(self, item):
        return linuxserver_document({'data':{'repositories':{'linuxserver':[item]}}})

    def test_linuxserver_builds_explicit_images_and_secret_fields(self):
        doc, skipped = self.convert(self.image(env_vars=[{'name':'PASSWORD','value':'unsafe-public-password','optional':False}], volumes=[{'path':'/config','optional':False}]))
        self.assertFalse(skipped)
        app=next(iter(recipes(doc,LINUXSERVER)[1].values()))
        self.assertEqual(app['image'],'lscr.io/linuxserver/example:latest')
        self.assertEqual(app['install_schema'][0]['type'],'password')
        self.assertEqual(app['install_schema'][0]['default'],'')
        self.assertNotIn('unsafe-public-password',json.dumps(app))

    def test_linuxserver_does_not_silently_drop_required_devices_or_volumes(self):
        for cfg in ({'devices':[{'path':'/dev/dri'}]}, {'volumes':[{'path':'/movies'},{'path':'/downloads'}]}, {'custom':[{'optional':False,'name':'shm-size'}]}):
            doc, skipped=self.convert(self.image(**cfg))
            self.assertFalse(doc['apps'])
            self.assertEqual(len(skipped),1)

    def archive(self, document):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive: archive.writestr('Apps/example/docker-compose.yml',document)
        return data.getvalue()

    def test_casaos_import_translates_paths_and_never_executes_compose(self):
        data=json.dumps({'services':{'app':{'image':'example/app:1','ports':['8081:80'],'volumes':['/DATA/AppData/example:/config']}}, 'x-casaos':{'title':{'en_US':'Example'},'port_map':'8081'}})
        doc, skipped=casaos_document(self.archive(data),'owner/store')
        self.assertFalse(skipped)
        app=next(iter(recipes(doc,'https://github.com/owner/store')[1].values()))
        self.assertTrue(app['config_mount'])
        self.assertIsNone(app['mount'])
        self.assertNotIn('/DATA',json.dumps(app))
        self.assertEqual(app['port'],80)

    def test_casaos_rejects_privileges_multiservice_host_mounts_and_aliases(self):
        base={'services':{'app':{'image':'example/app:1','ports':['8081:80']}},'x-casaos':{'port_map':'8081'}}
        for key,value in [('privileged',True),('command','echo ${UNRESOLVED}'),('volumes',['/var/run/docker.sock:/socket'])]:
            doc=json.loads(json.dumps(base));doc['services']['app'][key]=value
            with self.assertRaises(ValueError): casaos_document(self.archive(json.dumps(doc)),'owner/store')
        base['services']['db']={'image':'db:1'}
        converted, skipped = casaos_document(self.archive(json.dumps(base)),'owner/store')
        self.assertFalse(skipped)
        self.assertEqual(len(converted['apps'][0]['stack']['services']),2)
        with self.assertRaises(ValueError): casaos_document(self.archive('services: &root\n  app: *root'),'owner/store')

    def test_presets_have_valid_urls_and_default_can_be_disabled_without_removing_apps(self):
        class MemoryHost(StoreMixin):
            def __init__(self):self.rows={}
            def load(self,key,default):return self.rows.get(key,default)
            def save(self,key,value):self.rows[key]=value
        for store in PRESETS:self.assertEqual(store_url(store['url']),store['url'])
        host=MemoryHost();host.op_app_store_toggle('linuxserver',False)
        with patch('titan.app_stores.catalog',return_value={'apps':[{'id':'jellyfin','name':'Jellyfin'}]}):self.assertEqual(host.op_catalog()['apps'],[])
        self.assertIn('jellyfin',APPS)
        host.op_app_store_toggle('linuxserver',True)
        self.assertTrue(host.op_app_stores()['stores'][0]['enabled'])

    def test_new_sources_do_not_rewrite_legacy_rollback_catalog(self):
        class MemoryHost(StoreMixin):
            def __init__(self): self.rows={'app-stores':[]}
            def load(self,key,default): return self.rows.get(key,default)
            def save(self,key,value): self.rows[key]=value
        host=MemoryHost()
        host.op_app_store_toggle('linuxserver',False)
        self.assertEqual(host.rows['app-stores'],[])
        self.assertEqual(host.rows['app-store-sources-v2'][0]['url'],LINUXSERVER)
        host.op_app_store_toggle('linuxserver',True)
        self.assertEqual(host.rows['app-stores'],[])

    def test_refresh_keeps_installed_retired_recipe_after_restart_and_disable(self):
        class MemoryHost(StoreMixin):
            def __init__(self): self.rows={}
            def load(self,key,default): return self.rows.get(key,default)
            def save(self,key,value): self.rows[key]=value
        host=MemoryHost()
        url='https://raw.githubusercontent.com/example/store/main/store.json'
        def document(slug):
            return {'schema':1,'name':'Test','apps':[{'id':slug,'name':slug,'description':'A test app','image':'example/app:1', 'port':8080,'documentation':'https://example.org/docs','login_note':'Create the initial account in the application.'}]}
        old,new=document('old'),document('new')
        old_id=next(iter(recipes(old,url)[1]));new_id=next(iter(recipes(new,url)[1]))
        try:
            with patch.object(host,'store_document',return_value=(old,[])): host.op_app_store_add(url,trusted=True)
            row=next(row for row in host.op_app_stores()['stores'] if row['url']==url)
            host.rows['apps']=[{'id':old_id}]
            with patch.object(host,'store_document',return_value=(new,[])): host.op_app_store_refresh(row['id'])
            self.assertIn(old_id,APPS)
            APPS.pop(old_id)
            host.initialize_app_stores()
            self.assertIn(old_id,APPS)
            host.op_app_store_toggle(row['id'],False)
            with patch('titan.app_stores.catalog',return_value={'apps':[{'id':old_id,'store_url':url},{'id':new_id,'store_url':url}]}):
                self.assertEqual([item['id'] for item in host.op_catalog()['apps']],[old_id])
            with self.assertRaises(Error): host.op_app_store_remove(row['id'])
        finally:
            APPS.pop(old_id,None);APPS.pop(new_id,None)

class FirmwareTests(unittest.TestCase):
    def test_uefi_xml_requests_q35_and_persistent_vars_bios_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'vms').mkdir()
            host=Host(root/'agent',root/'shares',root/'vms',root/'smb')
            with patch.object(host,'vm_resources',return_value=(2,2048)),patch.object(host,'validate_vm_firmware'),patch.object(host,'validate_vm_disk_path'):
                uefi=ET.fromstring(host.vm_definition('guest',2,2048,root/'vms'/'guest.qcow2',firmware='uefi'))
                bios=ET.fromstring(host.vm_definition('legacy',2,2048,root/'vms'/'legacy.qcow2'))
            self.assertEqual(uefi.find('os').get('firmware'),'efi')
            self.assertEqual(uefi.find('./os/type').get('machine'),'q35')
            self.assertEqual(uefi.findtext('./os/nvram'),'/var/lib/libvirt/qemu/nvram/titan-guest_VARS.fd')
            self.assertIsNone(bios.find('./os/nvram'))
            self.assertEqual(host.vm_media_info(uefi)['firmware'],'uefi')
            self.assertEqual(host.vm_media_info(bios)['firmware'],'bios')

    def test_invalid_or_missing_firmware_is_rejected(self):
        with self.assertRaises(Error): Host.validate_vm_firmware('arbitrary-loader')
        with patch('titan.vm_management.Path.is_file',return_value=False):
            with self.assertRaises(Error) as result: Host.validate_vm_firmware('uefi')
            self.assertEqual(result.exception.status,503)

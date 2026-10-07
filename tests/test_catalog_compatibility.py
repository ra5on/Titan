"""Recipe imports preserve isolation, bindings and bounded runtime semantics."""
import copy
import io
import json
import threading
import unittest
from unittest.mock import patch
import zipfile

from titan.app_stores import StoreMixin
from titan.bigbear import URL, archive_document, translate
from titan.catalog import APPS, compose, published_ports
from titan.compose_templates import UnsupportedTemplate, duration, memory_size
from titan.core import Error
from titan.store_recipes import recipes
from titan.package_center import PackageCenterMixin


def source():
    return {'services':{'web':{'image':'example/app:1','ports':['8088:80'],'volumes':['data:/data']}}}


def document():
    return {'schema':1,'name':'BigBear','apps':[translate(source(), {'name':'Example','port':'8088'}, 'example')]}


class MemoryHost(StoreMixin):
    catalog_auto_bootstrap = True
    def __init__(self): self.rows = {}; self.app_config_lock = threading.RLock()
    def load(self, key, default): return copy.deepcopy(self.rows.get(key, default))
    def save(self, key, value): self.rows[key] = copy.deepcopy(value)


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.original = copy.deepcopy(APPS)
        self.addCleanup(self.restore)

    def restore(self): APPS.clear(); APPS.update(self.original)

    def register(self, doc, port='8088'):
        _, parsed = recipes({'schema':1,'name':'BigBear','apps':[translate(doc, {'name':'Example','port':port}, 'example')]}, URL)
        APPS.update(parsed)
        return next(iter(parsed)), next(iter(parsed.values()))

    def test_common_compose_syntax_keeps_runtime_protections_and_healthchecks(self):
        doc = source(); row = doc['services']['web']
        row.update(shm_size='1gb', mem_limit='512MiB', user='root:root', read_only=True, init=True,
                   cap_drop=['ALL'], security_opt=['no-new-privileges'], tmpfs=['/tmp'],
                   stop_grace_period='1m30s', expose=[9000],
                   healthcheck={'test':'curl -f http://127.0.0.1/ || exit 1', 'interval':'1m30s', 'timeout':'0.5s', 'start_interval':'5s', 'retries':30})
        key, recipe = self.register(doc)
        service = compose(key, '/control', 1000, 1000, 8088, '/data')['services'][key]
        self.assertEqual(service['user'], '0:0')
        self.assertEqual(service['shm_size'], '1g')
        self.assertEqual(service['mem_limit'], '512m')
        self.assertEqual(service['healthcheck']['test'][0], 'CMD-SHELL')
        self.assertEqual(service['healthcheck']['interval'], '1m30s')
        self.assertEqual(service['healthcheck']['retries'], 30)
        for field in ('read_only','init','cap_drop','tmpfs','stop_grace_period'):
            self.assertEqual(service[field], row[field])
        self.assertEqual(service['security_opt'], ['no-new-privileges:true'])
        self.assertEqual(service['expose'], ['9000'])

    def test_loopback_binding_and_small_port_ranges_survive_deployment(self):
        doc = source(); doc['services']['web']['ports'] = ['127.0.0.1:8088:80', '12000-12002:12000-12002/udp']
        key, recipe = self.register(doc)
        ports = published_ports(key, 8090)
        self.assertEqual(ports[0]['host_ip'], '127.0.0.1')
        self.assertEqual(len(ports), 4)
        service = compose(key, '/control', 1000, 1000, 8090, '/data')['services'][key]
        self.assertEqual(service['ports'], ['127.0.0.1:8090:80/tcp','12000:12000/udp','12001:12001/udp','12002:12002/udp'])
        with self.assertRaises(Error):
            doc['services']['web']['ports'] = ['1000-2000:1000-2000']; self.register(doc)

    def test_multiple_publications_of_one_target_are_not_silently_collapsed(self):
        doc = source(); doc['services']['web']['ports'] = ['127.0.0.1:8088:80','192.168.10.18:8089:80']
        with self.assertRaises(UnsupportedTemplate) as caught: self.register(doc)
        self.assertEqual(caught.exception.code, 'ports')

    def test_private_network_segments_and_aliases_are_not_collapsed(self):
        doc = source()
        doc['networks'] = {'front': {'driver':'bridge'}, 'back':{'driver':'bridge','internal':True}}
        doc['services']['web']['networks'] = {'front':{'aliases':['public']},'back':{}}
        doc['services']['db'] = {'image':'postgres:17','networks':['back']}
        doc['services']['worker'] = {'image':'example/worker:1'}
        key, recipe = self.register(doc)
        built = compose(key, '/control', 1000, 1000, 8088, '/data')
        self.assertEqual(set(built['services'][key]['networks']), {'front','back'})
        self.assertEqual(set(built['services'][key+'-db']['networks']), {'back'})
        self.assertEqual(set(built['services'][key+'-worker']['networks']), {'default'})
        self.assertTrue(built['networks']['back']['internal'])
        self.assertIn('public', built['services'][key]['networks']['front']['aliases'])
        self.assertIn('default', built['networks'])
        self.assertNotIn('name', built['networks']['front'])

    def test_headless_udp_service_has_no_invented_web_publication(self):
        doc = {'services':{'game':{'image':'example/game:1','ports':['30000:30000/udp']}}}
        key, recipe = self.register(doc, '30000')
        self.assertFalse(recipe['web_available'])
        self.assertEqual(recipe['port'], 0)
        self.assertEqual(recipe['default_port'], 0)
        self.assertEqual(published_ports(key, 0), [{'host':30000,'target':30000,'protocol':'udp','service':'game'}])
        self.assertEqual(compose(key, '/control', 1000, 1000, 0, '/data')['services'][key]['ports'], ['30000:30000/udp'])
        with self.assertRaises(Error): published_ports(key, 8088)

    def test_headless_background_worker_does_not_need_any_port(self):
        key, recipe = self.register({'services':{'job':{'image':'example/job:1'}}}, '')
        self.assertFalse(recipe['web_available'])
        self.assertEqual(published_ports(key, 0), [])
        self.assertEqual(compose(key, '/control', 1000, 1000, 0, '/data')['services'][key]['ports'], [])

    def test_metadata_may_identify_the_internal_webport_instead_of_publication(self):
        doc = source(); doc['services']['web']['ports'] = [{'target':9283,'published':80,'protocol':'tcp'}]
        key, recipe = self.register(doc, '9283')
        self.assertTrue(recipe['web_available'])
        self.assertEqual(recipe['port'], 9283)
        self.assertEqual(recipe['default_port'], 9283)
        self.assertEqual(published_ports(key, 9283)[0]['target'], 9283)
        self.assertEqual(compose(key, '/control', 1000, 1000, 9283, '/data')['services'][key]['ports'], ['9283:9283/tcp'])

    def test_basic_auth_pass_is_a_private_password_even_if_upstream_uses_empty_quotes(self):
        for published in ('', '""', "''", 'PUBLIC_DEFAULT_MUST_NOT_LEAK'):
            doc = source(); doc['services']['web']['environment'] = {'BASIC_AUTH_PASS':published}
            key, recipe = self.register(doc)
            field = recipe['install_schema'][0]
            self.assertEqual(field['type'], 'password')
            self.assertEqual(field['default'], '')
            self.assertNotIn('PUBLIC_DEFAULT_MUST_NOT_LEAK', json.dumps(recipe))
            with self.assertRaises(Error): published_ports(key, 8088)
            service = compose(key, '/control',1000,1000,8088,'/data',{field['key']:'private$Password'})['services'][key]
            self.assertEqual(service['environment']['BASIC_AUTH_PASS'], 'private$$Password')

    def test_old_cached_and_frozen_descriptors_do_not_expose_saved_pass_in_logs(self):
        doc = source(); doc['services']['web']['environment'] = {'BASIC_AUTH_PASS':'old-default'}
        item = translate(doc, {'name':'Example','port':'8088'}, 'example')
        # A cache written by the older adapter did not recognize *_PASS.
        item['stack_fields'][0].update(type='text', default='old-default', min_length=0)
        _, parsed = recipes({'schema':1,'name':'BigBear','apps':[item]}, URL)
        key, recipe = next(iter(parsed.items()))
        field = recipe['install_schema'][0]
        self.assertEqual(field['type'], 'password')
        self.assertEqual(field['default'], '')
        frozen = copy.deepcopy(recipe); frozen['install_schema'][0].update(type='text',default='old-default')
        host = MemoryHost(); host.catalog_auto_bootstrap = False
        host.rows = {'apps':[{'id':key}], 'installed-app-recipes-v1':{key:frozen}}
        host.initialize_app_stores()
        self.assertEqual(APPS[key]['install_schema'][0]['type'], 'password')
        self.assertEqual(APPS[key]['stack'], frozen['stack'])
        class Logs(PackageCenterMixin):
            def _app_options(self, app): return {field['key']:'private$oldPassword'}
        self.assertEqual(Logs()._package_redact(key,'private$oldPassword and private$$oldPassword'), '[ausgeblendet] and [ausgeblendet]')

    def test_permissions_are_structured_and_never_granted_silently(self):
        for key, value, kind in [('privileged',True,'privileged'),('devices',['/dev/dri:/dev/dri'],'devices'),('cap_add',['SYS_ADMIN'],'capabilities')]:
            doc = source(); doc['services']['web'][key] = value
            with self.assertRaises(UnsupportedTemplate) as caught: self.register(doc)
            self.assertEqual(caught.exception.code, 'permissions')
            self.assertEqual(caught.exception.requirements[0]['kind'], kind)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for label, doc in [('okay',source()),('socket',{'services':{'app':{'image':'example/app:1','ports':['8088:80'],'volumes':['/var/run/docker.sock:/var/run/docker.sock']}}})]:
                archive.writestr('Apps/'+label+'/compose.yaml', json.dumps(doc))
                archive.writestr('Apps/'+label+'/metadata.json', json.dumps({'port':'8088'}))
        _, skipped = archive_document(stream.getvalue())
        self.assertEqual(skipped[0]['code'], 'host_mount')
        self.assertEqual(skipped[0]['requirements'][0]['kind'], 'docker_socket')

    def test_more_than_400_apps_are_supported_but_import_remains_bounded(self):
        row = document()['apps'][0]
        doc = {'schema':1,'name':'BigBear','apps':[{**row,'id':'app-'+str(index)} for index in range(463)]}
        self.assertEqual(len(recipes(doc, URL)[1]), 463)
        with self.assertRaises(Error): recipes({**doc,'apps':doc['apps']*3}, URL)

    def test_memory_and_duration_validation_rejects_unbounded_or_dynamic_values(self):
        self.assertEqual(memory_size('1.5GiB'), '1536m')
        for value in ('1tb','0g','${RAM}','999999999999gb'):
            with self.subTest(value=value), self.assertRaises(Error): memory_size(value)
        for value in ('0s','1000h','${INTERVAL}','1m junk'):
            with self.subTest(value=value), self.assertRaises(Error): duration(value)



if __name__ == '__main__': unittest.main()

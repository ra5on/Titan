import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from titan.core import Error
from titan.docker_engine import DockerEngineMixin, identifier
from titan.app_metrics import cgroup_memory
from titan.vm_metrics import VMMetricsMixin
from titan.dashboard_layout import validate_sizes
from test_lifecycle_http import HTTPFixture

ID='a'*64
class Engine(DockerEngineMixin):
    pass

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.engine=Engine();self.engine.engine_docker=Mock(return_value=ID)
    def test_create_validates_everything_before_mutation_and_no_host_shell(self):
        config={'name':'web','image':'nginx:stable','ports':[{'published':8080,'target':80,'protocol':'tcp'}],'environment':{'VALUE':'$(touch /tmp/unsafe)'}}
        self.engine.op_docker_container_create(config)
        args=self.engine.engine_docker.call_args_list[0].args[0]
        self.assertEqual(args[:3],['create','--name','titan-custom-web'])
        self.assertIn('8080:80/tcp',args);self.assertIn('VALUE=$(touch /tmp/unsafe)',args)
        self.assertNotIn('sh',args);self.assertEqual(self.engine.engine_docker.call_args_list[1].args[0],['start',ID])
        for patch in [{'name':'--privileged'},{'image':'nginx;id'},{'privileged':True},{'ports':[{'published':5000,'target':80,'protocol':'tcp'}]},{'environment':{'a\0b':'bad'}},{'command':'sh -c id'}]:
            self.engine.engine_docker.reset_mock()
            with self.assertRaises(Error):self.engine.op_docker_container_create({**config,**patch})
            self.engine.engine_docker.assert_not_called()
    def manual_stopped(self):
        return {'Id':ID,'Name':'/titan-custom-web','Config':{'Image':'nginx:stable','Labels':{'io.titan.manual':'true'},'Env':['SECRET=private']},'State':{'Running':False,'Status':'exited'},'HostConfig':{'Memory':512*1048576,'NanoCpus':1000000000,'NetworkMode':'bridge','RestartPolicy':{'Name':'unless-stopped'},'PortBindings':{'80/tcp':[{'HostIp':'','HostPort':'8080'}]}},'Mounts':[]}

    def test_device_edit_preserves_backup_and_recreates_from_local_snapshot(self):
        row=self.manual_stopped();self.engine.engine_container=Mock(return_value=row)
        self.engine.op_app_devices=Mock(return_value={'devices':[]})
        image='sha256:'+'c'*64
        def docker(args,**kwargs):
            return image if args[0]=='commit' else 'b'*64
        self.engine.engine_docker.side_effect=docker
        result=self.engine.op_docker_container_hardware(ID,[])
        calls=[v.args[0] for v in self.engine.engine_docker.call_args_list]
        self.assertEqual(result['backup_container'],ID)
        self.assertTrue(any(v[:2]==['commit','--change'] for v in calls))
        self.assertIn(['rename',ID,'titan-previous-'+ID[:20]],calls)
        create=next(v for v in calls if v[0]=='create');self.assertEqual(create[-1],image)
        self.assertFalse(any(v[0]=='rm' for v in calls))
        self.assertNotIn('private',json.dumps(result))

    def test_device_edit_rejects_running_foreign_or_unknown_device_before_changes(self):
        self.engine.op_app_devices=Mock(return_value={'devices':[]})
        for patch,devices in [({'State':{'Running':True}},[]),({'Config':{'Labels':{}}},[]),({},['usb:fake'])]:
            self.engine.engine_container=Mock(return_value={**self.manual_stopped(),**patch})
            self.engine.engine_docker.reset_mock()
            with self.assertRaises(Error):self.engine.op_docker_container_hardware(ID,devices)
            self.engine.engine_docker.assert_not_called()

    def test_device_edit_restores_original_name_if_create_fails(self):
        self.engine.engine_container=Mock(return_value=self.manual_stopped())
        self.engine.op_app_devices=Mock(return_value={'devices':[]})
        self.engine.op_docker_container_create=Mock(side_effect=Error('create failed'))
        def docker(args,**kwargs):return 'sha256:'+'c'*64 if args[0]=='commit' else ''
        self.engine.engine_docker.side_effect=docker
        with self.assertRaises(Error):self.engine.op_docker_container_hardware(ID,[])
        self.assertEqual(self.engine.engine_docker.call_args.args[0],['rename',ID,'titan-custom-web'])

    def test_no_force_delete_or_volume_removal_with_container(self):
        self.engine.engine_container=Mock(return_value={'Id':ID,'Config':{},'State':{'Running':True}})
        with self.assertRaises(Error):self.engine.op_docker_container_action(ID,'remove')
        self.engine.engine_docker.assert_not_called()
        self.engine.engine_container.return_value['State']['Running']=False
        self.engine.op_docker_container_action(ID,'remove')
        self.engine.engine_docker.assert_called_once_with(['rm',ID],timeout=120)
    def test_managed_app_actions_keep_existing_validation(self):
        self.engine.engine_container=Mock(return_value={'Id':ID,'Config':{'Labels':{'io.titan.managed':'true','io.titan.app':'heimdall'}}})
        self.engine.op_app_action=Mock(return_value={'ok':True})
        self.engine.op_docker_container_action(ID,'start')
        self.engine.op_app_action.assert_called_once_with('heimdall','start');self.engine.engine_docker.assert_not_called()
    def test_summary_never_exposes_environment_secrets(self):
        summary=self.engine.engine_summary({'Id':ID,'Config':{'Image':'nginx','Env':['SECRET=private'],'Labels':{'PRIVATE':'hidden'}},'State':{'Status':'exited'}})
        self.assertNotIn('private',json.dumps(summary));self.assertNotIn('hidden',json.dumps(summary))
    def test_dynamic_web_port_is_validated_without_exposing_environment(self):
        row={'Id':ID,'Config':{'Labels':{'io.titan.managed':'true','io.titan.app':'qbittorrent'},'Env':['WEBUI_PORT=9090','SECRET=private']},'HostConfig':{'NetworkMode':'host'}}
        summary=self.engine.engine_summary(row)
        self.assertEqual(summary['web_port'],9090);self.assertEqual(summary['network_mode'],'host')
        self.assertNotIn('private',json.dumps(summary))
        row['Config']['Env']=['WEBUI_PORT=999999','SECRET=private']
        self.assertIsNone(self.engine.engine_summary(row)['web_port'])

    def test_local_volume_driver_cannot_smuggle_host_paths(self):
        self.engine.engine_docker.return_value=json.dumps([{'Driver':'local','Options':{'device':'/etc','o':'bind'}}])
        with self.assertRaises(Error):self.engine.op_docker_container_create({'name':'web','image':'nginx','volume':'host-path'})
        self.assertEqual(self.engine.engine_docker.call_count,1)
    def test_full_ids_required_and_unknown_actions_rejected(self):
        for value in ['abc','--help',ID+'x',None]:
            with self.assertRaises(Error):identifier(value)
    def test_batch_validates_all_before_mutation_and_deduplicates_managed_stack(self):
        other='b'*64
        labels={'io.titan.managed':'true','io.titan.app':'heimdall','com.docker.compose.project':'titan-heimdall'}
        self.engine.engine_container=Mock(side_effect=lambda value:{'Id':value,'Config':{'Labels':labels}})
        self.engine.op_docker_container_action=Mock(return_value={'ok':True})
        result=self.engine.op_docker_container_batch([ID,other],'restart')
        self.assertTrue(result['ok']);self.engine.op_docker_container_action.assert_called_once_with(ID,'restart')
        self.engine.op_docker_container_action.reset_mock()
        self.engine.engine_container.side_effect=[{'Id':ID,'Config':{}},Error('missing')]
        with self.assertRaises(Error):self.engine.op_docker_container_batch([ID,other],'stop')
        self.engine.op_docker_container_action.assert_not_called()
        for values,action in [([ID,ID],'start'),([ID],'remove'),([],'start'),([ID]*65,'stop')]:
            with self.assertRaises(Error):self.engine.op_docker_container_batch(values,action)

    def test_batch_reports_partial_failure_without_claiming_success(self):
        other='b'*64
        self.engine.engine_container=Mock(side_effect=lambda value:{'Id':value,'Config':{}})
        self.engine.op_docker_container_action=Mock(side_effect=[{'ok':True},Error('cannot start')])
        result=self.engine.op_docker_container_batch([ID,other],'start')
        self.assertFalse(result['ok']);self.assertEqual(result['completed'],[ID]);self.assertEqual(result['failed'][0]['container'],other)

    def test_cgroup_total_includes_cache_and_missing_measurement_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'proc/42').mkdir(parents=True);(root/'groups/system.slice/docker.scope').mkdir(parents=True)
            (root/'proc/42/cgroup').write_text('0::/system.slice/docker.scope\n')
            (root/'groups/system.slice/docker.scope/memory.current').write_text('104857600\n')
            self.assertEqual(cgroup_memory(42,root/'proc',root/'groups'),104857600)
            (root/'proc/42/cgroup').write_text('0::/../../etc\n')
            self.assertIsNone(cgroup_memory(42,root/'proc',root/'groups'));self.assertIsNone(cgroup_memory(0))
    def test_stopped_vm_cannot_publish_stale_balloon_and_running_list_is_corrected(self):
        host=type('Metrics',(VMMetricsMixin,),{'command':lambda *a,**kw:"Domain: 'titan-lab'\n state.state=5\n balloon.rss=9999999\n balloon.available=9999\n balloon.unused=0\n"})()
        vm={'id':ID,'name':'lab','state':'running','cpus':2}
        host.vm_measurements([vm]);self.assertEqual(vm['state'],'shut off');self.assertEqual(vm['metrics']['memory_resident_bytes'],0);self.assertEqual(vm['metrics']['memory_guest_used_bytes'],0)
    def test_size_preferences_bounded_and_no_boolean_dimensions(self):
        self.assertEqual(validate_sizes({'tools':{'columns':3,'height':400}})['tools']['columns'],3)
        for value in [{'bad':{'columns':1,'height':0}},{'tools':{'columns':True,'height':300}},{'tools':{'columns':2,'height':999999}}]:
            with self.assertRaises(Error):validate_sizes(value)

class EngineHTTPTests(HTTPFixture,unittest.TestCase):
    def test_engine_and_console_are_admin_only_and_arguments_strict(self):
        for path in ['/api/docker-engine','/api/docker-metrics','/api/docker-container?container='+ID,'/api/vm-console?vm=fixture']:
            self.assertEqual(self.request(path,actor=None)[0],401)
            self.assertEqual(self.request(path,actor='reader')[0],403)
        self.agent.call.assert_not_called()
        self.assertEqual(self.request('/api/vm-console?vm=fixture&extra=x')[0],400)
        self.assertEqual(self.request('/api/docker-container')[0],400)
        self.agent.call.return_value={'port':1234}
        self.assertEqual(self.json_request('/api/vm-console?vm=fixture')[1],{'ready':True})

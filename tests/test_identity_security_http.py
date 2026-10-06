from http.server import ThreadingHTTPServer
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock
from titan.core import Error
from titan.server import Application, Handler
from titan.security import totp


class IdentitySecurityHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Application(self.temp.name)
        self.app.store.create_user('admin','admin-password-long','admin','admin')
        self.app.store.create_user('reader','reader-password-long','user','reader')
        self.agent=Mock();self.agent.call.return_value={'ok':True}
        self.app.agent=self.agent;self.app.users.agent=self.agent;self.app.identity.agent=self.agent
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.app=self.app;self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
        self.sessions={name:self.app.store.login(name,name+'-password-long') for name in ('admin','reader')}

    def tearDown(self):
        deadline=time.monotonic()+3
        while any(job['status'] in ('queued','running') for job in self.app.store.jobs()) and time.monotonic()<deadline: time.sleep(.01)
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()

    def request(self,path,body=None,actor='reader',csrf=True):
        headers={'Content-Type':'application/json'}
        if actor:
            token,code=self.sessions[actor];headers['Cookie']='titan_session='+token;headers['X-CSRF-Token']=code if csrf else 'wrong'
        request=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(request) as response: return response.status,json.loads(response.read())
        except urllib.error.HTTPError as response: return response.code,json.loads(response.read())

    def test_security_overview_scoped_to_self(self):
        status,data=self.request('/api/security')
        self.assertEqual(status,200);self.assertTrue(all(item['username']=='reader' for item in data['sessions']))
        self.assertEqual(self.request('/api/security?all=1')[0],403)
        self.assertEqual(self.request('/api/security?all=1',actor='admin')[0],200)
        self.agent.call.assert_not_called()

    def test_global_totp_count_is_only_exposed_to_admin_overview(self):
        setup=self.app.security.begin('reader','reader-password-long')
        self.app.security.confirm('reader','reader-password-long',totp(setup['secret'],int(time.time()//30)),current_token=self.sessions['reader'][0])
        status,data=self.request('/api/security?all=1',actor='admin')
        self.assertEqual(status,200);self.assertEqual(data['two_factor_user_count'],1)
        self.assertNotIn('two_factor_user_count',self.request('/api/security')[1])
        self.assertEqual(self.request('/api/security?all=1')[0],403)
        self.assertNotIn(setup['secret'],str(data))

    def test_regular_user_cannot_edit_groups_or_quota_of_other_user(self):
        self.assertEqual(self.request('/api/identity')[0],403)
        self.assertEqual(self.request('/api/identity',{'schema':1,'groups':[],'users':{}})[0],403)
        self.assertEqual(self.request('/api/identity/quotas',{'name':'admin','target':'tank/data','limit_bytes':10})[0],403)
        self.agent.call.assert_not_called()

    def test_security_mutations_require_csrf(self):
        self.assertEqual(self.request('/api/security/totp/begin',{'password':'reader-password-long'},csrf=False)[0],403)
        self.assertFalse(self.app.security.overview('reader')['two_factor'])

    def test_http_totp_workflow_enforces_login_challenge(self):
        status,setup=self.request('/api/security/totp/begin',{'password':'reader-password-long'})
        self.assertEqual(status,200)
        code=totp(setup['secret'],int(time.time()//30))
        status,result=self.request('/api/security/totp/confirm',{'password':'reader-password-long','code':code})
        self.assertEqual(status,200);self.assertEqual(len(result['recovery_codes']),10)
        self.assertEqual(self.request('/api/security')[0],200,'Keep enrollment browser alive to save recovery codes.')
        self.assertEqual(self.request('/api/login',{'name':'reader','password':'reader-password-long'},actor=None)[0],401)
        status,login=self.request('/api/login',{'name':'reader','password':'reader-password-long','otp':result['recovery_codes'][0]},actor=None)
        self.assertEqual(status,200);self.assertNotIn('secret',login)

    def test_application_grant_opens_only_corresponding_routes(self):
        self.assertEqual(self.request('/api/vms')[0],403)
        self.app.store.set_config('identity',{'schema':1,'groups':[{'name':'vmusers','members':['reader'],'applications':{'vms':True},'shares':{}}],'users':{}})
        self.agent.call.return_value=[]
        self.assertEqual(self.request('/api/vms')[0],200)
        self.assertEqual(self.request('/api/docker-engine')[0],403)
        self.assertEqual(self.request('/api/users')[0],403)
        self.assertEqual(self.request('/api/updates/system')[0],403)
        self.assertEqual(self.request('/api/security')[0],200)

    def test_queued_vm_action_rechecks_revoked_application_right(self):
        policy={'schema':1,'groups':[],'users':{'reader':{'applications':{'vms':True},'shares':{}}}}
        self.app.store.set_config('identity',policy)
        self.app.admin_action('reader','vm_action',{'vm':'guest','action':'start'})
        self.agent.call.assert_called_once_with('vm_action',vm='guest',action='start')
        self.agent.call.reset_mock();policy['users']['reader']['applications']['vms']=False;self.app.store.set_config('identity',policy)
        with self.assertRaises(Error): self.app.admin_action('reader','vm_action',{'vm':'guest','action':'start'})
        self.agent.call.assert_not_called()

    def test_file_application_denial_is_server_enforced(self):
        self.app.store.set_config('identity',{'schema':1,'groups':[],'users':{'reader':{'applications':{'files':False},'shares':{}}}})
        self.assertEqual(self.request('/api/files?share=photos')[0],403)
        self.assertEqual(self.request('/api/shares')[0],403)
        self.assertEqual(self.request('/api/files',{'share':'photos','action':'mkdir','path':'x'})[0],403)
        self.agent.call.assert_not_called()

    def test_recursive_file_query_is_boolean_and_invalid_values_rejected(self):
        self.request('/api/files?share=photos&recursive=1&type=image')
        self.agent.call.assert_called_once_with('file',user='reader',share='photos',action='list',path='',offset=0,limit=200,search='',recursive=True,type='image')
        self.agent.call.reset_mock()
        self.assertEqual(self.request('/api/files?share=photos&recursive=true')[0],400)
        self.agent.call.assert_not_called()

    def grant_backups(self):
        self.app.store.set_config('identity',{'schema':1,'groups':[],'users':{'reader':{'applications':{'backups':True},'shares':{}}}})
        self.shares=[{'name':'photos','readers':['reader'],'writers':[]},{'name':'private','readers':[],'writers':['admin']},{'name':'destination','readers':[],'writers':['reader']}]
        self.manifest={'id':'backup-public','type':'shares','shares':['photos'],'include_config':False}
        self.agent.call.side_effect=lambda operation,**kwargs:self.shares if operation=='shares' else {'items':[self.manifest]} if operation=='backups' else {'ok':True}

    def test_delegated_backup_http_rejects_foreign_sources_and_config(self):
        self.grant_backups()
        for arguments in ({'shares':['private'],'include_config':False},{'shares':['photos'],'include_config':True},{'shares':['photos']}):
            status,_=self.request('/api/actions',{'operation':'backup_create','arguments':arguments})
            self.assertEqual(status,403)
        self.assertFalse(any(call.args[0]=='delegated_backup' for call in self.agent.call.call_args_list))
        self.assertEqual(self.request('/api/backup/settings',{'include_config':False})[0],403)

    def test_delegated_backup_http_restore_checks_target_write_access(self):
        self.grant_backups()
        args={'backup':'backup-public','paths':['photos/a.txt'],'share':'photos','name':'restore'}
        self.assertEqual(self.request('/api/actions',{'operation':'backup_restore_selection','arguments':args})[0],403)
        self.assertFalse(any(call.args[0]=='delegated_backup' for call in self.agent.call.call_args_list))

    def test_delegated_backup_job_rechecks_revoked_source_right(self):
        self.grant_backups()
        args={'shares':['photos'],'include_config':False}
        self.app.admin_action('reader','backup_create',args)
        self.assertTrue(any(call.args[0]=='delegated_backup' for call in self.agent.call.call_args_list))
        self.agent.call.reset_mock();self.shares[0]['readers']=[]
        with self.assertRaises(Error):self.app.admin_action('reader','backup_create',args)
        self.assertFalse(any(call.args[0]=='delegated_backup' for call in self.agent.call.call_args_list))

    def test_regular_user_cannot_revoke_another_user_session(self):
        session=self.app.security.overview('admin')['sessions'][0]
        self.assertEqual(self.request('/api/security/sessions/revoke',{'id':session['id']})[0],404)
        self.assertIsNotNone(self.app.store.session(self.sessions['admin'][0]))


if __name__=='__main__': unittest.main()

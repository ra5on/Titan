"""Office sessions cannot bypass current application/share rights or revisions."""
import base64
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from titan.core import Error
from titan.files import operate
from titan.office_gateway import sign
from titan.server import Application, Handler


class CacheResponse:
    status=200
    def __init__(self,content):self.content=content
    def read(self,size):return self.content[:size]
class CacheConnection:
    def __init__(self,content):self.content=content;self.requests=[]
    def request(self,*args,**kwargs):self.requests.append((args,kwargs))
    def getresponse(self):return CacheResponse(self.content)
    def close(self):pass


class OfficeGatewayHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.directory=Path(self.temporary.name)
        self.files=self.directory/'documents';self.files.mkdir();self.document=self.files/'Example.docx';self.original=b'PK\x03\x04\x00original-document';self.document.write_bytes(self.original)
        os.chmod(self.document,0o640)
        self.app=Application(self.directory/'web');self.app.store.create_user('writer','writer-password-long','user','writer');self.app.store.create_user('reader','reader-password-long','user','reader');self.app.store.create_user('admin','admin-password-long','admin','admin')
        self.share={'name':'docs','path':str(self.files),'readers':['reader'],'writers':['writer']}
        self.writes=[]
        self.app.agent=self
        self.runtime={'secret':'test-jwt-key-0123456789abcdef-0123456789abcdef','engine_origin':'http://127.0.0.1:19003','bridge_gateway':'172.20.0.1'}
        self.app.office_runtime=lambda:dict(self.runtime)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.app=self.app;self.server.daemon_threads=True;self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start();self.url='http://127.0.0.1:'+str(self.server.server_port)
        self.tokens={name:self.app.store.login(name,name+'-password-long') for name in ('writer','reader','admin')}

    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.temporary.cleanup()

    def call(self,operation,**args):
        if operation=='shares':return [dict(self.share)]
        if operation in ('file','admin_file','office_write'):
            admin=operation=='admin_file' or args.pop('admin',False)
            user=args.pop('user',None)
            share=args.pop('share');action='office_write' if operation=='office_write' else args.pop('action');path=args.pop('path','')
            if share!='docs':raise Error('Unknown share',404)
            if not admin and user not in self.share['readers']+self.share['writers']:raise Error('Share denied',403)
            if action=='office_write':
                if not admin and user not in self.share['writers']:raise Error('Read-only share',403)
                self.writes.append((user,path,dict(args)))
            return operate(self.files,action,path,**args)
        raise Error('Unexpected operation '+operation)

    def request(self,path,body=None,actor='writer',extra=None,csrf=True):
        headers={'Content-Type':'application/json',**(extra or {})}
        if actor:
            token,code=self.tokens[actor];headers['Cookie']='titan_session='+token;headers['X-CSRF-Token']=code if csrf else 'invalid'
        request=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(request) as response:return response.status,response.read()
        except urllib.error.HTTPError as response:return response.code,response.read()

    def start(self,actor='writer'):
        status,raw=self.request('/api/office/session',{'share':'docs','path':'Example.docx'},actor=actor)
        self.assertEqual(status,200,raw)
        result=json.loads(raw);session=result['url'].split('session=')[1]
        return session,self.app.store.config('office-sessions')[session]

    def callback(self,session,record,token=None):
        payload={'key':record['key'],'status':6,'url':self.runtime['engine_origin']+'/cache/files/new.docx'}
        return self.request('/office/internal/callback?session='+session,{'token':token or sign({'payload':payload},self.runtime['secret'])},actor=None)

    def test_document_config_needs_same_actor_and_does_not_expose_jwt_secret(self):
        session,record=self.start()
        self.assertEqual(self.request('/api/office/config?session='+session,actor='reader')[0],403)
        status,raw=self.request('/api/office/config?session='+session)
        self.assertEqual(status,200)
        self.assertNotIn(self.runtime['secret'].encode(),raw)
        self.assertTrue(json.loads(raw)['config']['document']['permissions']['edit'])

    def test_office_session_requires_csrf_and_current_file_application_right(self):
        self.assertEqual(self.request('/api/office/session',{'share':'docs','path':'Example.docx'},csrf=False)[0],403)
        self.app.store.set_config('identity',{'schema':1,'groups':[],'users':{'writer':{'applications':{'files':False},'shares':{}}}})
        self.assertEqual(self.request('/api/office/session',{'share':'docs','path':'Example.docx'})[0],403)

    def test_recovery_of_file_does_not_ignore_share_revocation(self):
        session,record=self.start();self.share['writers']=[]
        self.assertEqual(self.request('/office/internal/file?session='+session,actor=None)[0],403)
        self.assertFalse(self.writes)

    def test_caddy_backchannel_uses_canonical_nas_host_and_retains_acl_checks(self):
        session,record=self.start();self.app.origin='http://nas.example:5000'
        path='/office/internal/file?session='+session
        self.assertEqual(self.request(path,actor=None)[0],403,'The raw 5101/proxy Host must not bypass canonical Host validation.')
        status,content=self.request(path,actor=None,extra={'Host':'nas.example:5000'})
        self.assertEqual(status,200);self.assertEqual(content,self.original)
        self.share['writers']=[]
        self.assertEqual(self.request(path,actor=None,extra={'Host':'nas.example:5000'})[0],403)

    def test_invalid_signed_callback_cannot_write(self):
        session,record=self.start()
        status,raw=self.callback(session,record,token=sign({'payload':{'key':record['key'],'status':6,'url':self.runtime['engine_origin']+'/cache/files/new.docx'}},'wrong-test-key-0123456789abcdef'))
        self.assertEqual(status,200);self.assertEqual(json.loads(raw)['error'],1);self.assertEqual(self.document.read_bytes(),self.original);self.assertFalse(self.writes)

    def test_binary_save_preserves_mode_owner_and_updates_revision(self):
        session,record=self.start();before=self.document.stat();updated=b'PK\x03\x04\x00changed-document-content'
        connection=CacheConnection(updated)
        with patch('titan.office_gateway.engine_connection',return_value=connection):
            status,raw=self.callback(session,record)
        self.assertEqual(status,200);self.assertEqual(json.loads(raw)['error'],0,raw);self.assertEqual(self.document.read_bytes(),updated)
        after=self.document.stat();self.assertEqual((after.st_uid,after.st_gid,after.st_mode&0o777),(before.st_uid,before.st_gid,before.st_mode&0o777))
        latest=self.app.store.config('office-sessions')[session]
        self.assertNotEqual(latest['revision'],record['revision']);self.assertEqual(self.writes[0][0],'writer')

    def test_concurrent_external_edit_is_never_overwritten(self):
        session,record=self.start();self.document.write_bytes(b'Externally edited document')
        with patch('titan.office_gateway.engine_connection') as connection:
            status,raw=self.callback(session,record)
        self.assertEqual(json.loads(raw)['error'],1);connection.assert_not_called();self.assertEqual(self.document.read_bytes(),b'Externally edited document');self.assertFalse(self.writes)

    def test_live_writer_to_reader_change_rejects_save(self):
        session,record=self.start();self.share['writers']=[];self.share['readers'].append('writer')
        with patch('titan.office_gateway.engine_connection',return_value=CacheConnection(b'new document')):
            status,raw=self.callback(session,record)
        self.assertEqual(json.loads(raw)['error'],1);self.assertEqual(self.document.read_bytes(),self.original)

    def test_read_only_session_cannot_save(self):
        session,record=self.start(actor='reader');self.assertFalse(record['writable'])
        with patch('titan.office_gateway.engine_connection') as connection:
            status,raw=self.callback(session,record)
        self.assertEqual(json.loads(raw)['error'],1);connection.assert_not_called();self.assertFalse(self.writes)

    def test_signed_callback_url_cannot_fetch_outside_engine_cache(self):
        session,record=self.start();token=sign({'payload':{'key':record['key'],'status':6,'url':'http://169.254.169.254/latest/meta-data/'}},self.runtime['secret'])
        with patch('titan.office_gateway.engine_connection') as connection:
            status,raw=self.callback(session,record,token=token)
        self.assertEqual(json.loads(raw)['error'],1);connection.assert_not_called();self.assertFalse(self.writes)


if __name__=='__main__':unittest.main()

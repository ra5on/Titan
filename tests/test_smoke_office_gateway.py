"""Validate the CI Office fixture; the real engine is exercised by its workflow."""
import importlib.util
import hashlib
from http.server import ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

from titan.core import Error
from titan.files import operate
from titan.office_gateway import proxy_location, save_path
from titan.server import Application


spec=importlib.util.spec_from_file_location('titan_smoke_office_gateway',Path(__file__).resolve().parents[1]/'scripts/smoke-office-gateway.py')
smoke=importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class OfficeSmokeFixtureTests(unittest.TestCase):
    def test_generated_docx_is_valid_and_preserves_literal_text(self):
        marker='Titan & private <documents>'
        with zipfile.ZipFile(io.BytesIO(smoke.document_bytes(marker))) as archive:
            self.assertEqual(set(archive.namelist()),{'[Content_Types].xml','_rels/.rels','word/document.xml'})
            text=''.join(ET.fromstring(archive.read('word/document.xml')).itertext())
            self.assertEqual(text,marker)
            self.assertNotIn(b'TargetMode="External"',archive.read('_rels/.rels'))

    def test_engine_fixture_cannot_run_on_unconfirmed_real_host(self):
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'false'}):
            with self.assertRaises(Error):smoke.run_office_gateway_smoke(None,{},lambda *args: self.fail('Docker must not be invoked'))

    def test_http_diagnostics_preserve_status_and_cache_shape_without_tokens(self):
        key='a'*64
        token='private-capability-value-0123456789'
        url='http://172.18.0.2/cache/files/data/conv_'+key+'_odt/output.odt/Roundtrip.odt?md5='+token
        error=smoke.http_failure('Converted-document proxy failed',403,
                                json.dumps({'message':'Office-Dokumentpfad ist nicht freigegeben. '+url}).encode(),url)
        message=str(error)
        self.assertIn('HTTP 403',message)
        self.assertIn('Office-Dokumentpfad ist nicht freigegeben.',message)
        self.assertIn('/cache/files/data/conv_[document-key]_odt/output.odt/Roundtrip.odt',message)
        for private in (key,token,'172.18.0.2','?md5='):
            self.assertNotIn(private,message)
        self.assertEqual(str(smoke.http_failure('Save failed',502,b'<html>private</html>')),'Save failed (HTTP 502).')

    def test_local_engine_standard_port_urls_match_the_privileged_runtime(self):
        runtime={'engine_origin':'http://172.18.0.2:80'}
        path='/cache/files/document/output.docx?md5=scoped-cache-token'
        self.assertEqual(save_path('http://172.18.0.2'+path,runtime,'https://nas.local:443'),path)
        self.assertEqual(save_path('https://nas.local/office-engine'+path,runtime,'https://nas.local:443'),path)
        self.assertEqual(proxy_location('http://172.18.0.2'+path,runtime,'https://nas.local:443'),'/office-engine'+path)
        for source in ('http://172.18.0.2:8080'+path,'http://172.18.0.3'+path,'https://172.18.0.2'+path,'http://user@172.18.0.2'+path,'http://172.18.0.2:invalid'+path):
            with self.subTest(source=source),self.assertRaises(Error):save_path(source,runtime,'https://nas.local:443')


class OfficeSmokeProxyHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        root=Path(self.temporary.name)
        self.documents=root/'documents';self.documents.mkdir()
        self.document=self.documents/'Example.docx'
        self.document.write_bytes(smoke.document_bytes('Bridge document fetch'))
        self.app=Application(root/'web')
        self.app.store.create_user('writer','test-password-for-office','user','writer')
        login,_=self.app.store.login('writer','test-password-for-office')
        files=self.documents
        class Agent:
            def call(inner,operation,**arguments):
                if operation!='file' or arguments.pop('user')!='writer' or arguments.pop('share')!='docs' or arguments.get('action')!='read':
                    raise Error('Fixture file access denied.',403)
                return operate(files,**arguments)
        self.app.agent=Agent()
        revision=operate(files,'read',self.document.name,size=1)['revision']
        self.app.store.set_config('office-sessions',{'accepted':{'actor':'writer','system_user':'writer','login_digest':hashlib.sha256(login.encode()).hexdigest(),'share':'docs','path':self.document.name,'revision':revision,'writable':True,'expires':time.time()+60,'key':'example'}})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),smoke.OfficeSmokeHandler)
        self.server.app=self.app
        self.server.office_bridge_gateway='172.18.0.1'
        self.app.origin='http://127.0.0.1:'+str(self.server.server_port)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temporary.cleanup()

    def request(self,path,host):
        request=urllib.request.Request(self.app.origin+path,headers={'Host':host})
        try:
            with urllib.request.urlopen(request,timeout=5) as response:return response.status,response.read()
        except urllib.error.HTTPError as response:return response.code,response.read()

    def test_bridge_document_fetch_mirrors_caddy_origin_host_forwarding(self):
        status,data=self.request('/office/internal/file?session=accepted','172.18.0.1:5101')
        self.assertEqual(status,200,data)
        self.assertEqual(data,self.document.read_bytes())
        status,_=self.request('/office/internal/file?session=invalid','172.18.0.1:5101')
        self.assertEqual(status,403)

    def test_bridge_host_does_not_bypass_host_validation_for_public_or_foreign_routes(self):
        self.assertEqual(self.request('/api/session','172.18.0.1:5101')[0],403)
        self.assertEqual(self.request('/office/internal/file?session=accepted','172.19.0.1:5101')[0],403)


if __name__=='__main__':unittest.main()

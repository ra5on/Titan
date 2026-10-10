"""Real Caddy/HTTP/WebSocket boundary test. Set TITAN_TEST_CADDY to its binary."""
import base64
import hashlib
import http.client
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import urllib.parse

from titan.app_access import AppAccess
from titan.app_gateway import configuration
from titan.core import Store, Error
from titan.server import Handler


@unittest.skipUnless(os.environ.get('TITAN_TEST_CADDY'), 'real Caddy binary required')
class GatewayHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.store.create_user('admin', 'test-password-long-enough', 'admin', 'admin')
        self.parent, _ = self.store.login('admin', 'test-password-long-enough')
        self.access = AppAccess(self.store)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); self.port = probe.getsockname()[1]
        self.origin = 'http://127.0.0.1:' + str(self.port)
        self.available = True
        owner = self
        class Backend(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                if self.headers.get('Upgrade', '').lower() == 'websocket':
                    key = self.headers['Sec-WebSocket-Key']
                    accept = base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
                    self.send_response(101); self.send_header('Upgrade', 'websocket')
                    self.send_header('Connection', 'Upgrade'); self.send_header('Sec-WebSocket-Accept', accept)
                    self.end_headers(); self.wfile.write(b'\x81\x05hello'); self.wfile.flush()
                    return
                raw = json.dumps({'cookie': self.headers.get('Cookie', ''), 'method': self.command,
                                  'body': self.rfile.read(int(self.headers.get('Content-Length',0))).decode()}).encode()
                self.send_response(200); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
            do_POST = do_GET
        self.backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
        self.start(self.backend)
        class Agent:
            def call(self, operation, **args):
                if operation != 'app_gateway_info' or args.get('app') != 'notes' or not owner.available:
                    raise Error('Not installed', 404)
                return {'id': 'notes', 'port': owner.port, 'scheme': 'http'}
        self.api = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        self.api.app = SimpleNamespace(demo=False, origin=None, store=self.store, app_access=self.access, agent=Agent())
        self.start(self.api)
        text = configuration('notes', 'localhost', self.port)
        text = text.replace('host.docker.internal:5101', '127.0.0.1:'+str(self.api.server_port))
        text = text.replace('reverse_proxy localhost:'+str(self.port), 'reverse_proxy 127.0.0.1:'+str(self.backend.server_port))
        path = Path(self.temp.name)/'Caddyfile';path.write_text(text)
        self.log = open(Path(self.temp.name)/'caddy.log', 'w+')
        self.addCleanup(self.log.close)
        self.process = subprocess.Popen([os.environ['TITAN_TEST_CADDY'],'run','--config',str(path),'--adapter','caddyfile'],stdout=self.log,stderr=self.log)
        self.addCleanup(self.stop_proxy)
        for _ in range(100):
            try:
                self.request('/');break
            except OSError: time.sleep(.05)
        else:
            self.log.seek(0);self.fail(self.log.read())

    def start(self, server):
        server.daemon_threads=True
        threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)

    def stop_proxy(self):
        self.process.terminate()
        try:self.process.wait(5)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait()

    def request(self,path,method='GET',headers=None,body=None,port=None):
        conn=http.client.HTTPConnection('127.0.0.1',port or self.port,timeout=3)
        try:
            conn.request(method,path,body=body,headers=headers or {})
            response=conn.getresponse();return response.status,dict(response.getheaders()),response.read()
        finally:conn.close()

    def login(self):
        status,headers,_=self.request('/api/app-open?app=notes',port=self.api.server_port,headers={'Cookie':'titan_session='+self.parent})
        self.assertEqual(status,303)
        parsed=urllib.parse.urlsplit(headers['Location'])
        self.assertEqual(parsed.netloc,'127.0.0.1:'+str(self.port))
        status,headers,_=self.request(parsed.path+'?'+parsed.query)
        self.assertEqual(status,303)
        self.assertEqual(headers['Location'],'/')
        cookie=SimpleCookie(headers['Set-Cookie'])['titan_app_notes']
        self.assertTrue(cookie['httponly'])
        return 'titan_app_notes='+cookie.value

    def test_no_login_denied_then_handoff_and_cookie_isolation(self):
        self.assertEqual(self.request('/')[0],401)
        cookie=self.login()
        status,_,data=self.request('/',headers={'Cookie':cookie+'; titan_session='+self.parent+'; titan_app_other=other; own=kept'})
        self.assertEqual(status,200)
        self.assertEqual(json.loads(data)['cookie'],'own=kept')
        status,_,data=self.request('/',headers={'Cookie':cookie+'; titan_session='+self.parent})
        self.assertEqual(status,200);self.assertEqual(json.loads(data)['cookie'],'')
        self.store.logout(self.parent)
        self.assertEqual(self.request('/',headers={'Cookie':cookie})[0],401)

    def test_post_body_survives_auth_and_foreign_origin_is_rejected(self):
        cookie=self.login()
        self.assertEqual(self.request('/',method='POST',headers={'Cookie':cookie},body='hello')[0],403)
        self.assertEqual(self.request('/',method='POST',headers={'Cookie':cookie,'Origin':'https://foreign.test'},body='hello')[0],403)
        status,_,data=self.request('/',method='POST',headers={'Cookie':cookie,'Origin':self.origin},body='hello')
        self.assertEqual(status,200);self.assertEqual(json.loads(data)['body'],'hello')

    def test_websocket_upgrade_and_data_require_app_session(self):
        headers={'Connection':'Upgrade','Upgrade':'websocket','Sec-WebSocket-Version':'13',
                 'Sec-WebSocket-Key':base64.b64encode(b'0123456789abcdef').decode(),'Origin':self.origin}
        self.assertEqual(self.request('/socket',headers=headers)[0],401)
        headers['Cookie']=self.login()
        with socket.create_connection(('127.0.0.1',self.port),timeout=3) as stream:
            stream.sendall(('GET /socket HTTP/1.1\r\nHost: 127.0.0.1:'+str(self.port)+'\r\n'+''.join(k+': '+v+'\r\n' for k,v in headers.items())+'\r\n').encode())
            raw=b''
            while b'hello' not in raw:
                chunk=stream.recv(4096)
                if not chunk:break
                raw+=chunk
            self.assertIn(b'101 Switching Protocols',raw);self.assertIn(b'\x81\x05hello',raw)

    def test_uninstall_revokes_a_live_grant(self):
        cookie=self.login();self.available=False
        self.assertEqual(self.request('/',headers={'Cookie':cookie})[0],404)


if __name__=='__main__':unittest.main()

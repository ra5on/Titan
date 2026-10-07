"""Disposable real-Caddy test, without system services or production ports."""
from http.client import HTTPConnection, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest

from titan.web_access import caddy_config, initial_config, origin

CADDY = os.environ.get('TITAN_TEST_CADDY') or shutil.which('caddy')


@unittest.skipUnless(CADDY, 'Caddy binary required for disposable proxy integration')
class WebAccessProxyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.environment = {**os.environ,'XDG_DATA_HOME':str(self.root/'data'),'XDG_CONFIG_HOME':str(self.root/'config')}

    def validate(self, config):
        path = self.root/'Caddyfile'
        path.write_text(caddy_config(config))
        result = subprocess.run([CADDY,'validate','--config',str(path),'--adapter','caddyfile'],
                                capture_output=True,text=True,env=self.environment,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_generated_configs_are_valid_for_default_ipv6_and_protocol_transitions(self):
        for host in ('192.168.10.18','nas.example.test','fd00::18'):
            with self.subTest(host=host):
                config = initial_config(host)
                self.validate(config)
                previous = initial_config(host,'https://nas.example.test:5000')
                config.update(settings={'mode':'https','http_port':8080,'https_port':8443},pending={'previous':previous,'deadline':12345})
                self.validate(config)
                config['settings']['mode'] = 'http'
                self.validate(config)
                config['pending']['previous'] = initial_config(host,'http://nas.example.test:8080')
                config['settings']['mode'] = 'https'
                self.validate(config)

    def test_https_serves_backend_and_http_redirect_keeps_path_query_and_custom_port(self):
        class Backend(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'Titan disposable backend'
                self.send_response(200)
                self.send_header('Content-Length',str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self,*args):
                pass
        backend = ThreadingHTTPServer(('127.0.0.1',0),Backend)
        thread = threading.Thread(target=backend.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        thread.start()
        self.addCleanup(lambda:(backend.shutdown(),backend.server_close(),thread.join()))
        sockets = [socket.socket() for _ in range(3)]
        try:
            for sock in sockets: sock.bind(('127.0.0.1',0))
            http_port,https_port,office_port = [sock.getsockname()[1] for sock in sockets]
        finally:
            for sock in sockets: sock.close()
        config = initial_config('127.0.0.1')
        config['settings'].update(http_port=http_port,https_port=https_port)
        text = caddy_config(config).replace('127.0.0.1:5001','127.0.0.1:'+str(backend.server_port)).replace('http://:5101','http://127.0.0.1:'+str(office_port))
        path = self.root/'Caddyfile'
        path.write_text(text)
        log = (self.root/'proxy.log').open('w+')
        self.addCleanup(log.close)
        process = subprocess.Popen([CADDY,'run','--config',str(path),'--adapter','caddyfile'],stdout=log,stderr=log,env=self.environment)
        def close():
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        self.addCleanup(close)
        # A throwaway, locally generated certificate is used only by this test.
        context = ssl._create_unverified_context()
        for _ in range(100):
            client = HTTPSConnection('127.0.0.1',https_port,context=context,timeout=.3)
            try:
                client.request('GET','/api/session')
                response = client.getresponse()
                self.assertEqual(response.status,200)
                self.assertEqual(response.read(),b'Titan disposable backend')
                break
            except (OSError,ssl.SSLError):
                if process.poll() is not None:
                    log.seek(0)
                    self.fail(log.read())
                time.sleep(.05)
            finally:
                client.close()
        else:
            log.seek(0)
            self.fail('Proxy readiness timed out: '+log.read())
        client = HTTPConnection('127.0.0.1',http_port,timeout=3)
        try:
            client.request('GET','/nested/document?view=edit')
            response = client.getresponse()
            self.assertEqual(response.status,308)
            self.assertEqual(response.getheader('Location'),origin(config['host'],config['settings'])+'/nested/document?view=edit')
            response.read()
        finally:
            client.close()

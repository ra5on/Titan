#!/usr/bin/env python3
"""Disposable Linux CI: real guacd + Chromium + Titan login + browser input.

Run only on a disposable runner. No tunnels or real user accounts are involved.
"""
import http.server
import json
import logging
import os
import socket
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from titan.core import Error
from titan.desktop_runtime import DesktopRuntimeMixin
from titan.server import Application, Handler, WebServer
from titan.remote_access import tunnel_caddy, validate_remote

if os.environ.get('TITAN_DISPOSABLE_CI') != '1':
    raise SystemExit('A disposable CI environment is required')

logging.basicConfig(level=logging.INFO)

proof = threading.Event()


class Fixture(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        data = b'<!doctype html><title>Titan Guacamole proof</title><body style="background:#123456;color:white"><h1>Titan Guacamole proof</h1><form method="POST"><input name="proof" autofocus><button>Save</button></form></body>'
        self.send_response(200); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        if self.rfile.read(int(self.headers.get('Content-Length','0'))) == b'proof=TitanGuacamole':
            proof.set()
        self.do_GET()
    def log_message(self, *args):
        pass


class Runtime(DesktopRuntimeMixin):
    def __init__(self, path, port):
        self.directory, self.state, self.port = path, {}, port
    def _plugin_state(self): return self.state
    def _desktop_wait(self, port, vnc=False):
        try:
            return super()._desktop_wait(port, vnc=vnc)
        except Exception:
            names = subprocess.check_output(['docker','ps','-a','--filter','label=org.titan.desktop=1','--format','{{.Names}}'], text=True).splitlines()
            for name in names:
                subprocess.run(['docker','logs',name], check=False)
            raise
    def _desktop_command(self, args, **kwargs):
        try:
            return super()._desktop_command(args, **kwargs)
        except Exception as error:
            print('Disposable runtime command failed:', args[:4], str(error), flush=True)
            subprocess.run(['docker', 'logs', 'titan-guacd'], check=False)
            raise
    def save(self, name, state): self.state = state
    def _desktop_app_url(self, app): return f'http://host.docker.internal:{self.port}/'
    def managed_app(self, app): return {'id':app}
    def _app_container(self, app, record): return {'NetworkSettings':{'Networks':{}}}
    def dispatch(self, operation, **args):
        if operation == 'web_health': return {'agent_api':1, 'state_schema':1}
        return getattr(self, 'op_' + operation)(**args)


with tempfile.TemporaryDirectory(prefix='titan-guac-') as temporary:
    folder = Path(temporary)
    runtime = None
    server = None
    app = None
    proxy = None
    try:
        fixture = http.server.ThreadingHTTPServer(('0.0.0.0', 0), Fixture)
        threading.Thread(target=fixture.serve_forever, daemon=True).start()
        runtime = Runtime(folder, fixture.server_port)
        runtime._desktop_plugin('install', {})
        app = Application(folder / 'web')
        app.agent = SimpleNamespace(call=runtime.dispatch)
        app.store.create_user('tester', 'Disposable-Guac-proof-123!', 'admin', 'tester')
        server = WebServer(('127.0.0.1', 0), Handler); server.app = app
        threading.Thread(target=server.serve_forever, daemon=True).start()
        env = {**os.environ, 'TITAN_GUAC_URL':f'http://127.0.0.1:{server.server_port}'}
        subprocess.run(['node', 'scripts/smoke-guacamole-browser.cjs'], cwd=ROOT, env=env, check=True, timeout=120)
        if not proof.wait(5):
            raise RuntimeError('Keyboard input did not reach the real remote browser')
        print('PASS: real Chromium image, VNC, guacd, Titan websocket, input, reconnect and logout')
        # Emulate only Cloudflare's TLS edge. Everything behind it uses Titan's
        # actual generated, source/host restricted tunnel route, including WSS.
        public = 'https://nas.example.test'
        with Path('/etc/hosts').open('a') as hosts:
            hosts.write('\n127.0.0.1 nas.example.test\n')
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
            '-subj','/CN=nas.example.test','-addext','subjectAltName=DNS:nas.example.test',
            '-keyout',str(folder/'key.pem'),'-out',str(folder/'cert.pem')], check=True, capture_output=True)
        remote = {**validate_remote(None), 'enabled':True, 'public_origin':public,
                  'connector':'plugin-cloudflare', 'service_url':'http://127.0.0.1:5102'}
        route = tunnel_caddy({'remote':remote}).replace('127.0.0.1:5001', '127.0.0.1:' + str(server.server_port))
        source = folder/'Caddyfile'
        source.write_text('{\n admin off\n auto_https off\n}\n' + route +
            f'{public} {{\n bind 127.0.0.1\n tls {folder}/cert.pem {folder}/key.pem\n reverse_proxy 127.0.0.1:5102\n}}\n')
        proxy = subprocess.Popen(['caddy','run','--config',str(source),'--adapter','caddyfile'],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(100):
            if proxy.poll() is not None:
                raise RuntimeError(proxy.stderr.read().decode())
            try:
                with socket.create_connection(('127.0.0.1',443),timeout=.1): break
            except OSError: time.sleep(.05)
        app.origin = public
        proof.clear()
        subprocess.run(['node','scripts/smoke-guacamole-browser.cjs'], cwd=ROOT,
            env={**env,'TITAN_GUAC_URL':public, 'TITAN_GUAC_MODE':'tunnel'}, check=True, timeout=120)
        if not proof.wait(5):
            raise RuntimeError('Input did not reach the browser through the generated tunnel route')
        print('PASS: HTTPS/WSS, secure login, file transfer and logout through the generated Cloudflare origin route')
    except Exception:
        names = subprocess.check_output(['docker','ps','-a','--filter','label=org.titan.desktop=1','--format','{{.Names}}'], text=True).splitlines()
        for name in names:
            subprocess.run(['docker','logs',name], check=False)
        raise
    finally:
        if proxy:
            proxy.terminate(); proxy.wait(timeout=5)
        if app:
            app.stop.set(); app.close_all_desktops(); app.close_all_terminals()
        if server: server.shutdown(); server.server_close()
        if runtime:
            try: runtime._desktop_plugin('remove', {})
            except Exception: pass

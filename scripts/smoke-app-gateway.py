#!/usr/bin/env python3
"""Actual protected catalog package + Caddy sidecar, on a disposable CI runner."""
import argparse
import http.client
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import urllib.parse

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from titan.app_access import AppAccess
from titan.catalog import APPS, compose
from titan.core import Store, Error
from titan.server import Handler
from titan.store_recipes import recipes
from titan.umbrel_catalog import fetch_inventory, compile_inventory, URL


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--revision',required=True)
    parser.add_argument('--confirm-disposable-runner',action='store_true')
    args=parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS')!='true' or not args.confirm_disposable_runner:
        parser.error('Only an explicitly disposable GitHub runner is permitted.')
    document,_=compile_inventory(fetch_inventory(args.revision))
    selected=next(item for item in document['apps'] if item['id']=='bentopdf')
    _,parsed=recipes({**document,'apps':[selected]},URL)
    app,recipe=next(iter(parsed.items()));APPS[app]=recipe
    if recipe.get('app_gateway') is not True:raise Error('Authentication must be retained.')
    with tempfile.TemporaryDirectory(prefix='titan-gateway-smoke-') as directory:
        root=Path(directory);path=root/'compose.json'
        definition=compose(app,str(root),1000,1000,18080,str(root/'data'),{},config_path=str(root/'private'))
        path.write_text(json.dumps(definition));path.chmod(0o600)
        def docker(*arguments):
            return subprocess.run(['docker','compose','-p','titan-'+app,'-f',str(path),*arguments],capture_output=True,text=True,check=True,timeout=600).stdout
        store=Store(root/'web');password='Test-'+os.urandom(24).hex()
        store.create_user('admin',password,'admin','admin')
        parent,_=store.login('admin',password)
        class Agent:
            def call(self,operation,**arguments):
                if operation!='app_gateway_info' or arguments.get('app')!=app:raise Error('Unknown app',404)
                return {'id':app,'port':18080,'scheme':'http'}
        server=ThreadingHTTPServer(('0.0.0.0',5101),Handler);server.daemon_threads=True
        server.app=SimpleNamespace(demo=False,origin=None,store=store,app_access=AppAccess(store),agent=Agent())
        threading.Thread(target=server.serve_forever,daemon=True).start()
        def request(path,port=18080,cookie=''):
            conn=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
            try:
                conn.request('GET',path,headers={'Cookie':cookie})
                response=conn.getresponse();return response.status,dict(response.getheaders()),response.read(1024*1024)
            finally:conn.close()
        try:
            docker('config','--quiet');docker('up','-d')
            for _ in range(120):
                try:
                    if request('/')[0]==401:break
                except OSError:pass
                time.sleep(1)
            else:raise Error('Gateway did not deny unauthenticated access.')
            status,headers,_=request('/api/app-open?app='+app,5101,'titan_session='+parent)
            if status!=303:raise Error('Titan app handoff failed.')
            location=urllib.parse.urlsplit(headers['Location'])
            status,headers,_=request(location.path+'?'+location.query)
            if status!=303:raise Error('Gateway did not redeem the single-use ticket.')
            name='titan_app_'+app;cookie=name+'='+SimpleCookie(headers['Set-Cookie'])[name].value
            for _ in range(90):
                status,_,body=request('/',cookie=cookie)
                if status==200 and b'<html' in body.lower():break
                time.sleep(1)
            else:raise Error('Actual BentoPDF web interface is not reachable after authentication.')
            inspections=json.loads(subprocess.check_output(['docker','inspect','titan-'+app+'-backend'],text=True))
            if inspections[0]['HostConfig'].get('PortBindings'):
                raise Error('Package backend bypasses the authentication gateway.')
            from titan.app_management import AppMixin
            gateway=json.loads(subprocess.check_output(['docker','inspect','titan-'+app],text=True))[0]
            if not AppMixin._app_capabilities_match(app,app,definition['services'][app],gateway['HostConfig']):
                raise Error('Installed gateway fails the production container protection check.')
            store.logout(parent)
            if request('/',cookie=cookie)[0]!=401:raise Error('Logout did not revoke app access.')
            print(json.dumps({'ok':True,'app':'bentopdf','revision':args.revision,'scope':'actual-catalog-app-gateway',
                'checks':['compose-valid','unauthenticated-denied','single-use-handoff','actual-html','backend-not-published','production-capability-check','logout-revoked']}))
        except Exception:
            print(docker('ps','--all'),file=sys.stderr)
            print(docker('logs','--no-color','--tail','60',app),file=sys.stderr)
            raise
        finally:
            server.shutdown();server.server_close()
            try:docker('down','--remove-orphans')
            except subprocess.CalledProcessError as exc:print(exc.stderr[-2000:],file=sys.stderr)

if __name__=='__main__':main()

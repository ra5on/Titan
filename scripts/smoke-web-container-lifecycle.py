#!/usr/bin/env python3
"""Disposable CI: real Docker candidate failure and recovery through our controller.

Only systemctl is adapted to Docker lifecycle calls because the hosted runner
is not a Titan NAS. Readiness checks and both web processes are real.
"""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Disposable Actions runner required')
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('lifecycle',root/'packaging/container/web-container.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
import sys
sys.path.insert(0,str(root))
from titan import __version__
__version__ = os.environ.get("TITAN_WEB_VERSION", __version__)
if subprocess.run(['docker','inspect','titan-web'],capture_output=True).returncode==0:
    raise SystemExit('Refusing to replace an existing titan-web container')
with tempfile.TemporaryDirectory(prefix='titan-web-lifecycle-') as folder:
    folder=Path(folder);data=folder/'data';data.mkdir()
    definition=f'FROM titan-web:{__version__}\nLABEL org.opencontainers.image.version="0.0.0"\nHEALTHCHECK --interval=1s --timeout=1s --start-period=0s --retries=1 CMD exit 1\n'
    subprocess.run(['docker','build','--tag','titan-web-rejected','-'],input=definition,text=True,check=True)
    previous=m.validate_image('titan-web:'+__version__,__version__)
    rejected=m.validate_image('titan-web-rejected','0.0.0')
    actual_command=m.command;actual_healthy=m.healthy
    def command(*args,**kwargs):
        if args[:2]==('systemctl','stop'):
            subprocess.run(['docker','rm','-f','titan-web'],capture_output=True,check=True)
            return ''
        if args[:2]==('systemctl','start'):
            chosen=json.loads(m.STATE.read_text())['current']
            return actual_command('docker','run','-d','--name','titan-web','--user',f'{os.getuid()}:{os.getgid()}',
                '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--tmpfs','/tmp',
                '--mount',f'type=bind,src={data},dst=/var/lib/titan',chosen['image'],'--demo')
        return actual_command(*args,**kwargs)
    try:
        with patch.object(m,'STATE',folder/'selection.json'),patch.object(m,'command',side_effect=command),patch.object(m,'healthy',side_effect=lambda version:actual_healthy(version,seconds=35)):
            m.save({'current':previous})
            command('systemctl','start','titan-web.service');actual_healthy(__version__,seconds=45)
            try:m.switch(rejected)
            except RuntimeError as error:
                if 'health check failed' not in str(error):raise
            else:raise AssertionError('Unhealthy candidate was accepted')
            assert json.loads(m.STATE.read_text())['current']==previous
            actual_healthy(__version__,seconds=10)
            print('Actual Docker web candidate rejected; previous image and database remain usable.')
    finally:
        subprocess.run(['docker','logs','titan-web'])
        subprocess.run(['docker','rm','-f','titan-web'],capture_output=True)

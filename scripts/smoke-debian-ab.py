#!/usr/bin/env python3
"""Full A/B lifecycle in an explicitly disposable QEMU overlay, never the IMG.

The candidate is served locally only to this QEMU guest. The GitHub transport
is replaced inside a test-only Python process; RAUC, signatures, disk writes,
health checks, NAS state and rollback/reboot APIs are real production code.
No fixtures, private keys or test accounts are written into the released IMG.
"""
import argparse
import base64
import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('runtime_smoke', ROOT/'scripts/smoke-runtime.py')
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)


def command(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


class Agent:
    def __init__(self, path):self.path=str(path)
    def call(self, method, arguments=None):
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(15);sock.connect(self.path)
            sock.sendall(json.dumps({'execute':method,'arguments':arguments or {}}).encode()+b'\n')
            with sock.makefile('rb') as stream:
                for _ in range(20):
                    line=stream.readline(1024*1024)
                    if not line:break
                    value=json.loads(line.lstrip(b'\xff'))
                    if 'error' in value:raise RuntimeError('Guest agent rejected '+method)
                    if 'return' in value:return value['return']
        raise RuntimeError('No bounded guest agent response')
    def execute(self, args, timeout=180):
        value=self.call('guest-exec',{'path':args[0],'arg':args[1:],'capture-output':True})
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            status=self.call('guest-exec-status',{'pid':value['pid']})
            if status.get('exited'):
                out=base64.b64decode(status.get('out-data','')).decode(errors='replace')
                err=base64.b64decode(status.get('err-data','')).decode(errors='replace')
                if status.get('exitcode')!=0:
                    # Commands never contain credentials; diagnostics stay bounded.
                    raise RuntimeError('Guest command failed: '+err[-4000:])
                return out
            time.sleep(1)
        raise RuntimeError('Guest command timed out')
    def python(self, code, timeout=180):
        return self.execute(['/usr/bin/python3','-c',code], timeout)
    def ready(self, slot, version, previous_boot=None):
        deadline=time.monotonic()+360
        while time.monotonic()<deadline:
            try:
                boot=self.execute(['/bin/cat','/proc/sys/kernel/random/boot_id'],timeout=10).strip()
                if previous_boot==boot:
                    time.sleep(2);continue
                status=json.loads(self.python("import sys,json;sys.path.insert(0,'/usr/lib/titan');from titan.debian_updates import system_status;print(json.dumps(system_status()))"))
                if status['health_confirmed'] and status['booted']['slot']==slot and status['current']==version:
                    return boot,status
            except (OSError,ValueError,RuntimeError):pass
            time.sleep(3)
        raise RuntimeError('Expected healthy slot/version did not start: '+slot+' '+version)


def qmp(path, method, arguments=None):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(10);sock.connect(str(path))
        with sock.makefile('rb') as stream:
            assert 'QMP' in json.loads(stream.readline())
            for request in ({'execute':'qmp_capabilities'}, {'execute':method,'arguments':arguments or {}}):
                sock.sendall(json.dumps(request).encode()+b'\n')
                for _ in range(30):
                    value=json.loads(stream.readline())
                    if 'error' in value:raise RuntimeError('QMP command failed')
                    if 'return' in value:break
                else:raise RuntimeError('QMP response missing')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('image',type=Path);parser.add_argument('bundle',type=Path)
    parser.add_argument('--confirm-disposable-guest',action='store_true');args=parser.parse_args()
    assert os.environ.get('GITHUB_ACTIONS')=='true' and args.confirm_disposable_guest
    image=args.image.resolve();bundle=args.bundle.resolve()
    assert image.is_file() and bundle.is_file()
    original=sha(image);directory=image.parent
    identity=json.loads((directory/'ab-input/image-info.json').read_text())
    report={'format':'titan-debian-ab-smoke-v1','ok':False,'checks':[]}
    def passed(name):report['checks'].append(name);print(name+': passed',flush=True)
    proc=None;server=None
    with tempfile.TemporaryDirectory(prefix='titan-ab-smoke-') as temporary:
        work=Path(temporary);agent=Agent(work/'qga.sock')
        try:
            command(['qemu-img','create','-q','-f','qcow2','-F','raw','-b',str(image),str(work/'test.qcow2')])
            baseline='0.4.5-alpha.1'
            command(['python3','scripts/system-release-metadata.py','identity','--version',baseline,'--accounts',str(directory/'ab-input/system-accounts.json'),'--output',str(work/'image-info.json')])
            # Signed older system identity only in the private overlay; complete
            # root filesystem replacement then proves A -> B -> A transitions.
            command(['guestfish','-a',str(work/'test.qcow2'),'-m','/dev/sda3','upload',str(work/'image-info.json'),'/usr/share/titan/image-info.json'])
            command(['guestfish','-a',str(work/'test.qcow2'),'-m','/dev/sda3','upload',str(work/'image-info.json.sig'),'/usr/share/titan/image-info.json.sig'])
            (work/'factory-probe').write_text('baseline factory default\n')
            command(['guestfish','-a',str(work/'test.qcow2'),'-m','/dev/sda3','upload',str(work/'factory-probe'),'/etc/titan-ci-factory'])
            shutil.copyfile('/usr/share/OVMF/OVMF_VARS_4M.fd',work/'vars.fd')
            accel='kvm' if os.access('/dev/kvm',os.R_OK|os.W_OK) else 'tcg'
            with (work/'console.log').open('wb') as console:
                proc=subprocess.Popen(['qemu-system-x86_64','-accel',accel,'-machine','q35','-cpu','host' if accel=='kvm' else 'max',
                    '-m','3072','-smp','2','-display','none','-monitor','none','-serial','stdio',
                    '-qmp','unix:'+str(work/'qmp.sock')+',server=on,wait=off',
                    '-drive','if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd',
                    '-drive','if=pflash,format=raw,file='+str(work/'vars.fd'),
                    '-drive','id=titan-system,if=virtio,format=qcow2,file='+str(work/'test.qcow2'),
                    '-device','virtio-serial-pci','-chardev','socket,path='+str(work/'qga.sock')+',server=on,wait=off,id=qga',
                    '-device','virtserialport,chardev=qga,name=org.qemu.guest_agent.0',
                    '-netdev','user,id=net0,hostfwd=tcp:127.0.0.1:15000-:5000,hostfwd=tcp:127.0.0.1:15445-:445',
                    '-device','virtio-net-pci,netdev=net0'],stdout=console,stderr=console)
            boot,status=agent.ready('A',baseline);passed('baseline_boot_health')
            client=runtime.GuestClient(work/'qmp.sock');smoke=runtime.RuntimeSmoke(client);smoke.setup()
            client.action('share_create',{'name':'ab-persist','readers':[smoke.username],'writers':[smoke.username]})
            share=next(item for item in client.request('/api/shares') if item['name']=='ab-persist')
            assert share['path']=='/var/srv/titan/shares/ab-persist'
            agent.python("from pathlib import Path;p=Path('/var/srv/titan/shares/ab-persist/rollback-sentinel');p.write_text('preserved across A/B update and rollback\\n')")
            agent.python("from pathlib import Path;assert Path('/etc/titan-ci-factory').read_text()=='baseline factory default\\n';Path('/etc/titan-ci-local').write_text('persistent local change\\n')")
            snapshot_code="""import hashlib,json,subprocess
from pathlib import Path
items={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in ['/etc/passwd','/etc/shadow','/etc/group','/etc/samba/titan-shares.conf','/etc/titan-ci-local','/var/srv/titan/shares/ab-persist/rollback-sentinel']}
items['acl']=subprocess.check_output(['getfacl','-p','/var/srv/titan/shares/ab-persist'],text=True)
print(json.dumps(items,sort_keys=True))"""
            snapshot=agent.python(snapshot_code)
            # Grow this named private overlay while running, then exercise the
            # actual installed grow helper and check newly usable data capacity.
            before=int(agent.execute(['/usr/bin/stat','-f','-c','%b','/var/lib/titan-system']).strip())
            qmp(work/'qmp.sock','block_resize',{'device':'titan-system','size':64*1024**3})
            agent.python("""import subprocess,time
from pathlib import Path
for _ in range(30):
    if int(Path('/sys/class/block/vda/size').read_text()) >= 64*1024**3//512:break
    time.sleep(1)
else:raise RuntimeError('VirtIO disk size did not refresh')
""")
            agent.execute(['/bin/bash','/usr/share/titan/debian-grow-data.sh'])
            after=int(agent.execute(['/usr/bin/stat','-f','-c','%b','/var/lib/titan-system']).strip())
            assert after>before+3*1024**3//4096
            passed('proxmox_style_data_growth')
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path!='/candidate.raucb':self.send_error(404);return
                    self.send_response(200);self.send_header('Content-Length',str(bundle.stat().st_size));self.end_headers()
                    with bundle.open('rb') as source:shutil.copyfileobj(source,self.wfile)
                def log_message(self,*unused):pass
            server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            agent.execute(['/usr/bin/curl','--fail','--silent','--show-error','--max-time','600',
                           'http://10.0.2.2:'+str(server.server_port)+'/candidate.raucb','-o','/var/lib/titan-system/candidate.raucb'],timeout=660)
            assert agent.execute(['/usr/bin/sha256sum','/var/lib/titan-system/candidate.raucb']).split()[0]==sha(bundle)
            manifest={**identity,'bundle':{'name':bundle.name,'size':bundle.stat().st_size,'sha256':sha(bundle)},
                      'rootfs_sha256':sha(directory/'bundle/rootfs.ext4'),
                      **{key:'passed' for key in ('boot_test','runtime_test','update_test','rollback_test')}}
            # Local unpublished test offer. This injects transport only; all
            # production install checks and RAUC signature/verity checks run.
            install_code="""import sys,json,shutil
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,'/usr/lib/titan')
from titan import debian_updates as u
manifest=json.loads(MANIFEST)
assets={manifest['bundle']['name']:'https://api.github.com/test-bundle','manifest.json':'https://api.github.com/test-manifest','manifest.json.sig':'https://api.github.com/test-signature'}
offer={'available':True,'latest':manifest['version'],'assets':assets,'url':'https://github.com/ra5on/Titan/releases/test'}
with patch.object(u,'check',return_value=offer),patch('titan.updates.verified_release',return_value=(manifest,assets)),patch.object(u,'download',side_effect=lambda url,path,bundle,token:shutil.copyfile('/var/lib/titan-system/candidate.raucb',path)):
    result=u.install('ra5on/Titan','alpha',manifest['version'],Path('/var/lib/titan/titan.sqlite3'))
assert result['reboot_required'] is True and result['automatic_reboot'] is False
print('prepared')
""".replace('MANIFEST',repr(json.dumps(manifest)))
            agent.python(install_code,timeout=2100)
            staged=client.request('/api/updates/system');assert staged['next_boot']['slot']=='B' and staged['booted']['slot']=='A'
            assert agent.execute(['/bin/cat','/proc/sys/kernel/random/boot_id']).strip()==boot
            passed('signed_update_staged_without_reboot')
            client.action('system_reboot',{'expected_digest':identity['release_id'],'confirmation':'NEUSTART'})
            boot,status=agent.ready('B',identity['version'],boot)
            assert agent.python(snapshot_code)==snapshot
            assert status['rollback_available'] and status['rollback_options'][0]['slot']=='A'
            agent.python("from pathlib import Path;assert not Path('/etc/titan-ci-factory').exists()")
            passed('update_boot_and_preserved_accounts_acls_data')
            # Existing browser session and API are used to select the real old slot.
            client.request('/api/session')
            old=status['rollback_options'][0]
            client.action('update_rollback',{'expected_digest':old['digest'],'confirmation':'ROLLBACK'})
            client.action('system_reboot',{'expected_digest':old['digest'],'confirmation':'NEUSTART'})
            boot,status=agent.ready('A',baseline,boot)
            assert agent.python(snapshot_code)==snapshot
            agent.python("from pathlib import Path;assert Path('/etc/titan-ci-factory').read_text()=='baseline factory default\\n'")
            passed('factory_defaults_follow_selected_slot')
            passed('manual_rollback_and_preserved_accounts_acls_data')
            # Deliberately make the *inactive test slot* unbootable. GRUB must
            # consume its one attempt and choose healthy A after the test reset.
            agent.python("""import subprocess
from pathlib import Path
subprocess.run(['mount','/dev/disk/by-partlabel/TITAN-B','/mnt'],check=True)
try:
    p=Path('/mnt/vmlinuz');assert p.is_symlink();p.unlink()
finally:subprocess.run(['umount','/mnt'],check=True)
""")
            target=next(x for x in status['rollback_options'] if x['slot']=='B')
            client.action('update_rollback',{'expected_digest':target['digest'],'confirmation':'ROLLBACK'})
            client.action('system_reboot',{'expected_digest':target['digest'],'confirmation':'NEUSTART'})
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                try:agent.call('guest-ping')
                except (OSError,ValueError,RuntimeError):break
                time.sleep(3)
            else:raise RuntimeError('Scheduled fallback test reboot never began')
            # QGA has stopped for shutdown. Allow the one GRUB attempt to fail
            # before the explicit reset; no hardware watchdog is assumed.
            time.sleep(30)
            qmp(work/'qmp.sock','system_reset')
            boot,status=agent.ready('A',baseline,boot)
            assert status['last_failure']['slot']=='B' and not status['rollback_options']
            assert agent.python(snapshot_code)==snapshot
            passed('failed_candidate_fallback_after_reset')
            report['ok']=True
        finally:
            if proc is not None:
                proc.terminate()
                try:proc.wait(timeout=15)
                except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=10)
            if server is not None:server.shutdown();server.server_close()
            if (work/'console.log').exists():
                shutil.copyfile(work/'console.log',directory/'ab-console.log')
                if not report['ok']:
                    print('TITAN_AB_CONSOLE_TAIL',flush=True)
                    print((work/'console.log').read_text(errors='replace')[-20000:],flush=True)
            report['raw_image_unchanged']=sha(image)==original
            report['ok']=report['ok'] and report['raw_image_unchanged']
            (directory/'ab-test.json').write_text(json.dumps(report,indent=2)+'\n')
    assert report['ok']


if __name__=='__main__':main()

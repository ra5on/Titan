#!/usr/bin/env python3
"""Cold replacement recovery of an installed NAS, apps and a real Linux VM.

Only new regular QCOW2 files on an explicitly disposable runner are attached.
Original disks are disconnected before replacement restore and subsequent boot.
The source image and rescue medium remain read-only throughout this test.
"""
import argparse
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
def module(name, filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/filename)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
ab=module('recovery_ab','smoke-debian-ab.py')
qcow=module('recovery_qcow','smoke-qcow2-guest.py')


@contextlib.contextmanager
def boot(work, output, name, disks, *, rescue=None, scsi=False):
    for socket in ('qga.sock','qmp.sock'): (work/socket).unlink(missing_ok=True)
    shutil.copyfile('/usr/share/OVMF/OVMF_VARS_4M.fd',work/'vars.fd')
    accel='kvm' if os.access('/dev/kvm',os.R_OK|os.W_OK) else 'tcg'
    command=['qemu-system-x86_64','-machine','q35','-accel',accel,'-cpu','host' if accel=='kvm' else 'max',
        '-m','2048' if rescue else '8192','-smp','2','-display','none',
        '-qmp','unix:'+str(work/'qmp.sock')+',server=on,wait=off',
        '-serial','file:'+str(output/('nas-recovery-'+name+'.log')),
        '-drive','if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd',
        '-drive','if=pflash,format=raw,file='+str(work/'vars.fd'),
        '-device','virtio-serial-pci','-chardev','socket,path='+str(work/'qga.sock')+',server=on,wait=off,id=qga',
        '-device','virtserialport,chardev=qga,name=org.qemu.guest_agent.0']
    if scsi: command+=['-device','virtio-scsi-pci,id=scsi']
    for index,disk in enumerate(disks):
        command+=['-drive',f'if=none,format=qcow2,id=d{index},file={work/(disk+".qcow2")},discard=unmap,detect-zeroes=unmap',
            '-device',('scsi-hd,bus=scsi.0' if scsi else 'virtio-blk-pci')+f',drive=d{index},serial=TITAN_{disk}']
    if rescue:
        command+=['-nic','none','-cdrom',str(rescue),'-boot','d']
    else:
        command+=['-netdev','user,id=net0,hostfwd=tcp:127.0.0.1:15000-:443,hostfwd=tcp:127.0.0.1:15001-:5000,hostfwd=tcp:127.0.0.1:15445-:445',
            '-device',('e1000' if scsi else 'virtio-net-pci')+',netdev=net0']
    with subprocess.Popen(command) as process:
        try:
            agent=ab.Agent(work/'qga.sock');deadline=time.monotonic()+360
            while time.monotonic()<deadline:
                if process.poll() is not None: raise RuntimeError('Disposable NAS VM exited during boot.')
                try: agent.execute(['/bin/true'],timeout=10);break
                except (OSError,RuntimeError):time.sleep(2)
            else:raise RuntimeError('Disposable NAS guest agent did not become available.')
            yield agent,process
        finally:
            if process.poll() is None:
                try:ab.qmp(work/'qmp.sock','screendump',{'filename':str(output/('nas-recovery-'+name+'.ppm'))})
                except (OSError,RuntimeError):pass
                process.terminate()
                try:process.wait(timeout=15)
                except subprocess.TimeoutExpired:process.kill();process.wait()


PRELUDE="""import importlib.machinery,importlib.util,json,os,subprocess
from pathlib import Path
loader=importlib.machinery.SourceFileLoader('recovery','/usr/local/bin/titan-recovery')
spec=importlib.util.spec_from_loader(loader.name,loader)
dr=importlib.util.module_from_spec(spec);loader.exec_module(dr)
def cmd(*args):return subprocess.check_output(args,text=True)
def disk(name):return next(d for d in dr.block_inventory() if d['identity']=='serial:TITAN_'+name)
"""


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image',type=Path);parser.add_argument('rescue',type=Path);parser.add_argument('guest',type=Path)
    parser.add_argument('--confirm-disposable-guest',action='store_true');args=parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS')!='true' or not args.confirm_disposable_guest:
        parser.error('Requires an explicitly disposable GitHub runner.')
    image,rescue,guest=(p.resolve(strict=True) for p in (args.image,args.rescue,args.guest))
    if not all(p.is_file() for p in (image,rescue,guest)):parser.error('Only regular input files are accepted.')
    output=image.parent;identity=json.loads((output/'ab-input/image-info.json').read_text())
    report={'schema':1,'scope':'installed-nas-replacement-recovery','ok':False,'source_commit':os.environ.get('GITHUB_SHA'),
        'image_sha256':ab.sha(image),'recovery_iso_sha256':ab.sha(rescue),'checks':[]}
    def passed(name):report['checks'].append(name);print(name+': passed',flush=True)
    try:
        with tempfile.TemporaryDirectory(prefix='titan-nas-recovery-') as tmp:
            work=Path(tmp)
            ab.command(['qemu-img','create','-q','-f','qcow2','-F','raw','-b',str(image),str(work/'source.qcow2')])
            for name,size in (('backup','24G'),('target','64G')):
                ab.command(['qemu-img','create','-q','-f','qcow2',str(work/(name+'.qcow2')),size])
            with boot(work,output,'source',['source']) as (agent,process):
                agent.ready('A',identity['version'])
                client=ab.runtime.GuestClient(work/'qmp.sock');smoke=ab.runtime.RuntimeSmoke(client)
                smoke.setup();smoke.components()
                reader=('smoke-r-'+secrets.token_hex(4),secrets.token_urlsafe(48))
                outsider=('smoke-n-'+secrets.token_hex(4),secrets.token_urlsafe(48))
                for name,password in (reader,outsider):client.user_create(name,password)
                share='smoke-share-'+secrets.token_hex(4)
                client.action('share_create',{'name':share,'readers':[smoke.username,reader[0]],'writers':[smoke.username]})
                client.smb_access((smoke.username,smoke.password),reader,outsider,share)
                client.action('app_store_refresh',{'store':'umbrel'},timeout=300)
                app=next(row for row in client.request('/api/catalog')['apps'] if row.get('umbrel_catalog') and row.get('name','').lower()=='memos')
                client.action('app_install',{'app':app['id'],'port':5230},timeout=600)
                agent.execute(['/usr/bin/curl','--fail','--retry','30','--retry-connrefused','--retry-delay','2','http://127.0.0.1:5230/'],timeout=120)
                client.action('app_action',{'app':app['id'],'action':'stop'})
                app_record=next(row for row in client.request('/api/apps')['installed'] if row['id']==app['id'])
                database=agent.python('config='+repr(app_record['config_path'])+'\n'+"""import sqlite3
from pathlib import Path
paths=[p for p in Path(config).rglob('memos_prod.db') if p.is_file()]
assert len(paths)==1, 'Memos must create exactly one persistent database'
p=paths[0]
with sqlite3.connect(p) as db:
    assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
    db.execute('create table titan_recovery_probe(value text)')
    db.execute('insert into titan_recovery_probe values (?)',('restored NAS application data',))
print(str(p))
""").strip()
                vm=qcow.run(smoke,guest,retain=True)['vm']
                snapshot_code="share="+repr(share)+"\n"+"""import hashlib,json,subprocess
from pathlib import Path
paths=['/etc/passwd','/etc/shadow','/etc/group','/etc/samba/titan-shares.conf']
print(json.dumps({'files':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths},'acl':subprocess.check_output(['getfacl','-p','/var/srv/titan/shares/'+share],text=True)},sort_keys=True))
"""
                snapshot=agent.python(snapshot_code)
                passed('source_accounts_smb_app_database_and_qcow2_guest')
                # Guest services receive an orderly NAS shutdown before any cold read.
                ab.qmp(work/'qmp.sock','system_powerdown');process.wait(timeout=180)
            source_hash=ab.sha(work/'source.qcow2')
            with boot(work,output,'backup',['source','backup'],rescue=rescue) as (agent,_):
                agent.python(PRELUDE+"""
backup=disk('backup')['path'];cmd('mkfs.ext4','-q','-F',backup)
Path('/mnt/backup').mkdir();cmd('mount',backup,'/mnt/backup')
record={**{key:disk('source')[key] for key in ('identity','size','sector')},'id':'disk-001','system':True}
with dr.pin_disks([record],{'disk-001':record['identity']}) as descriptors:
    dr.backup('/mnt/backup/packet',{'disks':[record]},descriptors)
cmd('umount','/mnt/backup')
""",timeout=1800)
                passed('cold_full_system_backup')
            with boot(work,output,'restore',['target','backup'],rescue=rescue,scsi=True) as (agent,_):
                agent.python(PRELUDE+"""
Path('/mnt/backup').mkdir();cmd('mount',disk('backup')['path'],'/mnt/backup')
Path('/mnt/backup/journals').mkdir(mode=0o700)
packet=dr.Packet('/mnt/backup/packet');mapping={'disk-001':disk('target')['identity']}
journal=Path('/mnt/backup/journals/restore.json')
def interrupt(state,value):
    if state=='disk_verified':raise RuntimeError('intentional interruption')
with dr.pin_disks(packet.disks,mapping,writing=True) as descriptors:
    try:dr.restore(packet,descriptors,mapping,journal,checkpoint=interrupt)
    except RuntimeError as exc:assert str(exc)=='intentional interruption'
    else:raise AssertionError('Restore interruption did not occur')
with dr.pin_disks(packet.disks,mapping,writing=True,resumed=True) as descriptors:
    assert dr.restore(packet,descriptors,mapping,journal,resume=True)['state']=='complete'
cmd('umount','/mnt/backup')
""",timeout=2400)
                passed('restore_resume_without_original_disk_on_changed_controller')
            with boot(work,output,'replacement',['target'],scsi=True) as (agent,process):
                agent.ready('A',identity['version'])
                assert agent.python(snapshot_code)==snapshot,'Accounts or share ACLs changed'
                client=ab.runtime.GuestClient(work/'qmp.sock')
                login=client.request('/api/login',{'name':smoke.username,'password':smoke.password});client.csrf=login['csrf']
                assert client.request('/api/session')['user']['role']=='admin'
                client.smb_access((smoke.username,smoke.password),reader,outsider,share)
                passed('replacement_login_accounts_and_smb_permissions')
                client.action('app_action',{'app':app['id'],'action':'start'})
                agent.execute(['/usr/bin/curl','--fail','--retry','30','--retry-connrefused','--retry-delay','2','http://127.0.0.1:5230/'],timeout=120)
                client.action('app_action',{'app':app['id'],'action':'stop'})
                agent.python('import sqlite3\nwith sqlite3.connect('+repr(database)+') as db:\n assert db.execute("pragma integrity_check").fetchone()[0]=="ok"\n assert db.execute("select value from titan_recovery_probe").fetchall()==[("restored NAS application data",)]')
                passed('restored_application_runs_with_preserved_database')
                client.action('vm_action',{'vm':vm,'action':'start'});qcow.wait_guest(client,vm,True)
                client.console_rfb(vm)
                client.action('vm_guest_action',{'vm':vm,'action':'shutdown'});qcow.wait_guest(client,vm,False)
                passed('restored_qcow2_guest_boot_console_and_clean_shutdown')
                ab.qmp(work/'qmp.sock','system_powerdown');process.wait(timeout=180)
            assert ab.sha(work/'source.qcow2')==source_hash,'Original source disk changed'
            assert ab.sha(image)==report['image_sha256'] and ab.sha(rescue)==report['recovery_iso_sha256']
            passed('original_disks_and_distribution_images_unchanged')
            report['ok']=True
    finally:
        (output/'nas-recovery-test.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()

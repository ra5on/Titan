#!/usr/bin/env python3
"""Boot the rescue ISO and recover real disposable virtual block devices.

No host block device is ever attached. Source disks are disconnected before
restoration; replacement serial numbers, controller and capacity differ.
This verifies the rescue medium, not yet a complete installed NAS boot.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ab_smoke', ROOT/'scripts/smoke-debian-ab.py')
ab = importlib.util.module_from_spec(spec); spec.loader.exec_module(ab)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('iso', type=Path)
    parser.add_argument('--confirm-disposable-guest', action='store_true')
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true' or not args.confirm_disposable_guest:
        parser.error('Requires an explicitly disposable GitHub runner.')
    iso = args.iso.resolve()
    if not iso.is_file(): parser.error('Rescue ISO missing.')
    report = {'format':'titan-recovery-medium-test-v1', 'ok':False,
              'scope':'rescue-iso-real-block-devices', 'installed_nas_boot_verified':False,
              'source_commit':os.environ.get('GITHUB_SHA'), 'iso_sha256':ab.sha(iso), 'checks':[]}
    def passed(name):
        report['checks'].append(name); print(name + ': passed', flush=True)
    try:
        with tempfile.TemporaryDirectory(prefix='titan-recovery-acceptance-') as tmp:
            work = Path(tmp)
            for name, size in [('source1',64),('source2',64),('target1',96),('target2',96),('backup',512)]:
                with (work/(name+'.raw')).open('xb') as stream: stream.truncate(size*1024**2)
            @contextlib.contextmanager
            def boot(phase, disks, controller):
                vars_source = next(Path('/usr/share/OVMF').glob('OVMF_VARS_4M.fd'))
                shutil.copyfile(vars_source, work/'vars.fd')
                socket = work/'qga.sock'; socket.unlink(missing_ok=True)
                (work/'qmp.sock').unlink(missing_ok=True)
                command = ['qemu-system-x86_64','-machine','q35,accel=kvm:tcg','-m','2048','-smp','2',
                           '-qmp','unix:'+str(work/'qmp.sock')+',server=on,wait=off','-display','none','-no-reboot','-nic','none','-boot','d',
                           '-drive','if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd',
                           '-drive','if=pflash,format=raw,file='+str(work/'vars.fd'),
                           '-cdrom',str(iso),'-serial','file:'+str(iso.parent/('recovery-console-'+phase+'.log')),
                           '-device','virtio-serial-pci','-chardev','socket,path='+str(socket)+',server=on,wait=off,id=qga',
                           '-device','virtserialport,chardev=qga,name=org.qemu.guest_agent.0']
                if controller == 'scsi': command += ['-device','virtio-scsi-pci,id=scsi']
                for index, name in enumerate([*disks, 'backup']):
                    command += ['-drive',f'if=none,format=raw,id=d{index},file={work/(name+".raw")}',
                                '-device', ('scsi-hd,bus=scsi.0' if controller=='scsi' else 'virtio-blk-pci')+f',drive=d{index},serial=TITAN_{name}']
                with subprocess.Popen(command) as proc:
                    try:
                        agent = ab.Agent(socket)
                        deadline = time.monotonic()+300; last_error = None
                        while time.monotonic() < deadline:
                            if proc.poll() is not None: raise RuntimeError('Rescue VM exited before guest agent was ready.')
                            try:
                                agent.execute(['/usr/bin/test','-f','/usr/local/bin/titan-recovery'],timeout=10)
                                break
                            except (OSError,RuntimeError) as exc:
                                last_error = str(exc); time.sleep(2)
                        else: raise RuntimeError('Rescue ISO guest agent unavailable: '+str(last_error))
                        yield agent
                    finally:
                        if not report['ok']:
                            try: ab.qmp(work/'qmp.sock','screendump',{'filename':str(iso.parent/('recovery-screen-'+phase+'.ppm'))})
                            except (OSError,RuntimeError): pass
                        proc.terminate()
                        try: proc.wait(timeout=15)
                        except subprocess.TimeoutExpired: proc.kill();proc.wait()
            prelude = '''import importlib.machinery, importlib.util, json, os, subprocess
from pathlib import Path
loader=importlib.machinery.SourceFileLoader('recovery','/usr/local/bin/titan-recovery')
spec=importlib.util.spec_from_loader(loader.name,loader)
dr=importlib.util.module_from_spec(spec);loader.exec_module(dr)
def cmd(*args): return subprocess.check_output(args,text=True)
def disk(name): return next(d for d in dr.block_inventory() if d['identity']=='serial:TITAN_'+name)
'''
            with boot('backup', ['source1','source2'], 'virtio') as agent:
                passed('uefi_rescue_boot')
                agent.python(prelude+'''
for name in ('source1','source2'):
    path=disk(name)['path']
    cmd('parted','-s',path,'mklabel','gpt','mkpart','primary','ext4','1MiB','100%')
    cmd('udevadm','settle')
    part=path+'1'
    cmd('mkfs.ext4','-q','-F',part)
    mount=Path('/mnt/'+name);mount.mkdir()
    cmd('mount',part,str(mount))
    sentinel=mount/'private-data';sentinel.write_text('Titan recovery '+name+'\\n');sentinel.chmod(0o640)
    os.chown(sentinel,1234,1235);os.setxattr(sentinel,'user.titan',b'preserved')
    cmd('setfacl','-m','u:1236:r--',str(sentinel))
    import sqlite3
    with sqlite3.connect(mount/'app.sqlite') as db:
        db.execute('create table proof(value text)');db.execute('insert into proof values (?)',(name,))
    db.close()
    cmd('qemu-img','create','-q','-f','qcow2',str(mount/'guest.qcow2'),'8M')
    cmd('umount',str(mount))
backup=disk('backup')['path'];cmd('mkfs.ext4','-q','-F',backup)
Path('/mnt/backup').mkdir();cmd('mount',backup,'/mnt/backup')
records=[{**{key:disk(name)[key] for key in ('identity','size','sector')},'id':'disk-%03d'%i,'system':i==1} for i,name in enumerate(('source1','source2'),1)]
with dr.pin_disks(records,{d['id']:d['identity'] for d in records}) as descriptors:
    dr.backup('/mnt/backup/packet',{'disks':records},descriptors)
cmd('umount','/mnt/backup')
''',timeout=240)
                passed('cold_backup_real_gpt_disks')
            source_hashes = [ab.sha(work/(name+'.raw')) for name in ('source1','source2')]
            with boot('restore', ['target1','target2'], 'scsi') as agent:
                passed('replacement_controller_boot_without_sources')
                agent.python(prelude+'''
Path('/mnt/backup').mkdir();cmd('mount',disk('backup')['path'],'/mnt/backup')
Path('/mnt/backup/journals').mkdir(mode=0o700)
packet=dr.Packet('/mnt/backup/packet');mapping={d['id']:'serial:TITAN_target'+str(i) for i,d in enumerate(packet.disks,1)}
journal=Path('/mnt/backup/journals/restore.json')
def interrupt(state,value):
    if state=='disk_verified': raise RuntimeError('simulated process interruption')
with dr.pin_disks(packet.disks,mapping,writing=True) as descriptors:
    try: dr.restore(packet,descriptors,mapping,journal,checkpoint=interrupt)
    except RuntimeError as exc:
        assert str(exc)=='simulated process interruption'
    else: raise AssertionError('Interruption did not occur')
    for d in packet.disks:
        fd=descriptors[d['id']]
        assert os.pread(fd,dr.HEADER,0)==bytes(dr.HEADER)
        assert os.pread(fd,dr.HEADER,d['size']-dr.HEADER)==bytes(dr.HEADER)
with dr.pin_disks(packet.disks,mapping,writing=True,resumed=True) as descriptors:
    assert dr.restore(packet,descriptors,mapping,journal,resume=True)['state']=='complete'
packet.verify()
for i,name in enumerate(('target1','target2'),1):
    path=disk(name)['path'];cmd('partprobe',path);cmd('udevadm','settle')
    mount=Path('/mnt/'+name);mount.mkdir();cmd('mount','-o','ro,noload',path+'1',str(mount))
    sentinel=mount/'private-data'
    assert sentinel.read_text()=='Titan recovery source'+str(i)+'\\n'
    assert (sentinel.stat().st_uid,sentinel.stat().st_gid)==(1234,1235)
    assert os.getxattr(sentinel,'user.titan')==b'preserved'
    assert 'user:1236:r--' in cmd('getfacl','-n',str(sentinel))
    import sqlite3
    with sqlite3.connect('file:'+str(mount/'app.sqlite')+'?mode=ro',uri=True) as db:
        assert db.execute('select value from proof').fetchone()[0]=='source'+str(i)
    db.close()
    assert json.loads(cmd('qemu-img','info','--output=json',str(mount/'guest.qcow2')))['format']=='qcow2'
    cmd('umount',str(mount))
cmd('umount','/mnt/backup')
''',timeout=240)
                passed('interrupted_restore_withholds_primary_and_backup_gpt')
                passed('resume_to_larger_disks_and_verify_every_byte')
                passed('uid_gid_acl_xattr_sqlite_qcow2_preserved')
            assert source_hashes == [ab.sha(work/(name+'.raw')) for name in ('source1','source2')]
            assert ab.sha(iso) == report['iso_sha256']
            passed('original_disks_and_rescue_image_unchanged')
            report['ok'] = True
    finally:
        (iso.parent/'recovery-test.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__ == '__main__': main()

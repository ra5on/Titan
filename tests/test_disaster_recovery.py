import copy
import gzip
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from titan import disaster_recovery as dr


class ColdRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.root.chmod(0o700)
        self.size = 3*1024*1024
        self.disks = [{'id':f'disk-{i:03}', 'identity':f'serial:source{i}', 'size':self.size,
                       'sector':512, 'system':i == 1, 'model':'Test'} for i in (1,2)]
        self.sources = {}; self.targets = {}; self.mapping = {}
        for disk in self.disks:
            name = disk['id']
            fd = os.open(self.root/(name+'.source'), os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
            os.ftruncate(fd,self.size)
            os.pwrite(fd, ('GPT-'+name).encode(),0)
            os.pwrite(fd,os.urandom(8192),dr.HEADER+100)
            os.pwrite(fd,('DATA-END-'+name).encode(),self.size-64)
            self.sources[name] = fd
            target = os.open(self.root/(name+'.target'),os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
            os.ftruncate(target,self.size+512*1024)
            self.targets[name] = target; self.mapping[name] = 'serial:replacement-'+name
        self.addCleanup(lambda:[os.close(fd) for fd in [*self.sources.values(),*self.targets.values()]])
        self.packet_path=self.root/'packet'
        dr.backup(self.packet_path,{'disks':self.disks},self.sources)
        self.packet=dr.Packet(self.packet_path); self.journal=self.root/'restore.json'

    def restore(self,**kwargs):
        return dr.restore(self.packet,self.targets,self.mapping,self.journal,sparse_files=True,**kwargs)

    def test_full_two_disk_roundtrip_preserves_all_bytes_and_source(self):
        before={key:dr.digest_fd(fd,self.size) for key,fd in self.sources.items()}
        result=self.restore();self.assertEqual(result['state'],'complete')
        self.assertEqual(before,{key:dr.digest_fd(fd,self.size) for key,fd in self.sources.items()})
        self.assertEqual(before,{key:dr.digest_fd(fd,self.size) for key,fd in self.targets.items()})
        self.assertEqual(dr.Packet(self.packet_path).verify(),self.packet.fingerprint)
        self.assertEqual(os.pread(self.targets['disk-001'],512,self.size),bytes(512))

    def test_corrupt_last_archive_is_rejected_before_any_target_write(self):
        for fd in self.targets.values():os.pwrite(fd,b'KEEP',0)
        path=self.packet_path/'disk-002.img.gz';data=bytearray(path.read_bytes());data[-5]^=0x20;path.write_bytes(data)
        with self.assertRaises((dr.RecoveryError,OSError,EOFError)):self.restore()
        self.assertFalse(self.journal.exists())
        for fd in self.targets.values():self.assertEqual(os.pread(fd,4,0),b'KEEP')

    def test_boot_headers_remain_invalid_until_all_disks_verify(self):
        observed=[]
        def checkpoint(state,value):
            if state in ('disk_verified','committing'):
                observed.append(state)
                for fd in self.targets.values():
                    self.assertEqual(os.pread(fd,dr.HEADER,0),bytes(dr.HEADER))
                    self.assertEqual(os.pread(fd,dr.HEADER,self.size-dr.HEADER),bytes(dr.HEADER))
        self.restore(checkpoint=checkpoint)
        self.assertEqual(observed,['disk_verified','disk_verified','committing'])

    def test_interrupted_restore_resumes_with_exact_packet_and_disk_identity(self):
        def crash(state,value):
            if state=='disk_verified':raise RuntimeError('power loss')
        with self.assertRaises(RuntimeError):self.restore(checkpoint=crash)
        for fd in self.targets.values():self.assertEqual(os.pread(fd,dr.HEADER,0),bytes(dr.HEADER))
        self.assertEqual(self.restore(resume=True)['state'],'complete')

    def test_resume_rejects_swapped_targets_or_changed_packet(self):
        dr.atomic_json(self.journal,{'fingerprint':self.packet.fingerprint,'targets':dict(reversed(list(self.mapping.items()))),'state':'writing'})
        swapped=dict(zip(self.mapping,reversed(list(self.mapping.values()))))
        with self.assertRaises(dr.RecoveryError):dr.restore(self.packet,self.targets,swapped,self.journal,resume=True,sparse_files=True)
        dr.atomic_json(self.journal,{'fingerprint':'wrong','targets':self.mapping,'state':'writing'})
        with self.assertRaises(dr.RecoveryError):self.restore(resume=True)

    def test_completed_journal_requires_matching_target_bytes(self):
        self.restore();self.assertEqual(self.restore(resume=True)['state'],'complete')
        os.pwrite(self.targets['disk-001'],b'changed',dr.HEADER+200)
        with self.assertRaises(dr.RecoveryError):self.restore(resume=True)

    def test_original_disk_cannot_be_chosen_as_target(self):
        self.mapping['disk-001']=self.disks[0]['identity']
        with self.assertRaises(dr.RecoveryError):self.restore()
        self.assertFalse(self.journal.exists())

    def test_missing_or_duplicate_targets_are_rejected(self):
        self.mapping['disk-002']=self.mapping['disk-001']
        with self.assertRaises(dr.RecoveryError):self.restore()
        del self.mapping['disk-002']
        with self.assertRaises(dr.RecoveryError):self.restore()

    def test_missing_source_cannot_be_marked_complete(self):
        with self.assertRaises(dr.RecoveryError):dr.backup(self.root/'bad',{'disks':self.disks},{'disk-001':self.sources['disk-001']})
        self.assertFalse((self.root/'bad/manifest.json').exists())

    def test_archive_symlink_and_unknown_files_are_rejected(self):
        extra=self.packet_path/'unexpected';extra.touch()
        with self.assertRaises(dr.RecoveryError):dr.Packet(self.packet_path)
        extra.unlink();archive=self.packet_path/'disk-001.img.gz';archive.rename(self.root/'outside');archive.symlink_to(self.root/'outside')
        with self.assertRaises(OSError):self.packet.verify()

    def test_duplicate_json_incomplete_packet_and_traversal_filename_rejected(self):
        with self.assertRaises(dr.RecoveryError):dr.strict_json('{"a":1,"a":2}')
        path=self.packet_path/'manifest.json';original=json.loads(path.read_text())
        for change in ({'complete':False},{'architecture':'aarch64'},{'disks':[]}, {'disks':[{**original['disks'][0],'file':'../outside'}]}):
            dr.atomic_json(path,{**original,**change})
            with self.assertRaises(dr.RecoveryError):dr.Packet(self.packet_path)

    def test_crash_leftover_journal_is_safely_replaced(self):
        leftover=self.journal.with_name(self.journal.name+'.new');leftover.write_bytes(b'{');leftover.chmod(0o600)
        self.assertEqual(self.restore()['state'],'complete');self.assertFalse(leftover.exists())

    def test_short_writes_are_completed(self):
        original=os.pwrite;fd=self.targets['disk-001']
        with patch.object(dr.os,'pwrite',side_effect=lambda f,data,offset:original(f,data[:3],offset)):
            dr.write_at(fd,b'abcdefghij',123)
        self.assertEqual(os.pread(fd,10,123),b'abcdefghij')

    def test_unknown_or_duplicate_source_identities_rejected(self):
        for identity in ('',None,self.disks[0]['identity']):
            value=copy.deepcopy(self.disks);value[1]['identity']=identity
            with self.assertRaises(dr.RecoveryError):dr.validate_disks(value)

    def test_mounted_disk_and_changed_sector_size_rejected_before_open(self):
        disk={'identity':self.disks[0]['identity'],'mounted':True,'size':self.size,'sector':512}
        with patch.object(dr.os,'geteuid',return_value=0),patch.object(dr,'block_inventory',return_value=[disk]),patch.object(dr.os,'open') as opening:
            with self.assertRaises(dr.RecoveryError):
                with dr.pin_disks(self.disks[:1],{'disk-001':disk['identity']}):pass
            opening.assert_not_called()
            disk['mounted']=False;disk['sector']=4096
            with self.assertRaises(dr.RecoveryError):
                with dr.pin_disks(self.disks[:1],{'disk-001':disk['identity']},writing=True):pass
            opening.assert_not_called()

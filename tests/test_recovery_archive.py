import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest

from titan.core import Error
from titan.recovery_archive import Packet, FORMAT, inspect_tar, pack_tree, unpack_tree, exchange_directories


@unittest.skipUnless(shutil.which('tar'), 'GNU tar required')
class RecoveryArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def archive(self, entries):
        path=self.root/'test.tar.gz'
        with tarfile.open(path,'w:gz') as t:
            for item,data in entries:
                t.addfile(item,io.BytesIO(data) if data is not None else None)
        return os.open(path,os.O_RDONLY)
    def inspect(self, entries):
        fd=self.archive(entries)
        try:return inspect_tar(fd)
        finally:os.close(fd)
    def test_actual_sparse_content_hardlinks_xattrs_and_modes_round_trip(self):
        source=self.root/'source';source.mkdir();(source/'folder').mkdir()
        f=source/'folder'/'text';f.write_bytes(b'private\x00data');f.chmod(0o640)
        os.link(f,source/'another');os.symlink('folder/text',source/'link')
        with (source/'vm.qcow2').open('wb') as out:out.seek(64*1024**2);out.write(b'VM-end')
        os.setxattr(f,'user.titan-proof',b'restored')
        archive=self.root/'persistent.tar.gz';fd=os.open(archive,os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600);src=os.open(source,os.O_DIRECTORY)
        try:
            record=pack_tree(src,fd);inspection=inspect_tar(fd)
            self.assertGreater(inspection['logical'],60*1024**2);self.assertLess(inspection['allocated'],128*1024)
            dest=self.root/'restored';dest.mkdir(mode=0o700);unpack_tree(fd,dest,inspected=inspection)
            self.assertEqual((dest/'folder'/'text').read_bytes(),b'private\x00data')
            self.assertEqual((dest/'another').stat().st_ino,(dest/'folder'/'text').stat().st_ino)
            self.assertEqual(os.readlink(dest/'link'),'folder/text')
            self.assertEqual(os.getxattr(dest/'folder'/'text','user.titan-proof'),b'restored')
            self.assertEqual((dest/'folder'/'text').stat().st_mode&0o777,0o640)
            with (dest/'vm.qcow2').open('rb') as stream:stream.seek(64*1024**2);self.assertEqual(stream.read(),b'VM-end')
            self.assertLess((dest/'vm.qcow2').stat().st_blocks*512,128*1024)
            self.assertEqual(record['sha256'],hashlib.sha256(archive.read_bytes()).hexdigest())
        finally:os.close(src);os.close(fd)
    def test_traversal_and_absolute_paths_rejected(self):
        for name in ('../escape','/etc/passwd','safe/../../escape','./safe/../escape'):
            with self.subTest(name=name),self.assertRaises(Error):self.inspect([(tarfile.TarInfo(name),b'')])
    def test_symlink_parent_rejected_even_when_listed_after_child(self):
        for reverse in (False,True):
            link=tarfile.TarInfo('parent');link.type=tarfile.SYMTYPE;link.linkname='/etc'
            child=tarfile.TarInfo('parent/passwd')
            entries=[(link,None),(child,b'')]
            with self.assertRaises(Error):self.inspect(list(reversed(entries)) if reverse else entries)
    def test_hardlink_outside_archive_rejected(self):
        link=tarfile.TarInfo('link');link.type=tarfile.LNKTYPE;link.linkname='../passwd'
        with self.assertRaises(Error):self.inspect([(link,None)])
    def test_duplicate_paths_and_block_devices_rejected(self):
        item=tarfile.TarInfo('file')
        with self.assertRaises(Error):self.inspect([(item,b''),(item,b'')])
        device=tarfile.TarInfo('disk');device.type=tarfile.BLKTYPE;device.devmajor=8
        with self.assertRaises(Error):self.inspect([(device,None)])
    def test_nonempty_destination_is_never_overwritten(self):
        fd=self.archive([(tarfile.TarInfo('file'),b'')]);dest=self.root/'existing';dest.mkdir(mode=0o700);(dest/'original').write_text('keep')
        try:
            with self.assertRaises(Error):unpack_tree(fd,dest)
            self.assertEqual((dest/'original').read_text(),'keep');self.assertFalse((dest/'file').exists())
        finally:os.close(fd)
    def test_atomic_directory_exchange_preserves_both_generations(self):
        for name,value in [('persistent','fresh'),('incoming','restored')]:
            (self.root/name).mkdir();(self.root/name/'identity').write_text(value)
        exchange_directories(self.root,'persistent','incoming')
        self.assertEqual((self.root/'persistent'/'identity').read_text(),'restored')
        self.assertEqual((self.root/'incoming'/'identity').read_text(),'fresh')
        exchange_directories(self.root,'persistent','incoming')
        self.assertEqual((self.root/'persistent'/'identity').read_text(),'fresh')
    def test_packet_verification_detects_changed_archive_and_missing_files(self):
        packet=self.root/'packet';packet.mkdir(mode=0o700)
        fd=self.archive([(tarfile.TarInfo('file'),b'')]);os.close(fd)
        archive=packet/'persistent.tar.gz';shutil.copy(self.root/'test.tar.gz',archive);archive.chmod(0o600)
        manifest={'format':FORMAT,'complete':True,'system':{},'archives':[{'file':archive.name,'size':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}]}
        metadata=packet/'manifest.json';metadata.write_text(json.dumps(manifest));metadata.chmod(0o600)
        with Packet(packet) as value:self.assertEqual(value.verify()[archive.name]['entries'],1)
        archive.write_bytes(archive.read_bytes()+b'tampered')
        with Packet(packet) as value:
            with self.assertRaises(Error):value.verify()
        archive.unlink()
        with self.assertRaises(Error):
            with Packet(packet):pass
    def test_incomplete_packet_not_accepted(self):
        packet=self.root/'packet';packet.mkdir(mode=0o700)
        (packet/'manifest.json').write_text(json.dumps({'format':FORMAT,'complete':False}));(packet/'manifest.json').chmod(0o600)
        with self.assertRaises(Error):
            with Packet(packet):pass

    def test_non_object_manifest_is_rejected_cleanly(self):
        packet=self.root/'packet';packet.mkdir(mode=0o700)
        metadata=packet/'manifest.json';metadata.write_text('[]');metadata.chmod(0o600)
        with self.assertRaises(Error):
            with Packet(packet):pass

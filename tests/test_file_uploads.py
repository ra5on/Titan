import base64
import contextlib
from concurrent.futures import ThreadPoolExecutor
import errno
import fcntl
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch

from titan.core import Error
from titan.files import operate
from titan.file_uploads import DIRECTORY, TTL
from titan import file_uploads
from titan.demo import Demo
from titan.management_host import ManagementMixin
from titan.backups import Backups, directory_fd
from titan.system_files import operate_system
from tests.test_lifecycle_http import HTTPFixture

TOKEN = 'a' * 64


class AtomicUploadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def call(self, path='upload.txt', **args):
        return operate(self.root, 'upload', path, upload_id=TOKEN, total=6, **args)

    def chunk(self, value=b'abc', offset=0, **args):
        return self.call(offset=offset, data=base64.b64encode(value).decode(), **args)

    def test_complete_file_is_exposed_only_by_confirmed_atomic_commit(self):
        self.assertEqual(self.chunk()['offset'], 3)
        self.assertFalse((self.root / 'upload.txt').exists())
        self.assertEqual(operate(self.root, 'list')['entries'], [])
        self.assertEqual(operate(self.root, 'list', recursive=True)['entries'], [])
        self.chunk(b'def', 3)
        self.assertFalse((self.root / 'upload.txt').exists())
        self.assertTrue(self.call(finish=True)['complete'])
        self.assertEqual((self.root / 'upload.txt').read_bytes(), b'abcdef')
        self.assertTrue(self.call(finish=True)['complete'], 'Commit retry is idempotent')
        self.assertEqual((self.root / 'upload.txt').stat().st_mode & 0o777, 0o660)

    def test_cancel_before_first_chunk_blocks_delayed_chunk_and_commit(self):
        self.assertTrue(self.call(cancel=True)['canceled'])
        with self.assertRaisesRegex(Error, 'abgebrochen'):
            self.chunk()
        with self.assertRaisesRegex(Error, 'abgebrochen'):
            self.call(finish=True)
        self.assertFalse((self.root / 'upload.txt').exists())
        self.assertFalse(list((self.root / DIRECTORY).glob('*.part')))

    def test_cancel_removes_private_parts_and_never_removes_completed_file(self):
        self.chunk()
        self.assertTrue(self.call(cancel=True)['canceled'])
        self.assertTrue(self.call(cancel=True)['canceled'])
        self.assertFalse(list((self.root / DIRECTORY).glob('*.part')))
        self.assertFalse((self.root / 'upload.txt').exists())
        result=operate(self.root, 'upload', 'complete', upload_id='b'*64, total=0, offset=0, data='')
        self.assertEqual(result['offset'], 0)
        operate(self.root, 'upload', 'complete', upload_id='b'*64, total=0, finish=True)
        self.assertTrue(operate(self.root, 'upload', 'complete', upload_id='b'*64, total=0, cancel=True)['complete'])
        self.assertEqual((self.root / 'complete').read_bytes(), b'')

    def test_existing_and_racing_destinations_are_never_overwritten(self):
        (self.root / 'upload.txt').write_text('original')
        with self.assertRaisesRegex(Error, 'existiert'):
            self.chunk()
        self.assertEqual((self.root / 'upload.txt').read_text(), 'original')
        (self.root / 'upload.txt').unlink()
        self.chunk(b'abcdef')
        (self.root / 'upload.txt').write_text('other writer')
        with self.assertRaisesRegex(Error, 'existiert'):
            self.call(finish=True)
        self.call(cancel=True)
        self.assertEqual((self.root / 'upload.txt').read_text(), 'other writer')
        self.assertFalse(list((self.root / DIRECTORY).glob('*.part')))

    def test_failed_stage_journal_save_can_be_canceled_without_exposing_data(self):
        with patch.object(file_uploads, '_save', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.chunk()
        self.assertFalse((self.root / 'upload.txt').exists())
        self.assertTrue(self.call(cancel=True)['canceled'])
        self.assertFalse(list((self.root / DIRECTORY).glob('*.part')))

    def test_finish_never_rewrites_the_journal_after_publishing_the_file(self):
        self.chunk(b'abcdef')
        with patch.object(file_uploads, '_save', side_effect=OSError('journal unavailable')) as save:
            self.assertTrue(self.call(finish=True)['complete'])
            self.assertTrue(self.call(cancel=True)['complete'])
            self.assertTrue(self.call(finish=True)['complete'])
            save.assert_not_called()
        self.assertEqual((self.root / 'upload.txt').read_bytes(), b'abcdef')

    def test_directory_fsync_failure_after_rename_recovers_complete_on_cancel(self):
        self.chunk(b'abcdef')
        sync = os.fsync
        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError('directory sync unavailable')
            return sync(fd)
        with patch.object(file_uploads.os, 'fsync', side_effect=fail_directory):
            with self.assertRaisesRegex(OSError, 'directory sync'):
                self.call(finish=True)
        self.assertEqual((self.root / 'upload.txt').read_bytes(), b'abcdef')
        result = self.call(cancel=True)
        self.assertTrue(result['complete'])
        self.assertFalse(result['canceled'])
        self.assertEqual(result['offset'], 6)

    def test_recovery_does_not_mistake_another_inode_for_a_committed_upload(self):
        self.chunk(b'abcdef')
        (self.root / DIRECTORY / (TOKEN + '.part')).rename(self.root / 'staged-elsewhere')
        (self.root / 'upload.txt').write_bytes(b'ABCDEF')
        result = self.call(cancel=True)
        self.assertFalse(result['complete'])
        self.assertTrue(result['canceled'])
        self.assertEqual((self.root / 'upload.txt').read_bytes(), b'ABCDEF')

    def test_binding_offsets_payload_limits_and_incomplete_finish(self):
        self.chunk()
        for options in ({'path':'other','offset':3,'data':''}, {'offset':0,'data':''}, {'offset':3,'data':'!!!!'}, {'offset':3,'data':base64.b64encode(b'1234').decode()}, {'finish':True}, {'cancel':'yes'}, {'finish':True,'cancel':True}):
            with self.subTest(options=options), self.assertRaises(Error):
                self.call(**options)
        with self.assertRaises(Error):
            operate(self.root, 'upload', 'upload.txt', upload_id=TOKEN, total=5, offset=3, data='')
        with self.assertRaises(Error):
            operate(self.root, 'upload', 'bad', upload_id='../bad', total=0, data='')
        self.assertFalse((self.root / 'upload.txt').exists())
        self.call(cancel=True)

    def test_cancel_serializes_with_a_chunk_already_in_progress(self):
        entered, release = threading.Event(), threading.Event()
        original = file_uploads._save
        def save(fd,state):
            if state['status']=='uploading':
                entered.set()
                self.assertTrue(release.wait(2))
            return original(fd,state)
        with ThreadPoolExecutor(max_workers=2) as workers, patch.object(file_uploads,'_save',side_effect=save):
            chunk=workers.submit(self.chunk)
            self.assertTrue(entered.wait(2))
            cancel=workers.submit(self.call,cancel=True)
            release.set()
            self.assertEqual(chunk.result(2)['offset'],3)
            self.assertTrue(cancel.result(2)['canceled'])
        self.assertFalse((self.root/'upload.txt').exists())
        self.assertFalse(list((self.root/DIRECTORY).glob('*.part')))
        with self.assertRaisesRegex(Error,'abgebrochen'):self.chunk(b'def',3)

    def test_private_directory_cannot_be_replaced_by_a_link_or_public_directory(self):
        (self.root / DIRECTORY).symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):self.chunk()
        (self.root / DIRECTORY).unlink()
        (self.root / DIRECTORY).mkdir(mode=0o755)
        with self.assertRaisesRegex(Error,'geschützt'):self.chunk()
        self.assertFalse((self.root/'upload.txt').exists())

    def test_share_acl_changes_do_not_grant_access_to_private_upload_fragments(self):
        self.chunk()
        visible = self.root / 'normal.txt'
        visible.write_text('visible')
        private = self.root / DIRECTORY
        protected = {(path.stat().st_dev, path.stat().st_ino) for path in [private, *private.iterdir()]}
        changed = set()
        host = ManagementMixin()
        host.directory = self.root
        host.open_share_root = lambda path: os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        def acl_write(fd, text, directory):
            value = os.fstat(fd)
            changed.add((value.st_dev, value.st_ino))
        with patch.object(host, 'acl_read', return_value='user::rwx'), patch.object(host, 'acl_for_members', return_value='shared'), patch.object(host, 'acl_write', side_effect=acl_write):
            host.share_acl_transaction({'path': str(self.root)}, [], ['writer'], lambda: None)
        self.assertIn((visible.stat().st_dev, visible.stat().st_ino), changed)
        self.assertFalse(changed & protected, 'Changing share access must not expose private chunks or upload records')
        self.assertEqual(private.stat().st_mode & 0o777, 0o700)

    def test_folder_copy_excludes_private_stages_but_keeps_completed_files(self):
        nested = self.root / 'folder' / 'nested'
        nested.mkdir(parents=True)
        (nested / 'ready.txt').write_text('ready')
        self.call(path='folder/nested/upload.txt', offset=0, data='YWJj')
        operate(self.root, 'copy', 'folder', destination='copy')
        self.assertEqual((self.root / 'copy/nested/ready.txt').read_text(), 'ready')
        self.assertFalse((self.root / 'copy/nested' / DIRECTORY).exists())
        self.assertTrue((nested / DIRECTORY / (TOKEN + '.part')).exists())
        with self.assertRaisesRegex(Error, 'Private Upload'):
            operate(self.root, 'copy', 'folder/nested/' + DIRECTORY, destination='private-copy')
        self.assertFalse((self.root / 'private-copy').exists())

    def test_folder_move_with_private_state_blocks_before_rename_or_copy(self):
        nested = self.root / 'folder' / 'nested'
        nested.mkdir(parents=True)
        self.call(path='folder/nested/upload.txt', offset=0, data='YWJj')
        for cross_device in (False, True):
            with self.subTest(cross_device=cross_device), patch('titan.files._rename_no_replace', side_effect=OSError(errno.EXDEV, 'cross device') if cross_device else None) as rename, patch('titan.files._copy_entry') as copy:
                with self.assertRaisesRegex(Error, 'Upload-Zwischenstände'):
                    operate(self.root, 'move', 'folder', destination='moved')
                rename.assert_not_called()
                copy.assert_not_called()
            self.assertTrue((nested / DIRECTORY / (TOKEN + '.part')).exists())
            self.assertFalse((self.root / 'moved').exists())
        self.call(path='folder/nested/upload.txt', offset=3, data='ZGVm')
        self.call(path='folder/nested/upload.txt', finish=True)
        operate(self.root, 'move', 'folder', destination='moved')
        operate(self.root, 'move', 'moved/nested/upload.txt', destination='complete.txt')
        self.assertEqual((self.root / 'complete.txt').read_bytes(), b'abcdef')

    def test_completed_and_canceled_metadata_allow_same_and_cross_filesystem_moves(self):
        for cross_device in (False, True):
            with self.subTest(cross_device=cross_device):
                name = 'cross' if cross_device else 'same'
                source = self.root / name
                source.mkdir()
                self.call(path=name + '/ready.txt', offset=0, data='YWJjZGVm')
                self.call(path=name + '/ready.txt', finish=True)
                operate(self.root, 'upload', name + '/canceled.txt', upload_id='b' * 64, total=6, offset=0, data='YWJj')
                operate(self.root, 'upload', name + '/canceled.txt', upload_id='b' * 64, total=6, cancel=True)
                # Completion must remain known even after the final file was renamed.
                (source / 'ready.txt').rename(source / 'renamed.txt')
                done_inode = (source / DIRECTORY).stat().st_ino
                destination = name + '-moved'
                manager = patch('titan.files._rename_no_replace', side_effect=OSError(errno.EXDEV, 'cross device')) if cross_device else contextlib.nullcontext()
                with manager:
                    operate(self.root, 'move', name, destination=destination)
                target = self.root / destination
                self.assertFalse(source.exists())
                self.assertEqual((target / 'renamed.txt').read_bytes(), b'abcdef')
                self.assertFalse((target / 'canceled.txt').exists())
                self.assertEqual((target / DIRECTORY).stat().st_mode & 0o777, 0o700)
                self.assertEqual((target / DIRECTORY).stat().st_uid, os.geteuid())
                for item in (target / DIRECTORY).iterdir():
                    self.assertEqual(item.stat().st_mode & 0o777, 0o600)
                if not cross_device:
                    self.assertEqual((target / DIRECTORY).stat().st_ino, done_inode)
                self.assertTrue(self.call(path=destination + '/ready.txt', finish=True)['complete'])
                with self.assertRaisesRegex(Error, 'abgebrochen'):
                    operate(self.root, 'upload', destination + '/canceled.txt', upload_id='b' * 64, total=6, offset=3, data='ZGVm')

    def test_private_directory_and_journal_locks_block_move_without_changes(self):
        source = self.root / 'folder'
        source.mkdir()
        self.call(path='folder/ready.txt', offset=0, data='YWJjZGVm')
        self.call(path='folder/ready.txt', finish=True)
        for path, mode in [(source / DIRECTORY, fcntl.LOCK_SH), (source / DIRECTORY / (TOKEN + '.json'), fcntl.LOCK_EX)]:
            with self.subTest(path=path):
                fd = os.open(path, os.O_RDONLY)
                try:
                    fcntl.flock(fd, mode | fcntl.LOCK_NB)
                    with patch('titan.files._rename_no_replace') as rename, patch('titan.files._copy_entry') as copy:
                        with self.assertRaisesRegex(Error, 'Upload-Zwischenstände'):
                            operate(self.root, 'move', 'folder', destination='moved')
                        rename.assert_not_called()
                        copy.assert_not_called()
                finally:
                    os.close(fd)
                self.assertEqual((source / 'ready.txt').read_bytes(), b'abcdef')
                self.assertFalse((self.root / 'moved').exists())

    def test_unclear_and_corrupt_private_metadata_block_moves(self):
        source = self.root / 'folder'
        source.mkdir()
        self.call(path='folder/pending.txt', offset=0, data='YWJj')
        (source / DIRECTORY / (TOKEN + '.part')).unlink()
        record = source / DIRECTORY / (TOKEN + '.json')
        for contents in [record.read_text(), '{broken', json.dumps({'name':'pending.txt','status':'complete','offset':3,'total':6})]:
            record.write_text(contents)
            with self.subTest(contents=contents), self.assertRaisesRegex(Error, 'Upload-Zwischenstände'):
                operate(self.root, 'move', 'folder', destination='moved')
            self.assertFalse((self.root / 'moved').exists())

    def test_cross_filesystem_metadata_copy_failure_keeps_source_and_cleans_target(self):
        source = self.root / 'folder'
        source.mkdir()
        self.call(path='folder/ready.txt', offset=0, data='YWJjZGVm')
        self.call(path='folder/ready.txt', finish=True)
        sync = os.fsync
        def fail_private_journal(fd):
            value = os.fstat(fd)
            if stat.S_ISREG(value.st_mode) and value.st_mode & 0o777 == 0o600:
                raise OSError('copy sync failed')
            return sync(fd)
        with patch('titan.files._rename_no_replace', side_effect=OSError(errno.EXDEV, 'cross device')), patch('titan.files.os.fsync', side_effect=fail_private_journal):
            with self.assertRaisesRegex(OSError, 'copy sync failed'):
                operate(self.root, 'move', 'folder', destination='moved')
        self.assertEqual((source / 'ready.txt').read_bytes(), b'abcdef')
        self.assertTrue((source / DIRECTORY / (TOKEN + '.json')).exists())
        self.assertFalse((self.root / 'moved').exists())

    def test_old_completion_markers_are_pruned_without_removing_final_files(self):
        self.chunk(b'abcdef')
        self.call(finish=True)
        private = self.root / DIRECTORY
        self.assertTrue((private / (TOKEN + '.done')).exists())
        os.utime(private / (TOKEN + '.json'), (1, 1))
        with patch.object(file_uploads.time, 'time', return_value=TTL + 2):
            operate(self.root, 'upload', 'next', upload_id='b' * 64, total=0, offset=0, data='')
        self.assertFalse((private / (TOKEN + '.done')).exists())
        self.assertEqual((self.root / 'upload.txt').read_bytes(), b'abcdef')

    def test_backup_archive_excludes_private_fragments_at_any_depth(self):
        nested = self.root / 'nested'
        nested.mkdir()
        (nested / 'ready.txt').write_text('ready')
        self.call(path='nested/upload.txt', offset=0, data='YWJj')
        backup = object.__new__(Backups)
        backup._data_fd = directory_fd
        memory = io.BytesIO()
        with tarfile.open(fileobj=memory, mode='w') as archive:
            backup._add_tree(archive, self.root, 'data', [0, 0])
        memory.seek(0)
        with tarfile.open(fileobj=memory) as archive:
            names = archive.getnames()
            self.assertIn('data/nested/ready.txt', names)
            self.assertFalse(any('.titan-uploads-' in name for name in names))
            self.assertEqual(archive.extractfile('data/nested/ready.txt').read(), b'ready')
        self.assertTrue((nested / DIRECTORY / (TOKEN + '.part')).exists())

    def test_demo_backup_excludes_private_root_and_nested_upload_state(self):
        demo = Demo(self.root / 'demo')
        self.addCleanup(demo._temporary.cleanup)
        demo.call('file', user='titan-files', share='dokumente', action='upload', path='pending.txt', upload_id=TOKEN, total=6, offset=0, data='YWJj')
        demo.call('file', user='titan-files', share='dokumente', action='mkdir', path='nested')
        demo.call('file', user='titan-files', share='dokumente', action='upload', path='nested/pending.txt', upload_id='b' * 64, total=6, offset=0, data='YWJj')
        demo.call('backup_save_settings', target='/mnt/demo', shares=['dokumente'])
        created = demo.call('backup_create')['backup']
        self.assertFalse(any('.titan-uploads-' in name for name in created['digests']))
        self.assertFalse(any(name.endswith('pending.txt') for name in created['digests']))

    def test_old_abandoned_parts_are_reclaimed_on_later_upload(self):
        self.chunk()
        record=self.root/DIRECTORY/(TOKEN+'.json')
        os.utime(record,(1,1))
        with patch.object(file_uploads.time,'time',return_value=TTL+2):
            operate(self.root,'upload','next',upload_id='b'*64,total=0,offset=0,data='')
        self.assertFalse(record.exists())
        self.assertFalse((self.root/DIRECTORY/(TOKEN+'.part')).exists())

    def test_legacy_upload_contract_still_operates_without_atomic_fallback(self):
        self.assertEqual(operate(self.root,'upload','legacy',offset=0,data='YWJj'),{'offset':3})
        self.assertEqual((self.root/'legacy').read_bytes(),b'abc')

    def test_demo_share_and_scoped_system_uploads_use_the_atomic_contract(self):
        demo=Demo(self.root/'demo')
        self.addCleanup(demo._temporary.cleanup)
        result=demo.call('file',user='titan-files',share='dokumente',action='upload',path='new.txt',upload_id=TOKEN,total=3,offset=0,data='YWJj')
        self.assertTrue(result['atomic'])
        demo.call('file',user='titan-files',share='dokumente',action='upload',path='new.txt',upload_id=TOKEN,total=3,finish=True)
        system=self.root/'system';(system/'var/srv/titan').mkdir(parents=True)
        options={'system_path_root':system,'allowed_roots':['var/srv/titan']}
        operate_system(str(system),'upload','var/srv/titan/new.txt',upload_id=TOKEN,total=3,offset=0,data='YWJj',**options)
        self.assertFalse((system/'var/srv/titan/new.txt').exists())
        operate_system(str(system),'upload','var/srv/titan/new.txt',upload_id=TOKEN,total=3,finish=True,**options)
        self.assertEqual((system/'var/srv/titan/new.txt').read_bytes(),b'abc')


class AtomicUploadHTTPTests(HTTPFixture,unittest.TestCase):
    def test_http_passes_atomic_upload_fields_and_rejects_unrelated_options(self):
        body={'share':'dokumente','path':'new.txt','action':'upload','upload_id':TOKEN,'total':3,'offset':0,'data':'YWJj'}
        self.assertEqual(self.request('/api/files',body,csrf='wrong')[0],403)
        self.assertEqual(self.request('/api/files',{**body,'root':'/etc'})[0],400)
        self.agent.call.return_value={'offset':3,'atomic':True,'upload_id':TOKEN}
        self.assertEqual(self.request('/api/files',body)[0],200)
        self.agent.call.assert_called_with('admin_file',**body)
        self.assertEqual(self.request('/api/files',{k:v for k,v in {**body,'cancel':True}.items() if k not in ('offset','data')})[0],200)

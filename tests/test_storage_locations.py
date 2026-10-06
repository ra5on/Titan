"""Named DATA destinations remain pinned when disks disappear or are replaced."""
import contextlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

from titan.core import Error
from titan.host import Host
from titan.locations import locations
from titan.storage_locations import StorageLocations
from titan.system_files import operate_system


class NamedStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.host = Host(self.root/'agent', self.root/'data', self.root/'vms', self.root/'smb.conf')
        self.host.share_root.mkdir(mode=0o755)
        self.host.vm_root.mkdir(mode=0o755)
        self.host.volume_manager.owner_uid = os.geteuid()
        self.names = []
        self.mounts = {}
        self.guid = '12345678'
        self.model = StorageLocations(self.host, self.command)

    def command(self, args, **kwargs):
        if args[:2] == ['zpool', 'list']:
            return '\n'.join(self.names)
        if args[:2] == ['zpool', 'get']:
            return self.guid
        if args[:2] == ['zfs', 'get']:
            name = args[-1]
            for mount in self.mounts.values():
                if mount['source'] == name:
                    return 'mountpoint\t'+mount['target']+'\nmounted\tyes'
            return 'mountpoint\tnone\nmounted\tno'
        if args[0] == 'findmnt':
            target = args[args.index('--target')+1]
            choices = [value for key, value in self.mounts.items() if Path(target).is_relative_to(key)]
            if not choices:
                return json.dumps({'filesystems': []})
            mount = max(choices, key=lambda value: len(Path(value['target']).parts))
            return json.dumps({'filesystems': [mount]})
        raise Error('unsupported fixture command')

    def pool(self, name="photos"):
        path = self.host.share_root/name; path.mkdir(mode=0o755)
        self.names = [name]
        device = path.stat().st_dev
        self.mounts[str(path)] = {'target': str(path), 'source': name, 'fstype': 'zfs', 'options': 'rw',
                                  'maj:min': f'{os.major(device)}:{os.minor(device)}'}
        return path

    def volume(self, mounted=True):
        record = {'name': 'archive', 'filesystem': 'xfs', 'uuid': str(uuid.uuid4()), 'phase': 'mounted'}
        path = self.host.volume_manager.root/'archive';path.mkdir(parents=True, mode=0o755)
        path.parent.chmod(0o755)
        self.host.save('volumes', [record])
        device = path.stat().st_dev
        mounts = [{'target': str(path), 'fstype': 'xfs', 'uuid': record['uuid'], 'maj:min': f'{os.major(device)}:{os.minor(device)}'}] if mounted else []
        return path, patch.object(self.host.volume_manager, 'mounts', return_value=mounts)

    def test_shared_ids_labels_and_programs_do_not_expose_os_root(self):
        self.pool()
        volume, mounted = self.volume()
        with mounted, patch('titan.locations.shutil.which', side_effect=lambda command, **kwargs: '/usr/bin/python3' if command == 'python3' else None):
            result = locations(self.host, self.command)
        self.assertEqual({item['id']:item['label'] for item in result['storage']},
                         {'system':'Interner Speicher', 'volume:archive':'archive', 'pool:photos':'photos'})
        self.assertFalse(any(item['path'] == '/' for item in result['items']))
        self.assertEqual(result['programs'], [{'path':'/usr/bin/python3','label':'Python 3'}])
        self.assertNotIn('backups', result['storage'][0]['capabilities'])
        self.assertIsNone(result['storage'][0]['backup_path'])
        self.assertEqual(next(item for item in result['storage'] if item['id']=='volume:archive')['backup_path'], str(volume/'backups'))

    def test_offline_volume_is_retained_and_never_uses_empty_data_directory(self):
        volume, mounted = self.volume(False)
        (volume/'fallback.txt').write_text('must not be read')
        with mounted:
            item = next(item for item in self.model.inventory()['storage'] if item['id']=='volume:archive')
            self.assertFalse(item['available'])
            self.assertEqual(item['status'], 'offline')
            for call in (lambda: self.model.resolve('volume:archive','apps'), lambda: self.model.validate_path(volume/'fallback.txt')):
                with self.assertRaises(Error): call()
        self.assertEqual((volume/'fallback.txt').read_text(), 'must not be read')
        self.assertFalse((self.host.share_root/'apps').exists())

    def test_imported_pool_guid_is_remembered_and_unmount_remains_blocked(self):
        path = self.pool()
        self.model.resolve('pool:photos')
        self.assertEqual(self.host.load('pools',[]), [{'name':'photos','guid':self.guid}])
        self.names = []; self.mounts = {}; self.model._pool_checked=0
        (path/'fallback.txt').write_text('empty mount fallback')
        item = next(item for item in self.model.inventory()['storage'] if item['id']=='pool:photos')
        self.assertFalse(item['available'])
        with self.assertRaises(Error):self.model.validate_path(path/'fallback.txt')
        self.assertEqual((path/'fallback.txt').read_text(), 'empty mount fallback')

    def test_same_pool_name_with_new_guid_is_refused_without_adoption(self):
        self.pool(); self.model.inventory(); self.guid='87654321'
        with self.assertRaises(Error):self.model.resolve('pool:photos','apps')
        self.assertEqual(self.host.load('pools',[])[0]['guid'], '12345678')

    def test_foreign_or_unmounted_zfs_dataset_is_not_treated_as_pool_data(self):
        path=self.pool()
        for change in ({'source':'other'}, {'fstype':'ext4'}, {'options':'ro'}, {'target':str(path.parent)}):
            with self.subTest(change=change), patch.dict(self.mounts[str(path)],change):
                with self.assertRaises(Error):self.model.resolve('pool:photos')
        with patch.object(self.model,'run',side_effect=lambda args,**kwargs: 'mountpoint\t'+str(path)+'\nmounted\tno' if args[0]=='zfs' else self.command(args)):
            with self.assertRaises(Error):self.model.resolve('pool:photos')

    def test_pool_vm_namespace_is_root_owned_and_rechecked_after_use(self):
        path=self.pool()
        with self.model.fd('pool:photos','vms',create=True) as (fd,record):
            self.assertEqual(Path(record['path']),path/'vms')
            self.assertEqual(record['uuid'],'zfs:'+self.guid)
            self.assertTrue(os.fstat(fd).st_mode & 0o100)
        (path/'vms').chmod(0o777)
        with self.assertRaises(Error):
            with self.model.fd('pool:photos','vms',create=True):pass

    def test_no_symlink_source_target_or_namespace_adoption(self):
        outside=self.root/'os';outside.mkdir();(outside/'config').write_text('untouched')
        (self.host.share_root/'link').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(Error):self.model.validate_path(self.host.share_root/'link/config',write=True)
        (self.host.share_root/'apps').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(Error):
            with self.model.fd('system','apps',create=True):pass
        self.assertEqual((outside/'config').read_text(),'untouched')

    def test_full_storage_still_lists_files_but_new_allocations_fail(self):
        usage=SimpleNamespace(f_bavail=0,f_blocks=1024,f_frsize=4096,f_flag=0)
        with patch('titan.storage_locations.os.fstatvfs',return_value=usage):
            resource=self.model.resolve('system')
            self.assertTrue(resource['available']);self.assertEqual(resource['status'],'full')
            with self.assertRaises(Error) as caught:self.model.resolve('system','apps')
            self.assertEqual(caught.exception.status,409)
        self.assertFalse((self.host.share_root/'apps').exists())

    def test_missing_default_is_reported_without_choosing_internal_storage(self):
        self.host.save('storage-preferences',{'default_storage':'volume:removed'})
        result=self.model.inventory()
        self.assertEqual(result['default_storage'],'volume:removed')
        self.assertTrue(result['warnings'])
        with self.assertRaises(Error):self.model.resolve(result['default_storage'],'apps')

    def test_internal_vm_path_is_preserved_and_os_paths_are_refused(self):
        self.assertEqual(self.model.resolve('system','vms')['path'],str(self.host.vm_root))
        for path in ('/etc/passwd','/usr/bin/python3','/proc/cpuinfo','/sys','/var/lib/titan-system/persistent/etc'):
            with self.subTest(path=path),self.assertRaises(Error):self.model.validate_path(path)
        with self.assertRaises(Error):self.model.resolve('system','backups')

    def test_production_data_mount_missing_fails_before_os_fallback(self):
        with patch.object(StorageLocations,'private_fixture',property(lambda owner:False)), patch.object(self.model,'run',return_value=json.dumps({'filesystems':[{'target':'/','fstype':'ext4','maj:min':'8:3','options':'rw'}]})):
            with self.assertRaises(Error):self.model.resolve('system','apps')
        self.assertFalse((self.host.share_root/'apps').exists())

    def test_worker_data_scope_rejects_os_even_with_root_descriptor(self):
        data=self.root/'var/srv/titan';data.mkdir(parents=True)
        (self.root/'etc').mkdir();(self.root/'etc/config').write_text('untouched')
        descriptor=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY)
        try:
            for action in ('list','read','write','delete'):
                with self.subTest(action=action),self.assertRaises(Error):
                    operate_system(descriptor,action,'etc/config',system_path_root=str(self.root),canonicalized=True,
                                   allowed_roots=['var/srv/titan'],data='changed',confirmation_path='/etc/config')
        finally:os.close(descriptor)
        self.assertEqual((self.root/'etc/config').read_text(),'untouched')

    def external(self):
        root=self.root/'external';root.mkdir(mode=0o755)
        target=root/'my-backups';target.mkdir(mode=0o755)
        device=target.stat().st_dev
        self.mounts[str(root)]={'target':str(root),'source':'/dev/mock','fstype':'ext4',
                               'uuid':'87c014c9-2471-4acd-861f-2ae6c69255e2','options':'rw',
                               'maj:min':f'{os.major(device)}:{os.minor(device)}'}
        self.host.save('backup-settings',{'target':str(target)})
        stack=contextlib.ExitStack()
        stack.enter_context(patch('titan.storage_locations.EXTERNAL_ROOTS',(root,)))
        validator=Mock();validator.validate_target.side_effect=lambda value:Path(value)
        stack.enter_context(patch('titan.storage_locations.Backups',return_value=validator))
        return root,target,stack

    def test_only_configured_legacy_external_backup_is_registered_and_pinned(self):
        root,target,context=self.external()
        with context:
            inventory=self.model.inventory()
            external=next(item for item in inventory['storage'] if item['kind']=='external')
            self.assertEqual(external['capabilities'],['backups','files'])
            self.assertEqual(external['backup_path'],str(target))
            self.assertEqual(self.model.validate_path(target)['id'],external['id'])
            registered=self.host.load('external-storage',[])
            self.assertEqual(registered[0]['uuid'],self.mounts[str(root)]['uuid'])
            with self.assertRaises(Error):self.model.resolve(external['id'],'apps')
            self.host.save('backup-settings',{'target':''})
            self.assertFalse(any(item['kind']=='external' for item in self.model.inventory()['storage']))
            with self.assertRaises(Error):self.model.validate_path(target)

    def test_external_backup_replacement_uuid_or_readonly_mount_is_not_adopted(self):
        root,target,context=self.external()
        with context:
            self.model.inventory()
            previous=self.host.load('external-storage',[])
            self.mounts[str(root)]['uuid']='ae107596-54b7-42c4-85ba-c37d9f90e866'
            with self.assertRaises(Error):self.model.validate_path(target)
            inventory=self.model.inventory()
            external=next(item for item in inventory['storage'] if item['kind']=='external')
            self.assertFalse(external['available'])
            self.assertFalse(external['backup_eligible'])
            self.assertEqual(self.host.load('external-storage',[]),previous)
            self.mounts[str(root)]['uuid']=previous[0]['uuid']
            self.mounts[str(root)]['options']='ro'
            with self.assertRaises(Error):self.model.validate_path(target)

    def test_external_missing_uuid_and_symlink_are_never_registered(self):
        root,target,context=self.external()
        with context:
            self.mounts[str(root)].pop('uuid')
            with self.assertRaises(Error):self.model.validate_path(target)
            self.assertFalse(self.host.load('external-storage',[]))
            self.mounts[str(root)]['uuid']='87c014c9-2471-4acd-861f-2ae6c69255e2'
            (target/'link').symlink_to(self.host.share_root,target_is_directory=True)
            with self.assertRaises(Error):self.model.validate_path(target/'link')

    def test_reserved_legacy_pool_is_files_only_and_blocks_internal_allocation(self):
        path = self.pool('apps')
        marker = path / 'retained.txt'; marker.write_text('existing data')
        record = next(item for item in self.model.inventory()['storage'] if item['id'] == 'pool:apps')
        self.assertEqual(record['capabilities'], ['files'])
        self.assertEqual(self.host.load('pools', []), [{'name': 'apps', 'guid': self.guid}])
        self.assertEqual(self.model.validate_path(marker)['id'], 'pool:apps')
        for storage in ('system', 'pool:apps'):
            with self.subTest(storage=storage), self.assertRaises(Error):
                with self.model.fd(storage, 'apps', create=True): pass
        self.names = []; self.mounts = {}; self.model._pool_checked = 0
        with self.assertRaises(Error): self.model.validate_path(marker)
        with self.assertRaises(Error):
            with self.model.fd('system', 'apps', create=True): pass
        self.assertEqual(marker.read_text(), 'existing data')
        self.assertFalse((path / 'apps').exists())

    def test_worker_accepts_more_than_eight_bounded_named_roots(self):
        prefixes = ['data-' + str(index) for index in range(12)]
        for name in prefixes: (self.root / name).mkdir()
        (self.root / prefixes[-1] / 'file.txt').write_text('allowed')
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            result = operate_system(fd, 'list', prefixes[-1], system_path_root=str(self.root),
                                    canonicalized=True, allowed_roots=prefixes)
            self.assertEqual(result['entries'][0]['name'], 'file.txt')
            for roots in (prefixes + [''], prefixes + ['.'], ['x'] * 261):
                with self.subTest(roots=roots[-1]), self.assertRaises(Error):
                    operate_system(fd, 'list', prefixes[-1], system_path_root=str(self.root),
                                   canonicalized=True, allowed_roots=roots)
        finally: os.close(fd)

    def test_scoped_worker_listing_does_not_follow_os_symlink_metadata(self):
        data = self.host.share_root
        os_dir = self.root / 'etc'; os_dir.mkdir()
        private = os_dir / 'private'; private.write_text('hidden' * 100)
        link = data / 'shortcut'; link.symlink_to('../etc/private')
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            result = operate_system(fd, 'list', 'data', system_path_root=str(self.root),
                                    canonicalized=True, allowed_roots=['data'])
            entry = result['entries'][0]
            self.assertFalse(entry['readable']); self.assertFalse(entry['editable'])
            self.assertEqual(entry['size'], link.lstat().st_size)
            self.assertNotIn('target', entry)
            with self.assertRaises(Error):
                operate_system(fd, 'read', 'data/shortcut', system_path_root=str(self.root), allowed_roots=['data'])
        finally: os.close(fd)
        self.assertEqual(private.read_text(), 'hidden' * 100)

    def test_purpose_namespaces_are_protected_but_contained_files_remain_mutable(self):
        self.host.system_root = self.root
        self.host._storage_locations = self.model
        apps = self.host.share_root / 'apps'; apps.mkdir(mode=0o755)
        file = apps / 'settings.txt'; file.write_text('editable data')
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        prefix = str(self.host.share_root.relative_to(self.root))
        protected = self.model.protected_paths()
        try:
            for action in ('delete', 'rename', 'move'):
                with self.subTest(action=action), self.assertRaises(Error):
                    self.host.op_system_file(action, prefix + '/apps', confirmation_path='/' + prefix + '/apps') if action == 'delete' else self.host.op_system_file(action, prefix + '/apps', destination=prefix + '/new')
            listing = operate_system(fd, 'list', prefix, system_path_root=str(self.root), canonicalized=True,
                                     allowed_roots=[prefix], protected_paths=protected)
            self.assertFalse(next(item for item in listing['entries'] if item['name'] == 'apps')['mutable'])
            listing = operate_system(fd, 'list', prefix + '/apps', system_path_root=str(self.root), canonicalized=True,
                                     allowed_roots=[prefix], protected_paths=protected)
            self.assertTrue(listing['entries'][0]['editable'])
            self.assertTrue(listing['entries'][0]['mutable'])
        finally: os.close(fd)
        self.assertEqual(file.read_text(), 'editable data')

    def test_backup_eligibility_excludes_app_data_and_config_filesystem_without_shares(self):
        self.host.save('shares', [])
        record = {'id': 'pool:archive', 'kind': 'pool', 'status': 'ready',
                  'capabilities': ['backups', 'files'], 'device': 987, 'uuid': 'zfs:12345'}
        descriptors = {}
        def opened(path):
            fd = len(descriptors) + 100
            descriptors[fd] = Path(path)
            return contextlib.nullcontext(fd)
        app_path = self.host.share_root / 'pool-with-apps' / 'app'
        def fstat(fd):
            return SimpleNamespace(st_dev=987 if descriptors[fd] == app_path else 1)
        with patch.object(self.model, 'backup_pool_conflict', return_value=False), patch('titan.storage_locations.directory_fd', side_effect=opened), patch('titan.storage_locations.os.fstat', side_effect=fstat):
            self.assertTrue(self.model.backup_eligible(record))
            for field in ('data', 'config_path'):
                with self.subTest(field=field):
                    self.host.save('apps', [{'id': 'photos', field: str(app_path)}])
                    self.assertFalse(self.model.backup_eligible(record))

    def test_zfs_backup_excludes_same_pool_across_distinct_dataset_devices(self):
        target = {'id':'pool:archive','kind':'pool','status':'ready','uuid':'zfs:12345',
                  'capabilities':['backups','files'],'device':987}
        source = self.host.share_root / 'archive' / 'app-dataset'
        self.host.save('apps', [{'id':'photos','data':str(source)}])
        def resolve(path, **kwargs):
            if Path(path)==source:
                return {'id':'pool:archive','kind':'pool','uuid':'zfs:12345','device':654}
            return {'id':'system','kind':'internal','device':1}
        with patch.object(self.model,'validate_path',side_effect=resolve), \
                patch('titan.storage_locations.directory_fd',return_value=contextlib.nullcontext(42)), \
                patch('titan.storage_locations.os.fstat',return_value=SimpleNamespace(st_dev=1)):
            self.assertTrue(self.model.backup_pool_conflict(target))
            self.assertFalse(self.model.backup_eligible(target))
            with patch.object(self.model,'validate_path',side_effect=lambda path,**kwargs:
                    {**resolve(path),'uuid':'zfs:67890'} if Path(path)==source else resolve(path)):
                self.assertFalse(self.model.backup_pool_conflict(target))
                self.assertTrue(self.model.backup_eligible(target))

    def test_managed_backup_save_rejects_shared_pool_before_creating_namespace(self):
        from titan.backups import Backups
        pool = self.host.share_root / 'archive'; pool.mkdir(mode=0o755)
        source = pool / 'app-dataset'; source.mkdir(mode=0o755)
        target = pool / 'backups'
        self.host.save('apps', [{'id':'photos','data':str(source)}])
        self.host._storage_locations=self.model
        record={'id':'pool:archive','kind':'pool','uuid':'zfs:12345','device':987}
        def resolve(path, **kwargs):
            if Path(path) in (source,target): return {**record,'device':654 if Path(path)==source else 987}
            return {'id':'system','kind':'internal','device':1}
        with patch.object(self.model,'validate_path',side_effect=resolve), \
                patch.object(self.model,'resolve',return_value={'path':str(target)}), \
                patch.object(self.model,'fd') as created, \
                patch('titan.storage_locations.directory_fd',return_value=contextlib.nullcontext(42)), \
                patch('titan.storage_locations.os.fstat',return_value=SimpleNamespace(st_dev=1)):
            with self.assertRaisesRegex(Error,'ZFS-Pool enthält Quelldaten'):
                Backups(self.host,self.command).validate_target(target,create=True)
            created.assert_not_called()
        self.assertFalse(target.exists())

    def test_mount_loss_before_namespace_creation_never_mutates_fallback(self):
        record = self.model.resolve('system', 'apps')
        record['device'] += 1
        with patch.object(self.model, 'resolve', return_value=record), patch('titan.storage_locations.os.mkdir') as mkdir:
            with self.assertRaises(Error) as failure:
                with self.model.fd('system', 'apps', create=True): pass
            self.assertEqual(failure.exception.status, 503)
            mkdir.assert_not_called()
        self.assertFalse((self.host.share_root / 'apps').exists())

    def test_pool_mount_changes_during_retained_fd_operation_raise(self):
        self.pool()
        with self.assertRaises(Error):
            with self.model.fd('pool:photos','vms',create=True):
                self.guid='87654321'
        self.assertEqual(self.host.load('pools',[])[0]['guid'],'12345678')


if __name__=='__main__':unittest.main()

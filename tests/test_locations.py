"""Legacy location pickers use the same named resources, never the OS root."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from titan.core import Error
from titan.host import Host
from titan.locations import locations


class LocationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.host=Host(self.root/'agent',self.root/'data',self.root/'vms',self.root/'smb.conf')
        self.host.share_root.mkdir(mode=0o755);self.host.vm_root.mkdir(mode=0o755)

    def collect(self):
        with patch('titan.locations.shutil.which',side_effect=lambda command,**kwargs:'/usr/bin/python3' if command=='python3' else None):
            return locations(self.host,lambda args: (_ for _ in ()).throw(Error('ZFS absent')))

    def test_internal_named_data_and_safe_programs_replace_os_root(self):
        result=self.collect()
        self.assertEqual(result['storage'][0]['label'],'Interner Speicher')
        self.assertEqual(result['items'][0]['path'],str(self.host.share_root))
        self.assertFalse(result['items'][0]['backup_eligible'])
        self.assertFalse(any(item['path']=='/' for item in result['items']))
        self.assertEqual(result['programs'],[{'path':'/usr/bin/python3','label':'Python 3'}])

    def test_unregistered_external_mounts_are_not_implicitly_adopted(self):
        result=self.collect()
        self.assertEqual([item['id'] for item in result['storage']],['system'])
        self.assertFalse(any(item['backup_eligible'] for item in result['items']))

    def test_share_paths_are_data_scoped_and_duplicate_paths_are_not_repeated(self):
        folder=self.host.share_root/'files';folder.mkdir(mode=0o755)
        shares=[{'name':'Fotos','path':str(folder)},{'name':'Alias','path':str(folder)},
                {'name':'OS','path':'/etc'},{'name':'Blocked','path':str(folder),'blocked':True}]
        with patch.object(self.host,'op_shares',return_value=shares):result=self.collect()
        paths=[item['path'] for item in result['items']]
        self.assertEqual(paths.count(str(folder)),1)
        self.assertNotIn('/etc',paths)
        self.assertEqual(next(item['id'] for item in result['items'] if item['path']==str(folder)),'share:Fotos')

    def test_missing_data_namespace_stays_disabled_in_catalog(self):
        self.host.share_root.rmdir()
        result=self.collect()
        self.assertFalse(result['storage'][0]['available'])
        self.assertEqual(result['storage'][0]['status'],'offline')
        self.assertEqual(result['items'][0]['path'],str(self.host.share_root))


if __name__=='__main__':unittest.main()

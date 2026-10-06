import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from titan.core import Error
from titan.backup_authorization import authorize, host_call, safe_listing


class BackupAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.shares=[{'name':'public','readers':['reader'],'writers':['writer']},{'name':'private','readers':[],'writers':['owner']},{'name':'destination','readers':[],'writers':['reader']}]
        self.public={'id':'public-backup','type':'shares','shares':['public'],'include_config':True}
        self.private={'id':'private-backup','type':'shares','shares':['private'],'include_config':False}
        self.mixed={'id':'mixed-backup','type':'shares','shares':['public','private'],'include_config':True}

    def test_listing_hides_foreign_and_mixed_backups_and_configuration_flags(self):
        records=safe_listing([self.public,self.private,self.mixed,{'id':'config','type':'shares','shares':[],'include_config':True}],{'public'})
        self.assertEqual([record['id'] for record in records],['public-backup'])
        self.assertFalse(records[0]['include_config']);self.assertFalse(records[0]['configuration_available'])
        self.assertTrue(self.public['include_config'],'Sanitizing metadata must not mutate the authoritative manifest.')

    def test_create_requires_explicit_own_sources_and_no_config(self):
        authorize('backup_create',{'shares':['public'],'include_config':False},'reader',self.shares)
        for args in ({'shares':['private'],'include_config':False},{'shares':['public'],'include_config':True},{'shares':['public']},{'include_config':False}):
            with self.assertRaises(Error):authorize('backup_create',args,'reader',self.shares)

    def test_restore_requires_readable_sources_and_writable_destination(self):
        valid={'backup':'public-backup','paths':['public/folder/file.txt'],'share':'destination','name':'restored'}
        authorize('backup_restore_selection',valid,'reader',self.shares,self.public)
        for manifest,args in [(self.private,valid),(self.mixed,valid),(self.public,{**valid,'share':'public'}),(self.public,{**valid,'paths':['private/secret']})]:
            with self.assertRaises(Error):authorize('backup_restore_selection',args,'reader',self.shares,manifest)

    def test_browse_rejects_other_source_or_absolute_traversal_path(self):
        for path in ('private','/public/file','public/../private/file'):
            with self.assertRaises(Error):authorize('backup_browse',{'backup':'public-backup','path':path},'reader',self.shares,self.public)

    def test_root_boundary_rechecks_current_acl_before_actual_restore(self):
        import threading
        host=SimpleNamespace(account_lock=threading.RLock(),require_active_account=Mock(),op_shares=Mock(return_value=copy.deepcopy(self.shares)),backups=Mock())
        host.backups.manifest.return_value=self.public
        args={'backup':'public-backup','paths':['public/a'],'share':'destination','name':'restored'}
        host_call(host,'backup_restore_selection','reader',args)
        host.backups.restore_selection.assert_called_once_with(**args)
        host.backups.restore_selection.reset_mock();host.op_shares.return_value[2]['writers']=[]
        with self.assertRaises(Error):host_call(host,'backup_restore_selection','reader',args)
        host.backups.restore_selection.assert_not_called()

    def test_root_boundary_rejects_blocked_account_before_archive_read(self):
        import threading
        host=SimpleNamespace(account_lock=threading.RLock(),require_active_account=Mock(side_effect=Error('Blocked',403)),op_shares=Mock(),backups=Mock())
        with self.assertRaises(Error):host_call(host,'backup_browse','reader',{'backup':'public-backup'})
        host.backups.manifest.assert_not_called()

if __name__=='__main__':unittest.main()

import base64
import copy
import hashlib
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from titan.core import Error, Store
from titan.identity import Identity, effective_application, effective_share, empty_policy, permissions, require_application, validate_policy
from titan.identity_host import IdentityHostMixin
from titan.security import Security, totp
from titan.config_restore import database_import, validate_identity_config


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(self.temporary.name)
        self.store.create_user('owner', 'owner-password-long', 'admin', 'owner')
        self.store.create_user('reader', 'reader-password-long', 'user', 'reader')
        self.security = Security(self.store)

    def tearDown(self): self.temporary.cleanup()

    def enroll(self):
        setup = self.security.begin('owner', 'owner-password-long')
        counter = int(time.time() // 30)
        result = self.security.confirm('owner', 'owner-password-long', totp(setup['secret'], counter))
        return setup, counter, result

    def test_rfc6238_sha1_vectors(self):
        secret = base64.b32encode(b'12345678901234567890').decode()
        for timestamp, expected in [(59,'94287082'), (1111111109,'07081804'), (1111111111,'14050471'), (1234567890,'89005924'), (2000000000,'69279037'), (20000000000,'65353130')]:
            self.assertEqual(totp(secret, timestamp//30, digits=8), expected)

    def test_enrollment_needs_password_and_valid_current_code(self):
        with self.assertRaises(Error): self.security.begin('owner', 'wrong-password-long')
        setup = self.security.begin('owner', 'owner-password-long')
        with self.assertRaises(Error): self.security.confirm('owner', 'owner-password-long', 'not-a-code')
        self.assertFalse(self.security.overview('owner')['two_factor'])
        self.security.confirm('owner', 'owner-password-long', totp(setup['secret'], int(time.time()//30)))
        self.assertTrue(self.security.overview('owner')['two_factor'])

    def test_login_requires_second_factor_and_rejects_replay(self):
        setup, counter, _ = self.enroll()
        with self.assertRaises(Error): self.store.login('owner', 'owner-password-long')
        with patch('titan.security.time.time', return_value=(counter+1)*30+1):
            code = totp(setup['secret'], counter+1)
            token, _ = self.store.login('owner', 'owner-password-long', otp=code)
            self.assertIsNotNone(self.store.session(token))
            with self.assertRaises(Error): self.store.login('owner', 'owner-password-long', otp=code)

    def test_recovery_code_is_consumed_once_and_only_stored_as_hash(self):
        _, _, result = self.enroll()
        code = result['recovery_codes'][0]
        token, _ = self.store.login('owner', 'owner-password-long', otp=code.lower())
        self.assertIsNotNone(self.store.session(token))
        with self.assertRaises(Error): self.store.login('owner', 'owner-password-long', otp=code)
        self.assertEqual(self.security.overview('owner')['recovery_remaining'],9)
        self.assertNotIn(code, self.store.path.read_bytes().decode('latin1'))

    def test_failed_password_does_not_consume_recovery(self):
        _, _, result = self.enroll()
        code = result['recovery_codes'][0]
        with self.assertRaises(Error): self.store.login('owner', 'wrong-password-long', otp=code)
        self.store.login('owner', 'owner-password-long', otp=code)

    def test_non_ascii_otp_rejected_without_crash(self):
        self.enroll()
        with self.assertRaises(Error) as failure: self.store.login('owner', 'owner-password-long', otp='１２３４５６')
        self.assertEqual(failure.exception.status,401)

    def test_non_ascii_enrollment_code_fails_without_activating_factor(self):
        self.security.begin('owner','owner-password-long')
        with self.assertRaises(Error):self.security.confirm('owner','owner-password-long','１２３４５６')
        self.assertFalse(self.security.overview('owner')['two_factor'])

    def test_login_history_contains_failed_attempts_but_no_passwords(self):
        with self.assertRaises(Error): self.store.login('owner','wrong-password-long',address='192.0.2.1',user_agent='Browser')
        self.store.login('owner','owner-password-long',address='192.0.2.2',user_agent='Mobile')
        events = self.security.overview('owner')['login_events']
        self.assertEqual([item['success'] for item in events],[1,0])
        self.assertEqual(events[0]['address'],'192.0.2.2')
        self.assertNotIn('password', str(events))

    def test_session_listing_and_revocation_scopes_normal_user(self):
        owner, _ = self.store.login('owner','owner-password-long')
        reader, _ = self.store.login('reader','reader-password-long')
        session = self.security.overview('owner',owner)['sessions'][0]
        self.assertTrue(session['current'])
        self.assertEqual(len(session['id']),32)
        with self.assertRaises(Error): self.security.revoke('reader',session['id'])
        self.security.revoke('owner',session['id'])
        self.assertIsNone(self.store.session(owner))
        self.assertIsNotNone(self.store.session(reader))

    def test_confirm_keeps_current_session_for_saving_recovery_codes(self):
        current, _ = self.store.login('owner','owner-password-long')
        other, _ = self.store.login('owner','owner-password-long')
        setup = self.security.begin('owner','owner-password-long')
        self.security.confirm('owner','owner-password-long',totp(setup['secret'],int(time.time()//30)),current_token=current)
        self.assertIsNotNone(self.store.session(current))
        self.assertIsNone(self.store.session(other))

    def test_expired_pending_enrollment_cannot_activate(self):
        setup=self.security.begin('owner','owner-password-long')
        with self.store.connection() as db: db.execute('UPDATE second_factors SET pending_expires=0')
        with self.assertRaises(Error): self.security.confirm('owner','owner-password-long',totp(setup['secret'],int(time.time()//30)))

    def test_security_response_does_not_expose_secret_or_recovery_hashes(self):
        setup, _, result=self.enroll()
        overview=str(self.security.overview('owner'))
        self.assertNotIn(setup['secret'],overview)
        self.assertNotIn(result['recovery_codes'][0],overview)

    def test_regenerate_recovery_invalidates_old_codes(self):
        _, _, result=self.enroll()
        fresh=self.security.recoveries('owner','owner-password-long',result['recovery_codes'][0])
        with self.assertRaises(Error): self.store.login('owner','owner-password-long',otp=result['recovery_codes'][1])
        self.store.login('owner','owner-password-long',otp=fresh['recovery_codes'][0])

    def test_old_configuration_import_clears_obsolete_factors_and_sessions(self):
        self.enroll()
        record=self.store.user_record('owner')
        database_import(self.store.path,{'users':[record],'config':{}})
        self.store.login('owner','owner-password-long')
        self.assertFalse(self.security.overview('owner')['two_factor'])


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.store=Store(self.temporary.name)
        self.store.create_user('admin','administrator-password','admin','admin')
        self.store.create_user('reader','reader-password-long','user','reader')
        self.users=self.store.users()
        self.shares=[{'name':'photos','path':'/srv/titan/shares/photos','readers':[],'writers':['titan-files']}]

    def tearDown(self): self.temporary.cleanup()

    def policy(self):
        return {'schema':1,'groups':[{'name':'family','description':'Familie','members':['reader'],'applications':{'apps':True},'shares':{'photos':'write'}}],'users':{}}

    def test_defaults_preserve_existing_regular_user_access(self):
        record=self.store.user_record('reader')
        rights=permissions(self.store,record)
        self.assertTrue(rights['files']['allowed'])
        self.assertFalse(rights['apps']['allowed'])
        with self.assertRaises(Error): require_application(self.store,record,'vms')

    def test_group_grant_and_explicit_user_denial_are_enforced(self):
        policy=validate_policy(self.policy(),self.users,self.shares)
        self.store.set_config('identity',policy)
        require_application(self.store,self.store.user_record('reader'),'apps')
        policy['users']['reader']={'applications':{'apps':False},'shares':{}}
        self.store.set_config('identity',policy)
        with self.assertRaises(Error): require_application(self.store,self.store.user_record('reader'),'apps')

    def test_group_denial_wins_and_user_override_is_explained(self):
        policy=self.policy()
        policy['groups'].append({'name':'guests','members':['reader'],'applications':{'apps':False},'shares':{'photos':'none'}})
        self.assertFalse(effective_application(policy,'reader','apps')['allowed'])
        self.assertEqual(effective_share(policy,'reader',self.shares[0])['permission'],'none')
        policy['users']['reader']={'applications':{'apps':True},'shares':{'photos':'read'}}
        self.assertFalse(effective_application(policy,'reader','apps')['inherited'])
        self.assertEqual(effective_share(policy,'reader',self.shares[0])['permission'],'read')

    def test_admin_bypass_does_not_change_group_or_smb_account(self):
        self.store.set_config('identity',self.policy())
        self.assertTrue(all(item['allowed'] for item in permissions(self.store,self.store.user_record('admin')).values()))
        self.assertEqual(self.store.user_record('admin')['system_user'],'admin')

    def test_invalid_members_or_permissions_are_rejected(self):
        for mutation in [lambda p:p['groups'][0]['members'].append('stranger'),lambda p:p['groups'][0]['applications'].update({'files':'yes'}),lambda p:p['groups'][0]['shares'].update({'photos':'root'}),lambda p:p['groups'].append(copy.deepcopy(p['groups'][0]))]:
            policy=self.policy();mutation(policy)
            with self.assertRaises(Error): validate_policy(policy,self.users,self.shares)

    def test_queued_permissions_recheck_current_disabled_account(self):
        record=self.store.user_record('reader')
        self.store.update_user('reader',enabled=False)
        with self.assertRaises(Error): require_application(self.store,record,'files')

    def test_host_failure_does_not_commit_web_application_grant(self):
        agent=Mock();agent.call.side_effect=lambda operation,**kwargs:self.shares if operation=='shares' else (_ for _ in ()).throw(Error('ACL error'))
        with self.assertRaises(Error): Identity(self.store,agent).apply('admin',self.policy())
        self.assertFalse(permissions(self.store,self.store.user_record('reader'))['apps']['allowed'])

    def test_stale_editor_cannot_overwrite_newer_group_permissions(self):
        from titan.identity import policy_revision
        stale=policy_revision(empty_policy());self.store.set_config('identity',self.policy())
        agent=Mock()
        with self.assertRaises(Error) as failure:Identity(self.store,agent).apply('admin',{**empty_policy(),'expected_revision':stale})
        self.assertEqual(failure.exception.status,409);agent.call.assert_not_called()
        self.assertEqual(self.store.config('identity'),self.policy())


class FakeHost(IdentityHostMixin):
    def __init__(self):
        import threading
        self.account_lock=threading.RLock();self.records={};self.changed=[]
        self.records['shares']=[{'name':'photos','path':'/srv/titan/shares/photos','readers':[],'writers':['titan-files']}]
    def load(self,key,default): return copy.deepcopy(self.records.get(key,default))
    def save(self,key,value): self.records[key]=copy.deepcopy(value)
    def op_shares(self): return self.load('shares',[])
    def managed_account(self,name):
        if name not in ('alice','bob'): raise Error('Unknown')
        return {'name':name,'enabled':True},SimpleNamespace(pw_uid=1001 if name=='alice' else 1002)
    def _update_share_rights(self,name,readers,writers):
        self.changed.append((name,readers,writers))
        self.records['shares']=[{**share,'readers':list(readers),'writers':list(writers)} if share['name']==name else share for share in self.op_shares()]


class HostIdentityTests(unittest.TestCase):
    def test_group_removal_revokes_materialized_access_and_preserves_service(self):
        host=FakeHost();users=[{'name':'alice','system_user':'alice'},{'name':'bob','system_user':'bob'}]
        policy={'schema':1,'groups':[{'name':'family','members':['alice'],'applications':{},'shares':{'photos':'write'}}],'users':{}}
        host.op_identity_apply(policy,users)
        self.assertIn('alice',host.op_shares()[0]['writers'])
        policy['groups'][0]['members']=[];host.op_identity_apply(policy,users)
        self.assertEqual(host.op_shares()[0]['writers'],['titan-files'])

    def test_legacy_service_identity_never_receives_personal_group_grants(self):
        host=FakeHost()
        policy={'schema':1,'groups':[{'name':'family','members':['legacy'],'shares':{'photos':'write'}}],'users':{}}
        with self.assertRaises(Error): host.op_identity_apply(policy,[{'name':'legacy','system_user':'titan-files'}])
        self.assertFalse(host.changed)

    def test_explicit_denial_overrides_group_and_survives_membership_update(self):
        host=FakeHost();users=[{'name':'alice','system_user':'alice'}]
        policy={'schema':1,'groups':[{'name':'family','members':['alice'],'shares':{'photos':'write'}}],'users':{'alice':{'applications':{},'shares':{'photos':'none'}}}}
        host.op_identity_apply(policy,users)
        self.assertNotIn('alice',host.op_shares()[0]['writers'])

    def test_personal_home_is_not_granted_to_other_group_members(self):
        host=FakeHost();host.records['identity-homes']={'alice':{'share':'photos','path':'/srv/titan/shares/photos','user':'alice'}}
        policy={'schema':1,'groups':[{'name':'family','members':['alice','bob'],'shares':{}}],'users':{}}
        host.op_identity_apply(policy,[{'name':'alice','system_user':'alice'},{'name':'bob','system_user':'bob'}])
        self.assertEqual(host.op_shares()[0]['writers'],['alice'])

    def test_quota_rejects_non_supported_target_before_zfs_set(self):
        host=FakeHost();host.command=Mock()
        with patch('titan.identity_host.shutil.which',return_value=None):
            with self.assertRaises(Error): host.op_user_quota('alice','arbitrary/dataset',100)
        host.command.assert_not_called()

    def test_actual_zfs_property_is_set_and_read_back(self):
        host=FakeHost();host.records['shares'][0]['dataset']='tank/photos'
        def command(args):
            if args[:2]==['zfs','set']: return ''
            return 'filesystem\n' if 'type' in args else '512\n1024\n'
        host.command=Mock(side_effect=command)
        with patch('titan.identity_host.shutil.which',return_value='/usr/sbin/zfs'):
            result=host.op_user_quota('alice','tank/photos',1024)
        self.assertEqual(result['quota']['limit_bytes'],1024)
        host.command.assert_any_call(['zfs','set','userquota@1001=1024','tank/photos'])

    def test_account_cleanup_resolves_web_alias_and_removes_only_named_access(self):
        host=FakeHost();host.records['identity-users']=[{'name':'web-alice','system_user':'alice'}]
        host.records['identity']={'schema':1,'groups':[{'name':'family','members':['web-alice'],'applications':{},'shares':{'photos':'write'}}],'users':{'web-alice':{'applications':{'apps':True},'shares':{'photos':'write'}}}}
        host.records['identity-baseline']={'photos':{'name':'photos','readers':['alice','bob'],'writers':['titan-files']}}
        host.records['identity-homes']={'alice':{'share':'personal','path':'/test','user':'alice'}}
        host.identity_remove_account('alice')
        self.assertEqual(host.records['identity']['groups'][0]['members'],[]);self.assertEqual(host.records['identity']['users'],{})
        self.assertEqual(host.records['identity-baseline']['photos']['readers'],['bob']);self.assertEqual(host.records['identity-homes'],{})
        self.assertEqual(host.records['identity-users'],[])

    def test_share_cleanup_removes_stale_group_and_explicit_references(self):
        host=FakeHost();host.records['identity']={'schema':1,'groups':[{'name':'family','members':['alice'],'applications':{},'shares':{'photos':'write'}}],'users':{'alice':{'applications':{'apps':True},'shares':{'photos':'read'}}}}
        host.records['identity-baseline']={'photos':{'name':'photos','readers':[],'writers':['alice']}}
        host.records['shares']=[];host.identity_remove_share('photos')
        self.assertEqual(host.records['identity']['groups'][0]['shares'],{});self.assertEqual(host.records['identity']['users']['alice']['shares'],{})
        self.assertTrue(host.records['identity']['users']['alice']['applications']['apps']);self.assertEqual(host.records['identity-baseline'],{})

    def test_restore_resets_newer_quota_even_if_its_share_was_removed(self):
        from titan.config_restore import quota_properties
        host=FakeHost();host.records['shares']=[];properties={'tank/retained':4096,'tank/photos':2048}
        def command(arguments):
            target=arguments[-1]
            if arguments[1]=='set':
                value=arguments[2].split('=')[1];properties[target]=0 if value=='none' else int(value);return ''
            return 'filesystem' if arguments[-2]=='type' else str(properties[target])
        host.command=Mock(side_effect=command)
        quota_properties(host,{'alice':{'tank/photos':1024}},{'alice':{'tank/photos':2048,'tank/retained':4096}})
        self.assertEqual(properties,{'tank/retained':0,'tank/photos':1024})
        self.assertEqual(host.records['identity-quotas'],{'alice':{'tank/photos':1024}})
        with self.assertRaises(Error):host._restore_user_quota('alice','foreign/dataset',100,{'tank/photos'})


if __name__=='__main__': unittest.main()

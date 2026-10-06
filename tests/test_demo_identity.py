import copy
from pathlib import Path
import tempfile
import unittest
from titan.core import Error
from titan.demo import Demo
from titan.identity import empty_policy


class DemoIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.demo=Demo(Path(self.temporary.name)/'files')
        self.users=[{'name':'first','system_user':'patrick'},{'name':'second','system_user':'familie'}]

    def tearDown(self):
        self.demo._temporary.cleanup();self.temporary.cleanup()

    def policy(self):
        return {'schema':1,'groups':[{'name':'friends','members':['second'],'shares':{'dokumente':'write'}}],'users':{}}

    def test_group_revocation_preserves_original_acl_and_service_identity(self):
        policy=self.policy();self.demo.call('identity_apply',policy=policy,users=self.users)
        self.assertIn('familie',self.demo.shares[0]['writers'])
        policy['groups'][0]['members']=[]
        self.demo.call('identity_apply',policy=policy,users=self.users)
        self.assertEqual(self.demo.shares[0]['readers'],['familie'])
        self.assertEqual(self.demo.shares[0]['writers'],['patrick','titan-files'])

    def test_personal_folder_created_only_within_isolated_demo(self):
        result=self.demo.call('identity_home',name='familie')
        home=Path(result['path']);self.assertTrue(home.is_relative_to(self.demo._private));self.assertTrue(home.is_dir())
        self.assertEqual(self.demo.call('identity_home',name='familie')['share'],result['share'])
        share=next(item for item in self.demo.shares if item['name']==result['share'])
        self.assertEqual(share['writers'],['familie']);self.assertEqual(share['readers'],[])
        before=copy.deepcopy(share)
        with self.assertRaises(Error):self.demo.call('share_update',name=result['share'],readers=['patrick'],writers=['familie'])
        self.assertEqual(share,before)

    def test_account_removal_cleans_web_alias_groups_and_mapping(self):
        self.demo.call('identity_apply',policy=self.policy(),users=self.users)
        self.demo.call('account_remove',name='familie')
        self.assertEqual(self.demo._identity_policy['groups'][0]['members'],[])
        self.assertEqual(self.demo._identity_users,[self.users[0]])
        self.assertNotIn('familie',self.demo.shares[0]['readers']+self.demo.shares[0]['writers'])

    def test_invalid_policy_leaves_acl_and_policy_unchanged(self):
        before=copy.deepcopy(self.demo.shares);policy=self.policy();policy['groups'][0]['members']=['absent']
        with self.assertRaises(Error):self.demo.call('identity_apply',policy=policy,users=self.users)
        self.assertEqual(self.demo.shares,before);self.assertEqual(self.demo._identity_policy,empty_policy())

    def test_demo_quota_support_is_explicit_and_only_managed_zfs(self):
        self.assertIn('simuliert',self.demo.call('identity_capabilities')['quota_notice'])
        result=self.demo.call('user_quota',name='patrick',target='tank/dokumente',limit_bytes=1024)
        self.assertEqual(result['quota']['limit_bytes'],1024)
        for target,limit in [('foreign/dataset',1024),('tank/dokumente',True),('tank/dokumente','1024')]:
            with self.assertRaises(Error):self.demo.call('user_quota',name='patrick',target=target,limit_bytes=limit)


if __name__=='__main__':unittest.main()

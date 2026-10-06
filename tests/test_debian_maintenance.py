"""Signed maintenance input, frozen source retention and download integrity."""
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('debian_maintenance',ROOT/'scripts/debian-maintenance.py')
maintenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maintenance)


def identity(version='0.5.3-alpha.1', source='c'*40, stage='alpha', app_version='0.5.3'):
    return {'format':'titan-debian-ab-v1','platform':'debian-rauc',
            'compatible':'titan-debian13-amd64-ab-v1','architecture':'x86_64','state_schema':1,
            'release_id':'sha256:'+'a'*64,'version':version,'release_stage':stage,'source_commit':'b'*40,
            'system_accounts':{'users':{'root':{'uid':0,'gid':0}},'groups':{'root':0}},
            'update_kind':'system','titan_version':app_version,'titan_stage':stage,
            'titan_source_commit':source,'system_revision':2,
            **{name:'passed' for name in ('boot_test','runtime_test','update_test','rollback_test')},
            'bundle':{'name':'titan-'+version+'-amd64.raucb','size':6,'sha256':hashlib.sha256(b'bundle').hexdigest()},
            'rootfs_sha256':'d'*64}


def inventory():
    return {'format':'titan-debian-packages-v1','suite':'trixie','architecture':'amd64','generated_at':'2026-10-04T10:00:00Z',
            'packages':[{'name':'openssl','version':'3.5.1-1','architecture':'amd64'}]}


class MaintenancePlanTests(unittest.TestCase):
    def test_release_allocator_keeps_frozen_prerelease_branch_and_global_stable_monotonicity(self):
        releases=[{'tag_name':'v0.5.3-alpha.1'},{'tag_name':'v0.5.3-alpha.4'},
                  {'tag_name':'v0.5.3-beta.1'},{'tag_name':'not-a-version'}]
        self.assertEqual(maintenance.allocate_version('0.5.3','alpha',releases,identity()),'0.5.3-alpha.5')
        self.assertEqual(maintenance.allocate_version('0.5.3','alpha',releases),'0.5.4-alpha.1')
        self.assertEqual(maintenance.allocate_version('0.5.3','stable',releases),'0.5.4')

    def test_retains_two_newest_app_commits_per_stage_and_newest_system_revision(self):
        records=[]; values={}; dates={}
        for stage in ('alpha','beta','stable'):
            for number in range(3):
                source=hashlib.sha1((stage+str(number)).encode()).hexdigest()
                tag='v0.5.3'+('' if stage=='stable' else '-'+stage+'.'+str(number+1))
                # Stable tags must also be unique for these fixture releases.
                if stage=='stable':tag='v0.5.'+str(number+3)
                release={'tag_name':tag,'assets':[{'name':'debian-packages.json'}]}
                records.append(release)
                values[tag]=(identity(tag[1:],source,stage),{'debian-packages.json':'inventory-url'})
                dates[source]='2026-10-0'+str(number+1)+'T03:00:00Z'
        newer={'tag_name':'v0.5.3-alpha.9','assets':[{'name':'debian-packages.json'}]}
        records.append(newer)
        old=values['v0.5.3-alpha.3'][0]
        values[newer['tag_name']]=(identity('0.5.3-alpha.9',old['titan_source_commit']),{'debian-packages.json':'inventory-url'})
        with patch.object(maintenance,'checked_release',side_effect=lambda r,t:values[r['tag_name']]), \
             patch.object(maintenance,'api',side_effect=lambda path,t:{'sha':path.split('/')[-1],
                 'committer':{'date':dates[path.split('/')[-1]]}}), \
             patch.object(maintenance,'checked_inventory',side_effect=lambda *a,**k:(k['verified'][0],inventory())) as full:
            result=maintenance.supported_sources(records)
        self.assertEqual(len(result),6)
        self.assertEqual(full.call_count,6)
        self.assertEqual([x['release']['tag_name'] for x in result if x['metadata']['titan_stage']=='alpha'],
                         ['v0.5.3-alpha.9','v0.5.3-alpha.2'])
        self.assertTrue(all(x['inventory']==inventory() for x in result))

    def test_foreign_or_unzoned_commit_date_is_rejected(self):
        release={'tag_name':'v0.5.3-alpha.1','assets':[{'name':'debian-packages.json'}]}
        for commit in ({'sha':'e'*40,'committer':{'date':'2026-10-04T00:00:00Z'}},
                       {'sha':'c'*40,'committer':{'date':'2026-10-04T00:00:00'}}):
            with self.subTest(commit=commit), patch.object(maintenance,'checked_release',return_value=(identity(),{})), \
                 patch.object(maintenance,'api',return_value=commit), self.assertRaises(ValueError):
                maintenance.supported_sources([release])

    def test_first_release_without_inventory_skips_maintenance_safely(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(maintenance,'release_list',return_value=[{'tag_name':'v0.5.2-alpha.1','assets':[]}]), \
             patch.object(maintenance.subprocess,'run') as run:
            self.assertEqual(maintenance.prepare_plan(Path(temporary)),{'include':[]})
            run.assert_not_called()

    def test_probe_is_disposable_official_and_matrix_pins_frozen_source(self):
        manifest=identity()
        source={'release':{'tag_name':'v0.5.3-alpha.1'},'manifest':manifest,
                'metadata':maintenance.updates.release_metadata(manifest),'inventory':inventory()}
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            report=maintenance.packages.summary([{'name':'openssl','old_version':'3.5.1-1',
                                                  'new_version':'3.5.1-2','security':True}])
            def probe(command,**kwargs):
                self.assertEqual(command[:3],['docker','run','--rm'])
                self.assertIn('--memory=1g',command)
                self.assertIn('debian:13-slim',command)
                self.assertIn('Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg',command[-1])
                self.assertIn('main contrib non-free non-free-firmware',command[-1])
                self.assertIn('https://security.debian.org/debian-security',command[-1])
                self.assertEqual(command[command.index('-v')+1],str(directory)+':/work')
                (directory/'probe-inventory-0.json').write_text(json.dumps(report))
            with patch.object(maintenance,'release_list',return_value=[source['release']]), \
                 patch.object(maintenance,'supported_sources',return_value=[source]), \
                 patch.object(maintenance.subprocess,'run',side_effect=probe) as run:
                result=maintenance.prepare_plan(directory)['include']
            run.assert_called_once()
        self.assertEqual(result,[{'version':'0.5.3-alpha.2','source_ref':'c'*40,'app_version':'0.5.3',
                                 'app_stage':'alpha','system_revision':3,'previous_tag':'v0.5.3-alpha.1',
                                 'changes':1,'security_changes':1}])


@unittest.skipUnless(shutil.which('openssl'),'OpenSSL required')
class SignedInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        key=self.root/'key.pem';self.public=self.root/'public.pem'
        subprocess.run(['openssl','genpkey','-algorithm','ED25519','-out',str(key)],check=True,capture_output=True)
        subprocess.run(['openssl','pkey','-in',str(key),'-pubout','-out',str(self.public)],check=True,capture_output=True)
        self.data={'manifest.json':json.dumps(identity()).encode(),'debian-packages.json':json.dumps(inventory()).encode()}
        self.data['SHA256SUMS']=(hashlib.sha256(self.data['debian-packages.json']).hexdigest()+'  debian-packages.json\n').encode()
        for name in ('manifest.json','SHA256SUMS'):
            path=self.root/name;path.write_bytes(self.data[name])
            subprocess.run(['openssl','pkeyutl','-sign','-rawin','-inkey',str(key),'-in',str(path),
                            '-out',str(path)+'.sig'],check=True,capture_output=True)
            self.data[name+'.sig']=Path(str(path)+'.sig').read_bytes()
        self.release={'tag_name':'v0.5.3-alpha.1','html_url':'https://github.com/ra5on/Titan/releases/tag/v0.5.3-alpha.1',
                      'assets':[{'name':name,'url':'https://api.github.com/'+name} for name in self.data]}
        keypatch=patch.object(maintenance.updates,'PUBLIC_KEY',self.public);keypatch.start();self.addCleanup(keypatch.stop)
        fetchpatch=patch.object(maintenance.updates,'fetch',side_effect=lambda url,*a,**k:self.data[url.rsplit('/',1)[1]])
        fetchpatch.start();self.addCleanup(fetchpatch.stop)

    def test_actual_ed25519_signatures_and_inventory_hash_are_verified(self):
        manifest,result=maintenance.checked_inventory(self.release)
        self.assertEqual(manifest['titan_source_commit'],'c'*40)
        self.assertEqual(result,inventory())

    def test_mutated_inventory_unsigned_checksum_and_manifest_are_rejected(self):
        for name in ('debian-packages.json','SHA256SUMS','manifest.json'):
            with self.subTest(name=name):
                original=self.data[name];self.data[name]=original+b' '
                with self.assertRaises((ValueError,subprocess.CalledProcessError,maintenance.updates.Error)):
                    maintenance.checked_inventory(self.release)
                self.data[name]=original

    def test_github_tag_cannot_override_signed_release_version(self):
        with self.assertRaises(ValueError): maintenance.checked_inventory({**self.release,'tag_name':'v0.5.3-alpha.2'})


class BundleDownloadTests(unittest.TestCase):
    def test_exact_signed_bundle_stream_is_published_atomically(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            response=io.BytesIO(b'bundle')
            with patch.object(maintenance,'api',return_value={}), \
                 patch.object(maintenance,'checked_inventory',return_value=(identity(),inventory())), \
                 patch.object(maintenance,'checked_release',return_value=(identity(),{identity()['bundle']['name']:'https://api.github.com/bundle'})), \
                 patch('urllib.request.build_opener',return_value=Mock(open=Mock(return_value=response))):
                maintenance.fetch_previous('v0.5.3-alpha.1',directory,bundle=True)
            self.assertEqual((directory/'previous.raucb').read_bytes(),b'bundle')
            self.assertEqual(list(directory.glob('*.partial')),[])

    def test_bad_size_hash_or_existing_output_leaves_no_trusted_bundle(self):
        for payload in (b'bundlE',b'short',b'long-bundle'):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temporary:
                directory=Path(temporary)
                with patch.object(maintenance,'api',return_value={}), \
                     patch.object(maintenance,'checked_inventory',return_value=(identity(),inventory())), \
                     patch.object(maintenance,'checked_release',return_value=(identity(),{identity()['bundle']['name']:'https://api.github.com/bundle'})), \
                     patch('urllib.request.build_opener',return_value=Mock(open=Mock(return_value=io.BytesIO(payload)))), \
                     self.assertRaises(ValueError):
                    maintenance.fetch_previous('v0.5.3-alpha.1',directory,bundle=True)
                self.assertFalse((directory/'previous.raucb').exists())
                self.assertEqual(list(directory.glob('*.partial')),[])
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);(directory/'previous.raucb').write_bytes(b'keep')
            with patch.object(maintenance,'api',return_value={}), \
                 patch.object(maintenance,'checked_inventory',return_value=(identity(),inventory())), \
                 patch.object(maintenance,'checked_release',return_value=(identity(),{})), self.assertRaises(ValueError):
                maintenance.fetch_previous('v0.5.3-alpha.1',directory,bundle=True)
            self.assertEqual((directory/'previous.raucb').read_bytes(),b'keep')

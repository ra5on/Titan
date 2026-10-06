import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('openssl'),'OpenSSL required')
class MetadataTests(unittest.TestCase):
    def build(self, work, *, kind='system', app_source='c'*40, extra_env=None, report=None, mode='identity'):
        keys=work/'titan-signing';keys.mkdir(exist_ok=True)
        key=keys/'root.key';public=keys/'public.pem'
        if not key.exists():
            subprocess.run(['openssl','genpkey','-algorithm','ED25519','-out',str(key)],check=True,capture_output=True)
            subprocess.run(['openssl','pkey','-in',str(key),'-pubout','-out',str(public)],check=True,capture_output=True)
        accounts=work/'accounts.json';accounts.write_text(json.dumps({'users':{'root':{'uid':0,'gid':0}},'groups':{'root':0}}))
        output=work/'identity.json'
        env={**os.environ,'GITHUB_ACTIONS':'true','GITHUB_SHA':'a'*40,'RUNNER_TEMP':str(work),
             'TITAN_UPDATE_KIND':kind,'TITAN_APP_VERSION':'0.5.3','TITAN_APP_STAGE':'alpha',
             'TITAN_APP_SOURCE_COMMIT':app_source,'TITAN_SYSTEM_REVISION':'2',**(extra_env or {})}
        command=['python3',str(ROOT/'scripts/system-release-metadata.py'),mode,'--version','0.5.3-alpha.2',
                 '--accounts',str(accounts),'--output',str(output)]
        if report is not None:
            path=work/'package-changes.json';path.write_text(json.dumps(report))
            command.extend(['--package-changes',str(path)])
        if mode=='manifest':
            bundle=work/'titan-0.5.3-alpha.2-amd64.raucb';bundle.write_bytes(b'bundle')
            rootfs=work/'rootfs.ext4';rootfs.write_bytes(b'rootfs')
            evidence=work/'evidence.json';evidence.write_text(json.dumps({name:'passed' for name in ('boot_test','runtime_test','update_test','rollback_test')}))
            command.extend(['--bundle',str(bundle),'--rootfs',str(rootfs),'--evidence',str(evidence)])
        result=subprocess.run(command,env=env,capture_output=True)
        return result, output, public

    def verify(self, output, public):
        return subprocess.run(['openssl','pkeyutl','-verify','-rawin','-pubin','-inkey',str(public),
                              '-in',str(output),'-sigfile',str(output)+'.sig'],capture_output=True).returncode

    def test_real_signature_binds_account_contract_and_release_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            work=Path(temporary);keys=work/'titan-signing';keys.mkdir()
            key=keys/'root.key';public=keys/'public.pem'
            subprocess.run(['openssl','genpkey','-algorithm','ED25519','-out',str(key)],check=True,capture_output=True)
            subprocess.run(['openssl','pkey','-in',str(key),'-pubout','-out',str(public)],check=True,capture_output=True)
            accounts={'users':{'root':{'uid':0,'gid':0}},'groups':{'root':0}}
            account_file=work/'accounts.json';account_file.write_text(json.dumps(accounts))
            output=work/'identity.json'
            env={**os.environ,'GITHUB_ACTIONS':'true','GITHUB_SHA':'a'*40,'RUNNER_TEMP':str(work)}
            subprocess.run(['python3',str(ROOT/'scripts/system-release-metadata.py'),'identity','--version','0.5.0-beta.1',
                            '--accounts',str(account_file),'--output',str(output)],env=env,check=True,capture_output=True)
            value=json.loads(output.read_text())
            self.assertEqual(value['system_accounts'],accounts)
            self.assertEqual(value['release_stage'],'beta')
            self.assertEqual(value['source_commit'],'a'*40)
            verify=['openssl','pkeyutl','-verify','-rawin','-pubin','-inkey',str(public),'-in',str(output),'-sigfile',str(output)+'.sig']
            subprocess.run(verify,check=True,capture_output=True)
            value['system_accounts']['users']['root']['uid']=1;output.write_text(json.dumps(value))
            self.assertNotEqual(subprocess.run(verify,capture_output=True).returncode,0)

    def test_system_signature_binds_frozen_app_revision_and_package_security(self):
        report={'package_changes':[{'name':'openssl','old_version':'3.5.1-1','new_version':'3.5.1-2','security':True}],
                'security_summary':{'total_packages':8,'security_packages':2,'checked_at':'2026-10-04T12:00:00Z'}}
        with tempfile.TemporaryDirectory() as temporary:
            result,output,public=self.build(Path(temporary),report=report)
            self.assertEqual(result.returncode,0,result.stderr.decode())
            signed=output.read_text();value=json.loads(signed)
            self.assertEqual(value['update_kind'],'system')
            self.assertEqual(value['titan_version'],'0.5.3')
            self.assertEqual(value['system_revision'],2)
            self.assertEqual(value['titan_source_commit'],'c'*40)
            self.assertEqual(value['security_summary'],report['security_summary'])
            self.assertEqual(self.verify(output,public),0)
            for field,bad in [('update_kind','titan'),('titan_source_commit','d'*40),('system_revision',3),
                              ('titan_version','0.5.4'),('security_summary',{**report['security_summary'],'security_packages':0})]:
                with self.subTest(field=field):
                    changed={**value,field:bad};output.write_text(json.dumps(changed))
                    self.assertNotEqual(self.verify(output,public),0)
                    output.write_text(signed)

    def test_frozen_builder_source_overrides_scheduler_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            result,output,_=self.build(Path(temporary),extra_env={'TITAN_BUILD_SOURCE_COMMIT':'c'*40})
            self.assertEqual(result.returncode,0,result.stderr.decode())
            self.assertEqual(json.loads(output.read_text())['source_commit'],'c'*40)

    def test_normal_titan_release_cannot_claim_a_foreign_frozen_app_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            result,output,_=self.build(Path(temporary),kind='titan')
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(output.exists())
            self.assertFalse(Path(str(output)+'.sig').exists())

    def test_invalid_revision_or_report_is_rejected_before_signing(self):
        invalid=[({'TITAN_SYSTEM_REVISION':'0'},None),({'TITAN_SYSTEM_REVISION':'2147483648'},None),
                 ({'TITAN_BUILD_SOURCE_COMMIT':'invalid'},None),({}, {'package_changes':[], 'security_summary':None, 'unexpected':True}),
                 ({}, {'package_changes':[], 'security_summary':{'total_packages':0,'security_packages':0,'checked_at':'invalid'}})]
        for env,report in invalid:
            with self.subTest(env=env,report=report), tempfile.TemporaryDirectory() as temporary:
                result,output,_=self.build(Path(temporary),extra_env=env,report=report)
                self.assertNotEqual(result.returncode,0)
                self.assertFalse(output.exists())
                self.assertFalse(Path(str(output)+'.sig').exists())

    def test_identity_and_final_manifest_keep_exact_frozen_app_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            work=Path(temporary)
            result,output,public=self.build(work)
            self.assertEqual(result.returncode,0,result.stderr.decode())
            identity=json.loads(output.read_text())
            result,output,public=self.build(work,mode='manifest')
            self.assertEqual(result.returncode,0,result.stderr.decode())
            final=json.loads(output.read_text())
            for field in identity:
                self.assertEqual(identity[field],final[field],field)
            self.assertEqual(final['rollback_test'],'passed')
            self.assertEqual(self.verify(output,public),0)

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

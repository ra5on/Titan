import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('qcow2_smoke', Path(__file__).resolve().parents[1]/'scripts/smoke-qcow2-guest.py')
smoke = importlib.util.module_from_spec(spec); spec.loader.exec_module(smoke)


class GuestSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.fixture = Path(self.temp.name)/'guest.qcow2'; self.fixture.write_bytes(bytes(1024**2))
        self.fixture.with_name('provenance.json').write_text(json.dumps({'fixture_sha256':hashlib.sha256(self.fixture.read_bytes()).hexdigest(),'fixture_size':self.fixture.stat().st_size}))

    def test_changed_fixture_and_missing_kvm_fail_before_any_guest_mutation(self):
        client = SimpleNamespace(action=lambda *args: self.fail('No action permitted'))
        with self.assertRaisesRegex(RuntimeError, 'nested KVM'):
            smoke.run(SimpleNamespace(client=client,kvm=False),self.fixture)
        with self.fixture.open('ab') as stream: stream.write(b'changed')
        with self.assertRaisesRegex(ValueError, 'differs'):
            smoke.run(SimpleNamespace(client=client,kvm=True),self.fixture)

    def test_vm_running_without_agent_is_not_guest_boot_proof(self):
        client=SimpleNamespace(request=lambda *args:{'state':'running','guest_agent':{'connected':False}})
        with patch.object(smoke.time,'monotonic',side_effect=[0,0,301]), patch.object(smoke.time,'sleep'):
            with self.assertRaisesRegex(RuntimeError,'boot Linux'):
                smoke.wait_guest(client,'vm',True)
        client.request=lambda *args:{'state':'running','guest_agent':{'connected':True}}
        self.assertEqual(smoke.wait_guest(client,'vm',True)['state'],'running')

    def test_upload_rejects_mismatched_acknowledgement_before_commit(self):
        response=SimpleNamespace(status=200,read=lambda *args:json.dumps({'atomic':True,'upload_id':'wrong','offset':1024**2}).encode())
        connection=SimpleNamespace(request=lambda *args:None,getresponse=lambda:response,close=lambda:None)
        client=SimpleNamespace(_connect_transport=lambda **args:connection,HOST='host',ORIGIN='https://host',cookie='cookie',csrf='csrf',request=lambda *args:self.fail('No commit after bad acknowledgement'))
        with self.assertRaisesRegex(RuntimeError,'acknowledgement'):
            smoke.upload(client,self.fixture,'share')

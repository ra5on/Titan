import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('web_controller', ROOT/'packaging/container/web-container.py')
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


class ContainerTests(unittest.TestCase):
    def test_only_matching_protocol_and_version_are_accepted(self):
        value = {'Id': 'sha256:'+'a'*64, 'Config': {'Labels': {'org.titan.agent-api': '1', 'org.titan.state-schema': '1', 'org.opencontainers.image.version': '0.6.1'}}}
        with patch.object(controller, 'command', return_value=json.dumps([value])):
            self.assertEqual(controller.validate_image('test', '0.6.1')['image'], value['Id'])
            with self.assertRaises(ValueError): controller.validate_image('test', '0.6.2')
            value['Config']['Labels']['org.titan.agent-api']='2'
        with patch.object(controller, 'command', return_value=json.dumps([value])):
            with self.assertRaises(ValueError): controller.validate_image('test', '0.6.1')

    def test_failed_health_restores_previous_selection(self):
        previous={'image':'sha256:'+'a'*64,'version':'0.6.1'}
        target={'image':'sha256:'+'b'*64,'version':'0.6.2'}
        with tempfile.TemporaryDirectory() as directory, patch.object(controller,'STATE',Path(directory)/'selection.json'), patch.object(controller,'selection',return_value={'current':previous}), patch.object(controller,'command') as commands, patch.object(controller,'healthy',side_effect=[RuntimeError('unhealthy'),None]):
            with self.assertRaisesRegex(RuntimeError,'unhealthy'): controller.switch(target)
            self.assertEqual(json.loads(controller.STATE.read_text())['current'],previous)
            self.assertEqual(sum(call.args==('systemctl','start','titan-web.service') for call in commands.call_args_list),2)

    def test_interrupted_update_reverts_at_next_start(self):
        previous={'image':'old','version':'0.6.1'}
        with tempfile.TemporaryDirectory() as directory, patch.object(controller,'STATE',Path(directory)/'selection.json'), patch.object(controller,'switch_in_progress',return_value=False):
            controller.save({'current':{'image':'new','version':'0.6.2'},'previous':previous,'pending':True})
            self.assertEqual(controller.selection()['current'],previous)
            self.assertNotIn('pending',json.loads(controller.STATE.read_text()))

    def test_new_password_hash_survives_backup_validation(self):
        from titan.core import password_hash, valid_password_hash, password_matches
        value=password_hash('correct-password')
        self.assertTrue(valid_password_hash(value))
        self.assertTrue(password_matches('correct-password',value))
        self.assertFalse(valid_password_hash(value+'bad'))

    def test_password_verification_performs_only_one_kdf(self):
        from titan import core
        value=core.password_hash('correct-password')
        with patch.object(core,'_scrypt', wraps=core._scrypt) as calculate:
            self.assertTrue(core.password_matches('correct-password',value))
            self.assertEqual(calculate.call_count,1)

    def test_jellyfin_media_are_read_only(self):
        from titan.app_packages import PACKAGES
        media=[m for m in PACKAGES['titan-jellyfin']['stack']['services']['jellyfin']['mounts'] if m['target']=='/media']
        self.assertEqual(len(media),1)
        self.assertTrue(media[0]['readonly'])

    def test_system_web_container_cannot_be_stopped_from_app_actions(self):
        from titan.docker_engine import DockerEngineMixin
        from titan.core import Error
        class Fake:
            def engine_container(self, value):
                return {'Config': {'Labels': {'org.titan.system': 'web'}}}
        with self.assertRaises(Error) as error:
            DockerEngineMixin.engine_action_target(Fake(), 'container', 'stop')
        self.assertEqual(error.exception.status, 409)

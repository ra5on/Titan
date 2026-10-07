import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from titan.app_state import legacy_recipe, load_state, save_state
from titan.catalog import APPS
from titan.core import atomic_json


def compatible_recipe():
    return {'name':'Old app','port':8080,'image':'example/app:1','imported_stack':True,
            'stack':{'primary':'app','services':{'app':{'image':'example/app:1','ports':[{'target':80,'published':8080,'protocol':'tcp'}]}}}}


class AppStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def read_old(self, name): return json.loads((self.directory/(name+'.json')).read_text())

    def make_newer(self, legacy, modern):
        timestamp = (self.directory/(modern+'.json')).stat().st_mtime_ns + 1000000
        os.utime(self.directory/(legacy+'.json'), ns=(timestamp,timestamp))

    def test_old_state_remains_a_fallback_until_first_new_write(self):
        atomic_json(self.directory/'apps.json', [{'id':'jellyfin','phase':'running'}])
        self.assertEqual(load_state(self.directory, 'apps', []), [{'id':'jellyfin','phase':'running'}])
        save_state(self.directory, 'apps', load_state(self.directory,'apps',[]))
        self.assertEqual(self.read_old('apps-v2'), self.read_old('apps'))

    def test_new_features_never_reach_the_old_recipe_or_app_registry(self):
        old = compatible_recipe()
        headless = {**copy.deepcopy(old),'port':0,'web_available':False}
        protected = copy.deepcopy(old); protected['stack']['services']['app']['read_only'] = True
        segmented = copy.deepcopy(old); segmented['stack']['networks'] = {'back':{'internal':True}}
        values = {'old':old,'background':headless,'protected':protected,'segmented':segmented}
        save_state(self.directory,'installed-app-recipes-v1',values)
        save_state(self.directory,'apps',[{'id':key} for key in values])
        self.assertEqual(set(self.read_old('installed-app-recipes-v1')), {'old'})
        self.assertEqual(self.read_old('apps'), [{'id':'old'}])
        self.assertEqual(set(load_state(self.directory,'installed-app-recipes-v1',{})), set(values))
        self.assertEqual(len(load_state(self.directory,'apps',[])),4)

    def test_old_parser_can_read_mirrored_recipe_without_new_metadata(self):
        recipe = compatible_recipe(); recipe['web_available'] = True
        recipe['stack']['services']['app']['restart'] = 'unless-stopped'
        mirrored = legacy_recipe(recipe)
        self.assertNotIn('web_available',mirrored)
        self.assertNotIn('restart',mirrored['stack']['services']['app'])
        self.assertIn('restart',recipe['stack']['services']['app'])
        recipe['web_host_ip'] = '127.0.0.1'
        self.assertIsNone(legacy_recipe(recipe))

    def test_old_image_stop_and_removal_do_not_resurrect_on_new_image(self):
        old = compatible_recipe(); headless = {**copy.deepcopy(old),'port':0,'web_available':False}
        save_state(self.directory,'installed-app-recipes-v1',{'old':old,'background':headless})
        save_state(self.directory,'apps',[{'id':'old','phase':'running'},{'id':'background','phase':'running'}])
        atomic_json(self.directory/'apps.json',[{'id':'old','phase':'stopped'}]); self.make_newer('apps','apps-v2')
        self.assertEqual({row['id']:row['phase'] for row in load_state(self.directory,'apps',[])}, {'old':'stopped','background':'running'})
        atomic_json(self.directory/'apps.json',[]); self.make_newer('apps','apps-v2')
        self.assertEqual(load_state(self.directory,'apps',[]),[{'id':'background','phase':'running'}])

    def test_compatible_install_during_rollback_is_merged_without_losing_new_recipes(self):
        headless = {**compatible_recipe(),'port':0,'web_available':False}
        save_state(self.directory,'installed-app-recipes-v1',{'background':headless})
        atomic_json(self.directory/'installed-app-recipes-v1.json',{'later':compatible_recipe()})
        self.make_newer('installed-app-recipes-v1','installed-app-recipes-v2')
        self.assertEqual(set(load_state(self.directory,'installed-app-recipes-v1',{})), {'background','later'})

    def test_restart_between_legacy_and_modern_writes_keeps_new_only_records(self):
        old = compatible_recipe(); headless = {**copy.deepcopy(old),'port':0,'web_available':False}
        save_state(self.directory,'installed-app-recipes-v1',{'old':old,'background':headless})
        save_state(self.directory,'apps',[{'id':'old','phase':'running'},{'id':'background','phase':'running'}])
        def interrupted(path, value):
            if path.name == 'apps-v2.json': raise OSError('simulated loss before modern publish')
            atomic_json(path, value)
        with patch('titan.app_state.atomic_json', side_effect=interrupted), self.assertRaises(OSError):
            save_state(self.directory,'apps',[{'id':'old','phase':'stopped'},{'id':'background','phase':'running'}])
        self.make_newer('apps','apps-v2')
        self.assertEqual({row['id']:row['phase'] for row in load_state(self.directory,'apps',[])}, {'old':'stopped','background':'running'})

    def test_legacy_snapshot_secret_metadata_is_repaired_without_password_rotation(self):
        recipe = compatible_recipe()
        recipe['stack']['services']['app']['environment'] = {'BASIC_AUTH_PASS':'@option:stack_env_0'}
        recipe['install_schema'] = [{'key':'stack_env_0','label':'BASIC_AUTH_PASS · app','type':'text','default':'older-default','required':True,'min_length':0,'max_length':1000}]
        atomic_json(self.directory/'installed-app-recipes-v1.json', {'app':recipe})
        loaded = load_state(self.directory,'installed-app-recipes-v1',{})['app']
        self.assertEqual(loaded['install_schema'][0]['type'], 'password')
        self.assertEqual(loaded['install_schema'][0]['default'], '')
        self.assertEqual(loaded['stack'], recipe['stack'])
        self.assertEqual(self.read_old('installed-app-recipes-v1')['app'], recipe)


if __name__ == '__main__': unittest.main()

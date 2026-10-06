"""Real smoke assertions must use the frozen app, not the current builder."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FrozenSmokeSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.work=Path(self.temp.name)
        (self.work/'titan').mkdir()
        (self.work/'titan/__init__.py').write_text("__version__='0.5.4'\n")
        source=(ROOT/'scripts/smoke-image.sh').read_text()
        self.assertion=re.search(r'''python3 - "\$task_dir/session.json" <<'PY'\n(.*?)\nPY\n''',source,re.S).group(1)
        self.session=self.work/'session.json'
        self.environment={key:value for key,value in os.environ.items() if not key.startswith('TITAN_')}

    def boot_assertion(self,version,**environment):
        self.session.write_text(json.dumps({'version':version,'setup_required':True,'user':None,'demo':False}))
        return subprocess.run([sys.executable,'-c',self.assertion,str(self.session)],cwd=self.work,
            env={**self.environment,**environment},capture_output=True,text=True)

    def test_maintenance_boot_accepts_frozen_app_and_rejects_current_builder_version(self):
        environment={'TITAN_UPDATE_KIND':'system','TITAN_APP_VERSION':'0.5.3'}
        result=self.boot_assertion('0.5.3',**environment)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotEqual(self.boot_assertion('0.5.4',**environment).returncode,0)

    def test_maintenance_never_falls_back_to_unvalidated_current_application(self):
        self.assertNotEqual(self.boot_assertion('0.5.4',TITAN_UPDATE_KIND='system').returncode,0)
        for version in ('', '0.5.3-alpha.1','0.5.3\n','injected'):
            with self.subTest(version=version):
                self.assertNotEqual(self.boot_assertion('0.5.3',TITAN_APP_VERSION=version).returncode,0)

    def test_legacy_manual_preview_uses_its_trusted_local_source(self):
        result=self.boot_assertion('0.5.4')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotEqual(self.boot_assertion('0.5.3').returncode,0)

    def test_runtime_catalog_and_package_contract_use_frozen_checkout(self):
        frozen=self.work/'frozen';(frozen/'titan').mkdir(parents=True)
        (frozen/'titan/__init__.py').write_text("__version__='0.5.3'\n")
        recipe={'name':'Frozen app','documentation':'https://example.invalid/frozen',
            'first_login':{'mode':'none','instructions':'Frozen guidance','documentation':'https://example.invalid/frozen'}}
        (frozen/'titan/catalog.py').write_text('APPS='+repr({'frozen-app':recipe})+'\n')
        (frozen/'titan/app_packages.py').write_text("PACKAGES={'frozen-app':{}}\n")
        source="""import importlib.util,json,sys
from types import SimpleNamespace
spec=importlib.util.spec_from_file_location('runtime',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
recipe=module.APPS['frozen-app']
value={'apps':[dict(recipe,id='frozen-app',install_schema=[])]}
print(json.dumps(module.RuntimeSmoke(SimpleNamespace(request=lambda path:value)).catalog()))
"""
        result=subprocess.run([sys.executable,'-c',source,str(ROOT/'scripts/smoke-runtime.py')],cwd=self.work,
            env={**self.environment,'TITAN_APP_SOURCE_ROOT':str(frozen)},capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['app_count'],1)
        self.assertTrue(json.loads(result.stdout)['ok'])


if __name__=='__main__':unittest.main()

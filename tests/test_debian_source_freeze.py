"""The maintenance builder must package the exact frozen application payload."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_system_build', ROOT/'scripts/prepare-system-build.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


@unittest.skipUnless(shutil.which('git'), 'Git required for checkout proofs')
class FrozenCheckoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app, self.app_sha = self.checkout('app')
        self.builder, self.builder_sha = self.checkout('builder')
        self.environment = {'TITAN_UPDATE_KIND': 'system', 'TITAN_APP_SOURCE_COMMIT': self.app_sha,
                            'TITAN_BUILD_SOURCE_COMMIT': self.builder_sha,
                            'TITAN_APP_VERSION': '0.5.1', 'TITAN_APP_STAGE': 'beta'}

    def checkout(self, name):
        path = self.root/name
        (path/'titan').mkdir(parents=True)
        (path/'titan/__init__.py').write_text("__version__ = '0.5.1'\n__release_stage__ = 'beta'\n")
        (path/'titan/payload.py').write_text(name+'\n')
        for command in (['init', '--quiet'], ['add', 'titan'],
                        ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                         'commit', '--quiet', '-m', 'Frozen fixture']):
            subprocess.run(['git', '-C', str(path), *command], check=True, capture_output=True)
        return path, prepare.commit(path)

    def test_independent_builder_and_frozen_application_are_bound(self):
        self.assertNotEqual(self.app_sha, self.builder_sha)
        self.assertEqual(prepare.validate(self.app, self.environment, self.builder),
                         {'TITAN_APP_SOURCE_ROOT': str(self.app)})

    def test_mismatching_commit_version_stage_or_kind_is_rejected(self):
        for field, value in [('TITAN_APP_SOURCE_COMMIT', 'a'*40), ('TITAN_BUILD_SOURCE_COMMIT', 'b'*40),
                             ('TITAN_APP_VERSION', '0.5.2'), ('TITAN_APP_STAGE', 'alpha'),
                             ('TITAN_UPDATE_KIND', 'titan'), ('TITAN_UPDATE_KIND', 'invalid')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                prepare.validate(self.app, {**self.environment, field:value}, self.builder)

    def test_tracked_changes_and_untracked_application_files_are_rejected(self):
        payload = self.app/'titan/payload.py'
        payload.write_text('uncommitted\n')
        with self.assertRaises(ValueError): prepare.validate(self.app, self.environment, self.builder)
        payload.write_text('app\n')
        (self.app/'titan/untracked.py').write_text('injected\n')
        with self.assertRaises(ValueError): prepare.validate(self.app, self.environment, self.builder)

    def test_nested_directory_cannot_claim_parent_checkout_identity(self):
        nested = self.app/'nested'
        nested.mkdir()
        with self.assertRaises(ValueError): prepare.commit(nested)

    def test_identity_parser_rejects_dynamic_duplicate_or_symlink_identity(self):
        path = self.app/'titan/__init__.py'
        for source in ("__version__ = get_version()\n__release_stage__='beta'\n",
                       "__version__='0.5.1'\n__version__='0.5.2'\n__release_stage__='beta'\n",
                       "__version__='0.5.1-beta.1'\n__release_stage__='beta'\n"):
            path.write_text(source)
            with self.assertRaises(ValueError): prepare.application_identity(self.app)
        path.unlink()
        path.symlink_to(self.builder/'titan/__init__.py')
        with self.assertRaises(ValueError): prepare.application_identity(self.app)


@unittest.skipUnless(shutil.which('dpkg-deb'), 'dpkg-deb required')
class FrozenDebianPayloadTests(unittest.TestCase):
    def test_real_package_uses_frozen_web_helpers_services_and_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            frozen = work/'frozen'
            frozen.mkdir()
            # Only the explicit payload roots, never local state or credentials.
            for name in ('titan', 'image', 'packaging', 'docs', 'scripts'):
                shutil.copytree(ROOT/name, frozen/name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            for name in ('LICENSE', 'NOTICE'): shutil.copyfile(ROOT/name, frozen/name)
            init = frozen/'titan/__init__.py'
            init.write_text("__version__ = '0.5.1'\n__release_stage__ = 'beta'\n")
            (frozen/'titan/web/index.html').write_text('frozen web payload\n')
            (frozen/'scripts/component-functions.sh').write_text('#!/bin/sh\n# frozen component helper\n')
            (frozen/'packaging/debian/runtime.sh').write_text('#!/bin/sh\n# frozen runtime helper\n')
            (frozen/'packaging/titan-web.service').write_text('[Unit]\nDescription=Frozen service\n')
            (frozen/'titan/custom_services.py').write_text('# frozen containment helper\n')
            (frozen/'image/titan-service-containment.service').write_text('[Unit]\nDescription=Frozen containment gate\n')
            output = work/'output'
            env = {**os.environ, 'TITAN_APP_SOURCE_ROOT':str(frozen)}
            subprocess.run(['python3',str(ROOT/'scripts/build-debian-package.py'),'--output',str(output)],
                           env=env,check=True,capture_output=True)
            package = output/'titan-debian-preview_0.5.1+debian1_amd64.deb'
            unpacked = work/'unpacked'
            subprocess.run(['dpkg-deb','--raw-extract',str(package),str(unpacked)],check=True,capture_output=True)
            for source, target in [('titan/web/index.html','usr/lib/titan/titan/web/index.html'),
                                   ('scripts/component-functions.sh','usr/share/titan/component-functions.sh'),
                                   ('packaging/debian/runtime.sh','usr/share/titan/install-components.sh'),
                                   ('packaging/titan-web.service','usr/lib/systemd/system/titan-web.service'),
                                   ('titan/custom_services.py','usr/lib/titan/titan/custom_services.py'),
                                   ('image/titan-service-containment.service','usr/lib/systemd/system/titan-service-containment.service')]:
                self.assertEqual((frozen/source).read_bytes(),(unpacked/target).read_bytes(),source)
            self.assertEqual(json.loads((unpacked/'usr/share/titan/image-info.json').read_text())['version'],'0.5.1')
            self.assertIn('Version: 0.5.1+debian1',(unpacked/'DEBIAN/control').read_text())
            self.assertFalse((unpacked/'var').exists())
            self.assertFalse((unpacked/'etc').exists())

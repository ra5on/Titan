from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WebReleasePolicyTests(unittest.TestCase):
    def test_only_explicit_boolean_opt_in_permits_standalone_publication(self):
        for assignment, allowed in (('', False), ('False', False), ('"true"', False), ('1', False), ('True', True)):
            with self.subTest(assignment=assignment), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / 'scripts').mkdir()
                (root / 'titan').mkdir()
                guard = root / 'scripts/require-standalone-web.py'
                shutil.copyfile(ROOT / 'scripts/require-standalone-web.py', guard)
                (root / 'titan/__init__.py').write_text(
                    '__version__ = "0.8.3"\n' + (f'__web_update_standalone__ = {assignment}\n' if assignment else ''))
                result = subprocess.run([sys.executable, str(guard)], capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, allowed, result.stderr)
                if not allowed:
                    self.assertIn('requires a full system update', result.stderr)

    def test_current_plugin_release_requires_full_system_update(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/require-standalone-web.py')],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('standalone web publication is disabled', result.stderr)

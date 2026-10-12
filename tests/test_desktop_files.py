import base64
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('desktop_files', Path(__file__).parents[1] / 'titan/session_browser/files.py')
files = importlib.util.module_from_spec(spec)
spec.loader.exec_module(files)


class DesktopFilesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        files.ROOT = Path(temporary.name)

    def test_multichunk_roundtrip_and_no_overwrite(self):
        for offset, value in [(0,b'hello'), (5,b' world')]:
            files.transfer({'action':'write','name':'test.txt','offset':offset,'data':base64.b64encode(value).decode()})
        self.assertEqual(files.transfer({'action':'read','name':'test.txt','offset':0}), {'total':11,'data':base64.b64encode(b'hello world').decode()})
        with self.assertRaises(FileExistsError):
            files.transfer({'action':'write','name':'test.txt','offset':0,'data':'YQ=='})
        self.assertEqual(files.transfer({'action':'list'})['files'], [{'name':'test.txt','size':11}])

    def test_path_traversal_and_stale_offset(self):
        for name in ('../passwd', '/etc/passwd', 'a\\b', '.hidden', 'a\x00b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                files.transfer({'action':'write','name':name,'offset':0,'data':'YQ=='})
        files.transfer({'action':'write','name':'ok','offset':0,'data':'YQ=='})
        with self.assertRaises(ValueError):
            files.transfer({'action':'write','name':'ok','offset':10,'data':'YQ=='})

    def test_symlinks_are_not_downloadable(self):
        try:
            (files.ROOT / 'link').symlink_to('/etc/passwd')
        except OSError:
            self.skipTest('Symlinks unavailable')
        with self.assertRaises(OSError):
            files.transfer({'action':'read','name':'link','offset':0})


if __name__ == '__main__':
    unittest.main()

import os
from pathlib import Path
import tempfile
import unittest

from titan.core import Error
from titan.files import operate
from titan.file_search import list_directory
from titan.system_files import operate_system


class FileSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'Fotos/Urlaub').mkdir(parents=True)
        (self.root / 'Fotos/Urlaub/Bild.JPG').write_bytes(b'12345')
        (self.root / 'Fotos/Notiz.txt').write_text('Notiz')
        (self.root / 'Budget.xlsx').write_bytes(b'PK\x00binary')
        (self.root / '.titan-trash').mkdir()
        (self.root / '.titan-trash/secret.JPG').write_bytes(b'hidden')
        (self.root / 'shortcut').symlink_to('Fotos', target_is_directory=True)
        (self.root / 'escape').symlink_to('/etc', target_is_directory=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_recursive_results_preserve_full_paths_and_skip_trash_and_links(self):
        result = operate(self.root, 'list', recursive=True, type='image')
        self.assertEqual([item['path'] for item in result['entries']], ['Fotos/Urlaub/Bild.JPG'])
        self.assertFalse(result['truncated'])
        self.assertFalse(result['has_more'])
        self.assertEqual(result['total'], 1)

    def test_size_date_type_and_case_insensitive_name_filters(self):
        target = self.root / 'Fotos/Urlaub/Bild.JPG'
        os.utime(target, (1700000000, 1700000000))
        for params, expected in [({'type': 'image', 'search': 'bIlD', 'min_size': 5, 'max_size': 5}, 1),
                                 ({'type': 'image', 'min_size': 6}, 0),
                                 ({'type': 'image', 'modified_after': 1700000001}, 0),
                                 ({'type': 'image', 'modified_before': 1700000000}, 1),
                                 ({'type': 'document'}, 2)]:
            with self.subTest(params=params):
                self.assertEqual(operate(self.root, 'list', recursive=True, **params)['total'], expected)

    def test_search_pagination_is_stable_and_operates_in_selected_subfolder(self):
        first = operate(self.root, 'list', path='Fotos', recursive=True, type='file', limit=1)
        second = operate(self.root, 'list', path='Fotos', recursive=True, type='file', limit=1, offset=1)
        self.assertTrue(first['has_more'])
        self.assertFalse(second['has_more'])
        self.assertEqual(first['path'], 'Fotos')
        self.assertEqual([first['entries'][0]['path'], second['entries'][0]['path']],
                         ['Fotos/Notiz.txt', 'Fotos/Urlaub/Bild.JPG'])

    def test_bounded_search_reports_truncation_and_does_not_claim_completion(self):
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            result = list_directory(fd, '', {'recursive': True}, max_entries=1)
            self.assertTrue(result['truncated'])
            self.assertEqual(result['scanned'], 1)
            self.assertIn('begrenzt', result['warning'])
        finally:
            os.close(fd)

    def test_invalid_filters_and_root_escape_are_rejected(self):
        for args in ({'recursive': 'false'}, {'type': 'executable'}, {'min_size': -1},
                     {'min_size': 10, 'max_size': 5}, {'modified_after': 20, 'modified_before': 10}):
            with self.subTest(args=args), self.assertRaises(Error):
                operate(self.root, 'list', **args)
        with self.assertRaises(Error):
            operate(self.root, 'list', '../', recursive=True)

    def test_system_search_preserves_metadata_and_avoids_virtual_subtrees(self):
        (self.root / 'proc').mkdir()
        (self.root / 'proc/secret.JPG').write_bytes(b'protected')
        result = operate_system(self.root, 'list', recursive=True, type='image', system_path_root=str(self.root))
        self.assertEqual([entry['path'] for entry in result['entries']],
                         ['.titan-trash/secret.JPG', 'Fotos/Urlaub/Bild.JPG'])
        self.assertTrue(all('mutable' in item for item in result['entries']))
        self.assertGreater(result['skipped'], 0)

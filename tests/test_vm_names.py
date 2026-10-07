import unittest

from titan.core import Error
from titan.vm_names import display_name, identity


class VMNamesTests(unittest.TestCase):
    def test_display_names_keep_capitals_spaces_and_unicode_out_of_paths(self):
        for value in ('Windows 11', 'Meine Linux VM', 'Büro NAS', '../../Meine VM', '123 Test'):
            internal, label = identity(value)
            self.assertEqual(label, value)
            self.assertRegex(internal, r'^[a-z][a-z0-9_-]{0,30}$')
            self.assertNotIn('/', internal)
        self.assertEqual(identity('linux'), ('linux', 'linux'))
        self.assertEqual(display_name('  Meine VM  '), 'Meine VM')

    def test_empty_control_and_unbounded_labels_rejected(self):
        for value in ('', ' ', None, True, 'a'*97, 'x\x00y', 'x\ny', 'x\u202ey'):
            with self.subTest(value=repr(value)), self.assertRaises(Error):
                identity(value)

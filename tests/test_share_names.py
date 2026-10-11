import unittest
from titan.core import Error
from titan.share_names import display_name, identity


class ShareNameTests(unittest.TestCase):
    def test_human_names_keep_separate_safe_identity(self):
        name, label = identity('  Meine Dateien für Jörg  ')
        self.assertEqual(label, 'Meine Dateien für Jörg')
        self.assertRegex(name, r'^[a-z][a-z0-9_-]{0,30}$')
        self.assertEqual(identity('documents'), ('documents', 'documents'))

    def test_config_injection_paths_controls_and_reserved_sections_are_rejected(self):
        for value in ('global', 'HOMES', 'printers', 'IPC$', '../files', 'a\\b', '[global]', 'foo\npath=x', 'a\x00b', '%U', 'a\u202eb', 'extern-usb', '', 'x' * 81):
            with self.subTest(value=value), self.assertRaises(Error):
                display_name(value)

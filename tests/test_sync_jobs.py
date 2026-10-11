import os
from pathlib import Path
import tempfile
import threading
import unittest
from titan.core import Error
from titan.sync_jobs import DIRECTORY, PARTIAL, SyncMixin, mirror


@unittest.skipUnless(os.name == 'posix', 'descriptor-bound traversal needs POSIX')
class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.source = Path(self.temporary.name) / 'source'
        self.target = Path(self.temporary.name) / 'target'
        self.source.mkdir()
        self.target.mkdir()
        (self.source / 'Fotos').mkdir()
        (self.source / 'Fotos' / 'a.jpg').write_bytes(b'a' * 5000)
        (self.source / 'notiz.txt').write_text('eins')

    def tearDown(self):
        self.temporary.cleanup()

    def run_mirror(self, delete=False, stop=None):
        source, target = os.open(self.source, DIRECTORY), os.open(self.target, DIRECTORY)
        try:
            return mirror(source, target, delete, stop=stop)
        finally:
            os.close(source)
            os.close(target)

    def test_copies_tree_then_only_changed_files(self):
        first = self.run_mirror()
        self.assertEqual((first['copied'], first['errors']), (2, 0))
        self.assertEqual((self.target / 'Fotos' / 'a.jpg').read_bytes(), b'a' * 5000)
        self.assertEqual(self.run_mirror()['copied'], 0)
        (self.source / 'notiz.txt').write_text('zwei, länger')
        again = self.run_mirror()
        self.assertEqual((again['copied'], again['unchanged']), (1, 1))
        self.assertEqual((self.target / 'notiz.txt').read_text(), 'zwei, länger')
        self.assertFalse((self.target / PARTIAL).exists())

    def test_deleted_source_files_stay_on_the_target_unless_requested(self):
        self.run_mirror()
        (self.source / 'notiz.txt').unlink()
        (self.target / 'nur-im-ziel.txt').write_text('bleibt')
        kept = self.run_mirror()
        self.assertEqual(kept['deleted'], 0)
        self.assertTrue((self.target / 'notiz.txt').exists())
        removed = self.run_mirror(delete=True)
        self.assertEqual(removed['deleted'], 2)
        self.assertFalse((self.target / 'notiz.txt').exists())
        self.assertFalse((self.target / 'nur-im-ziel.txt').exists())
        self.assertTrue((self.target / 'Fotos' / 'a.jpg').exists())

    def test_symlinks_and_private_folders_are_never_followed_or_copied(self):
        secret = Path(self.temporary.name) / 'secret'
        secret.mkdir()
        (secret / 'key').write_text('geheim')
        (self.source / 'link-datei').symlink_to(secret / 'key')
        (self.source / 'link-ordner').symlink_to(secret, target_is_directory=True)
        (self.source / '.titan-trash').mkdir()
        (self.source / '.titan-trash' / 'alt.txt').write_text('papierkorb')
        stats = self.run_mirror()
        self.assertEqual(stats['skipped'], 2)
        self.assertFalse((self.target / 'link-datei').exists())
        self.assertFalse((self.target / 'link-ordner').exists())
        self.assertFalse((self.target / '.titan-trash').exists())
        self.assertFalse(any(path.name == 'key' for path in self.target.rglob('*')))

    def test_a_link_planted_on_the_target_is_not_written_through(self):
        outside = Path(self.temporary.name) / 'outside.txt'
        outside.write_text('unberührt')
        (self.target / 'notiz.txt').symlink_to(outside)
        self.run_mirror(delete=True)
        self.assertEqual(outside.read_text(), 'unberührt')
        self.assertFalse((self.target / 'notiz.txt').is_symlink())
        self.assertEqual((self.target / 'notiz.txt').read_text(), 'eins')

    def test_stop_request_aborts_a_running_mirror(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaises(Error):
            self.run_mirror(stop=stop)


class ScheduleTests(unittest.TestCase):
    def test_due_jobs_respect_interval_and_enabled_switch(self):
        class Host(SyncMixin):
            def load(self, name, default):
                return [{'share': 'a', 'enabled': True, 'interval_minutes': 5, 'last_run': 1000},
                        {'share': 'b', 'enabled': False, 'interval_minutes': 1, 'last_run': None},
                        {'share': 'c', 'enabled': True, 'interval_minutes': 60, 'last_run': None}]
        host = Host()
        self.assertEqual([job['share'] for job in host.sync_due(now=1000 + 299)], ['c'])
        self.assertEqual([job['share'] for job in host.sync_due(now=1000 + 300)], ['a', 'c'])


if __name__ == '__main__':
    unittest.main()

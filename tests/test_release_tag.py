import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location('release_tag', Path(__file__).resolve().parents[1] / 'scripts/reserve-release-tag.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReleaseTagTests(unittest.TestCase):
    commit = 'a' * 40

    def response(self, sha=None, kind='commit'):
        return SimpleNamespace(returncode=0, stdout=json.dumps({'ref': 'refs/tags/v0.6.1', 'object': {'type': kind, 'sha': sha or self.commit}}))

    def test_creates_exact_tag(self):
        run = Mock(return_value=self.response())
        self.assertEqual(module.reserve('v0.6.1', self.commit, run), self.commit)
        self.assertEqual(run.call_count, 1)
        self.assertIn('sha=' + self.commit, run.call_args.args[0])

    def test_retry_accepts_existing_exact_commit(self):
        run = Mock(side_effect=[SimpleNamespace(returncode=1), self.response()])
        self.assertEqual(module.reserve('v0.6.1', self.commit, run), self.commit)
        self.assertEqual(run.call_count, 2)
        self.assertNotIn('--method', run.call_args.args[0])

    def test_different_commit_cannot_be_overwritten(self):
        run = Mock(side_effect=[SimpleNamespace(returncode=1), self.response('b' * 40)])
        with self.assertRaisesRegex(RuntimeError, 'refusing to retag'):
            module.reserve('v0.6.1', self.commit, run)
        self.assertEqual(run.call_count, 2)

    def test_failed_reservation_stops_before_build(self):
        run = Mock(return_value=SimpleNamespace(returncode=1))
        with self.assertRaisesRegex(RuntimeError, 'permissions'):
            module.reserve('v0.6.1', self.commit, run)

    def test_invalid_tag_never_calls_github(self):
        run = Mock()
        for tag in ('v0.6.1;echo bad', 'refs/heads/main', 'v01.6.1', '../v0.6.1'):
            with self.assertRaises(ValueError):
                module.reserve(tag, self.commit, run)
        run.assert_not_called()

    def test_annotated_tag_is_not_silently_replaced(self):
        with self.assertRaisesRegex(RuntimeError, 'refusing to retag'):
            module.reserve('v0.6.1', self.commit, Mock(return_value=self.response(kind='tag')))

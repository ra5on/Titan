import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('titan_ab_smoke', Path(__file__).resolve().parents[1] / 'scripts/smoke-debian-ab.py')
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)


class DebianABSmokeTests(unittest.TestCase):
    def test_image_and_system_baselines_have_distinct_provenance(self):
        image = ab.published_baseline_metadata('published-image', '0.4.6-alpha.1', 'a' * 64)
        self.assertEqual(image['baseline_source'], 'published-release')
        self.assertNotIn('baseline_bundle_sha256', image)
        system = ab.published_baseline_metadata('published-system', '0.5.2-alpha.1', 'a' * 64, 'b' * 64)
        self.assertEqual(system['baseline_source'], 'published-system-release')
        self.assertEqual(system['baseline_sha256'], 'a' * 64)
        self.assertEqual(system['baseline_bundle_sha256'], 'b' * 64)

    def test_incomplete_or_invalid_published_provenance_is_rejected(self):
        for args in (('synthetic', '0.5.2-alpha.1', 'a' * 64), ('published-image', 'latest', 'a' * 64), ('published-image', '0.5.2-alpha.1', 'no-hash'), ('published-image', '0.5.2-alpha.1', 'a' * 64, 'b' * 64), ('published-system', '0.5.2-alpha.1', 'a' * 64), ('published-system', '0.5.2-alpha.1', 'a' * 64, 'B' * 64)):
            with self.subTest(args=args):
                with self.assertRaises(ValueError): ab.published_baseline_metadata(*args)

    def test_system_baseline_cli_requires_image_and_sha_before_any_mutation(self):
        for extra in (['--baseline-kind', 'published-system'], ['--baseline-kind', 'published-system', '--baseline-image', '/tmp/baseline.img'], ['--baseline-kind', 'published-system', '--baseline-image', '/tmp/baseline.img', '--baseline-bundle-sha256', 'bad']):
            with patch.object(ab.os, 'environ', {'GITHUB_ACTIONS': 'true'}), patch('sys.argv', ['smoke-debian-ab.py', '/tmp/candidate.img', '/tmp/candidate.raucb', '--confirm-disposable-guest', *extra]), patch.object(ab, 'command') as command:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error: ab.main()
                self.assertEqual(error.exception.code, 2)
                command.assert_not_called()

    def test_image_baseline_cannot_claim_system_bundle_provenance(self):
        with patch('sys.argv', ['smoke-debian-ab.py', '/tmp/candidate.img', '/tmp/candidate.raucb', '--baseline-bundle-sha256', 'b' * 64]), patch.object(ab, 'command') as command:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error: ab.main()
            self.assertEqual(error.exception.code, 2)
            command.assert_not_called()


if __name__ == '__main__':
    unittest.main()

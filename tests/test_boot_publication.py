"""Boot safety: fresh CoreOS presets and failed Alpha candidate update gating."""
from pathlib import Path
import unittest
from titan.core import Error
from titan.updates import validate_image_manifest

ROOT = Path(__file__).resolve().parents[1]


class BootPublicationTests(unittest.TestCase):
    def test_failed_boot_candidate_cannot_enter_system_updates(self):
        with self.assertRaises(Error) as result:
            validate_image_manifest({'boot_test': 'failed'}, {})
        self.assertEqual(result.exception.status, 409)

    def test_incomplete_runtime_candidate_cannot_enter_system_updates(self):
        for status in ('failed', 'not-run'):
            with self.subTest(status=status), self.assertRaises(Error) as result:
                validate_image_manifest({'boot_test': 'passed', 'runtime_test': status}, {})
            self.assertEqual(result.exception.status, 409)

    def test_update_requires_explicit_passed_boot_and_runtime(self):
        valid = {'boot_test': 'passed', 'runtime_test': 'passed'}
        for field in valid:
            for status in ('failed', 'not-run', 'unknown', '', None, True, 1, ['passed']):
                manifest = {**valid, field: status}
                with self.subTest(field=field, status=status), self.assertRaises(Error) as result:
                    validate_image_manifest(manifest, {})
                self.assertEqual(result.exception.status, 409)
            manifest = dict(valid)
            del manifest[field]
            with self.subTest(field=field, missing=True), self.assertRaises(Error) as result:
                validate_image_manifest(manifest, {})
            self.assertEqual(result.exception.status, 409)

    def test_img_only_and_legacy_complete_iso_manifests_share_update_format(self):
        image = 'ghcr.io/ra5on/titan@sha256:' + 'a' * 64
        info = {'architecture': 'x86_64', 'image_repository': 'ghcr.io/ra5on/titan'}
        manifest = {'format': 'titan-ucore-image-v1', 'platform': 'ucore-hci',
                    'version': '0.4.0', 'release_stage': 'alpha', 'architecture': 'x86_64',
                    'image': image, 'boot_test': 'passed', 'runtime_test': 'passed'}
        self.assertEqual(validate_image_manifest(manifest, info), image)
        manifest['iso'] = {name: 'passed' for name in
                           ('boot_test', 'install_test', 'system_boot_test', 'runtime_test')}
        self.assertEqual(validate_image_manifest(manifest, info), image)

    def test_fresh_machine_presets_enable_nas_and_disable_unconfigured_ssh(self):
        rules = dict(line.split(maxsplit=1)[::-1] for line in
                     (ROOT/'legacy/ucore/image/00-00-titan.preset').read_text().splitlines()
                     if line and not line.startswith('#'))
        for service in ('firstboot','runtime','agent','web','proxy'):
            self.assertEqual(rules['titan-'+service+'.service'], 'enable')
        for service in ('docker.service','smb.service','virtqemud.socket','firewalld.service'):
            self.assertEqual(rules[service], 'enable')
        for service in ('sshd.service','sshd.socket','zincati.service','bootc-fetch-apply-updates.timer'):
            self.assertEqual(rules[service], 'disable')


if __name__ == '__main__':
    unittest.main()

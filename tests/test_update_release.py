"""Signed OCI-only releases work with the existing updater without IMG downloads."""
from contextlib import ExitStack, closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from titan import updates
from titan.core import Error
from titan.host import run as real_host_run

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('titan_sign_update_release', ROOT/'scripts/sign_release.py')
signing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(signing)
REPOSITORY = 'ghcr.io/ra5on/titan'
IMAGE = REPOSITORY + '@sha256:' + 'a'*64


class UpdateReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.fake_root = self.directory/'source'
        (self.fake_root/'packaging').mkdir(parents=True)
        self.key = self.directory/'private.pem'
        self.public = self.fake_root/'packaging/release-public.pem'
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'ED25519', '-out', str(self.key)],
                       check=True, capture_output=True)
        subprocess.run(['openssl', 'pkey', '-in', str(self.key), '-pubout', '-out', str(self.public)],
                       check=True, capture_output=True)
        self.release = {'tag_name': 'v'+signing.__version__, 'name': 'Titan Alpha', 'prerelease': True,
                        'html_url': 'https://github.com/ra5on/Titan/releases/tag/v'+signing.__version__,
                        'assets': [{'name': name, 'url': 'https://api.github.com/repos/ra5on/Titan/releases/assets/'+str(i)}
                                   for i, name in enumerate(('manifest.json', 'manifest.json.sig'), 1)]}

    def invoke(self, *, mode=('--update-only',), extra=()):
        arguments = ['sign_release.py', '--key', str(self.key), '--directory', str(self.directory),
                     '--image', IMAGE, '--boot-test', 'passed', '--runtime-test', 'passed', *mode, *extra]
        with patch.object(signing, 'ROOT', self.fake_root), patch.object(sys, 'argv', arguments):
            signing.main()

    def manifest(self):
        return json.loads((self.directory/'manifest.json').read_text())

    def fetch(self, url, token=None, binary=False, maximum=8*1024*1024):
        if url == 'https://api.github.com/repos/ra5on/Titan/releases?per_page=30':
            return json.dumps([self.release]).encode()
        for asset in self.release['assets']:
            if url == asset['url']:
                self.assertTrue(binary)
                content = (self.directory/asset['name']).read_bytes()
                self.assertLessEqual(len(content), maximum)
                return content
        self.fail('The updater requested an unexpected download: '+url)

    def verify(self, filename):
        return subprocess.run(['openssl', 'pkeyutl', '-verify', '-rawin', '-pubin', '-inkey', str(self.public),
                               '-in', str(self.directory/filename), '-sigfile', str(self.directory/(filename+'.sig'))],
                              capture_output=True).returncode

    def test_real_signed_update_has_no_disk_metadata_or_stale_installation_downloads(self):
        # Old media in an output directory must never silently enter an update release.
        (self.directory/'titan-0.4.0-x86_64.img.xz').write_bytes(b'stale installer')
        (self.directory/'titan-0.4.0-x86_64.iso.xz').write_bytes(b'stale ISO')
        self.invoke()
        manifest = self.manifest()
        self.assertEqual(manifest['publication'], 'update-only')
        self.assertEqual(manifest['image'], IMAGE)
        self.assertTrue(all(name not in manifest for name in ('asset', 'sha256', 'size', 'iso')))
        self.assertEqual([asset['name'] for asset in manifest['assets']], ['release-public.pem'])
        self.assertEqual([asset['kind'] for asset in manifest['assets']], ['verification-helper'])
        self.assertEqual(self.verify('manifest.json'), 0)
        self.assertEqual(self.verify('SHA256SUMS'), 0)
        self.assertNotIn('.img', (self.directory/'SHA256SUMS').read_text())
        self.assertNotIn('.iso', (self.directory/'SHA256SUMS').read_text())
        signing.require_public_release(manifest)

    def test_existing_backend_authenticates_update_only_release_using_real_signature(self):
        self.invoke()
        with patch.object(updates, 'PUBLIC_KEY', self.public), patch.object(updates, 'fetch', side_effect=self.fetch):
            manifest, assets = updates.verified_release(self.release)
        self.assertEqual(manifest, self.manifest())
        self.assertEqual(set(assets), {'manifest.json', 'manifest.json.sig'})
        self.assertEqual(updates.validate_image_manifest(manifest, {'architecture': 'x86_64',
                         'image_repository': REPOSITORY}), IMAGE)

    def test_existing_update_check_and_install_stage_exact_signed_digest_without_disk_asset(self):
        self.invoke()
        info = {'format': updates.FORMAT, 'platform': 'ucore-hci', 'version': '0.0.0',
                'release_stage': 'alpha', 'architecture': 'x86_64', 'image_repository': REPOSITORY}
        before = {'booted': {'image': REPOSITORY+':alpha', 'digest': 'sha256:'+'b'*64, 'incompatible': False},
                  'reboot_required': False, 'staged': None}
        after = {**before, 'reboot_required': True, 'staged': {'image': IMAGE, 'digest': IMAGE.split('@')[1],
                 'version': signing.__version__, 'incompatible': False}}
        database = self.directory/'configuration.sqlite3'
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute('CREATE TABLE settings (value TEXT)')
            connection.execute('INSERT INTO settings VALUES (?)', ('preserved setting',))
        staged_commands = []
        def command(arguments, **kwargs):
            if arguments[0] == 'bootc':
                staged_commands.append((arguments, kwargs))
                return ''
            self.assertEqual(arguments[0], 'openssl')
            return real_host_run(arguments, **kwargs)
        with ExitStack() as stack:
            stack.enter_context(patch.object(updates, 'PUBLIC_KEY', self.public))
            stack.enter_context(patch.object(updates, 'fetch', side_effect=self.fetch))
            stack.enter_context(patch.object(updates, 'image_info', return_value=info))
            stack.enter_context(patch.object(updates, 'system_status', side_effect=[before, before, after]))
            stack.enter_context(patch.object(updates, 'read_token', return_value=None))
            stack.enter_context(patch.object(updates, 'verify_container_policy'))
            stack.enter_context(patch.object(updates, 'BACKUP_DIRECTORY', self.directory/'backup'))
            stack.enter_context(patch('titan.host.run', side_effect=command))
            result = updates.install('ra5on/Titan', 'alpha', 'v'+signing.__version__, database)
        self.assertEqual(staged_commands, [(['bootc', 'switch', '--enforce-container-sigpolicy', IMAGE], {'timeout': 1800})])
        self.assertTrue(result['ok'])
        self.assertTrue(result['reboot_required'])
        self.assertFalse(result['automatic_reboot'])
        with closing(sqlite3.connect(result['backup'])) as connection:
            self.assertEqual(connection.execute('SELECT value FROM settings').fetchone()[0], 'preserved setting')

    def test_tampered_update_only_manifest_is_rejected_by_existing_backend(self):
        self.invoke()
        manifest = self.manifest()
        manifest['image'] = REPOSITORY+'@sha256:'+'c'*64
        (self.directory/'manifest.json').write_text(json.dumps(manifest))
        with patch.object(updates, 'PUBLIC_KEY', self.public), patch.object(updates, 'fetch', side_effect=self.fetch):
            with self.assertRaises(Error):
                updates.verified_release(self.release)

    def test_publication_mode_is_required_and_mutually_exclusive(self):
        for mode in ((), ('--update-only', '--image-file', str(self.directory/'titan-0.4.0-x86_64.img.xz'))):
            with self.subTest(mode=mode), self.assertRaises(SystemExit):
                self.invoke(mode=mode)
        self.assertFalse((self.directory/'manifest.json').exists())

    def test_update_only_mode_rejects_iso_download_arguments(self):
        with self.assertRaises(SystemExit):
            self.invoke(extra=('--iso-description', str(self.directory/'iso-download.json'),
                               '--iso-test', str(self.directory/'iso-test.json')))
        self.assertFalse((self.directory/'manifest.json').exists())

    def test_update_only_release_keeps_explicit_boot_and_runtime_publication_gates(self):
        self.invoke()
        for field in ('boot_test', 'runtime_test'):
            for outcome in ('failed', 'not-run', 'unknown', None, True):
                with self.subTest(field=field, outcome=outcome), self.assertRaises(ValueError):
                    signing.require_public_release({**self.manifest(), field: outcome})
            manifest = self.manifest()
            del manifest[field]
            with self.subTest(field=field, missing=True), self.assertRaises(ValueError):
                signing.require_public_release(manifest)

    def test_failed_runtime_can_be_signed_for_diagnostics_but_cannot_be_published(self):
        self.invoke(extra=('--runtime-test', 'failed'))
        self.assertEqual(self.manifest()['runtime_test'], 'failed')
        self.assertEqual(self.verify('manifest.json'), 0)
        with self.assertRaises(ValueError):
            signing.require_public_release(self.manifest())

    def test_update_only_publication_rejects_misleading_installation_metadata(self):
        self.invoke()
        for field, value in (('asset', 'installer.img.xz'), ('sha256', 'a'*64), ('size', 123), ('iso', {}),
                             ('assets', [{'kind': 'raw-image'}]), ('assets', [{'kind': 'iso-download'}]),
                             ('assets', None), ('assets', ['invalid'])):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                signing.require_public_release({**self.manifest(), field: value})


if __name__ == '__main__':
    unittest.main()

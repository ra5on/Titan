"""Execute update-only release selection without publishing or touching the host."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def notes_code():
    source = (ROOT / 'legacy/ucore/workflows/release-notes.yml').read_text()
    return textwrap.dedent(source.split("python3 - <<'PYNOTES'\n", 1)[1].split('\n          PYNOTES', 1)[0])


class UpdatePublicationTests(unittest.TestCase):
    def test_signer_selects_update_only_by_default_and_explicit_installer_when_requested(self):
        source = (ROOT / 'legacy/ucore/workflows/release.yml').read_text()
        section = source.split('- name: Sign system update manifest and checksums', 1)[1]
        code = 'task_distribution=' + section.split('task_distribution=', 1)[1].split("          python3 - <<'PY'", 1)[0]
        code = textwrap.dedent(code)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'dist').mkdir()
            (directory / 'scripts').mkdir()
            (directory / 'dist/image.digest').write_text('sha256:' + 'a' * 64)
            (directory / 'dist/boot-status').write_text('passed')
            (directory / 'dist/runtime-test.json').write_text('{"ok":true}')
            (directory / 'scripts/sign_release.py').write_text(
                'import json,sys\nfrom pathlib import Path\nPath("args.json").write_text(json.dumps(sys.argv[1:]))\n')
            environment = {**os.environ, 'RELEASE_VERSION': '0.4.1', 'task_key': 'fixture-key'}
            for mode in ('false', 'true'):
                with self.subTest(installer_image=mode):
                    environment['INSTALLER_IMAGE'] = mode
                    result = subprocess.run(['bash', '-e', '-c', code], cwd=directory,
                                            env=environment, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    arguments = json.loads((directory / 'args.json').read_text())
                    self.assertEqual(arguments[arguments.index('--boot-test') + 1], 'passed')
                    self.assertEqual(arguments[arguments.index('--runtime-test') + 1], 'passed')
                    if mode == 'false':
                        self.assertIn('--update-only', arguments)
                        self.assertNotIn('--image-file', arguments)
                    else:
                        self.assertNotIn('--update-only', arguments)
                        self.assertEqual(arguments[arguments.index('--image-file') + 1],
                                         'dist/titan-0.4.1-x86_64.img.xz')

    def test_routine_artifact_contains_no_disk_media(self):
        source = (ROOT / 'legacy/ucore/workflows/release.yml').read_text()
        routine = source.split('name: titan-ucore-update', 1)[1].split('      - uses:', 1)[0]
        self.assertNotIn('.img', routine)
        self.assertNotIn('.iso', routine)
        for name in ('manifest.json', 'SHA256SUMS', 'release-public.pem', 'runtime-test.json'):
            self.assertIn(name, routine)
        installer = source.split('name: titan-ucore-img', 1)[0].rsplit('      - uses:', 1)[1]
        self.assertIn("steps.release.outputs.installer_image == 'true'", installer)

    def run_notes(self, manifest, signature_ok=True):
        changes = []
        commands = []
        release = {'id': 123, 'tag_name': 'v0.4.1', 'draft': False, 'body': 'Existing notes',
                   'assets': [{'name': 'manifest.json'}, {'name': 'manifest.json.sig'}]}
        if manifest.get('asset'):
            name = manifest['asset']
            release['assets'].append({'name': name, 'size': manifest['size'],
                                      'browser_download_url': 'https://github.com/ra5on/Titan/releases/download/v0.4.1/' + name})

        def run(command, **kwargs):
            commands.append(command)
            if command[:3] == ['gh', 'release', 'download']:
                directory = Path(command[command.index('--dir') + 1])
                (directory / 'manifest.json').write_text(json.dumps(manifest))
                (directory / 'manifest.json.sig').write_bytes(b'signature fixture')
            elif command[0] == 'openssl':
                return subprocess.CompletedProcess(command, 0 if signature_ok else 1)
            elif command[:2] == ['gh', 'api']:
                changes.append(json.loads(kwargs['input']))
            else:
                self.fail('Unexpected external command: ' + str(command))
            return subprocess.CompletedProcess(command, 0)

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'docs').mkdir()
            (directory / 'docs/RELEASE-0.4.1.md').write_text('Release fixture')
            original = Path.cwd()
            try:
                os.chdir(directory)
                with patch('subprocess.check_output', return_value=json.dumps([release])), patch('subprocess.run', side_effect=run):
                    exec(compile(notes_code(), '<release notes workflow>', 'exec'), {})
            finally:
                os.chdir(original)
        return changes, commands

    def test_signed_verified_update_only_notes_are_left_without_a_fake_download(self):
        manifest = {'publication': 'update-only', 'version': '0.4.1',
                    'boot_test': 'passed', 'runtime_test': 'passed'}
        changes, commands = self.run_notes(manifest)
        self.assertEqual(changes, [])
        self.assertTrue(any(command[0] == 'openssl' for command in commands))

    def test_update_only_signature_and_release_version_are_still_checked(self):
        manifest = {'publication': 'update-only', 'version': '0.4.1',
                    'boot_test': 'passed', 'runtime_test': 'passed'}
        self.assertEqual(self.run_notes(manifest, signature_ok=False)[0], [])
        with self.assertRaisesRegex(SystemExit, 'update version does not match'):
            self.run_notes({**manifest, 'version': '0.4.2'})
        for status in ('failed', 'not-run'):
            with self.subTest(runtime=status):
                self.assertEqual(self.run_notes({**manifest, 'runtime_test': status})[0], [])

    def test_existing_img_release_keeps_verified_direct_download(self):
        name = 'titan-0.4.1-x86_64.img.xz'
        manifest = {'version': '0.4.1', 'boot_test': 'passed', 'runtime_test': 'passed',
                    'asset': name, 'size': 42}
        changes, _ = self.run_notes(manifest)
        self.assertEqual(len(changes), 1)
        self.assertEqual(set(changes[0]), {'body'})
        self.assertIn('/v0.4.1/' + name, changes[0]['body'])
        self.assertTrue(changes[0]['body'].endswith('Existing notes'))

    def test_missing_installer_is_not_silently_treated_as_update_only(self):
        manifest = {'version': '0.4.1', 'boot_test': 'passed', 'runtime_test': 'passed'}
        with self.assertRaisesRegex(SystemExit, 'download does not match'):
            self.run_notes(manifest)


if __name__ == '__main__':
    unittest.main()

"""Native acceptance stays private and uses the selected frozen product source."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NativeAcceptanceTests(unittest.TestCase):
    def test_gate_selection_reads_frozen_version_without_executing_app_code(self):
        selector = script('ci-app-source.py')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'titan').mkdir()
            source = root / 'titan/__init__.py'
            for version, expected in (('0.5.6', 'legacy'), ('0.5.7', 'legacy'), ('0.5.8', 'native'), ('0.6.0', 'native')):
                source.write_text(f"raise RuntimeError('must never import')\n__version__ = '{version}'\n")
                self.assertEqual(selector.gate_mode(root), expected)
            for version in ('0.5.8-alpha', 'latest', '0.5.8\\n', ''):
                source.write_text(f"__version__ = '{version}'\n")
                with self.subTest(version=version), self.assertRaises(ValueError):
                    selector.gate_mode(root)

    def test_fixture_wrapper_imports_and_executes_only_the_frozen_smoke(self):
        wrapper = script('smoke-compose-fixture.py')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'titan').mkdir()
            (root / 'titan/native_catalog.py').write_text('')
            (root / 'scripts').mkdir()
            (root / 'scripts/smoke-app-packages.py').write_text(
                'import json,sys\ndef main(): print(json.dumps({"source":__file__,"args":sys.argv[1:]}))\n')
            output = io.StringIO()
            with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}), patch.object(wrapper.os, 'geteuid', return_value=0), \
                    patch.object(sys, 'path', sys.path.copy()), patch.object(sys, 'argv', ['fixture', '--source-root', str(root), '--confirm-disposable-runner']), \
                    contextlib.redirect_stdout(output):
                wrapper.main()
            proof = json.loads(output.getvalue())
            self.assertEqual(proof['source'], str(root / 'scripts/smoke-app-packages.py'))
            self.assertEqual(proof['args'], ['titan-ci-compose-fixture', '--confirm-disposable-runner', '--app-backup-smoke'])

    def test_fixture_wrapper_refuses_unconfirmed_nonroot_and_nonci_execution(self):
        wrapper = script('smoke-compose-fixture.py')
        for confirmed, ci, uid in ((False, 'true', 0), (True, '', 0), (True, 'true', 1000)):
            argv = ['fixture', '--source-root', str(ROOT)] + (['--confirm-disposable-runner'] if confirmed else [])
            with self.subTest(confirmed=confirmed, ci=ci, uid=uid), patch.dict(os.environ, {'GITHUB_ACTIONS': ci}), \
                    patch.object(wrapper.os, 'geteuid', return_value=uid), patch.object(sys, 'argv', argv), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                wrapper.main()
            self.assertEqual(error.exception.code, 2)

    def test_native_workflow_has_no_live_store_download_and_legacy_gates_are_version_scoped(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/app-packages.yml').read_text())
        for name in ('legacy-package', 'legacy-cloudflared-web', 'cloudflared-token', 'compose-fixture'):
            job = workflow['jobs'][name]
            mode = 'legacy' if name.startswith('legacy-') else 'native'
            self.assertEqual(job['needs'], 'source')
            self.assertEqual(job['if'], f"needs.source.outputs.mode == '{mode}'")
            checkouts = [step for step in job['steps'] if step.get('uses', '').startswith('actions/checkout@')]
            self.assertEqual(checkouts[0]['with']['ref'], '${{ inputs.source_ref || github.sha }}')
            self.assertEqual(checkouts[1]['with']['ref'], '${{ github.sha }}')
            self.assertEqual(checkouts[1]['with']['path'], '.titan-ci-builder')
            commands = '\n'.join(step.get('run', '') for step in job['steps'])
            self.assertIn('.titan-ci-builder/scripts/ci-ubuntu-dependencies.sh', commands)
            if mode == 'native':
                self.assertNotIn('bigbear', commands.lower())
        token = '\n'.join(step.get('run', '') for step in workflow['jobs']['cloudflared-token']['steps'])
        self.assertIn('test_web_access_caddy.py', token)
        self.assertIn('test_remote_access_proxy.py', token)
        self.assertIn('scripts/smoke-cloudflare-token.py', token)
        main = yaml.safe_load((ROOT / '.github/workflows/bigbear.yml').read_text())
        self.assertNotIn('env', main)
        self.assertEqual(main['jobs']['native-apps']['uses'], './.github/workflows/app-packages.yml')

    def test_boot_fixture_injection_touches_overlay_only_and_refuses_a_dirty_raw_image(self):
        source = (ROOT / 'scripts/smoke-image.sh').read_text()
        block = re.search(r'(task_app_source=.*?\nfi)\nif \[\[ "\$\{2:-\}" == --debian-ab', source, re.S).group(1)
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            binary = work / 'bin'; binary.mkdir()
            image = work / 'distribution.raw'; image.write_bytes(b'original raw image')
            overlay = work / 'test.qcow2'; overlay.write_bytes(b'overlay')
            logs = work / 'guestfish.jsonl'
            guestfish = binary / 'guestfish'
            guestfish.write_text('#!' + sys.executable + '\nimport json,os,sys\n'
                'from pathlib import Path\n'
                'with Path(os.environ["TEST_GUESTFISH_LOG"]).open("a") as stream: stream.write(json.dumps({"argv":sys.argv[1:],"input":sys.stdin.read()})+"\\n")\n'
                'if "--ro" in sys.argv: print(os.environ.get("TEST_RAW_FIXTURE", "false"))\n')
            guestfish.chmod(0o755)
            env = {**os.environ, 'PATH': str(binary) + ':' + os.environ['PATH'], 'TEST_GUESTFISH_LOG': str(logs),
                   'TITAN_APP_SOURCE_ROOT': str(work / 'product')}
            product = work / 'product'
            (product / 'titan').mkdir(parents=True)
            (product / 'titan/__init__.py').write_text("__version__='0.5.8'\n")
            (product / 'tests/fixtures').mkdir(parents=True)
            fixture = json.loads((ROOT / 'tests/fixtures/runtime-stack-store.json').read_text())
            (product / 'tests/fixtures/runtime-stack-store.json').write_text(json.dumps(fixture))
            command = 'set -euo pipefail\ntask_dir="$1"\ntask_image="$2"\n' + block
            result = subprocess.run(['bash', '-c', command, 'smoke', str(work), str(image)], cwd=ROOT, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in logs.read_text().splitlines()]
            self.assertEqual(calls[0]['argv'], ['--ro', '-a', str(image), '-m', '/dev/sda3', 'exists', '/var/lib/titan-agent/ci-compose-fixtures.json'])
            self.assertEqual(calls[1]['argv'], ['--rw', '--format=qcow2', '-a', str(overlay), '-m', '/dev/sda3'])
            self.assertIn('chmod 0600 /var/lib/titan-agent/ci-compose-fixtures.json', calls[1]['input'])
            self.assertEqual(json.loads((work / 'ci-compose-fixtures.json').read_text()),
                {'schema': 1, 'disposable': True, 'document': fixture, 'legacy_ids': ['heimdall']})
            self.assertEqual(image.read_bytes(), b'original raw image')
            logs.unlink()
            result = subprocess.run(['bash', '-c', command, 'smoke', str(work), str(image)], cwd=ROOT,
                env={**env, 'TEST_RAW_FIXTURE': 'true'}, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(logs.read_text().splitlines()), 1)
            self.assertEqual(image.read_bytes(), b'original raw image')


if __name__ == '__main__':
    unittest.main()

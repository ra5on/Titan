"""Release gate wiring and disposable-device cleanup for real app restore CI."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

from titan.core import Error

spec = importlib.util.spec_from_file_location('titan_app_backup_smoke',
    Path(__file__).resolve().parents[1] / 'scripts/smoke-app-packages.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class AppBackupSmokeTests(unittest.TestCase):
    def test_image_gate_runs_real_restore_only_for_nextcloud(self):
        root = Path(__file__).resolve().parents[1]
        workflow = yaml.safe_load((root / '.github/workflows/app-packages.yml').read_text())
        step = next(step for step in workflow['jobs']['package']['steps']
                    if 'smoke-app-packages.py' in step.get('run', ''))
        self.assertIn("matrix.package == 'bigbear:nextcloud' && '--app-backup-smoke' || ''", step['run'])
        self.assertIn('--confirm-disposable-runner', step['run'])
        self.assertIn('--bigbear-revision', step['run'])
        dependencies = '\n'.join(step.get('run', '') for step in workflow['jobs']['package']['steps'])
        self.assertIn('e2fsprogs', dependencies)
        self.assertIn('util-linux', dependencies)

    def test_separate_ext4_loop_is_unmounted_and_detached_after_success_and_failure(self):
        for fail_body in (False, True):
            with self.subTest(fail_body=fail_body), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                target = base / 'mounted'
                target.mkdir()
                def command(args, **kwargs):
                    return '/dev/loop7\n' if args[:3] == ['losetup', '--find', '--show'] else ''
                run = Mock(side_effect=command)
                with patch.object(smoke.tempfile, 'mkdtemp', return_value=str(target)) as location:
                    def check():
                        with smoke.disposable_backup_disk(base, run) as disk:
                            self.assertEqual(disk, target)
                            self.assertEqual((base / 'backup-smoke.ext4').stat().st_size, 4 * 1024 ** 3)
                            if fail_body:
                                raise Error('acceptance failed')
                    if fail_body:
                        with self.assertRaisesRegex(Error, 'acceptance failed'):
                            check()
                    else:
                        check()
                self.assertEqual(location.call_args.kwargs['dir'], '/mnt')
                self.assertFalse((base / 'backup-smoke.ext4').exists())
                self.assertFalse(target.exists())
                commands = [call.args[0] for call in run.call_args_list]
                self.assertIn(['mount', '-t', 'ext4', '-o', 'nodev,nosuid', '/dev/loop7', str(target)], commands)
                self.assertEqual(commands[-2:], [['umount', str(target)], ['losetup', '--detach', '/dev/loop7']])
                self.assertFalse(any('tmpfs' in item for command in commands for item in command))

    def test_restore_gate_flag_cannot_run_for_another_package(self):
        with patch.object(smoke.sys, 'argv', ['smoke-app-packages.py', 'bigbear:immich', '--app-backup-smoke']), \
                self.assertRaises(SystemExit) as result:
            smoke.main()
        self.assertEqual(result.exception.code, 2)


if __name__ == '__main__':
    unittest.main()

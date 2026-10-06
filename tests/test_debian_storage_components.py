"""ZFS must match the shipped kernel and pass a current-boot runtime proof."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


components = load('debian_storage_components', 'image/debian/zfs-components.py')
runtime = load('debian_storage_runtime', 'scripts/smoke-runtime.py')
KERNEL = '6.12.64+deb13-cloud-amd64'
BOOT = 'ac01628d-1b37-4b89-aa37-cb50d2f69814'


class FilesystemBootProofTests(unittest.TestCase):
    def setUp(self):
        self.values = {
            '/sys/module/zfs/parameters/zfs_arc_max': str(1024**3),
            '/sys/module/zfs/parameters/zfs_arc_min': str(128*1024**2),
            '/proc/spl/kstat/zfs/arcstats': '13 1 0x01 114 0 0\nname type data\nsize 4 12345\n',
            '/proc/sys/kernel/random/boot_id': BOOT,
        }

    @contextlib.contextmanager
    def prepared(self):
        def command(args, **kwargs):
            return SimpleNamespace(stdout=KERNEL + ' SMP preempt mod_unload' if args[1:3] == ['-F', 'vermagic'] else '')
        with patch.object(components.os, 'geteuid', return_value=0), \
                patch.object(components.os, 'uname', return_value=SimpleNamespace(release=KERNEL)), \
                patch.object(components.shutil, 'which', side_effect=lambda name, **kwargs:'/usr/sbin/'+name), \
                patch.object(components.subprocess, 'run', side_effect=command) as execute, \
                patch.object(Path, 'read_text', side_effect=lambda path:self.values[str(path)], autospec=True), \
                patch.object(Path, 'is_dir', return_value=True):
            yield execute

    def test_fixed_boot_check_loads_exact_kernel_module_and_only_queries_pools(self):
        with self.prepared() as execute:
            value = components.check()
        calls = [call.args[0][1:] for call in execute.call_args_list]
        self.assertEqual(calls, [['zfs'], ['-F', 'vermagic', 'zfs'],
                                 ['list', '-H', '-o', 'name'], ['list', '-H', '-o', 'name']])
        self.assertTrue(value['zfs_module_matches_kernel']); self.assertTrue(value['ext4_tools'])
        self.assertTrue(value['xfs_tools']); self.assertEqual(value['zfs_arc_size_bytes'], 12345)
        self.assertEqual(value['zfs_arc_max_bytes'], 1024**3)
        self.assertFalse(any(word in ('create', 'import', 'destroy', 'mkfs.ext4', 'mkfs.xfs') for call in calls for word in call))

    def test_missing_tools_wrong_kernel_failed_modprobe_or_wrong_arc_limits_abort(self):
        with self.prepared(), patch.object(components.shutil, 'which', return_value=None), self.assertRaises(RuntimeError):
            components.check()
        with self.prepared(), patch.object(components.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['modprobe','zfs'])), self.assertRaises(subprocess.CalledProcessError):
            components.check()
        with self.prepared(), patch.object(components, 'command', return_value='6.8.0-appliance SMP'), self.assertRaises(RuntimeError):
            components.check()
        self.values['/sys/module/zfs/parameters/zfs_arc_max']='0'
        with self.prepared(), self.assertRaises(RuntimeError): components.check()

    def test_nonroot_or_unloaded_module_never_publishes_success(self):
        with self.prepared(), patch.object(components.os,'geteuid',return_value=1000), self.assertRaises(RuntimeError):
            components.check()
        with self.prepared(), patch.object(Path,'is_dir',return_value=False), self.assertRaises(RuntimeError):
            components.check()

    def test_atomic_proof_is_world_readable_without_foreign_writes(self):
        with self.prepared(): value=components.check()
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'proof.json'
            owner=SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR|0o755)
            with patch.object(Path,'stat',return_value=owner): components.publish(value,path)
            self.assertEqual(json.loads(path.read_text()),value)
            self.assertEqual(path.stat().st_mode & 0o777,0o644)
            self.assertEqual(list(path.parent.glob('.titan-storage-*')),[])
            with patch.object(Path,'stat',return_value=SimpleNamespace(st_uid=0,st_mode=stat.S_IFDIR|0o777)), self.assertRaises(RuntimeError):
                components.publish(value,path)


class RuntimeFilesystemProofTests(unittest.TestCase):
    def proof(self):
        return {'format':'titan-storage-components-v1','boot_id':BOOT,'kernel':KERNEL,
                'ext4_tools':True,'xfs_tools':True,'zfs_module_loaded':True,'zfs_module_matches_kernel':True,
                'zpool_query':True,'zfs_query':True,'zfs_arc_max_bytes':1024**3,
                'zfs_arc_min_bytes':128*1024**2,'zfs_arc_size_bytes':12345}

    def test_strict_current_proof_keeps_actual_arc_usage_in_public_evidence(self):
        client=Mock(); client.storage_components.return_value=self.proof()
        value=runtime.RuntimeSmoke(client).storage_components()
        self.assertEqual(value['zfs_arc_size_bytes'],12345)
        self.assertNotIn('boot_id',value); self.assertNotIn('format',value)

    def test_partial_foreign_or_unbounded_proof_cannot_pass(self):
        for field,value in [('zfs_module_loaded',False),('zfs_arc_max_bytes',0),('zfs_arc_size_bytes',2**64),
                            ('zfs_arc_min_bytes',True),('kernel','private/path'),('extra','secret')]:
            with self.subTest(field=field):
                client=Mock(); client.storage_components.return_value={**self.proof(),field:value}
                with self.assertRaises(runtime.SmokeFailure): runtime.RuntimeSmoke(client).storage_components()

    def read_fixed_proof(self, value, uid=0, mode=0o644):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'proof.json'; path.write_text(json.dumps(value)); path.chmod(mode)
            actual_open, actual_stat = os.open, os.fstat
            def opened(name,flags):
                self.assertEqual(name,'/run/titan-storage-components.json')
                self.assertTrue(flags & os.O_NOFOLLOW)
                return actual_open(path,flags)
            def fstat(fd):
                info=actual_stat(fd)
                return SimpleNamespace(st_mode=info.st_mode,st_uid=uid,st_size=info.st_size)
            fields={'/proc/sys/kernel/random/boot_id':BOOT,
                    '/sys/module/zfs/parameters/zfs_arc_max':str(1024**3),
                    '/sys/module/zfs/parameters/zfs_arc_min':str(128*1024**2),
                    '/proc/spl/kstat/zfs/arcstats':'name type data\nsize 4 345678\n'}
            output=io.StringIO()
            with patch.object(os,'open',side_effect=opened), patch.object(os,'fstat',side_effect=fstat), \
                    patch.object(os,'uname',return_value=SimpleNamespace(release=KERNEL)), \
                    patch.object(Path,'is_dir',return_value=True), \
                    patch.object(Path,'read_text',side_effect=lambda item:fields[str(item)],autospec=True), \
                    contextlib.redirect_stdout(output):
                exec(compile(runtime.GUEST_STORAGE_COMPONENTS,'<fixed-storage-proof>','exec'),{})
            return json.loads(output.getvalue().split('TITAN_STORAGE_COMPONENTS:')[1])

    def test_nonroot_reader_verifies_root_owned_current_boot_proof_and_live_arc_usage(self):
        value=self.read_fixed_proof(self.proof())
        self.assertEqual(value['zfs_arc_size_bytes'],345678)
        for change in ({'boot_id':'00000000-0000-0000-0000-000000000000'}, {'kernel':'6.8.0-appliance'}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                self.read_fixed_proof({**self.proof(),**change})
        for uid,mode in ((1000,0o644),(0,0o666)):
            with self.subTest(uid=uid,mode=mode), self.assertRaises(RuntimeError):
                self.read_fixed_proof(self.proof(),uid,mode)

    def test_debian_ab_run_requires_storage_components(self):
        runner=runtime.RuntimeSmoke(Mock()); runner.kvm=False
        with patch.object(runner,'run_check',side_effect=lambda name,function: (runner.record(name,'passed','fixture') or True)), contextlib.redirect_stdout(io.StringIO()):
            report=runner.run(debian_ab=True)
        self.assertIn('storage_components',{check['name'] for check in report['checks']})


class OfflineKernelBuildTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('systemd-analyze'), 'systemd-analyze required')
    def test_early_component_unit_has_no_cycle_with_official_zfs_boot_ordering(self):
        text = (ROOT/'image/debian/configure-guest.sh').read_text()
        unit = text.split("<<'ZFSUNIT'\n", 1)[1].split('\nZFSUNIT', 1)[0] + '\n'
        # Dependency projection of the official OpenZFS cache/scan/mount units:
        # https://github.com/openzfs/zfs/tree/master/etc/systemd/system
        # Commands are inert placeholders; systemd-analyze never starts them.
        early = '[Unit]\nDefaultDependencies=no\n'
        service = '[Service]\nType=oneshot\nExecStart=/usr/bin/true\n'
        imports = 'After=systemd-udev-settle.service systemd-udev-trigger.service systemd-modules-load.service cryptsetup.target multipathd.service\nBefore=zfs-import.target\nWants=systemd-udev-settle.service\n'
        units = {
            'titan-storage-components.service': unit,
            'systemd-modules-load.service': early + 'Before=sysinit.target\n' + service,
            'systemd-remount-fs.service': early + 'Before=local-fs.target\n' + service,
            'local-fs.target': early + 'Before=sysinit.target\n',
            'sysinit.target': early + 'After=local-fs.target\nWants=local-fs.target systemd-modules-load.service systemd-remount-fs.service titan-storage-components.service\n',
            'basic.target': early + 'After=sysinit.target\nRequires=sysinit.target\n',
            'multi-user.target': early + 'After=basic.target\nRequires=basic.target\nWants=titan-agent.service zfs.target\n',
            'titan-agent.service': service,
            'zfs.target': '[Unit]\nWants=zfs-import.target zfs-mount.service\n',
            'zfs-import.target': '[Unit]\nWants=zfs-import-cache.service zfs-import-scan.service\n',
            'zfs-mount.service': early + 'After=zfs-import.target systemd-remount-fs.service\nBefore=local-fs.target\n' + service,
            'zfs-import-cache.service': early + imports + 'After=systemd-remount-fs.service\n' + service,
            'zfs-import-scan.service': early + imports + service,
            'shutdown.target': early,
            'cryptsetup.target': early,
        }
        for name in ('systemd-udev-settle.service', 'systemd-udev-trigger.service', 'multipathd.service'):
            units[name] = early + service
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root/'usr/lib/systemd/system'; directory.mkdir(parents=True)
            for name, content in units.items(): (directory/name).write_text(content)
            for name in ('true', 'python3'):
                executable = root/'usr/bin'/name; executable.parent.mkdir(parents=True, exist_ok=True)
                executable.write_text('#!/bin/sh\nexit 0\n'); executable.chmod(0o755)
            command = ['systemd-analyze', '--root', str(root), '--man=no', '--generators=no',
                       'verify', 'multi-user.target', 'titan-storage-components.service', 'zfs-mount.service']
            valid = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(valid.returncode, 0, valid.stderr)
            # Prove the test detects the actual early-boot ordering hazard.
            (directory/'titan-storage-components.service').write_text(unit.replace('DefaultDependencies=no', 'DefaultDependencies=yes'))
            broken = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(broken.returncode, 0)
            self.assertIn('cycle', broken.stderr.lower())

    def test_offline_installer_matches_boot_kernel_and_discards_module_private_key(self):
        text=(ROOT/'image/debian/configure-guest.sh').read_text()
        self.assertIn('linux-headers-cloud-amd64',text); self.assertIn('linux-headers-amd64',text)
        self.assertIn('"linux-headers-$task_zfs_kernel"',text)
        self.assertIn('dkms autoinstall -k "$task_zfs_kernel" -j 2',text)
        self.assertIn('modinfo -k "$task_zfs_kernel" -F vermagic zfs',text)
        self.assertIn('rm -f /tmp/titan-zfs-build.key /tmp/titan-zfs-build.pub',text)
        self.assertNotIn('linux-headers-$(uname',text)
        self.assertNotIn('backports',text)
        self.assertIn('systemctl enable titan-storage-components.service',text)
        subprocess.run(['bash','-n',str(ROOT/'image/debian/configure-guest.sh')],check=True)

    @unittest.skipUnless(shutil.which('dpkg-deb'),'dpkg-deb required')
    def test_real_package_declares_all_filesystem_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary:
            subprocess.run(['python3',str(ROOT/'scripts/build-debian-package.py'),'--output',temporary],check=True,capture_output=True)
            package=next(Path(temporary).glob('*.deb'))
            dependencies=subprocess.check_output(['dpkg-deb','-f',str(package),'Depends'],text=True)
            for name in ('e2fsprogs','xfsprogs','zfsutils-linux','zfs-dkms'):
                self.assertIn(name,dependencies)


if __name__=='__main__': unittest.main()

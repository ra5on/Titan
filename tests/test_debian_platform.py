import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from titan import platforms, updates
from titan.core import Error
from titan.monitoring import Monitor

ROOT=Path(__file__).resolve().parents[1]

class DebianProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'image-info.json'

    def write(self, value):
        self.path.write_text(json.dumps(value))

    def test_explicit_debian_profile(self):
        self.write({'platform':'debian-preview','format':'titan-debian-preview-v1'})
        value=platforms.current(self.path)
        self.assertEqual(value.samba_unit,'smbd.service')
        self.assertEqual(value.qemu_user,'libvirt-qemu')
        self.assertEqual(value.vm_unit,'libvirtd.socket')
        self.assertEqual(value.updates,'disabled')

    def test_source_development_disables_updates(self):
        self.assertEqual(platforms.current(self.path),platforms.DEBIAN)

    def test_unknown_mixed_and_corrupt_markers_fail_closed(self):
        for value in ({'platform':'ubuntu','format':'titan-debian-preview-v1'},
                      {'platform':'debian-preview','format':'unsupported-format'},[],None):
            with self.subTest(value=value):
                self.write(value)
                with self.assertRaises(Error):platforms.current(self.path)
        self.path.write_text('{broken')
        with self.assertRaises(Error):platforms.current(self.path)

    def test_preview_cannot_enable_system_updates(self):
        self.write({'platform':'debian-preview','format':'titan-debian-preview-v1'})
        with patch('titan.debian_updates.INFO',self.path), patch('titan.host.run') as command:
            with self.assertRaises(Error):
                updates.system_status()
            self.assertTrue(all(call.args[0][0]=='openssl' for call in command.call_args_list))

    def test_monitor_queries_debian_services(self):
        host=Mock();host.directory=Path(self.temp.name)
        host.load.side_effect=lambda key,default:default
        monitor=Monitor(host,Mock())
        with patch('titan.monitoring.host_platform',return_value=platforms.DEBIAN), \
             patch.object(monitor,'_pools',return_value=([],None)), \
             patch.object(monitor,'_service',return_value={'installed':True,'active':True}) as service:
            monitor.service_status()
        self.assertIn(unittest.mock.call('smbd.service','smbd'),service.call_args_list)
        self.assertIn(unittest.mock.call('libvirtd.socket','virsh'),service.call_args_list)

@unittest.skipUnless(shutil.which('dpkg-deb'),'dpkg-deb required')
class DebianPackageTests(unittest.TestCase):
    def test_real_package_extracts_with_correct_units_and_without_instance_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            work=Path(temporary)
            subprocess.run(['python3',str(ROOT/'scripts/build-debian-package.py'),'--output',str(work)],check=True,capture_output=True)
            package=next(work.glob('*.deb'))
            target=work/'unpacked'
            subprocess.run(['dpkg-deb','--raw-extract',str(package),str(target)],check=True)
            self.assertEqual(platforms.current(target/'usr/share/titan/image-info.json'),platforms.DEBIAN)
            for name in ('titan-agent','titan-web','titan-proxy','titan-firstboot','titan-runtime'):
                text=(target/f'usr/lib/systemd/system/{name}.service').read_text()
                self.assertNotIn('SELinuxContext=',text)
                self.assertNotIn('smb.service',text)
            self.assertTrue((target/'usr/lib/titan/titan/web/index.html').is_file())
            self.assertFalse((target/'var').exists())
            self.assertFalse((target/'etc').exists())
            self.assertFalse((target/'DEBIAN/postinst').exists())
            self.assertFalse(list(target.rglob('*.pyc')))
            for item in target.rglob('*'):
                self.assertNotIn('.secrets',item.parts)
            control=(target/'DEBIAN/control').read_text()
            for dependency in ('docker.io','docker-cli','docker-compose (>= 2)','libvirt-daemon-system','samba','apparmor'):
                self.assertIn(dependency,control)
            subprocess.run(['sh','-n',str(target/'DEBIAN/preinst')],check=True)
            subprocess.run(['bash','-n',str(target/'usr/share/titan/install-components.sh')],check=True)

if __name__=='__main__':unittest.main()

class DebianImageSafetyTests(unittest.TestCase):
    def test_image_builder_refuses_normal_host_before_any_commands(self):
        import os
        env=dict(os.environ);env.pop('GITHUB_ACTIONS',None)
        result=subprocess.run(['bash',str(ROOT/'scripts/build-debian-image.sh'),'--disposable-runner'],env=env,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Requires disposable',result.stderr)

    def test_preview_smoke_explicitly_skips_inapplicable_update_and_xfs_tests(self):
        spec=importlib.util.spec_from_file_location('debian_smoke_test',ROOT/'scripts/smoke-runtime.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        smoke=module.RuntimeSmoke(Mock());smoke.kvm=False
        def check(name,function):
            smoke.record(name,'passed','mocked')
            return True
        with patch.object(smoke,'run_check',side_effect=check):
            report=smoke.run(debian_preview=True)
        states={item['name']:item['status'] for item in report['checks']}
        self.assertEqual(states['system_update_state_confirmation'],'skipped')
        self.assertEqual(states['system_disk_growth'],'skipped')
        self.assertEqual(states['runtime_components'],'passed')
        self.assertEqual(report['platform'],'debian-preview')

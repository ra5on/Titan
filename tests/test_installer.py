"""Immutable first boot and removal of legacy host installation."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('firstboot',ROOT/'image/firstboot.py')
firstboot=importlib.util.module_from_spec(spec)
spec.loader.exec_module(firstboot)


class FirstBootTests(unittest.TestCase):
    def test_endpoint_is_port_5000_and_has_one_origin(self):
        env,caddy=firstboot.endpoint('192.0.2.31')
        self.assertEqual(env,'TITAN_ORIGIN=https://192.0.2.31:5000\n')
        self.assertIn('https://192.0.2.31:5000 {',caddy)
        self.assertIn('reverse_proxy 127.0.0.1:5001',caddy)
        self.assertIn('tls internal',caddy)

    def test_address_cannot_inject_caddy_or_environment(self):
        for value in ('$(reboot)','a\nTITAN_ORIGIN=http://evil','a:5000','a/b','127.0.0.1',
                      '0.0.0.0','999.999.0.1','a..b','-evil','evil-','a.'+'b'*64,'::1'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                firstboot.endpoint(value)

    def test_dns_names_supported(self):
        self.assertEqual(firstboot.address('NAS.example.lan'),'nas.example.lan')

    def test_legacy_download_installers_fail_without_mutations(self):
        for filename in ('install.sh','bootstrap.sh'):
            result=subprocess.run(['bash',str(ROOT/filename)],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,1)
            self.assertIn('Debian 13',result.stderr)
            self.assertIn('.img',result.stderr)



    def test_firstboot_does_not_relabel_running_vm_disks(self):
        source=(ROOT/'image/firstboot.py').read_text()
        self.assertNotIn("'restorecon', '-R'",source)
        self.assertIn('virt_image_t',source)
        self.assertIn('titan_share_t',source)




"""Run the image gate against representative kernel/initrd inventories, never host disks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'image/debian/ab/verify-initramfs.sh'
DRIVERS = ['ext4', 'overlay', 'ahci', 'nvme', 'usb_storage', 'uas', 'xhci_pci',
           'virtio_pci', 'virtio_blk', 'virtio_scsi', 'megaraid_sas', 'mpt3sas']
KERNEL = '6.12.64-test-amd64'


class PortableInitramfsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'; self.bin.mkdir()
        self.initrd = self.root / 'initrd'; self.initrd.write_bytes(b'fixture')
        self.modules = {}; self.entries = []
        for i, driver in enumerate(DRIVERS):
            filename = driver.replace('_', '-') + '.ko' + ['', '.xz', '.zst', '.gz'][i % 4]
            path = self.root / 'lib/modules' / KERNEL / 'kernel/drivers' / filename
            path.parent.mkdir(parents=True, exist_ok=True); path.touch()
            self.modules[driver] = str(path)
            self.entries.append('usr/lib/modules/' + KERNEL + '/kernel/drivers/' + filename)
        self.command('modinfo', "import json,os,sys\nm=json.loads(os.environ['TITAN_TEST_MODULES'])\nv=m.get(sys.argv[-1])\nif v is None:sys.exit(1)\nprint(v)\n")
        self.command('lsinitramfs', "import os,sys\nprint(os.environ['TITAN_TEST_ENTRIES'])\nsys.exit(int(os.environ.get('TITAN_TEST_LIST_EXIT','0')))\n")

    def command(self, name, source):
        path = self.bin / name
        path.write_text('#!' + sys.executable + '\n' + source); path.chmod(0o755)

    def run_gate(self, kernel=KERNEL, **extra):
        return subprocess.run(['bash', str(SCRIPT), kernel, str(self.initrd)], capture_output=True, text=True,
            env={**os.environ, 'PATH':str(self.bin)+os.pathsep+os.environ['PATH'],
                 'TITAN_TEST_MODULES':json.dumps(self.modules),
                 'TITAN_TEST_ENTRIES':'\n'.join(self.entries), **extra})

    def test_accepts_mixed_compression_and_usr_merged_paths(self):
        result = self.run_gate(); self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_builtin_without_archived_module(self):
        self.modules['ahci'] = '(builtin)'
        self.entries = [entry for entry in self.entries if '/ahci.ko' not in entry]
        result = self.run_gate(); self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_boot_controller_is_rejected(self):
        self.entries = [entry for entry in self.entries if '/nvme.ko' not in entry]
        result = self.run_gate(); self.assertNotEqual(result.returncode, 0)
        self.assertIn('nvme', result.stderr)

    def test_missing_kernel_module_is_rejected(self):
        del self.modules['mpt3sas']
        self.assertNotEqual(self.run_gate().returncode, 0)

    def test_appliance_abi_cannot_substitute_for_shipped_kernel(self):
        other = self.root / 'other-kernel/ahci.ko'; other.parent.mkdir(); other.touch()
        self.modules['ahci'] = str(other)
        self.assertNotEqual(self.run_gate().returncode, 0)

    def test_cloud_kernel_and_failed_initrd_listing_are_rejected(self):
        self.assertNotEqual(self.run_gate(kernel='6.12.64-cloud-amd64').returncode, 0)
        self.assertNotEqual(self.run_gate(TITAN_TEST_LIST_EXIT='1').returncode, 0)

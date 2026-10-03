import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/prepare-debian-rootfs.sh'


@unittest.skipUnless(all(shutil.which(x) for x in ('mkfs.ext4','e2fsck','resize2fs','blkid')), 'ext4 tools required')
class RootfsPreparationTests(unittest.TestCase):
    def invoke(self, image, size):
        return subprocess.run(['bash',str(SCRIPT),str(image),str(size)],
                              env={**os.environ,'GITHUB_ACTIONS':'true'},capture_output=True,text=True)

    def test_real_ext4_is_expanded_and_left_clean_for_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            image=Path(temporary)/'rootfs.ext4'
            with image.open('wb') as stream:stream.truncate(32*1024**2)
            subprocess.run(['mkfs.ext4','-q','-F',str(image)],check=True,capture_output=True)
            result=self.invoke(image,64*1024**2)
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)
            self.assertEqual(image.stat().st_size,64*1024**2)
            check=subprocess.run(['e2fsck','-f','-n',str(image)],capture_output=True,text=True)
            self.assertEqual(check.returncode,0,check.stderr+check.stdout)
            # Exactly the operation that RAUC previously rejected must now work.
            resized=subprocess.run(['resize2fs',str(image)],capture_output=True,text=True)
            self.assertEqual(resized.returncode,0,resized.stderr+resized.stdout)
            self.assertIn('Nothing to do',resized.stderr+resized.stdout)
            link=Path(temporary)/'alias';link.symlink_to(image)
            self.assertNotEqual(self.invoke(link,64*1024**2).returncode,0)
            self.assertNotEqual(self.invoke(image,32*1024**2).returncode,0)
            self.assertEqual(image.stat().st_size,64*1024**2)

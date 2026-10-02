"""Offline media safety, real compression/reassembly, and signed release binding."""
import hashlib
import importlib.util
import json
import lzma
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load('titan_prepare_iso', 'prepare-iso.py')
package = load('titan_package_iso', 'package-iso.py')
restore = load('titan_restore_iso', 'restore-iso.py')
signing = load('titan_sign_iso_release', 'sign_release.py')
IMAGE = 'ghcr.io/ra5on/titan@sha256:' + 'a'*64
FIELDS = ('boot_test', 'install_test', 'system_boot_test', 'runtime_test')


class IsoInstallerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.kickstart = tomllib.loads((ROOT/'legacy/ucore/image/installer.toml').read_text())['customizations']['installer']['kickstart']['contents']
        self.contents = '%include /run/install/repo/osbuild-base.ks\n' + self.kickstart
        self.base = 'ostreecontainer --transport=oci --url=/run/install/repo/container\n%post --erroronfail\nbootc switch --mutate-in-place --transport registry ' + IMAGE + '\n%end\n'

    def test_public_iso_requires_storage_selection_and_offline_payload(self):
        prepare.check_kickstart(self.contents, self.base, IMAGE)
        self.assertIn('text\n', self.kickstart)
        self.assertIn('rootpw --lock', self.kickstart)
        self.assertNotIn('--non-interactive', self.kickstart)
        self.assertIn('test -s /run/install/repo/container/index.json', self.kickstart)

    def test_wiping_partitioning_and_unattended_public_iso_are_rejected(self):
        for command in ('clearpart --all','zerombr','autopart','part / --size=20000',
                        'ignoredisk --only-use=vda','text --non-interactive','reboot'):
            with self.subTest(command=command), self.assertRaises(ValueError):
                prepare.check_kickstart(self.contents+'\n'+command, self.base, IMAGE)
        with self.assertRaises(ValueError):
            prepare.check_kickstart(self.contents, self.base+'\nclearpart --all', IMAGE)

    def test_mismatching_remote_or_non_local_install_payload_is_rejected(self):
        with self.assertRaises(ValueError):
            prepare.check_kickstart(self.contents, self.base.replace('a'*64,'b'*64), IMAGE)
        with self.assertRaises(ValueError):
            prepare.check_kickstart(self.contents, self.base.replace('/run/install/repo/container','https://example.invalid/image'), IMAGE)

    def test_test_copy_only_partitions_one_virtual_disk_and_keeps_payload(self):
        copy = prepare.test_kickstart(self.contents)
        self.assertIn('text --non-interactive', copy)
        self.assertIn('ignoredisk --only-use=vda', copy)
        self.assertIn('clearpart --all --initlabel --disklabel=gpt --drives=vda', copy)
        for mount in ('/boot/efi', '/boot', '/'):
            self.assertRegex(copy, r'part '+re.escape(mount)+r' .*--ondisk=vda')
        self.assertTrue(copy.startswith('%include /run/install/repo/osbuild-base.ks'))
        self.assertNotIn('clearpart', self.contents)

    def test_embedded_manifest_must_match_original_signed_oci_digest(self):
        manifest = json.dumps({'config': {'digest':'sha256:'+'b'*64}, 'layers':[{'digest':'sha256:'+'c'*64}]}).encode()
        digest = 'sha256:'+hashlib.sha256(manifest).hexdigest()
        index = {'manifests':[{'digest':digest}]}
        prepare.check_payload(index,manifest,digest)
        with self.assertRaises(ValueError): prepare.check_payload(index,manifest+b' ',digest)
        with self.assertRaises(ValueError): prepare.check_payload({'manifests':[]},manifest,digest)

    def test_unattended_copy_is_refused_outside_confirmed_disposable_ci(self):
        with tempfile.TemporaryDirectory() as temporary:
            iso = Path(temporary)/'test.iso'; iso.write_bytes(b'fixture')
            arguments=['prepare-iso.py',str(iso),'--image',IMAGE,'--test-output',str(iso.with_name('copy.iso')),'--confirm-disposable-guest']
            with patch.dict(os.environ,{'GITHUB_ACTIONS':'false'}), patch.object(sys,'argv',arguments), self.assertRaises(SystemExit):
                prepare.main()
            self.assertFalse(iso.with_name('copy.iso').exists())


class IsoPreservedPayloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.payload = self.directory / 'verified-oci'
        self.blobs = self.payload / 'blobs/sha256'
        self.blobs.mkdir(parents=True)
        self.config = self.add_blob(b'{"architecture":"amd64","os":"linux"}')
        self.layer = self.add_blob(b'preserved compressed image layer fixture')
        self.manifest = json.dumps({'schemaVersion':2, 'config':self.config, 'layers':[self.layer]}).encode()
        self.digest = 'sha256:' + hashlib.sha256(self.manifest).hexdigest()
        (self.blobs / self.digest.removeprefix('sha256:')).write_bytes(self.manifest)
        (self.payload / 'index.json').write_text(json.dumps({'schemaVersion':2,'manifests':[{'digest':self.digest}]}))
        (self.payload / 'oci-layout').write_text('{"imageLayoutVersion":"1.0.0"}')

    def add_blob(self, content):
        digest = hashlib.sha256(content).hexdigest()
        (self.blobs / digest).write_bytes(content)
        return {'digest':'sha256:'+digest,'size':len(content)}

    def tearDown(self): self.temporary.cleanup()

    def test_preserved_exact_manifest_and_all_blobs_are_validated(self):
        prepare.verify_oci_layout(self.payload, self.digest)
        blob = self.blobs / self.layer['digest'].removeprefix('sha256:')
        content = blob.read_bytes()
        blob.write_bytes(b'X' + content[1:])
        with self.assertRaisesRegex(ValueError, 'signed manifest'):
            prepare.verify_oci_layout(self.payload, self.digest)

    def test_missing_size_changed_or_symlinked_blobs_are_rejected(self):
        blob = self.blobs / self.config['digest'].removeprefix('sha256:')
        content = blob.read_bytes()
        blob.unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            prepare.verify_oci_layout(self.payload, self.digest)
        blob.write_bytes(content+b' ')
        with self.assertRaisesRegex(ValueError, 'wrong size'):
            prepare.verify_oci_layout(self.payload, self.digest)
        blob.unlink()
        outside = self.directory / 'config'; outside.write_bytes(content)
        blob.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            prepare.verify_oci_layout(self.payload, self.digest)

    def test_invalid_payload_never_changes_existing_iso(self):
        iso = self.directory / 'public.iso'; iso.write_bytes(b'original ISO fixture')
        blob = self.blobs / self.layer['digest'].removeprefix('sha256:')
        blob.write_bytes(b'changed')
        with self.assertRaises(ValueError), patch.object(prepare,'run') as tool:
            prepare.replace_payload(iso, self.payload, self.digest)
        tool.assert_not_called()
        self.assertEqual(iso.read_bytes(), b'original ISO fixture')

    @unittest.skipUnless(all(shutil.which(command) for command in ('xorriso','implantisomd5','checkisomd5')),
                         'ISO remaster tools are installed only on the media-build runner.')
    def test_real_remaster_removes_old_blobs_preserves_firmware_and_updates_media_checksum(self):
        tree = self.directory / 'tree'
        (tree / 'boot').mkdir(parents=True)
        (tree / 'container').mkdir()
        (tree / 'container/obsolete').write_bytes(b'old decompressed layers')
        (tree / 'container/index.json').write_text('{"manifests":[]}')
        kickstart = tomllib.loads((ROOT/'legacy/ucore/image/installer.toml').read_text())['customizations']['installer']['kickstart']['contents']
        (tree / 'osbuild.ks').write_text('%include /run/install/repo/osbuild-base.ks\n' + kickstart)
        image = 'ghcr.io/ra5on/titan@' + self.digest
        (tree / 'osbuild-base.ks').write_text('ostreecontainer --transport=oci --url=/run/install/repo/container\n'
                                            '%post --erroronfail\nbootc switch --mutate-in-place --transport registry ' + image + '\n%end\n')
        (tree / 'boot/bios.img').write_bytes(bytes(8192))
        (tree / 'boot/efi.img').write_bytes(bytes(1024*1024))
        mbr = self.directory / 'mbr.img'; mbr.write_bytes(bytes(512))
        iso = self.directory / 'public.iso'
        prepare.run('xorriso','-as','mkisofs','-o',str(iso),'-b','boot/bios.img',
                    '-no-emul-boot','-boot-load-size','4','-boot-info-table','--grub2-boot-info',
                    '--grub2-mbr',str(mbr),'-partition_offset','16','-appended_part_as_gpt',
                    '-append_partition','2','C12A7328-F81F-11D2-BA4B-00A0C93EC93B',str(tree/'boot/efi.img'),
                    '-iso_mbr_part_type','EBD0A0A2-B9E5-4433-87C0-68B6B72699C7','-eltorito-alt-boot',
                    '-e','--interval:appended_partition_2:all::','-no-emul-boot',str(tree))
        prepare.refresh_media_checksum(iso)
        arguments = ['prepare-iso.py',str(iso),'--image',image,'--payload-dir',str(self.payload)]
        with patch.object(sys,'argv',arguments): prepare.main()
        prepare.run('checkisomd5',str(iso))
        extracted = self.directory / 'extracted'
        prepare.run('xorriso','-osirrox','on','-indev',str(iso),'-extract','/container',str(extracted))
        self.assertFalse((extracted / 'obsolete').exists())
        prepare.verify_oci_layout(extracted, self.digest)
        boot = prepare.run('xorriso','-indev',str(iso),'-report_el_torito','plain')
        report = boot.stdout + boot.stderr
        self.assertIn('BIOS',report)
        self.assertIn('UEFI',report)
        self.assertIn('/boot/bios.img',report)
        system = prepare.run('xorriso','-indev',str(iso),'-report_system_area','plain')
        self.assertIn('GPT',system.stdout+system.stderr)
        self.assertIn('grub2-mbr',system.stdout+system.stderr)
        copy = self.directory / 'test-only.iso'
        arguments = ['prepare-iso.py',str(iso),'--image',image,'--test-output',str(copy),'--confirm-disposable-guest']
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'true'}), patch.object(sys,'argv',arguments): prepare.main()
        prepare.run('checkisomd5',str(copy))
        extracted_ks = self.directory / 'test.ks'
        prepare.run('xorriso','-osirrox','on','-indev',str(copy),'-extract','/osbuild.ks',str(extracted_ks))
        self.assertIn('text --non-interactive',extracted_ks.read_text())


class IsoDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.iso = self.directory/'titan-0.4.0-x86_64.iso'
        self.data = bytes(range(256))*20
        self.iso.write_bytes(self.data)

    def tearDown(self): self.temporary.cleanup()

    def split_package(self):
        with patch.object(package,'ASSET_LIMIT',150),patch.object(package,'CHUNK_SIZE',100):
            return package.package(self.iso)

    def test_small_iso_is_one_download_and_restores_exact_content(self):
        description = package.package(self.iso)
        self.assertEqual(len(description['parts']),1)
        self.iso.unlink()
        target = restore.restore(self.directory,{'iso':description})
        self.assertEqual(target.read_bytes(),self.data)

    def test_large_iso_is_split_in_order_and_restores_identical_bootable_bytes(self):
        description = self.split_package()
        self.assertGreater(len(description['parts']),1)
        self.assertFalse(self.iso.with_name(self.iso.name+'.xz').exists())
        self.assertTrue(all(part['size']<=100 for part in description['parts']))
        combined = b''.join((self.directory/part['name']).read_bytes() for part in description['parts'])
        self.assertEqual(hashlib.sha256(combined).hexdigest(), description['sha256'])
        self.iso.unlink()
        self.assertEqual(restore.restore(self.directory,{'iso':description}).read_bytes(),self.data)

    def test_tampered_or_missing_piece_does_not_create_an_iso(self):
        description = self.split_package(); self.iso.unlink()
        piece = self.directory/description['parts'][0]['name']
        original = piece.read_bytes(); piece.write_bytes(b'X'+original[1:])
        with self.assertRaises(ValueError): restore.restore(self.directory,{'iso':description})
        self.assertFalse(self.iso.exists())
        piece.unlink()
        with self.assertRaises(ValueError): restore.restore(self.directory,{'iso':description})

    def test_paths_and_wrong_order_are_rejected(self):
        description = self.split_package(); self.iso.unlink()
        description['parts'].reverse()
        with self.assertRaises(ValueError): restore.restore(self.directory,{'iso':description})
        description['filename']='../outside.iso'
        with self.assertRaises(ValueError): restore.restore(self.directory,{'iso':description})

    def test_wrong_restored_hash_removes_partial_file(self):
        description = package.package(self.iso); self.iso.unlink()
        description['uncompressed_sha256']='f'*64
        with self.assertRaises(ValueError): restore.restore(self.directory,{'iso':description})
        self.assertFalse(self.iso.exists())
        self.assertFalse(self.iso.with_name(self.iso.name+'.restoring').exists())

    def test_existing_output_is_preserved(self):
        description = package.package(self.iso)
        with self.assertRaises(ValueError): restore.restore(self.directory,{'iso':description})
        self.assertEqual(self.iso.read_bytes(),self.data)

    def test_dangling_output_and_temporary_symlinks_are_preserved(self):
        description = package.package(self.iso); self.iso.unlink()
        temporary = self.iso.with_name(self.iso.name+'.restoring')
        for path in (self.iso, temporary):
            with self.subTest(path=path.name):
                path.symlink_to(self.directory/'missing')
                with self.assertRaisesRegex(ValueError, 'Refusing'):
                    restore.restore(self.directory, {'iso':description})
                self.assertTrue(path.is_symlink())
                path.unlink()

    def test_late_destination_cannot_overwrite_an_existing_file_or_symlink(self):
        description = package.package(self.iso); self.iso.unlink()
        actual_link = os.link
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                def collision(source, target, **kwargs):
                    if symlink: target.symlink_to(self.directory/'missing')
                    else: target.write_bytes(b'keep existing destination')
                    return actual_link(source, target, **kwargs)
                with patch.object(restore.os, 'link', side_effect=collision):
                    with self.assertRaises(FileExistsError):
                        restore.restore(self.directory, {'iso':description})
                if symlink: self.assertTrue(self.iso.is_symlink())
                else: self.assertEqual(self.iso.read_bytes(), b'keep existing destination')
                self.assertFalse(self.iso.with_name(self.iso.name+'.restoring').exists())
                self.iso.unlink()

    def test_temporary_created_by_another_writer_after_check_is_preserved(self):
        description = package.package(self.iso); self.iso.unlink()
        temporary = self.iso.with_name(self.iso.name+'.restoring')
        actual_open = Path.open
        def collision(path, *args, **kwargs):
            if path == temporary and args == ('xb',):
                path.write_bytes(b'other writer')
            return actual_open(path, *args, **kwargs)
        with patch.object(Path, 'open', collision):
            with self.assertRaises(FileExistsError):
                restore.restore(self.directory, {'iso':description})
        self.assertEqual(temporary.read_bytes(), b'other writer')
        self.assertFalse(self.iso.exists())


class IsoReleaseSignatureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.fake_root = self.directory/'source'
        (self.fake_root/'scripts').mkdir(parents=True)
        (self.fake_root/'scripts/restore-iso.py').write_bytes((ROOT/'scripts/restore-iso.py').read_bytes())
        (self.fake_root/'packaging').mkdir()
        self.key = self.directory/'private.pem'
        self.public = self.fake_root/'packaging/release-public.pem'
        subprocess.run(['openssl','genpkey','-algorithm','ED25519','-out',str(self.key)],check=True,capture_output=True)
        subprocess.run(['openssl','pkey','-in',str(self.key),'-pubout','-out',str(self.public)],check=True,capture_output=True)
        self.iso = self.directory/'titan-0.4.0-x86_64.iso'; self.iso.write_bytes(bytes(range(256))*20)
        with patch.object(package,'ASSET_LIMIT',150),patch.object(package,'CHUNK_SIZE',100):
            self.description = package.package(self.iso)
        self.report = {name:'passed' for name in FIELDS}
        (self.directory/'iso-test.json').write_text(json.dumps(self.report))
        self.raw = self.directory/'titan-0.4.0-x86_64.img.xz'; self.raw.write_bytes(lzma.compress(b'raw test fixture'))

    def tearDown(self): self.temporary.cleanup()

    def invoke(self, *, include_iso=True, extra=()):
        args=['sign_release.py','--key',str(self.key),'--directory',str(self.directory),'--image',IMAGE,
              '--image-file',str(self.raw),'--boot-test','passed','--runtime-test','passed']
        if include_iso:
            args += ['--iso-description',str(self.directory/'iso-download.json'),
                     '--iso-test',str(self.directory/'iso-test.json')]
        args += list(extra)
        with patch.object(signing,'ROOT',self.fake_root),patch.object(sys,'argv',args): signing.main()

    def verify(self, name):
        return subprocess.run(['openssl','pkeyutl','-verify','-rawin','-pubin','-inkey',str(self.public),
                               '-in',str(self.directory/name),'-sigfile',str(self.directory/(name+'.sig'))],capture_output=True).returncode

    def test_manifest_and_checksum_signatures_bind_img_and_all_iso_pieces(self):
        self.invoke()
        self.assertEqual(self.verify('manifest.json'),0)
        self.assertEqual(self.verify('SHA256SUMS'),0)
        manifest=json.loads((self.directory/'manifest.json').read_text())
        self.assertEqual(manifest['asset'],self.raw.name)
        self.assertEqual(manifest['iso']['parts'],self.description['parts'])
        self.assertEqual(manifest['iso']['uncompressed_sha256'],hashlib.sha256(self.iso.read_bytes()).hexdigest())
        self.assertTrue(all(manifest['iso'][name]=='passed' for name in FIELDS))
        sums=(self.directory/'SHA256SUMS').read_text()
        for name in [self.raw.name,self.iso.name]+[part['name'] for part in self.description['parts']]: self.assertIn(name,sums)
        (self.directory/'SHA256SUMS').write_text(sums.replace(self.raw.name,'modified.img.xz'))
        self.assertNotEqual(self.verify('SHA256SUMS'),0)

    def test_modified_iso_piece_cannot_be_signed(self):
        piece=self.directory/self.description['parts'][0]['name']; piece.write_bytes(b'tampered')
        with self.assertRaises(ValueError): self.invoke()
        self.assertFalse((self.directory/'manifest.json').exists())

    def test_img_only_release_has_signed_image_and_public_key_without_iso_helpers(self):
        # Stale historical ISO files are deliberately present in the output directory.
        self.invoke(include_iso=False)
        self.assertEqual(self.verify('manifest.json'),0)
        self.assertEqual(self.verify('SHA256SUMS'),0)
        manifest=json.loads((self.directory/'manifest.json').read_text())
        self.assertNotIn('iso',manifest)
        self.assertEqual(manifest['asset'],self.raw.name)
        self.assertEqual([asset['name'] for asset in manifest['assets']],
                         [self.raw.name,'release-public.pem'])
        self.assertEqual([asset['kind'] for asset in manifest['assets']],
                         ['raw-image','verification-helper'])
        self.assertFalse((self.directory/'restore-iso.py').exists())
        self.assertNotIn('.iso',(self.directory/'SHA256SUMS').read_text())
        signing.require_public_release(manifest)

    def test_optional_iso_metadata_must_be_provided_as_complete_pair(self):
        for option, filename in (('--iso-description','iso-download.json'),('--iso-test','iso-test.json')):
            with self.subTest(option=option),self.assertRaises(SystemExit):
                self.invoke(include_iso=False,extra=(option,str(self.directory/filename)))
        self.assertFalse((self.directory/'manifest.json').exists())

    def test_standalone_helper_checks_signature_then_restores_the_iso(self):
        self.invoke(); self.iso.unlink()
        command=[sys.executable,str(ROOT/'scripts/restore-iso.py'),'--directory',str(self.directory),'--key',str(self.public)]
        result=subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Verified bootable ISO ready:',result.stdout)
        self.assertEqual(self.iso.read_bytes(),bytes(range(256))*20)
        self.iso.unlink()
        path=self.directory/'manifest.json'
        path.write_text(path.read_text().replace('"platform": "ucore-hci"','"platform": "modified"'))
        result=subprocess.run(command,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('signature verification failed',result.stderr.lower())
        self.assertFalse(self.iso.exists())

    def test_missing_outcome_is_rejected_instead_of_claimed_success(self):
        del self.report['install_test']
        with self.assertRaises(ValueError): signing.iso_metadata(self.directory,self.description,self.report)

    def test_boot_failure_is_signed_as_failure_for_artifacts(self):
        self.report['system_boot_test']='failed'
        actual=signing.iso_metadata(self.directory,self.description,self.report)
        self.assertEqual(actual['system_boot_test'],'failed')


class IsoPublicReleaseGateTests(unittest.TestCase):
    def test_img_only_publication_requires_both_explicit_passed_outcomes(self):
        for field in ('boot_test','runtime_test'):
            for status in ('failed','not-run','unknown',None,True):
                manifest={'boot_test':'passed','runtime_test':'passed',field:status}
                with self.subTest(field=field,status=status),self.assertRaises(ValueError):
                    signing.require_public_release(manifest)
            manifest={'boot_test':'passed','runtime_test':'passed'}
            del manifest[field]
            with self.subTest(field=field,missing=True),self.assertRaises(ValueError):
                signing.require_public_release(manifest)

    def test_release_upload_skips_empty_optional_errors_and_requires_nonempty_assets(self):
        source=(ROOT/'legacy/ucore/workflows/release.yml').read_text()
        section=source.split('- name: Publish signed system image with test status',1)[1]
        code='task_assets=('+section.split('task_assets=(',1)[1].split('          gh release create',1)[0]
        code=textwrap.dedent(code)+'\nprintf "%s\\n" "${task_assets[@]}"\n'
        required=('release-public.pem','manifest.json','manifest.json.sig',
                  'SHA256SUMS','SHA256SUMS.sig','boot-test.json','boot-console.log','runtime-test.json')
        optional=('boot-http-error.txt',)
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);dist=directory/'dist';dist.mkdir()
            for name in required: (dist/name).write_bytes(b'nonempty fixture')
            for name in optional: (dist/name).touch()
            environment={**os.environ,'INSTALLER_IMAGE':'false','RELEASE_VERSION':'0.4.0'}
            def invoke(): return subprocess.run(['bash','-e','-c',code],cwd=directory,env=environment,capture_output=True,text=True)
            # An old disk file must never leak into a routine update publication.
            image=dist/'titan-0.4.0-x86_64.img.xz';image.write_bytes(b'old image fixture')
            result=invoke();self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(set(result.stdout.splitlines()),{'dist/'+name for name in required})
            for name in optional: (dist/name).write_bytes(b'actual error fixture')
            result=invoke();self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(set(result.stdout.splitlines()),{'dist/'+name for name in required+optional})
            for name in required:
                with self.subTest(name=name):
                    path=dist/name;path.write_bytes(b'')
                    result=invoke();self.assertNotEqual(result.returncode,0)
                    self.assertIn('Missing or empty required release asset:',result.stderr)
                    path.write_bytes(b'nonempty fixture')
            environment['INSTALLER_IMAGE']='true'
            result=invoke();self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(set(result.stdout.splitlines()),{'dist/'+name for name in required+optional+(image.name,)})
            image.write_bytes(b'')
            self.assertNotEqual(invoke().returncode,0)
            image.unlink()
            self.assertNotEqual(invoke().returncode,0)
            environment['INSTALLER_IMAGE']='false'
            self.assertEqual(invoke().returncode,0)
            (dist/'runtime-test.json').unlink()
            self.assertNotEqual(invoke().returncode,0)

    def test_future_pipeline_tests_oci_and_only_optionally_publishes_img(self):
        source=(ROOT/'legacy/ucore/workflows/release.yml').read_text()
        for marker in ('anaconda-iso','smoke-iso.sh','package-iso.py','--iso-description',
                       'dist/*.iso.xz*','dist/restore-iso.py'):
            self.assertNotIn(marker,source)
        self.assertIn('bash scripts/smoke-image.sh',source)
        self.assertIn('--boot-test "$(cat dist/boot-status)"',source)
        self.assertIn('--runtime-test',source)
        self.assertIn('name: titan-ucore-img',source)
        self.assertIn('name: titan-ucore-update',source)
        self.assertIn('installer_image:',source)
        self.assertIn('default: false',source)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.installer_image || false",source)
        self.assertIn('task_distribution=(--update-only)',source)
        compress=source.split('- name: Compress the tested raw image',1)[1].split('- name:',1)[0]
        self.assertIn("steps.release.outputs.installer_image == 'true'",compress)
        self.assertIn("steps.boot.outcome == 'success'",compress)
        self.assertLess(source.index('bash scripts/smoke-image.sh'),
                        source.index('- name: Compress the tested raw image'))

    def test_every_incomplete_img_or_iso_result_blocks_public_release_even_alpha(self):
        source=(ROOT/'legacy/ucore/workflows/release.yml').read_text()
        section=source.split('- name: Require verified system update before public release',1)[1].split('- name: Publish signed system image',1)[0]
        code=textwrap.dedent(section.split("python3 - <<'PY'\n",1)[1].split('\n          PY',1)[0])
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary); (directory/'dist').mkdir()
            path=directory/'dist/manifest.json'
            manifest={'release_stage':'alpha','boot_test':'passed','runtime_test':'passed'}
            path.write_text(json.dumps(manifest))
            environment={**os.environ,'PYTHONPATH':str(ROOT)}
            def invoke(): return subprocess.run([sys.executable,'-c',code],cwd=directory,env=environment,capture_output=True)
            self.assertEqual(invoke().returncode,0)
            manifest['iso']={name:'passed' for name in FIELDS}
            path.write_text(json.dumps(manifest))
            self.assertEqual(invoke().returncode,0)
            for group,field in [(None,'boot_test'),(None,'runtime_test')]+[('iso',name) for name in FIELDS]:
                for status in ('failed','not-run','unknown',None,True):
                    with self.subTest(group=group,field=field,status=status):
                        target=manifest[group] if group else manifest
                        target[field]=status; path.write_text(json.dumps(manifest))
                        self.assertNotEqual(invoke().returncode,0)
                        target[field]='passed'
                target=manifest[group] if group else manifest
                target.pop(field)
                path.write_text(json.dumps(manifest))
                self.assertNotEqual(invoke().returncode,0)
                target[field]='passed'
            for iso in (None, [], 'passed'):
                manifest['iso']=iso
                path.write_text(json.dumps(manifest))
                self.assertNotEqual(invoke().returncode,0)
            path.unlink()
            self.assertNotEqual(invoke().returncode,0)

    def test_iso_smoke_never_passes_host_disks_to_qemu(self):
        source=(ROOT/'scripts/smoke-iso.sh').read_text()
        self.assertIn('GITHUB_ACTIONS',source)
        self.assertIn('--confirm-disposable-guest',source)
        self.assertIn('restrict=on',source)
        self.assertIn('truncate -s 32G "$task_dir/installed.img"',source)
        self.assertIn('stat -c %b',source)
        self.assertNotIn('file=/dev/',source)
        self.assertNotIn('virtfs',source)


if __name__ == '__main__': unittest.main()

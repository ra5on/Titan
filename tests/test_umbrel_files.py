import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from titan.core import Error
from titan.umbrel_files import validate, install
from titan.umbrel_catalog import archive_inventory, compile_inventory, URL
from titan.store_recipes import recipes
from test_umbrel_catalog import archive, package, REVISION

SLOT = 'umbrel-' + 'a' * 20

def seed(path='config.json', data=b'{"enabled":true}', slot=SLOT):
    return {'slot': slot, 'path': path, 'sha256': hashlib.sha256(data).hexdigest(),
            'content': base64.b64encode(data).decode(), 'mode': 0o644}


class SeedFilesTests(unittest.TestCase):
    def test_integrity_paths_duplicates_and_size_rejected_before_filesystem(self):
        for changes in ({'path':'../escape'}, {'path':'/etc/shadow'}, {'path':'a//b'},
                        {'path':'./file'}, {'slot':'data'}, {'mode':0o4755},
                        {'sha256':'0'*64}, {'content':'not base64'}, {'content':None}):
            with self.subTest(changes=changes), self.assertRaises(Error):
                validate([{**seed(), **changes}])
        for rows in ([seed(), seed()], [seed('a'), seed('a/b')],
                     [seed(data=b'x'*(1024**2+1))]):
            with self.assertRaises(Error): validate(rows)

    def test_compiled_seed_file_content_is_preserved_and_frozen(self):
        files = package(); files['example/data/nested/config.json'] = '{"example":1}'
        document, blocked = compile_inventory(archive_inventory(archive(files), REVISION))
        self.assertEqual(blocked, [])
        recipe = next(iter(recipes(document, URL)[1].values()))
        row = recipe['seed_files'][0]
        self.assertEqual(row['path'], 'nested/config.json')
        self.assertEqual(validate([row])[0][1], b'{"example":1}')
        altered = copy.deepcopy(document)
        altered['apps'][0]['seed_files'][0]['sha256'] = '0'*64
        with self.assertRaises(Error): recipes(altered, URL)

    def test_directory_and_file_mounts_are_seeded_without_overwriting_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            definition = {'services': {'web': {'volumes': [{'source': str(root/SLOT)}]}}}
            install(root, [seed('nested/config.json')], definition, os.getuid(), os.getgid())
            path = root/SLOT/'nested/config.json'
            self.assertEqual(path.read_bytes(), b'{"enabled":true}')
            path.write_bytes(b'changed by app'); path.chmod(0o600)
            install(root, [seed('nested/config.json', b'new defaults')], definition, os.getuid(), os.getgid())
            self.assertEqual(path.read_bytes(), b'changed by app')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            file_slot = 'umbrel-'+'b'*20
            definition['services']['web']['volumes'].append({'source': str(root/file_slot)})
            install(root, [seed('', b'file mount', file_slot)], definition, os.getuid(), os.getgid())
            self.assertEqual((root/file_slot).read_bytes(), b'file mount')
            self.assertFalse(list(root.rglob('.titan-seed-*')))

    def test_symlink_hardlink_and_directory_collisions_never_touch_external_files(self):
        for kind in ('parent-symlink','leaf-symlink','hardlink','directory'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)/'config';root.mkdir()
                external = Path(temp)/'outside';external.mkdir()
                secret = external/'config.json';secret.write_bytes(b'private')
                if kind == 'parent-symlink': (root/SLOT).symlink_to(external, target_is_directory=True)
                else:
                    (root/SLOT).mkdir();leaf=root/SLOT/'config.json'
                    if kind == 'leaf-symlink': leaf.symlink_to(secret)
                    elif kind == 'hardlink': os.link(secret, leaf)
                    else: leaf.mkdir()
                definition={'services':{'web':{'volumes':[{'source':str(root/SLOT)}]}}}
                with self.assertRaises((Error, OSError)):
                    install(root,[seed()],definition,os.getuid(),os.getgid())
                self.assertEqual(secret.read_bytes(), b'private')

    def test_private_signing_identity_is_generated_once_per_installation(self):
        import yaml
        row = {**seed('selfhosted.yaml', b'jwt:\n  secret: public-catalog-default\nserver:\n  port: 2021\n'),
               'personalize': 'yaml-jwt-secret'}
        keys = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp); definition={'services':{'web':{'volumes':[{'source':str(root/SLOT)}]}}}
                install(root, [row], definition, os.getuid(), os.getgid())
                path=root/SLOT/'selfhosted.yaml'; data=yaml.safe_load(path.read_bytes())
                self.assertEqual(data['server']['port'], 2021)
                self.assertRegex(data['jwt']['secret'], r'^[a-f0-9]{64}$')
                before=path.read_bytes(); install(root, [row], definition, os.getuid(), os.getgid())
                self.assertEqual(path.read_bytes(), before)
                keys.append(data['jwt']['secret'])
        self.assertNotEqual(*keys)

    def test_missing_mount_and_corrupt_content_fail_without_creating_any_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with self.assertRaises(Error): install(root,[seed()],{'services':{}},os.getuid(),os.getgid())
            self.assertEqual(list(root.iterdir()), [])
            with self.assertRaises(Error): install(root,[{**seed(),'sha256':'0'*64}],{'services':{}},os.getuid(),os.getgid())
            self.assertEqual(list(root.iterdir()), [])

if __name__=='__main__':unittest.main()

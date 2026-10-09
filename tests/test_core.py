from update_fixtures import identity, manifest, state
import base64
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
from titan.core import Error, Store, identifier, password_hash, password_matches
from titan.files import operate
from titan.host import Host
from titan.rpc import receive, send
from titan.updates import version, validate_url, check


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def setup_admin(self): self.store.setup("admin", "long-enough-password")
    def test_setup_needs_valid_credentials_but_no_local_token(self):
        self.assertFalse(self.store.setup_file.exists())
        with self.assertRaises(Error): self.store.setup("../invalid", "long-enough-password")
        with self.assertRaises(Error): self.store.setup("admin", "short")
        self.assertEqual(self.store.users(), [])
    def test_setup_is_single_use(self):
        self.setup_admin()
        self.assertFalse(self.store.setup_file.exists())
        with self.assertRaises(Error) as error: self.store.setup("other", "long-enough-password")
        self.assertEqual(error.exception.status, 409)

    def test_first_admin_creation_is_atomic_across_store_instances(self):
        other = Store(self.temp.name)
        barrier = threading.Barrier(2)
        results = []
        def create(store, name):
            barrier.wait()
            try:
                store.setup(name, "long-enough-password")
                results.append((name, 200))
            except Error as error:
                results.append((name, error.status))
        threads = [threading.Thread(target=create, args=(store, name))
                   for store, name in ((self.store, "first"), (other, "second"))]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(sorted(status for _, status in results), [200, 409])
        self.assertEqual(len(self.store.users()), 1)
        self.assertEqual(self.store.users()[0]["role"], "admin")

    def test_old_code_is_discarded_without_changing_existing_accounts(self):
        self.setup_admin()
        self.store.setup_file.write_text("obsolete-local-code")
        restarted = Store(self.temp.name)
        self.assertFalse(restarted.setup_file.exists())
        token, _ = restarted.login("admin", "long-enough-password")
        self.assertEqual(restarted.session(token)["name"], "admin")
    def test_authentication_and_logout(self):
        self.setup_admin()
        with self.assertRaises(Error): self.store.login("admin", "incorrect-password")
        token, csrf = self.store.login("admin", "long-enough-password")
        self.assertEqual(self.store.session(token)["csrf"], csrf)
        with self.store.connection() as db:
            self.assertNotEqual(db.execute("SELECT token FROM sessions").fetchone()[0], token)
        self.store.logout(token)
        self.assertIsNone(self.store.session(token))
    def test_passwords_are_salted(self):
        one, two = password_hash("long-enough-password"), password_hash("long-enough-password")
        self.assertNotEqual(one, two)
        self.assertTrue(password_matches("long-enough-password", one))
        self.assertFalse(password_matches("wrong-password", one))
    def test_legacy_password_hash_is_accepted_and_upgraded_on_login(self):
        import hashlib
        self.setup_admin()
        salt = "ab" * 16
        legacy = salt + ":" + hashlib.scrypt(b"long-enough-password", salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        with self.store.connection() as db:
            db.execute("UPDATE users SET password=? WHERE name='admin'", (legacy,))
        self.assertTrue(password_matches("long-enough-password", legacy))
        self.assertFalse(password_matches("incorrect-password", legacy))
        self.store.login("admin", "long-enough-password")
        with self.store.connection() as db:
            upgraded = db.execute("SELECT password FROM users WHERE name='admin'").fetchone()[0]
        self.assertTrue(upgraded.startswith("scrypt$65536$8$2$"))
        self.assertTrue(password_matches("long-enough-password", upgraded))
        self.assertFalse(password_matches("incorrect-password", upgraded))
    def test_malformed_or_downgraded_hashes_never_match(self):
        for stored in ("", "garbage", "scrypt$1$1$1$00$00", "scrypt$16384$8$1$" + "00" * 16 + "$00", None):
            self.assertFalse(password_matches("long-enough-password", stored))
    def test_identifier_rejects_shell_and_path_payloads(self):
        for name in ("root; reboot", "../../root", "-bad", "bad\nname", "$(id)"):
            with self.assertRaises(Error): identifier(name)
    def test_settings_validate_types(self):
        for value in ({"auto_check": "false"}, {"channel": "evil"}, {"window_hour": 25}, {"repository": "https://evil"}, {"unknown": True}):
            with self.assertRaises(Error): self.store.save_settings(value)
        self.assertFalse(self.store.save_settings({"auto_check": False})["auto_check"])
    def test_pending_jobs_become_failed_after_restart(self):
        with self.store.connection() as db:
            db.execute("INSERT INTO jobs VALUES ('a',0,'admin','scrub','running','{}')")
        restarted = Store(self.temp.name)
        self.assertEqual(restarted.jobs()[0]["status"], "failed")


class FilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "share"
        self.root.mkdir()
        (self.root / "hello.txt").write_text("hello")
    def tearDown(self): self.temp.cleanup()
    def test_root_directory_listing(self):
        self.assertEqual(operate(self.root, "list")["entries"][0]["name"], "hello.txt")
    def test_read_respects_range(self):
        result = operate(self.root, "read", "hello.txt", offset=1, size=3)
        self.assertEqual(base64.b64decode(result["data"]), b"ell")
        self.assertEqual(result["total"], 5)
    def test_path_traversal_rejected(self):
        for path in ("../secret", "/etc/passwd", "a/../../secret", "bad\x00name"):
            with self.assertRaises(Error): operate(self.root, "read", path)
    def test_symlinks_and_symlink_ancestors_rejected(self):
        (self.root / "link").symlink_to("/etc/passwd")
        (self.root / "outside").symlink_to("/etc", target_is_directory=True)
        for path in ("link", "outside/passwd"):
            with self.assertRaises((Error, OSError)): operate(self.root, "read", path)
    def test_chunked_upload_does_not_overwrite(self):
        one = operate(self.root, "upload", "new.txt", offset=0, data=base64.b64encode(b"abc").decode())
        self.assertEqual(one["offset"], 3)
        operate(self.root, "upload", "new.txt", offset=3, data=base64.b64encode(b"def").decode())
        self.assertEqual((self.root / "new.txt").read_bytes(), b"abcdef")
        with self.assertRaises(FileExistsError): operate(self.root, "upload", "new.txt", offset=0, data="")
        with self.assertRaises(Error): operate(self.root, "upload", "new.txt", offset=2, data="")
    def test_trash_can_be_restored(self):
        result = operate(self.root, "trash", "hello.txt")
        self.assertFalse((self.root / "hello.txt").exists())
        self.assertEqual(len(operate(self.root, "trash_list")["entries"]), 1)
        operate(self.root, "restore", trash_name=result["trash_name"], destination="hello.txt")
        self.assertEqual((self.root / "hello.txt").read_text(), "hello")
    def test_cannot_modify_share_root(self):
        for operation in ("trash", "rename", "mkdir"):
            with self.assertRaises(Error): operate(self.root, operation, "", destination="new")
    def test_rename_does_not_replace_existing(self):
        (self.root / "other.txt").write_text("other")
        with self.assertRaises(Error): operate(self.root, "rename", "hello.txt", destination="other.txt")
        self.assertEqual((self.root / "other.txt").read_text(), "other")


class HostValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.host = Host(self.temp.name, self.temp.name, self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def test_no_arbitrary_operations(self):
        with self.assertRaises(Error): self.host.dispatch("exec", command="id")
    def test_mounted_or_partitioned_disks_rejected(self):
        for disk in ({"name":"/dev/sda","type":"disk","fstype":None,"mountpoints":["/"]},
                     {"name":"/dev/sda","type":"disk","fstype":None,"children":[{"name":"/dev/sda1"}]}):
            with patch.object(self.host, "disks", return_value=[disk]), patch("titan.host.run") as run:
                with self.assertRaises(Error): self.host.op_pool_create("tank", "mirror", ["/dev/sda","/dev/sdb"], "tank")
                run.assert_not_called()
    def test_disk_confirmation_required(self):
        with self.assertRaises(Error): self.host.op_pool_create("tank", "mirror", ["/dev/sda","/dev/sdb"], "wrong")
    def test_smb_readers_cannot_write(self):
        self.host.save("shares", [{"name":"shared","path":"/tmp","readers":["reader"],"writers":["writer"]}])
        with self.assertRaises(Error) as error: self.host.op_file("reader", "shared", "upload", "a", data="")
        self.assertEqual(error.exception.status, 403)
    def test_unlisted_user_cannot_read(self):
        self.host.save("shares", [{"name":"shared","path":"/tmp","readers":[],"writers":["writer"]}])
        with self.assertRaises(Error): self.host.op_file("intruder", "shared", "read", "a")


class UpdatesTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch("titan.debian_updates.image_info", return_value=identity()).start()
        patch("titan.debian_updates.system_status", return_value=state()).start()
        def verified(release, token):
            return (manifest(release['tag_name'], 'beta' if '-beta.' in release['tag_name'] else 'stable'), {'titan-test-amd64.raucb':'https://github.com/x/y/bundle'})
        patch("titan.updates.verified_release", side_effect=verified).start()
    def test_semantic_version_sort(self):
        self.assertGreater(version("v0.10.0"), version("v0.9.9"))
        self.assertGreater(version("v1.0.0"), version("v1.0.0-beta.5"))
        self.assertGreater(version("v1.0.0-beta.10"), version("v1.0.0-beta.2"))
    def test_download_host_allowlist(self):
        for url in ("http://github.com/x", "https://evil.com/x", "https://github.com.evil.com/x", "https://user@github.com/x", "https://github.com:444/x"):
            with self.assertRaises(Error): validate_url(url)
        validate_url("https://release-assets.githubusercontent.com/file")
    def test_stable_channel_excludes_prereleases(self):
        releases = [{"tag_name":"v0.2.0","draft":False,"prerelease":False,"body":"stable","html_url":"https://github.com/x/y","assets":[]},
                    {"tag_name":"v0.3.0-beta.1","draft":False,"prerelease":True,"html_url":"https://github.com/x/y","assets":[]}]
        with patch("titan.updates.fetch", return_value=json.dumps(releases).encode()):
            self.assertEqual(check("x/y", "stable")["latest"], "v0.2.0")
            self.assertEqual(check("x/y", "beta")["latest"], "v0.3.0-beta.1")
    def test_network_failure_is_reported_not_current(self):
        with patch("titan.updates.fetch", side_effect=Error("Offline")):
            result = check("x/y")
            self.assertEqual(result["error"], "Offline")
            self.assertFalse(result["available"])


if __name__ == "__main__": unittest.main()

import base64
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from titan.core import Error
from titan.demo import Demo
from titan.files import operate, TEXT_LIMIT
from titan.host import Host
from titan.system_files import operate_system
from tests import test_admin_files as file_fixtures
from tests.test_lifecycle_http import HTTPFixture


def encoded(content):
    return base64.b64encode(content).decode("ascii")


class TextCreationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "share"
        self.root.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def create(self, path, content=b"", **arguments):
        return operate(self.root, "create", path, data=encoded(content), **arguments)

    def test_empty_utf8_and_exact_limit_files_are_created(self):
        for name, content in (("empty.txt", b""), ("Notizen.txt", "Grüße 🌍\n".encode()),
                              ("limit.txt", b"a" * TEXT_LIMIT)):
            with self.subTest(name=name):
                self.assertEqual(self.create(name, content), {"ok": True})
                self.assertEqual((self.root / name).read_bytes(), content)
                self.assertEqual((self.root / name).stat().st_uid, os.geteuid())

    def test_invalid_payloads_do_not_create_a_file(self):
        for data in (encoded(b"a" * (TEXT_LIMIT + 1)), encoded(b"\xff"), encoded(b"a\x00b"),
                     "%%%", "ä", None, 42, ["dGVzdA=="]):
            with self.subTest(data_type=type(data).__name__), self.assertRaises(Error):
                operate(self.root, "create", "invalid.txt", data=data)
            self.assertFalse((self.root / "invalid.txt").exists())

    def test_existing_file_folder_and_symlink_are_never_overwritten(self):
        (self.root / "old.txt").write_text("retained")
        (self.root / "folder").mkdir()
        (self.root / "link.txt").symlink_to("old.txt")
        (self.root / "dangling.txt").symlink_to("missing.txt")
        for name in ("old.txt", "folder", "link.txt", "dangling.txt"):
            with self.subTest(name=name), self.assertRaises(Error):
                self.create(name, b"replacement")
        self.assertEqual((self.root / "old.txt").read_text(), "retained")
        self.assertTrue((self.root / "folder").is_dir())
        self.assertTrue((self.root / "link.txt").is_symlink())
        self.assertTrue((self.root / "dangling.txt").is_symlink())
        self.assertFalse((self.root / "missing.txt").exists())

    def test_no_overwrite_open_blocks_symlink_race_after_initial_check(self):
        outside = Path(self.temporary.name) / "outside.txt"
        outside.write_text("retained")
        original_open = os.open

        def racing_open(path, flags, *args, **options):
            if path == "new.txt" and flags & os.O_CREAT:
                (self.root / "new.txt").symlink_to(outside)
            return original_open(path, flags, *args, **options)

        with patch("titan.files.os.open", side_effect=racing_open), self.assertRaises(Error) as failure:
            self.create("new.txt", b"replacement")
        self.assertEqual(failure.exception.status, 409)
        self.assertEqual(outside.read_text(), "retained")
        self.assertTrue((self.root / "new.txt").is_symlink())

    def test_creation_uses_exclusive_nofollow_open_and_syncs_file_and_parent(self):
        sync_kinds = []
        original_sync = os.fsync

        def sync(fd):
            sync_kinds.append(stat.S_IFMT(os.fstat(fd).st_mode))
            return original_sync(fd)

        with patch("titan.files.os.open", wraps=os.open) as opening, patch("titan.files.os.fsync", side_effect=sync):
            self.create("new.txt", b"text")
        final = next(call for call in opening.call_args_list if call.args[0] == "new.txt")
        self.assertEqual(final.args[1] & (os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW),
                         os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW)
        self.assertIs(type(final.kwargs["dir_fd"]), int)
        self.assertEqual(sync_kinds, [stat.S_IFREG, stat.S_IFDIR])

    def test_failed_new_file_is_removed_but_concurrent_replacement_is_retained(self):
        with patch('titan.files.os.fsync', side_effect=OSError('disk full')), self.assertRaises(OSError):
            self.create('incomplete.txt', b'partial')
        self.assertFalse((self.root / 'incomplete.txt').exists())
        def replace_then_fail(fd):
            (self.root / 'new.txt').unlink()
            (self.root / 'new.txt').write_bytes(b'concurrent replacement')
            raise OSError('disk full')
        with patch('titan.files.os.fsync', side_effect=replace_then_fail), self.assertRaises(OSError):
            self.create('new.txt', b'partial')
        self.assertEqual((self.root / 'new.txt').read_bytes(), b'concurrent replacement')

    def test_symlink_parents_and_traversal_cannot_create_outside_share(self):
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (self.root / "escape").symlink_to(outside, target_is_directory=True)
        for path in ("escape/new.txt", "../outside/new.txt", str(outside / "new.txt"), "bad\x00name", ""):
            with self.subTest(path=path), self.assertRaises((Error, OSError)):
                self.create(path)
        self.assertEqual(list(outside.iterdir()), [])

    def test_parent_descriptor_remains_bound_during_rename(self):
        (self.root / "folder").mkdir()
        retained = self.root / "retained"
        original_open = os.open

        def renamed_open(path, flags, *args, **options):
            fd = original_open(path, flags, *args, **options)
            if path == "folder":
                (self.root / "folder").rename(retained)
                (self.root / "folder").mkdir()
            return fd

        with patch("titan.files.os.open", side_effect=renamed_open):
            self.create("folder/new.txt", b"bound")
        self.assertEqual((retained / "new.txt").read_bytes(), b"bound")
        self.assertFalse((self.root / "folder/new.txt").exists())

    def test_own_file_edit_preserves_owner_and_respects_file_write_permission(self):
        target = self.root / "owned.txt"
        self.create("owned.txt", b"old")
        original = target.stat()
        read = operate(self.root, "read", "owned.txt")
        operate(self.root, "write", "owned.txt", data=encoded(b"new"), revision=read["revision"])
        value = target.stat()
        self.assertEqual((value.st_uid, value.st_gid, stat.S_IMODE(value.st_mode)),
                         (original.st_uid, original.st_gid, stat.S_IMODE(original.st_mode)))
        self.assertEqual(target.read_text(), "new")
        target.chmod(0o440)
        read = operate(self.root, "read", "owned.txt")
        if os.geteuid() == 0:
            self.skipTest("A root process bypasses ordinary file mode restrictions.")
        with self.assertRaises(Error) as failure:
            operate(self.root, "write", "owned.txt", data=encoded(b"denied"), revision=read["revision"])
        self.assertEqual(failure.exception.status, 403)
        self.assertEqual(target.read_text(), "new")
        self.assertFalse(list(self.root.glob(".titan-edit-*")))

    def test_foreign_owner_edit_fails_clearly_before_creating_replacement(self):
        self.create("foreign.txt", b"retained")
        read = operate(self.root, "read", "foreign.txt")
        with patch("titan.files.os.geteuid", return_value=os.geteuid() + 100), self.assertRaises(Error) as failure:
            operate(self.root, "write", "foreign.txt", data=encoded(b"new"), revision=read["revision"])
        self.assertEqual(failure.exception.status, 403)
        self.assertIn("Eigentümerschaft", str(failure.exception))
        self.assertEqual((self.root / "foreign.txt").read_text(), "retained")
        self.assertFalse(list(self.root.glob(".titan-edit-*")))


class ShareTextHostTests(unittest.TestCase):
    setUp = file_fixtures.AdminFileHostTests.setUp
    tearDown = file_fixtures.AdminFileHostTests.tearDown
    execute_worker = file_fixtures.AdminFileHostTests.execute_worker

    def test_writer_create_and_edit_use_own_uid_groups(self):
        self.host.op_file("owner", "private", "create", "new.txt", data=encoded(b"new"))
        read = self.host.op_file("owner", "private", "read", "new.txt")
        self.host.op_file("owner", "private", "write", "new.txt", data=encoded(b"edited"), revision=read["revision"])
        self.assertEqual((self.source / "new.txt").read_text(), "edited")
        for request, options in self.calls:
            self.assertEqual(request["root"], str(self.source))
            self.assertEqual(options["user"], 1234)
            self.assertEqual(options["group"], 4567)
            self.assertEqual(options["extra_groups"], [4567, 5678])
            self.assertEqual(options["pass_fds"], ())

    def test_reader_cannot_create_or_edit_and_writer_cannot_permanently_delete(self):
        for action, extra in (("create", {"data": ""}), ("write", {"data": "", "revision": "old"})):
            with self.assertRaises(Error) as failure:
                self.host.op_file("reader", "private", action, "new.txt", **extra)
            self.assertEqual(failure.exception.status, 403)
        with self.assertRaises(Error) as failure:
            self.host.op_file("owner", "private", "delete", "letter.txt", confirmation_path="private/letter.txt")
        self.assertEqual(failure.exception.status, 403)
        self.worker.assert_not_called()

    def test_admin_create_keeps_verified_descriptor_and_create_rejects_extra_options(self):
        self.host.op_admin_file("private", "create", "new.txt", data=encoded(b"text"))
        request, options = self.calls[0]
        self.assertIs(type(request["root"]), int)
        self.assertEqual(options["pass_fds"], (request["root"],))
        self.assertEqual(options["user"], 0)
        self.worker.reset_mock()
        for extra in ({"root": "/"}, {"revision": "old"}, {"offset": 1}):
            with self.assertRaises(Error):
                self.host.op_file("owner", "private", "create", "other.txt", data="", **extra)
        self.worker.assert_not_called()


class SystemTextCreationTests(TextCreationTests):
    def setUp(self):
        super().setUp()
        for name in ("etc", "tmp", "proc", "home/owner"):
            (self.root / name).mkdir(parents=True)

    def create(self, path, content=b"", **arguments):
        return operate_system(str(self.root), "create", path, system_path_root=str(self.root),
                              data=encoded(content), **arguments)

    # System browsing accepts canonicalized parent aliases, so the share-only
    # traversal policy is verified separately by TextCreationTests.
    def test_symlink_parents_and_traversal_cannot_create_outside_share(self):
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (self.root / "escape").symlink_to(outside, target_is_directory=True)
        for path in ("escape/new.txt", "../outside/new.txt", "bad\x00name", ""):
            with self.subTest(path=path), self.assertRaises((Error, OSError)):
                self.create(path)
        self.assertEqual(list(outside.iterdir()), [])

    def test_parent_descriptor_remains_bound_during_rename(self):
        # Canonicalized system requests retain the same descriptor guarantees.
        super().test_parent_descriptor_remains_bound_during_rename()

    def test_parent_alias_is_followed_but_leaf_symlink_is_never_resolved(self):
        (self.root / "alias").symlink_to("etc", target_is_directory=True)
        self.create("alias/new.txt", b"text")
        self.assertEqual((self.root / "etc/new.txt").read_bytes(), b"text")
        (self.root / "etc/leaf.txt").symlink_to("missing.txt")
        with self.assertRaises(Error):
            self.create("alias/leaf.txt", b"replacement")
        self.assertTrue((self.root / "etc/leaf.txt").is_symlink())
        self.assertFalse((self.root / "etc/missing.txt").exists())

    def test_virtual_system_targets_cannot_be_created(self):
        with self.assertRaises(Error) as failure:
            self.create("proc/new.txt", b"text")
        self.assertEqual(failure.exception.status, 403)
        self.assertFalse((self.root / "proc/new.txt").exists())

    def test_host_create_canonicalizes_parent_only_before_privileged_worker(self):
        host = Host(self.root / "agent", self.root / "storage", self.root / "vms", self.root / "smb.conf")
        host.system_root = self.root
        (self.root / "etc/leaf.txt").symlink_to("missing.txt")

        def execute(command, **options):
            request = json.loads(options["input"])
            request.pop("system")
            self.assertEqual(request["path"], "etc/leaf.txt")
            self.assertEqual(options["user"], 0)
            self.assertEqual(options["pass_fds"], (request["root"],))
            try:
                result = {"result": operate_system(**request)}
            except Error as exc:
                result = {"error": str(exc), "status": exc.status}
            return SimpleNamespace(stdout=json.dumps(result))

        with patch("titan.system_files.subprocess.run", side_effect=execute) as worker:
            with self.assertRaises(Error):
                host.op_system_file("create", "etc/leaf.txt", data=encoded(b"text"))
            worker.assert_called_once()
        self.assertFalse((self.root / "etc/missing.txt").exists())


class TextCreationHTTPTests(HTTPFixture, unittest.TestCase):
    def test_regular_user_create_and_write_dispatch_own_account(self):
        for action, extra in (("create", {"data": "dGVzdA=="}),
                              ("write", {"data": "dGVzdA==", "revision": "old"})):
            body = {"share": "public", "action": action, "path": "new.txt", **extra}
            self.assertEqual(self.request("/api/files", body, actor="reader")[0], 200)
            self.agent.call.assert_called_once_with("file", user="reader", **body)
            self.agent.call.reset_mock()

    def test_create_requires_csrf_and_rejects_injected_privileged_options(self):
        body = {"share": "public", "action": "create", "path": "new.txt", "data": ""}
        self.assertEqual(self.request("/api/files", body, actor="reader", csrf="wrong")[0], 403)
        self.assertEqual(self.request("/api/files", {**body, "user": "root"}, actor="reader")[0], 400)
        self.assertEqual(self.request("/api/files", {**body, "root": "/"}, actor="reader")[0], 400)
        self.agent.call.assert_not_called()

    def test_system_create_and_permanent_delete_remain_admin_only(self):
        body = {"share": "@system", "action": "create", "path": "tmp/new.txt", "data": ""}
        self.assertEqual(self.request("/api/files", body, actor="reader")[0], 403)
        self.assertEqual(self.request("/api/files", {"share": "public", "action": "delete", "path": "new.txt",
                                                   "confirmation_path": "public/new.txt"}, actor="reader")[0], 403)
        self.agent.call.assert_not_called()
        self.assertEqual(self.request("/api/files", body)[0], 200)
        self.agent.call.assert_called_once_with("system_file", action="create", path="tmp/new.txt", data="")


class DemoTextCreationTests(unittest.TestCase):
    def test_share_writer_can_create_and_edit_but_reader_and_delete_are_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            demo = Demo(Path(directory) / "files")
            try:
                demo.call("file", user="patrick", share="dokumente", action="create", path="new.txt", data=encoded(b"new"))
                read = demo.call("file", user="patrick", share="dokumente", action="read", path="new.txt")
                demo.call("file", user="patrick", share="dokumente", action="write", path="new.txt", data=encoded(b"edited"), revision=read["revision"])
                self.assertEqual((demo.directory / "new.txt").read_text(), "edited")
                for action, extra in (("create", {"data": ""}), ("write", {"data": "", "revision": "old"})):
                    with self.assertRaises(Error) as failure:
                        demo.call("file", user="familie", share="dokumente", action=action, path="new.txt", **extra)
                    self.assertEqual(failure.exception.status, 403)
                with self.assertRaises(Error) as failure:
                    demo.call("file", user="patrick", share="dokumente", action="delete", path="new.txt", confirmation_path="dokumente/new.txt")
                self.assertEqual(failure.exception.status, 403)
                demo.call("system_file", action="create", path="tmp/new.txt", data=encoded(b"system"))
                self.assertEqual((demo._system_path / "tmp/new.txt").read_text(), "system")
            finally:
                demo._temporary.cleanup()


if __name__ == "__main__":
    unittest.main()

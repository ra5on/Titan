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
from titan.files import operate
from titan.host import Host
from titan.system_files import operate_system
from tests.test_lifecycle_http import HTTPFixture


class SystemFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "system"
        for name in ("etc", "home/owner", "usr/bin", "tmp", "proc", "dev", "sys"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        (self.root / "etc/config").write_text("original\n")
        (self.root / "etc/config").chmod(0o640)
        self.original = self.root / "etc/config"

    def tearDown(self):
        self.temporary.cleanup()

    def call(self, action, path="", **args):
        return operate_system(str(self.root), action, path, system_path_root=str(self.root), **args)

    def test_root_lists_system_and_hidden_files_and_opens_linux_directory_links(self):
        (self.root / "bin").symlink_to("usr/bin", target_is_directory=True)
        (self.root / ".titan-trash").mkdir()
        entries = {item["name"]: item for item in self.call("list")["entries"]}
        self.assertIn(".titan-trash", entries)
        self.assertFalse(entries["etc"]["mutable"])
        self.assertTrue(entries["bin"]["directory"])
        self.assertTrue(entries["bin"]["readable"])
        self.assertEqual(self.call("list", "/bin")["path"], "usr/bin")

    def test_edit_preserves_mode_ownership_and_extended_attributes(self):
        before = self.original.stat()
        os.setxattr(self.original, "user.titan-test", b"retained")
        read = self.call("read", "etc/config")
        self.call("write", "etc/config", data=base64.b64encode("neu ä\n".encode()).decode(), revision=read["revision"])
        after = self.original.stat()
        self.assertEqual(self.original.read_text(), "neu ä\n")
        self.assertEqual((after.st_uid, after.st_gid, stat.S_IMODE(after.st_mode)),
                         (before.st_uid, before.st_gid, stat.S_IMODE(before.st_mode)))
        self.assertEqual(os.getxattr(self.original, "user.titan-test"), b"retained")
        self.assertFalse(list(self.original.parent.glob(".titan-edit-*")))

    def test_edit_refuses_stale_version_without_overwriting_external_change(self):
        read = self.call("read", "etc/config")
        self.original.write_text("external change")
        with self.assertRaises(Error) as failure:
            self.call("write", "etc/config", data=base64.b64encode(b"new").decode(), revision=read["revision"])
        self.assertEqual(failure.exception.status, 409)
        self.assertEqual(self.original.read_text(), "external change")
        self.assertFalse(list(self.original.parent.glob(".titan-edit-*")))

    def test_edit_through_symlink_preserves_link_and_updates_real_target(self):
        link = self.root / "etc/shortcut"
        link.symlink_to("config")
        read = self.call("read", "etc/shortcut")
        self.call("write", "etc/shortcut", data=base64.b64encode(b"updated").decode(), revision=read["revision"])
        self.assertTrue(link.is_symlink())
        self.assertEqual(self.original.read_text(), "updated")

    def test_symlink_listing_reports_target_size_for_editor_limit(self):
        self.original.write_bytes(b"x" * (1024 * 1024 + 1))
        (self.root / "etc/shortcut").symlink_to("config")
        entry = next(item for item in self.call("list", "etc")["entries"] if item["name"] == "shortcut")
        self.assertTrue(entry["symlink"])
        self.assertEqual(entry["size"], 1024 * 1024 + 1)

    def test_binary_oversize_and_hardlinked_edits_are_rejected(self):
        read = self.call("read", "etc/config")
        for content in (b"\x00binary", b"\xff", b"x" * (1024 * 1024 + 1)):
            with self.assertRaises(Error):
                self.call("write", "etc/config", data=base64.b64encode(content).decode(), revision=read["revision"])
        os.link(self.original, self.root / "etc/hardlink")
        read = self.call("read", "etc/config")
        with self.assertRaises(Error):
            self.call("write", "etc/config", data=base64.b64encode(b"new").decode(), revision=read["revision"])
        self.assertEqual(self.original.read_text(), "original\n")

    def test_create_rename_delete_tree_never_follows_symlink_on_removal(self):
        self.call("mkdir", "home/owner/new")
        self.call("upload", "home/owner/new/file.txt", data=base64.b64encode(b"test").decode())
        (self.root / "home/owner/new/link").symlink_to(self.original)
        self.call("rename", "home/owner/new", destination="home/owner/renamed")
        with self.assertRaises(Error):
            self.call("delete", "home/owner/renamed", confirmation_path="/wrong")
        self.call("delete", "home/owner/renamed", confirmation_path="/home/owner/renamed")
        self.assertFalse((self.root / "home/owner/renamed").exists())
        self.assertTrue(self.original.exists())

    def test_delete_symlink_only_removes_link_and_rename_keeps_link(self):
        (self.root / "tmp/link").symlink_to(self.original)
        self.call("rename", "tmp/link", destination="tmp/renamed")
        self.assertTrue((self.root / "tmp/renamed").is_symlink())
        self.call("delete", "tmp/renamed", confirmation_path="/tmp/renamed")
        self.assertTrue(self.original.exists())

    def test_system_roots_virtual_files_and_nested_mounts_are_protected(self):
        (self.root / "proc/status").write_text("virtual")
        for action in ("delete", "rename", "move"):
            for path in ("", "etc", "home", "proc/status"):
                with self.assertRaises(Error):
                    self.call(action, path, confirmation_path="/"+path, destination="tmp/new")
        for action in ("read", "write", "upload", "mkdir"):
            with self.assertRaises(Error): self.call(action, "proc/status")
        (self.root / "home/owner/data").mkdir()
        with patch("titan.system_files.mount_paths", return_value={"home/owner/data/mounted"}):
            with self.assertRaises(Error):
                self.call("delete", "home/owner/data", confirmation_path="/home/owner/data")
        self.assertTrue(self.original.exists())

    def test_essential_usrmerge_aliases_cannot_be_removed_or_renamed(self):
        for name in ("bin", "sbin", "lib", "lib64"):
            (self.root / name).symlink_to("usr/bin")
            for action in ("delete", "rename"):
                with self.assertRaises(Error):
                    self.call(action, name, confirmation_path="/"+name, destination="tmp/moved")
            self.assertTrue((self.root / name).is_symlink())

    def test_worker_rechecks_device_on_managed_volume_before_any_write(self):
        mount = self.root / "srv/titan/volumes/test"
        mount.mkdir(parents=True)
        root = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for action, path in (("list", "srv/titan/volumes/test"), ("mkdir", "srv/titan/volumes/test/new")):
                with self.assertRaises(Error) as failure:
                    operate_system(root, action, path, system_path_root=str(self.root), canonicalized=True,
                                   devices={"srv/titan/volumes/test": mount.stat().st_dev + 1})
                self.assertEqual(failure.exception.status, 503)
            self.assertFalse((mount / "new").exists())
        finally:
            os.close(root)

    def test_volume_directory_descriptor_stays_on_original_mount_namespace(self):
        mount = self.root / "srv/titan/volumes/test"
        (mount / "shares").mkdir(parents=True)
        (mount / "shares/file.txt").write_text("original")
        retained = self.root / "retained-volume"
        opened = os.open
        replaced = False
        def replace_after_open(path, *args, **options):
            nonlocal replaced
            fd = opened(path, *args, **options)
            if path == "test" and not replaced:
                replaced = True
                mount.rename(retained)
                (mount / "shares").mkdir(parents=True)
                (mount / "shares/file.txt").write_text("underlying filesystem")
            return fd
        root = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with patch("titan.files.os.open", side_effect=replace_after_open):
                result = operate_system(root, "read", "srv/titan/volumes/test/shares/file.txt",
                                        system_path_root=str(self.root), canonicalized=True,
                                        devices={"srv/titan/volumes/test": mount.stat().st_dev})
            self.assertEqual(base64.b64decode(result["data"]), b"original")
            self.assertEqual((mount / "shares/file.txt").read_text(), "underlying filesystem")
        finally:
            os.close(root)

    def test_device_and_fifo_entries_are_visible_but_not_readable(self):
        os.mkfifo(self.root / "tmp/pipe")
        entry = self.call("list", "tmp")["entries"][0]
        self.assertFalse(entry["readable"])
        with self.assertRaises(Error): self.call("read", "tmp/pipe")

    def test_traversal_and_demo_symlink_escape_are_rejected(self):
        outside = Path(self.temporary.name) / "secret"
        outside.write_text("secret")
        (self.root / "tmp/escape").symlink_to(outside)
        for path in ("../secret", "etc/../../secret", "tmp/escape", "etc/\x00config"):
            with self.assertRaises(Error): self.call("read", path)


class SystemFileHostTests(unittest.TestCase):
    setUp = SystemFileTests.setUp
    tearDown = SystemFileTests.tearDown

    def test_offline_system_destination_is_checked_for_rename(self):
        host = Host(self.root / "agent", self.root / "srv/titan", self.root / "vms", self.root / "smb.conf")
        host.system_root = self.root
        target = "srv/titan/volumes/test"
        (self.root / target).mkdir(parents=True)
        with patch.object(host.volume_manager, "required_path", side_effect=Error("offline", 503)) as check, \
                patch("titan.system_files.subprocess.run") as worker:
            with self.assertRaises(Error):
                host.op_system_file("rename", "etc/config", destination=target + "/config")
            check.assert_called_once_with(self.root / target / "config")
            worker.assert_not_called()

    def test_privileged_worker_uses_fixed_root_and_verified_fds_without_real_root_process(self):
        host = Host(self.root / "agent", self.root / "srv", self.root / "vms", self.root / "smb.conf")
        host.system_root = self.root
        def execute(arguments, **options):
            request = json.loads(options["input"])
            self.assertTrue(request.pop("system"))
            self.assertEqual(options["user"], 0)
            self.assertEqual(options["group"], 0)
            self.assertEqual(options["extra_groups"], [])
            self.assertEqual(options["pass_fds"], (request["root"],))
            return SimpleNamespace(stdout=json.dumps({"result": operate_system(**request)}))
        with patch("titan.system_files.subprocess.run", side_effect=execute) as worker:
            result = host.op_system_file("read", "etc/config")
            self.assertEqual(base64.b64decode(result["data"]), b"original\n")
            for injected in ({"root": "/etc"}, {"user": "root"}, {"system_path_root": "/"}, {"destination_root": "/"}):
                with self.assertRaises(Error): host.op_system_file("list", **injected)
            self.assertEqual(worker.call_count, 1)


class UCoreImmutableFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "usr/bin").mkdir(parents=True)
        (self.root / "etc").mkdir()
        (self.root / "usr/bin/tool").write_text("image-owned\n")
        def filesystem(path):
            frozen = Path(path).is_relative_to(self.root / "usr")
            return SimpleNamespace(f_flag=os.ST_RDONLY if frozen else 0)
        self.mounts = patch("titan.system_files.os.statvfs", side_effect=filesystem)
        self.mounts.start()

    def tearDown(self):
        self.mounts.stop()
        self.temporary.cleanup()

    def call(self, action, path="", **args):
        return operate_system(str(self.root), action, path, system_path_root=str(self.root), **args)

    def test_image_files_are_readable_but_not_advertised_as_editable(self):
        entry = self.call("list", "usr/bin")["entries"][0]
        self.assertTrue(entry["readable"])
        self.assertFalse(entry["editable"])
        self.assertFalse(entry["mutable"])
        self.assertIn(b"image-owned", base64.b64decode(self.call("read", "usr/bin/tool")["data"]))

    def test_link_in_mutable_configuration_can_be_removed_without_changing_image_target(self):
        (self.root / "etc/tool-link").symlink_to("../usr/bin/tool")
        entry = self.call("list", "etc")["entries"][0]
        self.assertTrue(entry["mutable"])
        self.assertFalse(entry["editable"])
        self.call("delete", "etc/tool-link", confirmation_path="/etc/tool-link")
        self.assertFalse((self.root / "etc/tool-link").exists())
        self.assertTrue((self.root / "usr/bin/tool").exists())

    def test_mutations_fail_before_touching_image_and_copy_out_remains_available(self):
        for action, args in (("write", {"data": "changed"}),
                             ("create", {"data": "new"}), ("mkdir", {}),
                             ("rename", {"destination": "etc/tool"}),
                             ("delete", {"confirmation_path": "/usr/bin/tool"})):
            with self.assertRaisesRegex(Error, "Systemimage"):
                self.call(action, "usr/bin/tool", **args)
        self.call("copy", "usr/bin/tool", destination="etc/tool", destination_system=True)
        self.assertEqual((self.root / "etc/tool").read_text(), "image-owned\n")
        with self.assertRaisesRegex(Error, "Systemimage"):
            self.call("copy", "etc/tool", destination="usr/bin/new", destination_system=True)


class SystemFileHTTPTests(HTTPFixture, unittest.TestCase):
    def test_editor_read_accepts_bounded_size_and_dispatches_privileged_scope(self):
        self.agent.call.return_value = {"data": "dGVzdA==", "total": 4, "revision": "version"}
        body = {"share": "@system", "action": "read", "path": "etc/config", "size": 1048577}
        self.assertEqual(self.request("/api/files", body)[0], 200)
        self.agent.call.assert_called_once_with("system_file", action="read", path="etc/config", size=1048577)

    def test_admin_system_listing_and_download_dispatch_without_share_or_injected_uid(self):
        self.agent.call.return_value = {"entries": [], "total": 0}
        self.assertEqual(self.request("/api/files?share=%40system&path=etc")[0], 200)
        self.agent.call.assert_called_once_with("system_file", action="list", path="etc", offset=0, limit=200, search="")

    def test_ordinary_user_cannot_list_read_write_or_delete_system_files(self):
        for path in ("/api/files?share=%40system&path=etc", "/api/file?share=%40system&path=etc/config"):
            self.assertEqual(self.request(path, actor="reader")[0], 403)
        for action in ("read", "write", "delete", "mkdir"):
            self.assertEqual(self.request("/api/files", {"share": "@system", "action": action, "path": "etc/config"}, actor="reader")[0], 403)
        self.agent.call.assert_not_called()

    def test_edit_and_delete_require_csrf_and_server_derived_admin_scope(self):
        body = {"share": "@system", "action": "write", "path": "etc/config", "data": "dGVzdA==", "revision": "old"}
        self.agent.call.return_value = {"ok": True}
        self.assertEqual(self.request("/api/files", body, csrf="wrong")[0], 403)
        self.agent.call.assert_not_called()
        self.assertEqual(self.request("/api/files", {**body, "root": "/"})[0], 400)
        self.assertEqual(self.request("/api/files", body)[0], 200)
        self.agent.call.assert_called_once_with("system_file", action="write", path="etc/config", data="dGVzdA==", revision="old")


class DemoSystemFileTests(unittest.TestCase):
    def test_demo_system_changes_are_confined_to_its_temporary_tree_and_cross_share_copy_works(self):
        with tempfile.TemporaryDirectory() as directory:
            demo = Demo(Path(directory) / "files")
            try:
                content = demo.call("system_file", action="read", path="etc/hostname")
                demo.call("system_file", action="write", path="etc/hostname", revision=content["revision"], data="ZGVtby1uZXcK")
                self.assertEqual((demo._system_path / "etc/hostname").read_text(), "demo-new\n")
                demo.call("system_file", action="copy", path="etc/hostname", destination="host.txt", destination_share="dokumente")
                self.assertEqual((demo.directory / "host.txt").read_text(), "demo-new\n")
                demo.call("admin_file", share="dokumente", action="copy", path="host.txt", destination="tmp/host-copy.txt", destination_share="@system")
                self.assertEqual((demo._system_path / "tmp/host-copy.txt").read_text(), "demo-new\n")
            finally:
                demo._temporary.cleanup()

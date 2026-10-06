import errno
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from titan.core import Error
from titan.files import operate
from titan import files as file_module
from titan.demo import Demo


class FileManagementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "source"
        self.destination = Path(self.temporary.name) / "destination"
        self.root.mkdir()
        self.destination.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_search_and_pagination_never_truncate_a_large_directory(self):
        for number in range(2105):
            (self.root / f"file-{number:04}.txt").touch()
        (self.root / "folder").mkdir()
        (self.root / ".titan-trash").mkdir()
        first = operate(str(self.root), "list", limit=30)
        self.assertEqual(first["total"], 2106)
        self.assertEqual(first["entries"][0]["name"], "folder")
        self.assertTrue(first["has_more"])
        last = operate(str(self.root), "list", offset=2100, limit=30)
        self.assertEqual(len(last["entries"]), 6)
        self.assertFalse(last["has_more"])
        found = operate(str(self.root), "list", search="FILE-210", limit=30)
        self.assertEqual(found["total"], 5)
        self.assertEqual(found["entries"][0]["name"], "file-2100.txt")

    def test_nested_copy_to_another_share(self):
        (self.root / "Documents").mkdir()
        (self.root / "Documents" / "nested").mkdir()
        (self.root / "Documents" / "nested" / "letter.txt").write_text("Hello")
        operate(str(self.root), "copy", "Documents", destination="Archive",
                destination_root=str(self.destination))
        self.assertEqual((self.destination / "Archive" / "nested" / "letter.txt").read_text(), "Hello")
        self.assertTrue((self.root / "Documents").exists())

    def test_move_to_another_share_and_no_overwrite(self):
        (self.root / "letter.txt").write_text("Original")
        (self.destination / "letter.txt").write_text("Existing")
        with self.assertRaises(Error):
            operate(str(self.root), "move", "letter.txt", destination="letter.txt",
                    destination_root=str(self.destination))
        self.assertEqual((self.destination / "letter.txt").read_text(), "Existing")
        operate(str(self.root), "move", "letter.txt", destination="moved.txt",
                destination_root=str(self.destination))
        self.assertFalse((self.root / "letter.txt").exists())
        self.assertEqual((self.destination / "moved.txt").read_text(), "Original")

    def test_move_across_filesystems_copies_before_removing(self):
        (self.root / "folder").mkdir()
        (self.root / "folder" / "letter.txt").write_text("Hello")
        with patch("titan.files._rename_no_replace", side_effect=OSError(errno.EXDEV, "cross device")):
            operate(str(self.root), "move", "folder", destination="moved",
                    destination_root=str(self.destination))
        self.assertFalse((self.root / "folder").exists())
        self.assertEqual((self.destination / "moved" / "letter.txt").read_text(), "Hello")

    def test_cross_filesystem_move_preserves_source_if_changed_after_copy(self):
        (self.root / "letter.txt").write_text("Original")
        remove = file_module._remove_source
        def changed(*args, **kwargs):
            (self.root / "letter.txt").write_text("New content")
            return remove(*args, **kwargs)
        with patch("titan.files._rename_no_replace", side_effect=OSError(errno.EXDEV, "cross device")), \
                patch("titan.files._remove_source", side_effect=changed):
            with self.assertRaises(Error):
                operate(str(self.root), "move", "letter.txt", destination="moved.txt",
                        destination_root=str(self.destination))
        self.assertEqual((self.root / "letter.txt").read_text(), "New content")
        self.assertEqual((self.destination / "moved.txt").read_text(), "Original")

    def test_copy_symlink_rejection_leaves_no_partial_target(self):
        (self.root / "folder").mkdir()
        (self.root / "folder" / "letter.txt").write_text("Hello")
        (self.root / "folder" / "link").symlink_to("/etc/passwd")
        with self.assertRaises((Error, OSError)):
            operate(str(self.root), "copy", "folder", destination="copy")
        self.assertFalse((self.root / "copy").exists())
        self.assertTrue((self.root / "folder" / "letter.txt").exists())

    def test_copy_rejects_destination_symlink_and_own_subdirectory(self):
        (self.root / "folder").mkdir()
        (self.root / "folder" / "nested").mkdir()
        (self.root / "letter.txt").write_text("Hello")
        (self.root / "shortcut").symlink_to(self.destination, target_is_directory=True)
        with self.assertRaises(OSError):
            operate(str(self.root), "copy", "letter.txt", destination="shortcut/letter.txt")
        for action in ("copy", "move"):
            with self.assertRaises(Error):
                operate(str(self.root), action, "folder", destination="folder/nested/copy")
        self.assertFalse((self.destination / "letter.txt").exists())

    def test_copy_never_overwrites_or_traverses_destination(self):
        (self.root / "letter.txt").write_text("Original")
        (self.destination / "letter.txt").write_text("Existing")
        with self.assertRaises(FileExistsError):
            operate(str(self.root), "copy", "letter.txt", destination="letter.txt",
                    destination_root=str(self.destination))
        with self.assertRaises(Error):
            operate(str(self.root), "copy", "letter.txt", destination="../outside")
        self.assertEqual((self.destination / "letter.txt").read_text(), "Existing")


class DemoManagementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.demo = Demo(Path(self.temporary.name) / "files")

    def tearDown(self):
        self.demo._temporary.cleanup()
        self.temporary.cleanup()

    def test_demo_enforces_copy_and_move_share_permissions(self):
        self.demo.call("share_create", name="familie", readers=[], writers=["familie", "titan-files"])
        self.demo.call("file", share="dokumente", user="familie", action="copy", path="Willkommen.txt",
                       destination_share="familie", destination="Kopie.txt")
        result = self.demo.call("file", share="familie", user="familie", action="list")
        self.assertEqual(result["entries"][0]["name"], "Kopie.txt")
        with self.assertRaises(Error):
            self.demo.call("file", share="dokumente", user="familie", action="move", path="Willkommen.txt",
                           destination_share="familie", destination="Verschoben.txt")
        self.demo.call("account_update", name="familie", enabled=False)
        with self.assertRaises(Error):
            self.demo.call("file", share="familie", user="familie", action="list")

    def test_demo_file_requests_cannot_supply_a_trusted_destination_root(self):
        with self.assertRaises(Error):
            self.demo.call("file", share="dokumente", action="copy", path="Willkommen.txt",
                           destination="leak", destination_root="/tmp")

    def test_demo_backup_restore_is_isolated_and_preserves_current_files(self):
        self.demo.call("backup_save_settings", target="/mnt/titan-demo-must-not-be-written", shares=["dokumente"])
        created = self.demo.call("backup_create")["backup"]
        self.demo.call("backup_verify", backup=created["id"])
        self.demo.call("backup_restore", backup=created["id"], share="dokumente", name="restore-test")
        root = self.demo.directory
        self.assertEqual((root / "restore-test" / "dokumente" / "Willkommen.txt").read_bytes(),
                         (root / "Willkommen.txt").read_bytes())
        with self.assertRaises(FileExistsError):
            self.demo.call("backup_restore", backup=created["id"], share="dokumente", name="restore-test")
        self.assertFalse(Path("/mnt/titan-demo-must-not-be-written").exists())

    def test_demo_backup_tampering_is_rejected(self):
        self.demo.call("backup_save_settings", target="/mnt/demo", shares=["dokumente"])
        created = self.demo.call("backup_create")["backup"]
        (self.demo._private / "backups" / created["id"] / "dokumente" / "Willkommen.txt").write_text("changed")
        with self.assertRaises(Error):
            self.demo.call("backup_restore", backup=created["id"], share="dokumente", name="restore-test")
        self.assertFalse((self.demo.directory / "restore-test").exists())

    def test_demo_vm_updates_and_backups_require_offline_machine(self):
        vm = self.demo.vms[0]
        with self.assertRaises(Error):
            self.demo.call("vm_update", vm=vm["id"], cpus=4, memory_mb=8192)
        self.demo.call("vm_action", vm=vm["id"], action="disable-autostart")
        self.assertEqual(vm["state"], "running")
        self.assertFalse(vm["autostart"])
        self.demo.call("vm_action", vm=vm["id"], action="shutdown")
        self.demo.call("vm_update", vm=vm["id"], cpus=4, memory_mb=8192)
        self.demo.call("backup_save_settings", target="/mnt/demo")
        record = self.demo.call("vm_backup", vm=vm["id"], target="/mnt/demo")["backup"]
        self.demo.call("vm_restore", backup=record["id"], name="restored-vm")
        restored = next(item for item in self.demo.vms if item["name"] == "restored-vm")
        self.assertEqual(restored["cpus"], 4)
        self.assertEqual(restored["memory_mb"], 8192)
        self.assertEqual(restored["state"], "shut off")


if __name__ == "__main__":
    unittest.main()

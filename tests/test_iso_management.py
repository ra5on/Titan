import base64
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from titan.core import Error
from titan.host import Host


class ISOManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.host = Host(self.root / "agent", self.root / "shares", self.root / "vms", self.root / "smb.conf")
        self.host.vm_root.mkdir(mode=0o755, parents=True, exist_ok=True)
        self.host.vm_root.chmod(0o755)
        self.library = self.host.iso_directory()

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def encoded(data):
        return base64.b64encode(data).decode()

    def upload(self, name="linux.iso", data=b"abc", offset=0, total=6, upload_id=None):
        return self.host.op_iso_upload(name, offset, self.encoded(data), total, upload_id)

    def test_partial_upload_is_hidden_until_all_chunks_complete(self):
        first = self.upload()
        self.assertEqual(first["offset"], 3)
        self.assertFalse(first["complete"])
        partial, metadata = self.host.upload_paths(first["upload_id"])
        self.assertEqual(partial.read_bytes(), b"abc")
        self.assertEqual(json.loads(metadata.read_text()), {"name": "linux.iso", "total": 6})
        self.assertEqual(self.host.op_isos(), [])
        second = self.upload(data=b"def", offset=3, upload_id=first["upload_id"])
        self.assertTrue(second["complete"])
        self.assertEqual(second["offset"], 6)
        self.assertEqual((self.library / "linux.iso").read_bytes(), b"abcdef")
        self.assertEqual(stat.S_IMODE((self.library / "linux.iso").stat().st_mode), 0o644)
        self.assertEqual(self.host.op_isos(), ["linux.iso"])
        self.assertFalse(partial.exists())
        self.assertFalse(metadata.exists())

    def test_single_chunk_upload_is_finalized_immediately(self):
        result = self.upload(data=b"complete", total=8)
        self.assertTrue(result["complete"])
        self.assertEqual((self.library / "linux.iso").read_bytes(), b"complete")

    def test_existing_media_and_symlink_destinations_are_never_overwritten(self):
        image = self.library / "linux.iso"
        image.write_bytes(b"existing media, possibly used by a VM")
        with self.assertRaises(Error) as result:
            self.upload(data=b"new", total=3)
        self.assertEqual(result.exception.status, 409)
        self.assertEqual(image.read_bytes(), b"existing media, possibly used by a VM")
        image.unlink()
        outside = self.root / "outside.iso"
        outside.write_bytes(b"retained outside media")
        image.symlink_to(outside)
        with self.assertRaises(Error):
            self.upload(data=b"new", total=3)
        self.assertTrue(image.is_symlink())
        self.assertEqual(outside.read_bytes(), b"retained outside media")
        image.unlink()
        image.symlink_to(self.root / "missing-outside.iso")
        with self.assertRaises(Error):
            self.upload(data=b"new", total=3)
        self.assertFalse((self.root / "missing-outside.iso").exists())

    def test_competing_upload_cannot_replace_first_completed_image(self):
        first = self.upload(data=b"aaa")
        second = self.upload(data=b"bbb")
        self.upload(data=b"AAA", offset=3, upload_id=first["upload_id"])
        with self.assertRaises(Error) as result:
            self.upload(data=b"BBB", offset=3, upload_id=second["upload_id"])
        self.assertEqual(result.exception.status, 409)
        self.assertEqual((self.library / "linux.iso").read_bytes(), b"aaaAAA")
        partial, _ = self.host.upload_paths(second["upload_id"])
        self.assertEqual(partial.read_bytes(), b"bbb")

    def test_cancel_removes_only_selected_incomplete_upload(self):
        first = self.upload()
        second = self.upload(name="rescue.iso")
        retained = self.library / "existing.iso"
        retained.write_bytes(b"retained final media")
        partial, metadata = self.host.upload_paths(first["upload_id"])
        self.assertEqual(self.host.op_iso_cancel(first["upload_id"]), {"ok": True})
        self.assertFalse(partial.exists())
        self.assertFalse(metadata.exists())
        self.assertTrue(self.host.upload_paths(second["upload_id"])[0].exists())
        self.assertEqual(retained.read_bytes(), b"retained final media")
        self.host.op_iso_cancel(first["upload_id"])

    def test_cancel_rejects_invalid_tokens_without_removing_uploads(self):
        first = self.upload()
        partial, metadata = self.host.upload_paths(first["upload_id"])
        for token in (None, 123, "../../outside", "not-a-token", "F" * 32):
            with self.subTest(token=token):
                with self.assertRaises(Error):
                    self.host.op_iso_cancel(token)
                self.assertEqual(partial.read_bytes(), b"abc")
                self.assertTrue(metadata.is_file())

    def test_continuation_must_match_name_total_offset_and_token(self):
        first = self.upload()
        partial, metadata = self.host.upload_paths(first["upload_id"])
        cases = [{"name": "other.iso"}, {"total": 7}, {"offset": 0}, {"offset": 4},
                 {"upload_id": "f" * 32}, {"upload_id": "../../escape"}, {"upload_id": 123}]
        for changes in cases:
            args = {"data": b"def", "offset": 3, "upload_id": first["upload_id"]}
            args.update(changes)
            with self.subTest(changes=changes):
                with self.assertRaises(Error):
                    self.upload(**args)
                self.assertEqual(partial.read_bytes(), b"abc")
                self.assertEqual(json.loads(metadata.read_text()), {"name": "linux.iso", "total": 6})
                self.assertEqual(self.host.op_isos(), [])

    def test_first_chunk_must_begin_at_zero_and_size_limits_are_enforced(self):
        for changes in ({"offset": 1}, {"total": 0}, {"total": -1}, {"total": True},
                        {"total": 64 * 1024**3 + 1}, {"data": b""},
                        {"data": b"too large", "total": 3},
                        {"data": b"x" * (1024**2 + 1), "total": 2 * 1024**2}):
            with self.subTest(changes=changes):
                with self.assertRaises(Error):
                    self.upload(**changes)
        for name in ("../linux.iso", "/tmp/linux.iso", "invalid name.iso", "image.qcow2", None, 123):
            with self.subTest(name=name):
                with self.assertRaises(Error):
                    self.upload(name=name)
        with self.assertRaises(Error):
            self.host.op_iso_upload("linux.iso", 0, "not valid base64!", 6)
        self.assertEqual(self.host.op_isos(), [])

    def test_symlink_partial_and_metadata_are_rejected_without_touching_outside_data(self):
        for replace in ("partial", "metadata"):
            with self.subTest(replace=replace):
                first = self.upload(name=replace + ".iso")
                partial, metadata = self.host.upload_paths(first["upload_id"])
                selected = partial if replace == "partial" else metadata
                outside = self.root / (replace + "-outside")
                outside.write_bytes(b"outside data must survive")
                selected.unlink()
                selected.symlink_to(outside)
                with self.assertRaises(Error):
                    self.upload(name=replace + ".iso", data=b"def", offset=3, upload_id=first["upload_id"])
                self.assertEqual(outside.read_bytes(), b"outside data must survive")

    def test_symlink_upload_directory_or_library_is_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        uploads = self.library / ".uploads"
        uploads.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(Error):
            self.upload()
        self.assertEqual(list(outside.iterdir()), [])
        uploads.unlink()
        self.library.rmdir()
        self.library.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(Error):
            self.upload()
        with self.assertRaises(Error):
            self.host.op_isos()
        self.assertEqual(list(outside.iterdir()), [])

    def test_inventory_omits_empty_directory_symlink_and_incomplete_media(self):
        (self.library / "zeta.iso").write_bytes(b"zeta")
        (self.library / "alpha.iso").write_bytes(b"alpha")
        (self.library / "empty.iso").touch()
        (self.library / "directory.iso").mkdir()
        (self.library / "linked.iso").symlink_to(self.library / "alpha.iso")
        self.upload()
        self.assertEqual(self.host.op_isos(), ["alpha.iso", "zeta.iso"])
        with patch.object(self.host, "op_vms", return_value={"available": True, "vms": [
                {"name": "linux", "iso": "alpha.iso"}, {"name": "rescue", "iso": None}]}):
            inventory = self.host.op_iso_library()
        self.assertEqual(inventory["items"], [{"name": "alpha.iso", "size": 5, "used_by": ["linux"]},
                                             {"name": "zeta.iso", "size": 4, "used_by": []}])

    @staticmethod
    def domain_xml(name, image=None):
        domain = ET.Element("domain")
        ET.SubElement(domain, "name").text = name
        devices = ET.SubElement(domain, "devices")
        if image is not None:
            disk = ET.SubElement(devices, "disk", type="file", device="cdrom")
            ET.SubElement(disk, "source", file=str(image))
        return ET.tostring(domain, encoding="unicode")

    def test_removal_rejects_media_referenced_by_foreign_offline_guest(self):
        image = self.library / "linux.iso"
        image.write_bytes(b"foreign guest media")
        calls = []
        def command(arguments, **kwargs):
            calls.append(arguments)
            if arguments[:2] == ["virsh", "list"]:
                return "foreign-id"
            if arguments[:2] == ["virsh", "dumpxml"]:
                return self.domain_xml("other-hypervisor-guest", image)
            raise AssertionError(arguments)
        with patch("titan.host.run", side_effect=command):
            with self.assertRaises(Error) as result:
                self.host.op_iso_remove("linux.iso")
        self.assertEqual(result.exception.status, 409)
        self.assertEqual(image.read_bytes(), b"foreign guest media")
        self.assertIn(["virsh", "list", "--all", "--uuid"], calls)

    def test_removal_also_checks_active_guest_media_when_persistent_definition_ejected_it(self):
        image = self.library / "linux.iso"
        image.write_bytes(b"active-only guest media")
        def command(arguments, **kwargs):
            if arguments[:2] == ["virsh", "list"]:
                return "foreign-id"
            if arguments[:2] == ["virsh", "dumpxml"]:
                return self.domain_xml("foreign-guest", None if "--inactive" in arguments else image)
            raise AssertionError(arguments)
        with patch("titan.host.run", side_effect=command):
            with self.assertRaises(Error) as result:
                self.host.op_iso_remove("linux.iso")
        self.assertEqual(result.exception.status, 409)
        self.assertEqual(image.read_bytes(), b"active-only guest media")

    def test_removal_fails_closed_when_libvirt_cannot_be_inspected(self):
        image = self.library / "linux.iso"
        image.write_bytes(b"retained media")
        with patch("titan.host.run", side_effect=Error("libvirt unavailable")):
            with self.assertRaises(Error):
                self.host.op_iso_remove("linux.iso")
        self.assertEqual(image.read_bytes(), b"retained media")

    def test_removal_deletes_only_unreferenced_final_image(self):
        image = self.library / "linux.iso"
        image.write_bytes(b"unused media")
        retained = self.library / "retained.iso"
        retained.write_bytes(b"retained media")
        with patch("titan.host.run", return_value=""):
            result = self.host.op_iso_remove("linux.iso")
        self.assertTrue(result["ok"])
        self.assertFalse(image.exists())
        self.assertEqual(retained.read_bytes(), b"retained media")


if __name__ == "__main__":
    unittest.main()

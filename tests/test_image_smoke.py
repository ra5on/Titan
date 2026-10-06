"""Bounded QMP protocol and identity checks for disposable image growth."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("titan_image_smoke", ROOT / "scripts/smoke-runtime.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class DisposableQMPTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="titan-image-smoke.", dir="/tmp")
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "qmp.sock"
        self.overlay = self.directory / "test.qcow2"
        self.overlay.write_bytes(b"private-overlay-fixture")

    def tearDown(self):
        self.temporary.cleanup()

    def rows(self, size):
        return [{"device": "titan-system", "inserted": {"ro": False, "drv": "qcow2", "file": str(self.overlay),
            "backing_file_depth": 1, "image": {"format": "qcow2", "virtual-size": size},
            "private-field": "private-token"}}]

    def execute(self, before=None, after=None, replies=None):
        messages = replies if replies is not None else [
            {"QMP": {"version": {}, "capabilities": []}}, {"return": {}, "id": 1},
            {"return": before if before is not None else self.rows(smoke.DisposableDiskGrowth.INITIAL), "id": 2},
            {"event": "BLOCK_SIZE_CHANGED", "data": {"private": "private-value"}}, {"return": {}, "id": 3},
            {"return": after if after is not None else self.rows(smoke.DisposableDiskGrowth.EXPANDED), "id": 4}]
        stream = io.BytesIO(b"".join(json.dumps(value).encode() + b"\n" for value in messages))
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.makefile.return_value = stream
        self.connection = connection
        original = Path.lstat
        def metadata(path):
            if path == self.path:
                return SimpleNamespace(st_mode=stat.S_IFSOCK | 0o700, st_uid=os.geteuid())
            return original(path)
        with patch.object(Path, "lstat", metadata), patch.object(smoke.socket, "socket", return_value=connection):
            result = smoke.DisposableDiskGrowth(self.path).grow()
        return result, connection

    def test_fixed_protocol_grows_only_named_overlay_and_checks_capacity_afterward(self):
        result, connection = self.execute()
        self.assertEqual(result, {"overlay_grown": True, "virtual_size_before": 32 * 1024**3,
                                  "virtual_size_after": 36 * 1024**3})
        commands = [json.loads(call.args[0]) for call in connection.sendall.call_args_list]
        self.assertEqual([value["execute"] for value in commands], ["qmp_capabilities", "query-block", "block_resize", "query-block"])
        self.assertEqual(commands[2], {"execute": "block_resize", "id": 3,
            "arguments": {"device": "titan-system", "size": 36 * 1024**3}})
        connection.connect.assert_called_once_with(str(self.path))
        self.assertNotIn("private", json.dumps(result))

    def test_foreign_drive_wrong_capacity_and_unsafe_mount_are_rejected_before_resize(self):
        mutations = [lambda rows: rows[0].update(device="foreign-host-disk"),
            lambda rows: rows.append(copy.deepcopy(rows[0])),
            lambda rows: rows[0]["inserted"].update(ro=True),
            lambda rows: rows[0]["inserted"].update(drv="raw"),
            lambda rows: rows[0]["inserted"].update(file="/dev/private-host-disk"),
            lambda rows: rows[0]["inserted"].update(backing_file_depth=0),
            lambda rows: rows[0]["inserted"]["image"].update(**{"virtual-size": 36 * 1024**3})]
        for change in mutations:
            rows = self.rows(smoke.DisposableDiskGrowth.INITIAL)
            change(rows)
            with self.subTest(change=change), self.assertRaises(smoke.SmokeFailure) as caught:
                self.execute(before=rows)
            self.assertNotIn("private", str(caught.exception))
            self.assertNotIn("foreign-host-disk", str(caught.exception))
            self.assertNotIn("block_resize", [json.loads(call.args[0])["execute"] for call in self.connection.sendall.call_args_list])

    def test_report_never_accepts_success_without_expanded_overlay(self):
        with self.assertRaisesRegex(smoke.SmokeFailure, "expected overlay and capacity"):
            self.execute(after=self.rows(smoke.DisposableDiskGrowth.INITIAL))

    def test_qmp_error_mismatched_reply_and_event_flood_have_closed_errors(self):
        hello = {"QMP": {"version": {}}}
        for replies in ([hello, {"error": {"desc": "private-command-error"}, "id": 1}],
                        [hello, {"return": {"private": "private-value"}, "id": 99}],
                        [hello] + [{"event": "private-event"}] * 16,
                        [{"private-greeting": "private-value"}]):
            with self.subTest(replies=replies), self.assertRaises(smoke.SmokeFailure) as caught:
                self.execute(replies=replies)
            self.assertNotIn("private", str(caught.exception))

    def test_only_private_owned_direct_socket_and_regular_overlay_are_accepted(self):
        for path in (None, "/run/libvirt/libvirt-sock", "/tmp/titan-image-smoke.12345678/../qmp.sock", self.directory / "other.sock"):
            with self.subTest(path=path), patch.object(smoke.socket, "socket") as network:
                with self.assertRaises(smoke.SmokeFailure): smoke.DisposableDiskGrowth(path).grow()
                network.assert_not_called()
        self.directory.chmod(0o755)
        with self.assertRaises(smoke.SmokeFailure): self.execute()
        self.connection.connect.assert_not_called()
        self.directory.chmod(0o700)
        self.overlay.unlink()
        self.overlay.symlink_to("/dev/private-host-disk")
        with self.assertRaises(smoke.SmokeFailure): self.execute()

    @unittest.skipUnless(shutil.which("qemu-img") and shutil.which("qemu-system-x86_64"), "QEMU fixture tools unavailable")
    def test_real_qmp_grows_temp_overlay_and_preserves_raw_backing_content(self):
        base = self.directory / "base.img"
        base.write_bytes(b"Titan temporary read-only QMP backing proof.\n")
        with base.open("ab") as output: output.truncate(1024**2)
        expected_hash = hashlib.sha256(base.read_bytes()).hexdigest()
        self.overlay.unlink()
        subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", "-F", "raw", "-b", str(base), str(self.overlay)], check=True, timeout=10, capture_output=True)
        subprocess.run(["qemu-img", "resize", "-q", str(self.overlay), "32G"], check=True, timeout=10, capture_output=True)
        process = subprocess.Popen(["qemu-system-x86_64", "-machine", "none", "-nodefaults", "-no-user-config", "-display", "none", "-monitor", "none",
            "-qmp", "unix:" + str(self.path) + ",server=on,wait=off",
            "-drive", "if=none,id=titan-system,format=qcow2,file=" + str(self.overlay)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 5
            while not self.path.exists() and process.poll() is None and time.monotonic() < deadline: time.sleep(0.01)
            result = smoke.DisposableDiskGrowth(self.path).grow()
            self.assertTrue(result["overlay_grown"])
            self.assertEqual(result["virtual_size_after"], 36 * 1024**3)
            self.assertEqual(hashlib.sha256(base.read_bytes()).hexdigest(), expected_hash)
            self.assertEqual(base.stat().st_size, 1024**2)
        finally:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()

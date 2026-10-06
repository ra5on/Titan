import base64
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from titan.core import Error
from titan.files import operate
from titan.host import Host
from tests.test_lifecycle_http import HTTPFixture


class AdminFileHostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.host = Host(self.root / "agent", self.root / "storage", self.root / "vms", self.root / "smb.conf")
        self.source = self.host.share_root / "shares" / "private"
        self.target = self.host.share_root / "shares" / "archive"
        self.source.mkdir(parents=True)
        self.target.mkdir()
        self.source.parent.chmod(0o750)  # Root-controlled namespace under the agent's production umask.
        (self.source / "letter.txt").write_text("original contents")
        self.shares = [{"name": "private", "path": str(self.source), "readers": ["reader"], "writers": ["owner"]},
                       {"name": "archive", "path": str(self.target), "readers": [], "writers": ["owner"]}]
        self.account = patch.object(self.host, "require_active_account").start()
        patch.object(self.host, "op_shares", side_effect=lambda: self.shares).start()
        patch.object(self.host.volume_manager, "required_path", return_value=None).start()
        patch("titan.host.pwd.getpwnam", side_effect=lambda name: SimpleNamespace(pw_uid=0 if name == "root" else 1234,
                                                                                pw_gid=0 if name == "root" else 4567)).start()
        patch("titan.host.os.getgrouplist", return_value=[4567, 5678]).start()
        self.calls = []
        self.before_worker = None
        self.worker = patch("titan.host.subprocess.run", side_effect=self.execute_worker).start()

    def tearDown(self):
        patch.stopall()
        self.temporary.cleanup()

    def execute_worker(self, arguments, **options):
        # Execute confined file code with the current test UID. The subprocess
        # UID/GID and inherited-FD contract is inspected; no root process runs.
        request = json.loads(options["input"])
        self.calls.append((request, options))
        for descriptor in options["pass_fds"]:
            os.fstat(descriptor)
        if self.before_worker:
            self.before_worker(request, options)
        try:
            result = {"result": operate(**request)}
        except Exception as exc:
            result = {"error": str(exc), "status": getattr(exc, "status", 400)}
        return SimpleNamespace(stdout=json.dumps(result), returncode=0)

    def test_admin_reads_share_without_smb_membership_with_verified_inherited_fd(self):
        result = self.host.op_admin_file("private", "read", "letter.txt")
        self.assertEqual(base64.b64decode(result["data"]), b"original contents")
        request, options = self.calls[0]
        self.assertIs(type(request["root"]), int)
        self.assertEqual(options["pass_fds"], (request["root"],))
        self.assertEqual(options["user"], 0)
        self.assertEqual(options["group"], 0)
        self.assertEqual(options["extra_groups"], [])
        with self.assertRaises(OSError): os.fstat(request["root"])

    def test_admin_copy_receives_both_verified_share_descriptors(self):
        self.host.op_admin_file("private", "copy", "letter.txt", destination="copy.txt", destination_share="archive")
        self.assertEqual((self.target / "copy.txt").read_text(), "original contents")
        request, options = self.calls[0]
        self.assertIs(type(request["root"]), int)
        self.assertIs(type(request["destination_root"]), int)
        self.assertEqual(options["pass_fds"], (request["root"], request["destination_root"]))
        self.assertNotEqual(request["root"], request["destination_root"])
        for descriptor in options["pass_fds"]:
            with self.assertRaises(OSError): os.fstat(descriptor)

    def test_admin_source_fd_remains_bound_when_namespace_is_replaced(self):
        retained = self.root / "original-private"
        def replace(request, options):
            self.source.rename(retained)
            self.source.mkdir()
            (self.source / "letter.txt").write_text("replacement contents")
        self.before_worker = replace
        result = self.host.op_admin_file("private", "read", "letter.txt")
        self.assertEqual(base64.b64decode(result["data"]), b"original contents")
        self.assertEqual((self.source / "letter.txt").read_text(), "replacement contents")

    def test_admin_target_fd_remains_bound_when_namespace_is_replaced(self):
        retained = self.root / "original-archive"
        def replace(request, options):
            self.target.rename(retained)
            self.target.mkdir()
        self.before_worker = replace
        self.host.op_admin_file("private", "copy", "letter.txt", destination="copy.txt", destination_share="archive")
        self.assertEqual((retained / "copy.txt").read_text(), "original contents")
        self.assertFalse((self.target / "copy.txt").exists())

    def test_admin_privileges_do_not_allow_absolute_parent_or_symlink_escape(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("never read")
        (self.source / "escape").symlink_to(outside, target_is_directory=True)
        (self.source / "secret-link.txt").symlink_to(outside / "secret.txt")
        for path in ("../outside/secret.txt", str(outside / "secret.txt"), "escape/secret.txt", "secret-link.txt"):
            with self.assertRaises(Error): self.host.op_admin_file("private", "read", path)
        self.assertEqual((outside / "secret.txt").read_text(), "never read")

    def test_admin_copy_cannot_traverse_or_follow_target_symlinks(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.target / "escape").symlink_to(outside, target_is_directory=True)
        for destination in ("../leak.txt", "escape/leak.txt", str(outside / "leak.txt")):
            with self.assertRaises(Error):
                self.host.op_admin_file("private", "copy", "letter.txt", destination=destination, destination_share="archive")
        self.assertEqual(list(outside.iterdir()), [])

    def test_admin_cannot_open_a_symlink_share_root_or_outside_registry_path(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.source.rename(self.root / "original")
        self.source.symlink_to(outside, target_is_directory=True)
        with self.assertRaises((Error, OSError)): self.host.op_admin_file("private", "list")
        self.shares[0]["path"] = str(outside)
        with self.assertRaises(Error): self.host.op_admin_file("private", "list")
        self.worker.assert_not_called()

    def test_blocked_share_or_offline_volume_prevents_privileged_worker(self):
        self.shares[0]["blocked"] = True
        with self.assertRaises(Error): self.host.op_admin_file("private", "list")
        self.shares[0]["blocked"] = False
        with patch.object(self.host.storage_locations, "required_path", side_effect=Error("volume offline", 503)):
            with self.assertRaises(Error): self.host.op_admin_file("private", "list")
        self.worker.assert_not_called()

    def test_blocked_destination_prevents_admin_copy(self):
        self.shares[1]["blocked"] = True
        with self.assertRaises(Error):
            self.host.op_admin_file("private", "copy", "letter.txt", destination="copy.txt", destination_share="archive")
        self.worker.assert_not_called()

    def test_normal_user_retains_own_uid_groups_and_membership_checks(self):
        self.host.op_file("reader", "private", "read", "letter.txt")
        request, options = self.calls[0]
        self.assertEqual(request["root"], str(self.source))
        self.assertEqual(options["user"], 1234)
        self.assertEqual(options["group"], 4567)
        self.assertEqual(options["extra_groups"], [4567, 5678])
        self.assertEqual(options["pass_fds"], ())
        self.worker.reset_mock()
        with self.assertRaises(Error): self.host.op_file("reader", "private", "mkdir", "forbidden")
        with self.assertRaises(Error): self.host.op_file("reader", "archive", "list")
        with self.assertRaises(Error):
            self.host.op_file("reader", "private", "copy", "letter.txt", destination="forbidden", destination_share="archive")
        self.worker.assert_not_called()

    def test_untrusted_host_parameters_cannot_request_admin_uid_or_root(self):
        for extra in ({"_admin": True}, {"root": "/etc"}, {"destination_root": "/etc"}):
            with self.assertRaises(Error): self.host.op_file("reader", "private", "list", **extra)
        self.worker.assert_not_called()


class AdminFileHTTPTests(HTTPFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.shares = [{"name": "public", "readers": ["reader"], "writers": []},
                       {"name": "private", "readers": ["owner"], "writers": ["owner"]},
                       {"name": "archive", "readers": [], "writers": ["owner"]}]
        self.agent.call.side_effect = self.agent_result

    def agent_result(self, operation, **arguments):
        if operation == "shares": return self.shares
        if operation in ("file", "admin_file"):
            if operation == "file" and arguments["share"] != "public":
                raise Error("Keine Freigaberechte.", 403)
            if arguments["action"] == "read":
                data = b"secret contents"
                offset = arguments.get("offset", 0)
                size = arguments.get("size", len(data))
                return {"name": "letter.txt", "total": len(data), "data": base64.b64encode(data[offset:offset+size]).decode()}
            return {"entries": [], "total": 0, "ok": True}
        return {"ok": True}

    def test_admin_sees_every_managed_share_without_service_account_membership(self):
        status, result, _ = self.json_request("/api/shares")
        self.assertEqual(status, 200)
        self.assertEqual([item["name"] for item in result], ["public", "private", "archive"])
        status, result, _ = self.json_request("/api/shares", actor="reader")
        self.assertEqual(status, 200)
        self.assertEqual([item["name"] for item in result], ["public"])

    def test_admin_listing_dispatches_only_role_derived_privileged_operation(self):
        self.assertEqual(self.request("/api/files?share=private&path=nested")[0], 200)
        self.agent.call.assert_called_once_with("admin_file", share="private", action="list", path="nested", offset=0,
                                               limit=200, search="")

    def test_admin_download_and_range_use_confined_admin_operation(self):
        status, body, headers = self.request("/api/file?share=private&path=letter.txt&preview=1",
                                             headers={"Range": "bytes=0-5"})
        self.assertEqual(status, 206)
        self.assertEqual(body, b"secret")
        self.assertEqual(headers["Content-Range"], "bytes 0-5/15")
        calls = self.agent.call.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call.args == ("admin_file",) for call in calls))
        self.assertTrue(all("user" not in call.kwargs and "root" not in call.kwargs for call in calls))

    def test_normal_user_download_uses_own_account_and_cannot_read_private_share(self):
        self.assertEqual(self.request("/api/file?share=private&path=letter.txt", actor="reader")[0], 403)
        self.agent.call.assert_called_once_with("file", user="reader", share="private", action="read", path="letter.txt", offset=0, size=1)

    def test_injected_admin_uid_root_or_role_body_flags_are_rejected(self):
        body = {"share": "public", "action": "mkdir", "path": "folder"}
        for actor in ("admin", "reader"):
            for extra in ({"_admin": True}, {"admin": True}, {"user": "root"}, {"root": "/etc"},
                          {"destination_root": "/etc"}, {"role": "admin"}):
                self.assertEqual(self.request("/api/files", {**body, **extra}, actor=actor)[0], 400)
        self.agent.call.assert_not_called()

    def test_untrusted_query_or_headers_cannot_promote_normal_reader(self):
        status, _, _ = self.request("/api/files?share=public&_admin=1&user=root&root=/etc", actor="reader",
                                    headers={"X-User-Role": "admin"})
        self.assertEqual(status, 200)
        self.agent.call.assert_called_once_with("file", user="reader", share="public", action="list", path="", offset=0,
                                               limit=200, search="")

    def test_file_mutation_uses_authenticated_role_and_still_requires_csrf(self):
        body = {"share": "private", "action": "mkdir", "path": "folder"}
        self.assertEqual(self.request("/api/files", body, csrf="wrong")[0], 403)
        self.agent.call.assert_not_called()
        self.assertEqual(self.request("/api/files", body)[0], 200)
        self.agent.call.assert_called_once_with("admin_file", **body)


if __name__ == "__main__":
    unittest.main()

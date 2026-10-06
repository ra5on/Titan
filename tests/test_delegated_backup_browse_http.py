"""The archive browser must preserve delegated users' share boundaries."""
from http.server import ThreadingHTTPServer
import json
import tempfile
import threading
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock

from titan.backup_authorization import host_call
from titan.core import Error
from titan.server import Application, Handler


class DelegatedBackupBrowseHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.app = Application(self.temporary.name)
        for name, role in (("admin", "admin"), ("reader", "user")):
            self.app.store.create_user(name, name + "-password-long", role, name)
        self.app.store.set_config("identity", {
            "schema": 1, "groups": [],
            "users": {"reader": {"applications": {"backups": True}, "shares": {}}},
        })
        self.shares = [
            {"name": "public", "readers": ["reader"], "writers": []},
            {"name": "private", "readers": [], "writers": ["owner"]},
        ]
        self.manifests = {
            "public-backup": {"id": "public-backup", "type": "shares", "shares": ["public"]},
            "private-backup": {"id": "private-backup", "type": "shares", "shares": ["private"]},
            "mixed-backup": {"id": "mixed-backup", "type": "shares", "shares": ["public", "private"]},
        }
        self.backend = Mock()
        self.backend.manifest.side_effect = self.manifests.__getitem__
        self.backend.browse.side_effect = lambda **arguments: {"items": [{"name": "document.txt"}], **arguments}
        self.host = SimpleNamespace(
            account_lock=threading.RLock(), require_active_account=Mock(),
            op_shares=lambda: self.shares, backups=self.backend,
        )
        self.calls = []
        self.app.agent = self
        self.tokens = {name: self.app.store.login(name, name + "-password-long")[0]
                       for name in ("admin", "reader")}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.app = self.app
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def call(self, operation, **arguments):
        self.calls.append((operation, arguments))
        if operation == "delegated_backup":
            return host_call(self.host, arguments["action"], arguments["user"], arguments["arguments"])
        if operation == "backup_browse":
            return self.backend.browse(**arguments)
        raise Error("Unexpected operation: " + operation)

    def request(self, query, actor="reader"):
        request = urllib.request.Request(self.url + "/api/backup/browse?" + query,
            headers={"Cookie": "titan_session=" + self.tokens[actor]})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as response:
            return response.code, json.loads(response.read())

    def test_nonadmin_browser_rechecks_full_manifest_sources_at_root_boundary(self):
        for backup in ("private-backup", "mixed-backup"):
            with self.subTest(backup=backup):
                status, result = self.request("backup=" + backup)
                self.assertEqual(status, 403, result)
        self.backend.browse.assert_not_called()
        self.assertTrue(all(operation == "delegated_backup" for operation, _ in self.calls))

    def test_own_backup_preserves_validated_pagination_and_path(self):
        status, result = self.request("backup=public-backup&path=public&offset=200&limit=25")
        self.assertEqual(status, 200, result)
        self.backend.browse.assert_called_once_with(backup="public-backup", path="public", offset=200, limit=25)
        self.host.require_active_account.assert_called_once_with("reader")

    def test_read_permission_revoked_after_login_blocks_archive_browser(self):
        self.shares[0]["readers"] = []
        status, result = self.request("backup=public-backup&path=public")
        self.assertEqual(status, 403, result)
        self.backend.browse.assert_not_called()

    def test_admin_can_browse_private_backup_without_delegated_identity(self):
        status, result = self.request("backup=private-backup&path=private", actor="admin")
        self.assertEqual(status, 200, result)
        self.assertEqual(self.calls[0][0], "backup_browse")


if __name__ == "__main__":
    unittest.main()

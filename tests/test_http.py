import base64
from http.client import HTTPResponse
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from titan.server import Application, Handler, WebServer


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.app = Application(cls.temp.name, demo=True)
        cls.server = WebServer(("127.0.0.1", 0), Handler)
        cls.server.app = cls.app
        cls.server.daemon_threads = True
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.app.stop.set()
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()
        cls.app.close_all_terminals()
        cls.app.agent.terminals.close_all()
        cls.temp.cleanup()
    def request(self, path, body=None, csrf="demo-only", extra=None):
        headers = {"X-CSRF-Token": csrf, **(extra or {})}
        request = urllib.request.Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Content-Type":"application/json", **headers})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as response:
            return response.code, response.read(), response.headers
    def test_all_pages_backing_endpoints(self):
        for path in ("/", "/app.js", "/style.css", "/api/session", "/api/status", "/api/catalog", "/api/storage", "/api/snapshots", "/api/apps", "/api/shares", "/api/managed-shares", "/api/vms", "/api/isos", "/api/users", "/api/settings", "/api/updates", "/api/logs", "/api/jobs", "/api/backups", "/api/backup/settings", "/api/monitoring"):
            self.assertEqual(self.request(path)[0], 200, path)
    def test_startup_connection_burst_is_queued_and_served(self):
        # Pause acceptance while a proxy's initial asset burst arrives. The
        # old listen backlog of five stalls before all 64 handshakes finish;
        # this test then also proves the queued sockets reach the real handler.
        server = WebServer(("127.0.0.1", 0), Handler)
        server.app = self.app
        clients = []
        thread = None
        try:
            for index in range(64):
                try:
                    client = socket.create_connection(server.server_address, timeout=1)
                except OSError as exc:
                    self.fail(f"Startup listener could queue only {index} of 64 connections: {exc}")
                clients.append(client)
            request = (b"GET /api/session HTTP/1.1\r\nHost: localhost\r\n"
                       b"Connection: close\r\n\r\n")
            for client in clients:
                client.settimeout(10)
                client.sendall(request)
            thread = threading.Thread(target=server.serve_forever,
                                      kwargs={"poll_interval": .01}, daemon=True)
            thread.start()
            for index, client in enumerate(clients):
                with self.subTest(connection=index), HTTPResponse(client) as response:
                    response.begin()
                    self.assertEqual(response.status, 200)
                    payload = json.loads(response.read())
                    self.assertTrue(payload["demo"])
                    self.assertEqual(payload["user"]["name"], "demo")
        finally:
            for client in clients:
                client.close()
            if thread is not None:
                server.shutdown()
                thread.join(timeout=5)
            server.server_close()
        if thread is not None:
            self.assertFalse(thread.is_alive(), "Burst server thread did not shut down.")
    def test_mutations_require_csrf(self):
        self.assertEqual(self.request("/api/settings", {"auto_check":False}, csrf="wrong")[0], 403)
    def test_cross_origin_rejected(self):
        self.assertEqual(self.request("/api/settings", {}, extra={"Origin":"https://evil.com"})[0], 403)
    def test_static_path_traversal_rejected(self):
        self.assertEqual(self.request("/%2e%2e/core.py")[0], 404)
    def test_range_download(self):
        status, data, headers = self.request("/api/file?share=dokumente&path=Willkommen.txt", extra={"Range":"bytes=0-9"})
        self.assertEqual(status, 206); self.assertEqual(len(data), 10)
        self.assertTrue(headers["Content-Range"].startswith("bytes 0-9/"))
    def test_upload_and_preview(self):
        data=base64.b64encode(b"hello").decode()
        self.assertEqual(self.request("/api/files", {"share":"dokumente","path":"api-test.txt","action":"upload","offset":0,"data":data})[0], 200)
        status, content, headers=self.request("/api/file?share=dokumente&path=api-test.txt&preview=1")
        self.assertEqual(content,b"hello"); self.assertTrue(headers["Content-Type"].startswith("text/plain"))
    def test_settings_persist(self):
        self.assertEqual(self.request("/api/settings", {"auto_check":False})[0], 200)
        self.assertFalse(json.loads(self.request("/api/settings")[1])["auto_check"])
    def test_unknown_privileged_action_rejected(self):
        self.assertEqual(self.request("/api/actions", {"operation":"shell","arguments":{"command":"id"}})[0], 400)
    def test_live_mode_has_no_implicit_session(self):
        original=self.app.demo
        try:
            self.app.demo=False
            self.assertEqual(self.request("/api/status")[0],401)
            self.assertIsNone(json.loads(self.request("/api/session")[1])["user"])
        finally:self.app.demo=original
    def test_user_role_cannot_manage_host(self):
        user={"name":"reader","role":"user","system_user":"reader","csrf":"demo-only"}
        from unittest.mock import patch
        with patch.object(Handler, "user", return_value=user):
            for path in ("/api/status","/api/users","/api/settings","/api/managed-shares","/api/storage"):
                self.assertEqual(self.request(path)[0],403,path)


if __name__ == "__main__": unittest.main()

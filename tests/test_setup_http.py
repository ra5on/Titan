from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from titan.server import Application, Handler


class SetupHTTPTests(unittest.TestCase):
    """Exercise first setup over HTTP using a mocked SMB account adapter."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.agent = Mock()
        def provision(operation, **arguments):
            if operation != "account_create":
                raise AssertionError("Unexpected setup host operation")
            return {"ok": True}
        self.agent.call.side_effect = provision
        self.agent_patch = patch("titan.server.AgentClient", return_value=self.agent)
        self.agent_patch.start()
        self.app = Application(self.temp.name)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.app = self.app
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.password = "first-admin-long-password"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.agent_patch.stop()
        self.temp.cleanup()

    def request(self, path, body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request("POST" if body is not None else "GET", path,
                               body=json.dumps(body).encode() if body is not None else None,
                               headers=headers or {})
            response = connection.getresponse()
            return response.status, json.loads(response.read()), response.headers
        finally:
            connection.close()

    def setup_headers(self, **overrides):
        headers = {"Origin": self.app.origin or self.origin,
                   "Content-Type": "application/json",
                   "X-CSRF-Token": self.app.setup_csrf}
        if self.app.origin:
            from urllib.parse import urlsplit
            headers["Host"] = urlsplit(self.app.origin).netloc
        headers.update(overrides)
        return {key: value for key, value in headers.items() if value is not None}

    def setup(self, name="admin", **header_overrides):
        return self.request("/api/setup", {"name": name, "password": self.password},
                            self.setup_headers(**header_overrides))

    def assert_no_account(self):
        self.assertEqual(self.app.store.users(), [])
        self.agent.call.assert_not_called()

    def test_empty_installation_exposes_setup_nonce_without_a_code_file_or_session(self):
        status, session, headers = self.request("/api/session")
        self.assertEqual(status, 200)
        self.assertTrue(session["setup_required"])
        self.assertFalse(session["demo"])
        self.assertIsNone(session["user"])
        self.assertIsInstance(session["setup_csrf"], str)
        self.assertGreaterEqual(len(session["setup_csrf"]), 32)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertFalse((Path(self.temp.name) / "setup-token").exists())
        self.assert_no_account()

    def test_browser_setup_creates_the_first_admin_without_logging_in_implicitly(self):
        nonce = self.request("/api/session")[1]["setup_csrf"]
        status, result, headers = self.setup(**{"X-CSRF-Token": nonce})
        self.assertEqual((status, result), (200, {"ok": True}))
        self.assertIsNone(headers.get("Set-Cookie"))
        self.assertEqual(self.app.store.users(), [{"name": "admin", "role": "admin",
                                                  "system_user": "admin", "enabled": True,
                                                  "display_name": "", "description": ""}])
        session = self.request("/api/session")[1]
        self.assertFalse(session["setup_required"])
        self.assertNotIn("setup_csrf", session)
        self.assertIsNone(session["user"])
        self.assertFalse((Path(self.temp.name) / "setup-token").exists())
        self.agent.call.assert_called_once_with("account_create", name="admin", password=self.password)

    def test_setup_requires_same_origin_json_and_the_page_nonce(self):
        for override in ({"Origin": None}, {"Origin": "https://foreign.example"},
                         {"X-CSRF-Token": None}, {"X-CSRF-Token": "wrong"},
                         {"Content-Type": "text/plain"},
                         {"Content-Type": "application/x-www-form-urlencoded"},
                         {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=override):
                status, result, _ = self.setup(**override)
                self.assertEqual(status, 403)
                self.assertIn("error", result)
                self.assert_no_account()

    def test_only_username_and_password_are_accepted_during_setup(self):
        for extra in ({"role": "user"}, {"role": "admin"}, {"token": "old-code"},
                      {"system_user": "root"}):
            with self.subTest(extra=extra):
                status, result, _ = self.request("/api/setup", {
                    "name": "admin", "password": self.password, **extra}, self.setup_headers())
                self.assertEqual(status, 400)
                self.assertIn("error", result)
                self.assert_no_account()

    def test_incomplete_or_invalid_credentials_leave_setup_open(self):
        for body in ({"name": "admin"}, {"password": self.password},
                     {"name": "../root", "password": self.password},
                     {"name": "admin", "password": "short"}):
            with self.subTest(body=body):
                status, _, _ = self.request("/api/setup", body, self.setup_headers())
                self.assertEqual(status, 400)
                self.assert_no_account()
                self.assertTrue(self.request("/api/session")[1]["setup_required"])

    def test_configured_https_origin_is_required_and_succeeds_with_matching_host(self):
        self.app.origin = "https://nas.example.test:5000"
        for origin in (None, self.origin, "https://foreign.example"):
            with self.subTest(origin=origin):
                self.assertEqual(self.setup(**{"Origin": origin})[0], 403)
                self.assert_no_account()
        self.assertEqual(self.setup()[0], 200)

    def test_existing_non_admin_account_closes_setup_and_hides_the_nonce(self):
        self.app.store.create_user("reader", self.password, "user", "reader")
        status, session, _ = self.request("/api/session")
        self.assertEqual(status, 200)
        self.assertFalse(session["setup_required"])
        self.assertNotIn("setup_csrf", session)
        self.assertEqual(self.setup()[0], 409)
        self.assertEqual([user["name"] for user in self.app.store.users()], ["reader"])
        self.agent.call.assert_not_called()

    def test_disabled_accounts_do_not_reopen_first_setup(self):
        self.app.store.create_user("reader", self.password, "user", "reader")
        self.app.store.update_user("reader", enabled=False)
        session = self.request("/api/session")[1]
        self.assertFalse(session["setup_required"])
        self.assertNotIn("setup_csrf", session)
        self.assertEqual(self.setup()[0], 409)
        self.assertEqual(self.app.store.users(), [{"name": "reader", "role": "user",
                                                  "system_user": "reader", "enabled": False,
                                                  "display_name": "", "description": ""}])

    def test_concurrent_setup_requests_create_exactly_one_administrator(self):
        barrier = threading.Barrier(2)

        def submit(name):
            barrier.wait(timeout=5)
            return self.setup(name=name)[0]

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(submit, ("alice", "bob")))
        self.assertEqual(sorted(results), [200, 409])
        users = self.app.store.users()
        self.assertEqual(len(users), 1)
        self.assertIn(users[0]["name"], {"alice", "bob"})
        self.assertEqual(users[0]["role"], "admin")
        self.assertEqual(users[0]["system_user"], users[0]["name"])
        self.agent.call.assert_called_once_with("account_create", name=users[0]["name"], password=self.password)

    def test_service_restart_invalidates_the_old_setup_page_nonce(self):
        old_nonce = self.request("/api/session")[1]["setup_csrf"]
        self.app = Application(self.temp.name)
        self.server.app = self.app
        new_nonce = self.request("/api/session")[1]["setup_csrf"]
        self.assertNotEqual(new_nonce, old_nonce)
        self.assertEqual(self.setup(**{"X-CSRF-Token": old_nonce})[0], 403)
        self.assert_no_account()
        self.assertEqual(self.setup(**{"X-CSRF-Token": new_nonce})[0], 200)

    def test_http_login_creates_fresh_session_with_csrf_and_logout(self):
        self.assertEqual(self.setup()[0], 200)
        status, login, headers = self.request("/api/login", {
            "name": "admin", "password": self.password}, {
            "Origin": self.origin, "Content-Type": "application/json",
            "Cookie": "titan_session=attacker-supplied-session"})
        self.assertEqual(status, 200)
        cookie = SimpleCookie(headers["Set-Cookie"])["titan_session"]
        self.assertNotEqual(cookie.value, "attacker-supplied-session")
        self.assertFalse(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertEqual(cookie["path"], "/")
        self.assertEqual(cookie["max-age"], "43200")
        session_headers = {"Cookie": f"titan_session={cookie.value}"}
        session = self.request("/api/session", headers=session_headers)[1]
        self.assertFalse(session["setup_required"])
        self.assertNotIn("setup_csrf", session)
        self.assertEqual(session["user"]["name"], "admin")
        self.assertEqual(session["user"]["role"], "admin")
        self.assertEqual(session["user"]["csrf"], login["csrf"])
        self.assertEqual(self.request("/api/settings", {"auto_check": False}, {
            **session_headers, "Content-Type": "application/json"})[0], 403)
        mutation_headers = {**session_headers, "Content-Type": "application/json",
                            "Origin": self.origin, "X-CSRF-Token": login["csrf"]}
        self.assertEqual(self.request("/api/settings", {"auto_check": False}, mutation_headers)[0], 200)
        self.assertEqual(self.request("/api/logout", {}, mutation_headers)[0], 200)
        self.assertIsNone(self.request("/api/session", headers=session_headers)[1]["user"])
        self.agent.call.assert_called_once_with("account_create", name="admin", password=self.password)

    def test_failed_login_does_not_issue_a_session(self):
        self.assertEqual(self.setup()[0], 200)
        status, _, headers = self.request("/api/login", {
            "name": "admin", "password": "wrong-long-password"}, {
            "Origin": self.origin, "Content-Type": "application/json"})
        self.assertEqual(status, 401)
        self.assertIsNone(headers.get("Set-Cookie"))
        self.assertIsNone(self.request("/api/session")[1]["user"])


if __name__ == "__main__":
    unittest.main()

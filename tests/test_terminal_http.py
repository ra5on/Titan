"""Terminal routing/authentication tests without sockets or real host shells."""
import base64
from email.message import Message
import io
import json
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call

from titan.core import Error, Store
from titan.server import Handler
from titan.terminal_http import TerminalApplicationMixin, terminal_owner


TERMINAL_ID = "ab" * 32


class _Stop:
    def __init__(self):
        self.stopped = False
        self.waits = 0

    def is_set(self):
        return self.stopped

    def wait(self, timeout):
        self.waits += 1
        if self.waits > 20:
            raise AssertionError("Unbounded test SSE stream")
        return self.stopped


class _Application(TerminalApplicationMixin):
    pass


class TerminalHTTPTests(unittest.TestCase):
    def setUp(self):
        self.users = {
            "admin": {"name": "admin", "role": "admin", "system_user": "admin", "csrf": "csrf-login-one"},
            "admin-second-login": {"name": "admin", "role": "admin", "system_user": "admin", "csrf": "csrf-login-two"},
            "reader": {"name": "reader", "role": "user", "system_user": "reader", "csrf": "csrf-reader"},
        }
        self.tokens = {name: "test-cookie-" + name for name in self.users}
        self.sessions = {self.tokens[name]: user for name, user in self.users.items()}
        self.agent = Mock()
        self.agent.call.return_value = {"id": TERMINAL_ID, "cols": 100, "rows": 30,
                                        "exited": False, "exit_code": None}
        def session(token):
            current = self.sessions.get(token)
            return dict(current) if current is not None else None
        self.store = SimpleNamespace(session=Mock(side_effect=session), audit=Mock(),
                                     logout=Mock(side_effect=lambda token: self.sessions.pop(token, None)))
        self.app = _Application()
        self.app.__dict__.update(
            demo=False, origin=None, agent=self.agent, store=self.store,
            terminal_stream_lock=threading.Lock(), terminal_streams=set(), stop=_Stop())
        self.app.initialize_terminals()
        self.app._start_terminal_reaper = Mock()
        self.app._terminal_user_active = lambda user: any(
            current['name'] == user['name'] and current['csrf'] == user['csrf'] and current['role'] == 'admin'
            for current in self.sessions.values())

    def handler(self, method, path, body=None, actor="admin", csrf="default", headers=None):
        # Exercise Handler's real routes, JSON parser, role/CSRF/origin checks
        # and SSE implementation.  Only HTTP transport framing is replaced.
        handler = object.__new__(Handler)
        handler.server = SimpleNamespace(app=self.app)
        handler.command = method
        handler.path = path
        handler.client_address = ("127.0.0.1", 12345)
        handler.close_connection = False
        handler.statuses = []
        handler.response_headers = []
        handler.send_response = lambda status: handler.statuses.append(status)
        handler.send_header = lambda key, value: handler.response_headers.append((key, value))
        handler.end_headers = lambda: None
        handler.headers = Message()
        values = {"Host": "nas.test", "Content-Type": "application/json"}
        if actor:
            values["Cookie"] = "titan_session=" + self.tokens[actor]
            if csrf is not None:
                values["X-CSRF-Token"] = self.users[actor]["csrf"] if csrf == "default" else csrf
        data = json.dumps(body).encode() if body is not None else b""
        values["Content-Length"] = str(len(data))
        values.update(headers or {})
        for key, value in values.items():
            handler.headers[key] = value
        handler.rfile = io.BytesIO(data)
        handler.wfile = io.BytesIO()
        return handler

    def request(self, method, path, body=None, **options):
        handler = self.handler(method, path, body, **options)
        (handler.do_POST if method == "POST" else handler.do_GET)()
        self.assertTrue(handler.statuses, "Handler did not respond")
        return handler

    def json_response(self, handler):
        return json.loads(handler.wfile.getvalue())

    def stream_results(self, *results, on_poll=None):
        remaining = iter(results)
        def dispatch(operation, **arguments):
            if operation == "terminal_poll":
                result = next(remaining)
                if on_poll:
                    on_poll(arguments)
                return result
            if operation == "terminal_close":
                return {"id": TERMINAL_ID, "closed": True}
            raise AssertionError("Unexpected terminal operation")
        self.agent.call.side_effect = dispatch

    def events(self, handler):
        result = []
        for block in handler.wfile.getvalue().decode().split("\n\n"):
            lines = block.splitlines()
            if not lines or lines[0].startswith(":"):
                continue
            self.assertEqual(len(lines), 2)
            result.append((lines[0].removeprefix("event: "),
                           json.loads(lines[1].removeprefix("data: "))))
        return result

    def test_terminal_routes_require_admin_cookie(self):
        for actor, status in ((None, 401), ("reader", 403)):
            with self.subTest(actor=actor):
                self.assertEqual(self.request("POST", "/api/terminal", {"action": "create"}, actor=actor).statuses, [status])
                self.assertEqual(self.request("GET", "/api/terminal/output?id=" + TERMINAL_ID, actor=actor).statuses, [status])
        self.agent.call.assert_not_called()

    def test_all_terminal_mutations_require_csrf(self):
        bodies = ({"action": "create"}, {"action": "write", "id": TERMINAL_ID, "data": "eA=="},
                  {"action": "resize", "id": TERMINAL_ID, "cols": 80, "rows": 24},
                  {"action": "close", "id": TERMINAL_ID})
        for body in bodies:
            for csrf in (None, "wrong-login"):
                with self.subTest(action=body["action"], csrf=csrf):
                    handler = self.request("POST", "/api/terminal", body, csrf=csrf)
                    self.assertEqual(handler.statuses, [403])
        self.agent.call.assert_not_called()

    def test_foreign_origin_and_cross_site_requests_are_rejected(self):
        for headers in ({"Origin": "https://other.test"}, {"Sec-Fetch-Site": "cross-site"}):
            for method, path, body in (("POST", "/api/terminal", {"action": "create"}),
                                       ("GET", "/api/terminal/output?id=" + TERMINAL_ID, None)):
                with self.subTest(method=method, headers=headers):
                    self.assertEqual(self.request(method, path, body, headers=headers).statuses, [403])
        self.agent.call.assert_not_called()

    def test_create_defaults_are_fixed_and_owner_is_derived_from_login(self):
        handler = self.request("POST", "/api/terminal", {"action": "create"})
        self.assertEqual(handler.statuses, [200])
        self.assertEqual(self.json_response(handler)["id"], TERMINAL_ID)
        self.agent.call.assert_called_once_with("terminal_create", owner="admin.csrf-login-one", cols=100, rows=30)
        self.assertIn(("admin.csrf-login-one", TERMINAL_ID), self.app.terminal_sessions)

    def test_created_terminal_is_closed_when_json_reply_disconnects(self):
        handler = self.handler("POST", "/api/terminal", {"action": "create"})
        handler.wfile = Mock()
        handler.wfile.write.side_effect = BrokenPipeError()
        handler.do_POST()
        self.agent.call.assert_any_call("terminal_close", owner="admin.csrf-login-one", id=TERMINAL_ID)
        self.assertEqual(self.app.terminal_sessions, {})

    def test_create_in_flight_after_logout_never_returns_a_live_session(self):
        def dispatch(operation, **arguments):
            if operation == "terminal_create":
                self.sessions.pop(self.tokens["admin"])
                return {"id": TERMINAL_ID, "cols": 100, "rows": 30}
            if operation == "terminal_close":
                return {"closed": True}
            raise AssertionError("Unexpected terminal operation")
        self.agent.call.side_effect = dispatch
        handler = self.request("POST", "/api/terminal", {"action": "create"})
        self.assertEqual(handler.statuses, [403])
        self.agent.call.assert_any_call("terminal_close", owner="admin.csrf-login-one", id=TERMINAL_ID)
        self.assertEqual(self.app.terminal_sessions, {})
        self.store.audit.assert_not_called()

    def test_logout_closes_only_the_current_login_even_without_sse(self):
        self.app.track_terminal(self.users["admin"], TERMINAL_ID)
        other_id = "cd" * 32
        self.app.track_terminal(self.users["admin-second-login"], other_id)
        handler = self.request("POST", "/api/logout", {})
        self.assertEqual(handler.statuses, [200])
        self.store.logout.assert_called_once_with(self.tokens["admin"])
        self.agent.call.assert_called_once_with("terminal_close", owner="admin.csrf-login-one", id=TERMINAL_ID)
        self.assertEqual(set(self.app.terminal_sessions), {("admin.csrf-login-two", other_id)})

    def test_only_nonempty_terminal_input_refreshes_idle_lifetime(self):
        self.app.track_terminal(self.users["admin"], TERMINAL_ID)
        entry = self.app.terminal_sessions[("admin.csrf-login-one", TERMINAL_ID)]
        entry["activity"] -= 10
        activity = entry["activity"]
        self.request("POST", "/api/terminal", {"action": "resize", "id": TERMINAL_ID, "cols": 120, "rows": 42})
        self.request("POST", "/api/terminal", {"action": "write", "id": TERMINAL_ID, "data": ""})
        self.assertEqual(entry["activity"], activity)
        self.request("POST", "/api/terminal", {"action": "write", "id": TERMINAL_ID, "data": "eA=="})
        self.assertGreater(entry["activity"], activity)

    def test_auth_race_close_failure_remains_tracked_for_retry(self):
        def dispatch(operation, **arguments):
            if operation == "terminal_create":
                self.sessions.pop(self.tokens["admin"])
                return {"id": TERMINAL_ID}
            raise Error("Agent temporarily unavailable", 503)
        self.agent.call.side_effect = dispatch
        handler = self.request("POST", "/api/terminal", {"action": "create"})
        self.assertEqual(handler.statuses, [403])
        self.assertTrue(self.app.terminal_sessions[("admin.csrf-login-one", TERMINAL_ID)]["closing"])
        self.agent.call.side_effect = None
        self.agent.call.return_value = {"closed": True}
        self.app.reap_terminals()
        self.assertEqual(self.app.terminal_sessions, {})

    def test_write_resize_and_close_dispatch_synchronous_bound_operations(self):
        bodies = ({"action": "write", "id": TERMINAL_ID, "data": "AAM="},
                  {"action": "resize", "id": TERMINAL_ID, "cols": 120, "rows": 42},
                  {"action": "close", "id": TERMINAL_ID})
        for body in bodies:
            self.assertEqual(self.request("POST", "/api/terminal", body).statuses, [200])
        self.assertEqual(self.agent.call.call_args_list, [
            call("terminal_write", owner="admin.csrf-login-one", id=TERMINAL_ID, data="AAM="),
            call("terminal_resize", owner="admin.csrf-login-one", id=TERMINAL_ID, cols=120, rows=42),
            call("terminal_close", owner="admin.csrf-login-one", id=TERMINAL_ID)])

    def test_second_login_cannot_supply_the_first_login_owner(self):
        self.request("POST", "/api/terminal", {"action": "close", "id": TERMINAL_ID}, actor="admin-second-login")
        self.agent.call.assert_called_once_with("terminal_close", owner="admin.csrf-login-two", id=TERMINAL_ID)
        self.agent.call.reset_mock()
        for extra in ("owner", "user", "root", "cwd", "shell", "env", "command"):
            body = {"action": "create", extra: "injected"}
            self.assertEqual(self.request("POST", "/api/terminal", body).statuses, [400])
        self.agent.call.assert_not_called()

    def test_unknown_actions_extra_fields_and_nonobject_body_are_rejected(self):
        bodies = ([], "text", None, {}, {"action": "execute"}, {"action": ["create"]},
                  {"action": "close", "id": TERMINAL_ID, "data": "eA=="},
                  {"action": "write", "id": TERMINAL_ID, "data": "eA==", "timeout": 9})
        for body in bodies:
            with self.subTest(body=body):
                self.assertEqual(self.request("POST", "/api/terminal", body).statuses, [400])
        self.agent.call.assert_not_called()

    def test_id_must_be_exactly_64_lowercase_hex_characters(self):
        for token in (None, 123, [], "", "a" * 63, "a" * 65, "AB" * 32, "g" * 64, "../etc/passwd"):
            for action in ("write", "resize", "close"):
                body = {"action": action, "id": token}
                if action == "write":
                    body["data"] = "eA=="
                if action == "resize":
                    body.update(cols=80, rows=24)
                with self.subTest(token=token, action=action):
                    self.assertEqual(self.request("POST", "/api/terminal", body).statuses, [400])
        self.agent.call.assert_not_called()

    def test_dimensions_require_bounded_integer_json_values(self):
        for cols, rows in ((19, 24), (501, 24), (80, 4), (80, 201),
                           (True, 24), (80, False), ("80", 24), (80.9, 24), (80, 24.9), (80, None)):
            for action in ("create", "resize"):
                body = {"action": action, "cols": cols, "rows": rows}
                if action == "resize":
                    body["id"] = TERMINAL_ID
                with self.subTest(cols=cols, rows=rows, action=action):
                    self.assertEqual(self.request("POST", "/api/terminal", body).statuses, [400])
        self.agent.call.assert_not_called()

    def test_resize_requires_both_dimensions(self):
        for body in ({"action": "resize", "id": TERMINAL_ID},
                     {"action": "resize", "id": TERMINAL_ID, "cols": 80},
                     {"action": "resize", "id": TERMINAL_ID, "rows": 24}):
            self.assertEqual(self.request("POST", "/api/terminal", body).statuses, [400])
        self.agent.call.assert_not_called()

    def test_write_requires_valid_bounded_base64(self):
        for data in (None, 123, [], "!not-base64!", "é", "e A==", "x" * 22001):
            with self.subTest(data_type=type(data).__name__):
                handler = self.request("POST", "/api/terminal", {"action": "write", "id": TERMINAL_ID, "data": data})
                self.assertEqual(handler.statuses, [400])
        self.agent.call.assert_not_called()

    def test_stream_rejects_credentials_unknown_options_and_invalid_ids(self):
        queries = ("", "id=bad", "id=" + TERMINAL_ID + "&owner=admin",
                   "id=" + TERMINAL_ID + "&csrf=login", "id=" + TERMINAL_ID + "&token=cookie")
        for query in queries:
            with self.subTest(query=query):
                self.assertEqual(self.request("GET", "/api/terminal/output?" + query).statuses, [400])
        self.agent.call.assert_not_called()

    def test_stream_rejects_duplicate_or_blank_query_options(self):
        queries = ("id=" + TERMINAL_ID + "&id=" + TERMINAL_ID,
                   "id=wrong&id=" + TERMINAL_ID,
                   "id=" + TERMINAL_ID + "&owner=", "id=" + TERMINAL_ID + "&csrf=")
        self.stream_results({"data": "", "eof": True, "exit_code": 0},
                            {"data": "", "eof": True, "exit_code": 0},
                            {"data": "", "eof": True, "exit_code": 0},
                            {"data": "", "eof": True, "exit_code": 0})
        for query in queries:
            with self.subTest(query=query):
                self.assertEqual(self.request("GET", "/api/terminal/output?" + query).statuses, [400])
        self.agent.call.assert_not_called()

    def test_sse_delivers_opaque_base64_tail_then_exit_and_cleans_up(self):
        first = base64.b64encode(b"test\x1b[31moutput\x00\xff").decode()
        tail = base64.b64encode(b"final\r\n").decode()
        self.stream_results({"data": first, "eof": False, "exit_code": None},
                            {"data": tail, "eof": True, "exit_code": 17})
        handler = self.request("GET", "/api/terminal/output?id=" + TERMINAL_ID, csrf=None)
        self.assertEqual(handler.statuses, [200])
        self.assertEqual(self.events(handler), [("output", {"data": first}), ("output", {"data": tail}),
                                                ("exit", {"exit_code": 17})])
        headers = dict(handler.response_headers)
        self.assertEqual(headers["Content-Type"], "text/event-stream; charset=utf-8")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Accel-Buffering"], "no")
        self.assertTrue(handler.close_connection)
        self.assertEqual(self.app.terminal_streams, set())
        self.assertEqual(self.agent.call.call_args_list, [
            call("terminal_poll", owner="admin.csrf-login-one", id=TERMINAL_ID, timeout=0),
            call("terminal_poll", owner="admin.csrf-login-one", id=TERMINAL_ID, timeout=0.5),
            call("terminal_close", owner="admin.csrf-login-one", id=TERMINAL_ID)])
        self.store.audit.assert_not_called()

    def test_stream_does_not_stop_before_eof_when_exit_code_arrives_early(self):
        self.stream_results({"data": "YQ==", "eof": False, "exit_code": 0},
                            {"data": "Yg==", "eof": True, "exit_code": 0})
        handler = self.request("GET", "/api/terminal/output?id=" + TERMINAL_ID)
        self.assertEqual(self.events(handler), [("output", {"data": "YQ=="}),
                                                ("output", {"data": "Yg=="}), ("exit", {"exit_code": 0})])

    def test_authentication_or_owner_revocation_before_first_output_closes_stream(self):
        for change in ("logout", "role", "login"):
            with self.subTest(change=change):
                self.setUp()
                def revoke(arguments):
                    if change == "logout":
                        self.sessions.pop(self.tokens["admin"])
                    elif change == "role":
                        self.users["admin"]["role"] = "user"
                    else:
                        self.users["admin"]["csrf"] = "another-login"
                self.stream_results({"data": "c2VjcmV0", "eof": False, "exit_code": None}, on_poll=revoke)
                handler = self.request("GET", "/api/terminal/output?id=" + TERMINAL_ID)
                self.assertEqual(handler.statuses, [403])
                self.assertIn("error", self.json_response(handler))
                self.agent.call.assert_any_call("terminal_close", owner="admin.csrf-login-one", id=TERMINAL_ID)
                self.assertEqual(self.app.terminal_streams, set())

    def test_auth_revocation_during_blocking_poll_prevents_further_output(self):
        polls = 0
        def revoke_after_wait(arguments):
            nonlocal polls
            polls += 1
            if polls == 2:
                self.sessions.pop(self.tokens["admin"])
        self.stream_results({"data": "", "eof": False, "exit_code": None},
                            {"data": "c2VjcmV0", "eof": False, "exit_code": None}, on_poll=revoke_after_wait)
        handler = self.request("GET", "/api/terminal/output?id=" + TERMINAL_ID)
        self.assertEqual([name for name, _ in self.events(handler)], ["exit"])
        self.agent.call.assert_any_call("terminal_close", owner="admin.csrf-login-one", id=TERMINAL_ID)

    def test_duplicate_stream_does_not_poll_or_close_existing_session(self):
        key = (terminal_owner(self.users["admin"]), TERMINAL_ID)
        self.app.terminal_streams.add(key)
        handler = self.request("GET", "/api/terminal/output?id=" + TERMINAL_ID)
        self.assertEqual(handler.statuses, [409])
        self.assertEqual(self.app.terminal_streams, {key})
        self.agent.call.assert_not_called()

    def test_preflight_agent_error_keeps_json_status_and_does_not_close_foreign_id(self):
        self.agent.call.side_effect = Error("Terminalsitzung nicht gefunden.", 404)
        handler = self.request("GET", "/api/terminal/output?id=" + TERMINAL_ID)
        self.assertEqual(handler.statuses, [404])
        self.assertIn("error", self.json_response(handler))
        self.agent.call.assert_called_once_with("terminal_poll", owner="admin.csrf-login-one", id=TERMINAL_ID, timeout=0)
        self.assertEqual(self.app.terminal_streams, set())

    def test_agent_error_after_acceptance_sends_exit_and_closes(self):
        def dispatch(operation, **arguments):
            if operation == "terminal_close":
                return {"closed": True}
            if arguments["timeout"] == 0:
                return {"data": "", "eof": False}
            raise Error("Terminaldienst nicht erreichbar.", 503)
        self.agent.call.side_effect = dispatch
        handler = self.request("GET", "/api/terminal/output?id=" + TERMINAL_ID)
        self.assertEqual(handler.statuses, [200])
        self.assertEqual(self.events(handler), [("exit", {"error": "Terminaldienst nicht erreichbar."})])
        self.agent.call.assert_any_call("terminal_close", owner="admin.csrf-login-one", id=TERMINAL_ID)
        self.assertEqual(self.app.terminal_streams, set())

    def test_output_disconnect_always_closes_valid_session(self):
        self.stream_results({"data": "eA==", "eof": False, "exit_code": None})
        handler = self.handler("GET", "/api/terminal/output?id=" + TERMINAL_ID)
        handler.wfile = Mock()
        handler.wfile.write.side_effect = BrokenPipeError()
        handler.do_GET()
        self.agent.call.assert_any_call("terminal_close", owner="admin.csrf-login-one", id=TERMINAL_ID)
        self.assertEqual(self.app.terminal_streams, set())

    def test_header_disconnect_always_closes_valid_session(self):
        self.stream_results({"data": "", "eof": False, "exit_code": None})
        handler = self.handler("GET", "/api/terminal/output?id=" + TERMINAL_ID)
        handler.end_headers = Mock(side_effect=BrokenPipeError())
        handler.do_GET()
        self.agent.call.assert_any_call("terminal_close", owner="admin.csrf-login-one", id=TERMINAL_ID)
        self.assertEqual(self.app.terminal_streams, set())

    def test_application_shutdown_closes_stream_without_more_polls(self):
        def stop_after_preflight(arguments):
            self.app.stop.stopped = True
        self.stream_results({"data": "", "eof": False, "exit_code": None}, on_poll=stop_after_preflight)
        handler = self.request("GET", "/api/terminal/output?id=" + TERMINAL_ID)
        self.assertEqual(handler.statuses, [503])
        self.assertIn("error", self.json_response(handler))
        self.agent.call.assert_any_call("terminal_close", owner="admin.csrf-login-one", id=TERMINAL_ID)

    def test_audit_contains_only_open_close_metadata_and_never_terminal_data(self):
        private_input = base64.b64encode(b"private-stdin-marker\n").decode()
        for body in ({"action": "create"}, {"action": "write", "id": TERMINAL_ID, "data": private_input},
                     {"action": "resize", "id": TERMINAL_ID, "cols": 80, "rows": 24},
                     {"action": "close", "id": TERMINAL_ID}):
            self.assertEqual(self.request("POST", "/api/terminal", body).statuses, [200])
        self.assertEqual([item.args[1] for item in self.store.audit.call_args_list], ["terminal_create", "terminal_close"])
        audit = str(self.store.audit.call_args_list)
        for secret in (private_input, "private-stdin-marker", TERMINAL_ID, self.users["admin"]["csrf"], self.tokens["admin"]):
            self.assertNotIn(secret, audit)


class TerminalApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(self.temporary.name)
        self.store.setup("admin", "administrator-test-password")
        self.token, _ = self.store.login("admin", "administrator-test-password")
        self.second_token, _ = self.store.login("admin", "administrator-test-password")
        self.user = self.store.session(self.token)
        self.second_user = self.store.session(self.second_token)
        self.app = _Application()
        self.app.__dict__.update(demo=False, store=self.store, agent=Mock(), stop=threading.Event())
        self.app.agent.call.return_value = {"closed": True}
        self.app.initialize_terminals()
        self.app._start_terminal_reaper = Mock()

    def tearDown(self):
        self.app.close_all_terminals()
        self.temporary.cleanup()

    def test_reaper_closes_logged_out_login_without_touching_other_login(self):
        self.app.track_terminal(self.user, TERMINAL_ID)
        other_id = "cd" * 32
        self.app.track_terminal(self.second_user, other_id)
        self.store.logout(self.token)
        self.app.reap_terminals()
        self.app.agent.call.assert_called_once_with("terminal_close", owner=terminal_owner(self.user), id=TERMINAL_ID)
        self.assertEqual(set(self.app.terminal_sessions), {(terminal_owner(self.second_user), other_id)})

    def test_reaper_checks_role_enabled_state_and_database_expiry(self):
        for field, value in (("role", "user"), ("enabled", 0), ("expires", time.time() - 1)):
            with self.subTest(field=field):
                self.app.track_terminal(self.user, TERMINAL_ID)
                with self.store.connection() as db:
                    if field == "expires":
                        db.execute("UPDATE sessions SET expires=? WHERE csrf=?", (value, self.user['csrf']))
                    else:
                        db.execute("UPDATE users SET " + field + "=? WHERE name='admin'", (value,))
                self.app.reap_terminals()
                self.assertEqual(self.app.terminal_sessions, {})
                self.app.agent.call.assert_called_once_with("terminal_close", owner=terminal_owner(self.user), id=TERMINAL_ID)
                self.app.agent.call.reset_mock()
                with self.store.connection() as db:
                    db.execute("UPDATE users SET role='admin', enabled=1 WHERE name='admin'")
                    db.execute("UPDATE sessions SET expires=? WHERE csrf=?", (time.time() + 3600, self.user['csrf']))

    def test_invalidated_create_is_rejected_and_closed_using_original_owner(self):
        self.store.logout(self.token)
        with self.assertRaises(Error) as failure:
            self.app.track_terminal(self.user, TERMINAL_ID)
        self.assertEqual(failure.exception.status, 403)
        self.app.agent.call.assert_called_once_with("terminal_close", owner=terminal_owner(self.user), id=TERMINAL_ID)
        self.assertEqual(self.app.terminal_sessions, {})

    def test_registry_is_bounded_and_rejects_a_fifth_session(self):
        for index in range(4):
            self.app.track_terminal(self.user if index < 2 else self.second_user, f"{index:064x}")
        new_id = "ef" * 32
        with self.assertRaises(Error) as failure:
            self.app.track_terminal(self.user, new_id)
        self.assertEqual(failure.exception.status, 429)
        self.assertEqual(len(self.app.terminal_sessions), 4)
        self.app.agent.call.assert_called_once_with("terminal_close", owner=terminal_owner(self.user), id=new_id)

    def test_transient_close_errors_are_retained_and_retried_once_per_sweep(self):
        self.app.track_terminal(self.user, TERMINAL_ID)
        self.app.agent.call.side_effect = Error("Agent temporarily unavailable", 503)
        self.app.close_terminal_owner(terminal_owner(self.user))
        self.assertTrue(self.app.terminal_sessions[(terminal_owner(self.user), TERMINAL_ID)]["closing"])
        self.app.reap_terminals()
        self.assertEqual(self.app.agent.call.call_count, 2)
        self.app.agent.call.side_effect = None
        self.app.reap_terminals()
        self.assertEqual(self.app.terminal_sessions, {})
        self.assertEqual(self.app.agent.call.call_count, 3)

    def test_unknown_or_expired_agent_sessions_are_forgotten(self):
        for status in (404, 410):
            with self.subTest(status=status):
                self.app.track_terminal(self.user, TERMINAL_ID)
                self.app.agent.call.side_effect = Error("Session already gone", status)
                self.assertTrue(self.app.close_terminal_session(terminal_owner(self.user), TERMINAL_ID))
                self.assertEqual(self.app.terminal_sessions, {})

    def test_idle_and_maximum_lifetime_expire_even_with_valid_login(self):
        self.app.track_terminal(self.user, TERMINAL_ID)
        entry = self.app.terminal_sessions[(terminal_owner(self.user), TERMINAL_ID)]
        entry["activity"] -= 15 * 60 + 1
        self.app.reap_terminals()
        self.assertEqual(self.app.terminal_sessions, {})
        self.app.track_terminal(self.user, TERMINAL_ID)
        entry = self.app.terminal_sessions[(terminal_owner(self.user), TERMINAL_ID)]
        entry["created"] -= 8 * 60 * 60 + 1
        entry["activity"] = time.monotonic()
        self.app.reap_terminals()
        self.assertEqual(self.app.terminal_sessions, {})

    def test_shutdown_closes_tracked_sessions_and_rejects_inflight_registration(self):
        self.app.track_terminal(self.user, TERMINAL_ID)
        self.app.close_all_terminals()
        self.assertEqual(self.app.terminal_sessions, {})
        self.app.agent.call.reset_mock()
        new_id = "ef" * 32
        with self.assertRaises(Error) as failure:
            self.app.track_terminal(self.user, new_id)
        self.assertEqual(failure.exception.status, 503)
        self.app.agent.call.assert_called_once_with("terminal_close", owner=terminal_owner(self.user), id=new_id)

    def test_reaper_is_lazy_and_stops_on_shutdown(self):
        self.assertIsNone(self.app._terminal_reaper)
        del self.app.__dict__["_start_terminal_reaper"]
        swept = threading.Event()
        with unittest.mock.patch.object(self.app, "reap_terminals", side_effect=swept.set):
            self.app._start_terminal_reaper()
            self.assertTrue(swept.wait(timeout=3))
            self.app.close_all_terminals()
        self.assertFalse(self.app._terminal_reaper.is_alive())

    def test_demo_reaper_uses_enabled_admin_metadata_and_fixed_demo_identity(self):
        self.app.demo = True
        self.app.store = SimpleNamespace(user_record=Mock(return_value={"enabled": True, "role": "admin"}))
        user = {"name": "demo", "csrf": "demo-only"}
        self.app.track_terminal(user, TERMINAL_ID)
        self.app.store.user_record.return_value = {"enabled": False, "role": "admin"}
        self.app.reap_terminals()
        self.app.agent.call.assert_called_once_with("terminal_close", owner="demo.demo-only", id=TERMINAL_ID)
        self.assertEqual(self.app.terminal_sessions, {})


if __name__ == "__main__":
    unittest.main()

from http.server import ThreadingHTTPServer
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock

from titan.core import Error
from titan.server import Application, Handler


class HTTPFixture:
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.app = Application(self.temporary.name)
        self.app.store.setup("admin", "admin-original-password")
        self.app.store.create_user("reader", "reader-original-password", "user", "reader")
        self.agent = Mock()
        self.agent.call.return_value = {"ok": True}
        self.app.agent = self.agent
        self.app.users.agent = self.agent
        self.tokens = {actor: self.app.store.login(actor, actor + "-original-password") for actor in ("admin", "reader")}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.app = self.app
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        deadline = time.monotonic() + 3
        while any(item["status"] in ("queued", "running") for item in self.app.store.jobs()) and time.monotonic() < deadline:
            time.sleep(.01)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def request(self, path, body=None, actor="admin", csrf=None, headers=None):
        request_headers = {"Content-Type": "application/json"}
        if actor:
            token, expected_csrf = self.tokens[actor]
            request_headers.update(Cookie="titan_session=" + token)
            request_headers["X-CSRF-Token"] = expected_csrf if csrf is None else csrf
        request_headers.update(headers or {})
        request = urllib.request.Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                                         headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as response:
            return response.code, response.read(), response.headers

    def json_request(self, *args, **kwargs):
        status, body, headers = self.request(*args, **kwargs)
        return status, json.loads(body), headers

    def wait_job(self, identifier):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = next(item for item in self.app.store.jobs() if item["id"] == identifier)
            if result["status"] in ("completed", "failed"):
                return result
            time.sleep(.01)
        self.fail("Queued lifecycle action did not finish")


class LifecycleHTTPTests(HTTPFixture, unittest.TestCase):
    def test_app_details_and_iso_library_are_admin_only(self):
        for path in ("/api/app-details?app=jellyfin", "/api/iso-library", "/api/isos"):
            self.assertEqual(self.request(path, actor=None)[0], 401)
            self.assertEqual(self.request(path, actor="reader")[0], 403)
        self.agent.call.assert_not_called()

    def test_app_details_validates_tail_and_dispatches_bounded_request(self):
        self.agent.call.return_value = {"app": {"id": "jellyfin"}, "logs": "ready"}
        status, result, _ = self.json_request("/api/app-details?app=jellyfin&tail=40")
        self.assertEqual(status, 200)
        self.assertEqual(result["logs"], "ready")
        self.agent.call.assert_called_once_with("app_details", app="jellyfin", tail=40)
        self.agent.call.reset_mock()
        for tail in ("0", "501", "bad"):
            self.assertEqual(self.request("/api/app-details?app=jellyfin&tail=" + tail)[0], 400)
        self.agent.call.assert_not_called()

    def test_iso_upload_requires_declared_total_and_rejects_extra_options(self):
        valid = {"name": "linux.iso", "offset": 0, "data": "aGVsbG8=", "total": 5}
        invalid = [dict((key, value) for key, value in valid.items() if key != "total"),
                   {**valid, "root": "/etc"}, {**valid, "final": True}]
        for body in invalid:
            self.assertEqual(self.request("/api/isos", body)[0], 400)
        self.agent.call.assert_not_called()
        self.assertEqual(self.request("/api/isos", valid)[0], 200)
        self.agent.call.assert_called_once_with("iso_upload", **valid)

    def test_iso_continuation_passes_upload_id_without_host_path_flags(self):
        body = {"name": "linux.iso", "offset": 5, "data": "Ynl0ZXM=", "total": 10, "upload_id": "abc"}
        self.assertEqual(self.request("/api/isos", body)[0], 200)
        self.agent.call.assert_called_once_with("iso_upload", **body)

    def test_iso_upload_and_cancel_enforce_admin_csrf_and_origin(self):
        requests = (("/api/isos", {"name": "linux.iso", "offset": 0, "data": "", "total": 0}),
                    ("/api/isos/cancel", {"upload_id": "abc"}))
        for path, body in requests:
            self.assertEqual(self.request(path, body, actor="reader")[0], 403)
            self.assertEqual(self.request(path, body, csrf="wrong")[0], 403)
            self.assertEqual(self.request(path, body, headers={"Origin": "https://foreign.example"})[0], 403)
        self.agent.call.assert_not_called()

    def test_cancel_requires_only_upload_id(self):
        for body in ({}, {"upload_id": "abc", "name": "linux.iso"}, {"upload_id": "abc", "root": "/tmp"}):
            self.assertEqual(self.request("/api/isos/cancel", body)[0], 400)
        self.agent.call.assert_not_called()
        self.assertEqual(self.request("/api/isos/cancel", {"upload_id": "abc"})[0], 200)
        self.agent.call.assert_called_once_with("iso_cancel", upload_id="abc")

    def test_vm_media_and_iso_remove_queue_only_for_authorized_admin(self):
        actions = (("vm_media", {"vm": "vm-uuid", "iso": None}),
                   ("iso_remove", {"name": "linux.iso"}))
        for operation, arguments in actions:
            body = {"operation": operation, "arguments": arguments}
            self.assertEqual(self.request("/api/actions", body, actor="reader")[0], 403)
            self.assertEqual(self.request("/api/actions", body, csrf="wrong")[0], 403)
        self.agent.call.assert_not_called()
        for operation, arguments in actions:
            status, result, _ = self.json_request("/api/actions", {"operation": operation, "arguments": arguments})
            self.assertEqual(status, 202)
            self.assertEqual(self.wait_job(result["job"])["status"], "completed")
            self.agent.call.assert_any_call(operation, **arguments)

    def test_lifecycle_job_rechecks_actor_role_before_privileged_execution(self):
        self.app.store.create_user("second", "second-long-password", "admin", "second")
        self.app.store.update_user("admin", role="user")
        for operation, arguments in (("vm_media", {"vm": "id", "iso": None}),
                                     ("iso_remove", {"name": "linux.iso"})):
            with self.assertRaises(Error): self.app.admin_action("admin", operation, arguments)
        self.agent.call.assert_not_called()


if __name__ == "__main__":
    unittest.main()

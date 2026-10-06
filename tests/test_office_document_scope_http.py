"""Document proxy access must retain the actor and live share boundaries."""
import json
import unittest
from unittest.mock import Mock, patch

import test_office_gateway_http as office_fixture


class OfficeDocumentProxyHTTPTests(unittest.TestCase):
    # Reuse the temporary HTTP/file fixture, without inheriting its test methods.
    setUp = office_fixture.OfficeGatewayHTTPTests.setUp
    tearDown = office_fixture.OfficeGatewayHTTPTests.tearDown
    call = office_fixture.OfficeGatewayHTTPTests.call
    request = office_fixture.OfficeGatewayHTTPTests.request
    start = office_fixture.OfficeGatewayHTTPTests.start
    callback = office_fixture.OfficeGatewayHTTPTests.callback

    def assert_original_login_capability_revoked(self, session, record):
        self.assertEqual(self.request("/office/internal/file?session=" + session, actor=None)[0], 403)
        with patch("titan.office_gateway.engine_connection") as connection:
            status, raw = self.callback(session, record)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["error"], 1)
        connection.assert_not_called()
        self.assertFalse(self.writes)
        self.assertEqual(self.document.read_bytes(), self.original)

    def proxy_connection(self):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b"document endpoint"
        response.getheader.side_effect = lambda name, default=None: "text/plain" if name == "Content-Type" else default
        return connection

    def test_known_document_key_does_not_authorize_a_different_actor(self):
        _, record = self.start()
        with patch("titan.office_gateway.engine_connection") as connection:
            for prefix in ("/doc/", "/cache/files/", "/cache/files/conv_", "/cache/files/data/", "/cache/files/data/conv_"):
                status, _ = self.request("/office-engine" + prefix + record["key"] + "/content", actor="reader")
                self.assertEqual(status, 403)
        connection.assert_not_called()

    def test_proxy_rechecks_revoked_share_before_contacting_engine(self):
        _, record = self.start()
        self.share["writers"] = []
        with patch("titan.office_gateway.engine_connection") as connection:
            status, _ = self.request("/office-engine/doc/" + record["key"] + "/c/info")
        self.assertEqual(status, 403)
        connection.assert_not_called()

    def test_expired_office_record_cannot_authorize_the_document_proxy(self):
        session, record = self.start()
        records = self.app.store.config("office-sessions")
        records[session]["expires"] = 0
        self.app.store.set_config("office-sessions", records)
        with patch("titan.office_gateway.engine_connection") as connection:
            status, _ = self.request("/office-engine/cache/files/" + record["key"] + "/content")
        self.assertEqual(status, 403)
        connection.assert_not_called()

    def test_converter_cache_retains_live_document_login_and_share_scope(self):
        _, record = self.start()
        paths = ["/office-engine/cache/files/" + prefix + record["key"] + "_67/output.odt?signature=scoped-test"
                 for prefix in ("conv_", "data/conv_")]
        for path in paths:
            connection = self.proxy_connection()
            with patch("titan.office_gateway.engine_connection", return_value=connection):
                self.assertEqual(self.request(path)[0], 200)
            self.assertEqual(connection.request.call_args.args[:2], ("GET", path.removeprefix("/office-engine")))
        self.share["writers"] = []
        with patch("titan.office_gateway.engine_connection") as connection:
            for path in paths:
                self.assertEqual(self.request(path)[0], 403)
        connection.assert_not_called()

    def test_converter_key_cannot_authorize_unknown_or_malformed_document(self):
        self.start()
        for cache_key in ("conv_" + "0" * 64 + "_67", "conv_titan-save-unrelated_67", "conv_" + "0" * 65 + "_67"):
            with self.subTest(cache_key=cache_key), patch("titan.office_gateway.engine_connection") as connection:
                self.assertEqual(self.request("/office-engine/cache/files/" + cache_key + "/output.odt")[0], 403)
                connection.assert_not_called()

    def test_http_logout_revokes_existing_document_fetch_and_signed_save(self):
        session, record = self.start()
        status, raw = self.request("/api/logout", {})
        self.assertEqual(status, 200, raw)
        self.assert_original_login_capability_revoked(session, record)

    def test_admin_session_revoke_revokes_existing_document_capability(self):
        session, record = self.start()
        status, raw = self.request("/api/security/sessions/revoke", {"id": record["login_digest"][:32]}, actor="admin")
        self.assertEqual(status, 200, raw)
        self.assert_original_login_capability_revoked(session, record)

    def test_expired_browser_session_does_not_retain_document_capability(self):
        session, record = self.start()
        with self.app.store.connection() as database:
            database.execute("UPDATE sessions SET expires=0 WHERE token=?", (record["login_digest"],))
        self.assert_original_login_capability_revoked(session, record)

    def test_logout_then_new_login_can_reopen_unchanged_document(self):
        old_session, old_record = self.start()
        self.assertEqual(self.request("/api/logout", {})[0], 200)
        self.tokens["writer"] = self.app.store.login("writer", "writer-password-long")
        new_session, new_record = self.start()
        self.assertEqual(old_record["key"], new_record["key"])
        self.assertNotEqual(old_record["login_digest"], new_record["login_digest"])
        with patch("titan.office_gateway.engine_connection", return_value=self.proxy_connection()):
            status, raw = self.request("/office-engine/doc/" + new_record["key"] + "/c/info")
        self.assertEqual(status, 200, raw)
        self.assertEqual(self.request("/office/internal/file?session=" + old_session, actor=None)[0], 403)
        self.assertEqual(self.request("/office/internal/file?session=" + new_session, actor=None), (200, self.original))

    def test_parallel_browser_logins_each_use_their_own_document_record(self):
        first_login = self.tokens["writer"]
        first_session, first_record = self.start()
        self.tokens["writer"] = self.app.store.login("writer", "writer-password-long")
        second_login = self.tokens["writer"]
        second_session, second_record = self.start()
        self.assertEqual(first_record["key"], second_record["key"])
        for login, session in ((first_login, first_session), (second_login, second_session)):
            self.tokens["writer"] = login
            with patch("titan.office_gateway.engine_connection", return_value=self.proxy_connection()):
                status, raw = self.request("/office-engine/doc/" + first_record["key"] + "/c/info")
            self.assertEqual(status, 200, raw)
            self.assertEqual(self.request("/office/internal/file?session=" + session, actor=None), (200, self.original))
        self.app.store.logout(first_login[0])
        self.assertEqual(self.request("/office/internal/file?session=" + first_session, actor=None)[0], 403)
        self.assertEqual(self.request("/office/internal/file?session=" + second_session, actor=None), (200, self.original))


if __name__ == "__main__":
    unittest.main()

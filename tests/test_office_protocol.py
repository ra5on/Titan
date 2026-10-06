"""Office conversion, signature and redirect boundaries without a host engine."""
import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import Mock, patch

from titan.core import Error
from titan.office_gateway import b64, original_format_url, proxy_location, save_path, sign, verify


class OfficeProtocolTests(unittest.TestCase):
    runtime = {"engine_origin": "http://172.20.0.8:80", "secret": "test-key-0123456789abcdef-0123456789abcdef"}
    public = "https://nas.example.test:5000"
    source = runtime["engine_origin"] + "/cache/files/session/output.docx?signature=test"

    def converter(self, result, status=200):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = status
        response.read.return_value = result if isinstance(result, bytes) else json.dumps(result).encode()
        return connection

    def test_unchanged_ooxml_format_needs_no_conversion(self):
        with patch("titan.office_gateway.engine_connection") as connection:
            path = original_format_url(self.source, "docx", "docx", "document-key", self.runtime, self.public)
        self.assertEqual(path, "/cache/files/session/output.docx?signature=test")
        connection.assert_not_called()

    def test_odf_conversion_is_signed_and_downloads_only_from_engine_cache(self):
        result = {"endConvert": True, "fileType": "odt", "fileUrl": self.runtime["engine_origin"] + "/cache/files/converted/output.odt"}
        connection = self.converter(result)
        with patch("titan.office_gateway.engine_connection", return_value=connection):
            path = original_format_url(self.source, "docx", "odt", "document-key", self.runtime, self.public)
        args, kwargs = connection.request.call_args
        self.assertEqual(args, ("POST", "/converter"))
        request = json.loads(kwargs["body"])
        token = request.pop("token")
        self.assertEqual(verify(token, self.runtime["secret"]), request)
        self.assertEqual(request["filetype"], "docx")
        self.assertEqual(request["outputtype"], "odt")
        self.assertIs(request["async"], False)
        self.assertEqual(request["url"], self.source)
        self.assertEqual(path, "/cache/files/converted/output.odt")
        connection.close.assert_called_once()

    def test_converter_cannot_fetch_an_external_input_url(self):
        with patch("titan.office_gateway.engine_connection") as connection:
            with self.assertRaises(Error):
                original_format_url("http://169.254.169.254/latest/meta-data/", "docx", "odt", "key", self.runtime, self.public)
        connection.assert_not_called()

    def test_repeated_forcesave_does_not_reuse_a_previous_converter_cache_key(self):
        connection = self.converter({"endConvert": True, "fileType": "odt",
                                     "fileUrl": self.runtime["engine_origin"] + "/cache/files/converted/output.odt"})
        with patch("titan.office_gateway.engine_connection", return_value=connection):
            for _ in range(2):
                original_format_url(self.source, "docx", "odt", "same-document-key", self.runtime, self.public)
        requests = [json.loads(call.kwargs["body"]) for call in connection.request.call_args_list]
        self.assertEqual(requests[0]["url"], requests[1]["url"])
        self.assertNotEqual(requests[0]["key"], requests[1]["key"], "Repeated saves at one engine cache URL must reconvert the latest content.")

    def test_converter_errors_incomplete_or_wrong_formats_do_not_return_a_save_path(self):
        replies = (
            ({"error": -3}, 200),
            ({"endConvert": False}, 200),
            ({"endConvert": True, "fileType": "docx", "fileUrl": self.source}, 200),
            ({"endConvert": True, "fileType": "odt", "fileUrl": "http://elsewhere.test/cache/files/document.odt"}, 200),
            (b"not JSON", 200),
            ({"endConvert": True}, 503),
        )
        for result, status in replies:
            with self.subTest(result=result, status=status):
                connection = self.converter(result, status)
                with patch("titan.office_gateway.engine_connection", return_value=connection):
                    with self.assertRaises(Error):
                        original_format_url(self.source, "docx", "odt", "key", self.runtime, self.public)
                connection.close.assert_called_once()

    def test_cache_save_rejects_traversal_credentials_fragment_and_non_cache_files(self):
        for suffix in ("/cache/files/../private", "/cache/files/%2e%2e/private", "/cache/files/%5cprivate", "/cache/files/document#fragment", "/web-apps/config.json"):
            with self.subTest(suffix=suffix):
                with self.assertRaises(Error):
                    save_path(self.runtime["engine_origin"] + suffix, self.runtime, self.public)
        with self.assertRaises(Error):
            save_path("http://user:password@172.20.0.8:80/cache/files/document", self.runtime, self.public)
        self.assertEqual(save_path(self.public + "/office-engine/cache/files/a.odt?signature=test", self.runtime, self.public), "/cache/files/a.odt?signature=test")

    def test_proxy_redirects_stay_inside_local_document_engine(self):
        engine = self.runtime["engine_origin"]
        self.assertEqual(proxy_location(engine + "/9.3.4/web-apps/index.html?v=2", self.runtime, self.public), "/office-engine/9.3.4/web-apps/index.html?v=2")
        self.assertEqual(proxy_location("/sdkjs/word/sdk.js", self.runtime, self.public), "/office-engine/sdkjs/word/sdk.js")
        self.assertEqual(proxy_location("/office-engine/fonts/font.ttf", self.runtime, self.public), "/office-engine/fonts/font.ttf")
        local = self.public + "/office-engine/web-apps/index.html"
        self.assertEqual(proxy_location(local, self.runtime, self.public), local)
        for url in ("https://outside.example.test/path", "//outside.example.test/path", "javascript:alert(1)"):
            with self.subTest(url=url), self.assertRaises(Error):
                proxy_location(url, self.runtime, self.public)

    def test_jwt_refuses_expired_tampered_or_other_algorithm_even_with_valid_hmac(self):
        secret = self.runtime["secret"]
        with self.assertRaises(Error):
            verify(sign({"exp": time.time() - 1}, secret), secret)
        with self.assertRaises(Error):
            verify(sign({"key": "safe"}, "other-key"), secret)
        header = b64(b'{"alg":"none","typ":"JWT"}')
        body = b64(b'{"key":"safe"}')
        message = header + "." + body
        token = message + "." + b64(hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest())
        with self.assertRaises(Error):
            verify(token, secret)
        self.assertEqual(verify(sign({"key": "safe", "exp": time.time() + 60}, secret), secret)["key"], "safe")


if __name__ == "__main__":
    unittest.main()

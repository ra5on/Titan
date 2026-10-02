"""Check bundled terminal assets and real static-response CSP without sockets."""
import base64
from email import message_from_bytes
import hashlib
from html.parser import HTMLParser
import importlib.util
import io
import json
from pathlib import Path
import re
import unittest

from titan.server import Handler, WEB


ROOT = Path(__file__).resolve().parents[1]
VENDOR = WEB / "vendor/terminal"


class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.script_text = []
        self.in_script = False

    def handle_starttag(self, tag, attributes):
        self.tags.append((tag, dict(attributes)))
        if tag == "script":
            self.in_script = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        if self.in_script and data.strip():
            self.script_text.append(data)


def static_response(relative):
    # Use actual Handler.static/send_headers and HTTP serialization, avoiding
    # BaseHTTPRequestHandler.__init__ because it creates a live connection.
    handler = Handler.__new__(Handler)
    handler.wfile = io.BytesIO()
    handler.request_version = "HTTP/1.1"
    handler.requestline = "GET /" + relative + " HTTP/1.1"
    handler.command = "GET"
    handler.path = "/" + relative
    handler.close_connection = True
    handler.static(WEB, relative)
    headers, separator, body = handler.wfile.getvalue().partition(b"\r\n\r\n")
    if not separator:
        raise AssertionError("Static response is missing its HTTP header boundary")
    status, _, header_lines = headers.partition(b"\r\n")
    return status, message_from_bytes(header_lines), body


class TerminalAssetsTests(unittest.TestCase):
    def test_manifest_pins_complete_local_assets_with_matching_hashes(self):
        manifest = json.loads((VENDOR / "manifest.json").read_text())
        self.assertEqual({entry["name"]: entry["version"] for entry in manifest},
                         {"@xterm/xterm": "6.0.0", "@xterm/addon-fit": "0.11.0"})
        expected = {"@xterm/xterm": {"xterm.js", "xterm.css", "xterm-LICENSE"},
                    "@xterm/addon-fit": {"addon-fit.js", "addon-fit-LICENSE"}}
        files = {"manifest.json"}
        for entry in manifest:
            self.assertEqual(set(entry["sha256"]), expected[entry["name"]])
            self.assertTrue(entry["url"].startswith("https://registry.npmjs.org/"))
            digest = base64.b64decode(entry["integrity"].removeprefix("sha512-"), validate=True)
            self.assertEqual(len(digest), 64)
            for name, recorded in entry["sha256"].items():
                with self.subTest(asset=name):
                    path = VENDOR / name
                    self.assertTrue(path.is_file())
                    self.assertFalse(path.is_symlink())
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), recorded)
                    files.add(name)
        self.assertEqual({path.name for path in VENDOR.iterdir()}, files)

    def test_vendoring_recipe_matches_manifest_without_downloading(self):
        specification = importlib.util.spec_from_file_location("terminal_vendor_recipe", ROOT / "scripts/vendor_terminal.py")
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        manifest = {entry["name"]: entry for entry in json.loads((VENDOR / "manifest.json").read_text())}
        for package in module.PACKAGES:
            entry = manifest[package["name"]]
            for key in ("version", "url", "integrity"):
                self.assertEqual(entry[key], package[key])
            self.assertEqual(set(package["files"].values()), set(entry["sha256"]))

    def test_both_mit_notices_and_installed_copyright_paths_exist(self):
        copyright_file = (ROOT / "NOTICE").read_text()
        self.assertIn("titan/web/vendor/terminal", copyright_file)
        self.assertIn("MIT", copyright_file)
        for name in ("xterm-LICENSE", "addon-fit-LICENSE"):
            with self.subTest(notice=name):
                notice = (VENDOR / name).read_text()
                self.assertIn("Copyright", notice)
                self.assertIn("Permission is hereby granted, free of charge", notice)
                self.assertIn('THE SOFTWARE IS PROVIDED "AS IS"', notice)
                self.assertIn("/usr/lib/titan/titan/web/vendor/terminal/" + name, copyright_file)

    def test_all_four_generated_xterm_styles_receive_document_nonce(self):
        source = (VENDOR / "xterm.js").read_text()
        pattern = (r'\(\(n\)=>\{const e=n\.createElement\("style"\);'
                   r'e\.nonce=n\.querySelector\("meta\[name=titan-style-nonce\]"\)\?\.content\|\|"";'
                   r'return e;\}\)\((?:s\.mainDocument|this\._document|document)\)')
        self.assertEqual(len(re.findall(pattern, source)), 4)
        self.assertNotRegex(re.sub(pattern, "NONCED_STYLE", source), r'createElement\([\'"]style[\'"]\)')
        self.assertNotIn("unsafe-inline", source)
        self.assertNotIn("unsafe-eval", source)

    def test_terminal_scripts_and_styles_load_only_from_local_files(self):
        document = Document()
        document.feed((WEB / "index.html").read_text())
        scripts = [attributes for tag, attributes in document.tags if tag == "script"]
        sources = [attributes.get("src") for attributes in scripts]
        self.assertIn("/vendor/terminal/xterm.js", sources)
        self.assertIn("/vendor/terminal/addon-fit.js", sources)
        self.assertIn("/terminal_controls.js", sources)
        self.assertLess(sources.index("/vendor/terminal/xterm.js"), sources.index("/terminal_controls.js"))
        self.assertLess(sources.index("/vendor/terminal/addon-fit.js"), sources.index("/terminal_controls.js"))
        self.assertEqual(document.script_text, [])
        for attributes in scripts:
            source = attributes["src"]
            self.assertTrue(source.startswith("/") and not source.startswith("//"))
            self.assertTrue((WEB / source.lstrip("/")).is_file())
            self.assertIn("defer", attributes)
        self.assertTrue(any(tag == "link" and attributes.get("href") == "/vendor/terminal/xterm.css"
                            for tag, attributes in document.tags))

    def test_real_index_response_generates_fresh_matching_nonce_and_strict_script_policy(self):
        nonces = []
        for _ in range(2):
            status, headers, body = static_response("index.html")
            self.assertTrue(status.endswith(b"200 OK"))
            self.assertEqual(int(headers["Content-Length"]), len(body))
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertNotIn(b"__TITAN_STYLE_NONCE__", body)
            document = Document()
            document.feed(body.decode())
            selected = [attributes["content"] for tag, attributes in document.tags
                        if tag == "meta" and attributes.get("name") == "titan-style-nonce"]
            self.assertEqual(len(selected), 1)
            nonce = selected[0]
            self.assertRegex(nonce, r"^[A-Za-z0-9_-]{32}$")
            nonces.append(nonce)
            directives = {words[0]: words[1:] for part in headers["Content-Security-Policy"].split(";")
                          if (words := part.split())}
            self.assertEqual(directives["style-src"], ["'self'", "'nonce-" + nonce + "'"])
            self.assertEqual(directives["script-src"], ["'self'"])
            self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"])
            self.assertNotIn("unsafe-eval", headers["Content-Security-Policy"])
        self.assertNotEqual(nonces[0], nonces[1])

    def test_real_vendor_static_response_preserves_manifest_bytes_and_strict_csp(self):
        for name in ("xterm.js", "addon-fit.js", "xterm.css"):
            with self.subTest(asset=name):
                status, headers, body = static_response("vendor/terminal/" + name)
                self.assertTrue(status.endswith(b"200 OK"))
                self.assertEqual(body, (VENDOR / name).read_bytes())
                self.assertEqual(int(headers["Content-Length"]), len(body))
                self.assertNotIn("nonce-", headers["Content-Security-Policy"])
                self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
                self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"])


if __name__ == "__main__":
    unittest.main()

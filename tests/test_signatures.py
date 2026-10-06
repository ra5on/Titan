import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from titan.core import Error
from titan.updates import verify_manifest


class SignatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        directory = Path(self.temp.name)
        self.key, self.public = directory / "private.pem", directory / "public.pem"
        self.manifest, self.signature = directory / "manifest.json", directory / "manifest.json.sig"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(self.key)], check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-in", str(self.key), "-pubout", "-out", str(self.public)], check=True, capture_output=True)
        self.manifest.write_text(json.dumps({"version":"0.2.0","sha256":"example"}))
        subprocess.run(["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(self.key), "-in", str(self.manifest), "-out", str(self.signature)], check=True, capture_output=True)
    def tearDown(self): self.temp.cleanup()
    def test_authentic_manifest_is_accepted(self):
        self.assertEqual(verify_manifest(self.manifest,self.signature,self.public)["version"], "0.2.0")
    def test_tampered_manifest_is_rejected(self):
        self.manifest.write_text(json.dumps({"version":"9.0.0","sha256":"changed"}))
        with self.assertRaises(Error): verify_manifest(self.manifest,self.signature,self.public)
    def test_untrusted_key_is_rejected(self):
        other = Path(self.temp.name) / "other.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(other)], check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-in", str(other), "-pubout", "-out", str(self.public)], check=True, capture_output=True)
        with self.assertRaises(Error): verify_manifest(self.manifest,self.signature,self.public)
    def sign(self, text):
        self.manifest.write_text(text)
        subprocess.run(["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(self.key),
                        "-in", str(self.manifest), "-out", str(self.signature)], check=True, capture_output=True)

    def test_duplicate_json_keys_are_rejected_even_with_an_authentic_signature(self):
        self.sign('{"version":"0.3.0","version":"9.0.0"}')
        with self.assertRaises(Error):
            verify_manifest(self.manifest, self.signature, self.public)

import copy
import unittest

from titan import catalog
from titan.core import Error


class CatalogOptionsTests(unittest.TestCase):
    def test_qbittorrent_ports_and_environment_match_changed_ui_and_peer_ports(self):
        service = catalog.compose("qbittorrent", "/private/app", 1000, 1000, 12500, "/nas/downloads",
                                  {"peer_port": 12600})["services"]["qbittorrent"]
        self.assertEqual(service["ports"], ["12500:12500", "12600:12600/tcp", "12600:12600/udp"])
        self.assertEqual(service["environment"]["WEBUI_PORT"], "12500")
        self.assertEqual(service["environment"]["TORRENTING_PORT"], "12600")
        self.assertEqual(service["volumes"][1]["target"], "/downloads")

    def test_authentication_is_required_for_apps_that_allow_anonymous_upstream_access(self):
        for app in ("transmission", "code-server", "librespeed"):
            for value in (None, {}, {"password": "short"}, {"password": "abcdefghijkl\n"}, {"password": True}):
                with self.subTest(app=app, value=value), self.assertRaises(Error):
                    catalog.validate_options(app, value)

    def test_options_are_curated_and_do_not_accept_host_or_environment_overrides(self):
        for value in ({"PUID": "0"}, {"privileged": True}, {"password": "long-password-123", "SUDO_PASSWORD": "root"}, [], "text"):
            with self.subTest(value=value), self.assertRaises(Error):
                catalog.validate_options("code-server", value)
        for port in (True, 500, 65536, "bad"):
            with self.subTest(port=port), self.assertRaises(Error):
                catalog.validate_options("qbittorrent", {"peer_port": port})
        for username in ("-unsafe\n", "a:b", "a b", "", 1):
            with self.subTest(username=username), self.assertRaises(Error):
                catalog.validate_options("transmission", {"username": username, "password": "long-password-123"})

    def test_password_dollar_signs_are_literal_and_no_sudo_is_enabled(self):
        password = "example$HOME${TOKEN}123"
        service = catalog.compose("code-server", "/private/app", 1000, 1000, 8443, "/nas/files",
                                  {"password": password})["services"]["code-server"]
        self.assertEqual(service["environment"]["PASSWORD"], "example$$HOME$${TOKEN}123")
        self.assertEqual(service["environment"]["DEFAULT_WORKSPACE"], "/data")
        self.assertNotIn("SUDO_PASSWORD", service["environment"])
        self.assertNotIn("SUDO_PASSWORD_HASH", service["environment"])

    def test_same_web_and_peer_port_is_rejected_for_each_protocol(self):
        for app in ("qbittorrent", "transmission"):
            options = {"peer_port": 12000, "password": "long-password-123"} if app == "transmission" else {"peer_port": 12000}
            with self.subTest(app=app), self.assertRaises(Error) as caught:
                catalog.published_ports(app, 12000, options)
            self.assertEqual(caught.exception.status, 409)
        with self.assertRaises(Error):
            catalog.published_ports("syncthing", 22000)

    def test_catalog_exposes_form_schema_without_private_environment_mapping(self):
        saved = copy.deepcopy(catalog._cache)
        try:
            catalog._cache.update(time=10**12, images={}, error=None)
            apps = {app["id"]: app for app in catalog.catalog(include_legacy=True)["apps"]}
            self.assertGreaterEqual(len(apps), 21)
            for app in apps.values():
                self.assertNotIn("environment", app)
                self.assertTrue(all("env" not in field for field in app["install_schema"]))
            self.assertTrue(next(field for field in apps["code-server"]["install_schema"] if field["key"] == "password")["required"])
            self.assertNotIn("default", apps["code-server"]["install_schema"][0])
        finally:
            catalog._cache.clear()
            catalog._cache.update(saved)

    def test_pairdrop_has_no_persistent_storage_claim_and_download_default_ports_do_not_collide(self):
        service = catalog.compose("pairdrop", "/private/app", 1000, 1000, 3000, "/nas/files")["services"]["pairdrop"]
        self.assertEqual(service["volumes"], [])
        self.assertEqual(service["environment"]["WS_FALLBACK"], "true")
        defaults = [app.get("default_port", app["port"]) for app in catalog.APPS.values() if not app.get("titan_package")]
        self.assertEqual(len(set(defaults)), len(defaults))
        self.assertFalse({5000, 5001} & set(defaults))


if __name__ == "__main__":
    unittest.main()

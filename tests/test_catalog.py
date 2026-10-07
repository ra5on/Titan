import base64
import json
import re
import time
import unittest
from unittest.mock import patch

from titan.catalog import APPS, _cache, _image_metadata, catalog, compose, published_ports
from titan.core import Error


class CatalogTests(unittest.TestCase):
    def test_new_recipes_have_documented_ports_and_persistent_mounts(self):
        expected = {"freshrss": (80, None), "calibre-web": (8083, "/books"),
                    "prowlarr": (9696, None), "radarr": (7878, "/movies")}
        for name, (port, mount) in expected.items():
            with self.subTest(app=name):
                service = compose(name, "/srv/apps/" + name, 1000, 1000, 12345, "/srv/data")["services"][name]
                self.assertEqual(service["ports"], [f"12345:{port}"])
                self.assertIn({"type": "bind", "source": f"/srv/apps/{name}/config", "target": "/config",
                               "bind": {"create_host_path": False, "selinux": "Z"}}, service["volumes"])
                if mount:
                    self.assertIn({"type": "bind", "source": "/srv/data", "target": mount,
                                   "bind": {"create_host_path": False}}, service["volumes"])
                else:
                    self.assertEqual(len(service["volumes"]), 1)
                self.assertEqual(service["image"], "lscr.io/linuxserver/" + name + ":latest")
                self.assertEqual(APPS[name]["verified"], "2026-09-30")

    def test_curated_recipes_do_not_grant_host_privileges(self):
        for name in APPS:
            options = {field["key"]: "ExamplePassword123" for field in APPS[name].get("install_schema", [])
                       if field["type"] == "password"}
            if name == 'titan-cloudflared':
                options['tunnel_token'] = base64.b64encode(json.dumps({'a': 'a' * 32,
                    't': '2c9069cd-5cf1-470f-9ddd-df156d3f2c57',
                    's': base64.b64encode(b'disposable-test-secret-with-entropy').decode()}).encode()).decode()
            if name == 'titan-tailscale':
                options['auth_key'] = 'tskey-auth-disposable-invalid-test-key-123456789'
            port = 0 if APPS[name].get('web_available') is False else 12345
            services = compose(name, "/srv/app", 1000, 1000, port, "/srv/data", options)["services"]
            for service in services.values():
                self.assertNotIn("privileged", service)
                self.assertNotIn("network_mode", service)
                self.assertNotIn("cap_add", service)
                self.assertNotIn("devices", service)
                self.assertFalse(any("docker.sock" in volume["source"] for volume in service["volumes"]))
                self.assertTrue(all(volume["bind"]["create_host_path"] is False for volume in service["volumes"]))

    def test_arbitrary_remote_image_is_not_installable(self):
        with self.assertRaises(Error):
            compose("untrusted-image", "/srv/app", 1000, 1000, 12345, "/srv/data")

    def test_every_app_explains_its_initial_login(self):
        self.assertGreaterEqual(len(APPS), 73)
        for name, recipe in APPS.items():
            with self.subTest(app=name):
                login = recipe["first_login"]
                self.assertIn(login["mode"], {"setup", "default", "install", "generated", "none", "documentation"})
                self.assertGreater(len(login["instructions"]), 30)
                self.assertTrue(login["documentation"].startswith("https://"))
                if not recipe.get("store_url"): self.assertRegex(login["verified"], r"^\d{4}-\d{2}-\d{2}$")
                self.assertLessEqual(set(login), {"mode", "instructions", "documentation", "verified", "username", "password"})
                if login["mode"] != "default":
                    self.assertNotIn("password", login)
                if login["mode"] in {"setup", "install", "none"}:
                    self.assertNotIn("username", login)

    def test_only_documented_initial_defaults_are_published(self):
        expected = {"calibre-web": ("admin", "admin123"), "grocy": ("admin", "admin"),
                    "deluge": ("admin", "deluge"), "raneto": ("admin", "password"),
                    "pyload-ng": ("pyload", "pyload")}
        defaults = {name: (recipe["first_login"]["username"], recipe["first_login"]["password"])
                    for name, recipe in APPS.items() if recipe["first_login"]["mode"] == "default"}
        self.assertEqual(defaults, expected)
        for name in expected:
            self.assertIn("sofort", APPS[name]["first_login"]["instructions"])

    def test_generated_and_user_chosen_passwords_are_not_catalog_credentials(self):
        login = APPS["qbittorrent"]["first_login"]
        self.assertEqual(login["mode"], "generated")
        self.assertEqual(login["username"], "admin")
        self.assertIn("Protokoll", login["instructions"])
        self.assertNotIn("password", login)
        for name in {"transmission", "nzbget", "code-server", "duplicati", "librespeed"}:
            self.assertEqual(APPS[name]["first_login"]["mode"], "install")
            self.assertNotIn("password", APPS[name]["first_login"])
            self.assertNotIn("username", APPS[name]["first_login"])

    def test_nzbget_requires_and_passes_private_install_credentials(self):
        with self.assertRaises(Error):
            compose("nzbget", "/srv/app", 1000, 1000, 6789, "/srv/data")
        secret = "My$PrivatePassword123"
        service = compose("nzbget", "/srv/app", 1000, 1000, 6789, "/srv/data",
                          {"username": "chosen.user", "password": secret})["services"]["nzbget"]
        self.assertEqual(service["environment"]["NZBGET_USER"], "chosen.user")
        self.assertEqual(service["environment"]["NZBGET_PASS"], "My$$PrivatePassword123")
        with patch.dict(_cache, {"time": time.time(), "images": {}, "error": None}):
            public = catalog()
        self.assertNotIn(secret, json.dumps(public))
        for recipe in public["apps"]:
            self.assertNotIn("environment", recipe)
            self.assertTrue(all("env" not in field for field in recipe["install_schema"]))

    def test_deluge_publishes_selected_tcp_udp_peer_port_to_fixed_internal_port(self):
        ports = published_ports("deluge", 8112, {"peer_port": 16882})
        self.assertEqual(ports, [{"host": 8112, "target": 8112, "protocol": "tcp"},
                                 {"host": 16882, "target": 6881, "protocol": "tcp"},
                                 {"host": 16882, "target": 6881, "protocol": "udp"}])
        with self.assertRaises(Error):
            published_ports("deluge", 8112, {"peer_port": 8112})

    def test_ubooquity_has_separate_configurable_administration_port(self):
        ports = published_ports("ubooquity", 2202, {"admin_port": 12203})
        self.assertEqual(ports, [{"host": 2202, "target": 2202, "protocol": "tcp"},
                                 {"host": 12203, "target": 2203, "protocol": "tcp"}])
        self.assertIn("/ubooquity/admin", APPS["ubooquity"]["first_login"]["instructions"])
        with self.assertRaises(Error):
            published_ports("ubooquity", 2202, {"admin_port": 2202})

    def test_expanded_apps_keep_files_in_their_documented_persistent_mounts(self):
        expected = {"emby": "/data", "lazylibrarian": "/data", "mylar3": "/data", "deluge": "/downloads",
                    "nzbget": "/downloads", "nzbhydra2": "/downloads", "pyload-ng": "/downloads",
                    "resilio-sync": "/sync", "smokeping": "/data", "ubooquity": "/files"}
        for name, target in expected.items():
            with self.subTest(app=name):
                options = {field["key"]: "PrivatePassword123" for field in APPS[name].get("install_schema", [])
                           if field["type"] == "password"}
                service = compose(name, "/srv/app", 1000, 1000, 12345, "/srv/data", options)["services"][name]
                self.assertIn({"type": "bind", "source": "/srv/data", "target": target,
                               "bind": {"create_host_path": False}}, service["volumes"])

    def test_default_web_ports_are_distinct_and_leave_titan_port_available(self):
        ports = [recipe.get("default_port", recipe["port"]) for recipe in APPS.values() if not recipe.get("titan_package")]
        self.assertEqual(len(set(ports)), len(ports))
        self.assertFalse({5000, 5001} & set(ports))
        self.assertTrue(all(1024 <= port <= 65535 for port in ports))

    def test_all_default_publications_leave_system_and_other_app_ports_available(self):
        owners = {}
        for name, recipe in APPS.items():
            if recipe.get("titan_package"): continue
            options = {field["key"]: "ExamplePassword123" for field in recipe.get("install_schema", [])
                       if field["type"] == "password"}
            for publication in published_ports(name, recipe.get("default_port", recipe["port"]), options):
                with self.subTest(app=name, publication=publication):
                    host_port = publication["host"]
                    self.assertNotIn(host_port, {5000, 5001})
                    # One app may publish its peer port as both TCP and UDP;
                    # another app must not claim either publication's host port.
                    self.assertIn(owners.get(host_port), {None, name})
                    owners[host_port] = name

    def test_local_ids_are_valid_compose_project_names(self):
        self.assertTrue(all(re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name) for name in APPS))
        service = compose("changedetection", "/srv/app", 1000, 1000, 8102, "/srv/data")["services"]["changedetection"]
        self.assertEqual(service["image"], "lscr.io/linuxserver/changedetection.io:latest")
        self.assertEqual(service["container_name"], "titan-changedetection")

    def test_upstream_name_mapping_supplies_metadata_without_overriding_login(self):
        remote = _image_metadata([{"name": "changedetection.io", "version": "0.55.8", "deprecated": False,
                                   "architectures": [{"arch": "x86-64"}],
                                   "first_login": {"mode": "default", "password": "UNTRUSTED_REMOTE"}},
                                  {"name": "untrusted-image", "version": "1"}])
        self.assertEqual(set(remote), {"changedetection"})
        with patch.dict(_cache, {"time": time.time(), "images": remote, "error": None}):
            public = next(recipe for recipe in catalog(include_legacy=True)["apps"] if recipe["id"] == "changedetection")
        self.assertEqual(public["version"], "latest")
        self.assertEqual(public["first_login"]["mode"], "setup")
        self.assertNotIn("password", public["first_login"])
        self.assertEqual(public["documentation"], "https://docs.linuxserver.io/images/docker-changedetection.io/")
        self.assertNotIn("UNTRUSTED_REMOTE", json.dumps(public))


if __name__ == "__main__":
    unittest.main()

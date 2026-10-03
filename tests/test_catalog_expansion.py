import importlib
import io
import json
import unittest
from unittest.mock import patch


catalog_module = importlib.import_module("titan.catalog")


class CatalogExpansionTests(unittest.TestCase):
    def setUp(self):
        self.cache = {"time": 0, "images": {}, "error": None}
        self.cache_patch = patch.object(catalog_module, "_cache", self.cache)
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    def refresh(self, images):
        body = json.dumps({"data": {"repositories": {"linuxserver": images}}}).encode()
        with patch.object(catalog_module.urllib.request, "urlopen", return_value=io.BytesIO(body)) as network:
            result=catalog_module.catalog(refresh=True)
            network.assert_not_called()
            self.assertEqual(result["source"],"Titan AppStore")
            return result

    def test_external_metadata_cannot_change_images_ports_mounts_or_add_apps(self):
        result = self.refresh([
            {"name": "kavita", "version": "verified-version", "architectures": [{"arch": "amd64"}],
             "image": "attacker/image", "port": 5000, "mount": "/", "privileged": True},
            {"name": "untrusted-app", "image": "attacker/image", "version": "latest"},
        ])
        app = next(item for item in result["apps"] if item["id"] == "kavita")
        self.assertEqual(app["version"], "latest")
        self.assertEqual(app["architectures"], [])
        self.assertEqual(app["image"], "lscr.io/linuxserver/kavita:latest")
        self.assertEqual(app["mount"], "/data")
        self.assertEqual(app["default_port"], 8085)
        self.assertNotIn("privileged", app)
        self.assertFalse(any(item["id"] == "untrusted-app" for item in result["apps"]))
        service = catalog_module.compose("kavita", "/var/lib/titan-agent/apps/kavita", 900, 901,
                                         app["default_port"], "/var/srv/titan/books")["services"]["kavita"]
        self.assertEqual(service["ports"], ["8085:5000"])
        self.assertEqual(service["environment"]["PUID"], "900")
        self.assertEqual(service["environment"]["PGID"], "901")
        self.assertFalse(any("docker.sock" in item["source"] for item in service["volumes"]))

    def test_malformed_optional_metadata_does_not_break_the_local_catalog(self):
        result = self.refresh([
            None, 5, {"name": []}, {"name": {}},
            {"name": "sonarr", "version": {}, "deprecated": "false",
             "architectures": [None, {}, {"arch": []}, {"arch": "amd64"}]},
            {"name": "kavita", "version": "x" * 129, "architectures": {}},
        ])
        self.assertIsNone(result["error"])
        sonarr = next(item for item in result["apps"] if item["id"] == "sonarr")
        self.assertEqual(sonarr["version"], "latest")
        self.assertEqual(sonarr["architectures"], [])
        self.assertFalse(sonarr["deprecated"])
        kavita = next(item for item in result["apps"] if item["id"] == "kavita")
        self.assertEqual(kavita["version"], "latest")
        self.assertEqual(kavita["architectures"], [])

    def test_network_failure_preserves_last_good_metadata_and_local_recipes(self):
        self.refresh([{"name": "dokuwiki", "version": "known-good", "deprecated": False}])
        with patch.object(catalog_module.urllib.request, "urlopen", side_effect=OSError("unreachable")):
            result = catalog_module.catalog(refresh=True)
        self.assertIsNone(result["error"])
        self.assertEqual({item["id"] for item in result["apps"]}, set(catalog_module.APPS))
        self.assertEqual(next(item for item in result["apps"] if item["id"] == "dokuwiki")["version"],
                         "latest")

    def test_invalid_response_structure_uses_fallback_without_losing_templates(self):
        result = self.refresh({"unexpected": "object"})
        self.assertIsNone(result["error"])
        self.assertTrue({"sonarr", "lidarr", "bazarr", "dokuwiki", "kavita"}.issubset(
            item["id"] for item in result["apps"]))

    def test_new_default_ports_leave_titan_control_ports_available(self):
        for name in ("sonarr", "lidarr", "bazarr", "dokuwiki", "kavita"):
            with self.subTest(app=name):
                recipe = catalog_module.APPS[name]
                host_port = recipe.get("default_port", recipe["port"])
                self.assertGreaterEqual(host_port, 1024)
                self.assertNotIn(host_port, (5000, 5001))
                service = catalog_module.compose(name, "/var/lib/titan-agent/apps/" + name,
                                                 900, 901, host_port, "/var/srv/titan/media")["services"][name]
                self.assertEqual(len(service["ports"]), 1)
                self.assertNotIn("depends_on", service)
                self.assertNotIn("cap_add", service)
                self.assertNotIn("network_mode", service)


if __name__ == "__main__":
    unittest.main()

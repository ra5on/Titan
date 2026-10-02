import json
from pathlib import Path
import tempfile
import unittest

from titan.catalog import APPS
from titan.core import Error
from titan.demo import Demo


class CatalogDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.demo = Demo(Path(self.temp.name))

    def tearDown(self):
        self.demo._temporary.cleanup()
        self.temp.cleanup()

    def test_every_curated_recipe_installs_with_schema_options_and_exposes_correct_ports(self):
        for app, recipe in APPS.items():
            if any(item["id"] == app for item in self.demo.apps):
                continue
            options = {field["key"]: "ExamplePassword123" for field in recipe.get("install_schema", []) if field["type"] == "password"}
            with self.subTest(app=app):
                self.demo.call("app_install", app=app, port=recipe.get("default_port", recipe["port"]), options=options)
                detail = self.demo.call("app_details", app=app)
                self.assertEqual(detail["app"]["state"], "running")
                self.assertNotIn("ExamplePassword123", json.dumps(detail))
        qbt = self.demo.call("app_details", app="qbittorrent")["container"]["ports"]
        self.assertEqual([(item["port"], item["target"], item["protocol"]) for item in qbt], [(8090, 8090, "tcp"), (6881, 6881, "tcp"), (6881, 6881, "udp")])
        self.assertEqual(len(self.demo.call("app_details", app="syncthing")["container"]["ports"]), 4)
        self.assertNotIn("ExamplePassword123", json.dumps(self.demo.call("apps")))

    def test_invalid_secret_and_port_conflicts_do_not_add_demo_apps(self):
        for options in ({}, {"password": "short"}, {"password": "long-password-123", "SUDO_PASSWORD": "root"}):
            with self.assertRaises(Error):
                self.demo.call("app_install", app="code-server", port=8443, options=options)
        for port in (5000, 5001, 22000, 21027):
            with self.assertRaises(Error) as result:
                self.demo.call("app_install", app="heimdall", port=port)
            self.assertEqual(result.exception.status, 409)
        self.assertEqual(len(self.demo.apps), 2)

    def test_selected_writable_share_is_reflected_without_revealing_password(self):
        self.demo.call("app_install", app="code-server", port=8443, share="dokumente", options={"password": "long-password-123"})
        self.assertEqual(self.demo.call("app_details", app="code-server")["data_path"], self.demo.shares[0]["path"])
        self.demo.shares[0]["writers"] = ["patrick"]
        with self.assertRaises(Error):
            self.demo.call("app_install", app="wikijs", port=3001, share="dokumente")

    def test_stopped_app_update_and_backup_keep_stopped_state_and_are_labeled_simulation(self):
        self.demo.call("app_action", app="jellyfin", action="stop")
        for action in ("backup", "update"):
            result = self.demo.call("app_action", app="jellyfin", action=action)
            self.assertTrue(result["demo"])
            self.assertTrue(result["kept_stopped"])
            self.assertIn("[Demo]", result["output"])
        with self.assertRaises(Error):
            self.demo.call("app_action", app="jellyfin", action="exec")
        with self.assertRaises(Error) as result:
            self.demo.call("app_action", app="missing", action="restart")
        self.assertEqual(result.exception.status, 404)

    def test_stopped_docker_blocks_installation_and_updates_availability(self):
        self.demo.call("service_action", service="docker.service", command="stop")
        self.assertFalse(self.demo.call("apps")["available"])
        with self.assertRaises(Error):
            self.demo.call("app_install", app="heimdall", port=8080)

    def test_service_reload_and_reset_failed_do_not_toggle_autostart(self):
        record = self.demo.services["smb.service"]
        record["enabled"] = False
        detail = self.demo.call("service_details", service="smb.service", tail=0)
        self.assertIn("reload", detail["service"]["allowed_actions"])
        self.demo.call("service_action", service="smb.service", command="reload")
        self.assertFalse(record["enabled"])
        self.assertTrue(record["active"])
        record.update(active=False, failed=True)
        self.assertEqual(self.demo.call("services")["counts"]["failed"], 1)
        self.demo.call("service_action", service="smb.service", command="reset-failed")
        self.assertFalse(record["enabled"])
        self.assertFalse(record["active"])
        self.assertEqual(self.demo.call("services")["counts"]["failed"], 0)
        with self.assertRaises(Error):
            self.demo.call("service_action", service="titan-web.service", command="reset-failed")


if __name__ == "__main__":
    unittest.main()

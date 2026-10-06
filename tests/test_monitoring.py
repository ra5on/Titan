import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from titan.core import atomic_json, Error
from titan.monitoring import Monitor


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.host = SimpleNamespace(directory=root, share_root=root,
                                    disks=lambda: [{"name": "/dev/sda", "type": "disk"}])
        self.host.load = lambda key, default: json.loads((root / (key + ".json")).read_text()) if (root / (key + ".json")).exists() else default
        self.host.save = lambda key, value: atomic_json(root / (key + ".json"), value)
        self.host.volume_manager = Mock()
        self.host.volume_manager.inventory.return_value = {"volumes": []}
        self.run = Mock(return_value="LoadState=loaded\nActiveState=active\nSubState=running")
        self.monitor = Monitor(self.host, self.run)
        self.which = patch("titan.monitoring.shutil.which", side_effect=lambda name: "/usr/bin/" + name if name != "zpool" else None)
        self.which.start()

    def tearDown(self):
        self.which.stop()
        self.temporary.cleanup()

    def test_installed_and_actual_active_service_state_are_separate(self):
        self.run.return_value = "LoadState=loaded\nActiveState=failed\nSubState=failed"
        with patch.object(self.monitor, "_smart", return_value={"name": "/dev/sda", "health": "passed", "temperature": 30}):
            state = self.monitor.check()
        self.assertTrue(state["services"]["docker"]["installed"])
        self.assertFalse(state["services"]["docker"]["active"])
        self.assertTrue(any(item["key"] == "service:docker" and item["active"] for item in state["alerts"]))
        self.assertTrue(any("titan-proxy.service" in call.args[0] for call in self.run.call_args_list))

    def test_smart_bitmask_failure_output_is_parsed_and_temperature_alerted(self):
        smart = {"smart_status": {"passed": False}, "temperature": {"current": 60}}
        with patch("titan.monitoring.subprocess.run", return_value=SimpleNamespace(stdout=json.dumps(smart), returncode=8)):
            state = self.monitor.check()
        alerts = {item["key"]: item for item in state["alerts"]}
        self.assertTrue(alerts["smart:/dev/sda"]["active"])
        self.assertEqual(alerts["temperature:/dev/sda"]["severity"], "warning")

    def test_hardware_temperature_warns_against_reported_limit_and_recovers(self):
        self.host.telemetry = Mock()
        sensor = {"id": "hwmon0:temp1", "label": "coretemp · Package", "kind": "cpu", "current": 92, "critical": 100}
        self.host.telemetry.sample.return_value = {"temperatures": [sensor], "telemetry_sampled_at": 123}
        with patch.object(self.monitor, "_smart", return_value={"name": "/dev/sda", "health": "passed", "temperature": 30}):
            state = self.monitor.check(force=True)
            alert = next(item for item in state["alerts"] if item["key"] == "temperature:sensor:hwmon0:temp1")
            self.assertEqual(alert["severity"], "warning")
            self.assertEqual(state["telemetry_sampled_at"], 123)
            sensor["current"] = 101
            critical = self.monitor.check(force=True)
            self.assertEqual(next(item for item in critical["alerts"] if item["id"] == alert["id"])["severity"], "error")
            sensor["current"] = 60
            recovered = self.monitor.check(force=True)
        self.assertFalse(next(item for item in recovered["alerts"] if item["id"] == alert["id"])["active"])

    def test_sensor_without_critical_limit_does_not_get_an_invented_threshold(self):
        self.host.telemetry = Mock()
        self.host.telemetry.sample.return_value = {"temperatures": [
            {"id": "hwmon0:temp1", "label": "CPU", "kind": "cpu", "current": 92, "critical": None}]}
        with patch.object(self.monitor, "_smart", return_value={"name": "/dev/sda", "health": "passed", "temperature": 30}):
            state = self.monitor.check(force=True)
        self.assertFalse(any(item["key"].startswith("temperature:sensor:") for item in state["alerts"]))

    def test_space_pool_and_backup_failure_alerts(self):
        self.host.save("backup-state", {"last": {"ok": False, "error": "Ziel fehlt"}})
        def runner(args):
            return "tank\tDEGRADED\t100\t90" if args[0] == "zpool" else "LoadState=loaded\nActiveState=active"
        with patch("titan.monitoring.shutil.which", return_value="/usr/bin/tool"), patch("titan.monitoring.shutil.disk_usage", return_value=SimpleNamespace(total=100, used=98, free=2)), patch.object(self.monitor, "_smart", return_value={"name": "/dev/sda", "health": "passed", "temperature": 30}):
            self.monitor.run = runner
            state = self.monitor.check()
        keys = {item["key"] for item in state["alerts"] if item["active"]}
        self.assertTrue({"space:shares", "pool:tank", "backup:last"}.issubset(keys))

    def test_acknowledgement_survives_checks_and_reappearance_resets(self):
        self.monitor.report("custom:test", "Test", "Detail", "warning")
        alert = self.monitor.get()["alerts"][0]
        self.monitor.acknowledge(alert["id"])
        other = Monitor(self.host, self.run)
        self.assertTrue(other.get()["alerts"][0]["acknowledged"])
        self.monitor.report("custom:test", "Test", "Still active", "warning")
        self.assertTrue(self.monitor.get()["alerts"][0]["acknowledged"])
        self.monitor.clear("custom:test")
        self.monitor.report("custom:test", "Test", "Reappeared")
        self.assertFalse(self.monitor.get()["alerts"][0]["acknowledged"])
        with self.assertRaises(Error):
            self.monitor.acknowledge("unknown")

    def test_cached_checks_do_not_repeat_hardware_commands(self):
        with patch.object(self.monitor, "_smart", return_value={"name": "/dev/sda", "health": "passed", "temperature": 30}) as smart:
            self.monitor.check()
            count = self.run.call_count
            self.monitor.check()
            self.assertEqual(self.run.call_count, count)
            self.assertEqual(smart.call_count, 1)

    def test_volume_space_uses_verified_capacity_and_missing_volume_warns(self):
        self.host.volume_manager.inventory.return_value = {"volumes": [
            {"name": "data", "mounted": True, "mountpoint": "/srv/titan/volumes/data",
             "total": 100, "used": 98, "free": 2},
            {"name": "offline", "mounted": False, "error": "Laufwerk fehlt"}]}
        with patch.object(self.monitor, "_smart", return_value={"name": "/dev/sda", "health": "passed", "temperature": 30}):
            state = self.monitor.check()
        alerts = {item["key"]: item for item in state["alerts"] if item["active"]}
        self.assertEqual(alerts["space:volume:data"]["severity"], "error")
        self.assertIn("volume:offline", alerts)
        self.assertFalse(any(item["name"] == "volume:offline" for item in state["storage"]))
        self.assertEqual(next(item for item in state["storage"] if item["name"] == "volume:data")["free"], 2)

    def test_mount_recovery_clears_missing_volume_alert(self):
        self.host.volume_manager.inventory.return_value = {"volumes": [{"name": "data", "mounted": False}]}
        with patch.object(self.monitor, "_smart", return_value={"name": "/dev/sda", "health": "passed", "temperature": 30}):
            self.monitor.check()
            self.host.volume_manager.inventory.return_value = {"volumes": [{"name": "data", "mounted": True,
                "mountpoint": "/srv/titan/volumes/data", "total": 100, "used": 10, "free": 90}]}
            state = self.monitor.check(force=True)
        self.assertTrue(any(item["key"] == "volume:data" and not item["active"] for item in state["alerts"]))

    def test_missing_unit_for_installed_service_raises_alert(self):
        self.run.return_value = "LoadState=not-found\nActiveState=inactive"
        with patch.object(self.monitor, "_smart", return_value={"name": "/dev/sda", "health": "passed", "temperature": 30}):
            state = self.monitor.check()
        self.assertTrue(state["services"]["https"]["installed"])
        self.assertEqual(state["services"]["https"]["state"], "not-found")
        self.assertTrue(any(item["key"] == "service:https" and item["active"] for item in state["alerts"]))

    def test_missing_backup_mount_warns_without_reporting_root_as_backup_storage(self):
        self.host.save("backup-settings", {"target": "/mnt/backup"})
        with patch("titan.backups.Backups.validate_target", side_effect=Error("Nicht eingehängt")), patch.object(self.monitor, "_smart", return_value={"name": "/dev/sda", "health": "passed", "temperature": 30}):
            state = self.monitor.check()
        self.assertTrue(any(item["key"] == "backup:target" and item["active"] for item in state["alerts"]))
        self.assertFalse(any(item["name"] == "backup" for item in state["storage"]))

    def test_resolved_error_remains_in_history_but_is_not_active(self):
        self.host.save("backup-state", {"last": {"ok": False, "error": "Offline"}})
        with patch.object(self.monitor, "_smart", return_value={"name": "/dev/sda", "health": "passed", "temperature": 30}):
            first = self.monitor.check()
            self.host.save("backup-state", {"last": {"ok": True}})
            second = self.monitor.check(force=True)
        self.assertTrue(any(item["key"] == "backup:last" and item["active"] for item in first["alerts"]))
        self.assertTrue(any(item["key"] == "backup:last" and not item["active"] for item in second["alerts"]))

    def test_absent_unused_components_are_not_relevant(self):
        with patch("titan.monitoring.shutil.which", side_effect=lambda name: "/usr/bin/" + name if name in ("python3", "caddy") else None):
            services = self.monitor.service_status()
        for name in ("docker", "vms", "samba", "zfs"):
            self.assertFalse(services[name]["relevant"])
        for name in ("web", "agent", "https"):
            self.assertTrue(services[name]["relevant"])

    def test_missing_configured_components_remain_visible_and_raise_alerts(self):
        self.host.save("apps", [{"id": "jellyfin"}])
        self.host.save("shares", [{"name": "private"}])
        (self.host.directory / "vm-test.xml").write_text("<domain/>")
        with patch("titan.monitoring.shutil.which", side_effect=lambda name: "/usr/bin/" + name if name in ("python3", "caddy") else None), patch.object(self.monitor, "_smart", return_value={"name": "/dev/sda", "health": "passed", "temperature": 30}):
            state = self.monitor.check()
        for name in ("docker", "samba", "vms"):
            self.assertTrue(state["services"][name]["relevant"])
            self.assertTrue(state["services"][name]["configured"])
            self.assertTrue(any(alert["key"] == "service:" + name and alert["active"] for alert in state["alerts"]))

    def test_installed_zfs_without_pools_is_hidden_and_does_not_warn(self):
        self.monitor.run = lambda args: "" if args[0] == "zpool" else "LoadState=loaded\nActiveState=active"
        with patch("titan.monitoring.shutil.which", return_value="/usr/bin/tool"), patch.object(self.monitor, "_smart", return_value={"name": "/dev/sda", "health": "passed", "temperature": 30}):
            state = self.monitor.check()
        self.assertTrue(state["services"]["zfs"]["installed"])
        self.assertFalse(state["services"]["zfs"]["relevant"])
        self.assertFalse(any(alert["key"] == "service:zfs" and alert["active"] for alert in state["alerts"]))

    def test_used_zfs_reports_pool_health_not_inactive_import_target(self):
        self.monitor.run = lambda args: "tank\tONLINE\t100\t10" if args[0] == "zpool" else "LoadState=loaded\nActiveState=inactive"
        with patch("titan.monitoring.shutil.which", return_value="/usr/bin/tool"), patch.object(self.monitor, "_smart", return_value={"name": "/dev/sda", "health": "passed", "temperature": 30}):
            state = self.monitor.check()
        self.assertTrue(state["services"]["zfs"]["relevant"])
        self.assertTrue(state["services"]["zfs"]["active"])
        self.assertFalse(any(alert["key"] == "service:zfs" and alert["active"] for alert in state["alerts"]))

    def test_known_zfs_pool_remains_visible_after_tools_disappear(self):
        self.host.save("monitoring", {"checked": 0, "alerts": [], "pools": [{"name": "tank"}], "known_pools": ["tank"]})
        with patch.object(self.monitor, "_smart", return_value={"name": "/dev/sda", "health": "passed", "temperature": 30}):
            first = self.monitor.check(force=True)
            second = self.monitor.check(force=True)
        self.assertTrue(first["services"]["zfs"]["relevant"])
        self.assertTrue(second["services"]["zfs"]["relevant"])
        self.assertFalse(second["services"]["zfs"]["installed"])

    def test_pool_query_error_keeps_zfs_visible(self):
        def runner(args):
            if args[0] == "zpool":
                raise Error("Pool nicht erreichbar")
            return "LoadState=loaded\nActiveState=active"
        self.monitor.run = runner
        with patch("titan.monitoring.shutil.which", return_value="/usr/bin/tool"):
            services = self.monitor.service_status()
        self.assertTrue(services["zfs"]["relevant"])
        self.assertEqual(services["zfs"]["state"], "unknown")
        self.assertIn("Pool nicht erreichbar", services["zfs"]["error"])


if __name__ == "__main__":
    unittest.main()

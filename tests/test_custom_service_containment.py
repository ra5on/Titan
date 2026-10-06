"""Containment uses a fake system manager; never mutate the test host's units."""
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from titan.custom_services import (Containment, ContainmentFailure, REPORT_FORMAT,
    identity_uid, read_report, unsafe_custom_identity, write_report)
from titan.service_manager import ServiceManagerMixin

ROOT = Path(__file__).resolve().parents[1]


class FakeSystem:
    def __init__(self):
        self.units = {}
        self.calls = []
        self.disable_fails = False
        self.stop_fails = False
        self.stubborn = False
        self.enabled_after_disable = False
        self.now = 0.0

    def add(self, name, user="root", canonical=None, enabled=True, active=True):
        self.units[name] = {"Id": canonical or name,
            "Names": name if not canonical or canonical == name else name + " " + canonical,
            "User": user, "LoadState": "loaded", "ActiveState": "active" if active else "inactive",
            "MainPID": "42" if active else "0", "UnitFileState": "enabled" if enabled else "disabled"}

    def lookup(self, name):
        if name == "root" or name == "root-alias":
            return SimpleNamespace(pw_uid=0)
        if name == "titan-files":
            return SimpleNamespace(pw_uid=992)
        raise KeyError(name)

    def sleep(self, value):
        self.now += value

    def run(self, arguments, timeout):
        self.calls.append(arguments)
        self.assertions(timeout)
        if arguments[0] == "list-unit-files":
            return json.dumps([{"unit_file": name} for name in self.units])
        if arguments[0] == "list-units":
            return json.dumps([{"unit": name} for name in self.units])
        if arguments[0] == "show":
            return "\n".join(key + "=" + value for key, value in self.units[arguments[-1]].items())
        if "disable" in arguments:
            if self.disable_fails:
                raise ContainmentFailure("systemctl_failed")
            if not self.enabled_after_disable:
                for name in arguments[arguments.index("--") + 1:]:
                    self.units[name]["UnitFileState"] = "disabled"
            return ""
        if arguments[:2] == ["--no-block", "stop"]:
            if self.stop_fails:
                raise ContainmentFailure("systemctl_failed")
            if not self.stubborn:
                for name in arguments[arguments.index("--") + 1:]:
                    self.units[name].update(ActiveState="inactive", MainPID="0")
            return ""
        raise AssertionError(arguments)

    @staticmethod
    def assertions(timeout):
        assert 0 < timeout <= 10

    def guard(self, timeout=5):
        return Containment(run=self.run, lookup=self.lookup, clock=lambda: self.now,
            sleep=self.sleep, timeout=timeout)

    def mutations(self):
        return [args for args in self.calls if "disable" in args or "stop" in args]


class ContainmentTests(unittest.TestCase):
    def test_all_uid_zero_forms_are_contained_without_touching_other_services(self):
        fake = FakeSystem()
        for index, identity in enumerate(("", "root", "0", "000", "root-alias")):
            fake.add("titan-custom-root" + str(index) + ".service", identity)
        fake.add("titan-custom-reader.service", "titan-files")
        fake.add("titan-custom-numeric.service", "1000")
        fake.add("sshd.service", "root")
        fake.add("titan-service-containment.service", "root")
        original = copy.deepcopy(fake.units)
        result = fake.guard().contain()
        selected = sorted(name for name in fake.units if name.startswith("titan-custom-root"))
        self.assertTrue(result["ok"])
        self.assertEqual([item["name"] for item in result["blocked_units"]], selected)
        self.assertTrue(all(item["was_enabled"] and item["was_running"] for item in result["blocked_units"]))
        self.assertEqual(fake.mutations(), [["disable", "--", *selected],
            ["--runtime", "disable", "--", *selected], ["--no-block", "stop", "--", *selected]])
        for name in fake.units:
            if name not in selected:
                self.assertEqual(fake.units[name], original[name])
        self.assertTrue(all(fake.units[name]["ActiveState"] == "inactive" and
            fake.units[name]["UnitFileState"] == "disabled" for name in selected))

    def test_foreign_canonical_alias_and_unknown_identity_fail_before_mutation(self):
        for identity, canonical, category in (("root", "sshd.service", "foreign_unit_alias"),
                ("unknown-user", None, "unknown_identity")):
            with self.subTest(identity=identity):
                fake = FakeSystem()
                fake.add("titan-custom-known.service")
                fake.add("titan-custom-uncertain.service", identity, canonical)
                with self.assertRaisesRegex(ContainmentFailure, category):
                    fake.guard().contain()
                self.assertEqual(fake.mutations(), [])

    def test_disable_failure_still_stops_known_root_units_and_fails_closed(self):
        fake = FakeSystem(); fake.add("titan-custom-old.service"); fake.disable_fails = True
        with self.assertRaisesRegex(ContainmentFailure, "disable_failed"):
            fake.guard().contain()
        self.assertIn(["--no-block", "stop", "--", "titan-custom-old.service"], fake.mutations())
        self.assertEqual(fake.units["titan-custom-old.service"]["ActiveState"], "inactive")

    def test_stop_failure_and_unfinished_stop_are_never_reported_success(self):
        for category in ("systemctl_failed", "stop_timeout", "unit_still_enabled"):
            with self.subTest(category=category):
                fake = FakeSystem(); fake.add("titan-custom-old.service")
                fake.stop_fails = category == "systemctl_failed"
                fake.stubborn = category == "stop_timeout"
                fake.enabled_after_disable = category == "unit_still_enabled"
                with self.assertRaisesRegex(ContainmentFailure, category):
                    fake.guard(timeout=1).contain()
                self.assertLessEqual(fake.now, 1)

    def test_invalid_inventory_names_and_missing_properties_fail_closed(self):
        for name in ("titan-custom-*.service", "titan-custom-../root.service", "titan-custom-@.service"):
            fake = FakeSystem(); fake.add(name)
            with self.subTest(name=name), self.assertRaisesRegex(ContainmentFailure, "invalid_custom_unit"):
                fake.guard().contain()
            self.assertEqual(fake.mutations(), [])
        fake = FakeSystem(); fake.add("titan-custom-old.service"); fake.units["titan-custom-old.service"].pop("User")
        with self.assertRaisesRegex(ContainmentFailure, "invalid_unit_properties"):
            fake.guard().contain()
        self.assertEqual(fake.mutations(), [])
        guard = Containment(run=lambda args, timeout: "{invalid secret-output", clock=lambda:0)
        with self.assertRaisesRegex(ContainmentFailure, "^invalid_inventory$"):
            guard.contain()

    def test_no_custom_units_means_no_mutations(self):
        fake = FakeSystem(); fake.add("sshd.service"); fake.add("titan-agent.service")
        self.assertEqual(fake.guard().contain()["blocked_units"], [])
        self.assertEqual(fake.mutations(), [])

    def test_existing_unit_file_and_data_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            unit = path / "titan-custom-old.service"; unit.write_text("[Service]\nExecStart=/usr/bin/sleep infinity\n")
            data = path / "owned-data"; data.write_bytes(b"preserved\x00data")
            before = {file: file.read_bytes() for file in (unit, data)}
            fake = FakeSystem(); fake.add(unit.name); fake.guard().contain()
            self.assertEqual({file: file.read_bytes() for file in (unit, data)}, before)

    def test_main_refuses_nonroot_before_any_host_command(self):
        with patch("titan.custom_services.os.geteuid", return_value=1000), \
                patch("titan.custom_services._systemctl") as run, \
                patch("titan.custom_services.write_report") as write, \
                patch("titan.custom_services.print"):
            from titan.custom_services import main
            self.assertEqual(main(), 1)
            run.assert_not_called(); write.assert_not_called()


class ReportAndAPITests(unittest.TestCase):
    def test_report_is_atomic_private_and_rejects_symlinks_corruption_or_wrong_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result.json"
            fake = FakeSystem(); fake.add("titan-custom-old.service")
            value = fake.guard().contain()
            write_report(value, path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(read_report(path, owner=os.geteuid()), value)
            self.assertIsNone(read_report(path, owner=os.geteuid()+1))
            path.write_text('{"format":"invalid"}')
            self.assertIsNone(read_report(path, owner=os.geteuid()))
            path.unlink(); external = Path(temporary)/"outside"; external.write_text("unchanged")
            path.symlink_to(external)
            self.assertIsNone(read_report(path, owner=os.geteuid()))
            write_report(value, path)
            self.assertFalse(path.is_symlink())
            self.assertEqual(external.read_text(), "unchanged")
            Path(temporary).chmod(0o755)
            with self.assertRaisesRegex(ContainmentFailure, "diagnostic_failed"):
                write_report(value, path)

    def test_root_alias_unknown_numeric_and_nonroot_api_identities(self):
        fake = FakeSystem()
        for value in ("", "root", "0", "000", "root-alias", "missing-user", "4294967295", None):
            with self.subTest(value=value), patch("titan.custom_services.pwd.getpwnam", side_effect=fake.lookup):
                self.assertTrue(unsafe_custom_identity("titan-custom-old.service", {"User":value}))
        for value in ("992", "titan-files"):
            with self.subTest(value=value), patch("titan.custom_services.pwd.getpwnam", side_effect=fake.lookup):
                self.assertFalse(unsafe_custom_identity("titan-custom-worker.service", {"User":value}))
        self.assertFalse(unsafe_custom_identity("sshd.service", {"User":"root"}))
        self.assertTrue(unsafe_custom_identity("ordinary-alias.service", {"User":"0", "Id":"titan-custom-old.service"}))

    def test_contained_service_inventory_shows_block_reason_and_no_start_actions(self):
        name = "titan-custom-old.service"
        summary = ServiceManagerMixin._service_summary(name,
            {name:{"state":"disabled"}}, {}, contained=True)
        self.assertIn("Rootdienst deaktiviert", summary["protected_reason"])
        self.assertFalse(set(summary["allowed_actions"]) & {"start","restart","reload","enable"})
        self.assertFalse(summary["enabled"])

    def test_unit_runs_before_basic_and_agent_requires_successful_gate(self):
        text = (ROOT/"image/titan-service-containment.service").read_text()
        self.assertIn("DefaultDependencies=no", text)
        self.assertIn("After=local-fs.target", text)
        self.assertIn("Before=basic.target titan-agent.service", text)
        self.assertIn("WantedBy=basic.target", text)
        self.assertIn("ExecStart=/usr/bin/python3 -I /usr/lib/titan/titan/custom_services.py", text)
        self.assertIn("RuntimeDirectoryMode=0700", text)
        agent = (ROOT/"packaging/titan-agent.service").read_text()
        for prefix in ("Requires=", "After="):
            self.assertIn(prefix + "titan-service-containment.service", agent)
        self.assertIn("titan-service-containment.service", (ROOT/"image/debian/configure-guest.sh").read_text())


if __name__ == "__main__":
    unittest.main()

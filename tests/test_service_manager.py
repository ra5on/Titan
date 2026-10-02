import json
import os
from pathlib import Path
import shlex
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from titan.core import Error
from titan.service_manager import MAX_LOG_BYTES, MAX_SERVICES, ServiceManagerMixin, UNIT_PROPERTIES


class Manager(ServiceManagerMixin):
    def __init__(self, root):
        self.service_unit_root = root
        self.lock = threading.RLock()


class ServiceManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.units = self.root / "units"
        self.units.mkdir(mode=0o755)
        self.user_units = self.root / "user-units"
        self.user_units.mkdir()
        self.host = Manager(self.units)
        self.program = self.root / 'report $name%worker'
        self.program.write_text("#!/bin/sh\nexit 0\n")
        self.program.chmod(0o755)
        self.working_directory = self.root / "data % literal"
        self.working_directory.mkdir()
        self.accounts = [self.account("root", 0), self.account("titan-files", 992, "/usr/sbin/nologin"),
                         self.account("alice", 1000), self.account("daemon", 1, "/usr/sbin/nologin"),
                         self.account("other-daemon", 1010, "/usr/sbin/nologin"), self.account("nobody", 65534)]
        self.files = [{"unit_file": "cron.service", "state": "enabled", "preset": "enabled"}]
        self.loaded = [{"unit": "cron.service", "load": "loaded", "active": "active", "sub": "running", "description": "Cron"}]
        self.properties = {"Id": "cron.service", "Names": "cron.service", "Description": "Cron", "LoadState": "loaded",
                           "ActiveState": "active", "SubState": "running", "UnitFileState": "enabled", "MainPID": "42"}
        self.calls = []
        self.verified = []
        self.logs = "2026-10-01T12:30:00+0200 cron: completed\n"
        self.runner = patch("titan.host.run", side_effect=self.command).start()
        patch("titan.service_manager.pwd.getpwall", side_effect=lambda: self.accounts).start()
        patch("titan.service_manager.pwd.getpwnam", side_effect=self.account_by_name).start()
        patch("titan.service_manager.USER_UNIT_ROOTS", (self.user_units,)).start()

    def tearDown(self):
        patch.stopall()
        self.temp.cleanup()

    def account(self, name, uid, shell="/bin/bash"):
        return SimpleNamespace(pw_name=name, pw_uid=uid, pw_gid=uid, pw_shell=shell, pw_dir=str(self.root / "homes" / name))

    def account_by_name(self, name):
        account = next((account for account in self.accounts if account.pw_name == name), None)
        if account is None:
            raise KeyError(name)
        return account

    def command(self, arguments, **kwargs):
        self.calls.append((arguments, kwargs))
        if arguments[:2] == ["systemctl", "list-unit-files"]:
            return json.dumps(self.files)
        if arguments[:2] == ["systemctl", "list-units"]:
            return json.dumps(self.loaded)
        if arguments[:2] == ["systemctl", "show"]:
            return "\n".join(key + "=" + value for key, value in self.properties.items())
        if arguments[0] == "journalctl":
            return self.logs
        if arguments[:2] == ["systemd-analyze", "verify"]:
            path = Path(arguments[2])
            self.verified.append((path, path.read_text(), path.stat().st_mode & 0o777, path.parent.stat().st_mode & 0o777))
        return ""

    def create(self, **values):
        return self.host.op_service_create(**{"name": "report", "description": "Report worker", "program": str(self.program), **values})

    def mutation_calls(self):
        return [args for args, _ in self.calls if args[0] == "systemctl" and args[1] in ("start", "stop", "restart", "enable", "disable", "daemon-reload")]

    def test_inventory_uses_two_bulk_json_commands_and_contains_real_units(self):
        self.files += [{"unit_file": "inactive.service", "state": "disabled", "preset": "disabled"},
                       {"unit_file": "linked.service", "state": "linked", "preset": None},
                       {"unit_file": "titan-web.service", "state": "enabled", "preset": "enabled"}]
        self.loaded += [{"unit": "runtime.service", "load": "loaded", "active": "active", "sub": "running", "description": "Transient"},
                        {"unit": "removed.service", "load": "not-found", "active": "inactive", "sub": "dead", "description": "Removed"},
                        {"unit": "stale.service", "load": "loaded", "active": "inactive", "sub": "dead", "description": "Stale"}]
        result = self.host.op_services()
        rows = {row["name"]: row for row in result["items"]}
        self.assertEqual(set(rows), {"cron.service", "inactive.service", "linked.service", "titan-web.service", "runtime.service"})
        self.assertFalse(rows["inactive.service"]["enabled"])
        self.assertFalse(rows["linked.service"]["enabled"])
        self.assertEqual(rows["cron.service"]["sub"], "running")
        self.assertTrue(rows["runtime.service"]["transient"])
        self.assertTrue(rows["titan-web.service"]["protected"])
        self.assertEqual(rows["titan-web.service"]["allowed_actions"], ["start", "enable"])
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all("--output=json" in args and kwargs["timeout"] == 30 for args, kwargs in self.calls))
        self.assertEqual([row["name"] for row in result["users"]], ["titan-files", "root", "alice"])

    def test_large_inventory_is_bounded_without_per_unit_subprocesses(self):
        self.loaded = []
        self.files = [{"unit_file": f"unit-{number}.service", "state": "disabled", "preset": "disabled"}
                      for number in range(MAX_SERVICES + 25)]
        result = self.host.op_services()
        self.assertEqual(len(result["items"]), MAX_SERVICES)
        self.assertEqual(result["total"], MAX_SERVICES + 25)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(self.calls), 2)

    def test_running_template_instances_are_not_mislabeled_transient(self):
        self.files += [{"unit_file": "worker@.service", "state": "disabled", "preset": None}]
        self.loaded += [{"unit": "worker@one.service", "load": "loaded", "active": "active", "sub": "running", "description": "Worker one"}]
        rows = {row["name"]: row for row in self.host.op_services()["items"]}
        self.assertFalse(rows["worker@one.service"]["transient"])
        self.properties.update(Id="worker@one.service", Names="worker@one.service", Transient="no")
        self.files = []
        details = self.host.op_service_details("worker@one.service", tail=0)
        self.assertFalse(details["service"]["transient"])

    def test_details_filter_properties_and_bound_recent_logs(self):
        self.properties.update(Environment="PASSWORD=secret", ExecStart="secret --token=private")
        self.logs = "é" * (MAX_LOG_BYTES + 100)
        result = self.host.op_service_details("cron.service", 500)
        self.assertTrue(result["logs_truncated"])
        self.assertLessEqual(len(result["logs"].encode()), MAX_LOG_BYTES)
        self.assertNotIn("Environment", result["service"]["properties"])
        self.assertNotIn("ExecStart", result["service"]["properties"])
        self.assertNotIn("secret", json.dumps(result))
        command = next(args for args, _ in self.calls if args[0] == "journalctl")
        self.assertIn("--lines=500", command)
        self.assertIn("--unit=cron.service", command)
        shown = next(args for args, _ in self.calls if args[:2] == ["systemctl", "show"])
        self.assertIn("--property=" + ",".join(UNIT_PROPERTIES), shown)

    def test_log_failure_preserves_details_and_tail_zero_skips_journal(self):
        original = self.command
        def runner(args, **kwargs):
            if args[0] == "journalctl":
                raise Error("Journal unavailable", 503)
            return original(args, **kwargs)
        self.runner.side_effect = runner
        result = self.host.op_service_details("cron.service")
        self.assertEqual(result["service"]["active"], "active")
        self.assertEqual(result["logs_error"], "Journal unavailable")
        self.calls.clear()
        self.host.op_service_details("cron.service", 0)
        self.assertFalse(any(args[0] == "journalctl" for args, _ in self.calls))
        for tail in (True, -1, 501):
            with self.subTest(tail=tail), self.assertRaises(Error):
                self.host.op_service_details("cron.service", tail)

    def test_action_has_fixed_verb_and_unit_argument(self):
        result = self.host.op_service_action("cron.service", "restart")
        self.assertTrue(result["ok"])
        self.assertEqual(self.mutation_calls(), [["systemctl", "restart", "--", "cron.service"]])
        self.calls.clear()
        for service, command in (("cron.service", "restart; reboot"), ("cron*", "stop"),
                                 ("--all.service", "stop"), ("../cron.service", "stop"), ("missing.service", "start")):
            with self.subTest(service=service, command=command), self.assertRaises(Error):
                self.host.op_service_action(service, command)
        self.assertEqual(self.mutation_calls(), [])

    def test_agent_web_and_proxy_and_their_aliases_cannot_be_stopped(self):
        for name in ("titan-agent.service", "titan-web.service", "titan-proxy.service", "alias.service"):
            self.files = [{"unit_file": name, "state": "enabled", "preset": "enabled"}]
            self.loaded = []
            self.properties.update(Id=name if name != "alias.service" else "titan-agent.service",
                                   Names=name + " titan-agent.service")
            for command in ("stop", "restart", "disable"):
                with self.subTest(name=name, command=command), self.assertRaises(Error) as result:
                    self.host.op_service_action(name, command)
                self.assertEqual(result.exception.status, 403)
        self.assertEqual(self.mutation_calls(), [])

    def test_acknowledged_start_or_restart_of_failed_unit_returns_failed_result(self):
        self.properties.update(ActiveState="failed", SubState="failed", Result="exit-code", ExecMainStatus="3")
        for command in ("start", "restart"):
            with self.subTest(command=command):
                result = self.host.op_service_action("cron.service", command)
                self.assertFalse(result["ok"])
                self.assertEqual(result["command"], command)
                self.assertEqual(result["service"]["active"], "failed")
                self.assertIn("exit-code", result["error"])
                self.assertIn("Exit-Status 3", result["error"])

    def test_service_template_requires_instance_for_runtime_actions(self):
        self.files = [{"unit_file": "worker@.service", "state": "disabled", "preset": None}]
        self.properties.update(Id="worker@.service", Names="worker@.service")
        with self.assertRaises(Error):
            self.host.op_service_action("worker@.service", "start")
        self.assertEqual(self.mutation_calls(), [])

    def test_creation_verifies_literal_argv_before_publish_then_enables_and_starts(self):
        argv = ["two words", "$HOME", "${TOKEN}", "%i", "literal\\path", 'a"quote', ";", "|", "--name=value", ""]
        result = self.create(args=shlex.join(argv), description="Report % worker", working_directory=str(self.working_directory),
                             user="root", autostart=True, start=True)
        target = self.units / "titan-custom-report.service"
        source = target.read_text()
        self.assertEqual({key: result[key] for key in ("ok", "created", "service", "autostart", "start")},
                         {"ok": True, "created": True, "service": target.name, "autostart": True, "start": True})
        self.assertIn("details", result)
        self.assertIn("Description=Report %% worker\n", source)
        self.assertIn("User=root\n", source)
        self.assertIn("WorkingDirectory=" + str(self.working_directory).replace("%", "%%") + "\n", source)
        self.assertIn('ExecStart=:"' + str(self.program).replace("%", "%%") + '" ', source)
        self.assertIn('"two words" "$HOME" "${TOKEN}" "%%i" "literal\\\\path" "a\\"quote" \\; "|" "--name=value" ""\n', source)
        self.assertNotIn("/bin/sh", source)
        self.assertNotIn("Environment=", source)
        self.assertEqual(target.stat().st_mode & 0o777, 0o644)
        self.assertEqual(len(self.verified), 1)
        staged, verified, mode, directory_mode = self.verified[0]
        self.assertEqual(verified, source)
        self.assertEqual(staged.name, target.name)
        self.assertEqual(mode, 0o644)
        self.assertEqual(directory_mode, 0o700)
        self.assertFalse(staged.exists())
        self.assertEqual(self.mutation_calls(), [["systemctl", "daemon-reload"], ["systemctl", "enable", "--", target.name],
                                                ["systemctl", "start", "--", target.name]])

    def test_creation_without_autostart_or_start_only_reloads(self):
        self.create()
        self.assertEqual(self.mutation_calls(), [["systemctl", "daemon-reload"]])
        self.assertIn("User=titan-files\n", (self.units / "titan-custom-report.service").read_text())

    def test_controls_and_malformed_fields_are_rejected_before_commands(self):
        cases = [{field: value} for field, value in (("name", "bad\nname"), ("description", "okay\nExecStart=/bin/evil"),
                ("program", str(self.program) + "\x00"), ("args", "okay\r; reboot"), ("user", "root\n"),
                ("working_directory", str(self.root) + "\n"), ("description", "trailing\\"), ("args", "'broken"),
                ("args", "x " * 129), ("autostart", "false"), ("start", 1), ("user", "daemon"),
                ("user", "other-daemon"), ("program", "relative"), ("program", str(self.root)),
                ("working_directory", "relative"), ("working_directory", str(self.root / "missing")))]
        for params in cases:
            with self.subTest(params=params), self.assertRaises(Error):
                self.create(**params)
        self.assertEqual(self.calls, [])
        self.assertEqual(list(self.units.iterdir()), [])

    def test_non_executable_program_and_missing_default_user_are_rejected(self):
        self.program.chmod(0o644)
        with self.assertRaises(Error):
            self.create()
        self.program.chmod(0o755)
        self.accounts = [account for account in self.accounts if account.pw_name != "titan-files"]
        with self.assertRaises(Error):
            self.create()
        self.assertEqual(self.calls, [])

    def test_installed_or_loaded_unit_collision_never_mutates(self):
        self.files += [{"unit_file": "titan-custom-report.service", "state": "disabled", "preset": None}]
        with self.assertRaises(Error) as result:
            self.create()
        self.assertEqual(result.exception.status, 409)
        self.files = []
        self.loaded = [{"unit": "titan-custom-report.service", "load": "loaded", "active": "inactive", "sub": "dead", "description": "Existing transient"}]
        with self.assertRaises(Error):
            self.create()
        self.assertEqual(self.mutation_calls(), [])
        self.assertEqual(list(self.units.iterdir()), [])

    def test_existing_file_and_dangling_symlink_are_not_overwritten(self):
        path = self.units / "titan-custom-report.service"
        path.write_text("existing data")
        with self.assertRaises(Error):
            self.create()
        self.assertEqual(path.read_text(), "existing data")
        path.unlink()
        path.symlink_to(self.root / "missing")
        with self.assertRaises(Error):
            self.create()
        self.assertTrue(path.is_symlink())
        self.assertEqual(self.verified, [])
        self.assertEqual(self.mutation_calls(), [])

    def test_global_and_home_user_units_keep_their_names(self):
        path = self.user_units / "titan-custom-report.service"
        path.write_text("user service")
        with self.assertRaises(Error):
            self.create()
        self.assertEqual(path.read_text(), "user service")
        path.unlink()
        home_unit = Path(self.accounts[2].pw_dir) / ".config/systemd/user/titan-custom-report.service"
        home_unit.parent.mkdir(parents=True)
        home_unit.symlink_to(self.root / "missing")
        with self.assertRaises(Error):
            self.create()
        self.assertTrue(home_unit.is_symlink())
        self.assertEqual(self.mutation_calls(), [])

    def test_orphaned_custom_dropin_does_not_change_the_new_service_definition(self):
        directory = self.units / "titan-custom-report.service.d"
        directory.mkdir()
        existing = directory / "override.conf"
        existing.write_text("[Service]\nExecStart=/usr/bin/false\n")
        with self.assertRaises(Error) as result:
            self.create()
        self.assertEqual(result.exception.status, 409)
        self.assertEqual(existing.read_text(), "[Service]\nExecStart=/usr/bin/false\n")
        self.assertFalse((self.units / "titan-custom-report.service").exists())
        self.assertEqual(self.mutation_calls(), [])

    def test_concurrent_name_collision_at_publish_is_preserved(self):
        original = self.command
        target = self.units / "titan-custom-report.service"
        def runner(args, **kwargs):
            output = original(args, **kwargs)
            if args[0] == "systemd-analyze":
                target.write_text("concurrent creator")
            return output
        self.runner.side_effect = runner
        with self.assertRaises(Error) as result:
            self.create()
        self.assertEqual(result.exception.status, 409)
        self.assertEqual(target.read_text(), "concurrent creator")
        self.assertEqual(list(self.units.iterdir()), [target])
        self.assertEqual(self.mutation_calls(), [])

    def test_verification_failure_removes_only_private_staging(self):
        sentinel = self.units / "untouched.service"
        sentinel.write_text("important")
        original = self.command
        def runner(args, **kwargs):
            output = original(args, **kwargs)
            if args[0] == "systemd-analyze":
                raise Error("Unit verification failed")
            return output
        self.runner.side_effect = runner
        with self.assertRaises(Error):
            self.create()
        self.assertEqual(list(self.units.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_text(), "important")
        self.assertEqual(self.mutation_calls(), [])

    def test_failed_reload_enable_or_start_keeps_new_service_for_inspection_and_retry(self):
        original = self.command
        for failed_step in ("daemon-reload", "enable", "start"):
            def runner(args, **kwargs):
                output = original(args, **kwargs)
                if args[:2] == ["systemctl", failed_step]:
                    raise Error(failed_step + " failed")
                return output
            self.runner.side_effect = runner
            result = self.create(name=failed_step, autostart=True, start=True)
            self.assertFalse(result["ok"])
            self.assertTrue(result["created"])
            self.assertEqual(result["error"], failed_step + " failed")
            self.assertEqual(result["autostart"], failed_step == "start")
            self.assertFalse(result["start"])
            self.assertTrue((self.units / result["service"]).is_file())
        self.assertFalse(any(args[1] in ("stop", "disable") for args in self.mutation_calls()))

    def test_acknowledged_start_with_failed_process_is_not_reported_successful(self):
        self.properties.update(Id="titan-custom-report.service", Names="titan-custom-report.service",
                               ActiveState="failed", SubState="failed", Result="exit-code", ExecMainStatus="2",
                               Environment="SECRET=value")
        result = self.create(autostart=True, start=True)
        self.assertFalse(result["ok"])
        self.assertTrue(result["created"])
        self.assertTrue(result["autostart"])
        self.assertFalse(result["start"])
        self.assertEqual(result["details"]["active"], "failed")
        self.assertIn("exit-code", result["error"])
        self.assertIn("Exit-Status 2", result["error"])
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertTrue((self.units / result["service"]).is_file())

    def test_symlinked_or_writable_unit_directory_is_rejected(self):
        linked = self.root / "linked-units"
        linked.symlink_to(self.units, target_is_directory=True)
        self.host.service_unit_root = linked
        with self.assertRaises(Error):
            self.create()
        self.host.service_unit_root = self.units
        self.units.chmod(0o777)
        with self.assertRaises(Error):
            self.create()
        self.assertEqual(self.verified, [])
        self.assertEqual(self.mutation_calls(), [])

    def test_malformed_json_stops_before_any_service_mutation(self):
        self.runner.side_effect = lambda args, **kwargs: "UNIT FILE STATE PRESET"
        with self.assertRaises(Error) as result:
            self.create()
        self.assertEqual(result.exception.status, 503)
        self.assertEqual(list(self.units.iterdir()), [])

    def test_failed_services_are_visible_first_and_counts_include_unshown_inventory(self):
        self.files += [{"unit_file": "zz-failed.service", "state": "disabled", "preset": None}]
        self.loaded += [{"unit": "zz-failed.service", "load": "loaded", "active": "failed", "sub": "failed", "description": "Worker"}]
        result = self.host.op_services()
        self.assertEqual(result["items"][0]["name"], "zz-failed.service")
        self.assertEqual(result["counts"], {"total": 2, "active": 1, "failed": 1, "enabled": 1, "custom": 0})
        self.assertEqual(len(self.calls), 2)

    def test_reload_is_offered_only_for_active_reload_capable_units(self):
        self.properties["CanReload"] = "yes"
        details = self.host.op_service_details("cron.service", 0)
        self.assertIn("reload", details["service"]["allowed_actions"])
        self.assertTrue(self.host.op_service_action("cron.service", "reload")["ok"])
        self.assertTrue(any(args == ["systemctl", "reload", "--", "cron.service"] for args, _ in self.calls))
        self.calls.clear()
        self.properties["ActiveState"] = "inactive"
        with self.assertRaises(Error):
            self.host.op_service_action("cron.service", "reload")
        self.assertFalse(any(args[:2] == ["systemctl", "reload"] for args, _ in self.calls))

    def test_masked_static_and_transient_units_do_not_offer_invalid_actions(self):
        for state in ("static", "generated", "transient"):
            self.properties["UnitFileState"] = state
            summary = self.host.op_service_details("cron.service", 0)["service"]
            self.assertNotIn("enable", summary["allowed_actions"])
            self.assertNotIn("disable", summary["allowed_actions"])
        self.properties.update(UnitFileState="masked", CanStart="no")
        summary = self.host.op_service_details("cron.service", 0)["service"]
        self.assertEqual(summary["health"], "masked")
        self.assertFalse(set(summary["allowed_actions"]) & {"start", "restart", "reload", "enable"})

    def test_reset_failed_is_fixed_action_and_keeps_protected_access_units_safe(self):
        self.properties.update(ActiveState="failed", SubState="failed", Result="start-limit-hit")
        self.assertTrue(self.host.op_service_action("cron.service", "reset-failed")["ok"])
        self.assertTrue(any(args == ["systemctl", "reset-failed", "--", "cron.service"] for args, _ in self.calls))
        self.properties.update(Names="cron.service titan-web.service")
        self.calls.clear()
        with self.assertRaises(Error):
            self.host.op_service_action("cron.service", "reset-failed")
        self.assertFalse(any(args[:2] == ["systemctl", "reset-failed"] for args, _ in self.calls))

    def test_failed_command_returns_current_state_and_keeps_job_error_reviewable(self):
        original = self.command
        def command(args, **kwargs):
            if args[:2] == ["systemctl", "restart"]:
                self.properties.update(ActiveState="failed", SubState="failed", Result="exit-code", ExecMainStatus="2")
                raise Error("Job for cron.service failed because its process exited", 503)
            return original(args, **kwargs)
        self.runner.side_effect = command
        result = self.host.op_service_action("cron.service", "restart")
        self.assertFalse(result["ok"])
        self.assertEqual(result["service"]["active"], "failed")
        self.assertEqual(result["service"]["exit_code"], "2")
        self.assertIn("process exited", result["error"])

    def test_unavailable_post_action_status_does_not_report_success(self):
        original = self.command
        seen = False
        def command(args, **kwargs):
            nonlocal seen
            if args[:2] == ["systemctl", "stop"]:
                seen = True
            if seen and args[:2] == ["systemctl", "show"]:
                raise Error("System manager unavailable", 503)
            return original(args, **kwargs)
        self.runner.side_effect = command
        result = self.host.op_service_action("cron.service", "stop")
        self.assertFalse(result["ok"])
        self.assertIn("unavailable", result["status_error"])

    def test_accounting_and_socket_timer_relationships_use_measured_values_or_unknown(self):
        self.properties.update(MemoryCurrent="4096", MemoryPeak="18446744073709551615", CPUUsageNSec="2500000000",
                               NRestarts="3", TasksCurrent="[not set]", TriggeredBy="cron.timer cron.socket",
                               Requires="network.target", Wants="network-online.target", After="network.target")
        detail = self.host.op_service_details("cron.service", 0)["service"]
        self.assertEqual(detail["metrics"], {"main_pid": 42, "restarts": 3, "memory_bytes": 4096,
                                            "memory_peak_bytes": None, "cpu_seconds": 2.5, "tasks": None})
        self.assertEqual(detail["relationships"]["triggered_by"], ["cron.timer", "cron.socket"])
        self.assertEqual(detail["relationships"]["requires"], ["network.target"])


if __name__ == "__main__":
    unittest.main()

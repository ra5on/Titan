import hashlib
import json
import os
import subprocess
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from titan.app_management import AppMixin
from titan.catalog import compose
from titan.core import Error
from titan.host import Host


AppHost = Host


class AppManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.host = AppHost(self.root / "agent", self.root / "shares", self.root / "vms", self.root / "smb.conf")
        self.host.directory.chmod(0o700)  # Match the systemd StateDirectory.
        self.host.share_root.mkdir()
        self.owner = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        self.owner_patch = patch("titan.host.pwd.getpwnam", return_value=self.owner).start()
        self.calls = []
        self.containers = {}
        self.label_sequence = 0
        self.config_label = ""
        self.pulled = set()
        self.fail_up = False
        self.runner = patch("titan.host.run", side_effect=self.command).start()
        self.binary = patch("titan.app_management.shutil.which", return_value="/usr/bin/docker").start()
        self.logs = patch.object(self.host, "_app_logs", return_value="stdout ready\nstderr warning\n").start()
        self.volumes = patch.object(self.host.volume_manager, "required_path", return_value=None).start()
        self.selinux = patch.object(self.host, "_app_selinux_active", return_value=False).start()

    def tearDown(self):
        patch.stopall()
        self.temp.cleanup()

    def command(self, arguments, **kwargs):
        self.calls.append(arguments)
        if arguments[:2] == ["docker", "ps"]:
            return "\n".join(json.dumps({"ID": item["Id"], "Names": item["Name"].lstrip("/")}) for item in self.containers.values())
        if arguments[:2] == ["docker", "inspect"]:
            return json.dumps([next(item for item in self.containers.values() if item["Id"] == arguments[-1])])
        if arguments[0] == "chcon":
            self.config_label = arguments[-2]
            return ""
        if arguments[:2] == ["docker", "compose"] and "-f" in arguments:
            app = arguments[3][6:]
            command = arguments[6]
            if command == "create" and self.fail_up:
                raise Error("port already allocated")
            if command in ("up", "create"):
                if app not in self.containers or ("--no-recreate" not in arguments and ("--force-recreate" in arguments or app in self.pulled)):
                    self.make_container(app, "running" if command == "up" else "created")
                    self.pulled.discard(app)
            if command == "pull":
                self.pulled.add(app)
            if command in ("start", "restart") and app in self.containers:
                self.containers[app]["State"]["Status"] = "running"
            if command == "stop" and app in self.containers:
                self.containers[app]["State"]["Status"] = "exited"
            if command == "down":
                self.containers.pop(app, None)
            return "operation complete"
        if arguments[0] == "tar":
            Path(arguments[2]).write_bytes(b"config backup")
        return ""

    def make_container(self, app="jellyfin", state="running"):
        self.label_sequence += 1
        record = next(item for item in self.host.load("apps", []) if item["id"] == app)
        service = compose(app, str(self.host.directory / "apps" / app), self.owner.pw_uid, self.owner.pw_gid,
                          record["port"], record["data"], self.host._app_options(app))["services"][app]
        bindings = {}
        for publication in service["ports"]:
            published, target = publication.split(":")
            if "/" not in target:
                target += "/tcp"
            bindings[target] = [{"HostIp": "", "HostPort": published}]
        item = {"Id": "a" * 64 if app == "jellyfin" else hashlib.sha256(app.encode()).hexdigest(), "Name": "/titan-" + app,
                "MountLabel": f"system_u:object_r:container_file_t:s0:c10,c{20+self.label_sequence}",
                "Config": {"Image": service["image"], "Env": ["SECRET=hidden"],
                           "Labels": {**service["labels"], "com.docker.compose.project": "titan-" + app,
                                      "com.docker.compose.service": app}},
                "Mounts": [{"Type": "bind", "Source": binding["source"], "Destination": binding["target"]} for binding in service["volumes"]],
                "HostConfig": {"Privileged": False, "NetworkMode": "titan-" + app + "_default",
                               "PortBindings": bindings},
                "State": {"Status": state, "ExitCode": 0, "Error": "", "Health": {"Status": "healthy"}},
                "RestartCount": 2, "NetworkSettings": {"Ports": {"8096/tcp": [{"HostIp": "0.0.0.0", "HostPort": str(record["port"])}]}}}
        self.containers[app] = item
        return item

    def install(self, app="jellyfin", port=8096):
        self.host.op_app_install(app, port)
        self.calls.clear()

    def compose_commands(self):
        return [item[6:] for item in self.calls if item[:2] == ["docker", "compose"] and "-f" in item and item[6:] != ["config","--quiet"]]

    def test_device_edit_requires_stopped_app_and_preserves_data(self):
        self.install()
        marker=Path(self.host.load("apps",[])[0]["data"])/"keep.txt"
        marker.write_text("keep")
        with self.assertRaises(Error):self.host.op_app_hardware("jellyfin",[])
        self.assertFalse(any("--force-recreate" in call for call in self.calls))
        self.host.op_app_action("jellyfin","stop");self.calls.clear()
        self.host.op_app_hardware("jellyfin",[])
        self.assertEqual(marker.read_text(),"keep")
        self.assertEqual(self.containers["jellyfin"]["State"]["Status"],"created")
        self.assertEqual(self.host.load("apps",[])[0]["hardware"],[])
        self.assertNotIn(["start"],self.compose_commands())

    def test_device_edit_restores_configuration_on_recreate_failure(self):
        self.install();self.host.op_app_action("jellyfin","stop")
        path=self.host.directory/"apps/jellyfin/compose.json";old=path.read_bytes()
        real=self.command;failed=False
        def command(args,**kwargs):
            nonlocal failed
            if "--force-recreate" in args and not failed:
                failed=True;raise Error("failed")
            return real(args,**kwargs)
        self.runner.side_effect=command
        with self.assertRaisesRegex(Error,"vorherige Konfiguration wiederhergestellt"):
            self.host.op_app_hardware("jellyfin",[])
        self.assertEqual(path.read_bytes(),old)
        self.assertEqual(self.containers["jellyfin"]["State"]["Status"],"created")

    def enable_selinux(self):
        self.selinux.return_value = True
        patch("titan.app_management.os.getxattr", side_effect=lambda descriptor, attribute: (self.config_label + "\0").encode()).start()

    def label_commands(self):
        return [item for item in self.calls if item[0] == "chcon"]

    def test_failed_install_is_visible_and_start_retries_without_data_loss(self):
        self.fail_up = True
        with self.assertRaises(Error):
            self.host.op_app_install("jellyfin", 8096)
        record = self.host.load("apps", [])[0]
        self.assertEqual(record["phase"], "failed")
        self.assertIn("port already allocated", record["last_error"])
        marker = Path(record["data"]) / "keep.txt"
        marker.write_text("kept")
        listing = self.host.op_apps()["installed"][0]
        self.assertEqual(listing["state"], "missing")
        self.fail_up = False
        self.host.op_app_action("jellyfin", "start")
        self.assertEqual(self.host.load("apps", [])[0]["phase"], "ready")
        self.assertEqual(self.host.load("apps", [])[0]["last_error"], "")
        self.assertEqual(marker.read_text(), "kept")
        self.assertEqual(len(self.host.load("apps", [])), 1)

    def test_duplicate_failed_app_does_not_replace_definition(self):
        self.fail_up = True
        with self.assertRaises(Error): self.host.op_app_install("jellyfin", 8096)
        path = self.host.directory / "apps/jellyfin/compose.json"
        original = path.read_text()
        with self.assertRaises(Error) as result: self.host.op_app_install("jellyfin", 8097)
        self.assertEqual(result.exception.status, 409)
        self.assertEqual(path.read_text(), original)

    def test_backup_does_not_start_stopped_or_missing_container(self):
        self.install()
        for state in ("exited", None):
            if state: self.containers["jellyfin"]["State"]["Status"] = state
            else: self.containers.clear()
            self.calls.clear()
            result = self.host.op_app_backup("jellyfin")
            self.assertTrue(result["kept_stopped"])
            self.assertEqual(self.compose_commands(), [])
            self.assertTrue(Path(result["path"]).is_file())

    def test_running_backup_stops_then_restores_running(self):
        self.install()
        result = self.host.op_app_backup("jellyfin")
        self.assertFalse(result["kept_stopped"])
        self.assertEqual(self.compose_commands(), [["stop"], ["create"], ["start"]])
        self.assertEqual(self.containers["jellyfin"]["State"]["Status"], "running")

    def test_failed_archive_removes_partial_file_and_restarts_running_app(self):
        self.install()
        original = self.command
        def fail(arguments, **kwargs):
            if arguments[0] == "tar":
                Path(arguments[2]).write_bytes(b"partial")
                raise Error("backup failed")
            return original(arguments, **kwargs)
        self.runner.side_effect = fail
        with self.assertRaises(Error): self.host.op_app_backup("jellyfin")
        self.assertEqual(list((self.host.directory / "backups").glob("*")), [])
        self.assertEqual(self.containers["jellyfin"]["State"]["Status"], "running")

    def test_update_preserves_stopped_container_and_configuration(self):
        self.install()
        self.containers["jellyfin"]["State"]["Status"] = "exited"
        marker = self.host.directory / "apps/jellyfin/config/settings.xml"
        marker.write_text("persistent settings")
        result = self.host.op_app_action("jellyfin", "update")
        self.assertTrue(result["kept_stopped"])
        self.assertEqual(self.compose_commands(), [["pull"], ["create", "--force-recreate"]])
        self.assertEqual(self.containers["jellyfin"]["State"]["Status"], "created")
        self.assertEqual(marker.read_text(), "persistent settings")

    def test_running_update_keeps_service_running_after_backup(self):
        self.install()
        result = self.host.op_app_action("jellyfin", "update")
        self.assertFalse(result["kept_stopped"])
        self.assertEqual(self.compose_commands(), [["stop"], ["create"], ["start"], ["pull"], ["create"], ["start"]])

    def test_restart_requires_a_container_and_preserves_data(self):
        self.install()
        self.host.op_app_action("jellyfin", "restart")
        self.assertEqual(self.compose_commands(), [["create", "--no-recreate"], ["restart"]])
        self.containers.clear()
        with self.assertRaises(Error) as result: self.host.op_app_action("jellyfin", "restart")
        self.assertEqual(result.exception.status, 409)

    def test_remove_keeps_configuration_and_user_data(self):
        self.install()
        result = self.host.op_app_action("jellyfin", "remove")
        self.assertTrue(result["data_retained"])
        self.assertEqual(self.host.load("apps", []), [])
        self.assertTrue((self.host.directory / "apps/jellyfin/config").is_dir())
        self.assertTrue((self.host.share_root / "apps/jellyfin").is_dir())

    def test_foreign_name_or_missing_compose_label_is_never_operated_or_logged(self):
        self.install()
        for missing in ("io.titan.app", "com.docker.compose.project", "com.docker.compose.service"):
            self.make_container()
            del self.containers["jellyfin"]["Config"]["Labels"][missing]
            self.calls.clear()
            with self.assertRaises(Error): self.host.op_app_action("jellyfin", "remove")
            self.assertEqual(self.compose_commands(), [])
            self.logs.reset_mock()
            details = self.host.op_app_details("jellyfin")
            self.assertEqual(details["app"]["state"], "blocked")
            self.assertEqual(details["logs"], "")
            self.logs.assert_not_called()

    def test_wrong_bind_or_privileged_container_is_never_operated(self):
        self.install()
        self.containers["jellyfin"]["Mounts"][0]["Source"] = "/etc"
        with self.assertRaises(Error): self.host.op_app_action("jellyfin", "stop")
        self.make_container()
        self.containers["jellyfin"]["HostConfig"]["Privileged"] = True
        with self.assertRaises(Error): self.host.op_app_action("jellyfin", "stop")
        self.assertEqual(self.compose_commands(), [])

    def test_altered_compose_privileges_or_image_is_rejected_before_execution(self):
        self.install()
        path = self.host.directory / "apps/jellyfin/compose.json"
        original = path.read_text()
        for change in ({"privileged": True}, {"image": "evil/image"}, {"network_mode": "host"}):
            value = json.loads(original)
            value["services"]["jellyfin"].update(change)
            path.write_text(json.dumps(value))
            with self.assertRaises(Error): self.host.op_app_action("jellyfin", "stop")
        self.assertEqual(self.compose_commands(), [])

    def test_legacy_short_binds_upgrade_without_missing_path_creation(self):
        self.install()
        path = self.host.directory / "apps/jellyfin/compose.json"
        value = json.loads(path.read_text())
        value["services"]["jellyfin"]["volumes"] = [item["source"] + ":" + item["target"] for item in value["services"]["jellyfin"]["volumes"]]
        path.write_text(json.dumps(value))
        self.host.op_app_action("jellyfin", "start")
        self.assertTrue(all(item["bind"]["create_host_path"] is False for item in json.loads(path.read_text())["services"]["jellyfin"]["volumes"]))

    def test_details_show_health_ports_recent_logs_without_environment_secrets(self):
        self.install()
        details = self.host.op_app_details("jellyfin", 40)
        self.assertEqual(details["container"]["health"], "healthy")
        self.assertEqual(details["container"]["restarts"], 2)
        self.assertEqual(details["container"]["ports"][0]["port"], 8096)
        self.assertEqual(details["logs"], "stdout ready\nstderr warning\n")
        self.assertNotIn("SECRET", json.dumps(details))
        self.logs.assert_called_with(self.containers["jellyfin"], 40)
        for invalid in (0, 501, True):
            with self.assertRaises(Error): self.host.op_app_details("jellyfin", invalid)

    def test_logs_failure_keeps_details_available_with_a_warning(self):
        self.install()
        self.logs.side_effect = Error("logs unavailable", 503)
        details = self.host.op_app_details("jellyfin")
        self.assertEqual(details["app"]["state"], "running")
        self.assertEqual(details["warnings"], ["logs unavailable"])

    def test_syncthing_auxiliary_ports_are_reserved_in_both_directions(self):
        self.host.op_app_install("jellyfin", 22000)
        with self.assertRaises(Error): self.host.op_app_install("syncthing", 8384)
        self.host.save("apps", [])
        self.containers.clear()
        self.host.op_app_install("syncthing", 8384)
        for port in (22000, 21027, 5000, 5001, 8384):
            with self.assertRaises(Error): self.host.op_app_install("heimdall", port)

    def test_symlink_default_data_and_config_are_rejected(self):
        (self.host.share_root / "apps").mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        (self.host.share_root / "apps/jellyfin").symlink_to(outside)
        with self.assertRaises(Error): self.host.op_app_install("jellyfin", 8096)
        self.assertEqual(self.host.load("apps", []), [])
        self.assertEqual(list(outside.iterdir()), [])

    def test_log_reader_merges_stderr_and_caps_large_output(self):
        self.install()
        captured = {}
        def logs(arguments, **kwargs):
            captured.update(kwargs)
            self.assertEqual(arguments, ["docker", "logs", "--timestamps", "--tail", "75", "a" * 64])
            kwargs["stdout"].write(b"A" * (600 * 1024) + b"\nfinal stderr message\n")
            return SimpleNamespace(returncode=0)
        with patch("titan.app_management.subprocess.run", side_effect=logs):
            result = AppMixin._app_logs(self.containers["jellyfin"], 75)
        self.assertEqual(captured["stderr"], subprocess.STDOUT)
        self.assertLess(len(result), 512 * 1024 + 100)
        self.assertIn("512 KiB", result)
        self.assertTrue(result.endswith("final stderr message\n"))
        self.assertEqual(captured["timeout"], 30)

    def test_paused_backup_is_rejected_without_accidentally_starting_it(self):
        self.install()
        self.containers["jellyfin"]["State"]["Status"] = "paused"
        with self.assertRaises(Error) as result: self.host.op_app_backup("jellyfin")
        self.assertEqual(result.exception.status, 409)
        self.assertEqual(self.compose_commands(), [])
        self.assertFalse((self.host.directory / "backups").exists())

    def test_failed_pull_keeps_previous_app_running_and_records_failure(self):
        self.install()
        original = self.command
        def failed_pull(arguments, **kwargs):
            if arguments[:2] == ["docker", "compose"] and arguments[-1] == "pull":
                self.calls.append(arguments)
                raise Error("registry unreachable")
            return original(arguments, **kwargs)
        self.runner.side_effect = failed_pull
        with self.assertRaises(Error): self.host.op_app_action("jellyfin", "update")
        self.assertEqual(self.containers["jellyfin"]["State"]["Status"], "running")
        self.assertEqual(self.host.load("apps", [])[0]["last_error"], "registry unreachable")
        self.assertEqual(self.compose_commands(), [["stop"], ["create"], ["start"], ["pull"]])

    def test_data_replaced_with_symlink_cannot_start_or_restart(self):
        self.install()
        data = self.host.share_root / "apps/jellyfin"
        outside = self.root / "outside-data"
        data.rename(outside)
        data.symlink_to(outside)
        for action in ("start", "restart", "backup", "update"):
            with self.assertRaises(Error): self.host.op_app_action("jellyfin", action)
        self.assertEqual(self.calls, [])

    def test_altered_published_port_is_not_mistaken_for_a_managed_container(self):
        self.install()
        self.containers["jellyfin"]["HostConfig"]["PortBindings"]["8096/tcp"][0]["HostPort"] = "9999"
        with self.assertRaises(Error): self.host.op_app_action("jellyfin", "restart")
        self.assertEqual(self.compose_commands(), [])
        details = self.host.op_app_details("jellyfin")
        self.assertEqual(details["app"]["state"], "blocked")
        self.assertIsNone(details["container"])

    def test_private_install_options_are_persistent_owner_only_and_absent_from_api_records(self):
        secret = "Example$HOMEPassword123"
        self.host.op_app_install("code-server", 8443, options={"password": secret})
        options_path = self.host.directory / "apps/code-server/options.json"
        self.assertEqual(options_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(options_path.read_text()), {"password": secret})
        self.assertNotIn(secret, json.dumps(self.host.op_apps()))
        self.assertNotIn(secret, json.dumps(self.host.op_app_details("code-server")))
        self.host.op_app_action("code-server", "restart")
        self.assertEqual(json.loads(options_path.read_text())["password"], secret)

    def test_missing_or_unknown_auth_fields_fail_before_docker_and_directory_creation(self):
        for options in (None, {}, {"password": "short"}, {"password": "long-password-123", "SUDO_PASSWORD": "root"}):
            with self.subTest(options=options), self.assertRaises(Error):
                self.host.op_app_install("code-server", 8443, options=options)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.host.directory / "apps").exists())

    def test_custom_peer_ports_are_reserved_across_apps_and_match_runtime_container(self):
        self.host.op_app_install("qbittorrent", 12300, options={"peer_port": 12400})
        record = self.host.managed_app("qbittorrent")
        self.assertEqual(self.host._app_container("qbittorrent", record)["HostConfig"]["PortBindings"]["12400/udp"][0]["HostPort"], "12400")
        self.calls.clear()
        with self.assertRaises(Error) as caught:
            self.host.op_app_install("transmission", 9091, options={"password": "long-password-123", "peer_port": 12400})
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.host.directory / "apps/transmission").exists())
        self.containers["qbittorrent"]["HostConfig"]["PortBindings"]["12400/udp"][0]["HostPort"] = "12401"
        with self.assertRaises(Error):
            self.host.op_app_action("qbittorrent", "restart")
        self.assertEqual(self.compose_commands(), [])

    def test_unsafe_or_missing_private_options_block_app_commands(self):
        self.host.op_app_install("code-server", 8443, options={"password": "long-password-123"})
        path = self.host.directory / "apps/code-server/options.json"
        path.chmod(0o644)
        self.calls.clear()
        with self.assertRaises(Error):
            self.host.op_app_action("code-server", "restart")
        self.assertEqual(self.compose_commands(), [])
        path.unlink()
        path.symlink_to(self.root / "missing")
        with self.assertRaises(Error):
            self.host.op_app_action("code-server", "restart")
        self.assertEqual(self.compose_commands(), [])
        path.unlink()
        with self.assertRaises(Error):
            self.host.op_app_action("code-server", "restart")
        self.assertEqual(self.compose_commands(), [])

    def test_compose_error_passwords_are_redacted_before_jobs_or_public_records(self):
        secret = "Example$TOKENPassword123"
        original = self.command
        def command(args, **kwargs):
            if args[:2] == ["docker", "compose"] and "create" in args:
                raise Error("Rejected PASSWORD=" + secret + " or " + secret.replace("$", "$$"), 503)
            return original(args, **kwargs)
        self.runner.side_effect = command
        with self.assertRaises(Error) as caught:
            self.host.op_app_install("code-server", 8443, options={"password": secret})
        self.assertEqual(caught.exception.status, 503)
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn(secret.replace("$", "$$"), str(caught.exception))
        self.assertIn("[ausgeblendet]", str(caught.exception))
        self.assertNotIn(secret, json.dumps(self.host.load("apps", [])))

    def test_stateless_pairdrop_runtime_and_extra_https_publication_are_supported(self):
        self.host.op_app_install("pairdrop", 3000)
        self.assertEqual(self.containers["pairdrop"]["Mounts"], [])
        self.host.op_app_action("pairdrop", "restart")
        self.host.op_app_install("cops", 8094, options={"https_port": 9444})
        record = self.host.managed_app("cops")
        self.assertEqual(self.host._app_container("cops", record)["HostConfig"]["PortBindings"]["443/tcp"][0]["HostPort"], "9444")
        self.calls.clear()
        with self.assertRaises(Error):
            self.host.op_app_install("heimdall", 9444)
        self.assertEqual(self.calls, [])

    def test_selinux_install_creates_and_privately_labels_before_first_start(self):
        self.enable_selinux()
        self.host.op_app_install("heimdall", 18080)
        label = self.containers["heimdall"]["MountLabel"]
        command = ["chcon", "--recursive", "--no-dereference", "-P", "--", label,
                   str(self.host.directory / "apps/heimdall/config")]
        self.assertEqual(self.label_commands(), [command])
        create = next(index for index, item in enumerate(self.calls) if item[:2] == ["docker", "compose"] and item[6:7] == ["create"])
        start = next(index for index, item in enumerate(self.calls) if item[:2] == ["docker", "compose"] and item[6:7] == ["start"])
        self.assertLess(create, self.calls.index(command))
        self.assertLess(self.calls.index(command), start)
        self.assertEqual(self.containers["heimdall"]["State"]["Status"], "running")
        definition = json.loads((self.host.directory / "apps/heimdall/compose.json").read_text())
        self.assertFalse(definition["services"]["heimdall"]["volumes"][0]["bind"]["create_host_path"])

    def test_private_label_rejects_missing_public_malformed_or_other_type_before_mutation(self):
        self.install()
        self.enable_selinux()
        record = self.host.managed_app("jellyfin")
        invalid = (None, "", "system_u:object_r:container_file_t:s0", "system_u:object_r:var_lib_t:s0:c1,c2",
                   "other_u:object_r:container_file_t:s0:c1,c2", "system_u:object_r:container_file_t:s0:c1,c1024",
                   "system_u:object_r:container_file_t:s0:c1,c1", "system_u:object_r:container_file_t:s0:c01,c2",
                   "system_u:object_r:container_file_t:s0:c١,c٢", "system_u:object_r:container_file_t:s0:c1,c2\nprivate")
        for label in invalid:
            with self.subTest(label=label):
                self.containers["jellyfin"]["MountLabel"] = label
                self.calls.clear()
                with self.assertRaises(Error) as caught:
                    self.host._app_private_config_label("jellyfin", record)
                self.assertEqual(caught.exception.status, 503)
                self.assertEqual(self.label_commands(), [])
                self.assertEqual(self.compose_commands(), [])

    def test_selinux_restart_stops_existing_writer_before_relabel_and_restarts(self):
        self.install()
        self.enable_selinux()
        original = self.containers["jellyfin"]
        self.pulled.add("jellyfin")
        self.host.op_app_action("jellyfin", "restart")
        self.assertEqual(self.compose_commands(), [["create", "--no-recreate"], ["stop"], ["restart"]])
        self.assertIs(self.containers["jellyfin"], original)
        stop = next(index for index, item in enumerate(self.calls) if item[:2] == ["docker", "compose"] and item[6:7] == ["stop"])
        restart = next(index for index, item in enumerate(self.calls) if item[:2] == ["docker", "compose"] and item[6:7] == ["restart"])
        label = self.calls.index(self.label_commands()[0])
        self.assertLess(stop, label)
        self.assertLess(label, restart)
        self.assertEqual(self.containers["jellyfin"]["State"]["Status"], "running")

    def test_both_update_states_use_new_container_mcs_without_starting_stopped_app(self):
        for stopped in (False, True):
            with self.subTest(stopped=stopped):
                self.selinux.return_value = False
                if not self.host.load("apps", []): self.install()
                self.enable_selinux()
                if stopped: self.containers["jellyfin"]["State"]["Status"] = "exited"
                initial = self.containers["jellyfin"]["MountLabel"]
                marker = self.host.directory / "apps/jellyfin/config/keep.txt"
                marker.write_text("persistent config")
                self.calls.clear()
                result = self.host.op_app_action("jellyfin", "update")
                current = self.containers["jellyfin"]["MountLabel"]
                self.assertNotEqual(initial, current)
                self.assertEqual(self.label_commands()[-1][-2], current)
                self.assertEqual(result["kept_stopped"], stopped)
                self.assertEqual(self.containers["jellyfin"]["State"]["Status"], "created" if stopped else "running")
                if stopped: self.assertFalse(any(item[0] in ("start", "restart") for item in self.compose_commands()))
                self.assertEqual(marker.read_text(), "persistent config")

    def test_running_backup_restores_private_config_and_original_container_label(self):
        self.enable_selinux()
        self.install()
        initial = self.containers["jellyfin"]["MountLabel"]
        self.host.op_app_backup("jellyfin")
        self.assertEqual(self.label_commands()[-1][-2], initial)
        self.assertEqual(self.containers["jellyfin"]["State"]["Status"], "running")

    def test_label_command_failure_or_label_not_applied_prevents_start(self):
        self.install()
        self.containers["jellyfin"]["State"]["Status"] = "exited"
        self.enable_selinux()
        original = self.command
        def fail_label(arguments, **kwargs):
            if arguments[0] == "chcon":
                self.calls.append(arguments)
                raise Error("chcon permission denied", 503)
            return original(arguments, **kwargs)
        self.runner.side_effect = fail_label
        with self.assertRaises(Error): self.host.op_app_action("jellyfin", "start")
        self.assertEqual(self.compose_commands(), [["create"]])
        self.assertEqual(self.host.load("apps", [])[0]["phase"], "failed")
        self.assertEqual(self.containers["jellyfin"]["State"]["Status"], "exited")
        self.runner.side_effect = original
        self.calls.clear()
        with patch("titan.app_management.os.getxattr", return_value=b"system_u:object_r:var_lib_t:s0"):
            with self.assertRaises(Error): self.host.op_app_action("jellyfin", "start")
        self.assertEqual(self.compose_commands(), [["create"]])

    def test_config_root_symlink_or_writable_parent_is_rejected_without_outside_labels(self):
        self.install()
        self.enable_selinux()
        config = self.host.directory / "apps/jellyfin/config"
        outside = self.root / "outside-config"
        config.rename(outside)
        config.symlink_to(outside)
        record = self.host.load("apps", [])[0]
        with self.assertRaises(Error): self.host._app_private_config_label("jellyfin", record)
        self.assertEqual(self.label_commands(), [])
        config.unlink()
        outside.rename(config)
        self.calls.clear()
        (self.host.directory / "apps").chmod(0o777)
        with self.assertRaises(Error): self.host._app_private_config_label("jellyfin", record)
        self.assertEqual(self.label_commands(), [])

    def test_config_hardlink_is_rejected_and_nested_symlink_is_not_traversed(self):
        self.install()
        self.containers["jellyfin"]["State"]["Status"] = "exited"
        self.enable_selinux()
        config = self.host.directory / "apps/jellyfin/config"
        outside = self.root / "outside-file"
        outside.write_text("outside data")
        os.link(outside, config / "hardlink")
        with self.assertRaises(Error) as caught: self.host.op_app_action("jellyfin", "start")
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(self.label_commands(), [])
        (config / "hardlink").unlink()
        outside_symlink = self.root / "outside-symlink"
        outside_symlink.symlink_to(outside)
        outside_fifo = self.root / "outside-fifo"
        os.mkfifo(outside_fifo)
        for source in (outside_symlink, outside_fifo):
            with self.subTest(kind=source.name):
                os.link(source, config / "hardlink", follow_symlinks=False)
                with self.assertRaises(Error) as caught: self.host.op_app_action("jellyfin", "start")
                self.assertEqual(caught.exception.status, 403)
                self.assertEqual(self.label_commands(), [])
                (config / "hardlink").unlink()
        (config / "symlink").symlink_to(outside)
        self.host.op_app_action("jellyfin", "start")
        self.assertIn("--no-dereference", self.label_commands()[-1])
        self.assertIn("-P", self.label_commands()[-1])
        self.assertEqual(outside.read_text(), "outside data")

    def test_replaced_config_inode_after_labeling_is_rejected_before_start(self):
        self.install()
        self.containers["jellyfin"]["State"]["Status"] = "exited"
        self.enable_selinux()
        config = self.host.directory / "apps/jellyfin/config"
        original = self.command
        def replace(arguments, **kwargs):
            result = original(arguments, **kwargs)
            if arguments[0] == "chcon":
                config.rename(self.root / "old-config")
                config.mkdir()
            return result
        self.runner.side_effect = replace
        with self.assertRaises(Error) as caught: self.host.op_app_action("jellyfin", "start")
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.compose_commands(), [["create"]])

    def test_inactive_selinux_and_stateless_recipe_do_not_require_private_labels(self):
        self.install()
        self.containers["jellyfin"]["MountLabel"] = ""
        self.host.op_app_action("jellyfin", "start")
        self.assertEqual(self.label_commands(), [])
        self.enable_selinux()
        self.host.op_app_install("pairdrop", 3000)
        self.assertEqual(self.label_commands(), [])


if __name__ == "__main__":
    unittest.main()

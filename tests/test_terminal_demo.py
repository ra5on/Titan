import base64
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from titan.core import Error
from titan.demo import Demo
from titan.demo_terminal import FakeTerminalManager, MAX_INPUT, MAX_OUTPUT, PROMPT
from titan.service_manager import CUSTOM_PREFIX, PROTECTED_SERVICES, ServiceManagerMixin


class FakeTerminalTests(unittest.TestCase):
    def setUp(self):
        self.manager = FakeTerminalManager()
        self.owner = "demo.random-session-token"

    def tearDown(self):
        self.manager.close_all()

    def create(self):
        result = self.manager.create(self.owner, 100, 30)
        self.assertRegex(result["id"], r"^[a-f0-9]{64}$")
        self.assertFalse(result["exited"])
        self.assertIsNone(result["exit_code"])
        return result["id"]

    def read(self, session_id):
        result = self.manager.poll(self.owner, session_id)
        return base64.b64decode(result["data"]), result

    def write(self, session_id, data):
        return self.manager.write(self.owner, session_id, base64.b64encode(data).decode())

    def test_initial_output_labels_demo_and_does_not_expose_session_owner(self):
        session = self.create()
        data, result = self.read(session)
        self.assertIn(b"DEMO", data)
        self.assertIn(b"simuliert", data)
        self.assertIn(PROMPT.encode(), data)
        self.assertNotIn(self.owner.encode(), data)
        self.assertFalse(result["eof"])
        self.assertEqual(self.read(session)[0], b"")

    def test_fixed_commands_and_shell_constructs_are_literal_without_host_calls(self):
        session = self.create()
        self.read(session)
        with patch("subprocess.run", side_effect=AssertionError("Host command")), \
                patch("subprocess.Popen", side_effect=AssertionError("Host process")), \
                patch("os.system", side_effect=AssertionError("Host shell")), \
                patch("os.openpty", side_effect=AssertionError("Host PTY")):
            self.write(session, b"pwd\rwhoami\rhelp\rdate\rclear\recho '$(touch /tmp/forbidden); $HOME > /tmp/forbidden'\rsudo reboot\r")
            data, result = self.read(session)
        self.assertIn(b"/home/demo\r\n", data)
        self.assertIn(b"demo\r\n", data)
        self.assertIn(b"Keine Shell", data)
        self.assertRegex(data, rb"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC")
        self.assertIn(b"\x1b[2J\x1b[H", data)
        self.assertIn(b"$(touch /tmp/forbidden); $HOME > /tmp/forbidden\r\n", data)
        self.assertIn(b"Nur feste Beispielbefehle", data)
        self.assertFalse(result["eof"])

    def test_split_utf8_and_bracketed_paste_are_not_corrupted(self):
        session = self.create(); self.read(session)
        text = "echo ä😀\r".encode()
        offset = text.index("😀".encode()) + 1
        self.write(session, b"\x1b[200~" + text[:offset])
        self.write(session, text[offset:] + b"\x1b[201~")
        data, _ = self.read(session)
        self.assertIn("ä😀\r\n".encode(), data)
        self.assertNotIn("�".encode(), data)
        self.assertNotIn(b"[200~", data)
        self.assertNotIn(b"[201~", data)

    def test_backspace_interrupt_and_crlf_have_terminal_semantics(self):
        session = self.create(); self.read(session)
        self.write(session, b"echo unexecuted\x03echo worle\x7fd\r\n")
        data, _ = self.read(session)
        self.assertIn(b"^C\r\n", data)
        self.assertIn(b"world\r\n", data)
        self.assertNotIn(b"unexecuted\r\n", data)
        self.assertEqual(data.count(PROMPT.encode()), 2)

    def test_exit_retains_tail_until_poll_and_then_marks_eof(self):
        session = self.create(); self.read(session)
        self.write(session, b"echo retained\rexit\r")
        data, result = self.read(session)
        self.assertIn(b"retained\r\n", data)
        self.assertTrue(result["eof"])
        self.assertTrue(result["exited"])
        self.assertEqual(result["exit_code"], 0)
        with self.assertRaises(Error) as failed:
            self.write(session, b"echo must not run\r")
        self.assertEqual(failed.exception.status, 409)
        self.assertTrue(self.manager.close(self.owner, session)["closed"])
        with self.assertRaises(Error):
            self.read(session)

    def test_owner_is_bound_for_poll_write_resize_and_close(self):
        session = self.create()
        for operation in (lambda: self.manager.poll("other", session),
                          lambda: self.manager.write("other", session, ""),
                          lambda: self.manager.resize("other", session, 80, 24),
                          lambda: self.manager.close("other", session)):
            with self.subTest(operation=operation), self.assertRaises(Error) as result:
                operation()
            self.assertEqual(result.exception.status, 404)
        self.assertIn(b"DEMO", self.read(session)[0])
        self.assertEqual(self.manager.resize(self.owner, session, 91, 27)["rows"], 27)

    def test_dimensions_base64_timeout_and_capacity_are_bounded(self):
        for dimensions in ((True, 24), (80, 0), (501, 24), (80, "24")):
            with self.subTest(dimensions=dimensions), self.assertRaises(Error):
                self.manager.create(self.owner, *dimensions)
        for owner in (None, "", "x\nsecret"):
            with self.assertRaises(Error): self.manager.create(owner)
        first = self.create(); self.create()
        with self.assertRaises(Error) as result: self.create()
        self.assertEqual(result.exception.status, 429)
        self.manager.create("second"); self.manager.create("third")
        with self.assertRaises(Error): self.manager.create("fourth")
        for timeout in (-1, 1.1, True, float("nan")):
            with self.assertRaises(Error): self.manager.poll(self.owner, first, timeout)
        with self.assertRaises(Error): self.manager.write(self.owner, first, "not base64!")
        with self.assertRaises(Error): self.write(first, b"x" * (MAX_INPUT + 1))
        self.manager.close_all()
        with self.assertRaises(Error): self.create()

    def test_output_tail_larger_than_one_chunk_is_retained_and_bounded(self):
        session = self.create(); self.read(session)
        for _ in range(10):
            self.write(session, b"echo " + b"a" * 8190 + b"\r")
        self.write(session, b"exit\r")
        total = bytearray()
        for _ in range(8):
            data, result = self.read(session)
            self.assertLessEqual(len(data), MAX_OUTPUT)
            total.extend(data)
            if result["eof"]: break
        self.assertTrue(result["eof"])
        self.assertIn(b"Demo-Terminal beendet", total)


class DemoServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.demo = Demo(Path(self.temporary.name) / "files")

    def tearDown(self):
        self.demo.terminals.close_all()
        self.demo._temporary.cleanup()
        self.temporary.cleanup()

    def test_inventory_matches_host_schema_and_protects_titan_access(self):
        result = self.demo.call("services")
        self.assertEqual(set(result), {"items", "users", "total", "truncated", "custom_prefix", "counts"})
        self.assertEqual(result["counts"]["total"], result["total"])
        self.assertEqual(result["counts"]["active"], sum(item["active"] == "active" for item in result["items"]))
        self.assertEqual(result["total"], 8)
        self.assertEqual(result["users"][0]["name"], "titan-files")
        expected = ServiceManagerMixin._service_summary("example.service", {"example.service": {"state":"enabled"}}, {})
        for item in result["items"]:
            self.assertEqual(set(item), set(expected))
            self.assertIn("Demo", item["description"])
            self.assertEqual(item["protected"], item["name"] in PROTECTED_SERVICES)
            if item["protected"]:
                self.assertEqual(item["allowed_actions"], ["start", "enable"])
                self.assertTrue(item["protected_reason"])
        ssh = next(item for item in result["items"] if item["name"] == "ssh.service")
        self.assertFalse(ssh["enabled"])
        self.assertEqual(ssh["active"], "inactive")
        result["items"][0]["allowed_actions"].clear()
        self.assertTrue(self.demo.call("services")["items"][0]["allowed_actions"])

    def test_service_actions_change_only_simulated_state_and_logs(self):
        with patch("titan.host.run", side_effect=AssertionError("Host command")), \
                patch("subprocess.run", side_effect=AssertionError("Host command")), \
                patch("subprocess.Popen", side_effect=AssertionError("Host process")):
            disabled = self.demo.call("service_action", service="docker.service", command="disable")
            self.assertFalse(disabled["service"]["enabled"])
            self.assertEqual(disabled["service"]["active"], "active")
            stopped = self.demo.call("service_action", service="docker.service", command="stop")
            self.assertEqual(stopped["service"]["active"], "inactive")
            self.assertFalse(self.demo.call("status")["services"]["docker"])
            self.assertFalse(self.demo.call("components")["components"]["docker"]["available"])
            self.assertFalse(self.demo.call("monitoring")["services"]["docker"]["active"])
            details = self.demo.call("service_details", service="docker.service", tail=1)
            self.assertIn("stop simuliert", details["logs"])
            self.assertEqual(details["service"]["properties"]["MainPID"], "0")
            self.assertEqual(self.demo.call("service_details", service="docker.service", tail=0)["logs"], "")
            self.demo.call("service_action", service="docker.service", command="restart")
            self.assertTrue(self.demo.call("status")["services"]["docker"])
            self.demo.call("service_action", service="docker.service", command="enable")
            self.assertTrue(self.demo.call("service_details", service="docker.service")["service"]["enabled"])

    def test_protected_service_actions_and_invalid_names_leave_state_untouched(self):
        before = copy.deepcopy(self.demo.services)
        for name in PROTECTED_SERVICES:
            for command in ("stop", "restart", "disable"):
                with self.assertRaises(Error) as result:
                    self.demo.call("service_action", service=name, command=command)
                self.assertEqual(result.exception.status, 403)
        for name in ("../docker.service", "--force.service", "docker.service\n", "docker", None):
            with self.assertRaises(Error): self.demo.call("service_details", service=name)
        for command in (None, "reboot", "stop; reboot"):
            with self.assertRaises(Error): self.demo.call("service_action", service="docker.service", command=command)
        with self.assertRaises(Error): self.demo.call("service_details", service="absent.service")
        self.assertEqual(self.demo.services, before)

    def test_custom_service_create_is_in_memory_and_never_reads_or_runs_program(self):
        sentinel = Path(self.temporary.name) / "sentinel"
        sentinel.write_text("preserved")
        arguments = {"name":"demo-worker", "description":"A demo worker", "program":"/not/an/existing/program",
                     "args":"'$(touch /tmp/nope)' ';' '$HOME'", "user":"root", "working_directory":"/imaginary/demo",
                     "autostart":True, "start":True}
        with patch("titan.host.run", side_effect=AssertionError("Host command")), \
                patch("titan.service_manager.pwd.getpwnam", side_effect=AssertionError("Host user lookup")), \
                patch("titan.service_manager.pwd.getpwall", side_effect=AssertionError("Host user inventory")), \
                patch("subprocess.run", side_effect=AssertionError("Host command")), \
                patch("subprocess.Popen", side_effect=AssertionError("Host process")):
            created = self.demo.call("service_create", **arguments)
        self.assertTrue(created["ok"])
        self.assertEqual(created["service"], CUSTOM_PREFIX + "demo-worker.service")
        details = self.demo.call("service_details", service=created["service"])
        self.assertTrue(details["service"]["custom"])
        self.assertTrue(details["service"]["enabled"])
        self.assertEqual(details["service"]["active"], "active")
        self.assertIn("Kein Programm wurde ausgeführt", details["logs"])
        self.assertEqual(sentinel.read_text(), "preserved")
        self.assertFalse(list(Path(self.temporary.name).rglob("*.service")))
        with self.assertRaises(Error) as duplicate:
            self.demo.call("service_create", **arguments)
        self.assertEqual(duplicate.exception.status, 409)

    def test_service_create_validation_and_unknown_fields_do_not_add_records(self):
        valid = {"name":"worker", "description":"Worker", "program":"/usr/bin/sleep"}
        variants = [{"name":"../worker"}, {"description":"bad\nExecStart=/bin/bash"}, {"description":" trailing "},
                    {"program":"sleep"}, {"program":"/usr/bin/../bin/sleep"}, {"args":"'unclosed"},
                    {"args":" ".join("x" for _ in range(129))}, {"user":"unknown"},
                    {"working_directory":"relative"}, {"working_directory":"/bad\npath"},
                    {"autostart":1}, {"start":"yes"}]
        count = len(self.demo.services)
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(Error):
                self.demo.call("service_create", **{**valid, **variant})
        self.assertEqual(len(self.demo.services), count)

    def test_demo_terminal_dispatch_and_system_file_fixture_stay_isolated(self):
        before = (self.demo._system_path / "etc/hostname").read_text()
        with patch("subprocess.Popen", side_effect=AssertionError("Host process")), \
                patch("subprocess.run", side_effect=AssertionError("Host command")), \
                patch("titan.host.run", side_effect=AssertionError("Host command")):
            created = self.demo.call("terminal_create", owner="demo.token", cols=80, rows=24)
            session = created["id"]
            self.demo.call("terminal_write", owner="demo.token", id=session, data=base64.b64encode(b"echo safe\rrm -rf /\r").decode())
            result = self.demo.call("terminal_poll", owner="demo.token", id=session, timeout=0.1)
            self.assertIn(b"safe\r\n", base64.b64decode(result["data"]))
            self.demo.call("terminal_resize", owner="demo.token", id=session, cols=91, rows=27)
            self.assertTrue(self.demo.call("terminal_close", owner="demo.token", id=session)["closed"])
        self.assertEqual((self.demo._system_path / "etc/hostname").read_text(), before)
        self.assertTrue((self.demo.directory / "Willkommen.txt").is_file())
        with self.assertRaises(Error): self.demo.call("terminal_unknown", owner="demo.token")


if __name__ == "__main__":
    unittest.main()

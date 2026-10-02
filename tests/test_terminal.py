import base64
import errno
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from titan.core import Error
from titan.terminal import MAX_INPUT, MAX_OUTPUT, SAFE_PATH, TerminalManager


@unittest.skipIf(os.geteuid() == 0, "Interactive tests only run as an unprivileged workstation user")
class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.manager = TerminalManager(cwd=self.temporary.name, sweep_interval=0.05)

    def tearDown(self):
        self.manager.close_all()
        self.temporary.cleanup()

    def write(self, session_id, data, owner="administrator"):
        return self.manager.write(owner, session_id, base64.b64encode(data).decode())

    def read_until(self, session_id, marker, timeout=4, owner="administrator"):
        data = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.manager.poll(owner, session_id, timeout=0.1)
            data.extend(base64.b64decode(value["data"]))
            if marker in data:
                return bytes(data)
            if value["exited"]:
                break
        self.fail("Terminal output did not contain expected test marker: " + repr(bytes(data)))

    def create(self, owner="administrator", **options):
        created = self.manager.create(owner, **options)
        session_id = created["id"]
        self.read_until(session_id, b"$ ", owner=owner)
        self.write(session_id, b"stty -echo\n", owner=owner)
        self.read_until(session_id, b"$ ", owner=owner)
        return session_id

    def stopped(self, pid):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
                if fields[0] == "Z":
                    return
            except FileNotFoundError:
                return
            time.sleep(0.02)
        self.fail("Disposable terminal child is still running")

    def test_interactive_pty_shell_keeps_state_and_reports_dimensions(self):
        session_id = self.create(cols=91, rows=27)
        self.write(session_id, b"test -t 0 && test -t 1 && VALUE=retained\n")
        self.read_until(session_id, b"$ ")
        self.write(session_id, b"printf '__VALUE__%s\\n' \"$VALUE\"; stty size\n")
        output = self.read_until(session_id, b"27 91")
        self.assertIn(b"__VALUE__retained", output)
        self.assertNotIn(b"no job control", output)
        self.assertRegex(session_id, r"^[a-f0-9]{64}$")
        self.assertEqual(len(bytes.fromhex(session_id)), 32)

    def test_startup_ignores_host_environment_and_shell_profiles(self):
        startup = Path(self.temporary.name) / "startup"
        marker = Path(self.temporary.name) / "startup-ran"
        startup.write_text("touch startup-ran\n")
        (Path(self.temporary.name) / ".bashrc").write_text("touch startup-ran\n")
        (Path(self.temporary.name) / ".bash_profile").write_text("touch startup-ran\n")
        with patch.dict(os.environ, {"BASH_ENV": str(startup), "ENV": str(startup),
                                    "PATH": self.temporary.name, "RA_TERMINAL_TEST": "private-marker"}):
            session_id = self.create()
        self.write(session_id, b"printf '__ENV__%s:%s:%s\\n' \"$TERM\" \"$PATH\" \"${RA_TERMINAL_TEST-unset}\"\n")
        output = self.read_until(session_id, b":unset")
        self.assertIn(("__ENV__xterm-256color:" + SAFE_PATH + ":unset").encode(), output)
        self.assertFalse(marker.exists())

    def test_every_operation_checks_owner_and_unknown_ids(self):
        session_id = self.create()
        for owner, token in (("other-administrator", session_id), ("administrator", "unknown")):
            operations = (lambda: self.manager.poll(owner, token),
                          lambda: self.manager.write(owner, token, "eA=="),
                          lambda: self.manager.resize(owner, token, 80, 24),
                          lambda: self.manager.close(owner, token))
            for operation in operations:
                with self.assertRaises(Error) as failure:
                    operation()
                self.assertEqual(failure.exception.status, 404)
        self.write(session_id, b"printf '__STILL_OWNED__\\n'\n")
        self.read_until(session_id, b"__STILL_OWNED__")

    def test_global_and_per_owner_session_limits_release_after_close(self):
        sessions = [self.manager.create("one")["id"], self.manager.create("one")["id"]]
        with self.assertRaises(Error) as failure:
            self.manager.create("one")
        self.assertEqual(failure.exception.status, 429)
        sessions.extend([self.manager.create("two")["id"], self.manager.create("three")["id"]])
        with self.assertRaises(Error) as failure:
            self.manager.create("four")
        self.assertEqual(failure.exception.status, 429)
        self.manager.close("one", sessions[0])
        self.assertIn("id", self.manager.create("four"))

    def test_session_being_terminated_still_counts_towards_resource_limit(self):
        self.manager.close_all()
        self.manager = TerminalManager(cwd=self.temporary.name, max_sessions=1)
        session_id = self.create()
        entered = threading.Event()
        release = threading.Event()
        original = self.manager._terminate
        def terminate(session):
            entered.set()
            release.wait(timeout=2)
            original(session)
        with patch.object(self.manager, "_terminate", side_effect=terminate):
            worker = threading.Thread(target=self.manager.close, args=("administrator", session_id))
            worker.start()
            try:
                self.assertTrue(entered.wait(timeout=1))
                with self.assertRaises(Error) as failure:
                    self.manager.create("another-administrator")
                self.assertEqual(failure.exception.status, 429)
            finally:
                release.set()
                worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertIn("id", self.manager.create("another-administrator"))

    def test_ctrl_c_interrupts_foreground_job_and_shell_remains_usable(self):
        session_id = self.create()
        self.write(session_id, b"sleep 30\n")
        time.sleep(0.1)
        self.write(session_id, b"\x03")
        self.read_until(session_id, b"$ ")
        self.write(session_id, b"printf '__INTERRUPTED__\\n'\n")
        self.read_until(session_id, b"__INTERRUPTED__")
        self.assertFalse(self.manager.poll("administrator", session_id)["exited"])

    def test_resize_changes_kernel_dimensions_and_signals_foreground_job(self):
        session_id = self.create()
        self.write(session_id, b"trap 'printf __WINCH__' WINCH\n")
        self.read_until(session_id, b"$ ")
        self.manager.resize("administrator", session_id, 123, 42)
        self.read_until(session_id, b"__WINCH__")
        self.write(session_id, b"stty size\n")
        self.read_until(session_id, b"42 123")

    def test_exit_reports_status_after_draining_final_output(self):
        session_id = self.create()
        self.write(session_id, b"printf '__FINAL__\\n'; exit 17\n")
        output = bytearray()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = self.manager.poll("administrator", session_id, timeout=0.1)
            output.extend(base64.b64decode(result["data"]))
            if result["exited"]:
                break
        self.assertTrue(result["exited"])
        self.assertTrue(result["eof"])
        self.assertEqual(result["exit_code"], 17)
        self.assertIn(b"__FINAL__", output)
        with self.assertRaises(Error) as failure:
            self.write(session_id, b"x")
        self.assertEqual(failure.exception.status, 409)

    def test_large_final_output_is_drained_before_exited_is_reported(self):
        session_id = self.create()
        count = MAX_OUTPUT * 3 + 11
        self.write(session_id, (f"printf '%0{count}d' 0; exit 9\n").encode())
        output = bytearray()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.manager.poll("administrator", session_id, timeout=0.1)
            chunk = base64.b64decode(result["data"])
            self.assertLessEqual(len(chunk), MAX_OUTPUT)
            output.extend(chunk)
            if result["exited"]:
                break
        self.assertTrue(result["exited"])
        self.assertEqual(result["exit_code"], 9)
        self.assertEqual(len(re.search(rb"0{1000,}", output).group()), count)

    def test_input_end_error_does_not_hide_unread_output(self):
        session_id = self.create()
        self.write(session_id, b"printf '__TAIL_PRESERVED__\\n'\n")
        session = self.manager._sessions[session_id]
        session.pending.extend(b"unused")
        with patch("titan.terminal.os.write", side_effect=OSError(errno.EIO, "slave closed")):
            self.manager._flush(session)
        self.assertTrue(session.input_closed)
        self.assertFalse(session.eof)
        self.assertFalse(session.pending)
        self.read_until(session_id, b"__TAIL_PRESERVED__")

    def test_close_terminates_foreground_and_background_process_groups(self):
        session_id = self.create()
        shell = self.manager._sessions[session_id].process
        self.write(session_id, b"sleep 30 & printf '__BG__%s\\n' \"$!\"; sleep 30\n")
        output = self.read_until(session_id, b"__BG__")
        while not re.search(rb"__BG__(\d+)\r?\n", output):
            output += base64.b64decode(self.manager.poll("administrator", session_id, timeout=0.1)["data"])
        background = int(re.search(rb"__BG__(\d+)", output).group(1))
        groups = self.manager._process_groups(self.manager._sessions[session_id])
        self.assertGreaterEqual(len(groups), 2)
        closed = self.manager.close("administrator", session_id)
        self.assertTrue(closed["closed"])
        self.assertIsNotNone(shell.poll())
        self.stopped(background)
        self.assertNotIn(session_id, self.manager._sessions)

    def test_poll_resize_and_empty_input_never_refresh_activity(self):
        session_id = self.create()
        session = self.manager._sessions[session_id]
        activity = session.activity
        self.manager.poll("administrator", session_id, timeout=0.05)
        self.write(session_id, b"")
        self.assertEqual(session.activity, activity)
        self.manager.resize("administrator", session_id, 81, 25)
        self.assertEqual(session.activity, activity)

    def test_daemon_sweeper_removes_abandoned_session_without_polling(self):
        session_id = self.create()
        session = self.manager._sessions[session_id]
        session.activity -= self.manager.idle_ttl + 1
        deadline = time.monotonic() + 3
        while session_id in self.manager._sessions and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertNotIn(session_id, self.manager._sessions)
        self.stopped(session.process.pid)
        with self.assertRaises(Error):
            self.manager.poll("administrator", session_id)

    def test_maximum_lifetime_applies_even_after_fresh_user_activity(self):
        session_id = self.create()
        session = self.manager._sessions[session_id]
        with session.lock:
            session.created -= self.manager.max_ttl + 1
            session.activity = time.monotonic()
            with self.assertRaises(Error) as failure:
                self.manager.poll("administrator", session_id)
        self.assertEqual(failure.exception.status, 410)
        self.assertNotIn(session_id, self.manager._sessions)
        self.stopped(session.process.pid)

    def test_output_is_bounded_and_backpressure_does_not_drop_bytes(self):
        session_id = self.create()
        count = MAX_OUTPUT * 3 + 37
        # Bash built-in printf emits known bytes without depending on another
        # interpreter or writing a large file to the host.
        self.write(session_id, (f"printf '%0{count}d' 0; printf '__DONE__\\n'\n").encode())
        output = bytearray()
        deadline = time.monotonic() + 5
        while b"__DONE__" not in output and time.monotonic() < deadline:
            result = self.manager.poll("administrator", session_id, timeout=0.1)
            chunk = base64.b64decode(result["data"])
            self.assertLessEqual(len(chunk), MAX_OUTPUT)
            output.extend(chunk)
        self.assertIn(b"__DONE__", output)
        digits = re.search(rb"0{1000,}", output)
        self.assertIsNotNone(digits)
        self.assertEqual(len(digits.group()), count)
        self.assertLessEqual(len(self.manager._sessions[session_id].pending), MAX_INPUT)

    def test_input_and_poll_validation_is_bounded(self):
        session_id = self.create()
        for data in ("!not-base64!", "é", base64.b64encode(b"x" * (MAX_INPUT + 1)).decode(), None):
            with self.assertRaises(Error):
                self.manager.write("administrator", session_id, data)
        for timeout in (-1, 2, float("nan"), float("inf"), True, "1"):
            with self.assertRaises(Error):
                self.manager.poll("administrator", session_id, timeout)
        for cols, rows in ((0, 24), (80, 501), (True, 24), (80, "24")):
            with self.assertRaises(Error):
                self.manager.resize("administrator", session_id, cols, rows)

    def test_input_queue_rejects_overflow_without_accepting_partial_new_input(self):
        session_id = self.create()
        session = self.manager._sessions[session_id]
        session.pending.extend(b"x" * MAX_INPUT)
        with patch("titan.terminal.os.write", side_effect=BlockingIOError(errno.EAGAIN, "full")):
            with self.assertRaises(Error) as failure:
                self.write(session_id, b"new-input")
        self.assertEqual(failure.exception.status, 429)
        self.assertEqual(bytes(session.pending), b"x" * MAX_INPUT)
        session.pending.clear()

    def test_close_all_closes_fds_reaps_shells_and_stops_sweeper(self):
        session_id = self.create()
        session = self.manager._sessions[session_id]
        self.manager.close_all()
        self.assertFalse(self.manager._sweeper.is_alive())
        self.assertIsNotNone(session.process.poll())
        with self.assertRaises(OSError):
            os.fstat(session.master)
        with self.assertRaises(Error) as failure:
            self.manager.create("administrator")
        self.assertEqual(failure.exception.status, 503)
        self.manager.close_all()

    def test_spawn_failure_closes_pty_descriptors_and_maps_error(self):
        real_openpty = os.openpty
        opened = []
        def openpty():
            fds = real_openpty()
            opened.extend(fds)
            return fds
        with patch("titan.terminal.os.openpty", side_effect=openpty), \
                patch("titan.terminal.subprocess.Popen", side_effect=OSError("test failure")):
            with self.assertRaises(Error) as failure:
                self.manager.create("administrator")
        self.assertEqual(failure.exception.status, 503)
        self.assertFalse(self.manager._sessions)
        for fd in opened:
            with self.assertRaises(OSError):
                os.fstat(fd)


if __name__ == "__main__":
    unittest.main()

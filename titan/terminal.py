"""Bounded administrator PTYs owned by the trusted web session identity.

The HTTP layer authorizes the administrator and supplies ``owner`` itself.  No
client-selected executable, environment, working directory or Unix user enters
this module.  Terminal input and output are opaque base64 bytes.
"""

import base64
import binascii
import contextlib
import ctypes
from dataclasses import dataclass, field
import errno
import fcntl
import hmac
import math
import os
from pathlib import Path
import pwd
import secrets
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import time


def _worker(root=False):
    """Run only in the fresh, single-threaded session-leader subprocess."""
    os.umask(0o077)
    # Normal data terminals cannot elevate through setuid programs after the
    # trusted launcher drops UID. Root is a separate, explicit leased worker.
    if not root and ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0) != 0:
        raise SystemExit("Terminal privilege protection could not be enabled")
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    os.tcsetpgrp(0, os.getpgrp())
    os.execve("/bin/bash", ["/bin/bash", "--noprofile", "--norc", "-i"], os.environ)


# An isolated interpreter executes this trusted file by absolute path.  The
# worker needs no package search path, imports no local modules and never uses
# preexec_fn in the multithreaded agent.
if __name__ == "__main__":
    if sys.argv[1:] not in (["--worker"], ["--root-worker"]):
        raise SystemExit("This module is an internal terminal worker.")
    _worker(root=sys.argv[1:] == ["--root-worker"])
    raise SystemExit(1)


from .core import Error


MAX_OUTPUT = 64 * 1024
MAX_INPUT = 64 * 1024
MAX_POLL_TIMEOUT = 1.0
SAFE_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"


@dataclass
class _Session:
    id: str
    owner: str
    process: subprocess.Popen
    master: int
    cols: int
    rows: int
    created: float
    activity: float
    deadline: float | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)
    pending: bytearray = field(default_factory=bytearray)
    eof: bool = False
    input_closed: bool = False
    closed: bool = False
    retiring: bool = False
    children_cleaned: bool = False


class TerminalManager:
    """Manage at most four live PTYs and expire abandoned sessions.

    ``cwd`` and lifetime overrides are trusted construction settings, primarily
    for tests.  Runtime requests can pass only owner, session id, dimensions,
    terminal bytes and a bounded poll timeout.  Polling is not user activity.
    Exited sessions retain their final output until close or lifetime expiry.
    """

    def __init__(self, cwd=None, idle_ttl=15 * 60, max_ttl=8 * 60 * 60,
                 sweep_interval=30, max_sessions=4, max_sessions_per_owner=2, user=None, allow_root=False):
        self.unix_user = pwd.getpwnam(user) if user is not None else None
        if type(allow_root) is not bool:
            raise ValueError("Root terminal authorization must be explicit")
        self.root_mode = bool(self.unix_user is not None and self.unix_user.pw_uid == 0)
        if self.root_mode and not allow_root or self.unix_user is None and os.geteuid() == 0:
            raise ValueError("A data terminal cannot run as root")
        if allow_root and (not self.root_mode or os.geteuid() != 0):
            raise ValueError("Trusted root terminals require the root agent and explicit root identity")
        self.cwd = str(Path(cwd or "/").resolve())
        self.idle_ttl = self._duration(idle_ttl, "idle_ttl")
        self.max_ttl = self._duration(max_ttl, "max_ttl")
        self.sweep_interval = self._duration(sweep_interval, "sweep_interval")
        self.max_sessions = self._limit(max_sessions, 4)
        self.max_sessions_per_owner = self._limit(max_sessions_per_owner, 2)
        self._sessions = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._closed = False
        self._sweeper = threading.Thread(target=self._sweep_loop,
                                         name="titan-terminal-cleanup", daemon=True)
        self._sweeper.start()

    @staticmethod
    def _duration(value, name):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("Invalid terminal " + name)
        return float(value)

    @staticmethod
    def _limit(value, maximum):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            raise ValueError("Invalid terminal session limit")
        return value

    @staticmethod
    def _owner(owner):
        if not isinstance(owner, str) or not owner or len(owner) > 256 or any(ord(char) < 32 for char in owner):
            raise Error("Ungültiger Terminalbesitzer.")
        return owner

    @staticmethod
    def _dimensions(cols, rows):
        if any(isinstance(value, bool) or not isinstance(value, int) or not 2 <= value <= 500
               for value in (cols, rows)):
            raise Error("Terminalgröße muss zwischen 2 und 500 liegen.")
        return cols, rows

    @staticmethod
    def _size(fd, cols, rows):
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def _expired(self, session):
        now = time.monotonic()
        return (now - session.activity >= self.idle_ttl or now - session.created >= self.max_ttl
                or session.deadline is not None and now >= session.deadline)

    def _lookup(self, owner, session_id):
        self._owner(owner)
        session = self._sessions.get(session_id) if isinstance(session_id, str) and len(session_id) <= 128 else None
        if (session is None or session.retiring or session.closed or
                not hmac.compare_digest(session.owner.encode(), owner.encode())):
            raise Error("Terminalsitzung nicht gefunden.", 404)
        return session

    @contextlib.contextmanager
    def _owned(self, owner, session_id):
        # All acquisitions follow manager -> session.  The manager lock is
        # released during I/O; no operation reacquires it while holding a PTY.
        with self._lock:
            session = self._lookup(owner, session_id)
            session.lock.acquire()
            expired = self._expired(session)
            if expired:
                session.retiring = True
        try:
            if expired:
                self._terminate(session)
                raise Error("Terminalsitzung ist abgelaufen.", 410)
            if session.closed:
                raise Error("Terminalsitzung nicht gefunden.", 404)
            yield session
        finally:
            session.lock.release()
            if expired:
                with self._lock:
                    self._sessions.pop(session.id, None)

    @staticmethod
    def _state(session):
        code = session.process.poll()
        return {"id": session.id, "cols": session.cols, "rows": session.rows,
                # A client can close after exited=True without losing a tail
                # larger than a single output chunk.
                "exited": code is not None and session.eof, "exit_code": code}

    def create(self, owner, cols=100, rows=30, deadline=None):
        owner = self._owner(owner)
        cols, rows = self._dimensions(cols, rows)
        if deadline is not None and (not self.root_mode or type(deadline) not in (int, float)
                or not math.isfinite(deadline) or not time.monotonic() < deadline <= time.monotonic() + self.max_ttl):
            raise Error('Ungültige oder abgelaufene Root-Terminalfreigabe.', 403)
        if self.root_mode and deadline is None:
            raise Error('Zeitlich begrenzte Root-Terminalfreigabe erforderlich.', 403)
        self._sweep()
        with self._lock:
            if self._closed:
                raise Error("Terminaldienst wurde beendet.", 503)
            if len(self._sessions) >= self.max_sessions:
                raise Error("Maximale Anzahl an Terminalsitzungen erreicht.", 429)
            if sum(item.owner == owner for item in self._sessions.values()) >= self.max_sessions_per_owner:
                raise Error("Maximale Anzahl eigener Terminalsitzungen erreicht.", 429)
            session_id = secrets.token_hex(32)
            while session_id in self._sessions:
                session_id = secrets.token_hex(32)
            try:
                master, slave = os.openpty()
            except OSError as exc:
                raise Error("Terminal konnte nicht gestartet werden.", 503) from exc
            process = None
            try:
                self._size(slave, cols, rows)
                os.set_blocking(master, False)
                try:
                    username = self.unix_user.pw_name if self.unix_user else pwd.getpwuid(os.geteuid()).pw_name
                except KeyError:
                    username = str(os.geteuid())
                environment = {"PATH": SAFE_PATH, "TERM": "xterm-256color",
                               "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                               "HOME": self.cwd, "USER": username, "LOGNAME": username,
                               "SHELL": "/bin/bash",
                               "HISTFILE": "/dev/null", "HISTSIZE": "0", "HISTFILESIZE": "0",
                               "PS1": r"\u@\h:\w\$ "}
                privileges = ({"user": self.unix_user.pw_uid, "group": self.unix_user.pw_gid,
                               "extra_groups": os.getgrouplist(self.unix_user.pw_name, self.unix_user.pw_gid)}
                              if self.unix_user is not None else {})
                process = subprocess.Popen(
                    [sys.executable, "-I", str(Path(__file__).resolve()), "--root-worker" if self.root_mode else "--worker"],
                    stdin=slave, stdout=slave, stderr=slave, cwd=self.cwd,
                    env=environment, close_fds=True, start_new_session=True, **privileges)
                now = time.monotonic()
                session = _Session(session_id, owner, process, master, cols, rows, now, now, deadline=deadline)
                self._sessions[session_id] = session
                return self._state(session)
            except OSError as exc:
                if process is not None:
                    process.kill()
                    process.wait(timeout=1)
                os.close(master)
                raise Error("Terminal konnte nicht gestartet werden.", 503) from exc
            finally:
                os.close(slave)

    @staticmethod
    def _flush(session):
        while session.pending and not session.input_closed:
            try:
                count = os.write(session.master, session.pending)
            except BlockingIOError:
                break
            except OSError as exc:
                if exc.errno not in (errno.EIO, errno.EBADF):
                    raise
                # A closed slave can still have unread final output on the
                # master.  A write failure must not mark the read side EOF.
                session.input_closed = True
                session.pending.clear()
                break
            if not count:
                break
            del session.pending[:count]

    def poll(self, owner, session_id, timeout=0.0):
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or
                not math.isfinite(timeout) or not 0 <= timeout <= MAX_POLL_TIMEOUT):
            raise Error("Ungültige Terminal-Wartezeit.")
        with self._owned(owner, session_id) as session:
            output = bytearray()
            deadline = time.monotonic() + timeout
            self._flush(session)
            while not session.eof and len(output) < MAX_OUTPUT:
                wait = max(0.0, deadline - time.monotonic()) if not output else 0.0
                readable, writable, _ = select.select(
                    [session.master], [session.master] if session.pending else [], [], wait)
                if writable:
                    self._flush(session)
                if not readable:
                    # Pending input becoming writable may precede its output.
                    if writable and not output and time.monotonic() < deadline:
                        continue
                    break
                try:
                    chunk = os.read(session.master, min(16 * 1024, MAX_OUTPUT - len(output)))
                except BlockingIOError:
                    continue
                except OSError as exc:
                    if exc.errno != errno.EIO:
                        raise
                    chunk = b""
                if not chunk:
                    session.eof = True
                    session.pending.clear()
                    break
                output.extend(chunk)
            if session.process.poll() is not None and not session.children_cleaned:
                self._stop_processes(session)
                session.children_cleaned = True
            return {**self._state(session), "data": base64.b64encode(output).decode("ascii"),
                    "eof": session.eof}

    def write(self, owner, session_id, data):
        if not isinstance(data, str) or len(data) > 4 * ((MAX_INPUT + 2) // 3):
            raise Error("Terminaleingabe ist zu groß oder ungültig.", 413)
        try:
            decoded = base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error):
            raise Error("Ungültige Terminaleingabe.") from None
        if len(decoded) > MAX_INPUT:
            raise Error("Terminaleingabe ist zu groß.", 413)
        with self._owned(owner, session_id) as session:
            if session.process.poll() is not None or session.eof or session.input_closed:
                raise Error("Terminalsitzung wurde beendet.", 409)
            self._flush(session)
            if session.input_closed:
                raise Error("Terminalsitzung wurde beendet.", 409)
            if len(session.pending) + len(decoded) > MAX_INPUT:
                raise Error("Terminaleingabe ist ausgelastet.", 429)
            session.pending.extend(decoded)
            self._flush(session)
            if decoded:
                session.activity = time.monotonic()
            return {**self._state(session), "bytes": len(decoded)}

    def resize(self, owner, session_id, cols, rows):
        cols, rows = self._dimensions(cols, rows)
        with self._owned(owner, session_id) as session:
            if session.process.poll() is not None or session.eof or session.input_closed:
                raise Error("Terminalsitzung wurde beendet.", 409)
            self._size(session.master, cols, rows)
            session.cols, session.rows = cols, rows
            return self._state(session)

    @staticmethod
    def _process_groups(session):
        # Interactive bash assigns foreground and background jobs their own
        # process groups.  Killing only bash's group would leave those jobs
        # running.  /proc stat contains kernel ids; no command lines or terminal
        # content are read.  A session id remains reserved while it has members.
        groups = set()
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                if int(fields[3]) == session.process.pid:
                    groups.add(int(fields[2]))
            except (OSError, ValueError, IndexError):
                continue
        return {group for group in groups if group > 1}

    def _stop_processes(self, session):
        groups = self._process_groups(session)
        for group in groups:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(group, signal.SIGTERM)
        # A stopped job must resume to process SIGTERM.  Interactive bash may
        # ignore TERM; the final KILL bounds cleanup even for resistant jobs.
        for group in groups:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(group, signal.SIGCONT)
        deadline = time.monotonic() + 0.25
        while groups and time.monotonic() < deadline:
            session.process.poll()
            if not self._process_groups(session):
                break
            time.sleep(0.01)
        for group in self._process_groups(session):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(group, signal.SIGKILL)
        # Also cover the worker's tiny startup interval before /proc lists it.
        if session.process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                session.process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            session.process.wait(timeout=1)

    def _terminate(self, session):
        if session.closed:
            return
        try:
            self._stop_processes(session)
        finally:
            session.closed = True
            session.eof = True
            session.input_closed = True
            session.pending.clear()
            with contextlib.suppress(OSError):
                os.close(session.master)

    def close(self, owner, session_id):
        with self._lock:
            session = self._lookup(owner, session_id)
            session.lock.acquire()
            session.retiring = True
        try:
            self._terminate(session)
            return {"id": session.id, "closed": True, "exited": True,
                    "exit_code": session.process.poll()}
        finally:
            session.lock.release()
            with self._lock:
                self._sessions.pop(session.id, None)

    def _sweep(self):
        expired = []
        with self._lock:
            for session in list(self._sessions.values()):
                if session.retiring:
                    continue
                if not session.lock.acquire(blocking=False):
                    continue
                if self._expired(session):
                    session.retiring = True
                    expired.append(session)
                else:
                    session.lock.release()
        for session in expired:
            try:
                self._terminate(session)
            finally:
                session.lock.release()
                with self._lock:
                    self._sessions.pop(session.id, None)

    def _sweep_loop(self):
        while not self._stop.wait(self.sweep_interval):
            self._sweep()

    def close_all(self):
        """Permanently stop this manager during agent teardown."""
        with self._lock:
            self._closed = True
            self._stop.set()
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            with session.lock:
                self._terminate(session)
        if threading.current_thread() is not self._sweeper:
            self._sweeper.join(timeout=2)

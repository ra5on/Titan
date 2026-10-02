"""A bounded terminal-shaped demo interpreter; it never starts a host process."""
import base64
import binascii
import codecs
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hmac
import math
import secrets
import shlex
import threading

from .core import Error


MAX_INPUT = 64 * 1024
MAX_OUTPUT = 64 * 1024
MAX_BUFFER = 1024 * 1024
PROMPT = "demo@titan-demo:~$ "


@dataclass
class _DemoSession:
    id: str
    owner: str
    cols: int
    rows: int
    output: bytearray = field(default_factory=bytearray)
    line: str = ""
    escape: str = ""
    previous_cr: bool = False
    line_overflow: bool = False
    exit_code: int | None = None
    decoder: object = field(default_factory=lambda: codecs.getincrementaldecoder("utf-8")("replace"))


class FakeTerminalManager:
    """Match the live PTY API with isolated, fixed in-memory example commands."""

    def __init__(self):
        self._sessions = {}
        self._lock = threading.RLock()
        self._closed = False

    @staticmethod
    def _owner(owner):
        if (not isinstance(owner, str) or not owner or len(owner) > 256 or
                any(ord(character) < 32 for character in owner)):
            raise Error("Ungültiger Terminalbesitzer.")
        return owner

    @staticmethod
    def _dimensions(cols, rows):
        if any(type(value) is not int or not 2 <= value <= 500 for value in (cols, rows)):
            raise Error("Terminalgröße muss zwischen 2 und 500 liegen.")
        return cols, rows

    def _lookup(self, owner, session_id):
        self._owner(owner)
        session = self._sessions.get(session_id) if isinstance(session_id, str) else None
        if session is None or not hmac.compare_digest(session.owner.encode(), owner.encode()):
            raise Error("Terminalsitzung nicht gefunden.", 404)
        return session

    @staticmethod
    def _state(session):
        return {"id": session.id, "cols": session.cols, "rows": session.rows,
                "exited": session.exit_code is not None and not session.output,
                "exit_code": session.exit_code}

    @staticmethod
    def _append(session, text):
        encoded = text.encode("utf-8")
        if len(session.output) + len(encoded) > MAX_BUFFER:
            message = b"\r\nDemo-Ausgabe ist ausgelastet. Bitte neu verbinden.\r\n"
            session.output.extend(message[:max(0, MAX_BUFFER - len(session.output))])
            session.exit_code = 1
            return
        session.output.extend(encoded)

    def create(self, owner, cols=100, rows=30):
        owner = self._owner(owner)
        cols, rows = self._dimensions(cols, rows)
        with self._lock:
            if self._closed:
                raise Error("Terminaldienst wurde beendet.", 503)
            if len(self._sessions) >= 4 or sum(item.owner == owner for item in self._sessions.values()) >= 2:
                raise Error("Maximale Anzahl an Demo-Terminalsitzungen erreicht.", 429)
            session_id = secrets.token_hex(32)
            while session_id in self._sessions:
                session_id = secrets.token_hex(32)
            session = _DemoSession(session_id, owner, cols, rows)
            self._append(session, "Titan DEMO-Terminal: Alle Befehle werden ausschließlich simuliert.\r\n"
                         "Beispiele: help, pwd, whoami, echo, date, clear, exit.\r\n" + PROMPT)
            self._sessions[session_id] = session
            return self._state(session)

    def poll(self, owner, session_id, timeout=0.0):
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or
                not math.isfinite(timeout) or not 0 <= timeout <= 1):
            raise Error("Ungültige Terminal-Wartezeit.")
        with self._lock:
            session = self._lookup(owner, session_id)
            output = bytes(session.output[:MAX_OUTPUT])
            del session.output[:MAX_OUTPUT]
            return {**self._state(session), "data": base64.b64encode(output).decode("ascii"),
                    "eof": session.exit_code is not None and not session.output}

    def _command(self, session):
        line, session.line = session.line, ""
        if session.line_overflow:
            session.line_overflow = False
            self._append(session, "Demo: Die Eingabezeile ist zu lang.\r\n" + PROMPT)
            return
        try:
            words = shlex.split(line, posix=True)
        except ValueError:
            self._append(session, "Demo: Anführungszeichen sind nicht abgeschlossen.\r\n" + PROMPT)
            return
        if not words:
            self._append(session, PROMPT)
            return
        command, arguments = words[0], words[1:]
        if command == "pwd" and not arguments:
            self._append(session, "/home/demo\r\n")
        elif command == "whoami" and not arguments:
            self._append(session, "demo\r\n")
        elif command == "help" and not arguments:
            self._append(session, "DEMO: pwd, whoami, help, echo TEXT, date, clear und exit.\r\n"
                         "Strg+C bricht die Eingabe ab. Keine Shell, keine Hostaktionen.\r\n")
        elif command == "echo":
            # Arguments are printed literally. Variables, redirects, semicolons
            # and command substitutions have no shell semantics in this demo.
            self._append(session, " ".join(arguments) + "\r\n")
        elif command == "date" and not arguments:
            self._append(session, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") + "\r\n")
        elif command == "clear" and not arguments:
            self._append(session, "\x1b[2J\x1b[H")
        elif command == "exit" and not arguments:
            self._append(session, "Demo-Terminal beendet.\r\n")
            session.exit_code = 0
            return
        else:
            self._append(session, "Demo: Nur feste Beispielbefehle werden unterstützt. Mit help anzeigen.\r\n")
        if session.exit_code is None:
            self._append(session, PROMPT)

    def _character(self, session, character):
        if session.escape:
            if session.escape == "\x1b" and character == "[":
                session.escape += character
            elif session.escape.startswith("\x1b[") and not ("@" <= character <= "~") and len(session.escape) < 32:
                session.escape += character
            else:
                # Arrow keys and bracketed-paste delimiters affect a real PTY;
                # the demonstration ignores these controls without printing it.
                session.escape = ""
            return
        if character == "\x1b":
            session.escape = character
            return
        if character == "\x03":
            session.line = ""; session.line_overflow = False
            session.decoder.reset(); session.previous_cr = False
            self._append(session, "^C\r\n" + PROMPT)
            return
        if character == "\x04":
            if not session.line:
                self._append(session, "\r\nDemo-Terminal beendet.\r\n")
                session.exit_code = 0
            return
        if character in ("\r", "\n"):
            if character == "\n" and session.previous_cr:
                session.previous_cr = False
                return
            session.previous_cr = character == "\r"
            self._append(session, "\r\n")
            self._command(session)
            return
        session.previous_cr = False
        if character in ("\x08", "\x7f"):
            if session.line:
                session.line = session.line[:-1]
                self._append(session, "\b \b")
        elif character == "\t":
            pass  # No host command/path completion in the fixed interpreter.
        elif ord(character) >= 32 and not session.line_overflow:
            if len(session.line) >= 8192:
                session.line_overflow = True
            else:
                session.line += character
                self._append(session, character)

    def write(self, owner, session_id, data):
        if not isinstance(data, str) or len(data) > 4 * ((MAX_INPUT + 2) // 3):
            raise Error("Terminaleingabe ist zu groß oder ungültig.", 413)
        try:
            decoded = base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error):
            raise Error("Ungültige Terminaleingabe.") from None
        if len(decoded) > MAX_INPUT:
            raise Error("Terminaleingabe ist zu groß.", 413)
        with self._lock:
            session = self._lookup(owner, session_id)
            if session.exit_code is not None:
                raise Error("Terminalsitzung wurde beendet.", 409)
            for character in session.decoder.decode(decoded):
                self._character(session, character)
                if session.exit_code is not None:
                    break
            return {**self._state(session), "bytes": len(decoded)}

    def resize(self, owner, session_id, cols, rows):
        cols, rows = self._dimensions(cols, rows)
        with self._lock:
            session = self._lookup(owner, session_id)
            if session.exit_code is not None:
                raise Error("Terminalsitzung wurde beendet.", 409)
            session.cols, session.rows = cols, rows
            return self._state(session)

    def close(self, owner, session_id):
        with self._lock:
            session = self._lookup(owner, session_id)
            del self._sessions[session.id]
            return {"id": session.id, "closed": True, "exited": True,
                    "exit_code": session.exit_code if session.exit_code is not None else 0}

    def close_all(self):
        with self._lock:
            self._sessions.clear()
            self._closed = True

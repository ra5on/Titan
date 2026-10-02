import json
import socket
import struct
from .core import Error

MAX_MESSAGE = 24 * 1024 * 1024


def receive(stream):
    def exact(size):
        chunks = bytearray()
        while len(chunks) < size:
            chunk = stream.recv(size - len(chunks))
            if not chunk:
                raise Error("Verwaltungsdienst hat die Verbindung geschlossen.", 503)
            chunks.extend(chunk)
        return chunks
    size = struct.unpack("!I", exact(4))[0]
    if size > MAX_MESSAGE:
        raise Error("Nachricht zu groß.", 413)
    return json.loads(exact(size))


def send(stream, value):
    data = json.dumps(value).encode()
    if len(data) > MAX_MESSAGE:
        raise Error("Nachricht zu groß.", 413)
    stream.sendall(struct.pack("!I", len(data)) + data)


class AgentClient:
    def __init__(self, path="/run/titan/agent.sock"):
        self.path = path

    def call(self, operation, **arguments):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                stream.settimeout(900)
                stream.connect(self.path)
                send(stream, {"operation": operation, "arguments": arguments})
                # A full backup, or a mutation queued behind it, can take hours.
                # A client deadline must not report failure while the trusted
                # agent later executes the accepted action. Host commands retain
                # their own timeouts; service restart closes a stuck connection.
                stream.settimeout(None)
                response = receive(stream)
        except (OSError, ValueError) as exc:
            raise Error("Verwaltungsdienst nicht erreichbar: " + str(exc), 503)
        if "error" in response:
            raise Error(response["error"], response.get("status", 400))
        return response["result"]

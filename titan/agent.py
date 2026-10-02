import argparse
import grp
import logging
import os
from pathlib import Path
import pwd
import socket
import socketserver
import struct
from .core import Error
from .host import Host
from .rpc import receive, send


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(900)
        try:
            _, uid, _ = struct.unpack("3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid not in (0, pwd.getpwnam("titan").pw_uid):
                raise Error("Nicht autorisierter lokaler Client.", 403)
            message = receive(self.request)
            if not isinstance(message, dict) or not isinstance(message.get("arguments", {}), dict):
                raise Error("Ungültige Nachricht.")
            result = self.server.host.dispatch(message["operation"], **message.get("arguments", {}))
            send(self.request, {"result": result})
        except Exception as exc:
            logging.error("Agent operation failed: %s", type(exc).__name__)
            try:
                send(self.request, {"error": str(exc), "status": getattr(exc, "status", 400)})
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default="/run/titan/agent.sock")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Der Verwaltungsdienst benötigt root.")
    path = Path(args.socket)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    class Server(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True
    with Server(str(path), Handler) as server:
        server.host = Host()
        os.chown(path, 0, grp.getgrnam("titan").gr_gid)
        os.chmod(path, 0o660)
        try:
            server.serve_forever()
        finally:
            if hasattr(server.host, '_terminals'):
                server.host._terminals.close_all()


if __name__ == "__main__":
    main()

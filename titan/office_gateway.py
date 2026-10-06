"""Local Euro-Office bridge: scoped document sessions and revision checked saves.

The document server can reach only a signed, short-lived document URL through
the Docker bridge. Its callbacks never choose a NAS path or arbitrary URL.
"""
import base64
import hashlib
import hmac
import http.client
from http.cookies import SimpleCookie
import json
import mimetypes
import re
import secrets
import select
import socket
import threading
import time
import urllib.parse
from pathlib import PurePosixPath

from .core import Error

LIMIT = 16 * 1024 * 1024
KINDS = {**dict.fromkeys(("docx", "doc", "odt", "rtf"), "word"),
         **dict.fromkeys(("xlsx", "xls", "ods", "csv"), "cell"),
         **dict.fromkeys(("pptx", "ppt", "odp"), "slide")}


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def sign(payload, secret):
    header = b64(b'{"alg":"HS256","typ":"JWT"}')
    body = b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
    message = header + "." + body
    return message + "." + b64(hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest())


def verify(token, secret):
    try:
        if not isinstance(token, str) or len(token) > 65536:
            raise ValueError()
        header, body, signature = token.split(".")
        decode = lambda value: base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        jwt_header = json.loads(decode(header))
        if not isinstance(jwt_header, dict) or jwt_header.get("alg") != "HS256":
            raise ValueError()
        expected = hmac.new(secret.encode(), (header + "." + body).encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(decode(signature), expected):
            raise ValueError()
        value = json.loads(decode(body))
        if not isinstance(value, dict) or "exp" in value and float(value["exp"]) < time.time():
            raise ValueError()
        return value
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise Error("Office-Signatur ist ungültig.", 403) from None


def document_extension(path):
    extension = PurePosixPath(path).suffix.lstrip(".").lower()
    if extension not in KINDS:
        raise Error("Diese Datei wird vom Office-Editor nicht unterstützt.")
    return extension


def url_origin(parsed, status=403):
    """Compare authorities with their effective port, retaining the trust boundary."""
    try:
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError()
        port = parsed.port
        if port is not None and port < 1:
            raise ValueError()
        return parsed.scheme, parsed.hostname, port or (443 if parsed.scheme == "https" else 80)
    except (ValueError, TypeError):
        raise Error("Ungültige Office-Adresse.", status) from None


def save_path(url, runtime, public_origin):
    """Translate a signed engine/public cache URL, never follow a redirect."""
    try:
        parsed = urllib.parse.urlsplit(url)
        engine = urllib.parse.urlsplit(runtime["engine_origin"])
        origin = urllib.parse.urlsplit(public_origin)
    except (ValueError, TypeError):
        raise Error("Ungültige Office-Speicheradresse.", 403) from None
    if parsed.username or parsed.password or parsed.fragment or parsed.scheme not in {"http", "https"}:
        raise Error("Ungültige Office-Speicheradresse.", 403)
    source_origin = url_origin(parsed)
    decoded = urllib.parse.unquote(parsed.path)
    if ".." in PurePosixPath(decoded).parts or "\x00" in decoded or "\\" in decoded:
        raise Error("Ungültiger Office-Speicherpfad.", 403)
    if source_origin == url_origin(engine):
        path = parsed.path
    elif source_origin == url_origin(origin) and parsed.path.startswith("/office-engine/"):
        path = parsed.path[len("/office-engine"):]
    else:
        raise Error("Office-Speicheradresse gehört nicht zum lokalen Dokumentserver.", 403)
    if not urllib.parse.unquote(path).startswith("/cache/files/"):
        raise Error("Office darf ausschließlich sein Dokumentcache zurückliefern.", 403)
    return path + ("?" + parsed.query if parsed.query else "")


def engine_connection(runtime):
    origin = urllib.parse.urlsplit(runtime["engine_origin"])
    # This comes from privileged Docker inspection, not a browser parameter.
    if origin.scheme != "http" or not origin.hostname or origin.username or origin.password or origin.path not in {"", "/"}:
        raise Error("Lokaler Office-Dokumentserver ist nicht verfügbar.", 503)
    return http.client.HTTPConnection(origin.hostname, origin.port or 80, timeout=30)


def original_format_url(url, filetype, original_type, key, runtime, public_origin):
    """Convert a signed OOXML result back before replacing an ODF/CSV document."""
    source = save_path(url, runtime, public_origin)
    if filetype == original_type:
        return source
    if filetype not in KINDS or original_type in {"doc", "xls", "ppt"}:
        raise Error("Office kann dieses Dokument nicht im ursprünglichen Format speichern.")
    conversion = {"async": False, "filetype": filetype, "outputtype": original_type,
                  "key": "titan-save-" + secrets.token_hex(24),
                  "url": runtime["engine_origin"].rstrip("/") + source}
    conversion["token"] = sign(conversion, runtime["secret"])
    connection = engine_connection(runtime)
    try:
        connection.request("POST", "/converter", body=json.dumps(conversion).encode(),
                           headers={"Content-Type": "application/json", "Accept": "application/json"})
        response = connection.getresponse()
        raw = response.read(1024 * 1024 + 1)
        if response.status != 200 or len(raw) > 1024 * 1024:
            raise Error("Office konnte das ursprüngliche Dateiformat nicht wiederherstellen.", 503)
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise Error("Office hat eine ungültige Konvertierungsantwort geliefert.", 503) from None
        if not isinstance(result, dict) or result.get("error") or result.get("endConvert") is not True or result.get("fileType", original_type) != original_type:
            raise Error("Office-Konvertierung ist nicht abgeschlossen. Die Originaldatei bleibt erhalten.", 503)
        return save_path(result.get("fileUrl", ""), runtime, public_origin)
    finally:
        connection.close()


def proxy_location(value, runtime, public_origin):
    try:
        parsed = urllib.parse.urlsplit(value)
        engine = urllib.parse.urlsplit(runtime["engine_origin"])
        public = urllib.parse.urlsplit(public_origin)
    except (ValueError, TypeError):
        raise Error("Office hat eine ungültige Weiterleitung geliefert.", 503) from None
    if parsed.scheme or parsed.netloc:
        source_origin = url_origin(parsed, 503)
        if source_origin == url_origin(engine, 503):
            return "/office-engine" + parsed.path + ("?" + parsed.query if parsed.query else "")
        if source_origin == url_origin(public, 503) and parsed.path.startswith("/office-engine/"):
            return value
        raise Error("Office hat eine fremde Weiterleitung geliefert.", 503)
    if value.startswith("/"):
        return value if value.startswith("/office-engine/") else "/office-engine" + value
    return value


class OfficeHostMixin:
    def op_office_write(self, user, share, path, data, revision, admin=False):
        document_extension(path)
        if not isinstance(admin, bool):
            raise Error("Ungültige Office-Berechtigung.")
        if share == "@system":
            if not admin:
                raise Error("Systemdateien benötigen Administratorrechte.", 403)
            self.require_active_account(user)
            return self.op_system_file("office_write", path, data=data, revision=revision)
        return self._file_operation(user, share, "office_write", path,
                                    {"data": data, "revision": revision}, admin)


class OfficeApplicationMixin:
    def initialize_office(self):
        self.office_lock = threading.RLock()

    def office_user(self, record):
        from .identity import require_application
        current = self.store.user_record(record["actor"])
        if not current["enabled"] or current["system_user"] != record["system_user"]:
            raise Error("Office-Sitzung wurde widerrufen.", 403)
        require_application(self.store, current, "files")
        with self.store.connection() as db:
            active = db.execute("SELECT 1 FROM sessions WHERE token=? AND username=? AND expires>?", (record.get("login_digest", ""), record["actor"], time.time())).fetchone()
        if not active:
            raise Error("Die zugehörige Anmeldung wurde beendet. Dokument erneut öffnen.", 403)
        return current

    def office_record(self, session):
        if not isinstance(session, str) or len(session) > 64:
            raise Error("Office-Sitzung ist ungültig.", 403)
        record = self.store.config("office-sessions", {}).get(session)
        if not record or record["expires"] < time.time():
            raise Error("Office-Sitzung ist abgelaufen. Dokument erneut öffnen.", 403)
        self.office_user(record)
        return record

    def office_runtime(self):
        if self.demo:
            raise Error("Die Demo enthält keinen laufenden Office-Dokumentserver.", 503)
        runtime = self.agent.call("app_office_runtime")
        if not isinstance(runtime.get("secret"), str) or len(runtime["secret"]) < 32:
            raise Error("Office-Verbindung ist noch nicht eingerichtet.", 503)
        return runtime


class OfficeHTTPMixin:
    def office_document_access(self, user, key):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        if "titan_session" not in cookie:
            raise Error("Office benötigt eine gültige Anmeldung.", 403)
        digest = hashlib.sha256(cookie["titan_session"].value.encode()).hexdigest()
        records = self.app.store.config("office-sessions", {})
        record = next((value for value in records.values()
                       if value["key"] == key and value["actor"] == user["name"]
                       and value["expires"] > time.time()
                       and hmac.compare_digest(value.get("login_digest", ""), digest)), None)
        if not record:
            raise Error("Office-Dokument ist für diese Sitzung nicht freigegeben.", 403)
        current = self.app.office_user(record)
        # One byte is sufficient to enforce current filesystem/share permissions.
        self.file_call(current, share=record["share"], path=record["path"], action="read", size=1)

    def office_file(self, record):
        user = self.app.office_user(record)
        chunks = []
        offset = 0
        while True:
            value = self.file_call(user, share=record["share"], path=record["path"], action="read", offset=offset, size=4 * 1024 * 1024)
            if value["total"] > LIMIT:
                raise Error("Office unterstützt Dokumente bis 16 MiB.", 413)
            if value["revision"] != record["revision"]:
                raise Error("Dokument wurde inzwischen geändert. Erneut öffnen.", 409)
            chunk = base64.b64decode(value["data"], validate=True)
            chunks.append(chunk)
            offset += len(chunk)
            if offset >= value["total"]:
                break
            if not chunk:
                raise Error("Office-Dokument konnte nicht vollständig gelesen werden.", 503)
        return b"".join(chunks)

    def office_config(self, record, session, mobile=False):
        runtime = self.app.office_runtime()
        origin = self.app.origin or "http://" + self.headers["Host"]
        gateway = runtime["bridge_gateway"]
        import ipaddress
        if not ipaddress.ip_address(gateway).is_private:
            raise Error("Office-Dockerverbindung ist ungültig.", 503)
        internal = "http://" + gateway + ":5101/office/internal/"
        file_url = internal + "file?session=" + urllib.parse.quote(session)
        callback_url = internal + "callback?session=" + urllib.parse.quote(session)
        extension = document_extension(record["path"])
        config = {"documentType": KINDS[extension], "width": "100%", "height": "100%",
                  "document": {"fileType": extension, "key": record["key"],
                               "title": PurePosixPath(record["path"]).name, "url": file_url,
                               "permissions": {"edit": record["writable"], "download": True, "print": True}},
                  "editorConfig": {"mode": "edit" if record["writable"] else "view", "lang": "de",
                                   "callbackUrl": callback_url,
                                   "user": {"id": record["actor"], "name": record["actor"]},
                                   "customization": {"forcesave": True}},
                  "type": "mobile" if mobile else "desktop"}
        config["token"] = sign({**config, "exp": int(record["expires"])}, runtime["secret"])
        return {"config": config, "script": "/office-engine/web-apps/apps/api/documents/api.js",
                "origin": origin}

    def office_get(self, path, query):
        if path == "/office/internal/file":
            record = self.app.office_record(query.get("session"))
            data = self.office_file(record)
            self.send_headers(200, len(data), "application/octet-stream")
            self.wfile.write(data)
            return True
        if path == "/api/office/config":
            user = self.require_user()
            session = query.get("session")
            record = self.app.office_record(session)
            if user["name"] != record["actor"]:
                raise Error("Office-Sitzung gehört einem anderen Benutzer.", 403)
            return self.reply(self.office_config(record, session, query.get("mobile") == "1")) or True
        if path.startswith("/office-engine/"):
            self.office_proxy(path, "GET")
            return True
        return False

    def office_post(self, path):
        if path.startswith("/office-engine/"):
            self.office_proxy(path, "POST")
            return True
        if path == "/api/office/session":
            self.origin_check()
            user = self.require_user(mutation=True)
            from .identity import require_application
            require_application(self.app.store, user, "files")
            body = self.body()
            if set(body) != {"share", "path"}:
                raise Error("Dateiort und Dokument sind erforderlich.")
            document_extension(body["path"])
            runtime = self.app.office_runtime()
            initial = self.file_call(user, **body, action="read", size=1)
            if initial["total"] > LIMIT:
                raise Error("Office unterstützt Dokumente bis 16 MiB.", 413)
            shares = self.app.agent.call("shares")
            share = next((row for row in shares if row["name"] == body["share"]), {})
            writable = (user["role"] == "admin" or user["system_user"] in share.get("writers", [])) and document_extension(body["path"]) not in {"doc", "xls", "ppt"}
            session = secrets.token_urlsafe(32)
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            if "titan_session" not in cookie:
                raise Error("Office benötigt eine gültige Anmeldung.", 401)
            record = {**body, "actor": user["name"], "system_user": user["system_user"],
                      "login_digest": hashlib.sha256(cookie["titan_session"].value.encode()).hexdigest(),
                      "revision": initial["revision"], "writable": writable, "expires": time.time() + 86400,
                      "key": hashlib.sha256((body["share"] + "/" + body["path"] + initial["revision"]).encode()).hexdigest()}
            with self.app.office_lock:
                records = {key: value for key, value in self.app.store.config("office-sessions", {}).items()
                           if value["expires"] > time.time()}
                if len(records) >= 200:
                    raise Error("Zu viele offene Office-Dokumente. Später erneut versuchen.", 429)
                records[session] = record
                self.app.store.set_config("office-sessions", records)
            self.reply({"url": "/office_edit.html?session=" + session, "writable": writable})
            return True
        if path == "/office/internal/callback":
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
            self.office_callback(query)
            return True
        return False

    def office_callback(self, query):
        try:
            session = query.get("session")
            with self.app.office_lock:
                record = self.app.office_record(session)
                runtime = self.app.office_runtime()
                body = self.body()
                token = self.headers.get("AuthorizationJwt", "").removeprefix("Bearer ") or body.get("token")
                signed = verify(token, runtime["secret"])
                signed = signed.get("payload", signed)
                if not isinstance(signed, dict) or signed.get("key") != record["key"]:
                    raise Error("Office-Dokumentzuordnung ist ungültig.", 403)
                status = signed.get("status")
                if status not in {1, 2, 3, 4, 6, 7} or isinstance(status, bool):
                    raise Error("Unbekannter Office-Speicherstatus.")
                if status in {2, 6}:
                    if not record["writable"]:
                        raise Error("Office-Dokument ist schreibgeschützt.", 403)
                    # Check access and revision before asking the local engine.
                    self.office_file(record)
                    original_type = document_extension(record["path"])
                    url = signed.get("url", "")
                    guessed_type = PurePosixPath(urllib.parse.urlsplit(url).path).suffix.lstrip(".").lower()
                    download = original_format_url(url, signed.get("filetype") or (guessed_type if guessed_type in KINDS else original_type),
                                                   original_type, record["key"], runtime,
                                                   self.app.origin or "http://" + self.headers["Host"])
                    connection = engine_connection(runtime)
                    try:
                        connection.request("GET", download)
                        response = connection.getresponse()
                        if response.status != 200:
                            raise Error("Office-Dokumentcache ist nicht verfügbar.", 503)
                        content = response.read(LIMIT + 1)
                    finally:
                        connection.close()
                    if len(content) > LIMIT or not content:
                        raise Error("Office hat ein leeres oder zu großes Dokument geliefert.")
                    user = self.app.office_user(record)
                    self.app.agent.call("office_write", user=user["system_user"], share=record["share"],
                                        path=record["path"], data=base64.b64encode(content).decode(),
                                        revision=record["revision"], admin=user["role"] == "admin")
                    latest = self.file_call(user, share=record["share"], path=record["path"], action="read", size=1)
                    records = self.app.store.config("office-sessions", {})
                    for item in records.values():
                        if item["key"] == record["key"]:
                            item["revision"] = latest["revision"]
                    self.app.store.set_config("office-sessions", records)
                    self.app.store.audit(record["actor"], "office_save", record["share"] + "/" + record["path"])
                self.reply({"error": 1 if status in {3, 7} else 0})
        except Error as error:
            self.reply({"error": 1, "message": str(error)})

    def office_proxy(self, path, method):
        if method == "POST":
            self.origin_check()
        user = self.require_user()
        from .identity import require_application
        require_application(self.app.store, user, "files")
        runtime = self.app.office_runtime()
        upstream_path = path[len("/office-engine"):]
        decoded = urllib.parse.unquote(upstream_path)
        if ".." in PurePosixPath(decoded).parts or any(char in decoded for char in ("\x00", "\\", "\r", "\n")):
            raise Error("Ungültiger Office-Pfad.")
        resource_path = re.sub(r"^/[0-9][a-zA-Z0-9_.-]{0,80}(?=/)", "", decoded)
        if not resource_path.startswith(("/web-apps/", "/sdkjs/", "/fonts/", "/dictionaries/", "/cache/", "/doc/", "/coauthoring/", "/info/")):
            raise Error("Office-Pfad ist nicht freigegeben.", 403)
        document_key = None
        if resource_path.startswith(("/doc/", "/cache/")):
            # Converter cache IDs use conv_<document-key>_<format>. The same
            # live document/session check applies; arbitrary converter IDs do not.
            matched = re.match(r"^/(?:doc/|cache/files/(?:data/)?(?:conv_)?)([a-f0-9]{64})(?:[._/-]|$)", resource_path)
            if not matched:
                raise Error("Office-Dokumentpfad ist nicht freigegeben.", 403)
            document_key = matched.group(1)
            self.office_document_access(user, document_key)
        query = urllib.parse.urlsplit(self.path).query
        if query:
            upstream_path += "?" + query
        origin = urllib.parse.urlsplit(self.app.origin or "http://" + self.headers["Host"])
        headers = {"X-Forwarded-Host": origin.netloc + "/office-engine", "X-Forwarded-Proto": origin.scheme,
                   "Accept-Encoding": "identity"}
        for name in ("Content-Type", "Range", "If-Modified-Since", "If-None-Match"):
            if self.headers.get(name):
                headers[name] = self.headers[name]
        if self.headers.get("Upgrade", "").lower() == "websocket":
            if not self.headers.get("Origin"):
                raise Error("Office-Websocket benötigt eine gültige Herkunft.", 403)
            self.origin_check()
            self.office_websocket(runtime, upstream_path, headers, document_key)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > LIMIT:
            raise Error("Office-Anfrage ist zu groß.", 413)
        data = self.rfile.read(length) if method == "POST" else None
        connection = engine_connection(runtime)
        try:
            connection.request(method, upstream_path, body=data, headers=headers)
            response = connection.getresponse()
            data = response.read(32 * 1024 * 1024 + 1)
            if len(data) > 32 * 1024 * 1024:
                raise Error("Office-Antwort ist zu groß.", 413)
            location = proxy_location(response.getheader("Location"), runtime, origin.geturl()) if response.getheader("Location") else None
            self.send_response(response.status)
            self.send_header("Content-Type", response.getheader("Content-Type", "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            if location:
                self.send_header("Location", location)
            for name in ("Content-Range", "Accept-Ranges", "ETag", "Content-Encoding"):
                if response.getheader(name):
                    self.send_header(name, response.getheader(name))
            self.end_headers()
            self.wfile.write(data)
        finally:
            connection.close()

    def office_websocket(self, runtime, path, headers, document_key=None):
        if document_key is None:
            raise Error("Office-Websocket muss einem freigegebenen Dokument gehören.", 403)
        origin = urllib.parse.urlsplit(runtime["engine_origin"])
        forwarded = {**headers, "Host": origin.netloc, "Connection": "Upgrade", "Upgrade": "websocket"}
        for name in ("Sec-WebSocket-Key", "Sec-WebSocket-Version", "Sec-WebSocket-Protocol", "Sec-WebSocket-Extensions"):
            if self.headers.get(name):
                forwarded[name] = self.headers[name]
        if any("\r" in value or "\n" in value for value in forwarded.values()) or "\r" in path or "\n" in path:
            raise Error("Ungültige Office-Websocketanfrage.")
        with socket.create_connection((origin.hostname, origin.port or 80), timeout=30) as upstream:
            request = "GET " + path + " HTTP/1.1\r\n" + "\r\n".join(name + ": " + value for name, value in forwarded.items()) + "\r\n\r\n"
            upstream.sendall(request.encode("latin-1"))
            handshake = bytearray()
            while not handshake.endswith(b"\r\n\r\n"):
                chunk = upstream.recv(1)
                if not chunk or len(handshake) >= 16384:
                    raise Error("Office-Websocket antwortet nicht korrekt.", 503)
                handshake.extend(chunk)
            if not bytes(handshake).split(b"\r\n", 1)[0].startswith(b"HTTP/1.1 101"):
                raise Error("Office-Websocket konnte nicht geöffnet werden.", 503)
            self.wfile.write(handshake)
            self.wfile.flush()
            self.close_connection = True
            last_activity = time.monotonic()
            last_authorization = last_activity
            while not self.app.stop.is_set():
                if time.monotonic() - last_authorization >= 5:
                    from .identity import require_application
                    current = self.user()
                    if not current:
                        return
                    try:
                        require_application(self.app.store, current, "files")
                        self.office_document_access(current, document_key)
                    except Error:
                        return
                    last_authorization = time.monotonic()
                ready, _, _ = select.select([upstream, self.connection], [], [], 5)
                if not ready:
                    if time.monotonic() - last_activity > 300:
                        return
                    continue
                last_activity = time.monotonic()
                for source in ready:
                    chunk = source.recv(65536)
                    if not chunk:
                        return
                    (self.connection if source is upstream else upstream).sendall(chunk)

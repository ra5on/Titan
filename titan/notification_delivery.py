"""Optional SMTP alerts. Credentials stay in root-owned agent settings."""
from email.message import EmailMessage
from email.utils import parseaddr
import hashlib
import ipaddress
import re
import smtplib
import socket
import ssl
import threading
import time

from .core import Error, integer

DEFAULTS = {"enabled": False, "host": "", "port": 587, "tls": "starttls", "username": "",
            "sender": "", "recipients": [], "minimum_severity": "warning"}
LEVEL = {"info": 0, "warning": 1, "error": 2, "critical": 3}


def address(value):
    if (not isinstance(value, str) or len(value) > 254 or any(ord(character) < 32 for character in value)
            or parseaddr(value)[1] != value or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value)):
        raise Error("Eine vollständige E-Mail-Adresse angeben.")
    return value


class NotificationDelivery:
    def __init__(self, host):
        self.host = host
        self.lock = host.__dict__.setdefault("_notification_delivery_lock", threading.RLock())

    def settings(self):
        value = {**DEFAULTS, **self.host.load("notification-settings", {})}
        value.pop("password", None)
        value["password_set"] = bool(self.host.load("notification-credentials", {}).get("password"))
        return value

    def save_settings(self, **value):
        with self.lock:
            if set(value) - (set(DEFAULTS) | {"password", "clear_password"}):
                raise Error("Unbekannte Benachrichtigungseinstellung.")
            previous = self.settings()
            previous.pop("password_set", None)
            result = {**previous, **{key: item for key, item in value.items() if key in DEFAULTS}}
            if type(result["enabled"]) is not bool or result["tls"] not in ("starttls", "tls"):
                raise Error("SMTP benötigt STARTTLS oder eine direkte TLS-Verbindung.")
            result["port"] = integer(result["port"], 1, 65535)
            hostname = result["host"]
            if not isinstance(hostname, str) or len(hostname) > 253:
                raise Error("Ungültiger SMTP-Server.")
            if hostname:
                try:
                    ipaddress.ip_address(hostname)
                except ValueError:
                    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", hostname):
                        raise Error("Nur den SMTP-Hostnamen oder die IP-Adresse eingeben.")
            for key in ("username",):
                if not isinstance(result[key], str) or len(result[key]) > 320 or any(ord(character) < 32 for character in result[key]):
                    raise Error("Ungültiger SMTP-Benutzername.")
            if not isinstance(result["sender"], str):
                raise Error("Ungültige Absenderadresse.")
            if result["sender"]:
                result["sender"] = address(result["sender"])
            recipients = result["recipients"]
            if not isinstance(recipients, list) or len(recipients) > 10:
                raise Error("Maximal zehn E-Mail-Empfänger auswählen.")
            result["recipients"] = sorted(set(address(item) for item in recipients))
            if not isinstance(result["minimum_severity"], str) or result["minimum_severity"] not in LEVEL:
                raise Error("Ungültige Mindestpriorität.")
            if result["enabled"] and not (hostname and result["sender"] and result["recipients"]):
                raise Error("SMTP-Server, Absender und mindestens einen Empfänger angeben.")
            password = value.get("password", "")
            if not isinstance(password, str) or len(password) > 4096 or any(ord(character) < 32 for character in password):
                raise Error("Ungültiges SMTP-Passwort.")
            if type(value.get("clear_password", False)) is not bool:
                raise Error("Ungültige Passwortoption.")
            # SMTP cannot reflect the secret in settings or exception messages.
            old_credentials = self.host.load("notification-credentials", {})
            credentials = dict(old_credentials)
            if value.get("clear_password"):
                credentials = {}
            if password:
                credentials = {"password": password}
            try:
                self.host.save("notification-credentials", credentials)
                self.host.save("notification-settings", result)
            except Exception:
                try:
                    self.host.save("notification-credentials", old_credentials)
                    self.host.save("notification-settings", previous)
                except Exception:
                    raise Error("SMTP-Einstellungen konnten nicht zurückgesetzt werden. E-Mail-Konfiguration prüfen.", 503) from None
                raise Error("SMTP-Einstellungen konnten nicht gespeichert werden. Bisherige Konfiguration wurde wiederhergestellt.", 503) from None
            return self.settings()

    def _send(self, subject, content):
        settings = self.settings()
        if not (settings["host"] and settings["sender"] and settings["recipients"]):
            raise Error("Zuerst SMTP-Server, Absender und Empfänger speichern.")
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = settings["sender"], ", ".join(settings["recipients"]), subject
        message.set_content(content)
        context = ssl.create_default_context()
        try:
            if settings["tls"] == "tls":
                connection = smtplib.SMTP_SSL(settings["host"], settings["port"], timeout=20, context=context)
            else:
                connection = smtplib.SMTP(settings["host"], settings["port"], timeout=20)
            with connection as smtp:
                smtp.ehlo()
                if settings["tls"] == "starttls":
                    smtp.starttls(context=context)
                    smtp.ehlo()
                if settings["username"]:
                    password = self.host.load("notification-credentials", {}).get("password", "")
                    smtp.login(settings["username"], password)
                refused = smtp.send_message(message)
                if refused:
                    raise Error("Mindestens ein Empfänger wurde vom SMTP-Server abgelehnt.")
        except (smtplib.SMTPException, OSError, ValueError, Error):
            raise Error("E-Mail konnte nicht versendet werden. SMTP-Verbindung, TLS, Anmeldung und Empfänger prüfen.", 503) from None

    def test(self):
        with self.lock:
            self._send("Titan: Testbenachrichtigung", "Die E-Mail-Benachrichtigungen deines Titan NAS funktionieren.\n")
            return {"ok": True, "message": "Testnachricht versendet."}

    def deliver(self, alerts):
        with self.lock:
            settings = self.settings()
            state = self.host.load("notification-delivery", {"sent": {}})
            if not settings["enabled"]:
                return {"enabled": False}
            pending = []
            for alert in alerts:
                if alert.get("active") is False or alert.get("acknowledged") or LEVEL.get(alert.get("severity"), 0) < LEVEL[settings["minimum_severity"]]:
                    continue
                signature = hashlib.sha256((str(alert["id"]) + ":" + str(alert.get("episode", 1)) + ":" + str(alert.get("severity"))).encode()).hexdigest()
                if state["sent"].get(alert["id"]) != signature:
                    pending.append((alert, signature))
            if not pending:
                return {"enabled": True, "pending": 0, "last_sent": state.get("last_sent"), "error": state.get("error")}
            # Batch changes and retry failures at most once per five minutes.
            now = time.time()
            if now - state.get("last_attempt", 0) < 300:
                return {"enabled": True, "pending": len(pending), "error": state.get("error")}
            state["last_attempt"] = now
            self.host.save("notification-delivery", state)
            content = "Titan NAS: " + socket.gethostname() + "\n\n" + "\n\n".join(
                item["title"] + "\n" + str(item.get("detail", "")) + "\nBereich: " + str(item.get("route", "monitoring"))
                for item, signature in pending)
            try:
                self._send("Titan: " + str(len(pending)) + " neue Systemmeldungen", content)
            except Error as exc:
                state["error"] = str(exc)
            else:
                for alert, signature in pending:
                    state["sent"][alert["id"]] = signature
                state["sent"] = {item["id"]: state["sent"][item["id"]] for item in alerts if item["id"] in state["sent"]}
                state["last_sent"] = now
                state.pop("error", None)
            self.host.save("notification-delivery", state)
            return {"enabled": True, "pending": len(pending) if state.get("error") else 0,
                    "last_sent": state.get("last_sent"), "error": state.get("error")}

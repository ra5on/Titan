"""Coordinate the web account database with the restricted SMB account adapter."""
import threading
from .core import Error, configuration_lock, identifier, password_hash, password_matches
from .user_deletion import UserDeletionMixin


class Users(UserDeletionMixin):
    def __init__(self, store, agent, demo=False):
        self.store, self.agent, self.demo = store, agent, demo
        self.lock = threading.RLock()

    def _actor(self, actor, admin=False):
        user = self.store.user_record(actor)
        if not user["enabled"] or (admin and user["role"] != "admin"):
            raise Error("Berechtigung ist nicht mehr gültig.", 403)
        return user

    def setup(self, name, password):
        """Give the first administrator a personal SMB identity as well."""
        name = identifier(name)
        if name in {"root", "titan", "titan-files", "titan-proxy"}:
            raise Error("Dieser Benutzername ist für ein Dienstkonto reserviert.")
        with self.lock:
            self.store.setup(name, password, system_user=name,
                before_commit=lambda: self.agent.call("account_create", name=name, password=password))

    def create(self, actor, name, password, role):
        with self.lock, configuration_lock(self.store.directory):
            self._actor(actor, admin=True)
            # The database write is staged before changing SMB; rejected duplicates
            # and invalid roles must never leave a new host account behind.
            self.store.create_user(name, password, role, name,
                before_commit=lambda: self.agent.call("account_create", name=name, password=password))
            return {"ok": True, "name": name}

    def update(self, actor, name, **changes):
        with self.lock, configuration_lock(self.store.directory):
            self._actor(actor, admin=True)
            if set(changes) - {"password", "role", "enabled"} or not changes:
                raise Error("Ungültige Benutzeränderung.")
            if "password" in changes:
                password_hash(changes["password"])
            if "enabled" in changes and not isinstance(changes["enabled"], bool):
                raise Error("Kontostatus muss ein Schalter sein.")
            name = identifier(name)
            if actor == name and changes.get("enabled") is False:
                raise Error("Das eigene Konto kann nicht gesperrt werden.", 409)
            self.store.validate_user_update(name, **changes)
            if changes.get("enabled") is False:
                # Revoke web access first. If Samba is unavailable the web account
                # remains blocked and the failed job makes the SMB failure visible.
                current = self.store.user_record(name)
                result = self.store.update_user(name, **changes)
                if current["system_user"] != "titan-files":
                    host_changes = {key: value for key, value in changes.items() if key in ("password", "enabled")}
                    self.agent.call("account_update", name=current["system_user"], **host_changes)
                return result
            def host(current):
                if current["system_user"] == "titan-files":
                    return
                host_changes = {key: value for key, value in changes.items() if key in ("password", "enabled")}
                if host_changes:
                    self.agent.call("account_update", name=current["system_user"], **host_changes)
            return self.store.update_user(name, before_commit=host, **changes)

    def password(self, actor, current_password, password):
        with self.lock, configuration_lock(self.store.directory):
            current = self._actor(actor)
            if not self.demo and not password_matches(current_password, current["password"]):
                raise Error("Das aktuelle Passwort ist falsch.", 403)
            def host(user):
                if not self.demo and user["system_user"] == "titan-files":
                    # Older first administrators had a web password, but the app
                    # service identity never had a Samba login. The verified
                    # password change creates their own account and share rights.
                    self.agent.call("account_link", name=actor, password=password)
                elif user["system_user"] != "titan-files":
                    self.agent.call("account_password", name=user["system_user"], password=password)
            return self.store.update_user(actor, password=password, before_commit=host,
                system_user=actor if not self.demo and current["system_user"] == "titan-files" else None)

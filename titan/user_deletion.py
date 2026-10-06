"""Revoke an account before removing its web and SMB identities."""
import json
from .core import Error, configuration_lock, identifier


def validate_removal(store, actor, name):
    name = identifier(name)
    current_actor = store.user_record(actor)
    if not current_actor["enabled"] or current_actor["role"] != "admin":
        raise Error("Administratorrechte sind nicht mehr gültig.", 403)
    if actor == name:
        raise Error("Das eigene Konto kann nicht gelöscht werden.", 409)
    current = store.user_record(name)
    if current["enabled"] and current["role"] == "admin" and sum(
            item["enabled"] and item["role"] == "admin" for item in store.users()) <= 1:
        raise Error("Der letzte aktive Administrator muss erhalten bleiben.", 409)
    if current["system_user"] != "titan-files" and any(
            item["name"] != name and item["system_user"] == current["system_user"] for item in store.users()):
        raise Error("Die Dateiidentität wird noch von einem weiteren Webkonto verwendet.", 409)
    return current


class UserDeletionMixin:
    def remove(self, actor, name, confirmation):
        with self.lock, configuration_lock(self.store.directory):
            with self.store.lock:
                current = validate_removal(self.store, actor, name)
                if confirmation != name:
                    raise Error("Der Benutzername zur Bestätigung stimmt nicht überein.")
                # Persist revocation first. A failed host cleanup leaves a visible,
                # blocked web account that an administrator can delete again.
                self.store.update_user(name, enabled=False)
            if current["system_user"] != "titan-files":
                try:
                    self.agent.call("account_remove", name=current["system_user"])
                except Exception as exc:
                    raise Error("Benutzer ist gesperrt, konnte aber noch nicht vollständig gelöscht werden. "
                                "Die Löschung kann erneut gestartet werden: " + str(exc),
                                getattr(exc, "status", 500)) from exc
            # The shared service identity belongs to the NAS and its apps. Deleting
            # a web administrator never removes that identity or its memberships.
            with self.store.connection() as db:
                validate_removal(self.store, actor, name)
                db.execute("DELETE FROM second_factors WHERE username=?", (name,))
                db.execute("DELETE FROM recovery_codes WHERE username=?", (name,))
                db.execute("DELETE FROM login_protection_failures WHERE kind='account' AND username=?", (name,))
                db.execute("DELETE FROM login_protection_blocks WHERE kind='account' AND username=?", (name,))
                row = db.execute("SELECT value FROM config WHERE key='identity'").fetchone()
                if row:
                    policy = json.loads(row[0])
                    policy['users'].pop(name, None)
                    for group in policy['groups']:
                        group['members'] = [member for member in group['members'] if member != name]
                    db.execute("UPDATE config SET value=? WHERE key='identity'", (json.dumps(policy),))
                db.execute("DELETE FROM sessions WHERE username=?", (name,))
                db.execute("DELETE FROM users WHERE name=?", (name,))
                for prefix in ("dashboard-layout:", "launcher-layout:"):
                    db.execute("DELETE FROM config WHERE key=?", (prefix + name,))
            return {"ok": True, "name": name, "sessions_revoked": True,
                    "data_retained": True}

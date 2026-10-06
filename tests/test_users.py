import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from titan.core import Error, Store, password_hash
from titan.users import Users


class UsersTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.store.setup("admin", "admin-original-password")
        self.store.create_user("reader", "reader-original-password", "user", "reader")
        self.agent = Mock()
        self.users = Users(self.store, self.agent)

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_database_migrates_accounts_without_resetting_passwords(self):
        with tempfile.TemporaryDirectory() as old:
            db = sqlite3.connect(Path(old) / "titan.sqlite3")
            db.execute("CREATE TABLE users(name TEXT PRIMARY KEY,password TEXT NOT NULL,role TEXT NOT NULL,system_user TEXT NOT NULL)")
            db.execute("INSERT INTO users VALUES (?,?,?,?)", ("legacy", password_hash("legacy-long-password"), "admin", "titan-files"))
            db.commit(); db.close()
            migrated = Store(old)
            token, _ = migrated.login("legacy", "legacy-long-password")
            self.assertEqual(migrated.session(token)["name"], "legacy")
            self.assertTrue(migrated.users()[0]["enabled"])
            self.assertEqual(migrated.users()[0]["display_name"], "")
            self.assertEqual(migrated.users()[0]["description"], "")
            self.assertFalse(migrated.setup_file.exists())

    def test_disabled_account_cannot_log_in_and_all_sessions_are_revoked(self):
        tokens = [self.store.login("reader", "reader-original-password")[0] for _ in range(2)]
        self.users.update("admin", "reader", enabled=False)
        self.agent.call.assert_called_once_with("account_update", name="reader", enabled=False)
        for token in tokens:
            self.assertIsNone(self.store.session(token))
        with self.assertRaises(Error) as error:
            self.store.login("reader", "reader-original-password")
        self.assertEqual(error.exception.status, 401)

    def test_failed_smb_disable_still_blocks_web_access(self):
        token, _ = self.store.login("reader", "reader-original-password")
        self.agent.call.side_effect = Error("SMB nicht erreichbar")
        with self.assertRaises(Error):
            self.users.update("admin", "reader", enabled=False)
        self.assertFalse(self.store.user_record("reader")["enabled"])
        self.assertIsNone(self.store.session(token))

    def test_failed_enable_keeps_account_blocked(self):
        self.users.update("admin", "reader", enabled=False)
        self.agent.call.side_effect = Error("SMB nicht erreichbar")
        with self.assertRaises(Error):
            self.users.update("admin", "reader", enabled=True)
        self.assertFalse(self.store.user_record("reader")["enabled"])

    def test_own_password_requires_current_password(self):
        with self.assertRaises(Error) as error:
            self.users.password("reader", "wrong-current-password", "reader-changed-password")
        self.assertEqual(error.exception.status, 403)
        self.agent.call.assert_not_called()

    def test_password_change_updates_smb_then_revokes_old_sessions(self):
        token, _ = self.store.login("reader", "reader-original-password")
        self.users.password("reader", "reader-original-password", "reader-changed-password")
        self.agent.call.assert_called_once_with("account_password", name="reader", password="reader-changed-password")
        self.assertIsNone(self.store.session(token))
        with self.assertRaises(Error):
            self.store.login("reader", "reader-original-password")
        self.store.login("reader", "reader-changed-password")

    def test_failed_smb_password_change_preserves_web_credentials_and_session(self):
        token, _ = self.store.login("reader", "reader-original-password")
        self.agent.call.side_effect = Error("SMB nicht erreichbar")
        with self.assertRaises(Error):
            self.users.password("reader", "reader-original-password", "reader-changed-password")
        self.assertIsNotNone(self.store.session(token))
        self.store.login("reader", "reader-original-password")
        with self.assertRaises(Error):
            self.store.login("reader", "reader-changed-password")

    def test_legacy_administrator_gets_personal_smb_identity_on_verified_password_change(self):
        self.users.password("admin", "admin-original-password", "admin-changed-password")
        self.agent.call.assert_called_once_with("account_link", name="admin", password="admin-changed-password")
        self.assertEqual(self.store.user_record("admin")["system_user"], "admin")

    def test_failed_legacy_smb_link_preserves_web_password_identity_and_session(self):
        token, _ = self.store.login("admin", "admin-original-password")
        self.agent.call.side_effect = Error("SMB unavailable")
        with self.assertRaises(Error): self.users.password("admin", "admin-original-password", "admin-changed-password")
        self.assertEqual(self.store.user_record("admin")["system_user"], "titan-files")
        self.assertIsNotNone(self.store.session(token))
        self.store.login("admin", "admin-original-password")

    def test_new_setup_links_first_administrator_to_own_smb_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            users = Users(store, self.agent)
            users.setup("firstadmin", "first-admin-password")
            self.assertEqual(store.users()[0]["system_user"], "firstadmin")
            self.agent.call.assert_called_once_with("account_create", name="firstadmin", password="first-admin-password")

    def test_failed_first_smb_account_leaves_setup_open(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            self.agent.call.side_effect = Error("SMB unavailable")
            with self.assertRaises(Error): Users(store, self.agent).setup("firstadmin", "first-admin-password")
            self.assertEqual(store.users(), [])

    def test_demo_legacy_password_change_never_mutates_service_or_host(self):
        Users(self.store, self.agent, demo=True).password("admin", "ignored-current", "admin-changed-password")
        self.agent.call.assert_not_called()
        self.assertEqual(self.store.user_record("admin")["system_user"], "titan-files")

    def test_last_active_admin_is_protected(self):
        for change in ({"role": "user"}, {"enabled": False}):
            with self.assertRaises(Error) as error:
                self.store.update_user("admin", **change)
            self.assertEqual(error.exception.status, 409)
        self.assertTrue(self.store.user_record("admin")["enabled"])

    def test_disabled_admin_does_not_count_as_recovery_admin(self):
        self.store.create_user("second", "second-long-password", "admin", "second")
        self.store.update_user("second", enabled=False)
        with self.assertRaises(Error):
            self.store.update_user("admin", role="user")

    def test_role_change_revokes_existing_sessions(self):
        token, _ = self.store.login("reader", "reader-original-password")
        self.users.update("admin", "reader", role="admin")
        self.assertIsNone(self.store.session(token))
        self.agent.call.assert_not_called()

    def test_blocked_actor_cannot_execute_queued_update(self):
        self.store.create_user("second", "second-long-password", "admin", "second")
        self.store.update_user("second", enabled=False)
        with self.assertRaises(Error):
            self.users.update("second", "reader", role="admin")
        self.agent.call.assert_not_called()

    def test_self_block_and_invalid_input_rejected(self):
        for name, change in (("admin", {"enabled": False}), ("reader", {"enabled": "false"}),
                             ("reader", {"password": "bad-password\nline"}), ("reader", {"password": None}),
                             ("reader", {"role": "root"}), ("reader", {"unknown": True})):
            with self.assertRaises(Error):
                self.users.update("admin", name, **change)
        self.agent.call.assert_not_called()

    def test_failed_account_creation_leaves_no_web_account(self):
        self.agent.call.side_effect = Error("SAMBA unavailable")
        with self.assertRaises(Error):
            self.users.create("admin", "newuser", "new-long-password", "user")
        with self.assertRaises(Error) as error:
            self.store.user_record("newuser")
        self.assertEqual(error.exception.status, 404)

    def test_profile_creation_persists_unicode_and_keeps_login_identity(self):
        self.users.create("admin", "lena", "lena-original-password", "user",
                          display_name=" Léna Müller ", description="Familie · Fotos 📷")
        self.agent.call.assert_called_once_with("account_create", name="lena", password="lena-original-password")
        restored = Store(self.temp.name)
        row = next(item for item in restored.users() if item["name"] == "lena")
        self.assertEqual((row["display_name"], row["description"]), ("Léna Müller", "Familie · Fotos 📷"))
        self.assertEqual((row["system_user"], row["role"], row["enabled"]), ("lena", "user", True))
        self.assertNotIn("password", row)
        token, _ = restored.login("lena", "lena-original-password")
        self.assertEqual(restored.session(token)["name"], "lena")

    def test_profile_update_keeps_sessions_roles_and_smb_identity(self):
        token, _ = self.store.login("reader", "reader-original-password")
        original = self.store.user_record("reader")
        result = self.users.update("admin", "reader", display_name="Leserin", description="Nur Familienfotos")
        current = self.store.user_record("reader")
        self.assertEqual((current["display_name"], current["description"]), ("Leserin", "Nur Familienfotos"))
        for field in ("password", "role", "enabled", "system_user"):
            self.assertEqual(current[field], original[field])
        self.assertFalse(result["sessions_revoked"])
        self.assertIsNotNone(self.store.session(token))
        self.agent.call.assert_not_called()
        self.users.update("admin", "reader", description="")
        self.assertEqual(self.store.user_record("reader")["display_name"], "Leserin")
        self.assertEqual(self.store.user_record("reader")["description"], "")

    def test_profile_limits_and_control_characters_are_validated_before_host_changes(self):
        for field, maximum in (("display_name", 96), ("description", 256)):
            self.users.update("admin", "reader", **{field: "ü" * maximum})
            self.assertEqual(self.store.user_record("reader")[field], "ü" * maximum)
            for value in ("a" * (maximum + 1), None, True, 7, [], "bad\x00text", "bad\ntext",
                          "bad\rtext", "bad\ttext", "bad\x7ftext", "bad\x85text", "bad\u202etext",
                          "bad\ud800text", "bad\u2028text"):
                with self.subTest(field=field, value=repr(value)), self.assertRaises(Error):
                    self.users.update("admin", "reader", **{field: value})
            self.assertEqual(self.store.user_record("reader")[field], "ü" * maximum)
        with self.assertRaises(Error):
            self.users.create("admin", "invalid", "valid-user-password", "user", description="bad\x00text")
        self.agent.call.assert_not_called()
        self.assertNotIn("invalid", {item["name"] for item in self.store.users()})

    def test_profile_update_requires_current_administrator_privileges(self):
        self.store.create_user("second", "second-long-password", "admin", "second")
        self.store.update_user("second", enabled=False)
        for actor in ("reader", "second"):
            with self.assertRaises(Error) as error:
                self.users.update(actor, "reader", display_name="Forbidden")
            self.assertEqual(error.exception.status, 403)
        self.assertEqual(self.store.user_record("reader")["display_name"], "")
        self.agent.call.assert_not_called()

    def test_own_profile_update_preserves_admin_safeguards(self):
        token, _ = self.store.login("admin", "admin-original-password")
        self.users.update("admin", "admin", display_name="Administrator")
        self.assertIsNotNone(self.store.session(token))
        for change in ({"enabled": False}, {"role": "user"}):
            with self.assertRaises(Error) as error:
                self.users.update("admin", "admin", description="changed", **change)
            self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.store.user_record("admin")["description"], "")
        self.agent.call.assert_not_called()


if __name__ == "__main__":
    unittest.main()

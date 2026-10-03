from contextlib import ExitStack, closing

import json

from pathlib import Path

import sqlite3

import tempfile

import unittest

from unittest.mock import Mock, patch

from titan import updates

from titan.core import Error, Store

class ConfigurationSafetyTests(unittest.TestCase):
    def test_backup_is_consistent_readable_and_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            database = directory / "source.sqlite3"
            with closing(sqlite3.connect(database)) as source:
                source.execute("CREATE TABLE settings(value TEXT)")
                source.execute("INSERT INTO settings VALUES (?)", ("preserved",))
                source.commit()
            with patch.object(updates, "BACKUP_DIRECTORY", directory / "backups"):
                backup = Path(updates.backup_configuration(database))
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            with closing(sqlite3.connect(backup)) as connection:
                self.assertEqual(connection.execute("SELECT value FROM settings").fetchone()[0], "preserved")

    def test_missing_source_database_is_not_silently_created(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "missing.sqlite3"
            with patch.object(updates, "BACKUP_DIRECTORY", directory / "backups"), self.assertRaises(sqlite3.OperationalError):
                updates.backup_configuration(source)
            self.assertFalse(source.exists())

    def test_automatic_reboot_cannot_be_enabled_and_legacy_setting_is_sanitized(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(temporary)
            store.set_config("settings", {"allow_reboot": True})
            self.assertFalse(store.settings()["allow_reboot"])
            with self.assertRaises(Error):
                store.save_settings({"allow_reboot": True})
            self.assertFalse(store.save_settings({"installation": "automatic"})["allow_reboot"])

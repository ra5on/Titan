import copy
import datetime
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from titan.backup_freshness import activate, completed, overdue, GRACE_SECONDS
from titan.backups import Backups, DEFAULTS
from titan.monitoring import Monitor


def stamp(day, hour, minute=0):
    return datetime.datetime(2026, 10, day, hour, minute).timestamp()


class BackupFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.data = {}
        self.host = SimpleNamespace(load=lambda key, default: copy.deepcopy(self.data.get(key, default)),
                                    save=lambda key, value: self.data.__setitem__(key, copy.deepcopy(value)))
        self.settings = {**DEFAULTS, "target": "/mnt/backup", "auto_backup": True,
                         "shares": ["photos"], "apps": ["titan-immich"], "app_data": ["titan-immich"]}
        self.details = {"shares": ["photos"], "include_config": True,
                        "apps": ["titan-immich"], "app_data": ["titan-immich"]}

    def test_first_daily_deadline_has_grace_and_does_not_alarm_before_due(self):
        activate(self.host, self.settings, stamp(8, 2))
        self.assertIsNone(overdue(self.host, self.settings, stamp(8, 2, 59)))
        self.assertIsNone(overdue(self.host, self.settings, stamp(8, 4, 59)))
        self.assertEqual(overdue(self.host, self.settings, stamp(8, 5))["scheduled"], stamp(8, 3))

    def test_activation_after_todays_start_waits_for_next_calendar_deadline(self):
        activate(self.host, self.settings, stamp(8, 10))
        self.assertIsNone(overdue(self.host, self.settings, stamp(8, 23)))
        self.assertIsNone(overdue(self.host, self.settings, stamp(9, 4, 59)))
        self.assertEqual(overdue(self.host, self.settings, stamp(9, 5))["scheduled"], stamp(9, 3))

    def test_weekly_missed_deadline_remains_visible_on_other_weekdays(self):
        self.settings.update(interval="weekly", window_day=4)
        activate(self.host, self.settings, stamp(8, 2))
        self.assertIsNone(overdue(self.host, self.settings, stamp(8, 23)))
        self.assertIsNone(overdue(self.host, self.settings, stamp(9, 4, 59)))
        missed = overdue(self.host, self.settings, stamp(12, 12))
        self.assertEqual(missed["scheduled"], stamp(9, 3))

    def test_matching_success_resolves_and_becomes_stale_at_next_deadline(self):
        activate(self.host, self.settings, stamp(8, 2))
        completed(self.host, self.settings, "bundle", self.details, stamp(8, 6))
        self.assertIsNone(overdue(self.host, self.settings, stamp(8, 20)))
        self.assertIsNone(overdue(self.host, self.settings, stamp(9, 4, 59)))
        self.assertEqual(overdue(self.host, self.settings, stamp(9, 5))["last_success"], stamp(8, 6))

    def test_previous_missed_day_stays_visible_during_todays_grace(self):
        activate(self.host, self.settings, stamp(8, 2))
        self.assertEqual(overdue(self.host, self.settings, stamp(9, 4))["scheduled"], stamp(8, 3))

    def test_vm_and_partial_backups_do_not_satisfy_the_plan(self):
        activate(self.host, self.settings, stamp(8, 2))
        partials = [("vm", self.details), ("shares", {"shares": ["photos"], "include_config": True}),
                    ("bundle", {**self.details, "app_data": []}),
                    ("bundle", {**self.details, "include_config": False}),
                    ("bundle", {**self.details, "shares": []})]
        for kind, details in partials:
            with self.subTest(kind=kind, details=details):
                completed(self.host, self.settings, kind, details, stamp(8, 6))
                self.assertIsNone(overdue(self.host, self.settings, stamp(8, 6))["last_success"])

    def test_manual_backup_with_superset_of_selected_content_counts(self):
        activate(self.host, self.settings, stamp(8, 2))
        completed(self.host, self.settings, "bundle", {**self.details, "shares": ["photos", "documents"]}, stamp(8, 6))
        self.assertIsNone(overdue(self.host, self.settings, stamp(8, 12)))

    def test_disabled_and_reenabled_plans_get_a_new_observation_window(self):
        activate(self.host, self.settings, stamp(8, 2))
        self.settings["auto_backup"] = False
        self.assertIsNone(overdue(self.host, self.settings, stamp(10, 10)))
        self.settings["auto_backup"] = True
        activate(self.host, self.settings, stamp(10, 10), force=True)
        self.assertIsNone(overdue(self.host, self.settings, stamp(10, 23)))
        self.assertIsNotNone(overdue(self.host, self.settings, stamp(11, 5)))

    def test_unchanged_edits_preserve_history_but_target_content_schedule_changes_reset(self):
        activate(self.host, self.settings, stamp(8, 2))
        completed(self.host, self.settings, "bundle", self.details, stamp(8, 6))
        self.settings["retention"] = 30
        self.assertIsNotNone(overdue(self.host, self.settings, stamp(9, 6)))
        for change in ({"target": "/mnt/other"}, {"shares": ["new"]}, {"window_hour": 10}):
            with self.subTest(change=change):
                changed = {**self.settings, **change}
                activate(self.host, changed, stamp(9, 11))
                self.assertIsNone(overdue(self.host, changed, stamp(9, 23)))
                self.assertIsNotNone(overdue(self.host, changed, stamp(10, 12)))

    def test_legacy_plan_does_not_treat_an_unknown_old_or_vm_success_as_coverage(self):
        self.host.save("backup-state", {"last": {"ok": True, "time": stamp(1, 1), "backup": "old-vm"}})
        self.assertIsNone(overdue(self.host, self.settings, stamp(8, 12)))
        self.assertIsNotNone(overdue(self.host, self.settings, stamp(9, 5)))

    def test_active_copy_suppresses_missed_alarm_without_faking_success(self):
        activate(self.host, self.settings, stamp(8, 2))
        self.assertIsNone(overdue(self.host, self.settings, stamp(8, 8), running=True))
        self.assertIsNotNone(overdue(self.host, self.settings, stamp(8, 8), running=False))

    def test_failed_attempt_does_not_overwrite_last_success(self):
        backups = Backups(self.host, Mock())
        with patch("titan.backups.time.time", return_value=stamp(8, 4)):
            backups._last(True, backup="good")
        with patch("titan.backups.time.time", return_value=stamp(9, 4)):
            backups._last(False, error="offline")
        self.assertFalse(backups.state()["last"]["ok"])
        self.assertEqual(backups.state()["last_success"], {"time": stamp(8, 4), "ok": True, "backup": "good"})

    @unittest.skipUnless(hasattr(time, "tzset"), "requires local timezone support")
    def test_dst_uses_local_calendar_start_and_real_two_hour_grace(self):
        previous = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "Europe/Berlin"
            time.tzset()
            self.settings["window_hour"] = 1
            activated = datetime.datetime(2026, 10, 24, 23).timestamp()
            scheduled = datetime.datetime(2026, 10, 25, 1).timestamp()
            activate(self.host, self.settings, activated)
            self.assertIsNone(overdue(self.host, self.settings, scheduled + GRACE_SECONDS - 1))
            self.assertEqual(overdue(self.host, self.settings, scheduled + GRACE_SECONDS)["scheduled"], scheduled)
        finally:
            if previous is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous
            time.tzset()

    def test_monitor_persists_routes_and_resolves_overdue_notification(self):
        with tempfile.TemporaryDirectory() as directory:
            self.host.directory = self.host.share_root = Path(directory)
            self.host.disks = lambda: []
            self.host.volume_manager = Mock()
            self.host.volume_manager.inventory.return_value = {"volumes": []}
            self.host.save("backup-settings", self.settings)
            activate(self.host, self.settings, stamp(8, 2))
            monitor = Monitor(self.host, Mock())
            with patch.object(monitor, "_services", return_value={}), patch.object(monitor, "_pools", return_value=([], None)), \
                    patch("titan.monitoring.shutil.which", return_value=None), \
                    patch("titan.backups.Backups.validate_target", return_value=Path(directory)), \
                    patch("titan.backup_freshness.time.time", return_value=stamp(8, 6)):
                state = monitor.check(force=True)
                alert = next(item for item in state["alerts"] if item["key"] == "backup:overdue")
                self.assertTrue(alert["active"])
                self.assertEqual((alert["severity"], alert["route"]), ("warning", "backups"))
                completed(self.host, self.settings, "bundle", self.details, stamp(8, 6))
                healthy = monitor.check(force=True)
                self.assertFalse(next(item for item in healthy["alerts"] if item["id"] == alert["id"])["active"])


if __name__ == "__main__":
    unittest.main()

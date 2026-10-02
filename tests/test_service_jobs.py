"""Failed service results retain retry metadata without putting it in audit."""
import tempfile
import time
import unittest

from titan.core import Jobs, Store


class ServiceJobTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="titan-service-job-test-")
        self.store = Store(self.temporary.name)
        self.jobs = Jobs(self.store)

    def tearDown(self):
        self.temporary.cleanup()

    def complete(self, action, result):
        accepted = self.jobs.submit("administrator", action, lambda: result)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            record = next(row for row in self.store.jobs() if row["id"] == accepted["job"])
            if record["status"] in ("completed", "failed"):
                return record
            time.sleep(0.005)
        self.fail("Disposable service job did not finish")

    def test_created_service_with_failed_start_retains_retry_metadata_and_failed_status(self):
        result = {"ok": False, "created": True, "service": "titan-custom-report.service",
                  "autostart": True, "start": False, "error": "private diagnostic --token=do-not-audit",
                  "details": {"active": "failed", "properties": {"Result": "exit-code", "ExecMainStatus": "2"}}}
        record = self.complete("service_create", result)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["result"], result)
        self.assertTrue(record["result"]["created"])
        self.assertTrue(record["result"]["autostart"])
        self.assertFalse(record["result"]["start"])
        audit = self.store.logs()[0]
        self.assertEqual(audit["action"], "service_create")
        self.assertEqual(audit["detail"], "Fehlgeschlagen; Details im Auftrag")
        self.assertNotIn("token", audit["detail"])
        self.assertNotIn("private", audit["detail"])

    def test_failed_service_action_retains_actual_state_and_command(self):
        result = {"ok": False, "command": "restart", "service": {"name": "example.service", "active": "failed"},
                  "error": "Restart diagnostic contains private value"}
        record = self.complete("service_action", result)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["result"], result)
        self.assertEqual(self.store.logs()[0]["detail"], "Fehlgeschlagen; Details im Auftrag")

    def test_successful_service_result_remains_completed(self):
        result = {"ok": True, "created": True, "service": "titan-custom-report.service", "autostart": False, "start": False}
        record = self.complete("service_create", result)
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["result"], result)
        self.assertEqual(self.store.logs()[0]["detail"], "Erfolgreich")


if __name__ == "__main__":
    unittest.main()

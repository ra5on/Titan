from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from titan.telemetry import Telemetry


class KernelTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.proc, self.sys = self.root / "proc", self.root / "sys"
        self.proc.mkdir()
        self.sys.mkdir()
        self.stat("cpu 100 0 50 800 50 0 0 0 80 0")
        self.memory()
        self.monitor = Telemetry(self.proc, self.sys)

    def tearDown(self):
        self.temp.cleanup()

    def stat(self, summary):
        (self.proc / "stat").write_text(summary + "\ncpu0 50 0 25 400 25 0 0 0 40 0\ncpu1 50 0 25 400 25 0 0 0 40 0\n")

    def memory(self):
        (self.proc / "meminfo").write_text("MemTotal: 1000 kB\nMemAvailable: 600 kB\nMemFree: 100 kB\nBuffers: 20 kB\nCached: 200 kB\nSReclaimable: 40 kB\nShmem: 10 kB\nSwapTotal: 500 kB\nSwapFree: 400 kB\n")

    def hwmon(self, name, identifier="hwmon0", **fields):
        directory = self.sys / "class/hwmon" / identifier
        directory.mkdir(parents=True)
        (directory / "name").write_text(name)
        for key, value in fields.items():
            (directory / key).write_text(str(value))
        return directory

    def test_cpu_is_interval_activity_and_guest_is_not_counted_twice(self):
        with patch("titan.telemetry.time.monotonic", return_value=0):
            first = self.monitor.sample()
        self.assertIsNone(first["cpu_percent"])
        self.assertEqual(first["cpus"], 2)
        self.stat("cpu 180 0 70 900 50 0 0 0 150 0")
        with patch("titan.telemetry.time.monotonic", return_value=5):
            second = self.monitor.sample()
        self.assertEqual(second["cpu_percent"], 50)
        self.assertIsNone(second["status_history"][0]["cpu_percent"])
        self.assertEqual(second["status_history"][1]["cpu_percent"], 50)

    def test_counter_reset_cannot_be_reported_as_zero_or_negative_usage(self):
        with patch("titan.telemetry.time.monotonic", return_value=0):
            self.monitor.sample()
        self.stat("cpu 10 0 5 80 5 0 0 0 8 0")
        with patch("titan.telemetry.time.monotonic", return_value=2):
            self.assertIsNone(self.monitor.sample()["cpu_percent"])

    def test_ram_reports_total_occupied_and_separates_available_demand_cache_swap(self):
        sample = self.monitor.sample()
        self.assertEqual(sample["memory_used"], 900 * 1024)
        self.assertEqual(sample["memory_occupied"], 900 * 1024)
        self.assertEqual(sample["memory_demand"], 400 * 1024)
        self.assertEqual(sample["memory_free"], 100 * 1024)
        self.assertEqual(sample["memory_buffers"], 20 * 1024)
        self.assertEqual(sample["status_history"][0]["memory_occupied_percent"],90)
        self.assertEqual(sample["memory_available"], 600 * 1024)
        self.assertEqual(sample["memory_cached"], 230 * 1024)
        self.assertEqual(sample["swap_used"], 100 * 1024)
        self.assertEqual(sample["status_history"][0]["memory_percent"], 90)

    def test_invalid_ram_does_not_drop_cpu_or_imply_no_ram_in_use(self):
        (self.proc / "meminfo").write_text("MemTotal: 1000 kB\nMemAvailable: 2000 kB\n")
        sample = self.monitor.sample()
        self.assertIsNone(sample["memory_used"])
        self.assertIn("memory", sample["telemetry_errors"])
        self.assertEqual(sample["cpus"], 2)
        self.assertIsNone(sample["status_history"][0]["memory_percent"])

    def test_pressure_is_actual_stall_time_and_invalid_values_stay_unavailable(self):
        (self.proc / 'pressure').mkdir()
        source = self.proc / 'pressure/memory'
        source.write_text('some avg10=25.50 avg60=5.0 avg300=2.0 total=100\nfull avg10=6.00 avg60=1.0 avg300=0.0 total=10\n')
        sample = self.monitor.sample()
        self.assertEqual(sample['memory_pressure']['some_avg10'], 25.5)
        self.assertEqual(sample['memory_pressure']['full_avg10'], 6)
        self.assertEqual(sample['memory_health']['level'], 'critical')
        for invalid in ('nan', 'inf', '-1', '101'):
            source.write_text(f'some avg10={invalid}\nfull avg10=0\n')
            value, error = self.monitor._memory_pressure()
            self.assertFalse(value['memory_pressure']['available'])
            self.assertTrue(error)

    def test_swap_activity_and_recent_oom_are_deltas_not_historical_events(self):
        source = self.proc / 'vmstat'
        source.write_text('oom_kill 7\npswpin 100\npswpout 200\n')
        with patch('titan.telemetry.time.monotonic', return_value=0): first = self.monitor.sample()
        self.assertEqual(first['memory_oom_kills'], 7)
        self.assertIsNone(first['memory_oom_kills_delta'])
        source.write_text('oom_kill 8\npswpin 110\npswpout 220\n')
        with patch('titan.telemetry.time.monotonic', return_value=5), patch('titan.telemetry.os.sysconf', return_value=4096):
            second = self.monitor.sample()
        self.assertEqual(second['memory_oom_kills_delta'], 1)
        self.assertEqual(second['swap_in_bps'], 8192)
        self.assertEqual(second['swap_out_bps'], 16384)
        source.write_text('oom_kill 0\npswpin 0\npswpout 0\n')
        with patch('titan.telemetry.time.monotonic', return_value=10): reset = self.monitor.sample()
        self.assertIsNone(reset['memory_oom_kills_delta'])
        self.assertIsNone(reset['swap_in_bps'])

    def test_missing_pressure_kernel_support_is_not_a_fake_zero_measurement(self):
        sample = self.monitor.sample()
        self.assertFalse(sample['memory_pressure']['available'])
        self.assertIsNone(sample['memory_pressure']['some_avg10'])
        self.assertNotIn('memory_pressure', sample['telemetry_errors'])

    def test_no_temperature_sensor_is_unavailable_rather_than_zero(self):
        sample = self.monitor.sample()
        self.assertFalse(sample["temperature_available"])
        self.assertIsNone(sample["cpu_temperature"])
        self.assertEqual(sample["temperatures"], [])

    def test_cpu_and_disk_temperatures_are_not_conflated(self):
        self.hwmon("coretemp", temp1_input=52000, temp1_label="Package id 0", temp1_crit=100000,
                   temp2_input=46000, temp2_label="Core 0")
        self.hwmon("nvme", "hwmon1", temp1_input=65000, temp1_label="Composite")
        sample = self.monitor.sample()
        self.assertEqual(sample["cpu_temperature"], 52)
        self.assertEqual(len(sample["temperatures"]), 3)
        package = next(item for item in sample["temperatures"] if "Package" in item["label"])
        self.assertEqual(package["critical"], 100)
        self.assertEqual(next(item for item in sample["temperatures"] if item["kind"] == "storage")["current"], 65)

    def test_disabled_faulted_and_invalid_sensors_are_excluded(self):
        self.hwmon("coretemp", temp1_input=99000, temp1_fault=1, temp2_input=99000, temp2_enable=0,
                   temp3_input=250000, temp4_input=40000)
        sample = self.monitor.sample()
        self.assertEqual(sample["cpu_temperature"], 40)
        self.assertEqual(len(sample["temperatures"]), 1)
        self.assertIn("temperature", sample["telemetry_errors"])

    def test_soc_thermal_zone_is_used_without_hwmon_support(self):
        directory = self.sys / "class/thermal/thermal_zone0"
        directory.mkdir(parents=True)
        (directory / "type").write_text("cpu-thermal")
        (directory / "temp").write_text("48500")
        self.assertEqual(self.monitor.sample()["cpu_temperature"], 48.5)

    def test_cache_preserves_sampling_window_and_history_is_bounded(self):
        self.monitor = Telemetry(self.proc, self.sys, history_size=2)
        with patch("titan.telemetry.time.monotonic", return_value=0):
            first = self.monitor.sample()
        self.stat("cpu 180 0 70 900 50 0 0 0 150 0")
        with patch("titan.telemetry.time.monotonic", return_value=0.5):
            cached = self.monitor.sample()
        self.assertIsNone(cached["cpu_percent"])
        self.assertEqual(first["telemetry_sampled_at"], cached["telemetry_sampled_at"])
        with patch("titan.telemetry.time.monotonic", return_value=5):
            second = self.monitor.sample()
        second["status_history"].clear()
        self.stat("cpu 280 0 70 1000 50 0 0 0 150 0")
        with patch("titan.telemetry.time.monotonic", return_value=10):
            third = self.monitor.sample()
        self.assertEqual(len(third["status_history"]), 2)
        self.assertTrue(all(item["cpu_percent"] == 50 for item in third["status_history"]))

    def test_unreadable_cpu_resets_baseline_for_recovery(self):
        with patch("titan.telemetry.time.monotonic", return_value=0):
            self.monitor.sample()
        (self.proc / "stat").unlink()
        with patch("titan.telemetry.time.monotonic", return_value=5):
            unavailable = self.monitor.sample()
        self.assertIn("cpu", unavailable["telemetry_errors"])
        self.stat("cpu 180 0 70 900 50 0 0 0 150 0")
        with patch("titan.telemetry.time.monotonic", return_value=10):
            recovered = self.monitor.sample()
        self.assertIsNone(recovered["cpu_percent"])
        self.assertNotIn("cpu", recovered["telemetry_errors"])


if __name__ == "__main__":
    unittest.main()

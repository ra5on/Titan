"""Read-only kernel metrics with real sample history, independent of health checks."""
from collections import deque
from pathlib import Path
import re
import threading
import time


class Telemetry:
    def __init__(self, proc="/proc", sys="/sys", interval=1, history_interval=5, history_size=180):
        self.proc, self.sys = Path(proc), Path(sys)
        self.interval, self.history_interval = interval, history_interval
        self.lock = threading.RLock()
        self.previous_cpu = None
        self.previous_time = None
        self.history_time = None
        self.cached = None
        self.history = deque(maxlen=history_size)

    def _cpu(self):
        lines = (self.proc / "stat").read_text().splitlines()
        fields = next(line.split()[1:] for line in lines if line.startswith("cpu "))
        counters = [int(value) for value in fields[:8]]
        if len(counters) < 4 or any(value < 0 for value in counters):
            raise ValueError("Ungültige CPU-Zähler.")
        # guest/guest_nice are already included in user/nice. Counting them
        # again would inflate the denominator on a virtualization host.
        total = sum(counters)
        idle = counters[3] + (counters[4] if len(counters) > 4 else 0)
        current = (total, idle)
        percent = None
        if self.previous_cpu is not None:
            delta = total - self.previous_cpu[0]
            idle_delta = idle - self.previous_cpu[1]
            if delta > 0 and 0 <= idle_delta <= delta:
                percent = round(100 * (delta - idle_delta) / delta, 1)
        self.previous_cpu = current
        cpus = sum(bool(re.match(r"^cpu\d+\s", line)) for line in lines)
        return {"cpu_percent": percent, "cpus": cpus or None}

    def _memory(self):
        memory = {}
        for line in (self.proc / "meminfo").read_text().splitlines():
            key, separator, value = line.partition(":")
            fields = value.split()
            if separator and len(fields) == 2 and fields[1] == "kB":
                amount = int(fields[0]) * 1024
                if amount < 0:
                    raise ValueError("Ungültiger Speicherzähler.")
                memory[key] = amount
        total, available = memory["MemTotal"], memory["MemAvailable"]
        if total <= 0 or not 0 <= available <= total:
            raise ValueError("Ungültige RAM-Kapazität.")
        free = memory.get("MemFree")
        if free is not None and not 0 <= free <= total:
            raise ValueError("Ungültiger freier RAM.")
        swap_total, swap_free = memory.get("SwapTotal"), memory.get("SwapFree")
        swap_used = (swap_total - swap_free if swap_total is not None and swap_free is not None
                     and 0 <= swap_free <= swap_total else None)
        cached = max(0, memory.get("Cached", 0) + memory.get("SReclaimable", 0) - memory.get("Shmem", 0))
        return {"memory_total": total, "memory_available": available,
                "memory_used": total - free if free is not None else None, "memory_demand": total - available, "memory_cached": min(total, cached),
                "memory_free": free, "memory_occupied": total - free if free is not None else None,
                "memory_buffers": min(total, memory.get("Buffers", 0)),
                "swap_total": swap_total, "swap_used": swap_used}

    @staticmethod
    def _temperature(path):
        value = int(path.read_text().strip()) / 1000
        if not -40 <= value <= 150:
            raise ValueError("Ungültiger Temperaturwert.")
        return round(value, 1)

    @staticmethod
    def _kind(name):
        lowered = name.lower()
        if (lowered in ("coretemp", "k10temp", "zenpower", "fam15h_power") or
                any(token in lowered for token in ("cpu", "x86_pkg", "soc_thermal"))):
            return "cpu"
        if lowered in ("nvme", "drivetemp"):
            return "storage"
        return "system"

    def _temperatures(self):
        sensors, errors = [], []
        for directory in sorted((self.sys / "class/hwmon").glob("hwmon*")):
            try:
                name = (directory / "name").read_text().strip()
            except OSError:
                continue
            for source in sorted(directory.glob("temp[0-9]*_input")):
                base = source.name.removesuffix("_input")
                try:
                    if (directory / (base + "_enable")).exists() and (directory / (base + "_enable")).read_text().strip() == "0":
                        continue
                    if (directory / (base + "_fault")).exists() and (directory / (base + "_fault")).read_text().strip() == "1":
                        continue
                    label_path = directory / (base + "_label")
                    label = label_path.read_text().strip() if label_path.exists() else base.replace("temp", "Sensor ")
                    critical_path = directory / (base + "_crit")
                    try:
                        critical = self._temperature(critical_path) if critical_path.exists() else None
                    except (OSError, ValueError):
                        critical = None
                    sensors.append({"id": directory.name + ":" + base, "label": name + " · " + label,
                                    "kind": self._kind(name), "current": self._temperature(source), "critical": critical})
                except (OSError, ValueError):
                    errors.append(name + ": " + base)
        # Some SoCs expose temperature only through thermal zones. Prefer hwmon
        # when present to avoid displaying duplicate views of the same sensor.
        if not sensors:
            for directory in sorted((self.sys / "class/thermal").glob("thermal_zone*")):
                try:
                    name = (directory / "type").read_text().strip()
                    sensors.append({"id": directory.name, "label": name, "kind": self._kind(name),
                                    "current": self._temperature(directory / "temp"), "critical": None})
                except (OSError, ValueError):
                    errors.append(directory.name)
        cpus = [sensor["current"] for sensor in sensors if sensor["kind"] == "cpu"]
        return {"temperatures": sensors, "cpu_temperature": max(cpus) if cpus else None,
                "temperature_available": bool(sensors)}, errors

    def sample(self):
        with self.lock:
            now = time.monotonic()
            if self.cached is not None and now - self.previous_time < self.interval:
                return {**self.cached, "status_history": [dict(item) for item in self.history]}
            value = {"cpu_percent": None, "cpus": None, "memory_total": None,
                     "memory_used": None, "memory_demand": None, "memory_available": None, "memory_cached": None,
                     "memory_free": None, "memory_occupied": None, "memory_buffers": None,
                     "swap_total": None, "swap_used": None, "cpu_temperature": None,
                     "temperatures": [], "temperature_available": False,
                     "telemetry_sampled_at": time.time(), "telemetry_errors": {}}
            try:
                value.update(self._cpu())
            except (OSError, ValueError, StopIteration):
                self.previous_cpu = None
                value["telemetry_errors"]["cpu"] = "CPU-Zähler sind momentan nicht lesbar."
            try:
                value.update(self._memory())
            except (OSError, ValueError, KeyError):
                value["telemetry_errors"]["memory"] = "RAM-Zähler sind momentan nicht vollständig lesbar."
            thermal, errors = self._temperatures()
            value.update(thermal)
            if errors:
                value["telemetry_errors"]["temperature"] = "Sensoren momentan nicht lesbar: " + ", ".join(errors)[:500]
            if self.history_time is None or now - self.history_time >= self.history_interval:
                self.history.append({"time": value["telemetry_sampled_at"], "cpu_percent": value["cpu_percent"],
                                     "memory_percent": round(100 * value["memory_used"] / value["memory_total"], 1)
                                     if value["memory_total"] and value["memory_used"] is not None else None,
                                     "memory_occupied_percent": round(100 * value["memory_occupied"] / value["memory_total"], 1)
                                     if value["memory_total"] and value["memory_occupied"] is not None else None,
                                     "cpu_temperature": value["cpu_temperature"]})
                self.history_time = now
            self.previous_time, self.cached = now, value
            return {**value, "status_history": [dict(item) for item in self.history]}

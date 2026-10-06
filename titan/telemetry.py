"""Read-only kernel metrics with real sample history, independent of health checks."""
from collections import deque
from pathlib import Path
import math
import os
import re
import threading
import time


class Telemetry:
    def __init__(self, proc="/proc", sys="/sys", interval=1, history_interval=5, history_size=180):
        self.proc, self.sys = Path(proc), Path(sys)
        self.interval, self.history_interval = interval, history_interval
        self.lock = threading.RLock()
        self.previous_cpu = None
        self.previous_io = {}
        self.previous_vmstat = None
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

    def _memory_pressure(self):
        value = {'memory_pressure': {'available': False, 'some_avg10': None, 'full_avg10': None}}
        try:
            rows = (self.proc / 'pressure/memory').read_text().splitlines()
            parsed = {}
            for row in rows:
                fields = row.split()
                if not fields or fields[0] not in ('some', 'full'):
                    continue
                parts = dict(item.split('=', 1) for item in fields[1:])
                number = float(parts['avg10'])
                if not math.isfinite(number) or not 0 <= number <= 100:
                    raise ValueError('Ungültiger RAM-Druck.')
                parsed[fields[0] + '_avg10'] = number
            if len(parsed) != 2:
                raise ValueError('Unvollständiger RAM-Druck.')
            return {'memory_pressure': {'available': True, **parsed}}, None
        except FileNotFoundError:
            return value, None  # PSI may be disabled on an older host kernel.
        except (OSError, ValueError, KeyError):
            return value, 'Speicherdruck ist momentan nicht lesbar.'

    def _memory_activity(self, elapsed):
        result = {'memory_oom_kills': None, 'memory_oom_kills_delta': None,
                  'swap_in_bps': None, 'swap_out_bps': None}
        try:
            rows = dict(row.split() for row in (self.proc / 'vmstat').read_text().splitlines())
            current = {key: int(rows[key]) for key in ('oom_kill', 'pswpin', 'pswpout')}
            if any(value < 0 for value in current.values()):
                raise ValueError('Ungültiger Speicherzähler.')
            result['memory_oom_kills'] = current['oom_kill']
            previous, self.previous_vmstat = self.previous_vmstat, current
            if previous is not None and elapsed is not None and elapsed > 0:
                if current['oom_kill'] >= previous['oom_kill']:
                    result['memory_oom_kills_delta'] = current['oom_kill'] - previous['oom_kill']
                page = os.sysconf('SC_PAGE_SIZE')
                for source, target in (('pswpin', 'swap_in_bps'), ('pswpout', 'swap_out_bps')):
                    if current[source] >= previous[source]:
                        result[target] = round((current[source] - previous[source]) * page / elapsed, 1)
        except (OSError, ValueError, KeyError):
            self.previous_vmstat = None
        return result

    def _io(self, elapsed):
        """Counter deltas, not lifetime totals. Partitions and bridges are excluded."""
        result = {"network_interfaces": [], "disk_devices": [],
                  "network_receive_bps": None, "network_transmit_bps": None,
                  "disk_read_bps": None, "disk_write_bps": None}
        current = {}
        sources = (("network", self.proc / "net/dev"), ("disk", self.proc / "diskstats"))
        errors = {}
        for kind, source in sources:
            try:
                rows = source.read_text().splitlines()
                for row in rows:
                    if kind == "network":
                        if ":" not in row:
                            continue
                        name, counters = row.split(":", 1)
                        name, fields = name.strip(), counters.split()
                        if (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", name) or
                                name == "lo" or name.startswith(("veth", "docker", "br-", "virbr", "tun", "tap", "vnet"))):
                            continue
                        # A real NIC (including a virtual machine's virtio NIC)
                        # has a device symlink. Exclude the host bridge itself.
                        directory = self.sys / "class/net" / name
                        if directory.exists() and not (directory / "device").exists():
                            continue
                        if len(fields) < 16:
                            raise ValueError("Unvollständiger Netzwerkzähler.")
                        receive, transmit = int(fields[0]), int(fields[8])
                    else:
                        fields = row.split()
                        if len(fields) < 14:
                            continue
                        name = fields[2]
                        if (not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name) or
                                name.startswith(("loop", "ram", "dm-", "md"))):
                            continue
                        directory = self.sys / "class/block" / name
                        if (directory / "partition").exists():
                            continue
                        # sysfs is authoritative when available. Otherwise only
                        # whole-disk names can enter the aggregate.
                        if not directory.exists() and not re.fullmatch(r"(?:sd[a-z]+|vd[a-z]+|xvd[a-z]+|nvme[0-9]+n[0-9]+|mmcblk[0-9]+)", name):
                            continue
                        receive, transmit = int(fields[5]) * 512, int(fields[9]) * 512
                    if receive < 0 or transmit < 0:
                        raise ValueError("Negativer E/A-Zähler.")
                    key = (kind, name)
                    current[key] = (receive, transmit)
                    previous = self.previous_io.get(key)
                    incoming = outgoing = None
                    if elapsed and elapsed > 0 and previous:
                        left, right = receive - previous[0], transmit - previous[1]
                        if left >= 0 and right >= 0:
                            incoming, outgoing = round(left / elapsed, 1), round(right / elapsed, 1)
                    result["network_interfaces" if kind == "network" else "disk_devices"].append(
                        {"name": name, "receive_bps" if kind == "network" else "read_bps": incoming,
                         "transmit_bps" if kind == "network" else "write_bps": outgoing})
            except (OSError, ValueError):
                errors[kind] = "Netzwerkzähler sind momentan nicht lesbar." if kind == "network" else "Laufwerkszähler sind momentan nicht lesbar."
                result["network_interfaces" if kind == "network" else "disk_devices"] = []
                current = {key: value for key, value in current.items() if key[0] != kind}
        self.previous_io = current
        for collection, first, second, target_first, target_second in (
            ("network_interfaces", "receive_bps", "transmit_bps", "network_receive_bps", "network_transmit_bps"),
            ("disk_devices", "read_bps", "write_bps", "disk_read_bps", "disk_write_bps")):
            values = result[collection]
            if values and all(item[first] is not None and item[second] is not None for item in values):
                result[target_first] = round(sum(item[first] for item in values), 1)
                result[target_second] = round(sum(item[second] for item in values), 1)
        return result, errors

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
            pressure, pressure_error = self._memory_pressure()
            value.update(pressure)
            value.update(self._memory_activity(now - self.previous_time if self.previous_time is not None else None))
            from .app_memory import memory_health
            value['memory_health'] = memory_health(value)
            if pressure_error:
                value['telemetry_errors']['memory_pressure'] = pressure_error
            io, io_errors = self._io(now - self.previous_time if self.previous_time is not None else None)
            value.update(io)
            value["telemetry_errors"].update(io_errors)
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
                                     "cpu_temperature": value["cpu_temperature"],
                                     **{key: value[key] for key in ("network_receive_bps", "network_transmit_bps", "disk_read_bps", "disk_write_bps")}})
                self.history_time = now
            self.previous_time, self.cached = now, value
            return {**value, "status_history": [dict(item) for item in self.history]}

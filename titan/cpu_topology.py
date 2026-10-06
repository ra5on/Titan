"""Linux CPU topology and explicit libvirt CPU affinity, without P/E guesses."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from .core import Error, integer


def cpu_list(value):
    """Parse bounded Linux cpulists, including sparse CPU IDs and ranges."""
    if not isinstance(value, str) or len(value) > 65536:
        raise ValueError("Invalid CPU list")
    result = set()
    for part in value.strip().split(","):
        if not part and not value.strip():
            return []
        if not re.fullmatch(r"[0-9]+(?:-[0-9]+)?", part):
            raise ValueError("Invalid CPU list")
        bounds = [int(item) for item in part.split("-")]
        start, end = bounds[0], bounds[-1]
        if start > end or end > 65535 or end - start > 8191:
            raise ValueError("Invalid CPU range")
        result.update(range(start, end + 1))
        if len(result) > 8192:
            raise ValueError("CPU list too large")
    return sorted(result)


def topology(cpu_root="/sys/devices/system/cpu", pmu_root="/sys/devices"):
    root, pmus = Path(cpu_root), Path(pmu_root)
    warnings = []

    def read_list(path):
        try:
            return cpu_list(path.read_text().strip())
        except (OSError, ValueError):
            return None

    present = read_list(root / "present")
    online = read_list(root / "online")
    if present is None:
        present = sorted(int(path.name[3:]) for path in root.glob("cpu[0-9]*")
                         if re.fullmatch(r"cpu[0-9]{1,5}", path.name) and int(path.name[3:]) <= 65535)[:8192]
    if online is None:
        warnings.append("Linux meldet keine gültige Liste der aktiven CPUs. Manuelle CPU-Auswahl ist derzeit nicht verfügbar.")
        online = []
    present = sorted(set(present) | set(online))
    groups = {name: set(read_list(pmus / name / "cpus") or [])
              for name in ("cpu_core", "cpu_atom", "cpu_lowpower")}
    overlap = groups["cpu_core"] & (groups["cpu_atom"] | groups["cpu_lowpower"])
    if overlap:
        warnings.append("Linux meldet widersprüchliche Kerntypen. Betroffene CPUs werden ohne P-/E-Zuordnung angezeigt.")
    known = bool(groups["cpu_core"] or groups["cpu_atom"] or groups["cpu_lowpower"])
    if not known:
        warnings.append("Linux stellt keine P-/E-Kerntypen bereit. Die CPUs bleiben einzeln auswählbar.")

    def number(path):
        try:
            value = int(path.read_text().strip())
            return value if value >= 0 else None
        except (OSError, ValueError):
            return None

    cpus = []
    for cpu in present:
        base = root / f"cpu{cpu}" / "topology"
        kind = "unknown"
        if cpu not in overlap:
            if cpu in groups["cpu_core"]:
                kind = "performance"
            elif cpu in groups["cpu_atom"] or cpu in groups["cpu_lowpower"]:
                kind = "efficiency"
        siblings = read_list(base / "thread_siblings_list")
        item = {"id": cpu, "online": cpu in online, "core_type": kind,
                "core_id": number(base / "core_id"), "package_id": number(base / "physical_package_id"),
                "siblings": [item for item in (siblings or [cpu]) if item in present]}
        if cpu in groups["cpu_lowpower"] and kind == "efficiency":
            item["subtype"] = "low-power"
        cpus.append(item)
    return {"cpus": cpus, "online": online, "hybrid_detected": known,
            "source": "linux-sysfs", "warnings": warnings}


def demo_topology():
    """Explicit demo fixture; never used to identify a real processor."""
    return {"cpus": [{"id": cpu, "online": True,
             "core_type": "performance" if cpu < 4 else "efficiency",
             "core_id": cpu % 2 if cpu < 4 else cpu - 2, "package_id": 0,
             "siblings": [cpu % 2, cpu % 2 + 2] if cpu < 4 else [cpu]} for cpu in range(8)],
            "online": list(range(8)), "hybrid_detected": True, "source": "demo",
            "warnings": ["Beispielprozessor der Demo: 2 P-Kerne mit SMT und 4 E-Kerne."]}


class CpuMixin:
    def cpu_topology(self):
        return topology()

    def op_cpu_topology(self):
        return self.cpu_topology()

    def validate_vm_cpu_ids(self, cpus, cpu_ids):
        cpus = integer(cpus, 1, 8192)
        if cpu_ids is None or cpu_ids == []:
            return []
        if not isinstance(cpu_ids, list) or len(cpu_ids) > 8192 or any(type(cpu) is not int for cpu in cpu_ids):
            raise Error("CPU-Auswahl muss eine Liste von CPU-Nummern sein.")
        if len(set(cpu_ids)) != len(cpu_ids):
            raise Error("Eine CPU darf nur einmal ausgewählt werden.")
        active = set(self.cpu_topology()["online"])
        if not active or set(cpu_ids) - active:
            raise Error("Ausgewählte CPUs sind nicht verfügbar oder wurden deaktiviert. CPU-Auswahl neu laden.", 409)
        if len(cpu_ids) < cpus:
            raise Error("Mindestens so viele logische CPUs auswählen, wie die VM vCPUs erhält.")
        return sorted(cpu_ids)

    def apply_vm_cpu_policy(self, root, cpus, cpu_ids):
        ids = self.validate_vm_cpu_ids(cpus, cpu_ids)
        vcpu = root.find("vcpu")
        if vcpu is None:
            vcpu = ET.SubElement(root, "vcpu")
        vcpu.text = str(cpus)
        # Remove per-thread overrides so the selected domain CPU pool applies.
        tune = root.find("cputune")
        if tune is not None:
            for node in list(tune):
                if node.tag in ("vcpupin", "emulatorpin", "iothreadpin"):
                    tune.remove(node)
            if not len(tune):
                root.remove(tune)
        vcpu.attrib.pop("cpuset", None)
        vcpu.set("placement", "static")
        if ids:
            vcpu.set("cpuset", ",".join(str(cpu) for cpu in ids))
        return ids

    @staticmethod
    def vm_cpu_ids(root):
        if any(root.find("./cputune/" + tag) is not None for tag in ("vcpupin", "emulatorpin", "iothreadpin")):
            raise Error("Individuelle CPU-Threadzuweisungen dieser VM müssen zuerst auf dem Host entfernt werden.", 409)
        node = root.find("vcpu")
        try:
            return cpu_list(node.get("cpuset", "")) if node is not None else []
        except ValueError:
            raise Error("Die CPU-Zuordnung dieser VM kann nicht sicher bearbeitet werden.", 409)

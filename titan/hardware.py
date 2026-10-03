"""Read-only PCI GPU discovery; no mutable-root package installation."""
from pathlib import Path


def gpu_names(path='/usr/share/misc/pci.ids'):
    names, vendor = {}, None
    try:
        with open(path) as stream:
            for line in stream:
                if not line.startswith(('\t', '#', ' ')) and len(line) > 6:
                    candidate = line[:4]
                    vendor = candidate if all(c in '0123456789abcdef' for c in candidate) else None
                elif vendor and line.startswith('\t') and not line.startswith('\t\t') and len(line) > 7:
                    names[(vendor, line[1:5])] = line[7:].strip()[:200]
    except OSError:
        pass
    return names


def gpus(root='/sys/bus/pci/devices'):
    names = gpu_names()
    result = []
    for device in sorted(Path(root).glob('*')):
        def read(name):
            try:
                return (device / name).read_text().strip()[:200]
            except OSError:
                return ''
        if not read('class').startswith('0x03'):
            continue
        vendor, product = read('vendor'), read('device')
        maker = {'0x8086': 'Intel', '0x1002': 'AMD', '0x10de': 'NVIDIA', '0x1af4': 'VirtIO', '0x1234': 'QEMU'}.get(vendor, 'PCI')
        try:
            driver = (device / 'driver').resolve(strict=True).name
        except OSError:
            driver = None
        recommendation = {'Intel': 'i915 / xe mit Intel-Firmware', 'AMD': 'amdgpu mit AMD-Firmware',
                          'NVIDIA': 'nouveau oder ein zur GPU und zum Kernel passender NVIDIA-Treiber'}.get(maker, 'Treiber des Geräteherstellers')
        result.append({'pci': device.name, 'vendor': maker, 'model': names.get((vendor.removeprefix('0x'), product.removeprefix('0x')), 'Modellname nicht verfügbar'), 'device_id': vendor + ':' + product,
                       'driver': driver, 'bound': bool(driver), 'passthrough': driver == 'vfio-pci',
                       'recommendation': recommendation,
                       'message': 'Für PCI-Passthrough reserviert.' if driver == 'vfio-pci' else
                                  'Kernel-Treiber aktiv. Medienbeschleunigung muss separat geprüft werden.' if driver else
                                  'Kein aktiver Treiber. Passende Treiber müssen im signierten Titan-Systemupdate enthalten sein.',
                       'installation': 'system-update'})
    return result

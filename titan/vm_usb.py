"""Conservative USB assignment: unique hardware IDs, offline edits, no host disks."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from .core import Error


def inventory(root='/sys/bus/usb/devices'):
    devices = []
    for path in sorted(Path(root).glob('*')):
        def read(name):
            try:
                return (path / name).read_text().strip()[:200]
            except OSError:
                return ''
        vendor, product = read('idVendor'), read('idProduct')
        if not re.fullmatch('[0-9a-f]{4}', vendor) or not re.fullmatch('[0-9a-f]{4}', product):
            continue
        interfaces = list(path.glob(path.name + ':*'))
        classes = [read('bDeviceClass')]
        for interface in interfaces:
            try:
                classes.append((interface / 'bInterfaceClass').read_text().strip())
            except OSError:
                classes.append('unknown')
        # Storage, hubs, and networking may underpin the NAS itself. Never detach
        # them through this generic peripheral selector, even if not mounted.
        blocked = bool(set(classes) & {'08', '09', '02', '0a', 'e0', 'unknown'})
        devices.append({'id': vendor + ':' + product, 'port': path.name,
                        'name': ' '.join(filter(None, [read('manufacturer'), read('product')])) or vendor + ':' + product,
                        'serial': read('serial'), 'blocked': blocked,
                        'reason': 'Speicher, Hubs und Netzwerkgeräte bleiben beim NAS.' if blocked else ''})
    for device in devices:
        if sum(item['id'] == device['id'] for item in devices) > 1:
            device.update(blocked=True, reason='Mehrere baugleiche USB-Geräte: eindeutige Zuordnung derzeit nicht möglich.')
    return devices


def assigned(root):
    result = []
    for node in root.findall("./devices/hostdev[@type='usb']"):
        vendor, product = node.find('source/vendor'), node.find('source/product')
        if vendor is None or product is None:
            raise Error('Extern konfigurierte USB-Zuordnung wird nicht unterstützt.', 409)
        try:
            result.append(f"{int(vendor.get('id'), 0):04x}:{int(product.get('id'), 0):04x}")
        except (ValueError, TypeError):
            raise Error('Ungültige USB-Zuordnung.', 409) from None
    return result


class USBMixin:
    def op_vm_usb(self, vm):
        record = self.managed_vm(vm)
        selected = assigned(ET.fromstring(record['xml']))
        claims = {}
        for domain in self.command(['virsh', 'list', '--all', '--uuid']).splitlines():
            if not domain.strip() or domain.strip() == record['id']:
                continue
            root = ET.fromstring(self.command(['virsh', 'dumpxml', domain.strip()]))
            for device in assigned(root):
                claims[device] = root.findtext('name', domain)
        devices = inventory()
        for item in devices:
            if item['id'] in claims:
                item.update(blocked=True, reason='Zugeordnet: ' + claims[item['id']])
            item['selected'] = item['id'] in selected
        for identifier in selected:
            if not any(item['id'] == identifier for item in devices):
                devices.append({'id': identifier, 'name': identifier, 'port': '', 'serial': '',
                                'blocked': True, 'selected': True, 'reason': 'Nicht angeschlossen. Entfernen möglich.'})
        return {'devices': devices, 'selected': selected, 'editable': record['state'] == 'shut off'}

    def validate_vm_usb(self, vm, selected):
        if not isinstance(selected, list) or len(selected) > 8 or any(not isinstance(item, str) or not re.fullmatch('[0-9a-f]{4}:[0-9a-f]{4}', item) for item in selected) or len(set(selected)) != len(selected):
            raise Error('Bis zu acht eindeutige USB-Geräte auswählen.')
        if not selected:
            return
        devices = self.op_vm_usb(vm)['devices']
        for identifier in selected:
            item = next((item for item in devices if item['id'] == identifier), None)
            if not item or item['blocked']:
                raise Error('USB-Gerät nicht verfügbar: ' + identifier + '. ' + (item['reason'] if item else 'Nicht angeschlossen.'), 409)

    def op_vm_usb_update(self, vm, devices):
        record = self.managed_vm(vm)
        if record['state'] != 'shut off':
            raise Error('VM vor Änderungen an USB-Geräten herunterfahren.', 409)
        self.validate_vm_usb(vm, devices)
        root = ET.fromstring(record['xml'])
        parent = root.find('devices')
        for node in parent.findall("hostdev[@type='usb']"):
            parent.remove(node)
        for identifier in devices:
            vendor, product = identifier.split(':')
            node = ET.SubElement(parent, 'hostdev', mode='subsystem', type='usb', managed='yes')
            source = ET.SubElement(node, 'source', startupPolicy='mandatory')
            ET.SubElement(source, 'vendor', id='0x' + vendor)
            ET.SubElement(source, 'product', id='0x' + product)
        self.redefine_vm(record, root)
        return {'ok': True, 'devices': devices}

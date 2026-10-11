"""PCI passthrough for virtual machines: graphics cards and accelerators.

libvirt detaches a managed device from its host driver when the VM starts and
hands it back at shutdown. A device is only offered when its whole IOMMU
group can move with it; the remaining functions of the same card (for example
the HDMI audio of a graphics card) are passed along automatically.
"""
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from .core import Error
from .hardware import gpu_names

ADDRESS = re.compile(r'[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]\Z')
KINDS = {'03': 'gpu', '12': 'accelerator'}
MAKERS = {'0x8086': 'Intel', '0x1002': 'AMD', '0x1022': 'AMD', '0x10de': 'NVIDIA'}
LIMIT = 4


def slot(address):
    """Domain, bus and device without the function: all functions of one card."""
    return address.rsplit('.', 1)[0]


def inventory(root='/sys/bus/pci/devices', names=None):
    """Passthrough candidates with the functions that have to move together."""
    names = gpu_names() if names is None else names
    devices = {}
    for device in sorted(Path(root).glob('*')):
        if not ADDRESS.fullmatch(device.name):
            continue

        def read(name, device=device):
            try:
                return (device / name).read_text().strip()[:200]
            except OSError:
                return ''
        try:
            group = (device / 'iommu_group').resolve(strict=True).name
        except OSError:
            group = None
        try:
            driver = (device / 'driver').resolve(strict=True).name
        except OSError:
            driver = None
        devices[device.name] = {'address': device.name, 'class': read('class').removeprefix('0x'), 'vendor': read('vendor'),
                                'product': read('device'), 'group': group, 'driver': driver, 'boot_vga': read('boot_vga') == '1'}
    result = []
    for address, item in devices.items():
        kind = KINDS.get(item['class'][:2])
        if kind is None:
            continue
        maker = MAKERS.get(item['vendor'], 'PCI')
        model = names.get((item['vendor'].removeprefix('0x'), item['product'].removeprefix('0x')), '')
        entry = {'address': address, 'kind': kind, 'name': (maker + ' ' + model).strip() if model else maker + '-Gerät ' + address,
                 'driver': item['driver'], 'boot_vga': item['boot_vga'], 'companions': [], 'blocked': False, 'reason': ''}
        if item['group'] is None:
            entry.update(blocked=True, reason='IOMMU ist nicht aktiv. VT-d (Intel) oder AMD-Vi im BIOS/UEFI einschalten.')
        else:
            # Bridges stay with the host; every other member of the group must be a function of this card.
            members = [other for other, value in devices.items()
                       if value['group'] == item['group'] and other != address and not value['class'].startswith('06')]
            foreign = [other for other in members if slot(other) != slot(address)]
            if foreign:
                entry.update(blocked=True, reason='Teilt sich die IOMMU-Gruppe mit anderen Geräten (' + ', '.join(foreign) + '). Einen anderen Steckplatz verwenden.')
            else:
                entry['companions'] = members
        if item['boot_vga'] and not entry['blocked']:
            entry['warning'] = 'Titan zeigt seine eigene Bildschirmausgabe über diese Karte. Solange die VM läuft, bleibt der Monitor am NAS dunkel.'
        result.append(entry)
    return result


def assigned(root):
    """Host PCI addresses a domain definition passes through."""
    found = []
    for node in root.findall("./devices/hostdev[@type='pci']"):
        address = node.find('./source/address')
        if address is None:
            continue
        try:
            value = '{:04x}:{:02x}:{:02x}.{:x}'.format(*(int(address.get(key, '0'), 16) for key in ('domain', 'bus', 'slot', 'function')))
        except ValueError:
            continue
        if ADDRESS.fullmatch(value):
            found.append(value)
    return found


def apply(root, addresses):
    """Replace the PCI passthrough devices of a domain definition."""
    parent = root.find('devices')
    for node in parent.findall("hostdev[@type='pci']"):
        parent.remove(node)
    for address in addresses:
        domain, bus, rest = address.split(':')
        device, function = rest.split('.')
        node = ET.SubElement(parent, 'hostdev', mode='subsystem', type='pci', managed='yes')
        source = ET.SubElement(node, 'source')
        ET.SubElement(source, 'address', domain='0x' + domain, bus='0x' + bus, slot='0x' + device, function='0x' + function)
    return root


class PCIMixin:
    pci_root = '/sys/bus/pci/devices'

    def op_vm_pci(self, vm):
        record = self.managed_vm(vm)
        current = assigned(ET.fromstring(record['xml']))
        claims = {}
        for domain in self.command(['virsh', 'list', '--all', '--uuid']).splitlines():
            if not domain.strip() or domain.strip() == record['id']:
                continue
            other = ET.fromstring(self.command(['virsh', 'dumpxml', domain.strip()]))
            for address in assigned(other):
                claims[address] = other.findtext('name', domain)
        devices = inventory(self.pci_root)
        for item in devices:
            owner = next((claims[address] for address in [item['address'], *item['companions']] if address in claims), None)
            if owner:
                item.update(blocked=True, reason='Zugeordnet: ' + owner)
            item['selected'] = item['address'] in current
        known = {address for item in devices for address in [item['address'], *item['companions']]}
        for address in current:
            if address not in known:
                devices.append({'address': address, 'kind': 'gpu', 'name': 'Nicht mehr vorhanden · ' + address, 'driver': None, 'boot_vga': False,
                                'companions': [], 'blocked': True, 'selected': True, 'reason': 'Gerät fehlt. Abwählen entfernt die Zuordnung.'})
        return {'devices': devices, 'selected': [item['address'] for item in devices if item['selected']],
                'iommu': not any(item['reason'].startswith('IOMMU ist nicht aktiv') for item in devices),
                'editable': record['state'] == 'shut off', 'firmware': record.get('firmware')}

    def op_vm_pci_update(self, vm, devices):
        record = self.managed_vm(vm)
        if record['state'] != 'shut off':
            raise Error('VM vor Änderungen an PCI-Geräten herunterfahren.', 409)
        if (not isinstance(devices, list) or len(devices) > LIMIT or len(set(devices)) != len(devices)
                or any(not isinstance(item, str) or not ADDRESS.fullmatch(item) for item in devices)):
            raise Error('Bis zu vier eindeutige PCI-Geräte auswählen.')
        available = {item['address']: item for item in self.op_vm_pci(vm)['devices']}
        addresses = []
        for address in devices:
            item = available.get(address)
            if item is None:
                raise Error('PCI-Gerät nicht gefunden: ' + address, 409)
            if item['blocked']:
                raise Error('PCI-Gerät nicht verfügbar: ' + item['name'] + '. ' + item['reason'], 409)
            addresses += [address, *item['companions']]
        root = apply(ET.fromstring(record['xml']), sorted(set(addresses)))
        self.redefine_vm(record, root)
        return {'ok': True, 'devices': devices, 'passed': sorted(set(addresses))}

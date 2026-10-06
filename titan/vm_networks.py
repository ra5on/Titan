"""Validated libvirt network selection; never reconfigure the NAS uplink."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from .core import Error

class VMNetworkMixin:
    def vm_network_choices(self):
        networks, bridges, interfaces, warnings = [], [], [], []
        try:
            for name in self.command(['virsh', 'net-list', '--all', '--name']).splitlines():
                if not re.fullmatch(r'[A-Za-z0-9_.-]{1,63}', name): continue
                root = ET.fromstring(self.command(['virsh', 'net-dumpxml', name]))
                forward = root.find('forward')
                networks.append({'name': name, 'mode': forward.get('mode', 'isolated') if forward is not None else 'isolated'})
        except (Error, ET.ParseError) as exc:
            warnings.append('VM-Netze konnten nicht gelesen werden: ' + str(exc))
        for path in sorted(Path('/sys/class/net').iterdir()):
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', path.name) or path.name == 'lo': continue
            if (path / 'bridge').is_dir(): bridges.append(path.name)
            elif (path / 'device').exists() and not (path / 'master').exists(): interfaces.append(path.name)
        return {'networks': networks, 'bridges': bridges, 'interfaces': interfaces, 'warnings': warnings}

    @staticmethod
    def vm_network_info(root):
        node = root.find('./devices/interface')
        if node is None: return {'mode': 'none', 'source': '', 'model': 'virtio', 'mac': '', 'connected': False}
        source, model, mac, link = node.find('source'), node.find('model'), node.find('mac'), node.find('link')
        mode = node.get('type')
        return {'mode': mode, 'source': source.get('network' if mode == 'network' else 'bridge' if mode == 'bridge' else 'dev', '') if source is not None else '',
                'model': model.get('type', 'virtio') if model is not None else 'virtio', 'mac': mac.get('address', '') if mac is not None else '',
                'connected': link is None or link.get('state') != 'down'}

    @classmethod
    def vm_network_interfaces(cls, root):
        result = []
        for index, interface in enumerate(root.findall('./devices/interface')):
            temporary = ET.Element('domain')
            ET.SubElement(temporary, 'devices').append(interface)
            result.append({'index': index, **cls.vm_network_info(temporary)})
        return result

    def apply_vm_network(self, root, value):
        if not isinstance(value, dict) or set(value) - {'mode','source','model','mac','connected'}:
            raise Error('Ungültige VM-Netzwerkeinstellungen.')
        mode, source = value.get('mode', 'network'), value.get('source', 'default')
        model, mac, connected = value.get('model', 'virtio'), value.get('mac', ''), value.get('connected', True)
        if model not in ('virtio','e1000') or not isinstance(connected, bool): raise Error('Ungültiges Netzwerkmodell oder Verbindungsstatus.')
        if not isinstance(mac, str) or mac and (not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', mac) or int(mac[:2],16)&1 or mac.lower() == '00:00:00:00:00:00'):
            raise Error('MAC-Adresse muss eine gültige Unicast-Adresse sein.')
        if mac and mode != 'none':
            ids = self.command(['virsh','list','--all','--uuid'], timeout=5).splitlines()
            if len(ids)>128: raise Error('Zu viele VMs für die MAC-Prüfung.',409)
            for vm in ids:
                if vm == root.findtext('uuid'): continue
                other = ET.fromstring(self.command(['virsh','dumpxml',vm],timeout=5))
                if any(node.get('address','').lower()==mac.lower() for node in other.findall('./devices/interface/mac')):
                    raise Error('Diese MAC-Adresse wird bereits von einer anderen VM verwendet.',409)
        if mode not in ('network','bridge','direct','none'): raise Error('Nicht unterstützte VM-Netzwerkart.')
        if mode != 'none':
            choices = self.vm_network_choices()
            available = [row['name'] for row in choices['networks']] if mode == 'network' else choices['bridges' if mode == 'bridge' else 'interfaces']
            if source not in available: raise Error('Das ausgewählte VM-Netzwerk ist nicht mehr verfügbar.', 409)
        devices = root.find('devices')
        previous = devices.findall('interface')
        if mac and any(node.find('mac') is not None and node.find('mac').get('address','').lower() == mac.lower() for node in previous[1:]):
            raise Error('Diese MAC-Adresse gehört bereits zu einer weiteren Netzwerkkarte dieser VM.',409)
        old = previous[0] if previous else None
        if mode == 'none':
            if old is not None: devices.remove(old)
            return
        node = ET.Element('interface', type=mode)
        ET.SubElement(node,'source', **({'network':source} if mode=='network' else {'bridge':source} if mode=='bridge' else {'dev':source,'mode':'bridge'}))
        ET.SubElement(node,'model',type=model)
        if mac: ET.SubElement(node,'mac',address=mac.lower())
        ET.SubElement(node,'link',state='up' if connected else 'down')
        if old is not None:
            for child in old.findall('address'): node.append(child)
            devices.remove(old)
        devices.append(node)

    def vm_selected_network_ready(self, root):
        for value in self.vm_network_interfaces(root):
            if value['mode'] != 'network': continue
            name = value['source']
            if name == 'default':
                self.vm_network_ready()
                continue
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,63}',name): raise Error('Ungültiger Netzwerkname.')
            info = self.command(['virsh','net-info',name])
            if not re.search(r'^Active:\s+yes\s*$',info,re.MULTILINE):
                self.command(['virsh','net-start',name])

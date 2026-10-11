"""Inspect and grow only the persistent DATA partition of Titan's Debian A/B image.

The two OS slots, EFI and boot partitions are verified but never resized.
No device or size is accepted from the web client.
"""
from pathlib import Path
import re

from .system_disk import SystemDisk, UUID, device_path, positive, unsupported

LINUX_TYPE = '0fc63daf-8483-4772-8e79-3d69d8477de4'
EFI_TYPE = 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b'
LABELS = ('TITAN-EFI', 'TITAN-BOOT', 'TITAN-A', 'TITAN-B', 'TITAN-DATA')


class DebianSystemDisk(SystemDisk):
    filesystem = 'ext4'
    mountpoint = '/var/lib/titan-system'
    partition_label = 'TITAN-DATA'
    partition_type = LINUX_TYPE
    other_partition_types = {EFI_TYPE, LINUX_TYPE}
    complete_message = 'Der interne Datenspeicher nutzt jetzt den verfügbaren Platz der Systemplatte. Die beiden Systemslots bleiben unverändert.'

    def _mount_layout(self):
        data, root = self._mount(self.mountpoint), self._mount('/')
        if data.get('fsroot') != '/' or root.get('fsroot') != '/' or data['maj:min'] == root['maj:min']:
            unsupported('Der interne Speicher muss auf der eigenen TITAN-DATA-Partition liegen.')
        return data, root

    def _validate_layout(self, part, disk, rows, number, root, table):
        partitions = sorted(table['partitions'], key=lambda item: positive(item['start']))
        if number != 5 or tuple(item.get('name') for item in partitions) != LABELS:
            unsupported('Die Systemplatte entspricht nicht dem Titan-Debian-Layout mit zwei Systemslots und abschließender Datenpartition.')
        if device_path('/dev/disk/by-partlabel/TITAN-DATA') != device_path(part['name']):
            unsupported('Die Kennung TITAN-DATA verweist nicht auf den eingehängten internen Speicher.')
        roots = [row for row in rows if row.get('maj:min') == root['maj:min']]
        if len(roots) != 1 or roots[0].get('partlabel') not in ('TITAN-A', 'TITAN-B'):
            unsupported('Das laufende System liegt nicht auf einem Titan-A/B-Systemslot.')
        seen = set()
        for index, item in enumerate(partitions, 1):
            node = device_path(item['node'])
            matches = [row for row in rows if device_path(row['name']) == node]
            if len(matches) != 1:
                unsupported('Eine Partition der Titan-Systemplatte ist nicht eindeutig vorhanden.')
            row = matches[0]
            expected_type = EFI_TYPE if index == 1 else LINUX_TYPE
            if (row.get('type') != 'part' or device_path(row.get('pkname')) != disk
                    or self._block(row) != node or row.get('partlabel') != item['name']
                    or row.get('fstype') != ('vfat' if index == 1 else 'ext4')
                    or str(item.get('type', '')).lower() != expected_type
                    or str(row.get('parttype', '')).lower() != expected_type
                    or not UUID.fullmatch(str(item.get('uuid', '')))
                    or str(row.get('partuuid', '')).lower() != item['uuid'].lower()
                    or item['uuid'].lower() in seen
                    or positive(row['size']) != positive(item['size']) * positive(table['sectorsize'])
                    or positive(Path(f'/sys/dev/block/{row["maj:min"]}/partition').read_text().strip()) != index
                    or positive(Path(f'/sys/dev/block/{row["maj:min"]}/start').read_text().strip()) * 512 != positive(item['start']) * positive(table['sectorsize'])):
                unsupported('GPT- und Kernelstatus des Titan-Debian-Layouts stimmen nicht überein.')
            seen.add(item['uuid'].lower())
        if device_path(roots[0]['name']) not in {device_path(item['node']) for item in partitions[2:4]}:
            unsupported('Systemslot und interner Speicher liegen nicht auf derselben Systemplatte.')

    def _geometry(self, partition, filesystem_uuid):
        fields = {}
        for line in self._run(['tune2fs', '-l', partition]).stdout.splitlines():
            match = re.match(r'^([^:]+):\s*(.*?)\s*$', line)
            if match:
                key, value = match.groups()
                if key in fields:
                    unsupported('Die Ext4-Geometrie ist nicht eindeutig.')
                fields[key] = value
        if (fields.get('Filesystem UUID', '').lower() != filesystem_uuid.lower()
                or fields.get('Filesystem volume name') != 'TITAN-DATA'
                or fields.get('Journal device') not in (None, '0', '0x0000')
                or 'errors' in fields.get('Filesystem state', '')
                or 'has_journal' not in fields.get('Filesystem features', '').split()
                or not fields.get('Journal inode')):
            unsupported('Der interne Ext4-Datenspeicher ist nicht mit seiner Kennung und seinem internen Journal bestätigt.')
        blocksize, blocks = positive(fields.get('Block size')), positive(fields.get('Block count'))
        if blocksize not in (1024, 2048, 4096):
            unsupported('Die Ext4-Blockgröße wird nicht unterstützt.')
        return blocksize, blocks

    def _grow_filesystem(self, before):
        self._run(['resize2fs', before['partition']], timeout=120)

    def _verify(self, before, proof, after, changed_proof):
        super()._verify(before, proof, after, changed_proof)
        if any(proof[key] != changed_proof[key] for key in ('var', 'root', 'disk_major_minor', 'partition_major_minor')):
            unsupported('Die eingehängten Titan-Systemgeräte haben sich während der Erweiterung geändert.')

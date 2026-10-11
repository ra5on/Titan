"""Read-only export of a complete cold-recovery disk inventory."""
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from .core import Error
from . import disaster_recovery as recovery


def inventory(host):
    try:
        target = host.backups.validate_target(host.backups.settings()['target'])
        disks = recovery.block_inventory()
        excluded = recovery.disk_for_device(disks, target.stat().st_dev)
        # All configured volumes must be available; missing members cannot be
        # silently omitted from a packet described as complete.
        for volume in host.volume_manager.records(): host.volume_manager.require(volume['name'])
        from .host import run
        pools = host.load('pools', [])
        if pools:
            health = dict(line.split('\t') for line in run(['zpool','list','-H','-o','name,health']).splitlines())
            if any(pool['name'] not in health for pool in pools) or any(value != 'ONLINE' for value in health.values()):
                raise Error('Für eine vollständige Sicherung müssen alle ZFS-Pools vollständig online sein.')
            status = run(['zpool','status','-LP'])
            if any(word in status for word in ('UNAVAIL','OFFLINE','REMOVED','FAULTED')):
                raise Error('Ein ZFS-Mitglied fehlt. Kein vollständiger Rettungsplan möglich.')
        paths = [host.directory, host.vm_root, Path('/var/lib/titan-system')]
        paths += [Path(share['path']) for share in host.op_shares()]
        # Include inactive domains and additional VM disks, not only vm_root.
        # Network/block passthrough cannot be represented by this local packet.
        for vm in host.load('vms', []):
            xml = ET.fromstring(host.command(['virsh', 'dumpxml', vm['id'], '--inactive'], timeout=10))
            for disk in xml.findall('./devices/disk'):
                source = disk.find('source')
                if source is None:
                    continue
                if not source.get('file'):
                    raise Error('VM verwendet einen nicht lokal sicherbaren Datenträger: ' + vm['name'], 409)
                paths.append(Path(source.get('file')))
            nvram = xml.find('./os/nvram')
            if nvram is not None and nvram.text:
                paths.append(Path(nvram.text))
        for app in host.load('apps', []):
            paths.extend(Path(app[key]) for key in ('data','config_path') if app.get(key))
        # ZFS devices have synthetic dev_t values; all backing disks are included
        # by the inventory. The backup destination itself must be plain ext4/XFS.
        for path in paths:
            if not path.exists(): raise Error('Ein benötigter Datenpfad fehlt: ' + str(path))
            try: disk = recovery.disk_for_device(disks, path.stat().st_dev)
            except recovery.RecoveryError:
                fs = run(['findmnt','-n','-o','FSTYPE','--target',str(path)])
                if fs != 'zfs': raise Error('Nicht lokal sicherbarer Datenpfad: ' + str(path))
            else:
                if disk['identity'] == excluded['identity']:
                    raise Error('Sicherungsziel und Quelldaten befinden sich auf derselben physischen Platte.')
        return recovery.live_inventory(target)
    except (recovery.RecoveryError, KeyError, OSError, ET.ParseError) as exc:
        raise Error('Rettungsplan nicht möglich: ' + str(exc), 409) from None

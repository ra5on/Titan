"""Named NAS storage and retained program choices for all ordinary forms."""
import shutil

from .core import Error
from .storage_locations import StorageLocations

PROGRAMS = (("python3", "Python 3"), ("bash", "Bash"), ("node", "Node.js"),
            ("rsync", "Rsync"), ("rclone", "Rclone"), ("ffmpeg", "FFmpeg"))


def locations(host, runner):
    model = StorageLocations(host, runner)
    result = model.inventory()
    # Legacy path pickers retain named resource entries. Unknown mounts and the
    # OS root are intentionally absent; storage IDs are authoritative for writes.
    items = [{**record}
             for record in result['storage']]
    for share in host.op_shares():
        if share.get('blocked'):
            continue
        try:
            checked = model.validate_path(share['path'])
            if any(item['path'] == share['path'] for item in items):
                continue
            items.append({**checked, 'id': 'share:'+share['name'], 'path': share['path'], 'label': share['name'], 'kind': 'share',
                          'backup_eligible': False})
        except (Error, OSError):
            continue
    result['items'] = items
    result['programs'] = [{'path': path, 'label': label} for command, label in PROGRAMS
                          if (path := shutil.which(command, path='/usr/sbin:/usr/bin:/sbin:/bin'))]
    return result


class LocationsMixin:
    @property
    def storage_locations(self):
        if not hasattr(self, '_storage_locations'):
            def execute(*args, **kwargs):
                from .host import run
                return run(*args, **kwargs)
            self._storage_locations = StorageLocations(self, execute)
        return self._storage_locations

    def op_storage_locations(self):
        from .host import run
        return locations(self, run)

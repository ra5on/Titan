"""One named, mount-verified NAS storage namespace for all user data.

`resolve(id, purpose)` returns a verified record with a purpose-specific `path`;
`fd(...)` additionally retains a no-follow directory descriptor and rechecks the
mount identity after use. Resolution never creates or migrates data. Consumers
must keep their own capacity, namespace ownership and operation locking checks.
The internal ID `system` is a compatibility alias for DATA, never the OS root.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

from .backups import directory_fd, external_path, EXTERNAL_ROOTS, Backups
from .core import Error, identifier

PURPOSES = {'files', 'apps', 'shares', 'vms', 'backups'}
DATA = Path('/var/lib/titan-system')
RESERVED_POOLS = {'apps', 'shares', 'backups', 'vms', 'volumes'}


def absolute_path(value):
    if (not isinstance(value, (str, Path)) or not str(value).startswith('/') or len(str(value)) > 4096
            or '\\' in str(value) or any(ord(char) < 32 or ord(char) == 127 for char in str(value))
            or any(part in ('', '.', '..') for part in str(value).split('/')[1:])):
        raise Error('Einen gültigen absoluten NAS-Datenpfad auswählen.', 403)
    return Path(value)


class StorageLocations:
    def __init__(self, host, runner):
        self.host, self.run = host, runner
        self._pool_names, self._pool_checked = [], 0

    @property
    def private_fixture(self):
        # These prefixes are injected only by trusted local demo/test setup, not
        # by an RPC argument. No real-host mount is assumed for isolated fixtures.
        return Path(self.host.share_root).is_relative_to('/tmp')

    def _pools(self):
        saved = self.host.load('pools', [])
        if not isinstance(saved, list) or len(saved) > 128:
            raise Error('Ungültige Metadaten der verwalteten ZFS-Pools.', 503)
        records = {}
        for item in saved:
            if not isinstance(item, (str, dict)) or isinstance(item, dict) and 'name' not in item:
                raise Error('Ungültige Metadaten der verwalteten ZFS-Pools.', 503)
            name = identifier(item if isinstance(item, str) else item['name'])
            if name in records:
                raise Error('Mehrdeutige Metadaten der verwalteten ZFS-Pools.', 503)
            record = {'name': name} if isinstance(item, str) else dict(item)
            if 'guid' in record and (not isinstance(record['guid'], str) or not re.fullmatch(r'[0-9]{1,20}', record['guid']) or int(record['guid']) == 0):
                raise Error('Ungültige gespeicherte ZFS-Pool-Kennung.', 503)
            records[name] = record
        if time.monotonic() - self._pool_checked > 2:
            try:
                output = self.run(['zpool', 'list', '-H', '-o', 'name'])
            except (Error, OSError):
                pass
            else:
                if not isinstance(output, str):
                    raise Error('ZFS-Pool-Liste konnte nicht gelesen werden.', 503)
                names = [identifier(name.strip()) for name in output.splitlines() if name.strip()]
                if len(names) > 128 or len(names) != len(set(names)):
                    raise Error('Die ZFS-Pool-Liste ist zu groß oder nicht eindeutig.', 503)
                self._pool_names = names
            self._pool_checked = time.monotonic()
        for name in self._pool_names:
            records.setdefault(name, {'name': name})
        if len(records) > 128:
            raise Error('Zu viele gespeicherte und importierte ZFS-Pools.', 503)
        return [records[name] for name in sorted(records)]

    def _internal_spec(self):
        return {'id': 'system', 'label': 'Interner Speicher', 'kind': 'internal',
                'path': str(self.host.share_root), 'filesystem': 'ext4'}

    def _external_specs(self):
        settings = self.host.load('backup-settings', {})
        target = settings.get('target') if isinstance(settings, dict) else None
        if not target:
            return []
        path = external_path(target)
        if not any(path.is_relative_to(base) for base in EXTERNAL_ROOTS):
            return []
        storage = 'external:'+hashlib.sha256(str(path).encode()).hexdigest()[:24]
        saved = self.host.load('external-storage', [])
        if (not isinstance(saved, list) or len(saved) > 32 or any(not isinstance(item, dict)
                or not isinstance(item.get('id'), str) or not re.fullmatch(r'external:[a-f0-9]{24}', item['id']) for item in saved)):
            raise Error('Ungültige Kennungen externer Sicherungslaufwerke.', 503)
        known = next((item for item in saved if item.get('id') == storage), {})
        return [{**known, 'id': storage, 'label': path.name, 'kind': 'external', 'path': str(path)}]

    def specs(self):
        records = [self._internal_spec()]
        for volume in self.host.volume_manager.records():
            records.append({'id': 'volume:'+volume['name'], 'label': volume['name'], 'kind': 'volume',
                            'path': str(self.host.volume_manager.root / volume['name']),
                            'filesystem': volume['filesystem'], 'uuid': volume['uuid']})
        for pool in self._pools():
            name = pool['name']
            records.append({'id': 'pool:'+name, 'label': name, 'kind': 'pool',
                            'path': str(self.host.share_root / name), 'filesystem': 'zfs',
                            **({'uuid': 'zfs:'+pool['guid']} if pool.get('guid') else {})})
        records.extend(self._external_specs())
        return records

    def spec(self, storage):
        if not isinstance(storage, str):
            raise Error('Ungültiger Speicherbereich.')
        if storage == 'system':
            return self._internal_spec()
        if storage.startswith('volume:'):
            volume = self.host.volume_manager.record(storage.split(':', 1)[1])
            return {'id': storage, 'label': volume['name'], 'kind': 'volume',
                    'path': str(self.host.volume_manager.root / volume['name']),
                    'filesystem': volume['filesystem'], 'uuid': volume['uuid']}
        if storage != 'system':
            if not storage.startswith(('volume:', 'pool:', 'external:')):
                raise Error('Ungültiger Speicherbereich.')
            if storage.startswith('external:'):
                if not re.fullmatch(r'external:[a-f0-9]{24}', storage):
                    raise Error('Ungültiges externes Sicherungslaufwerk.')
            else:
                identifier(storage.split(':', 1)[1])
        record = next((record for record in self.specs() if record['id'] == storage), None)
        if record is None:
            raise Error('Speicherbereich nicht gefunden.', 404)
        return record

    def internal_device(self):
        if self.private_fixture:
            with directory_fd(self.host.share_root) as fd:
                return os.fstat(fd).st_dev
        try:
            value = json.loads(self.run(['findmnt', '--json', '--target', str(DATA), '--output', 'TARGET,SOURCE,FSTYPE,MAJ:MIN,OPTIONS']))
            entries = value['filesystems']
            if len(entries) != 1:
                raise ValueError('ambiguous DATA mount')
            item = entries[0]
            major, minor = map(int, item['maj:min'].split(':'))
            device = os.makedev(major, minor)
            block = Path('/dev/disk/by-partlabel/TITAN-DATA').resolve(strict=True).stat()
            if (item['target'] != str(DATA) or item['fstype'] != 'ext4' or 'ro' in item.get('options', '').split(',')
                    or not stat.S_ISBLK(block.st_mode) or block.st_rdev != device):
                raise ValueError('wrong DATA partition')
            with directory_fd(DATA) as fd:
                if os.fstat(fd).st_dev != device:
                    raise ValueError('DATA device changed')
            return device
        except (Error, OSError, ValueError, KeyError, TypeError):
            raise Error('Interner Datenspeicher ist nicht sicher eingehängt. Kein Zugriff auf die Systempartition.', 503) from None

    def _pool_device(self, record, path):
        pool = record['id'].split(':', 1)[1]
        try:
            value = json.loads(self.run(['findmnt', '--json', '--target', str(path), '--output', 'TARGET,SOURCE,FSTYPE,MAJ:MIN,OPTIONS']))
            entries = value['filesystems']
            if len(entries) != 1:
                raise ValueError('ambiguous dataset mount')
            mount = entries[0]
            source = mount['source']
            target = absolute_path(mount['target'])
            root = Path(record['path'])
            if (mount['fstype'] != 'zfs' or source != pool and not source.startswith(pool+'/')
                    or not path.is_relative_to(target) or not target.is_relative_to(root)
                    or path == root and (source != pool or target != root)
                    or 'ro' in mount.get('options', '').split(',')):
                raise ValueError('foreign or read-only pool mount')
            properties = dict(line.split('\t', 1) for line in self.run(
                ['zfs', 'get', '-H', '-o', 'property,value', 'mountpoint,mounted', source]).splitlines())
            if properties != {'mountpoint': str(target), 'mounted': 'yes'}:
                raise ValueError('dataset mount identity mismatch')
            guid = self.run(['zpool', 'get', '-H', '-o', 'value', 'guid', pool]).strip()
            if not re.fullmatch(r'[0-9]{1,20}', guid) or int(guid) == 0:
                raise ValueError('missing pool identity')
            if record.get('uuid') and record['uuid'] != 'zfs:'+guid:
                raise ValueError('pool GUID was replaced')
            major, minor = map(int, mount['maj:min'].split(':'))
            return os.makedev(major, minor), 'zfs:'+guid
        except (Error, OSError, ValueError, KeyError, TypeError):
            raise Error('ZFS-Pool ist nicht mit seiner bestätigten Dataset-Kennung eingehängt.', 503) from None

    def device(self, record, path=None):
        if record['kind'] == 'internal':
            return self.internal_device(), None
        if record['kind'] == 'volume':
            volume, device = self.host.volume_manager.require(record['id'].split(':', 1)[1])
            return device, volume['uuid']
        if record['kind'] == 'external':
            return self._external_device(record)
        return self._pool_device(record, Path(path or record['path']))

    def _external_device(self, record):
        try:
            path = Backups(self.host, self.run).validate_target(record['path'])
            values = json.loads(self.run(['findmnt', '--json', '--target', str(path), '--output', 'TARGET,SOURCE,FSTYPE,UUID,MAJ:MIN,OPTIONS']))
            if len(values['filesystems']) != 1:
                raise ValueError('ambiguous external mount')
            mount = values['filesystems'][0]
            uuid = mount.get('uuid')
            if (not isinstance(uuid, str) or not uuid or len(uuid) > 128 or not isinstance(mount.get('fstype'), str)
                    or not path.is_relative_to(absolute_path(mount['target'])) or 'ro' in mount.get('options', '').split(',')):
                raise ValueError('external mount has no pinned filesystem identity')
            if record.get('uuid') and (record['uuid'] != uuid or record.get('filesystem') != mount['fstype'] or record.get('mountpoint') != mount['target']):
                raise ValueError('external target was replaced')
            record.update(uuid=uuid, filesystem=mount['fstype'], mountpoint=mount['target'])
            major, minor = map(int, mount['maj:min'].split(':'))
            return os.makedev(major, minor), uuid
        except (Error, OSError, ValueError, KeyError, TypeError):
            raise Error('Das konfigurierte externe Sicherungsziel ist nicht mit seiner bestätigten Dateisystemkennung erreichbar.', 503) from None

    def purpose_path(self, record, purpose):
        if purpose not in PURPOSES:
            raise Error('Ungültiger Verwendungszweck für den Speicher.')
        if purpose == 'backups' and record['kind'] == 'internal':
            raise Error('Für Datensicherungen einen separaten verwalteten Speicherbereich auswählen.', 409)
        if record['kind'] == 'external':
            if purpose not in ('files', 'backups'):
                raise Error('Das bestehende externe Sicherungsziel ist nur für Dateien und Backups vorgesehen.', 409)
            return Path(record['path'])
        if record['kind'] == 'pool' and record['id'].split(':', 1)[1] in RESERVED_POOLS and purpose != 'files':
            raise Error('Dieser bestehende Pool belegt einen reservierten Titan-Datenbereich. Dateien bleiben zugänglich; neue Daten werden nicht übernommen oder umgeleitet.', 409)
        root = Path(record['path'])
        if purpose == 'files':
            return root
        if purpose == 'vms' and record['id'] == 'system':
            return Path(self.host.vm_root)  # Existing images are never moved.
        return root / purpose

    def _probe(self, record, path, write=False):
        path = absolute_path(path)
        if record['kind'] == 'internal' and path != Path(record['path']) and path.is_relative_to(record['path']):
            for pool in self._pools():
                if path.is_relative_to(Path(record['path']) / pool['name']):
                    raise Error('Dieser Datenbereich gehört zu einem verwalteten ZFS-Pool und kann nicht als interner Speicher verwendet werden. Keine Daten werden umgeleitet.', 409)
        # Verify the managed mount before probing inaccessible descendants. An
        # offline mountpoint must fail as offline, without touching fallback data.
        expected, uuid = self.device(record)
        existing = path
        while not existing.exists() and not existing.is_symlink():
            if existing == existing.parent:
                raise Error('NAS-Datenordner fehlt.', 503)
            existing = existing.parent
        if existing.is_symlink():
            raise Error('Speicherpfade dürfen keine symbolischen Links enthalten.', 403)
        directory = existing if existing.is_dir() else existing.parent
        if record['kind'] == 'pool' and directory != Path(record['path']):
            expected, uuid = self.device(record, directory)
        with directory_fd(directory) as fd:
            info, usage = os.fstat(fd), os.fstatvfs(fd)
            if info.st_dev != expected:
                raise Error('Speicherbereich wurde ausgehängt oder durch ein anderes Dateisystem ersetzt.', 503)
            if getattr(usage, 'f_flag', 0) & os.ST_RDONLY:
                raise Error('Speicherbereich ist schreibgeschützt.', 503)
            if existing != directory:
                leaf = os.stat(existing.name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(leaf.st_mode) or leaf.st_dev != expected:
                    raise Error('Dateipfad ist nicht sicher an den Speicherbereich gebunden.', 403)
            free = usage.f_bavail * usage.f_frsize
            total = getattr(usage, 'f_blocks', usage.f_bavail) * usage.f_frsize
        if record['kind'] == 'pool':
            self._remember_pool(record['id'].split(':', 1)[1], uuid[4:])
        if record['kind'] == 'external':
            self._remember_external(record)
        if write and free <= 0:
            raise Error('Der gewählte Speicherbereich ist voll. Einen anderen Bereich auswählen; Daten werden nicht umgeleitet.', 409)
        return {**record, 'root_path': record['path'], 'path': str(path), 'device': expected,
                **({'uuid': uuid} if uuid else {}), 'free_bytes': free, 'total_bytes': total,
                'available': True, 'status': 'ready' if free > 0 else 'full',
                'capabilities': self.capabilities(record)}

    @staticmethod
    def capabilities(record):
        if record['kind'] == 'internal':
            return sorted(PURPOSES - {'backups'})
        if record['kind'] == 'external':
            return ['backups', 'files']
        if record['kind'] == 'pool' and record['id'].split(':', 1)[1] in RESERVED_POOLS:
            return ['files']
        return sorted(PURPOSES)

    def resolve(self, storage='system', purpose='files', write=None):
        record = self.spec(storage)
        root = Path(record['path'])
        # A missing mountpoint never falls through to an ancestor on DATA/OS.
        with directory_fd(root) as fd:
            expected, _ = self.device(record)
            if os.fstat(fd).st_dev != expected:
                raise Error('Der ausgewählte Speicherbereich ist nicht eingehängt.', 503)
        target = self.purpose_path(record, purpose)
        verified = self._probe(record, target, purpose != 'files' if write is None else write)
        if purpose != 'files' and record['kind'] != 'external' and target.is_dir():
            with directory_fd(target) as fd:
                value = os.fstat(fd)
                if value.st_uid != os.geteuid() or value.st_mode & 0o022:
                    raise Error('Speicher-Namensräume müssen root gehören und gegen fremde Schreibzugriffe geschützt sein.', 409)
        return verified

    @contextlib.contextmanager
    def fd(self, storage='system', purpose='files', create=False, write=None):
        record = self.resolve(storage, purpose, create if write is None else write)
        path = Path(record['path'])
        with directory_fd(path.parent if create else path) as parent:
            if os.fstat(parent).st_dev != record['device']:
                raise Error('Speicher wurde vor der Dateiaktion ausgehängt. Kein Ordner wird im Ersatzverzeichnis angelegt.', 503)
            if create:
                if os.fstat(parent).st_uid != os.geteuid() or os.fstat(parent).st_mode & 0o022:
                    raise Error('Speicher-Namensräume müssen gegen fremde Schreibzugriffe geschützt sein.', 409)
                try:
                    os.mkdir(path.name, 0o755, dir_fd=parent)
                except FileExistsError:
                    pass
                child = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            else:
                child = os.dup(parent)
            try:
                verified = self._probe(self.spec(storage), path, create if write is None else write)
                if os.fstat(child).st_dev != verified['device']:
                    raise Error('Speicher wurde während der Aktion ausgetauscht.', 503)
                if create and (os.fstat(child).st_uid != os.geteuid() or os.fstat(child).st_mode & 0o022):
                    raise Error('Der vorhandene Speicher-Namensraum ist nicht gegen fremde Schreibzugriffe geschützt.', 409)
                yield child, verified
                after = self._probe(self.spec(storage), path)
                if (after['device'], after.get('uuid')) != (verified['device'], verified.get('uuid')):
                    raise Error('Speicher wurde während der Aktion ausgetauscht.', 503)
            finally:
                os.close(child)

    def validate_path(self, value, purpose='files', write=False, parent_only=False):
        candidate = absolute_path(value)
        choices = self.specs()
        matching = [record for record in choices if candidate.is_relative_to(Path(record['path']))]
        if candidate.is_relative_to(Path(self.host.vm_root)):
            matching.append(choices[0])
        # Home is an existing DATA bind, but agent/docker/libvirt configuration
        # and the raw persistence tree are deliberately outside this namespace.
        if not self.private_fixture and candidate.is_relative_to('/home'):
            matching.append(choices[0])
        if not matching:
            raise Error('Nur NAS-Daten im internen Speicher oder in eingerichteten Volumes/Pools sind zugänglich. Systemdateien sind geschützt.', 403)
        record = max(matching, key=lambda item: len(Path(item['path']).parts))
        if parent_only and candidate != Path(record['path']):
            verified = self._probe(record, candidate.parent, write)
            return {**verified, 'path': str(candidate)}
        return self._probe(record, candidate, write)

    def required_path(self, path):
        return self.validate_path(path)['device']

    def allowed_roots(self):
        paths = [Path(self.host.share_root), Path(self.host.vm_root)]
        if not self.private_fixture:
            paths.append(Path('/home'))
        paths.extend(Path(record['path']) for record in self._external_specs())
        return [str(path.relative_to(self.host.system_root)) for path in paths
                if path.is_relative_to(self.host.system_root)]

    def protected_paths(self):
        root = Path(self.host.system_root)
        paths = set(self.allowed_roots())
        for record in self.specs():
            for purpose in self.capabilities(record):
                path = self.purpose_path(record, purpose)
                if path.is_relative_to(root):
                    paths.add(str(path.relative_to(root)))
        return sorted(paths)

    def devices(self, path=None):
        root, result = Path(self.host.system_root), {}
        for record in self.specs():
            mount = Path(record['path'])
            if not mount.is_relative_to(root):
                continue
            try:
                expected = self._probe(record, mount)['device']
            except (Error, OSError):
                expected = -1  # Empty unmounted directories must never be used.
            result[str(mount.relative_to(root))] = expected
        for prefix in self.allowed_roots():
            candidate = root / prefix
            if prefix not in result:
                try:
                    result[prefix] = self.validate_path(str(candidate))['device']
                except (Error, OSError):
                    result[prefix] = -1
        if not self.private_fixture:
            # Include nested datasets and unknown mounts. A root-owned worker
            # must not wander into an unverified mount while copying a tree.
            try:
                values = json.loads(self.run(['findmnt', '--json', '--list', '--output', 'TARGET,SOURCE,FSTYPE,MAJ:MIN,OPTIONS']))
                for item in values['filesystems']:
                    mount = Path(item['target'])
                    if not any(mount.is_relative_to(root / prefix) for prefix in self.allowed_roots()):
                        continue
                    try:
                        expected = self.validate_path(str(mount))['device']
                    except (Error, OSError):
                        expected = -1
                    result[str(mount.relative_to(root))] = expected
            except (Error, OSError, ValueError, KeyError, TypeError):
                raise Error('Daten-Einhängepunkte konnten nicht vollständig geprüft werden.', 503) from None
        return result

    def inventory(self):
        records, warnings = [], []
        for spec in self.specs():
            try:
                verified = self.resolve(spec['id'])
                if spec['kind'] == 'pool':
                    self._remember_pool(spec['id'].split(':', 1)[1], verified['uuid'][4:])
                if spec['kind'] == 'external':
                    self._remember_external(verified)
                verified['backup_path'] = str(self.purpose_path(verified, 'backups')) if 'backups' in verified['capabilities'] else None
                verified['backup_eligible'] = self.backup_eligible(verified)
                records.append(verified)
            except (Error, OSError) as exc:
                records.append({**spec, 'available': False, 'status': 'offline', 'free_bytes': 0,
                                'total_bytes': 0, 'capabilities': self.capabilities(spec),
                                'backup_path': str(self.purpose_path(spec, 'backups')) if 'backups' in self.capabilities(spec) else None,
                                'backup_eligible': False, 'error': str(exc)})
        settings = self.host.load('storage-preferences', {})
        default = settings.get('default_storage', settings.get('default', 'system')) if isinstance(settings, dict) else 'system'
        if not isinstance(default, str):
            raise Error('Ungültiger gespeicherter Standardspeicher.', 503)
        if default not in {item['id'] for item in records}:
            warnings.append('Der gespeicherte Standardspeicher existiert nicht mehr; für neue Daten zuerst einen verfügbaren Bereich auswählen. Es erfolgt keine Umleitung auf den internen Speicher.')
        return {'storage': records, 'resources': records, 'default_storage': default, 'warnings': warnings}

    def backup_eligible(self, record):
        if 'backups' not in record['capabilities'] or record['status'] != 'ready':
            return False
        try:
            if self.backup_pool_conflict(record):
                return False
        except (Error, OSError):
            return False
        for source in self.backup_sources():
            try:
                with directory_fd(source) as fd:
                    if os.fstat(fd).st_dev == record['device']:
                        return False
            except (Error, OSError):
                continue
        return True

    def backup_sources(self):
        sources = [self.host.share_root, self.host.directory, self.host.vm_root]
        sources.extend(Path(item['path']) for item in self.host.op_shares())
        sources.extend(Path(item[key]) for item in self.host.load('apps', [])
                       for key in ('data', 'config_path') if item.get(key))
        return [Path(source) for source in sources]

    def backup_pool_conflict(self, record):
        """Datasets on the same ZFS pool share failure risk, not st_dev."""
        if record['kind'] != 'pool':
            return False
        guid = record.get('uuid')
        if not isinstance(guid, str) or not re.fullmatch(r'zfs:[0-9]{1,20}', guid):
            raise Error('Die Pool-Kennung des Sicherungsziels ist nicht bestätigt.', 503)
        for source in self.backup_sources():
            if source.is_relative_to(self.host.directory):
                # Agent configuration is the fixed DATA bind, outside public
                # file APIs. An unexpected mount here must also fail closed.
                if source.exists():
                    with directory_fd(source) as fd:
                        if os.fstat(fd).st_dev != self.internal_device():
                            raise Error('Der Konfigurationsspeicher ist nicht an die DATA-Partition gebunden.', 503)
                continue
            try:
                resource = self.validate_path(source)
            except (Error, OSError):
                # An offline/unverified data source cannot justify an
                # independent backup destination in this pool.
                return True
            if resource['kind'] == 'pool' and resource.get('uuid') == guid:
                return True
        return False

    def _remember_external(self, record):
        with self.host.lock:
            values = self.host.load('external-storage', [])
            previous = next((value for value in values if value['id'] == record['id']), None)
            saved = {key: record[key] for key in ('id', 'path', 'uuid', 'filesystem', 'mountpoint')}
            if previous and previous != saved:
                raise Error('Die Kennung des externen Sicherungsziels wurde verändert.', 503)
            if not previous:
                self.host.save('external-storage', values + [saved])

    def _remember_pool(self, name, guid):
        # Remember only a fully verified, mounted DATA pool. Identity is never
        # silently replaced by a newly created pool that reused the same name.
        with self.host.lock:
            values = self.host.load('pools', [])
            values = [{'name': value} if isinstance(value, str) else dict(value) for value in values]
            existing = next((value for value in values if value['name'] == name), None)
            if existing and existing.get('guid') and existing['guid'] != guid:
                raise Error('Die gespeicherte ZFS-Pool-Kennung wurde ersetzt. Keine vorhandenen Daten werden übernommen.', 503)
            if existing and existing.get('guid') == guid:
                return
            if existing:
                existing['guid'] = guid
            else:
                values.append({'name': name, 'guid': guid})
            self.host.save('pools', values)

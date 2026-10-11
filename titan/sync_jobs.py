"""Continuous one-way mirror of a share to another drive.

A mirror follows its source and is therefore not a backup: a changed or
damaged file overwrites the copy at the next run. Deleting on the target is
off by default, so a file removed by mistake stays available there.

All traversal is descriptor-bound and never follows symbolic links, like the
backup code. Symbolic links and special files are skipped.
"""
import logging
import os
from pathlib import Path
import stat
import threading
import time
from .backups import directory_fd
from .core import Error, identifier, integer

FOLDER = 'titan-sync'
PARTIAL = '.titan-sync-partial'
# Private folders of the file manager are not user data.
PRIVATE = ('.titan-trash',)
PRIVATE_PREFIX = '.titan-uploads-'
CHUNK = 1024 * 1024
DIRECTORY = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)


def empty_stats():
    return {'copied': 0, 'unchanged': 0, 'deleted': 0, 'skipped': 0, 'errors': 0, 'bytes': 0}


def _remove(parent, name):
    """Remove one entry below the directory descriptor ``parent`` without following links."""
    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode):
        os.unlink(name, dir_fd=parent)
        return
    fd = os.open(name, DIRECTORY, dir_fd=parent)
    try:
        with os.scandir(fd) as entries:
            names = [entry.name for entry in entries]
        for child in names:
            _remove(fd, child)
    finally:
        os.close(fd)
    os.rmdir(name, dir_fd=parent)


def _same(source, target):
    # FAT stores modification times in two-second steps.
    return stat.S_ISREG(target.st_mode) and source.st_size == target.st_size and abs(source.st_mtime - target.st_mtime) <= 2


def _copy(source, target, name, info, delete, stats):
    try:
        existing = os.stat(name, dir_fd=target, follow_symlinks=False)
    except FileNotFoundError:
        existing = None
    if existing is not None and _same(info, existing):
        stats['unchanged'] += 1
        return
    if existing is not None and not stat.S_ISREG(existing.st_mode):
        if not delete:
            stats['skipped'] += 1
            return
        _remove(target, name)
    reader = os.open(name, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0), dir_fd=source)
    try:
        opened = os.fstat(reader)
        if not stat.S_ISREG(opened.st_mode):
            stats['skipped'] += 1
            return
        writer = os.open(PARTIAL, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o660, dir_fd=target)
        try:
            while True:
                block = os.read(reader, CHUNK)
                if not block:
                    break
                view = memoryview(block)
                while view:
                    view = view[os.write(writer, view):]
                stats['bytes'] += len(block)
            os.utime(writer, ns=(opened.st_atime_ns, opened.st_mtime_ns))
        finally:
            os.close(writer)
        os.replace(PARTIAL, name, src_dir_fd=target, dst_dir_fd=target)
        stats['copied'] += 1
    finally:
        os.close(reader)


def mirror(source, target, delete=False, stats=None, stop=None, depth=0):
    """Make the directory behind descriptor ``target`` follow the one behind ``source``."""
    stats = empty_stats() if stats is None else stats
    if depth > 64:
        stats['skipped'] += 1
        return stats
    with os.scandir(source) as entries:
        listing = []
        for entry in entries:
            try:
                listing.append((entry.name, entry.stat(follow_symlinks=False)))
            except OSError:
                stats['errors'] += 1
    kept = set()
    for name, info in listing:
        if stop is not None and stop.is_set():
            raise Error('Abgleich wurde angehalten.', 503)
        if name == PARTIAL or (depth == 0 and (name in PRIVATE or name.startswith(PRIVATE_PREFIX))):
            continue
        kept.add(name)
        try:
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, DIRECTORY, dir_fd=source)
                try:
                    try:
                        os.mkdir(name, 0o770, dir_fd=target)
                    except FileExistsError:
                        if not stat.S_ISDIR(os.stat(name, dir_fd=target, follow_symlinks=False).st_mode):
                            if not delete:
                                stats['skipped'] += 1
                                continue
                            _remove(target, name)
                            os.mkdir(name, 0o770, dir_fd=target)
                    destination = os.open(name, DIRECTORY, dir_fd=target)
                    try:
                        mirror(child, destination, delete, stats, stop, depth + 1)
                    finally:
                        os.close(destination)
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode):
                _copy(source, target, name, info, delete, stats)
            else:
                stats['skipped'] += 1
        except Error:
            raise
        except OSError:
            stats['errors'] += 1
    if delete:
        with os.scandir(target) as entries:
            present = [entry.name for entry in entries]
        for name in present:
            if name not in kept:
                try:
                    _remove(target, name)
                    stats['deleted'] += 1
                except OSError:
                    stats['errors'] += 1
    else:
        try:
            os.unlink(PARTIAL, dir_fd=target)
        except OSError:
            pass
    return stats


class SyncMixin:
    def _sync_jobs(self):
        value = self.load('sync-jobs', [])
        return value if isinstance(value, list) else []

    def _sync_public(self, job):
        return {**job, 'running': job['share'] in getattr(self, '_sync_running', set()),
                'destination': str(Path(job['target']) / FOLDER / job['share'])}

    def op_sync_jobs(self):
        return {'jobs': [self._sync_public(job) for job in self._sync_jobs()]}

    def _sync_validate_target(self, share, target):
        path = self.backups.validate_target(target, create=True)
        source = self.open_share_root(share['path'])
        try:
            with directory_fd(path) as fd:
                if os.fstat(fd).st_dev == os.fstat(source).st_dev:
                    raise Error('Ziel und Freigabe liegen auf demselben Speicher. Für den Abgleich eine andere Platte wählen.')
        finally:
            os.close(source)
        return str(path)

    def op_sync_job_save(self, share, target, interval_minutes=15, delete=False, enabled=True):
        share = identifier(share)
        record = next((item for item in self.op_shares() if item['name'] == share), None)
        if record is None or record.get('blocked'):
            raise Error('Freigabe nicht gefunden.', 404)
        if type(delete) is not bool or type(enabled) is not bool:
            raise Error('Ungültiger Schalter.')
        interval_minutes = integer(interval_minutes, 1, 1440)
        target = self._sync_validate_target(record, target)
        jobs = [job for job in self._sync_jobs() if job['share'] != share]
        previous = next((job for job in self._sync_jobs() if job['share'] == share), {})
        job = {'share': share, 'target': target, 'interval_minutes': interval_minutes, 'delete': delete, 'enabled': enabled,
               'last_run': previous.get('last_run') if previous.get('target') == target else None,
               'last_ok': previous.get('last_ok') if previous.get('target') == target else None,
               'last_message': previous.get('last_message', '') if previous.get('target') == target else ''}
        self.save('sync-jobs', jobs + [job])
        return {'ok': True, 'job': self._sync_public(job)}

    def op_sync_job_remove(self, share):
        share = identifier(share)
        jobs = self._sync_jobs()
        if not any(job['share'] == share for job in jobs):
            raise Error('Für diese Freigabe ist kein Abgleich eingerichtet.', 404)
        self.save('sync-jobs', [job for job in jobs if job['share'] != share])
        return {'ok': True, 'data_retained': True}

    def op_sync_job_run(self, share):
        share = identifier(share)
        job = next((job for job in self._sync_jobs() if job['share'] == share), None)
        if job is None:
            raise Error('Für diese Freigabe ist kein Abgleich eingerichtet.', 404)
        return self._sync_run(job)

    @staticmethod
    def _sync_child(parent, name):
        try:
            os.mkdir(name, 0o770, dir_fd=parent)
        except FileExistsError:
            pass
        return os.open(name, DIRECTORY, dir_fd=parent)

    def _sync_run(self, job):
        if not hasattr(self, '_sync_lock'):
            self._sync_lock, self._sync_running = threading.Lock(), set()
        if not self._sync_lock.acquire(blocking=False):
            raise Error('Ein anderer Abgleich läuft gerade. Bitte kurz warten.', 409)
        self._sync_running.add(job['share'])
        stats, ok, text = empty_stats(), False, ''
        try:
            record = next((item for item in self.op_shares() if item['name'] == job['share']), None)
            if record is None or record.get('blocked'):
                raise Error('Freigabe nicht gefunden.', 404)
            target = self._sync_validate_target(record, job['target'])
            source = self.open_share_root(record['path'])
            try:
                with directory_fd(target) as base:
                    folder = self._sync_child(base, FOLDER)
                    try:
                        destination = self._sync_child(folder, job['share'])
                        try:
                            mirror(source, destination, job['delete'], stats, getattr(self, 'sync_stop', None))
                        finally:
                            os.close(destination)
                    finally:
                        os.close(folder)
            finally:
                os.close(source)
            ok = stats['errors'] == 0
            text = (f"{stats['copied']} kopiert, {stats['unchanged']} unverändert"
                    + (f", {stats['deleted']} entfernt" if stats['deleted'] else '')
                    + (f", {stats['skipped']} übersprungen" if stats['skipped'] else '')
                    + (f", {stats['errors']} Fehler" if stats['errors'] else ''))
        except (Error, OSError) as exc:
            text = str(exc)
        finally:
            self._sync_running.discard(job['share'])
            self._sync_lock.release()
            self.save('sync-jobs', [{**item, 'last_run': time.time(), 'last_ok': ok, 'last_message': text} if item['share'] == job['share'] else item
                                    for item in self._sync_jobs()])
        return {'ok': ok, 'message': text, 'stats': stats}

    def sync_due(self, now=None):
        now = time.time() if now is None else now
        return [job for job in self._sync_jobs()
                if job.get('enabled') and (not job.get('last_run') or now - job['last_run'] >= job['interval_minutes'] * 60)]

    def sync_loop(self, stop, interval=30):
        self.sync_stop = stop
        while not stop.wait(interval):
            for job in self.sync_due():
                try:
                    self._sync_run(job)
                except Error:
                    break
                except Exception as exc:
                    logging.warning('Share mirror failed: %s', type(exc).__name__)

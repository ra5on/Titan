#!/usr/bin/env python3
"""Real QCOW2 upload, import, Linux guest boot, console and orderly shutdown.

Called with the authenticated client of a disposable NAS runtime test. The
fixture is independently checksum-verified Debian, never a user disk.
"""
import hashlib
import json
from pathlib import Path
import secrets
import time
from urllib.parse import quote


def upload(client, fixture, share):
    token = secrets.token_hex(32)
    total = fixture.stat().st_size
    offset = 0
    with fixture.open('rb') as source:
        while block := source.read(4 * 1024**2):
            connection = client._connect_transport(timeout=120)
            metadata = {'share': share, 'path': 'debian.qcow2', 'upload_id': token, 'offset': offset, 'total': total}
            try:
                connection.request('POST', '/api/file-upload', block, {
                    'Host': client.HOST, 'Origin': client.ORIGIN, 'Cookie': client.cookie,
                    'X-CSRF-Token': client.csrf, 'Content-Type': 'application/octet-stream',
                    'X-Titan-Upload': quote(json.dumps(metadata), safe='')})
                response = connection.getresponse()
                raw = response.read(65537)
                if response.status != 200 or len(raw) > 65536:
                    raise RuntimeError('QCOW2 binary upload failed: HTTP ' + str(response.status))
                value = json.loads(raw)
                offset += len(block)
                if value.get('atomic') is not True or value.get('upload_id') != token or value.get('offset') != offset:
                    raise RuntimeError('QCOW2 upload acknowledgement is inconsistent.')
            finally:
                connection.close()
    completed = client.request('/api/files', {'share': share, 'path': 'debian.qcow2',
        'action': 'upload', 'upload_id': token, 'total': total, 'finish': True})
    if completed.get('complete') is not True or completed.get('offset') != total:
        raise RuntimeError('QCOW2 upload was not committed.')


def wait_guest(client, identifier, connected, timeout=300):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        details = client.request('/api/vm-extensions?vm=' + quote(identifier, safe=''))
        if connected and details.get('state') == 'running' and details.get('guest_agent', {}).get('connected') is True:
            return details
        if not connected and details.get('state') == 'shut off':
            return details
        time.sleep(3)
    raise RuntimeError('Imported QCOW2 guest did not ' + ('boot Linux and connect its agent.' if connected else 'shut down cleanly.'))


def run(smoke, fixture):
    client = smoke.client
    fixture = Path(fixture)
    if not fixture.is_file() or not 1024**2 <= fixture.stat().st_size <= 2 * 1024**3:
        raise ValueError('A bounded bootable Debian QCOW2 acceptance fixture is required.')
    provenance = json.loads(fixture.with_name('provenance.json').read_text())
    with fixture.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != provenance['fixture_sha256'] or fixture.stat().st_size != provenance['fixture_size']:
        raise ValueError('QCOW2 acceptance fixture differs from its verified build.')
    if not smoke.kvm:
        raise RuntimeError('Real QCOW2 guest acceptance requires nested KVM; it may not be skipped.')
    share = 'qcow-accept-' + secrets.token_hex(4)
    client.action('share_create', {'name': share, 'readers': [smoke.username], 'writers': [smoke.username]})
    location = next(row for row in client.request('/api/shares') if row['name'] == share)
    upload(client, fixture, share)
    source = str(Path(location['path']) / 'debian.qcow2')
    image = client.request('/api/vm-image-info?path=' + quote(source, safe=''))
    if image.get('format') != 'qcow2' or image.get('source_retained') is not True:
        raise RuntimeError('Uploaded guest is not a directly importable QCOW2 disk.')
    identifiers = []
    try:
        for mode in ('uploaded', 'nas-path'):
            vm = client.action('vm_create', {'name': 'qcow-' + mode + '-' + secrets.token_hex(3),
                'cpus': 1, 'memory_mb': 1024, 'disk_gb': max(4, image['min_disk_gb']),
                'disk_image': source, 'storage': 'system', 'firmware': 'uefi'})
            identifier = vm['id']; identifiers.append(identifier)
            if vm.get('source_retained') is not True or vm.get('disk_path') == source:
                raise RuntimeError('QCOW2 import did not preserve its source.')
            client.action('vm_guest_agent', {'vm': identifier, 'enabled': True})
            for cycle in range(2):
                client.action('vm_action', {'vm': identifier, 'action': 'start'})
                wait_guest(client, identifier, True)
                client.console_rfb(identifier)
                client.action('vm_guest_action', {'vm': identifier, 'action': 'shutdown'})
                wait_guest(client, identifier, False)
            # The second import exercises selection of a managed NAS image.
            source = vm['disk_path']
            image = client.request('/api/vm-image-info?path=' + quote(source, safe=''))
        return {'guest_os_boot': True, 'binary_upload': True, 'nas_path_import': True,
                'clean_guest_shutdown': True, 'restart': True, 'rfb_console': True,
                'fixture_sha256': digest, 'host_restart_verified': False}
    finally:
        for identifier in reversed(identifiers):
            details = client.request('/api/vm-extensions?vm=' + quote(identifier, safe=''))
            if details.get('state') != 'shut off':
                client.action('vm_action', {'vm': identifier, 'action': 'poweroff'})
            client.action('vm_remove', {'vm': identifier})
        client.action('share_remove', {'name': share})

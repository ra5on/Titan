#!/usr/bin/env python3
"""Root-owned lifecycle controller. The web container never gets Docker access.

Update: web-container.py update ghcr.io/ra5on/titan-web@sha256:... VERSION
Rollback: web-container.py rollback
Only protocol/schema-compatible images can replace the active web service.
"""
import argparse
import hashlib
import sys
import tempfile
import urllib.request
sys.path.insert(0, "/usr/lib/titan")
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import time

STATE = Path('/var/lib/titan-web/selection.json')
BUNDLED = Path('/usr/share/titan/web-image.json')
ARCHIVE = Path('/usr/share/titan/web-image.tar')
IMAGE = re.compile(r'ghcr\.io/ra5on/titan-web@sha256:[a-f0-9]{64}\Z')
VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z')


def command(*args, timeout=180):
    return subprocess.check_output(args, text=True, timeout=timeout).strip()


def read(path):
    return json.loads(path.read_text())


def save(value):
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = STATE.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(STATE)
    descriptor = os.open(STATE.parent, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_image(image, version):
    if not VERSION.fullmatch(version):
        raise ValueError('Version must have format x.x.x')
    value = json.loads(command('docker', 'image', 'inspect', image))[0]
    labels = value['Config'].get('Labels') or {}
    if (labels.get('org.titan.agent-api') != '1' or labels.get('org.titan.state-schema') != '1'
            or labels.get('org.opencontainers.image.version') != version):
        raise ValueError('Image version or host/data compatibility mismatch')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', value['Id']):
        raise ValueError('Invalid immutable Docker image identity')
    return {'image': value['Id'], 'version': version}


def switch_in_progress(state):
    if state.get('boot_id') != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
        return False
    with open('/run/lock/titan-web-update.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def selection():
    if STATE.exists():
        state = read(STATE)
        # A crash during a switch must not silently make a candidate permanent.
        if state.get('pending') and not switch_in_progress(state):
            state = {'current': state['previous'], 'previous': state['current']}
            save(state)
        return state
    return {'current': read(BUNDLED)}


def prepare():
    state = selection()
    current = state['current']
    try:
        validate_image(current['image'], current['version'])
    except subprocess.CalledProcessError:
        bundled = read(BUNDLED)
        if current != bundled:
            raise RuntimeError('Selected image is missing; refusing an implicit downgrade')
        command('docker', 'load', '--input', str(ARCHIVE), timeout=180)
        validate_image(current['image'], current['version'])


def run():
    current = selection()['current']
    account = pwd.getpwnam('titan')
    args = ['docker', 'run', '--rm', '--name', 'titan-web', '--network', 'host',
            '--user', f'{account.pw_uid}:{account.pw_gid}', '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--pids-limit', '256', '--memory', '1g',
            '--label', 'org.titan.system=web', '--env-file', '/etc/titan/web.env',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m,mode=1777']
    for path, writable in [('/var/lib/titan', True), ('/run/titan', False),
                           ('/etc/titan', False), ('/usr/share/titan', False)]:
        args += ['--mount', f'type=bind,src={path},dst={path}' + ('' if writable else ',readonly')]
    args += [current['image']]
    os.execvp('docker', args)


def healthy(version, seconds=90):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        try:
            status = json.loads(command('docker', 'inspect', 'titan-web', timeout=5))[0]
            labels = status['Config'].get('Labels') or {}
            if labels.get('org.opencontainers.image.version') == version and status['State'].get('Health', {}).get('Status') == 'healthy':
                return
        except (subprocess.SubprocessError, ValueError, KeyError, IndexError):
            pass
        time.sleep(2)
    raise RuntimeError('Web/agent/database health check failed')


def switch(target):
    previous = selection()['current']
    if target == previous:
        healthy(target['version'])
        return
    command('systemctl', 'stop', 'titan-web.service')
    # Do not use prepare/selection to read a pending switch: ExecStart must use
    # the candidate, while a reboot must fall back. A separate boot id disambiguates.
    state = {'current': target, 'previous': previous, 'pending': True,
             'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    save(state)
    try:
        command('systemctl', 'start', 'titan-web.service')
        healthy(target['version'])
    except Exception:
        command('systemctl', 'stop', 'titan-web.service')
        save({'current': previous, 'previous': target})
        command('systemctl', 'start', 'titan-web.service')
        healthy(previous['version'])
        raise
    save({'current': target, 'previous': previous})


def check_release():
    from titan import updates
    current = selection()['current']
    token = updates.read_token()
    releases = updates.strict_json(updates.fetch('https://api.github.com/repos/ra5on/Titan/releases?per_page=20', token))
    candidates = []
    for release in releases:
        if release.get('draft') or release.get('prerelease'):
            continue
        if not any(a.get('name') == 'web-container.tar.xz' for a in release.get('assets', [])):
            continue
        manifest, assets = updates.verified_release(release, token)
        item = manifest.get('web_container', {})
        if (item.get('agent_api') != 1 or item.get('state_schema') != 1
                or not VERSION.fullmatch(item.get('version', ''))
                or not re.fullmatch(r'sha256:[a-f0-9]{64}', item.get('image', ''))
                or not re.fullmatch(r'[a-f0-9]{64}', item.get('sha256', ''))
                or type(item.get('size')) is not int or not 0 < item['size'] < 512 * 1024**2):
            raise ValueError('Invalid signed web container metadata')
        candidates.append({**item, 'url': assets['web-container.tar.xz']})
    latest = max(candidates, key=lambda row: updates.version(row['version']), default=None)
    return {'current': current['version'], 'previous': selection().get('previous', {}).get('version'),
            'available': bool(latest and updates.version(latest['version']) > updates.version(current['version'])),
            'latest': latest}


def release_update(version):
    from titan import updates
    offer = check_release()
    item = offer['latest']
    if not offer['available'] or item['version'] != version:
        raise ValueError('Update offer changed; check again')
    # API assets use the existing allowlisted redirect and authentication logic.
    data = updates.fetch(item['url'], updates.read_token(), binary=True, maximum=item['size'])
    if len(data) != item['size'] or hashlib.sha256(data).hexdigest() != item['sha256']:
        raise ValueError('Web archive checksum mismatch')
    with tempfile.TemporaryDirectory(prefix='download-', dir=STATE.parent) as directory:
        archive = Path(directory) / 'web.tar.xz'
        archive.write_bytes(data)
        del data
        command('docker', 'load', '--input', str(archive), timeout=180)
    switch(validate_image(item['image'], version))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run', 'status', 'update', 'rollback', 'release'])
    parser.add_argument('image', nargs='?')
    parser.add_argument('version', nargs='?')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Root required; invoke through the host administration terminal')
    if args.action == 'prepare':
        prepare()
    elif args.action == 'run':
        run()
    elif args.action == 'status':
        print(json.dumps(selection(), indent=2))
    else:
        with open('/run/lock/titan-web-update.lock', 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action == 'release':
                STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                release_update(args.image)
                return
            if args.action == 'update':
                if not IMAGE.fullmatch(args.image or '') or not VERSION.fullmatch(args.version or ''):
                    parser.error('Use the published ghcr.io/ra5on/titan-web@sha256 digest and x.x.x version')
                command('docker', 'pull', args.image, timeout=600)
                target = validate_image(args.image, args.version)
            else:
                target = selection().get('previous')
                if not target:
                    parser.error('No previous web image available')
                validate_image(target['image'], target['version'])
            switch(target)
            print('Titan Web ' + target['version'] + ' is healthy')


if __name__ == '__main__':
    main()

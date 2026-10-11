#!/usr/bin/env python3
"""Exercise translated catalog containers only on a disposable CI runner.

This checks the compiled Compose boundary and persistent application databases,
not Titan's HTTP installer or the complete catalog. The report says so.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from titan.catalog import APPS, compose
from titan.store_recipes import recipes
from titan.umbrel_catalog import URL, compile_inventory, fetch_inventory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('app', choices=['memos', 'uptime-kuma', 'donetick'])
    parser.add_argument('--revision', required=True)
    parser.add_argument('--confirm-disposable-runner', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true' or not args.confirm_disposable_runner or os.geteuid() != 0:
        parser.error('This test requires root in an explicitly disposable GitHub runner.')
    inventory = fetch_inventory(args.revision)
    document, blocked = compile_inventory(inventory)
    selected = next((item for item in document['apps'] if item['id'] == args.app), None)
    if selected is None:
        raise RuntimeError('Selected package cannot be translated: ' + args.app)
    _, parsed = recipes({**document, 'apps': [selected]}, URL)
    key, recipe = next(iter(parsed.items()))
    APPS[key] = recipe
    root = Path(tempfile.mkdtemp(prefix='titan-umbrel-smoke-'))
    project = 'titan-catalog-' + uuid.uuid4().hex[:12]
    path = root / 'compose.json'
    checks = []
    def docker(*arguments):
        return subprocess.run(['docker','compose','--project-name',project,'-f',str(path),*arguments],
                              check=True, text=True, capture_output=True, timeout=600).stdout
    def wait_http():
        for attempt in range(120):
            try:
                with urllib.request.urlopen('http://127.0.0.1:18088/', timeout=3) as response:
                    if response.status == 200 and response.read(1024):
                        return
            except OSError:
                pass
            time.sleep(2)
        raise RuntimeError('Application web UI did not become reachable.')
    marker = uuid.uuid4().hex
    try:
        definition = compose(key, str(root), 1000, 1000, 18088, str(root/'data'), {}, config_path=str(root/'private'))
        for service in definition['services'].values():
            for binding in service['volumes']:
                directory = Path(binding['source'])
                if not directory.is_relative_to(root):
                    raise RuntimeError('Unexpected host mount in translated deployment.')
                directory.mkdir(parents=True, exist_ok=True)
                uid, gid = (service.get('user') or '1000:1000').split(':')
                os.chown(directory, int(uid), int(gid))
        from titan.umbrel_files import install as install_seeds
        install_seeds(root/'private', recipe.get('seed_files', []), definition, 1000, 1000)
        if args.app == 'donetick':
            import yaml
            seeded_config = next((root/'private').rglob('selfhosted.yaml'))
            personalized = yaml.safe_load(seeded_config.read_bytes())['jwt']['secret']
            if not re.fullmatch(r'[a-f0-9]{64}', personalized):
                raise RuntimeError('Donetick must have a private generated signing key.')
            checks.append('seeded-private-configuration')
        path.write_text(json.dumps(definition))
        os.chmod(path, 0o600)
        docker('config', '--quiet')
        checks.append('compose-valid')
        docker('pull')
        docker('up', '-d')
        wait_http()
        checks.append('web-reachable')
        if args.app == 'uptime-kuma':
            # Follow the app's browser setup API; v2 intentionally waits for
            # this choice before creating any database.
            request = urllib.request.Request('http://127.0.0.1:18088/setup-database',
                data=json.dumps({'dbConfig': {'type': 'sqlite'}}).encode(),
                headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=30) as response:
                if json.load(response).get('ok') is not True:
                    raise RuntimeError('Database setup was not accepted.')
            for attempt in range(90):
                try:
                    with urllib.request.urlopen('http://127.0.0.1:18088/setup-database-info', timeout=3) as response:
                        if json.load(response).get('needSetup') is False:
                            break
                except (OSError, ValueError):
                    pass
                time.sleep(2)
            else:
                raise RuntimeError('Database setup did not complete.')
            checks.append('browser-database-setup')
        docker('stop', '--timeout', '60')
        databases = [p for p in (root/'private').rglob('*') if p.is_file() and p.suffix in ('.db','.sqlite','.sqlite3')]
        database = next((p for p in databases if p.open('rb').read(16) == b'SQLite format 3\x00'), None)
        if database is None:
            raise RuntimeError('The application did not create a persistent SQLite database.')
        with sqlite3.connect(database) as connection:
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if not tables:
                raise RuntimeError('The application database has no schema.')
            connection.execute('CREATE TABLE titan_lifecycle_probe (value TEXT NOT NULL)')
            connection.execute('INSERT INTO titan_lifecycle_probe VALUES (?)', (marker,))
        checks.append('application-database-created')
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        docker('down')
        if hashlib.sha256(database.read_bytes()).hexdigest() != before:
            raise RuntimeError('Removing containers changed application data.')
        checks.append('remove-preserves-data')
        docker('up', '-d')
        wait_http()
        docker('stop', '--timeout', '60')
        with sqlite3.connect(database) as connection:
            if connection.execute('SELECT value FROM titan_lifecycle_probe').fetchall() != [(marker,)]:
                raise RuntimeError('Persistent application data was lost.')
        checks.append('recreate-preserves-database')
        args.output.write_text(json.dumps({'schema':1,'app':args.app,'revision':args.revision,'ok':True,
            'scope':'translated-compose-runtime','titan_installer_verified':False,'checks':checks},indent=2)+'\n')
        print(json.dumps({'app':args.app,'checks':checks}))
    finally:
        if path.exists():
            try: docker('down', '--remove-orphans')
            except subprocess.SubprocessError: pass
        shutil.rmtree(root)


if __name__ == '__main__':
    main()

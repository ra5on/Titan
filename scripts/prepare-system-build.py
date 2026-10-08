#!/usr/bin/env python3
"""Bind an explicit frozen application checkout to the current OS builder."""
import argparse
import ast
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def commit(path):
    top = subprocess.check_output(['git', '-C', str(path), 'rev-parse', '--show-toplevel'], text=True).strip()
    if Path(top).resolve() != Path(path).resolve():
        raise ValueError('Source path must be its own repository checkout')
    value = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
    if not re.fullmatch(r'[a-f0-9]{40}', value):
        raise ValueError('Invalid checkout identity')
    return value


def application_identity(path):
    path = Path(path).resolve(strict=True)
    source = path/'titan/__init__.py'
    if source.is_symlink() or not source.is_file():
        raise ValueError('Application identity must be a regular source file')
    values = {}
    for statement in ast.parse(source.read_text()).body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id in ('__version__', '__release_stage__'):
                    if target.id in values or not isinstance(statement.value, ast.Constant) or not isinstance(statement.value.value, str):
                        raise ValueError('Invalid application identity')
                    values[target.id] = statement.value.value
    if (set(values) != {'__version__', '__release_stage__'} or
            not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', values['__version__']) or
            values['__release_stage__'] not in ('alpha', 'beta', 'stable')):
        raise ValueError('Invalid application version or stage')
    return values['__version__'], values['__release_stage__']


def validate(app_root, environment, build_root=ROOT):
    app_root = Path(app_root).resolve(strict=True)
    if any(char in str(app_root) for char in '\r\n\x00'):
        raise ValueError('Invalid application source path')
    kind = environment.get('TITAN_UPDATE_KIND')
    if kind not in ('titan', 'system'):
        raise ValueError('Invalid system release kind')
    expected = environment.get('TITAN_APP_SOURCE_COMMIT', '')
    builder = environment.get('TITAN_BUILD_SOURCE_COMMIT', '')
    if not re.fullmatch(r'[a-f0-9]{40}', expected) or not re.fullmatch(r'[a-f0-9]{40}', builder):
        raise ValueError('Full source commit identities are required')
    if commit(app_root) != expected or commit(build_root) != builder:
        raise ValueError('Checked out source differs from the signed build inputs')
    payload = ['titan', 'image/firstboot.py', 'image/titan.sysusers', 'image/titan.tmpfiles', 'image/titan-firewall.xml',
               'image/titan-firstboot.service', 'image/titan-runtime.service', 'image/titan-service-containment.service', 'packaging/titan-agent.service',
               'packaging/titan-web.service', 'packaging/titan-proxy.service', 'scripts/component-functions.sh',
               'scripts/diagnose.sh', 'packaging/debian/runtime.sh', 'packaging/release-public.pem',
               'LICENSE', 'NOTICE', 'docs/DEBIAN-MIGRATION.md', 'docs/LICENSING.md', 'docs/DEBIAN-SOURCES.md']
    if subprocess.run(['git', '-C', str(app_root), 'diff', '--quiet', 'HEAD', '--', *payload], check=False).returncode:
        raise ValueError('Application payload differs from its frozen commit')
    if subprocess.check_output(['git', '-C', str(app_root), 'ls-files', '--others', '--exclude-standard', '--', *payload], text=True).strip():
        raise ValueError('Untracked application payload is not permitted')
    if kind == 'titan' and expected != builder:
        raise ValueError('Feature releases must build their current application source')
    version, stage = application_identity(app_root)
    if environment.get('TITAN_APP_VERSION') != version or environment.get('TITAN_APP_STAGE') != stage:
        raise ValueError('Frozen application version or stage differs from the build inputs')
    return {'TITAN_APP_SOURCE_ROOT': str(app_root)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        parser.error('Requires an explicitly disposable GitHub Actions builder')
    values = validate(args.app_root, os.environ)
    target = os.environ.get('GITHUB_ENV')
    if not target:
        raise ValueError('GitHub environment output is missing')
    with open(target, 'a') as stream:
        for key, value in values.items():
            stream.write(key + '=' + value + '\n')
    print('Frozen application checkout and current OS builder identities verified.')


if __name__ == '__main__':
    main()

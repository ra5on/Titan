#!/usr/bin/env python3
"""Run a frozen native app's own two-container acceptance on a disposable runner."""
import argparse
import importlib.util
import os
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--confirm-disposable-runner',action='store_true')
    args=parser.parse_args()
    if not args.confirm_disposable_runner or os.environ.get('GITHUB_ACTIONS')!='true' or os.geteuid()!=0:
        parser.error('Requires root on an explicitly confirmed disposable GitHub runner.')
    root=args.source_root.resolve(strict=True)
    if not (root/'titan/native_catalog.py').is_file():
        parser.error('The frozen source does not provide the native Compose fixture contract.')
    sys.path.insert(0,str(root))
    spec=importlib.util.spec_from_file_location('titan_frozen_compose_smoke',root/'scripts/smoke-app-packages.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    sys.argv=[str(root/'scripts/smoke-app-packages.py'),'titan-ci-compose-fixture','--confirm-disposable-runner','--app-backup-smoke']
    module.main()


if __name__=='__main__':
    main()

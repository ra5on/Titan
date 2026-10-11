#!/usr/bin/env python3
"""Emit a reproducible coverage report; --require-complete is a release gate."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from titan.umbrel_catalog import archive_inventory, compile_inventory, fetch_inventory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--revision', required=True)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-complete', action='store_true')
    args = parser.parse_args()
    inventory = (archive_inventory(args.archive.read_bytes(), args.revision)
                 if args.archive else fetch_inventory(args.revision))
    document, blocked = compile_inventory(inventory)
    report = {'schema': 1, 'revision': inventory['revision'],
              'archive_sha256': inventory['archive_sha256'],
              'total': len(inventory['packages']), 'translated': len(document['apps']),
              'runtime_verified': False,
              'complete': not blocked, 'blocked_counts': dict(Counter(row['code'] for row in blocked)),
              'translated_ids': [row['id'] for row in document['apps']], 'blocked': blocked}
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({key: report[key] for key in ('revision','total','translated','blocked_counts')}))
    if args.require_complete and blocked:
        raise SystemExit('Stable gesperrt: Umbrel-Pakete benötigen noch Laufzeitunterstützung.')


if __name__ == '__main__':
    main()

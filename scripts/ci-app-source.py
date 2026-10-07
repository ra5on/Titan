#!/usr/bin/env python3
"""Select acceptance gates from the frozen application without importing it."""
import argparse
from pathlib import Path
import re


def frozen_version(root):
    source = (Path(root) / 'titan' / '__init__.py').read_text()
    match = re.search(r'^__version__\s*=\s*[\"\'](\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z][0-9A-Za-z.-]{0,63})?[\"\']\s*$', source, re.M)
    if not match:
        raise ValueError('Frozen application version is unavailable or malformed.')
    return tuple(map(int, match.groups()))


def gate_mode(root):
    return 'native' if frozen_version(root) >= (0, 5, 8) else 'legacy'


def expanded_native(root):
    return frozen_version(root) >= (0, 5, 9)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_root', type=Path)
    args = parser.parse_args()
    try:
        print('mode=' + gate_mode(args.source_root))
        print('expanded_native=' + str(expanded_native(args.source_root)).lower())
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()

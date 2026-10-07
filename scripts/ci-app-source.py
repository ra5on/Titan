#!/usr/bin/env python3
"""Select acceptance gates from the frozen application without importing it."""
import argparse
from pathlib import Path
import re


def gate_mode(root):
    source = (Path(root) / 'titan' / '__init__.py').read_text()
    match = re.search(r'^__version__\s*=\s*[\"\'](\d+)\.(\d+)\.(\d+)[\"\']\s*$', source, re.M)
    if not match:
        raise ValueError('Frozen application version is unavailable or malformed.')
    version = tuple(map(int, match.groups()))
    return 'native' if version >= (0, 5, 8) else 'legacy'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_root', type=Path)
    args = parser.parse_args()
    try:
        print('mode=' + gate_mode(args.source_root))
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()

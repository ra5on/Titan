#!/usr/bin/env python3
"""Reserve the exact release commit before an expensive build, without retagging."""
import argparse
import json
import os
import re
import subprocess

TAG = re.compile(r'(?:web-)?v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-(?:alpha|beta)\.[0-9]+)?\Z')
SHA = re.compile(r'[a-f0-9]{40}\Z')


def reserve(tag, commit, invoke=subprocess.run):
    if not TAG.fullmatch(tag) or not SHA.fullmatch(commit):
        raise ValueError('Invalid release tag or frozen commit')
    endpoint = 'repos/ra5on/Titan/git/'
    created = invoke(['gh', 'api', '--method', 'POST', endpoint + 'refs',
                      '-f', 'ref=refs/tags/' + tag, '-f', 'sha=' + commit],
                     capture_output=True, text=True, timeout=45)
    # An existing exact tag is safe on retries. Never update or delete a tag.
    result = created if created.returncode == 0 else invoke(
        ['gh', 'api', endpoint + 'ref/tags/' + tag],
        capture_output=True, text=True, timeout=45)
    if result.returncode != 0:
        raise RuntimeError('Cannot reserve release tag. Verify repository release permissions before rebuilding.')
    value = json.loads(result.stdout)
    if (value.get('ref') != 'refs/tags/' + tag or value.get('object', {}).get('type') != 'commit'
            or value['object'].get('sha') != commit):
        raise RuntimeError('Release tag already identifies a different commit; refusing to retag it.')
    return commit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag')
    parser.add_argument('--commit', help='Exact frozen builder commit; defaults to the workflow commit')
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'ra5on/Titan':
        parser.error('Only the Titan release workflow may reserve release tags')
    reserve(args.tag, args.commit or os.environ.get('GITHUB_SHA', ''))
    print('Release tag is bound to the exact workflow commit.')


if __name__ == '__main__':
    main()

"""One-time, user-authorized cleanup of explicitly recorded obsolete refs.

Uses only the ephemeral Actions token on the Titan main root commit. Never
touches TitanOS, unlisted refs, changed branch heads, or newly created releases.
"""
import json
import os
from pathlib import Path
import urllib.request
import urllib.error


def main():
    repository = 'ra5on/Titan'
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY', '').lower() != repository.lower() or os.environ.get('GITHUB_REF') != 'refs/heads/main':
        raise SystemExit('Cleanup is restricted to Titan main on GitHub Actions.')
    token = os.environ['GH_TOKEN']
    def api(path, method='GET', payload=None):
        request = urllib.request.Request('https://api.github.com/repos/' + repository + '/' + path,
            method=method, data=json.dumps(payload).encode() if payload is not None else None, headers={'Authorization': 'Bearer ' + token,
            'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'Titan-repository-reset'})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read(1024 * 1024)
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            if exc.code == 404: return None
            raise
    head = api('git/ref/heads/main')['object']['sha']
    commit = api('git/commits/' + head)
    manifest = json.loads((Path(__file__).parents[1] / '.github/reset-manifest.json').read_text())
    tested = api('git/commits/' + os.environ['GITHUB_SHA'])
    if commit['tree']['sha'] != tested['tree']['sha'] or commit['message'] != 'Initialize Titan eigenbau with BigBear stacks':
        raise SystemExit('Cleanup requires the exact verified source tree; no changes made.')
    if commit['parents'] and (head != os.environ['GITHUB_SHA'] or len(commit['parents']) != 1 or commit['parents'][0]['sha'] != manifest['previous_main_sha']):
        raise SystemExit('Unexpected source history; no changes made.')
    # Validate every lease before performing any deletion.
    for row in manifest['refs']:
        if row['ref'] == 'heads/main' or not row['ref'].startswith(('heads/', 'tags/')):
            raise SystemExit('Invalid cleanup target.')
        current = api('git/ref/' + row['ref'])
        if current and current['object']['sha'] != row['sha']:
            raise SystemExit('An obsolete ref changed; cleanup stopped.')
    for row in manifest['releases']:
        release = api('releases/' + str(row['id']))
        if release and release['tag_name'] != row['tag_name']:
            raise SystemExit('A release changed; cleanup stopped.')
    if commit['parents']:
        root = api('git/commits', 'POST', {'message': commit['message'], 'tree': commit['tree']['sha'], 'parents': []})
        if root['parents']: raise SystemExit('New commit is not a root commit.')
        if api('git/ref/heads/main')['object']['sha'] != head:
            raise SystemExit('Main changed; no refs were overwritten.')
        api('git/refs/heads/main', 'PATCH', {'sha': root['sha'], 'force': True})
        print('New main root commit: ' + root['sha'])
    for row in manifest['releases']:
        api('releases/' + str(row['id']), 'DELETE')
        print('Removed obsolete release ' + row['tag_name'])
    for row in manifest['refs']:
        api('git/refs/' + row['ref'], 'DELETE')
        print('Removed obsolete ref ' + row['ref'])
    print('Old branches, tags and releases removed. External clones and GitHub retention are unaffected.')


if __name__ == '__main__':
    main()

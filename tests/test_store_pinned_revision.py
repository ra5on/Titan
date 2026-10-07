"""CI pins one validated upstream archive without anonymous API resolution."""
import argparse
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from titan.app_stores import StoreMixin
from titan.bigbear import URL, fetch, translate
from titan.core import Error


REVISION = 'f5e7cb7e4c5e01180d44fc459c65ae1c37c2ac20'
spec = importlib.util.spec_from_file_location('titan_package_pinned_smoke', Path(__file__).resolve().parents[1] / 'scripts/smoke-app-packages.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def source():
    return {'services':{'web':{'image':'example/web:1','ports':['8088:80']}}}


def archive():
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as result:
        result.writestr('Apps/sample/compose.yaml', json.dumps(source()))
        result.writestr('Apps/sample/metadata.json', json.dumps({'name':'Sample','port':'8088'}))
        unsafe = source(); unsafe['services']['web']['privileged'] = True
        result.writestr('Apps/unsafe/compose.yaml', json.dumps(unsafe))
        result.writestr('Apps/unsafe/metadata.json', json.dumps({'name':'Unsafe','port':'8088'}))
    return output.getvalue()


class PinnedRevisionTests(unittest.TestCase):
    def test_pinned_fetch_only_downloads_exact_commit_and_keeps_parser_safety(self):
        with patch('titan.store_sources.download', return_value=archive()) as download:
            document, skipped = fetch(REVISION)
        download.assert_called_once_with('https://codeload.github.com/bigbeartechworld/big-bear-dockge/zip/' + REVISION, 16 * 1024 ** 2)
        self.assertEqual(len(document['apps']), 1)
        self.assertEqual(document['apps'][0]['name'], 'Sample')
        self.assertEqual(skipped[0]['code'], 'permissions')

    def test_production_fetch_still_resolves_main_before_pinning_archive(self):
        with patch('titan.store_sources.download', side_effect=[json.dumps({'object':{'sha':REVISION}}).encode(), archive()]) as download:
            fetch()
        self.assertEqual(download.call_count, 2)
        self.assertEqual(download.call_args_list[0].args[0], 'https://api.github.com/repos/bigbeartechworld/big-bear-dockge/git/ref/heads/main')
        self.assertEqual(download.call_args_list[1].args[0], 'https://codeload.github.com/bigbeartechworld/big-bear-dockge/zip/' + REVISION)

    def test_revision_cannot_be_branch_path_url_or_malformed_sha(self):
        for revision in ('main', '../main', REVISION.upper(), REVISION + '/extra', 'https://example.test', None, 42):
            if revision is None: continue  # None intentionally selects production behavior.
            with self.subTest(revision=revision), patch('titan.store_sources.download') as download, self.assertRaises(Error):
                fetch(revision)
            download.assert_not_called()

    def test_pinned_and_normal_store_paths_use_identical_recipe_validation(self):
        row = translate(source(), {'name':'Sample','port':'8088'}, 'sample')
        invalid = copy.deepcopy(row); invalid.update(id='invalid', documentation='http://example.test')
        document = {'schema':1,'name':'BigBear','apps':[row, invalid]}
        with patch('titan.app_stores.fetch_document', side_effect=lambda url:(copy.deepcopy(document), [])):
            normal = StoreMixin.store_document(URL)
        with patch('titan.bigbear.fetch', return_value=(copy.deepcopy(document), [])) as pinned, patch('titan.app_stores.fetch_document') as current:
            fixed = StoreMixin.store_document(URL, bigbear_revision=REVISION)
        pinned.assert_called_once_with(REVISION)
        current.assert_not_called()
        self.assertEqual(normal, fixed)
        self.assertEqual(len(fixed[0]['apps']), 1)
        self.assertEqual(len(fixed[1]), 1)

    def test_pin_cannot_be_used_for_other_catalog_sources(self):
        with patch('titan.bigbear.fetch') as pinned, patch('titan.app_stores.fetch_document') as current, self.assertRaises(Error):
            StoreMixin.store_document('https://github.com/example/other-store', bigbear_revision=REVISION)
        pinned.assert_not_called(); current.assert_not_called()

    def test_smoke_cli_validates_and_passes_pin_before_runtime_actions(self):
        self.assertEqual(smoke.bigbear_revision(REVISION), REVISION)
        with self.assertRaises(argparse.ArgumentTypeError): smoke.bigbear_revision('main')
        class StopBeforeRuntime(Exception): pass
        with patch.object(smoke.sys, 'argv', ['smoke-app-packages.py','bigbear:nextcloud','--confirm-disposable-runner','--bigbear-revision',REVISION]), patch.dict(smoke.os.environ, {'GITHUB_ACTIONS':'true'}), patch.object(StoreMixin, 'store_document', side_effect=StopBeforeRuntime) as fetcher, self.assertRaises(StopBeforeRuntime):
            smoke.main()
        fetcher.assert_called_once_with(URL, bigbear_revision=REVISION)
        with patch.object(smoke.sys, 'argv', ['smoke-app-packages.py','titan-nextcloud-office','--confirm-disposable-runner','--bigbear-revision',REVISION]), patch.object(StoreMixin,'store_document') as fetcher, contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            smoke.main()
        self.assertEqual(caught.exception.code, 2)
        fetcher.assert_not_called()

    def test_all_workflow_bigbear_runs_use_one_explicit_revision(self):
        import yaml
        workflow = yaml.safe_load((Path(__file__).resolve().parents[1]/'.github/workflows/app-packages.yml').read_text())
        self.assertEqual(workflow['env']['BIGBEAR_REVISION'], REVISION)
        commands = [step['run'] for name,job in workflow['jobs'].items() if name.startswith('legacy-') for step in job['steps'] if 'run' in step and 'scripts/smoke-app-packages.py' in step['run']]
        self.assertEqual(len(commands), 2)
        self.assertTrue(all('--bigbear-revision "$BIGBEAR_REVISION"' in command for command in commands))


if __name__ == '__main__': unittest.main()

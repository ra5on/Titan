"""Release dispatchers share a queue, frozen app input and real VM gates."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class DebianWorkflowTests(unittest.TestCase):
    def load(self, name):
        return yaml.load((ROOT/'.github/workflows'/name).read_text(), Loader=yaml.BaseLoader)

    def test_dispatchers_serialize_and_keep_maintenance_update_only(self):
        feature=self.load('debian-image.yml');maintenance=self.load('debian-security.yml')
        self.assertEqual(feature['concurrency']['group'],maintenance['concurrency']['group'])
        self.assertEqual(maintenance['concurrency']['cancel-in-progress'],'false')
        self.assertEqual(feature['concurrency']['cancel-in-progress'],
                         "${{ github.event_name == 'push' && contains(github.event.head_commit.message, '[supersede-unpublished-release]') }}")
        self.assertEqual(feature['jobs']['identity']['if'],
                         "github.event_name != 'push' || !contains(github.event.head_commit.message, '[hold-release]')")
        self.assertEqual(feature['jobs']['hold']['if'],
                         "github.event_name == 'push' && contains(github.event.head_commit.message, '[hold-release]')")
        for document in (feature,maintenance):
            self.assertEqual(document['jobs']['build']['uses'],'./.github/workflows/debian-system-build.yml')
        reusable=self.load('debian-system-build.yml')
        self.assertNotIn('concurrency',reusable)  # Caller owns the lock; avoid nested lock deadlock.
        self.assertEqual(reusable['on']['workflow_call']['inputs']['include_image']['default'], 'false')
        self.assertEqual(reusable['on']['workflow_call']['inputs']['initial_image']['default'], 'false')
        self.assertEqual(feature['jobs']['build']['with']['include_image'], 'true')
        self.assertEqual(feature['jobs']['build']['with']['initial_image'], 'true')
        self.assertNotIn('include_image', maintenance['jobs']['build']['with'])
        self.assertIn('inputs.include_image', reusable['jobs']['system']['env']['TITAN_UPDATE_ONLY'])
        self.assertEqual(maintenance['jobs']['build']['strategy']['max-parallel'],'1')
        self.assertEqual(maintenance['on']['schedule'],[{'cron':'17 3 * * *','timezone':'Europe/Berlin'}])

    def test_application_smokes_and_payload_checkout_use_same_explicit_frozen_commit(self):
        reusable=self.load('debian-system-build.yml')
        package=self.load('app-packages.yml')
        self.assertEqual(reusable['jobs']['packages']['with']['source_ref'],'${{ inputs.source_ref }}')
        for job in package['jobs'].values():
            for step in job.get('steps',[]):
                if step.get('uses','').startswith('actions/checkout@'):
                    if step.get('name') == 'Check out current CI builder':
                        self.assertEqual(step['with']['ref'],'${{ github.sha }}')
                        self.assertEqual(step['with']['path'],'.titan-ci-builder')
                    else:
                        self.assertEqual(step['with']['ref'],'${{ inputs.source_ref || github.sha }}')
            dependency_steps=[step['run'] for step in job.get('steps',[]) if 'ci-ubuntu-dependencies.sh' in step.get('run','')]
            self.assertTrue(all('.titan-ci-builder/scripts/ci-ubuntu-dependencies.sh' in command for command in dependency_steps))
        frozen=[step for step in reusable['jobs']['system']['steps'] if step.get('name')=='Check out the frozen application source'][0]
        self.assertEqual(frozen['with']['ref'],'${{ inputs.source_ref }}')
        self.assertEqual(frozen['if'],"inputs.update_kind == 'system'")
        self.assertEqual(reusable['jobs']['system']['env']['TITAN_BUILD_SOURCE_COMMIT'],'${{ inputs.build_ref || github.sha }}')
        frozen_builder=next(row for row in reusable['jobs']['system']['steps'] if row.get('name')=='Check out exact builder for a publication retry')
        self.assertEqual(frozen_builder['with']['ref'],'${{ inputs.build_ref }}')
        self.assertEqual(frozen_builder['if'],"inputs.build_ref != ''")

    def test_real_boot_runtime_and_published_baseline_checks_precede_publication(self):
        steps=self.load('debian-system-build.yml')['jobs']['system']['steps']
        names=[step.get('name','') for step in steps]
        publish=names.index('Publish only tested signed update bundle')
        for required in ('Bind exact application and OS builder identities',
                         'Boot, HTTPS, UEFI, VNC and complete runtime checks',
                         'Real update, rollback and failure recovery'):
            self.assertLess(names.index(required),publish)
        boot=steps[names.index('Boot, HTTPS, UEFI, VNC and complete runtime checks')]['run']
        ab=steps[names.index('Real update, rollback and failure recovery')]['run']
        self.assertIn('smoke-image.sh',boot);self.assertIn('--debian-ab',boot)
        self.assertIn('--baseline-kind published-system',ab)
        self.assertIn('--baseline-bundle-sha256',ab)
        self.assertIn('--confirm-disposable-guest',ab)
        artifacts=steps[-1]['with']['path']
        self.assertNotIn('.img',artifacts)
        cleanup=steps[names.index('Remove temporary private signing material')]
        self.assertEqual(cleanup['if'],'always()')
        self.assertIn('titan-signing',cleanup['run'])
        recovery=steps[names.index('Preserve public release files if publication fails')]
        self.assertEqual(recovery['if'],"failure() && steps.publish.outcome == 'failure'")
        self.assertEqual(recovery['with']['retention-days'],'1')
        self.assertNotIn('titan-signing',recovery['with']['path'])
        self.assertNotIn('*.key',recovery['with']['path'])
        self.assertIn('SHA256SUMS.sig',recovery['with']['path'])

    def test_all_workflow_shell_blocks_parse(self):
        for path in (ROOT/'.github/workflows').glob('*.yml'):
            workflow=yaml.load(path.read_text(),Loader=yaml.BaseLoader)
            for job in workflow.get('jobs',{}).values():
                for step in job.get('steps',[]):
                    if 'run' in step:
                        source=re.sub(r'\$\{\{.*?\}\}','fixture',step['run'])
                        result=subprocess.run(['bash','-n'],input=source,text=True,capture_output=True)
                        self.assertEqual(result.returncode,0,path.name+': '+step.get('name','')+': '+result.stderr)

    def test_maintenance_baseline_refuses_an_unconfirmed_host_before_mutation(self):
        environment=dict(os.environ);environment.pop('GITHUB_ACTIONS',None)
        result=subprocess.run(['bash',str(ROOT/'scripts/prepare-maintenance-baseline.sh'),'--disposable-runner'],
                              env=environment,capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(result.stdout,b'');self.assertEqual(result.stderr,b'')

    def test_dependency_mirror_setup_refuses_local_and_self_hosted_execution(self):
        for github_actions,runner_environment in (('', ''), ('true', 'self-hosted'), ('', 'github-hosted')):
            environment={**os.environ,'GITHUB_ACTIONS':github_actions,'RUNNER_ENVIRONMENT':runner_environment}
            result=subprocess.run(['bash',str(ROOT/'scripts/ci-ubuntu-dependencies.sh'),'python3-yaml'],
                                  env=environment,capture_output=True)
            self.assertEqual(result.returncode,2)
            self.assertEqual(result.stdout,b'')
            self.assertEqual(result.stderr,b'Requires a disposable GitHub-hosted runner.\n')

    def test_unchanged_system_candidate_exits_before_evidence_signing_or_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            work=Path(temporary)
            (work/'dist/debian-image').mkdir(parents=True)
            (work/'dist/debian-image/package-changes.json').write_text('{"security_summary":{"total_packages":0}}')
            environment={**os.environ,'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'ra5on/Titan',
                         'TITAN_SYSTEM_VERSION':'0.5.3-alpha.2','TITAN_UPDATE_KIND':'system'}
            result=subprocess.run(['bash',str(ROOT/'scripts/publish-debian-system.sh')],cwd=work,
                                  env=environment,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('no maintenance release is published',result.stdout)
            self.assertEqual(list((work/'dist/debian-image').iterdir()),[work/'dist/debian-image/package-changes.json'])

    def test_publication_requires_a_complete_bounded_source_archive_sequence(self):
        # Fake only the already-independent metadata/evidence validators. This
        # exercises the actual publisher's rejection before signing or upload.
        for parts, expected in (([], 1), ([(1, 10)], 1),
                                ([(0, 10), (2, 10)], 1),
                                ([(0, 1800000001)], 1), ([(0, 0)], 1),
                                ([(0, 10), (1, 10)], 73)):
            with self.subTest(parts=parts), tempfile.TemporaryDirectory() as temporary:
                work=Path(temporary); release=work/'dist/debian-image'
                release.mkdir(parents=True); (work/'bin').mkdir()
                (work/'docs').mkdir(); (work/'docs/DEBIAN-SOURCES.md').write_text('sources')
                validator=work/'bin/python3'
                validator.write_text('#!/bin/sh\ncase "$1" in *system-release-metadata.py) exit 73;; *) exit 0;; esac\n')
                validator.chmod(0o755)
                for index, size in parts:
                    with (release/f'debian-sources.tar.part-{index:03d}').open('wb') as stream:
                        stream.truncate(size)
                environment={**os.environ,'PATH':str(work/'bin')+os.pathsep+os.environ['PATH'],
                             'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'ra5on/Titan',
                             'TITAN_SYSTEM_VERSION':'0.6.0-alpha.1','TITAN_UPDATE_KIND':'titan',
                             'TITAN_APP_SOURCE_COMMIT':'a'*40}
                result=subprocess.run(['bash',str(ROOT/'scripts/publish-debian-system.sh')],cwd=work,
                                      env=environment,text=True,capture_output=True)
                self.assertEqual(result.returncode,expected,result.stderr)
                self.assertFalse((release/'SHA256SUMS').exists())

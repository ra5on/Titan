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
        self.assertEqual(reusable['jobs']['system']['env']['TITAN_BUILD_SOURCE_COMMIT'],'${{ github.sha }}')

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
        self.assertEqual(steps[-2]['if'],'always()')
        self.assertIn('titan-signing',steps[-2]['run'])

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

"""Independent release streams must preserve one monotonic, signed A/B history."""
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from titan import updates, debian_updates
from titan.core import Error
from update_fixtures import identity, manifest, state


def stream(version, kind='titan', app='0.5.3', stage='alpha', revision=1, source='a'*40):
    global_stage = 'alpha' if '-alpha.' in version else 'beta' if '-beta.' in version else 'stable'
    return {**manifest(version, global_stage), 'update_kind': kind,
            'titan_version': app, 'titan_stage': stage, 'titan_source_commit': source,
            'source_commit': ('b'*40 if kind == 'system' else source), 'system_revision': revision}


def release(value):
    tag = 'v'+value['version']
    return {'tag_name': tag, 'name': 'Titan '+tag, 'draft': False,
            'prerelease': value['release_stage'] != 'stable',
            'body': 'Signed changes', 'html_url': 'https://github.com/ra5on/Titan/releases/tag/'+tag,
            'assets': [{'name': name, 'url': 'https://api.github.com/assets/'+tag+'/'+name}
                       for name in ('manifest.json', 'manifest.json.sig', value['bundle']['name'])]}


class StreamSelectionTests(unittest.TestCase):
    def check(self, installed, offers, kind='all', channel='alpha', status_changes=None):
        items = [release(item) for item in offers]
        by_tag = {'v'+item['version']: item for item in offers}
        verified = []
        def authenticate(item, token=None):
            verified.append(item['tag_name'])
            return copy.deepcopy(by_tag[item['tag_name']]), {asset['name']: asset['url'] for asset in item['assets']}
        with ExitStack() as stack:
            stack.enter_context(patch.object(debian_updates, 'image_info', return_value=installed))
            stack.enter_context(patch.object(debian_updates, 'system_status', return_value={**state(installed['version']), **(status_changes or {})}))
            stack.enter_context(patch.object(updates, 'fetch', return_value=json.dumps(items).encode()))
            stack.enter_context(patch.object(updates, 'verified_release', side_effect=authenticate))
            stack.enter_context(patch.object(updates, 'architecture', return_value='x86_64'))
            return updates.check('ra5on/Titan', channel, update_kind=kind), verified

    def test_independent_streams_choose_their_signed_kind(self):
        installed = stream('0.5.3-alpha.1')
        os_update = stream('0.5.3-alpha.2', 'system', revision=2)
        titan_update = stream('0.5.4-alpha.1', app='0.5.4', source='c'*40)
        result, checked = self.check(installed, [os_update, titan_update], 'system')
        self.assertEqual(result['latest'], 'v0.5.3-alpha.2')
        self.assertEqual(result['release_kind'], 'system')
        self.assertEqual(result['titan_version'], '0.5.3')
        self.assertEqual(result['latest_titan_version'], '0.5.3')
        self.assertEqual(result['latest_system_revision'], 2)
        self.assertEqual(result['selection_kind'], 'system')
        self.assertTrue(result['available'])
        self.assertEqual(checked, ['v0.5.4-alpha.1', 'v0.5.3-alpha.2'])
        result, _ = self.check(installed, [os_update, titan_update], 'titan')
        self.assertEqual(result['latest'], 'v0.5.4-alpha.1')
        self.assertTrue(result['available'])

    def test_system_candidate_matches_frozen_titan_commit_as_well_as_version(self):
        installed = stream('0.5.3-alpha.1')
        compatible = stream('0.5.3-alpha.2', 'system', revision=2)
        for mutation in ({'titan_version': '0.5.4'}, {'titan_stage': 'beta'}, {'titan_source_commit': 'c'*40}):
            foreign = {**stream('0.5.3-alpha.3', 'system', revision=3), **mutation}
            with self.subTest(mutation=mutation):
                result, _ = self.check(installed, [foreign, compatible], 'system')
                self.assertEqual(result['latest'], 'v0.5.3-alpha.2')
                self.assertTrue(result['available'])

    def test_only_foreign_system_release_never_becomes_offer(self):
        result, _ = self.check(stream('0.5.3-alpha.1'), [stream('0.5.3-alpha.2', 'system', source='c'*40, revision=2)], 'system')
        self.assertFalse(result['available'])
        self.assertNotIn('latest', result)

    def test_system_stage_can_differ_from_frozen_app_stage(self):
        installed = stream('0.5.3-alpha.1')
        system = stream('0.5.3', 'system', stage='alpha', revision=2)
        result, _ = self.check(installed, [system], 'system', 'stable')
        self.assertTrue(result['available'])
        self.assertEqual(result['latest_stage'], 'stable')
        self.assertEqual(result['latest_titan_stage'], 'alpha')

    def test_global_system_version_prevents_stale_titan_or_system_downgrade(self):
        installed = stream('0.5.3-alpha.20', 'system', revision=20)
        for target in (stream('0.5.3-alpha.1'), stream('0.5.3-alpha.19', 'system', revision=21)):
            with self.subTest(target=target):
                result, _ = self.check(installed, [target])
                self.assertFalse(result['available'])
        result, _ = self.check(installed, [stream('0.5.4-alpha.1', app='0.5.4', source='c'*40)], 'titan')
        self.assertTrue(result['available'])

    def test_global_stable_patch_is_separate_from_app_version(self):
        installed = stream('0.5.9', 'system', stage='stable', revision=7)
        # Seven OS builds advanced the global line but not the Titan app. The
        # next Titan 0.5.4 build uses the allocator's later global version.
        target = stream('0.5.10', app='0.5.4', stage='stable', source='c'*40)
        result, _ = self.check(installed, [target], 'titan', 'stable')
        self.assertTrue(result['available'])
        self.assertEqual(result['titan_version'], '0.5.3')
        self.assertEqual(result['latest_titan_version'], '0.5.4')

    def test_later_global_version_cannot_downgrade_titan_app(self):
        installed = stream('0.5.9', app='0.5.4', stage='stable')
        target = stream('0.5.10', app='0.5.3', stage='stable', source='c'*40)
        result, _ = self.check(installed, [target], 'titan', 'stable')
        self.assertFalse(result['available'])
        self.assertNotIn('latest', result)

    def test_newer_app_maintenance_bundle_can_deliver_titan_upgrade_after_os_patches(self):
        installed = stream('0.5.10', 'system', stage='stable', revision=8)
        newer_app_os = stream('0.5.11', 'system', app='0.5.4', stage='stable', source='c'*40, revision=3)
        for kind in ('titan', 'all'):
            result, _ = self.check(installed, [newer_app_os], kind, 'stable')
            self.assertTrue(result['available'])
            self.assertEqual(result['latest_titan_version'], '0.5.4')
            self.assertEqual(result['release_kind'], 'system')
            self.assertEqual(result['selection_kind'], kind)
        result, _ = self.check(installed, [newer_app_os], 'system', 'stable')
        self.assertFalse(result['available'])
        self.assertNotIn('latest', result)

    def test_newer_app_bundle_with_stale_global_version_is_not_offered(self):
        installed = stream('0.5.10', 'system', stage='stable', revision=8)
        target = stream('0.5.9', 'system', app='0.5.4', stage='stable', source='c'*40, revision=3)
        for kind in ('all', 'titan', 'system'):
            result, checked = self.check(installed, [target], kind, 'stable')
            self.assertFalse(result['available'])
            self.assertNotIn('latest', result)
            self.assertEqual(checked, [])

    def test_same_app_stage_foreign_source_system_bundle_cannot_claim_titan_upgrade(self):
        target = stream('0.5.3-alpha.4', 'system', source='c'*40, revision=4)
        for kind in ('all', 'titan', 'system'):
            result, _ = self.check(stream('0.5.3-alpha.3', revision=3), [target], kind)
            self.assertFalse(result['available'])
            self.assertNotIn('latest', result)

    def test_stable_system_release_cannot_smuggle_new_alpha_app_into_titan_stable(self):
        installed = stream('0.5.3', stage='stable')
        target = stream('0.5.4', 'system', app='0.5.4', stage='alpha', source='c'*40, revision=2)
        for kind in ('all', 'titan'):
            for channel in ('stable', 'beta'):
                with self.subTest(kind=kind, channel=channel):
                    result, _ = self.check(installed, [target], kind, channel)
                    self.assertFalse(result['available'])
                    self.assertNotIn('latest', result)
            result, _ = self.check(installed, [target], kind, 'alpha')
            self.assertTrue(result['available'])

    def test_system_revision_must_advance_and_new_app_can_reset_revision(self):
        installed = stream('0.5.3-alpha.3', 'system', revision=3)
        for revision in (1, 3):
            result, _ = self.check(installed, [stream('0.5.3-alpha.4', 'system', revision=revision)], 'system')
            self.assertFalse(result['available'])
        target = stream('0.5.4-alpha.1', app='0.5.4', source='c'*40, revision=1)
        result, _ = self.check(installed, [target], 'titan')
        self.assertTrue(result['available'])

    def test_legacy_published_release_remains_installable_transition(self):
        installed = identity('0.5.2-alpha.1')
        result, _ = self.check(installed, [stream('0.5.3-alpha.1')], 'titan')
        self.assertTrue(result['available'])
        self.assertEqual(result['system_revision'], 0)
        self.assertIsNone(result['titan_source_commit'])
        result, _ = self.check(installed, [manifest('0.5.3-alpha.1', 'alpha')], 'titan')
        self.assertTrue(result['available'])
        self.assertEqual(result['release_kind'], 'titan')

    def test_invalid_selection_rejected_before_network_or_system_access(self):
        for kind in ('security', '', None, [], False):
            with self.subTest(kind=kind), patch.object(updates, 'fetch') as fetch, patch.object(debian_updates, 'image_info') as info, self.assertRaises(Error):
                updates.check('ra5on/Titan', 'alpha', update_kind=kind)
            fetch.assert_not_called()
            info.assert_not_called()

    def test_signature_or_health_failure_never_offers_installation(self):
        target = stream('0.5.3-alpha.2', 'system', revision=2)
        for mutation in ({'health_confirmed': False}, {'reboot_required': True}, {'reboot_scheduled': True}):
            result, _ = self.check(stream('0.5.3-alpha.1'), [target], 'system', status_changes=mutation)
            self.assertFalse(result['available'])
        with patch.object(updates, 'verified_release', side_effect=Error('signature failed')):
            # Authentication is explicitly mocked by the helper, so exercise
            # check directly at this trust boundary.
            with patch.object(debian_updates, 'image_info', return_value=stream('0.5.3-alpha.1')), patch.object(debian_updates, 'system_status', return_value=state()), patch.object(updates, 'fetch', return_value=json.dumps([release(target)]).encode()):
                result = updates.check('ra5on/Titan', 'alpha', update_kind='system')
        self.assertFalse(result['available'])
        self.assertIn('signature failed', result['error'])

    def test_signed_package_summary_is_exposed_with_the_selected_offer(self):
        target = stream('0.5.3-alpha.2', 'system', revision=2)
        target['package_changes'] = [{'name': 'openssl', 'old_version': '3.5.1-1', 'new_version': '3.5.1-2', 'security': True}]
        target['security_summary'] = {'total_packages': 7, 'security_packages': 2, 'checked_at': '2026-10-04T12:00:00Z'}
        result, _ = self.check(stream('0.5.3-alpha.1'), [target], 'system')
        self.assertEqual(result['package_changes'], target['package_changes'])
        self.assertEqual(result['security_summary'], target['security_summary'])


class SignedMetadataSchemaTests(unittest.TestCase):
    def test_invalid_new_identity_fields_fail_closed(self):
        good = stream('0.5.3-alpha.1')
        for field, bad in (('update_kind', 'image'), ('update_kind', []), ('titan_version', '0.5.3-alpha.1'),
                           ('titan_stage', []), ('titan_source_commit', 'wrong'), ('system_revision', True),
                           ('system_revision', 0), ('system_revision', 2**31)):
            with self.subTest(field=field, bad=bad), self.assertRaises(Error):
                debian_updates.validate_identity({**good, field: bad})
        for field in ('update_kind', 'titan_version', 'titan_stage', 'titan_source_commit', 'system_revision'):
            bad = dict(good); bad.pop(field)
            with self.subTest(missing=field), self.assertRaises(Error):
                debian_updates.validate_identity(bad)

    def test_package_metadata_rejects_duplicate_names_bad_dates_and_unbounded_lists(self):
        good = stream('0.5.3-alpha.1')
        change = {'name': 'libssl3t64:amd64', 'old_version': None, 'new_version': '3.5.1-2', 'security': True}
        summary = {'total_packages': 1, 'security_packages': 1, 'checked_at': '2026-10-04T12:00:00Z'}
        debian_updates.validate_identity({**good, 'package_changes': [change], 'security_summary': summary})
        bad_reports = [({'name': '../openssl'}, None), ({'security': 1}, None), ({'new_version': 'x\n'}, None), ({'extra': True}, None)]
        for changes, _ in bad_reports:
            with self.subTest(changes=changes), self.assertRaises(Error):
                debian_updates.validate_identity({**good, 'package_changes': [{**change, **changes}]})
        for report in ({'package_changes': [change, change]}, {'package_changes': [change]*61},
                       {'package_changes': [change], 'security_summary': {**summary, 'security_packages': 0}},
                       {'security_summary': {**summary, 'checked_at': '2026-10-04T12:00:00'}},
                       {'security_summary': {**summary, 'checked_at': 'invalid'}},
                       {'security_summary': {**summary, 'checked_at': '2026-10-04T14:00:00+02:00'}}):
            with self.subTest(report=report), self.assertRaises(Error):
                debian_updates.validate_identity({**good, **report})

    def test_rollback_deployment_retains_its_own_app_and_system_identity(self):
        value = stream('0.5.3-alpha.7', 'system', revision=7)
        deployment = debian_updates.deployment('B', {'identity': value, 'confirmed': True})
        self.assertEqual(deployment['release_kind'], 'system')
        self.assertEqual(deployment['titan_version'], '0.5.3')
        self.assertEqual(deployment['system_revision'], 7)
        self.assertEqual(deployment['titan_source_commit'], 'a'*40)


class InstallCompatibilityTests(unittest.TestCase):
    def test_changed_kind_or_frozen_app_rejected_before_backup_and_rauc(self):
        installed = stream('0.5.3-alpha.1')
        offer = {'available': True, 'latest': 'v0.5.3-alpha.2', 'latest_stage': 'alpha',
                 'assets': {}, 'url': 'https://github.com/ra5on/Titan/releases/tag/v0.5.3-alpha.2'}
        for target in (stream('0.5.3-alpha.2', 'titan'), stream('0.5.3-alpha.2', 'system', revision=2, source='c'*40),
                       stream('0.5.3-alpha.1', 'system', revision=2)):
            with self.subTest(target=target), patch.object(debian_updates, 'check', return_value=offer), patch.object(updates, 'read_token', return_value=None), patch.object(updates, 'verified_release', return_value=(target, {})), patch.object(debian_updates, 'image_info', return_value=installed), patch.object(updates, 'backup_configuration') as backup, patch.object(debian_updates, 'run') as run, self.assertRaises(Error):
                debian_updates.install.__wrapped__.__wrapped__('ra5on/Titan', 'alpha', offer['latest'], '/unused', 'system')
            backup.assert_not_called()
            run.assert_not_called()

    def test_reverified_app_stage_blocks_alpha_payload_in_stable_titan_install(self):
        installed = stream('0.5.3', stage='stable')
        target = stream('0.5.4', 'system', app='0.5.4', stage='alpha', source='c'*40, revision=2)
        offer = {'available': True, 'latest': 'v0.5.4', 'latest_stage': 'stable',
                 'assets': {}, 'url': 'https://github.com/ra5on/Titan/releases/tag/v0.5.4'}
        with patch.object(debian_updates, 'check', return_value=offer), patch.object(updates, 'read_token', return_value=None), patch.object(updates, 'verified_release', return_value=(target, {})), patch.object(debian_updates, 'image_info', return_value=installed), patch.object(updates, 'backup_configuration') as backup, patch.object(debian_updates, 'run') as run, self.assertRaises(Error):
            debian_updates.install.__wrapped__.__wrapped__('ra5on/Titan', 'stable', offer['latest'], '/unused', 'titan')
        backup.assert_not_called()
        run.assert_not_called()

    def test_prepared_slot_preserves_signed_app_identity_for_future_system_checks(self):
        installed = stream('0.5.3-alpha.1')
        target = stream('0.5.3-alpha.2', 'system', revision=2)
        offer = {'available': True, 'latest': 'v0.5.3-alpha.2', 'latest_stage': 'alpha',
                 'assets': {}, 'url': 'https://github.com/ra5on/Titan/releases/tag/v0.5.3-alpha.2'}
        current = state(installed['version'])
        saved = []
        activated = []
        def activate(slot, record, value, kind):
            activated.append(copy.deepcopy(record))
            return {'staged': debian_updates.deployment(slot, record)}
        def run(args, **kwargs):
            return json.dumps({'filesystems': []}) if args[0] == 'findmnt' else ''
        slots = {'A': {}, 'B': {'slot_status': {'checksum': {'sha256': target['rootfs_sha256']},
                                             'bundle': {'build': target['release_id']}}}}
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            for owner, name, kwargs in ((debian_updates, 'check', {'return_value': offer}),
                    (updates, 'read_token', {'return_value': None}),
                    (updates, 'verified_release', {'return_value': (target, {target['bundle']['name']: 'https://api.github.com/assets/bundle'})}),
                    (debian_updates, 'image_info', {'return_value': installed}),
                    (debian_updates, 'system_status', {'return_value': current}),
                    (updates, 'backup_configuration', {'return_value': '/private/config.sqlite3'}),
                    (debian_updates, 'download', {'side_effect': lambda url, path, *args: path.write_bytes(b'bundle')}),
                    (debian_updates, 'run', {'side_effect': run}),
                    (debian_updates, 'verify_devices', {'return_value': None}),
                    (debian_updates, 'rauc_status', {'return_value': ({}, slots, 'A')}),
                    (debian_updates, 'load_state', {'return_value': {'schema': 1, 'slots': {}}}),
                    (debian_updates, 'save_state', {'side_effect': lambda value: saved.append(copy.deepcopy(value))}),
                    (debian_updates, 'activate', {'side_effect': activate})):
                stack.enter_context(patch.object(owner, name, **kwargs))
            stack.enter_context(patch.object(debian_updates, 'CACHE', Path(temporary)))
            stack.enter_context(patch.object(Path, 'resolve', lambda value, strict=False: value))
            result = debian_updates.install.__wrapped__.__wrapped__('ra5on/Titan', 'alpha', offer['latest'], '/unused', 'system')
        self.assertEqual(len(activated), 1)
        self.assertEqual(result['staged']['titan_source_commit'], installed['titan_source_commit'])
        self.assertEqual(result['staged']['system_revision'], 2)
        self.assertEqual(result['release_kind'], 'system')
        self.assertEqual(saved[0]['slots'], {})
        persisted = activated[0]['identity']
        debian_updates.validate_identity(persisted)
        for field in ('update_kind', 'titan_version', 'titan_stage', 'titan_source_commit', 'system_revision', 'source_commit'):
            self.assertEqual(persisted[field], target[field])


if __name__ == '__main__':
    unittest.main()

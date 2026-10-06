import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('package_state_test', Path(__file__).resolve().parents[1]/'scripts/debian-package-state.py')
packages = importlib.util.module_from_spec(spec); spec.loader.exec_module(packages)


def inventory(*records):
    return {'format': packages.FORMAT, 'suite': 'trixie', 'architecture': 'amd64',
            'generated_at': '2026-10-04T12:00:00Z', 'packages': [
                {'name': name, 'version': version, 'architecture': 'amd64'} for name, version in records]}


def candidate(version, security=False, trusted=True, origin='Debian', label=None):
    return SimpleNamespace(candidate=SimpleNamespace(version=version, origins=[SimpleNamespace(
        trusted=trusted, origin=origin, label=label or ('Debian-Security' if security else 'Debian'),
        archive='trixie-security' if security else 'trixie')]))


class PackageStateTests(unittest.TestCase):
    def test_dpkg_inventory_ignores_removed_packages_and_is_sorted(self):
        data = 'openssl\t3.5.1-2\tamd64\tinstalled\nzlib1g\t1:1.3.1-1\tamd64\tinstalled\nold-package\t1.0\tamd64\tconfig-files\n'
        with patch.object(packages.subprocess, 'check_output', return_value=data): value = packages.inventory()
        self.assertEqual([item['name'] for item in value['packages']], ['openssl', 'zlib1g'])

    def test_invalid_inventory_is_rejected(self):
        mutations = [lambda p: p.update(suite='sid'), lambda p: p.update(architecture='arm64'),
                     lambda p: p.update(generated_at='missing'), lambda p: p.update(generated_at='2026-10-04T12:00:00'),
                     lambda p: p.update(packages=[]), lambda p: p['packages'].append(copy.deepcopy(p['packages'][0])),
                     lambda p: p['packages'][0].update(version='1\nunsafe'), lambda p: p['packages'][0].update(version='💻'),
                     lambda p: p['packages'][0].update(name='../unsafe'), lambda p: p['packages'][0].update(architecture='i386')]
        for mutation in mutations:
            value = inventory(('openssl', '3.5.1-1')); mutation(value)
            with self.subTest(value=value), self.assertRaises(ValueError): packages.validate(value)

    def test_inventory_does_not_exceed_download_size_limit(self):
        value = inventory(*[('p' + str(index).zfill(127), '1' * 256) for index in range(5000)])
        with self.assertRaises(ValueError): packages.validate(value)

    def test_only_newer_official_debian_candidates_trigger_updates(self):
        before = inventory(('newer', '1'), ('same', '2'), ('older', '3'), ('missing', '1'))
        cache = {'newer': candidate('2', True), 'same': candidate('2'), 'older': candidate('2')}
        changes = packages.candidates(before, cache, lambda a,b: int(a)-int(b))
        self.assertEqual(changes, [{'name': 'newer', 'old_version': '1', 'new_version': '2', 'security': True}])

    def test_non_debian_or_untrusted_candidate_is_not_accepted(self):
        before = inventory(('openssl', '1'))
        for value in (candidate('2', origin='Ubuntu'), candidate('2', trusted=False), candidate('2', label='Other')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                packages.candidates(before, {'openssl': value}, lambda a,b: int(a)-int(b))

    def test_security_label_cannot_be_spoofed_by_another_origin(self):
        self.assertFalse(packages.security_origin(candidate('2', security=True, origin='Other').candidate))
        self.assertFalse(packages.security_origin(candidate('2', security=True, trusted=False).candidate))
        self.assertTrue(packages.security_origin(candidate('2', security=True).candidate))

    def test_preview_is_byte_bounded_security_first_and_keeps_full_counts(self):
        changes = [{'name': 'p' + str(index).zfill(127), 'old_version': '1' * 256,
                    'new_version': '2' * 256, 'security': index % 2 == 1} for index in range(100)]
        report = packages.summary(changes)
        self.assertLessEqual(len(json.dumps(report['package_changes'], indent=2).encode()), packages.MAX_PREVIEW_BYTES)
        self.assertLessEqual(len(report['package_changes']), packages.MAX_PREVIEW_PACKAGES)
        self.assertTrue(all(item['security'] for item in report['package_changes']))
        self.assertEqual(report['security_summary']['total_packages'], 100)
        self.assertEqual(report['security_summary']['security_packages'], 50)

    def test_actual_changes_include_new_packages_but_exclude_titan_application_version(self):
        before = inventory(('openssl', '1'), ('same', '2'), ('titan-debian-preview', '0.5.2+debian1'))
        after = inventory(('openssl', '2'), ('same', '2'), ('new-package', '1'), ('titan-debian-preview', '0.5.3+debian1'))
        cache = {'openssl': candidate('2', True), 'new-package': candidate('1')}
        report = packages.actual_changes(before, after, cache)
        self.assertEqual(report['security_summary']['total_packages'], 2)
        self.assertEqual(report['security_summary']['security_packages'], 1)
        self.assertEqual(report['package_changes'][1]['old_version'], None)
        self.assertEqual(report['package_changes'][1]['name'], 'new-package')

    def test_actual_package_downgrade_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            packages.actual_changes(inventory(('openssl', '2')), inventory(('openssl', '1')), {}, lambda a,b: int(a)-int(b))


if __name__ == '__main__': unittest.main()

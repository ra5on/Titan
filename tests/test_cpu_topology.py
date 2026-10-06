from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import xml.etree.ElementTree as ET
from titan.core import Error
from titan.cpu_topology import CpuMixin, cpu_list, topology, demo_topology


class CPUTopologyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cpus, self.pmus = self.root / 'cpus', self.root / 'pmus'
        self.cpus.mkdir(); self.pmus.mkdir()
        (self.cpus / 'present').write_text('0-3,8')
        (self.cpus / 'online').write_text('0,2-3')
        for cpu in (0, 1, 2, 3, 8):
            base = self.cpus / f'cpu{cpu}' / 'topology'
            base.mkdir(parents=True)
            (base / 'core_id').write_text(str(cpu % 2))
            (base / 'physical_package_id').write_text('0')
            (base / 'thread_siblings_list').write_text('0,2' if cpu in (0, 2) else str(cpu))

    def tearDown(self):
        self.temp.cleanup()

    def group(self, name, ids):
        directory = self.pmus / name
        directory.mkdir()
        (directory / 'cpus').write_text(ids)

    def test_sparse_online_ids_include_cpu_zero_and_offline_slots(self):
        result = topology(self.cpus, self.pmus)
        self.assertEqual(result['online'], [0, 2, 3])
        self.assertEqual([cpu['id'] for cpu in result['cpus']], [0, 1, 2, 3, 8])
        self.assertFalse(result['cpus'][1]['online'])
        self.assertEqual(result['cpus'][0]['siblings'], [0, 2])
        self.assertTrue(all(cpu['core_type'] == 'unknown' for cpu in result['cpus']))
        self.assertFalse(result['hybrid_detected'])

    def test_explicit_kernel_pmu_groups_classify_pe_and_lowpower(self):
        self.group('cpu_core', '0,2'); self.group('cpu_atom', '1,3,8'); self.group('cpu_lowpower', '8')
        result = topology(self.cpus, self.pmus)
        self.assertTrue(result['hybrid_detected'])
        self.assertEqual([cpu['core_type'] for cpu in result['cpus']],
                         ['performance', 'efficiency', 'performance', 'efficiency', 'efficiency'])
        self.assertEqual(result['cpus'][-1]['subtype'], 'low-power')

    def test_overlapping_types_are_unknown_instead_of_guessed(self):
        self.group('cpu_core', '0,2'); self.group('cpu_atom', '0,3')
        result = topology(self.cpus, self.pmus)
        self.assertEqual(result['cpus'][0]['core_type'], 'unknown')
        self.assertTrue(result['warnings'])

    def test_invalid_online_fails_manual_selection_closed(self):
        (self.cpus / 'online').write_text('0-100000')
        result = topology(self.cpus, self.pmus)
        self.assertEqual(result['online'], [])
        self.assertFalse(any(cpu['online'] for cpu in result['cpus']))
        self.assertTrue(result['warnings'])

    def test_missing_present_uses_directory_ids_without_guessing_online(self):
        (self.cpus / 'present').unlink()
        self.assertEqual([cpu['id'] for cpu in topology(self.cpus, self.pmus)['cpus']], [0, 1, 2, 3, 8])

    def test_list_validation_bounds_and_sparse_ranges(self):
        self.assertEqual(cpu_list('0-2,8,10-12'), [0, 1, 2, 8, 10, 11, 12])
        for value in ('3-0', '-1', '0,,2', 'x', '0-65536', '0-8192', '0,^2'):
            with self.subTest(value=value), self.assertRaises(ValueError): cpu_list(value)

    def test_demo_is_explicit_and_all_ids_online(self):
        result = demo_topology()
        self.assertEqual(result['source'], 'demo')
        self.assertEqual(result['online'], list(range(8)))
        self.assertEqual(result['cpus'][0]['siblings'], [0, 2])


class CPUAffinityTests(unittest.TestCase):
    def setUp(self):
        self.host = CpuMixin()
        self.host.cpu_topology = Mock(return_value={'online': [0, 2, 3, 8]})

    def test_invalid_or_offline_selection_and_oversubscription_rejected(self):
        for ids in ([1], [True], ['0'], [0, 0], '0', [-1], [65536]):
            with self.subTest(ids=ids), self.assertRaises(Error): self.host.validate_vm_cpu_ids(1, ids)
        with self.assertRaises(Error): self.host.validate_vm_cpu_ids(3, [0, 2])
        self.assertEqual(self.host.validate_vm_cpu_ids(2, [8, 0, 3]), [0, 3, 8])

    def test_auto_does_not_depend_on_cpu_discovery(self):
        for ids in (None, []): self.assertEqual(self.host.validate_vm_cpu_ids(2, ids), [])
        self.host.cpu_topology.assert_not_called()

    def test_selected_pool_covers_cpu_zero_and_clears_individual_overrides(self):
        root = ET.fromstring('<domain><vcpu current="2">2</vcpu><cputune><shares>1024</shares><vcpupin vcpu="0" cpuset="3"/><emulatorpin cpuset="3"/><iothreadpin iothread="1" cpuset="3"/></cputune></domain>')
        self.assertEqual(self.host.apply_vm_cpu_policy(root, 2, [2, 0]), [0, 2])
        self.assertEqual(root.find('vcpu').get('cpuset'), '0,2')
        self.assertEqual(self.host.vm_cpu_ids(root), [0, 2])
        self.assertEqual(root.find('cputune/shares').text, '1024')
        self.assertIsNone(root.find('cputune/vcpupin'))
        self.host.apply_vm_cpu_policy(root, 2, [])
        self.assertIsNone(root.find('vcpu').get('cpuset'))
        self.assertEqual(self.host.vm_cpu_ids(root), [])

    def test_unknown_cpu_mask_not_silently_replaced(self):
        with self.assertRaises(Error): self.host.vm_cpu_ids(ET.fromstring('<domain><vcpu cpuset="0-3,^2">2</vcpu></domain>'))

    def test_external_per_thread_overrides_are_not_silently_discarded(self):
        for tag in ('vcpupin', 'emulatorpin', 'iothreadpin'):
            with self.subTest(tag=tag), self.assertRaises(Error):
                self.host.vm_cpu_ids(ET.fromstring(f'<domain><vcpu>2</vcpu><cputune><{tag} cpuset="2"/></cputune></domain>'))

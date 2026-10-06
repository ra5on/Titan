"""Real import/Compose/budget regression for the disposable release guest."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from titan.app_memory import GIB, MIB, check_install_memory, limit_bytes, package_memory_plan
from titan.catalog import APPS, validate_options
from titan.compose_templates import build
from titan.core import Error
from titan.store_recipes import recipes


ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://raw.githubusercontent.com/ra5on/Titan/main/tests/fixtures/runtime-stack-store.json'


class RuntimeStackMemoryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((ROOT / 'tests/fixtures/runtime-stack-store.json').read_text())
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.proc = Path(self.temporary.name)
        # Firmware/kernel reservations make MemTotal smaller than QEMU's -m.
        # The NAS/daemon baseline leaves less available RAM than total RAM.
        self.total = 3 * GIB - 96 * MIB
        self.available = 2 * GIB + 384 * MIB
        self.write_memory(self.available)

    def write_memory(self, available):
        (self.proc / 'meminfo').write_text(
            f'MemTotal: {self.total // 1024} kB\n'
            f'MemAvailable: {available // 1024} kB\n'
            'MemFree: 98304 kB\n'
            'SwapTotal: 4194304 kB\n'
            'SwapFree: 4194304 kB\n')

    def imported(self, document):
        _, parsed = recipes(document, SOURCE)
        self.assertEqual(len(parsed), 1)
        app = next(iter(parsed))
        registry = patch.dict(APPS, parsed)
        registry.start()
        self.addCleanup(registry.stop)
        return app, parsed[app], validate_options(app, {})

    def test_fixture_import_compose_and_live_preflight_fit_real_three_gib_guest(self):
        app, recipe, options = self.imported(self.fixture)
        plan = package_memory_plan(app, options)
        definition = build(app, recipe, '/apps/runtime', 1000, 1000, 18080, '/nas/runtime', options)
        self.assertEqual(len(definition['services']), 2)
        compose_limits = [limit_bytes(service['mem_limit']) for service in definition['services'].values()]
        self.assertEqual(compose_limits, [512 * MIB, 512 * MIB])
        self.assertEqual([service['limit_bytes'] for service in plan['services']], compose_limits)
        self.assertEqual(plan['startup_limit_bytes'], GIB)

        # This reads MemAvailable through the production snapshot helper. The
        # budget implementation, import parser and Compose builder are real.
        result = check_install_memory(app, options, containers=[], vms=[], proc=self.proc)
        self.assertTrue(result['allowed'])
        self.assertEqual(result['total_bytes'], self.total)
        self.assertEqual(result['available_bytes'], self.available)
        self.assertEqual(result['system_reserve_bytes'], 512 * MIB)
        self.assertEqual(result['installation_headroom_bytes'], 512 * MIB)
        self.assertEqual(result['required_available_bytes'], 2 * GIB)
        self.assertTrue(result['limits_fit_capacity'])

    def test_previous_missing_limits_inherit_one_gib_each_and_are_rejected(self):
        previous = copy.deepcopy(self.fixture)
        for service in previous['apps'][0]['stack']['services'].values():
            service.pop('memory', None)
        app, recipe, options = self.imported(previous)
        plan = package_memory_plan(app, options)
        definition = build(app, recipe, '/apps/runtime', 1000, 1000, 18080, '/nas/runtime', options)
        self.assertEqual([limit_bytes(service['mem_limit']) for service in definition['services'].values()], [GIB, GIB])
        self.assertEqual(plan['startup_limit_bytes'], 2 * GIB)
        self.assertGreater(plan['startup_limit_bytes'] + 512 * MIB + 512 * MIB, self.total)
        with self.assertRaises(Error) as caught:
            check_install_memory(app, options, containers=[], vms=[], proc=self.proc)
        self.assertEqual(caught.exception.status, 409)
        self.assertIn('keine neuen Dienste gestartet', str(caught.exception))

    def test_smaller_fixture_still_enforces_real_available_ram_and_running_caps(self):
        app, _, options = self.imported(self.fixture)
        self.write_memory(GIB + 768 * MIB)
        with self.assertRaises(Error) as caught:
            check_install_memory(app, options, containers=[], vms=[], proc=self.proc)
        self.assertEqual(caught.exception.status, 409)

        self.write_memory(self.available)
        running = [{'Id': 'a' * 64, 'State': {'Running': True}, 'HostConfig': {'Memory': GIB}}]
        with self.assertRaises(Error) as caught:
            check_install_memory(app, options, containers=running, vms=[], proc=self.proc)
        self.assertEqual(caught.exception.status, 409)


if __name__ == '__main__':
    unittest.main()

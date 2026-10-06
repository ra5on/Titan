import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from titan.app_metrics import AppMetricsMixin, cgroup_memory, cgroup_memory_details


class CgroupMemoryTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        proc = root / 'proc/42'
        proc.mkdir(parents=True)
        directory = root / 'groups/system.slice/docker.scope'
        directory.mkdir(parents=True)
        (proc / 'cgroup').write_text('0::/system.slice/docker.scope\n')
        return root, directory

    def test_total_cache_swap_and_limits_are_distinct_observed_counters(self):
        root, directory = self.fixture()
        for source, value in {'memory.current': '104857600', 'memory.stat': 'anon 52428800\nfile 41943040\nkernel 10485760\n',
                              'memory.swap.current': '4096', 'memory.max': '1073741824', 'memory.events': 'oom 2\noom_kill 1\n'}.items():
            (directory / source).write_text(value)
        sample = cgroup_memory_details(42, root / 'proc', root / 'groups')
        self.assertEqual(sample['memory_bytes'], 104857600)
        self.assertEqual(sample['memory_cache_bytes'], 41943040)
        self.assertEqual(sample['memory_anon_bytes'], 52428800)
        self.assertEqual(sample['memory_swap_bytes'], 4096)
        self.assertEqual(sample['memory_limit_bytes'], 1073741824)
        self.assertEqual(sample['oom_kills'], 1)

    def test_missing_optional_counters_do_not_invent_zero_or_host_total(self):
        root, directory = self.fixture()
        (directory / 'memory.current').write_text('100')
        (directory / 'memory.max').write_text('max')
        sample = cgroup_memory_details(42, root / 'proc', root / 'groups')
        self.assertEqual(sample['memory_bytes'], 100)
        self.assertIsNone(sample['memory_limit_bytes'])
        self.assertIsNone(sample['memory_cache_bytes'])
        self.assertIsNone(sample['oom_kills'])

    def test_cgroup_path_cannot_escape_and_negative_or_nonfinite_counts_fail(self):
        root, directory = self.fixture()
        source = directory / 'memory.current'
        for invalid in ('-1', 'NaN', str(2 ** 64)):
            source.write_text(invalid)
            self.assertIsNone(cgroup_memory(42, root / 'proc', root / 'groups'))
        (root / 'proc/42/cgroup').write_text('0::/../../etc\n')
        self.assertIsNone(cgroup_memory_details(42, root / 'proc', root / 'groups'))

    def test_optional_office_variant_queries_only_actual_installed_services(self):
        root, _ = self.fixture()
        record = {'id': 'titan-nextcloud-office'}
        path = root / 'apps/titan-nextcloud-office'
        path.mkdir(parents=True)
        names = ['titan-nextcloud-office', 'titan-nextcloud-office-redis', 'titan-nextcloud-office-database', 'titan-nextcloud-office-cron']
        (path / 'compose.json').write_text(json.dumps({'services': {key: {} for key in names}}))
        seen = []
        class Host(AppMetricsMixin):
            directory = root
            def load(self, name, default): return [record]
            def managed_app(self, app): return record
            def _app_container(self, app, record, service_key):
                seen.append(service_key)
                return {'State': {'Running': True, 'Pid': 42}}
        measurements = {'memory_bytes': 100, 'memory_cache_bytes': 50, 'memory_swap_bytes': 0, 'memory_limit_bytes': 1000, 'oom_kills': 0}
        stats = '\n'.join(json.dumps({'Name': 'titan-' + name, 'CPUPerc': '0%', 'MemUsage': '50B / 1000B', 'BlockIO': '0B / 0B'}) for name in names)
        with patch('titan.app_metrics.cgroup_memory_details', return_value=measurements), patch('titan.app_management._run', return_value=stats):
            result = Host().op_app_metrics()['apps'][record['id']]
        self.assertEqual(seen, names)
        self.assertEqual(result['memory_bytes'], 400, 'Total charge includes cache; CLI working set is not substituted.')
        self.assertEqual(result['memory_cache_bytes'], 200)
        self.assertEqual(result['memory_limit_bytes'], 4000)


if __name__ == '__main__': unittest.main()

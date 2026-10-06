import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from titan.app_memory import (GIB, MIB, check_install_memory, check_start_memory, limit_bytes,
    memory_health, memory_preflight, memory_snapshot, package_memory_plan)
from titan.app_memory import check_vm_start_memory, vm_memory_reservations, vm_overhead
from titan.app_memory import check_container_start_memory
from titan.app_packages import PACKAGES, prepare_options, selected_recipe
from titan.app_package_setup import provision
from titan.catalog import catalog, compose, published_ports, validate_options
from titan.core import Error


def ram(total=8, available=7, occupied=7.9, pressure=None):
    return {'memory_total': int(total * GIB), 'memory_available': int(available * GIB),
        'memory_occupied': int(occupied * GIB), 'memory_free': int((total - occupied) * GIB),
        'memory_pressure': pressure or {'available': True, 'some_avg10': 0, 'full_avg10': 0}}


def options(office='disabled', profile='balanced'):
    return validate_options('titan-nextcloud-office', prepare_options('titan-nextcloud-office',
        {'password': 'PrivatePassword123', 'office_mode': office, 'resource_profile': profile}))


class AppMemoryTests(unittest.TestCase):
    def setUp(self):
        # Unit tests never consult a developer/CI host's actual hypervisor.
        hypervisor = patch('titan.app_memory.vm_memory_reservations', return_value=[])
        hypervisor.start()
        self.addCleanup(hypervisor.stop)

    def test_fresh_defaults_are_bounded_but_legacy_options_keep_office_and_recipe(self):
        fresh = prepare_options('titan-nextcloud-office', {'password': 'PrivatePassword123'})
        self.assertEqual(fresh['resource_profile'], 'balanced')
        self.assertEqual(fresh['office_mode'], 'disabled')
        previous = {'password': 'PreviousPassword', 'database_password': 'd' * 64, 'office_secret': 'o' * 64}
        retained = prepare_options('titan-nextcloud-office', {'password': 'NewPassword123'}, previous)
        self.assertEqual(retained['resource_profile'], 'legacy')
        self.assertEqual(retained['office_mode'], 'enabled')
        self.assertEqual(retained['office_secret'], previous['office_secret'])
        self.assertEqual(validate_options('titan-nextcloud-office', previous)['office_mode'], 'enabled')

    def test_nextcloud_without_office_keeps_all_mandatory_dependencies_and_no_office_port(self):
        value = options()
        definition = compose('titan-nextcloud-office', '/apps/nc', 1000, 1000, 8088, '/nas/nc', value)
        self.assertEqual(set(definition['services']), {'titan-nextcloud-office', 'titan-nextcloud-office-database', 'titan-nextcloud-office-redis', 'titan-nextcloud-office-cron'})
        self.assertNotIn(9980, {item['host'] for item in published_ports('titan-nextcloud-office', 8088, value)})
        full = compose('titan-nextcloud-office', '/apps/nc', 1000, 1000, 8088, '/nas/nc', options('enabled'))
        self.assertEqual(len(full['services']), 6)
        self.assertIn(9980, {item['host'] for item in published_ports('titan-nextcloud-office', 8088, options('enabled'))})

    def test_schema_enum_cannot_inject_arbitrary_commands_or_limits(self):
        for key, bad in (('resource_profile', 'balanced; id'), ('resource_profile', 'unlimited'), ('office_mode', 'false')):
            values = options()
            values[key] = bad
            with self.assertRaises(Error): validate_options('titan-nextcloud-office', values)

    def test_profile_resolution_never_mutates_shared_catalog(self):
        original = copy.deepcopy(PACKAGES['titan-nextcloud-office'])
        selected = selected_recipe('titan-nextcloud-office', PACKAGES['titan-nextcloud-office'], options())
        self.assertNotIn('eurooffice', selected['stack']['services'])
        self.assertEqual(PACKAGES['titan-nextcloud-office'], original)
        main = selected['stack']['services']['nextcloud']
        self.assertEqual(main['environment']['PHP_MEMORY_LIMIT'], '512M')
        self.assertIn('MaxRequestWorkers 3', main['command'][0])
        self.assertIn('exec /entrypoint.sh apache2-foreground', main['command'][0])
        self.assertEqual(selected['stack']['services']['database']['command'][0], 'postgres')

    def test_cache_services_have_explicit_data_volume(self):
        for name in ('titan-immich', 'titan-nextcloud-office'):
            self.assertEqual(PACKAGES[name]['stack']['services']['redis']['mounts'][0]['target'], '/data')

    def test_package_plan_is_limits_not_claimed_usage_and_excludes_nonconcurrent_office_init(self):
        full = package_memory_plan('titan-nextcloud-office', options('enabled'))
        steady = sum(item['limit_bytes'] for item in full['services'] if not item['one_shot'])
        self.assertEqual(full['startup_limit_bytes'], steady)
        self.assertTrue(full['office_enabled'])
        self.assertIn('kein gemessener', full['semantics'])
        base = package_memory_plan('titan-nextcloud-office', options())
        self.assertLess(base['startup_limit_bytes'], full['startup_limit_bytes'])
        self.assertEqual(base['container_count'], 4)
        self.assertEqual(base['startup_limit_bytes'], int(3.75 * GIB))

    def test_public_catalog_exposes_safe_default_and_optional_office_without_credentials(self):
        value = next(item for item in catalog(include_legacy=True)['apps'] if item['id'] == 'titan-nextcloud-office')
        self.assertEqual(value['containers_default'], 4)
        self.assertEqual(len(value['dependencies']), 4)
        self.assertEqual(len(value['optional_dependencies']), 2)
        self.assertNotIn('database_password', str(value['memory_plan']))
        self.assertFalse(value['memory_plan']['office_enabled'])

    def test_97_percent_occupied_cache_with_usable_ram_allows_base_nextcloud(self):
        result = check_install_memory('titan-nextcloud-office', options(), telemetry=ram(available=6.5))
        self.assertTrue(result['allowed'])
        self.assertEqual(result['health']['level'], 'normal')
        self.assertEqual(result['system_reserve_bytes'], GIB)

    def test_office_on_8gb_refuses_before_download_with_useful_message(self):
        with self.assertRaises(Error) as caught:
            check_install_memory('titan-nextcloud-office', options('enabled'), telemetry=ram())
        self.assertEqual(caught.exception.status, 409)
        self.assertIn('Office abwählen', str(caught.exception))
        self.assertIn('keine neuen Dienste', str(caught.exception))

    def test_sufficient_ram_allows_office_without_assuming_swap_is_ram(self):
        result = check_install_memory('titan-nextcloud-office', options('enabled'), telemetry=ram(total=16, available=14))
        self.assertTrue(result['allowed'])
        low = {**ram(available=.5), 'swap_total': 16 * GIB, 'swap_used': 0}
        with self.assertRaises(Error): check_install_memory('titan-adguard', telemetry=low)

    def test_actual_pressure_blocks_even_with_apparently_available_ram(self):
        for pressure in ({'some_avg10': 20, 'full_avg10': 0}, {'some_avg10': 0, 'full_avg10': 5}):
            with self.subTest(pressure=pressure):
                with self.assertRaises(Error): check_install_memory('titan-adguard', telemetry=ram(pressure=pressure))

    def test_missing_available_ram_fails_closed(self):
        for values in ({}, {'memory_total': 8 * GIB, 'memory_available': None}, {'memory_total': 8 * GIB, 'memory_available': 9 * GIB}):
            with self.assertRaises(Error) as caught: memory_preflight(values, GIB)
            self.assertEqual(caught.exception.status, 503)

    def test_running_caps_leave_room_for_nas_instead_of_overcommitting_idle_apps(self):
        running = [{'Name': '/other', 'State': {'Running': True}, 'HostConfig': {'Memory': 6 * GIB}}]
        with self.assertRaises(Error): check_install_memory('titan-nextcloud-office', options(), running, telemetry=ram())
        result = check_install_memory('titan-adguard', containers=running, telemetry=ram())
        self.assertTrue(result['allowed'])

    def test_start_repair_does_not_budget_already_running_member_twice(self):
        definition = {'services': {'app': {'container_name': 'titan-app', 'mem_limit': '2g'}, 'db': {'container_name': 'titan-db', 'mem_limit': '512m'}}}
        running = [{'Name': '/titan-app', 'State': {'Running': True}, 'HostConfig': {'Memory': 2 * GIB}}]
        result = check_start_memory('app', {}, definition, running, telemetry=ram())
        self.assertEqual(result['package_limit_bytes'], 512 * MIB)
        self.assertEqual(result['running_limit_bytes'], 2 * GIB)

    def test_successful_init_is_not_counted_as_a_new_start(self):
        definition = {'services': {'app-office-init': {'container_name': 'titan-app-office-init', 'mem_limit': '512m'},
                                   'app-eurooffice': {'container_name': 'titan-app-eurooffice', 'mem_limit': '4g'}}}
        rows = [{'Name': '/titan-app-office-init', 'State': {'Status': 'exited', 'ExitCode': 0}}]
        result = check_start_memory('app', {}, definition, rows, telemetry=ram(total=16, available=14))
        self.assertEqual(result['package_limit_bytes'], 4 * GIB)

    def test_no_new_members_does_not_block_noop_during_low_memory(self):
        definition = {'services': {'app': {'container_name': 'titan-app', 'mem_limit': '2g'}}}
        rows = [{'Name': '/titan-app', 'State': {'Running': True}, 'HostConfig': {'Memory': 2 * GIB}}]
        self.assertTrue(check_start_memory('app', {}, definition, rows, telemetry=ram(available=.1))['allowed'])

    def test_no_office_variant_provisions_cron_only(self):
        host = Mock()
        host.managed_app.return_value = {'id': 'titan-nextcloud-office'}
        host._app_container.return_value = {'Id': 'a' * 64}
        host._app_options.return_value = options()
        host.load.return_value = [{'id': 'titan-nextcloud-office'}]
        run = Mock(return_value='')
        provision(host, 'titan-nextcloud-office', run)
        self.assertEqual(run.call_count, 1)
        self.assertIn('background:cron', run.call_args.args[0])
        self.assertTrue(host.save.call_args.args[1][0]['package_initialized'])

    def test_new_profile_and_optional_office_are_never_forced_over_previous_choices(self):
        retained = prepare_options('titan-nextcloud-office', {'password': 'NextPassword123'}, options('enabled', 'performance'))
        self.assertEqual(retained['office_mode'], 'enabled')
        self.assertEqual(retained['resource_profile'], 'performance')

    def test_memory_health_distinguishes_recent_oom_from_historical_counters(self):
        self.assertEqual(memory_health({**ram(), 'memory_oom_kills': 50})['level'], 'normal')
        self.assertEqual(memory_health({**ram(), 'memory_oom_kills_delta': 1})['level'], 'warning')
        self.assertEqual(memory_health(ram(available=.5))['level'], 'critical')

    def test_memory_snapshot_uses_available_and_optional_psi_not_free_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            proc = Path(temporary)
            (proc / 'meminfo').write_text('MemTotal: 8388608 kB\nMemAvailable: 6815744 kB\nMemFree: 102400 kB\n')
            value = memory_snapshot(proc)
            self.assertEqual(value['memory_available'], int(6.5 * GIB))
            self.assertFalse(value['memory_pressure']['available'])
            (proc / 'meminfo').write_text('MemTotal: 10 kB\nMemAvailable: 11 kB\n')
            with self.assertRaises(Error): memory_snapshot(proc)

    def test_limit_parser_rejects_unlimited_or_code(self):
        self.assertEqual(limit_bytes('1536m'), 1536 * MIB)
        self.assertEqual(limit_bytes(4 * GIB), 4 * GIB)
        for bad in ('unlimited', '0g', '-1g', '4g; id', 0, -1, None): self.assertIsNone(limit_bytes(bad))


class ContainerMemoryBudgetTests(unittest.TestCase):
    def container(self, identifier='a' * 64, memory=6 * GIB, active=True, name='/manual'):
        return {'Id': identifier, 'Name': name, 'State': {'Running': active, 'Status': 'running' if active else 'exited'},
                'HostConfig': {'Memory': memory}}

    def test_new_manual_container_uses_limit_without_vm_overhead(self):
        result = check_container_start_memory('2g', containers=[], vms=[], telemetry=ram())
        self.assertTrue(result['allowed'])
        self.assertEqual(result['package_limit_bytes'], 2 * GIB)
        self.assertEqual(result['required_available_bytes'], 3 * GIB)

    def test_additional_manual_container_cannot_overcommit_running_container_caps(self):
        with self.assertRaises(Error) as caught:
            check_container_start_memory(2 * GIB, [self.container()], vms=[], telemetry=ram())
        self.assertEqual(caught.exception.status, 409)
        self.assertIn('Obergrenzen', str(caught.exception))

    def test_running_vm_future_allocation_is_included_before_new_container_starts(self):
        vm = {'id': 'guest', 'assigned_bytes': 6 * GIB, 'overhead_bytes': vm_overhead(6 * GIB),
              'limit_bytes': 6 * GIB + vm_overhead(6 * GIB)}
        with self.assertRaises(Error):
            check_container_start_memory(2 * GIB, vms=[vm], telemetry=ram())

    def test_unlimited_or_unknown_target_limit_always_blocks_even_active_restart(self):
        for limit in (None, 0, -1, True, False, '0g', 'unlimited', 2 ** 63):
            with self.subTest(limit=limit), self.assertRaises(Error) as caught:
                check_container_start_memory(limit, [self.container(memory=limit)], vms=[], telemetry=ram(), container='a' * 64)
            self.assertEqual(caught.exception.status, 409)

    def test_active_immutable_target_limit_is_not_counted_twice(self):
        result = check_container_start_memory(6 * GIB, [self.container()], vms=[], telemetry=ram(available=2), container='a' * 64)
        self.assertTrue(result['allowed'])
        self.assertEqual(result['package_limit_bytes'], 0)
        self.assertEqual(result['running_limit_bytes'], 6 * GIB)

    def test_stopped_target_is_counted_even_if_an_active_container_has_the_same_name(self):
        rows = [self.container(), self.container(identifier='b' * 64, memory=2 * GIB, active=False)]
        with self.assertRaises(Error):
            check_container_start_memory(2 * GIB, rows, vms=[], telemetry=ram(), container='b' * 64)

    def test_unknown_short_duplicate_or_changed_target_is_not_a_budget_exemption(self):
        for identifier, rows, limit, status in (('manual', [self.container()], 6 * GIB, 503),
                ('b' * 64, [self.container()], 6 * GIB, 503),
                ('a' * 64, [self.container(), self.container()], 6 * GIB, 503),
                ('a' * 64, [self.container()], 4 * GIB, 409)):
            with self.subTest(identifier=identifier[:8]), self.assertRaises(Error) as caught:
                check_container_start_memory(limit, rows, vms=[], telemetry=ram(), container=identifier)
            self.assertEqual(caught.exception.status, status)

    def test_missing_ram_unknown_libvirt_and_swap_do_not_invent_capacity(self):
        with self.assertRaises(Error) as caught:
            check_container_start_memory(GIB, vms=[], telemetry={})
        self.assertEqual(caught.exception.status, 503)
        with patch('titan.app_memory.vm_memory_reservations', side_effect=Error('unknown', 503)):
            with self.assertRaises(Error) as caught: check_container_start_memory(GIB, telemetry=ram())
        self.assertEqual(caught.exception.status, 503)
        with self.assertRaises(Error):
            check_container_start_memory(2 * GIB, vms=[], telemetry={**ram(available=1), 'swap_total': 100 * GIB})

    def test_installation_headroom_applies_to_manual_creation(self):
        self.assertTrue(check_container_start_memory(2 * GIB, vms=[], telemetry=ram(available=3))['allowed'])
        with self.assertRaises(Error):
            check_container_start_memory(2 * GIB, vms=[], telemetry=ram(available=3), installation=True)

    def test_active_unbounded_foreign_container_blocks_additional_apps_vms_and_manual_containers(self):
        for bad in (None, 0, False, 'unlimited', -1):
            rows = [self.container(memory=bad)]
            checks = (lambda: check_container_start_memory(GIB, rows, vms=[], telemetry=ram()),
                      lambda: check_install_memory('titan-adguard', containers=rows, vms=[], telemetry=ram()),
                      lambda: check_start_memory('app', {}, {'services': {'app': {'mem_limit': '512m'}}}, containers=rows, vms=[], telemetry=ram()),
                      lambda: check_vm_start_memory(GIB, containers=rows, vms=[], telemetry=ram()))
            for callback in checks:
                with self.subTest(limit=bad), self.assertRaises(Error) as caught: callback()
                self.assertEqual(caught.exception.status, 409)
                self.assertIn('laufender Docker-Container', str(caught.exception))

    def test_stopped_unbounded_foreign_container_does_not_claim_future_running_capacity(self):
        result = check_container_start_memory(GIB, [self.container(memory=0, active=False)], vms=[], telemetry=ram())
        self.assertTrue(result['allowed'])
        self.assertEqual(result['running_limit_bytes'], 0)


class VMMemoryBudgetTests(unittest.TestCase):
    first = '12345678-1234-1234-1234-123456789abc'
    second = 'abcdefab-1234-1234-1234-123456789abc'

    def xml(self, identifier=None, amount='6', unit='GiB', current='256'):
        return f'<domain type="kvm"><uuid>{identifier or self.first}</uuid><memory unit="{unit}">{amount}</memory><currentMemory unit="MiB">{current}</currentMemory></domain>'

    def vm(self, assigned=6, identifier=None):
        allocated = int(assigned * GIB)
        overhead = vm_overhead(allocated)
        return {'id': identifier or self.first, 'assigned_bytes': allocated, 'overhead_bytes': overhead, 'limit_bytes': allocated + overhead}

    def test_all_active_foreign_and_paused_domains_use_full_memory_not_balloon_target(self):
        run = Mock(side_effect=[self.first + '\n' + self.second + '\n', self.xml(self.first), self.xml(self.second, '2')])
        value = vm_memory_reservations(run, tool_present=True)
        self.assertEqual(run.call_args_list[0].args[0], ['virsh', '--connect', 'qemu:///system', 'list', '--uuid'])
        self.assertEqual({vm['id'] for vm in value}, {self.first, self.second})
        allocated = next(item for item in value if item['id'] == self.first)
        self.assertEqual(allocated['assigned_bytes'], 6 * GIB, 'A small balloon target cannot conceal future guest allocation.')
        self.assertGreater(allocated['limit_bytes'], allocated['assigned_bytes'])
        self.assertEqual(run.call_count, 3)

    def test_no_libvirt_tool_means_no_guests_but_installed_unreachable_daemon_fails_closed(self):
        run = Mock(side_effect=Error('connection failed with secret'))
        self.assertEqual(vm_memory_reservations(run, tool_present=False), [])
        run.assert_not_called()
        with self.assertRaises(Error) as caught: vm_memory_reservations(run, tool_present=True)
        self.assertEqual(caught.exception.status, 503)
        self.assertNotIn('secret', str(caught.exception))

    def test_zero_active_guests_is_accepted_only_after_successful_active_query(self):
        run = Mock(return_value='\n')
        self.assertEqual(vm_memory_reservations(run, tool_present=True), [])
        self.assertEqual(run.call_count, 1)

    def test_memory_units_are_explicit_and_default_kib_is_supported(self):
        for amount, unit, expected in (('512', 'MiB', 512 * MIB), ('512', 'M', 512 * MIB), ('512', 'mebibytes', 512 * MIB), ('1', 'GB', 1000 ** 3), ('1048576', 'KiB', GIB), ('1073741824', 'bytes', GIB)):
            run = Mock(side_effect=[self.first, self.xml(amount=amount, unit=unit)])
            self.assertEqual(vm_memory_reservations(run, tool_present=True)[0]['assigned_bytes'], expected)
        xml = f'<domain><uuid>{self.first}</uuid><memory>1048576</memory></domain>'
        self.assertEqual(vm_memory_reservations(Mock(side_effect=[self.first, xml]), tool_present=True)[0]['assigned_bytes'], GIB)

    def test_unknown_live_memory_uuid_or_xml_is_not_treated_as_zero_ram(self):
        invalid = [self.xml(amount='-1'), self.xml(amount='0'), self.xml(unit='bananas'), self.xml(self.second),
                   f'<domain><uuid>{self.first}</uuid><currentMemory>1</currentMemory></domain>',
                   '<!DOCTYPE domain><domain/>', '<bad', self.xml(amount=str(2 ** 63))]
        for xml in invalid:
            with self.subTest(xml=xml[:60]), self.assertRaises(Error) as caught:
                vm_memory_reservations(Mock(side_effect=[self.first, xml]), tool_present=True)
            self.assertEqual(caught.exception.status, 503)

    def test_active_inventory_has_bounded_count_and_never_executes_untrusted_domain_names(self):
        for output in ('--help', 'foreign-name', '\n'.join([self.first] * 257)):
            run = Mock(return_value=output)
            with self.assertRaises(Error): vm_memory_reservations(run, tool_present=True)
            self.assertEqual(run.call_count, 1)
        run = Mock(side_effect=[self.first + '\n' + self.first, self.xml()])
        self.assertEqual(len(vm_memory_reservations(run, tool_present=True)), 1)
        self.assertEqual(run.call_count, 2)

    def test_8gb_nas_rejects_6gb_vm_with_existing_nextcloud_stack_and_nas_reserve(self):
        containers = [{'Name': '/nextcloud', 'State': {'Running': True}, 'HostConfig': {'Memory': int(3.75 * GIB)}}]
        with self.assertRaises(Error) as caught:
            check_vm_start_memory(6 * GIB, containers, vms=[], telemetry=ram(available=7))
        self.assertEqual(caught.exception.status, 409)
        self.assertIn('Obergrenzen', str(caught.exception))

    def test_new_nextcloud_cannot_overcommit_a_running_6gb_vm_even_with_low_current_rss(self):
        with self.assertRaises(Error) as caught:
            check_install_memory('titan-nextcloud-office', options(), telemetry=ram(), vms=[self.vm()])
        self.assertEqual(caught.exception.status, 409)
        self.assertIn('laufende VMs', str(caught.exception))

    def test_small_vm_and_bounded_cloud_fit_8gb_without_inventing_extra_swap_capacity(self):
        containers = [{'Name': '/nextcloud', 'State': {'Running': True}, 'HostConfig': {'Memory': int(3.75 * GIB)}}]
        result = check_vm_start_memory(2 * GIB, containers, vms=[], telemetry=ram(available=4))
        self.assertTrue(result['allowed'])
        self.assertEqual(result['package_limit_bytes'], 2 * GIB + 256 * MIB)
        self.assertEqual(result['system_reserve_bytes'], GIB)
        installed = check_install_memory('titan-nextcloud-office', options(), telemetry=ram(), vms=[self.vm(2)])
        self.assertTrue(installed['allowed'])
        self.assertEqual(installed['running_vm_limit_bytes'], 2 * GIB + 256 * MIB)

    def test_resume_does_not_count_already_reserved_vm_twice(self):
        result = check_vm_start_memory(6 * GIB, vms=[self.vm()], telemetry=ram(available=1), vm=self.first)
        self.assertTrue(result['allowed'])
        self.assertEqual(result['package_limit_bytes'], 0)
        self.assertGreater(result['running_vm_limit_bytes'], 6 * GIB)

    def test_unreachable_libvirt_blocks_install_start_and_vm_checks_without_mutation(self):
        with patch('titan.app_memory.vm_memory_reservations', side_effect=Error('Unknown running VMs', 503)):
            for callback in (lambda: check_install_memory('titan-adguard', telemetry=ram()),
                             lambda: check_start_memory('app', {}, {'services': {'app': {'mem_limit': '512m'}}}, telemetry=ram()),
                             lambda: check_vm_start_memory(GIB, telemetry=ram())):
                with self.assertRaises(Error) as caught: callback()
                self.assertEqual(caught.exception.status, 503)

    def test_incomplete_or_duplicate_vm_budget_is_rejected(self):
        for vms in ([{'id': self.first}], [self.vm(), self.vm()], [{**self.vm(), 'limit_bytes': 1}], [{**self.vm(), 'overhead_bytes': 0}]):
            with self.assertRaises(Error): memory_preflight(ram(), GIB, vms=vms)


if __name__ == '__main__': unittest.main()

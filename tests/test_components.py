import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from titan.core import Error
from titan.host import Host, run
from tests.test_lifecycle_http import HTTPFixture

ROOT = Path(__file__).resolve().parents[1]


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.host = Host(self.root / 'agent', self.root / 'shares', self.root / 'vms', self.root / 'smb')
        self.host.share_root.mkdir(mode=0o755)
        self.host.component_helper = self.root / 'helper.sh'
        self.host.component_helper.write_text('# fixture, never executed\n')
        self.host.component_helper.chmod(0o644)
        self.ready = {'components': {'docker': {'installed': True, 'available': True},
                                    'vms': {'installed': True, 'available': True, 'daemon': True, 'kvm': True}}, 'repair': {}}

    def tearDown(self):
        self.temp.cleanup()

    def helper(self, report=None, code=0):
        return patch('titan.components.run_component_helper', return_value=SimpleNamespace(
            returncode=code, stdout=json.dumps(report or {'ok': True, 'components': {'docker': {'ok': True}}, 'warnings': []})))

    def test_repair_is_fixed_enum_and_never_accepts_command_or_path(self):
        with patch('titan.components.run_component_helper') as execute:
            for value in ('apt install evil', '../vms', '', 12, None, []):
                with self.assertRaises(Error): self.host.op_component_install(value)
            execute.assert_not_called()

    def test_success_rechecks_daemon_and_persists_finished_state(self):
        with self.helper() as execute, patch.object(self.host, 'op_components', return_value=self.ready):
            result = self.host.op_component_install('docker')
        self.assertTrue(result['ok'])
        self.assertEqual(execute.call_args.args[:2], (self.host.component_helper, 'docker'))
        self.assertFalse(self.host.load('component-repair', {})['running'])
        self.assertTrue(self.host.load('component-repair', {})['ok'])
        self.assertEqual(stat.S_IMODE((self.host.directory / 'component-install.log').stat().st_mode), 0o600)

    def test_failure_and_invalid_report_never_mark_ready(self):
        for report, code in (({'ok': False, 'components': {'docker': {'ok': False}}}, 1),
                             ({'ok': True}, 0), ({'ok': True, 'components': {}, 'warnings': 'invalid'}, 0)):
            with self.helper(report, code), patch.object(self.host, 'op_components') as status:
                with self.assertRaises(Error): self.host.op_component_install('docker')
                self.assertFalse(self.host.load('component-repair', {})['ok'])
                self.assertFalse(self.host.load('component-repair', {})['running'])
                status.assert_not_called()

    def test_installed_packages_with_unreachable_daemon_fail(self):
        self.ready['components']['docker'] = {'installed': True, 'available': False, 'error': 'daemon down'}
        with self.helper(), patch.object(self.host, 'op_components', return_value=self.ready):
            with self.assertRaisesRegex(Error, 'daemon down'): self.host.op_component_install('docker')

    def test_packages_can_be_repaired_when_host_kvm_is_absent(self):
        self.ready['components']['vms'].update(available=False, kvm=False, error='BIOS KVM missing')
        with self.helper(), patch.object(self.host, 'op_components', return_value=self.ready):
            result = self.host.op_component_install('vms')
        self.assertIn('BIOS KVM missing', result['warnings'])
        self.assertTrue(self.host.load('component-repair', {})['ok'])
        self.assertEqual(stat.S_IMODE(self.host.vm_root.stat().st_mode) & 0o011, 0o011)

    def test_helper_must_be_owned_regular_file_without_foreign_writes(self):
        self.host.component_helper.chmod(0o666)
        with self.helper() as execute:
            with self.assertRaises(Error): self.host.op_component_install('docker')
            execute.assert_not_called()
        self.host.component_helper.unlink()
        self.host.component_helper.symlink_to(ROOT / 'packaging/debian/runtime.sh')
        with self.helper() as execute:
            with self.assertRaises(Error): self.host.op_component_install('docker')
            execute.assert_not_called()

    def test_timeout_is_saved_as_failure(self):
        with patch('titan.components.run_component_helper', side_effect=subprocess.TimeoutExpired('fixture', 1800)):
            with self.assertRaises(Error): self.host.op_component_install('docker')
        self.assertFalse(self.host.load('component-repair', {})['running'])
        self.assertFalse(self.host.load('component-repair', {})['ok'])

    def test_docker_distinguishes_cli_compose_and_daemon(self):
        with patch('titan.components.shutil.which', return_value=None), patch('titan.host.run') as command:
            result = self.host.docker_component()
            self.assertEqual(result['missing'], ['docker']); command.assert_not_called()
        def missing_compose(args, **kwargs):
            if args[1] == 'compose': raise Error('no plugin')
            return 'version'
        with patch('titan.components.shutil.which', return_value='/usr/bin/docker'), patch('titan.host.run', side_effect=missing_compose):
            result = self.host.docker_component()
        self.assertFalse(result['available']); self.assertTrue(result['daemon'])
        self.assertEqual(result['missing'], ['Docker Compose'])

    def test_hung_or_missing_service_probes_keep_repair_status_available(self):
        for failure in (subprocess.TimeoutExpired('docker', 15), OSError('socket unavailable')):
            with patch('titan.components.shutil.which', return_value='/usr/bin/docker'), patch('titan.host.subprocess.run', side_effect=failure):
                with patch('titan.components.availability', return_value={'installed': True, 'available': True, 'missing': [], 'kvm': True}):
                    result = self.host.op_components()
            self.assertFalse(result['components']['docker']['available'])
            self.assertFalse(result['components']['vms']['available'])
            self.assertIn('error', result['components']['docker'])
            self.assertIn('error', result['components']['vms'])

    def test_virsh_uses_system_connection_and_fixed_lookup_path(self):
        with patch('titan.host.shutil.which', return_value='/usr/bin/virsh') as lookup, patch('titan.host.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='ready', stderr='')) as execute:
            self.assertEqual(run(['virsh', 'version']), 'ready')
        self.assertEqual(execute.call_args.kwargs['env']['LIBVIRT_DEFAULT_URI'], 'qemu:///system')
        self.assertEqual(lookup.call_args.kwargs['path'], execute.call_args.kwargs['env']['PATH'])

    def test_storage_repair_changes_only_traversal_and_preserves_guest_mode(self):
        self.host.vm_root.mkdir(mode=0o750)
        self.host.vm_root.chmod(0o750)
        guest = self.host.vm_root / 'guest.qcow2'
        guest.write_bytes(b'fixture'); guest.chmod(0o600)
        iso = self.host.vm_root / 'iso'; iso.mkdir(mode=0o750); iso.chmod(0o750)
        media = iso / 'guest.iso'; media.write_bytes(b'fixture'); media.chmod(0o640)
        self.host.prepare_vm_storage_access()
        self.assertEqual(stat.S_IMODE(self.host.vm_root.stat().st_mode), 0o751)
        self.assertEqual(stat.S_IMODE(iso.stat().st_mode), 0o751)
        self.assertEqual(stat.S_IMODE(guest.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(media.stat().st_mode), 0o640)

    def test_helper_dry_run_does_not_require_root_or_execute_apt(self):
        result = subprocess.run(['bash', str(ROOT / 'packaging/debian/runtime.sh'), '--component', 'all', '--dry-run'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('keine Datenlaufwerke', result.stdout)
        result = subprocess.run(['bash', str(ROOT / 'packaging/debian/runtime.sh'), '--component', 'all;touch /tmp/nope', '--dry-run'], capture_output=True)
        self.assertEqual(result.returncode, 2)

    def test_agent_restart_makes_interrupted_repair_retryable(self):
        self.host.save('component-repair', {'running': True, 'component': 'all'})
        restarted = Host(self.host.directory, self.host.share_root, self.host.vm_root, self.host.samba_config)
        state = restarted.load('component-repair', {})
        self.assertFalse(state['running'])
        self.assertFalse(state['ok'])
        self.assertIn('Dienstneustart', state['error'])

    def test_timeout_stops_the_entire_helper_group_before_returning(self):
        from titan.components import run_component_helper
        from unittest.mock import Mock
        import signal
        process = Mock(pid=456, returncode=-9)
        process.communicate.side_effect = [subprocess.TimeoutExpired('fixture', 2), subprocess.TimeoutExpired('fixture', 1), ('', '')]
        with patch('titan.components.subprocess.Popen', return_value=process) as spawn, patch('titan.components.os.killpg') as stop:
            with self.assertRaises(subprocess.TimeoutExpired):
                run_component_helper('/fixed/helper', 'vms', None, timeout=2, termination_grace=1)
        self.assertTrue(spawn.call_args.kwargs['start_new_session'])
        self.assertEqual([item.args for item in stop.call_args_list], [(456, signal.SIGTERM), (456, signal.SIGKILL)])
        self.assertEqual([item.kwargs['timeout'] for item in process.communicate.call_args_list], [2, 1, 1])


class ComponentHTTPTests(HTTPFixture, unittest.TestCase):
    def test_status_and_install_require_admin_and_csrf(self):
        for path, body in (('/api/components', None), ('/api/components/install', {'component': 'all'})):
            self.assertEqual(self.request(path, body, actor=None)[0], 401)
            self.assertEqual(self.request(path, body, actor='reader')[0], 403)
        self.assertEqual(self.request('/api/components/install', {'component': 'all'}, csrf='wrong')[0], 403)
        self.agent.call.assert_not_called()

    def test_selected_component_is_queued_and_revalidated(self):
        code, body, _ = self.json_request('/api/components/install', {'component': 'vms'})
        self.assertEqual(code, 202)
        self.assertEqual(self.wait_job(body['job'])['status'], 'completed')
        self.agent.call.assert_called_once_with('component_install', component='vms')

    def test_injected_paths_options_and_missing_enum_are_rejected(self):
        for body in ({}, {'component': 'all', 'command': 'rm'}, {'component': ['vms']}, {'component': '../vms'}, {'component': None}):
            self.assertEqual(self.request('/api/components/install', body)[0], 400)
        self.agent.call.assert_not_called()

class ComponentOrchestrationTests(unittest.TestCase):
    def helper(self, component='all', fail=''):
        import shlex
        source = (ROOT / 'packaging/debian/runtime.sh').read_text()
        source = source[source.index('failed=0'):]
        fixture = ('set -euo pipefail\njson=true\ncomponent=' + shlex.quote(component) + '\nfail=' + shlex.quote(fail) + '''
apt-get() { printf 'apt:%s\n' "$*" >&2; [[ "$fail" != update ]]; }
install_apps() { printf 'docker-attempt\n' >&2; [[ "$fail" != docker ]]; }
install_vm_components() { printf 'vm-attempt\n' >&2; [[ "$fail" != vms ]]; }
''')
        return subprocess.run(['bash', '-c', fixture + source], capture_output=True, text=True, timeout=5)

    def test_one_failure_does_not_skip_the_other_component(self):
        for name in ('docker', 'vms'):
            result = self.helper(fail=name)
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertFalse(report['ok'])
            self.assertFalse(report['components'][name]['ok'])
            self.assertTrue(report['components']['vms' if name == 'docker' else 'docker']['ok'])
            self.assertIn('docker-attempt', result.stderr)
            self.assertIn('vm-attempt', result.stderr)

    def test_selection_is_respected_and_no_package_install_is_attempted(self):
        for name, other in (('docker', 'vms'), ('vms', 'docker')):
            result = self.helper(component=name)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(set(json.loads(result.stdout)['components']), {name})
            self.assertNotIn(('vm' if other == 'vms' else 'docker') + '-attempt', result.stderr)
        result = self.helper(fail='update')
        self.assertEqual(result.returncode, 0)
        self.assertTrue(json.loads(result.stdout)['ok'])
        self.assertNotIn('apt:', result.stderr)


class DebianComponentServiceTests(unittest.TestCase):
    def network_fixture(self, active=False, racing=False, failure=''):
        import shlex
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / 'active'
            if active:
                state.touch()
            fixture = 'set -euo pipefail\nsource ' + shlex.quote(str(ROOT / 'scripts/component-functions.sh')) + '\n'
            fixture += 'state=' + shlex.quote(str(state)) + '\nracing=' + ('true' if racing else 'false') + '\nfailure=' + shlex.quote(failure) + '''
systemctl() {
    printf 'unit:%s\n' "$*" >&2
    [[ "$failure" != "$3" ]]
}
virsh() {
    printf 'virsh:%s locale:%s\n' "$*" "${LC_ALL:-unset}" >&2
    case "$3" in
        net-info|net-autostart) return 0 ;;
        net-list) [[ ! -f "$state" ]] || printf '%s\n' default; return 0 ;;
        net-start) if $racing; then touch "$state"; return 1; fi
                   [[ "$failure" != network ]] || return 1
                   touch "$state"; return 0 ;;
        *) return 1 ;;
    esac
}
activate_vm_services
'''
            return subprocess.run(['bash', '-c', fixture], capture_output=True, text=True, timeout=5)

    def test_active_network_is_idempotent_and_queries_use_fixed_locale(self):
        result = self.network_fixture(active=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('net-start', result.stderr)
        self.assertNotIn('locale:unset', result.stderr)
        self.assertIn('locale:C', result.stderr)
        for socket in ('libvirtd', 'virtlogd', 'virtlockd'):
            self.assertIn(socket + '.socket', result.stderr)

    def test_start_race_is_success_only_if_network_is_now_active(self):
        result = self.network_fixture(racing=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('net-start', result.stderr)
        result = self.network_fixture(failure='network')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Netzwerkstatus', result.stderr)

    def test_missing_socket_failures_do_not_continue_to_network_changes(self):
        result = self.network_fixture(failure='libvirtd.socket')
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('virsh:', result.stderr)

    def test_missing_image_dependencies_fail_without_package_manager_calls(self):
        import shlex
        fixture = ('set -euo pipefail\nsource ' + shlex.quote(str(ROOT / 'scripts/component-functions.sh')) + '''
command() { return 1; }
apt-get() { printf '%s\n' forbidden-package-install >&2; return 99; }
dnf() { printf '%s\n' forbidden-package-install >&2; return 99; }
systemctl() { printf '%s\n' forbidden-service-start >&2; return 99; }
install_apps
''')
        result = subprocess.run(['bash', '-c', fixture], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Systemimage', result.stderr)
        self.assertNotIn('forbidden-', result.stderr)

    def test_system_update_inventory_delegates_to_image_status_without_apt(self):
        with tempfile.TemporaryDirectory() as temporary:
            host = Host(Path(temporary) / 'agent')
            status = {'platform': 'debian-rauc', 'reboot_required': True}
            with patch('titan.updates.system_status', return_value=status) as image_status, patch('titan.host.run') as run:
                self.assertEqual(host.op_system_updates(), status)
            image_status.assert_called_once_with()
            run.assert_not_called()

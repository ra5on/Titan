"""Manual Docker data follows the selected, mount-verified NAS resource."""
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

from titan.core import Error
import test_storage_locations as storage_fixtures


class DockerStorageTests(unittest.TestCase):
    setUp = storage_fixtures.NamedStorageTests.setUp
    command = storage_fixtures.NamedStorageTests.command
    volume = storage_fixtures.NamedStorageTests.volume

    def configure(self):
        self.host._storage_locations = self.model
        self.host.app_memory_lock = threading.RLock()
        self.host._app_inspected_containers = Mock(return_value=[])
        self.memory = patch('titan.app_memory.check_container_start_memory', return_value={'allowed': True})
        self.memory.start(); self.addCleanup(self.memory.stop)
        self.device_guard = patch('titan.app_devices.devices', return_value=[])
        self.device_guard.start(); self.addCleanup(self.device_guard.stop)
        self.row = None
        self.created = None
        self.host.engine_docker = Mock(side_effect=self.docker)

    def docker(self, arguments, **kwargs):
        if arguments[0] == 'create':
            self.created = arguments
            labels = dict(arguments[i+1].split('=', 1) for i, part in enumerate(arguments[:-1]) if part == '--label')
            mount = dict(part.split('=', 1) for part in arguments[arguments.index('--mount')+1].split(','))
            self.row = {'Id': 'a'*64, 'Name': '/'+arguments[arguments.index('--name')+1],
                        'Config': {'Labels': labels}, 'HostConfig': {'Memory': 1024*1048576},
                        'State': {'Status': 'exited', 'Running': False},
                        'Mounts': [{'Type': 'bind', 'Source': mount['source'], 'Destination': mount['target'], 'RW': True}]}
            return self.row['Id']
        if arguments[0] == 'inspect':
            return json.dumps([self.row])
        return 'a'*64

    def test_default_resource_contains_actual_manual_container_data(self):
        self.configure(); folder, mounted = self.volume()
        with mounted:
            self.host.op_storage_preferences_save('volume:archive')
            self.host.op_docker_container_create({'name': 'web', 'image': 'nginx:stable'})
        self.assertTrue((folder/'apps/custom/web/data').is_dir())
        self.assertEqual(self.row['Config']['Labels']['io.titan.storage'], 'volume:archive')
        self.assertEqual(self.row['Mounts'][0]['Source'], str(folder/'apps/custom/web/data'))
        self.assertFalse((self.host.share_root/'apps/custom').exists())

    def test_offline_default_rejects_before_docker_create_and_no_fallback(self):
        self.configure(); folder, mounted = self.volume(False)
        self.host.save('storage-preferences', {'default_storage': 'volume:archive'})
        with mounted, self.assertRaises(Error):
            self.host.op_docker_container_create({'name': 'web', 'image': 'nginx:stable'})
        self.host.engine_docker.assert_not_called()
        self.assertFalse((folder/'apps').exists())
        self.assertFalse((self.host.share_root/'apps').exists())

    def test_replaced_resource_or_changed_bind_prevents_start_but_stop_is_available(self):
        self.configure(); folder, mounted = self.volume()
        with mounted:
            self.host.op_docker_container_create({'name': 'web', 'image': 'nginx:stable', 'storage_id': 'volume:archive'})
            self.row['Config']['Labels']['io.titan.storage.uuid'] = 'different-device'
            self.host.engine_docker.reset_mock()
            with self.assertRaises(Error):
                self.host.op_docker_container_action('a'*64, 'start')
            self.assertFalse(any(call.args[0][0] == 'start' for call in self.host.engine_docker.call_args_list))
            self.host.op_docker_container_action('a'*64, 'stop')
            self.row['Config']['Labels']['io.titan.storage.uuid'] = self.model.resolve('volume:archive')['uuid']
            self.row['Mounts'][0]['Source'] = str(self.host.share_root)
            with self.assertRaises(Error):
                self.host.op_docker_container_action('a'*64, 'start')

    def test_storage_and_docker_volume_are_mutually_exclusive(self):
        self.configure()
        with self.assertRaises(Error):
            self.host.op_docker_container_create({'name': 'web', 'image': 'nginx', 'storage_id': 'system', 'volume': 'archive'})
        self.host.engine_docker.assert_not_called()

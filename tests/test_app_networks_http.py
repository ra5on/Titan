"""Network actions pass through authenticated HTTP, queued jobs, and role checks."""
import unittest

from titan.core import Error
from test_lifecycle_http import HTTPFixture


class AppNetworksHTTPTests(HTTPFixture, unittest.TestCase):
    def test_network_inventory_and_mutations_require_permission_csrf_and_origin(self):
        self.assertEqual(self.request('/api/app-networks', actor=None)[0], 401)
        self.assertEqual(self.request('/api/app-networks', actor='reader')[0], 403)
        for operation, arguments in (
            ('app_network_create', {'name': 'meine-apps'}),
            ('app_network_remove', {'name': 'meine-apps', 'confirmation': 'meine-apps'}),
        ):
            body = {'operation': operation, 'arguments': arguments}
            self.assertEqual(self.request('/api/actions', body, actor=None)[0], 401)
            self.assertEqual(self.request('/api/actions', body, actor='reader')[0], 403)
            self.assertEqual(self.request('/api/actions', body, csrf='wrong')[0], 403)
            self.assertEqual(self.request('/api/actions', body, headers={'Origin': 'https://foreign.example'})[0], 403)
        self.assertEqual(self.app.store.jobs(), [])
        self.agent.call.assert_not_called()

    def test_name_only_create_and_confirmed_remove_execute_and_return_real_job_results(self):
        network = {'name': 'meine-apps', 'subnets': [{'subnet': '172.30.0.0/24', 'gateway': '172.30.0.1'}]}
        self.agent.call.return_value = {'ok': True, 'network': network}
        status, result, _ = self.json_request('/api/actions', {'operation': 'app_network_create', 'arguments': {'name': 'meine-apps'}})
        self.assertEqual(status, 202)
        completed = self.wait_job(result['job'])
        self.assertEqual(completed['status'], 'completed')
        self.assertEqual(completed['result']['network'], network)
        self.agent.call.assert_called_once_with('app_network_create', name='meine-apps')
        self.agent.call.reset_mock()
        arguments = {'name': 'meine-apps', 'confirmation': 'meine-apps'}
        status, result, _ = self.json_request('/api/actions', {'operation': 'app_network_remove', 'arguments': arguments})
        self.assertEqual(status, 202)
        self.assertEqual(self.wait_job(result['job'])['status'], 'completed')
        self.agent.call.assert_called_once_with('app_network_remove', **arguments)

    def test_invalid_network_payloads_are_rejected_before_queue_or_host_call(self):
        for arguments in ({}, {'name': 'bridge'}, {'name': '../unsafe'}, {'name': 'my-net', 'driver': 'host'},
                          {'name': 'my-net', 'internal': 'true'}, {'name': 'my-net', 'gateway': '172.30.0.1'},
                          {'name': 'my-net', 'subnet': '172.30.1.1/24'}):
            with self.subTest(arguments=arguments):
                self.assertEqual(self.request('/api/actions', {'operation': 'app_network_create', 'arguments': arguments})[0], 400)
        for arguments in ({'name': 'my-net'}, {'name': 'my-net', 'confirmation': 'other'},
                          {'name': 'my-net', 'confirmation': 'my-net', 'force': True}):
            with self.subTest(arguments=arguments):
                self.assertEqual(self.request('/api/actions', {'operation': 'app_network_remove', 'arguments': arguments})[0], 400)
        self.assertEqual(self.app.store.jobs(), [])
        self.agent.call.assert_not_called()

    def test_queued_network_action_rechecks_revoked_administrator(self):
        self.app.store.create_user('second', 'second-long-password', 'admin', 'second')
        pending = []
        self.app.jobs.submit = lambda actor, operation, callback, **kwargs: pending.append(callback) or {'job': 'pending'}
        self.assertEqual(self.request('/api/actions', {'operation': 'app_network_create', 'arguments': {'name': 'my-net'}})[0], 202)
        self.app.store.update_user('admin', role='user')
        with self.assertRaises(Error) as caught:
            pending[0]()
        self.assertEqual(caught.exception.status, 403)
        self.agent.call.assert_not_called()


if __name__ == '__main__':
    unittest.main()

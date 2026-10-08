import unittest

from titan.core import Error
from test_lifecycle_http import HTTPFixture


ARGUMENTS = {'pool': 'tank', 'member_guid': '1000000000000000002', 'disk': '/dev/sdc', 'expected_revision': 'a' * 64,
             'confirmation_pool': 'tank', 'confirmation_disk': '/dev/sdc'}


class StorageRecoveryHTTPTests(HTTPFixture, unittest.TestCase):
    def test_preview_is_private_admin_only_and_uncached_with_exact_pool(self):
        for actor, expected in ((None, 401), ('reader', 403)):
            self.assertEqual(self.request('/api/storage/recovery?pool=tank', actor=actor)[0], expected)
        self.agent.call.assert_not_called()
        status, value, headers = self.json_request('/api/storage/recovery?pool=tank')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.agent.call.assert_called_once_with('pool_recovery', pool='tank')
        self.agent.call.reset_mock()
        for path in ('/api/storage/recovery', '/api/storage/recovery?pool=tank&disk=/dev/sda', '/api/storage/recovery?pool=--help'):
            self.assertEqual(self.request(path)[0], 400)
        self.agent.call.assert_not_called()

    def test_replacement_needs_admin_csrf_and_strict_confirmed_inputs(self):
        body = {'operation': 'pool_replace', 'arguments': ARGUMENTS}
        for actor, csrf, expected in ((None, None, 401), ('reader', None, 403), ('admin', 'wrong', 403)):
            self.assertEqual(self.request('/api/actions', body, actor=actor, csrf=csrf)[0], expected)
        for args in ({}, {**ARGUMENTS, 'force': True}, {**ARGUMENTS, 'member_guid': None}, {**ARGUMENTS, 'expected_revision': 'old'},
                     {**ARGUMENTS, 'confirmation_pool': 'wrong'}, {**ARGUMENTS, 'confirmation_disk': '/dev/sda'}):
            self.assertEqual(self.request('/api/actions', {**body, 'arguments': args})[0], 400)
        self.agent.call.assert_not_called()

    def test_job_retains_actor_and_rechecks_current_administrator(self):
        status, response, _ = self.json_request('/api/actions', {'operation': 'pool_replace', 'arguments': ARGUMENTS})
        self.assertEqual(status, 202)
        job = self.wait_job(response['job'])
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['username'], 'admin')
        self.agent.call.assert_called_once_with('pool_replace', **ARGUMENTS)
        self.agent.call.reset_mock()
        self.app.store.create_user('secondadmin', 'secondadmin-original-password', 'admin', 'secondadmin')
        self.app.store.update_user('admin', enabled=False)
        with self.assertRaises(Error) as caught:
            self.app.admin_action('admin', 'pool_replace', ARGUMENTS)
        self.assertEqual(caught.exception.status, 403)
        self.agent.call.assert_not_called()

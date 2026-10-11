from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from titan.core import Error, Store
from titan.root_grants import RootGrantMixin

PASSWORD = 'Correct-Horse-Battery-9'


class Agent(RootGrantMixin):
    pass


class RootGrantTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        store = Store(self.temporary.name)
        store.create_user('admin', PASSWORD, 'admin', 'titan-files')
        store.create_user('gast', PASSWORD, 'user', 'gast')
        self.agent = Agent()
        self.agent.web_database = Path(self.temporary.name) / 'titan.sqlite3'

    def tearDown(self):
        self.temporary.cleanup()

    def test_only_a_confirmed_administrator_password_opens_a_lease(self):
        with self.assertRaises(Error) as missing:
            self.agent.require_root_grant('admin.session')
        self.assertEqual(missing.exception.status, 403)
        for name, password in (('admin', 'falsch'), ('gast', PASSWORD), ('niemand', PASSWORD)):
            with self.subTest(name=name), self.assertRaises(Error) as refused:
                self.agent.op_root_grant('admin.session', name, password)
            self.assertEqual(refused.exception.status, 403)
        with self.assertRaises(Error):
            self.agent.require_root_grant('admin.session')
        self.assertEqual(self.agent.op_root_grant('admin.session', 'admin', PASSWORD, minutes=5), {'ok': True})
        self.agent.require_root_grant('admin.session')
        with self.assertRaises(Error):
            self.agent.require_root_grant('other.session')

    def test_lease_expires_and_can_be_revoked(self):
        with patch('titan.root_grants.time.monotonic', return_value=1000.0):
            self.agent.op_root_grant('admin.session', 'admin', PASSWORD, minutes=1)
            self.agent.require_root_grant('admin.session')
        with patch('titan.root_grants.time.monotonic', return_value=1061.0), self.assertRaises(Error):
            self.agent.require_root_grant('admin.session')
        self.agent.op_root_grant('admin.session', 'admin', PASSWORD)
        self.agent.op_root_revoke('admin.session')
        with self.assertRaises(Error):
            self.agent.require_root_grant('admin.session')

    def test_repeated_failures_are_throttled_even_with_the_right_password(self):
        for _ in range(5):
            with self.assertRaises(Error):
                self.agent.op_root_grant('admin.session', 'admin', 'falsch')
        with self.assertRaises(Error) as throttled:
            self.agent.op_root_grant('admin.session', 'admin', PASSWORD)
        self.assertEqual(throttled.exception.status, 429)

    def test_malformed_requests_and_an_unreadable_database_are_refused(self):
        for arguments in (('', 'admin', PASSWORD), ('o', '', PASSWORD), ('o', 'admin', ''), ('o', 'admin', PASSWORD, 0),
                          ('o', 'admin', PASSWORD, 31), ('o', 'admin', PASSWORD, True), (7, 'admin', PASSWORD)):
            with self.subTest(arguments=arguments), self.assertRaises(Error):
                self.agent.op_root_grant(*arguments)
        self.agent.web_database = Path(self.temporary.name) / 'fehlt.sqlite3'
        with self.assertRaises(Error) as unreadable:
            self.agent.op_root_grant('o', 'admin', PASSWORD)
        self.assertEqual(unreadable.exception.status, 503)


if __name__ == '__main__':
    unittest.main()

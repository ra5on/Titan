import concurrent.futures
import tempfile
import unittest
from titan.app_access import AppAccess, upstream_cookies
from titan.core import Store, Error


class AppAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.store.create_user('alice', 'long-enough-password', 'user', 'alice')
        self.parent, _ = self.store.login('alice', 'long-enough-password')
        self.store.set_config('identity', {'users': {'alice': {'applications': {'apps': True}}}, 'groups': []})
        self.access = AppAccess(self.store)

    def opened(self):
        return self.access.redeem('notes', self.access.issue('notes', self.parent))

    def test_single_use_app_bound_ticket_and_hashed_storage(self):
        ticket = self.access.issue('notes', self.parent)
        with self.assertRaises(Error): self.access.redeem('other', ticket)
        token = self.access.redeem('notes', ticket)
        self.assertEqual(self.access.authorize('notes', token)['name'], 'alice')
        with self.assertRaises(Error): self.access.redeem('notes', ticket)
        with self.assertRaises(Error): self.access.authorize('other', token)
        with self.store.connection() as db:
            raw = str([tuple(row) for row in db.execute('SELECT * FROM app_access')])
        for secret in (ticket, token, self.parent): self.assertNotIn(secret, raw)

    def test_logout_revokes_existing_app_session(self):
        token = self.opened()
        self.store.logout(self.parent)
        with self.assertRaises(Error): self.access.authorize('notes', token)

    def test_permission_change_revokes_existing_app_session(self):
        token = self.opened()
        self.store.set_config('identity', {'users': {'alice': {'applications': {'apps': False}}}, 'groups': []})
        with self.assertRaises(Error): self.access.authorize('notes', token)

    def test_disabled_account_revokes_existing_app_session(self):
        token = self.opened()
        with self.store.connection() as db:
            db.execute("UPDATE users SET enabled=0 WHERE name='alice'")
        with self.assertRaises(Error): self.access.authorize('notes', token)

    def test_expired_ticket_and_parent_are_rejected(self):
        ticket = self.access.issue('notes', self.parent)
        self.access.clock = lambda: 10**12
        with self.assertRaises(Error): self.access.redeem('notes', ticket)
        with self.assertRaises(Error): self.access.issue('notes', self.parent)

    def test_restart_retains_grant_and_new_open_replaces_only_this_app(self):
        old = self.opened()
        other = self.access.redeem('other', self.access.issue('other', self.parent))
        resumed = AppAccess(Store(self.temp.name))
        self.assertEqual(resumed.authorize('notes', old)['name'], 'alice')
        new = self.opened()
        with self.assertRaises(Error): resumed.authorize('notes', old)
        self.assertEqual(resumed.authorize('notes', new)['name'], 'alice')
        self.assertEqual(resumed.authorize('other', other)['name'], 'alice')

    def test_concurrent_redemption_succeeds_once(self):
        ticket = self.access.issue('notes', self.parent)
        other = AppAccess(Store(self.temp.name))
        def redeem(access):
            try: return access.redeem('notes', ticket)
            except Error: return None
        with concurrent.futures.ThreadPoolExecutor() as pool:
            results = list(pool.map(redeem, [self.access, other]))
        self.assertEqual(sum(x is not None for x in results), 1)

    def test_package_receives_own_cookies_only(self):
        self.assertEqual(upstream_cookies('titan_session=private; titan_app_notes=grant; titan_app_other=another; app_session=own'), 'app_session=own')
        self.assertEqual(upstream_cookies('__Host-titan=private; theme=dark'), 'theme=dark')
        with self.assertRaises(Error): upstream_cookies('a=1\r\nInjected: yes')


if __name__ == '__main__': unittest.main()

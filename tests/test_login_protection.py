import copy
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from titan.config_restore import database_import
from titan.core import Error, Store
from titan.login_protection import DEFAULTS, LoginProtection, source_address, validate_settings
from titan.security import Security, totp


class LoginProtectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.store.create_user('admin', 'admin-password-long', 'admin', 'admin')
        self.store.create_user('reader', 'reader-password-long', 'user', 'reader')
        self.protection = LoginProtection(self.store)
        self.address = '192.0.2.9'

    def tearDown(self):
        self.temp.cleanup()

    def configure(self, **rules):
        overview = self.protection.overview('admin')
        policy = overview['settings']
        for kind, fields in rules.items():
            policy[kind].update(fields)
        return self.protection.save('admin', policy, overview['revision'])

    def rejected(self, name='reader', password='wrong-password-long', address=None, otp=None, store=None):
        with self.assertRaises(Error) as error:
            (store or self.store).login(name, password, address=address or self.address, otp=otp)
        return error.exception

    def test_defaults_are_safe_and_separate(self):
        data = self.protection.overview('admin')
        self.assertEqual(data['settings'], DEFAULTS)
        self.assertEqual(data['blocks'], [])
        self.assertIn('Titan-Webanmeldung', data['scope_note'])
        data['settings']['ip']['attempts'] = 99
        self.assertEqual(self.protection.overview('admin')['settings']['ip']['attempts'], 5)

    def test_exact_threshold_blocks_next_request_with_valid_password(self):
        for _ in range(5):
            self.assertEqual(self.rejected().status, 401)
        error = self.rejected(password='reader-password-long')
        self.assertEqual(error.status, 429)
        self.assertGreater(error.retry_after, 890)
        blocks = self.protection.overview('admin')['blocks']
        self.assertEqual({item['type'] for item in blocks}, {'ip', 'account'})
        self.assertEqual({item['address'] for item in blocks}, {self.address})

    def test_successful_logins_never_increment_or_trigger_lockout(self):
        self.configure(ip={'attempts': 2}, account={'attempts': 2})
        self.assertEqual(self.rejected().status, 401)
        for _ in range(15):
            token, _ = self.store.login('reader', 'reader-password-long', address=self.address)
            self.assertIsNotNone(self.store.session(token))
        self.assertEqual(self.protection.overview('admin')['blocks'], [])
        self.assertEqual(self.rejected().status, 401)
        self.assertEqual(self.rejected().status, 429)

    def test_ip_counts_failures_across_usernames(self):
        self.configure(ip={'attempts': 3}, account={'enabled': False})
        for name in ('reader', 'nobody', 'admin'):
            self.assertEqual(self.rejected(name=name).status, 401)
        self.assertEqual(self.rejected(name='other').status, 429)
        self.assertEqual(len(self.protection.overview('admin')['blocks']), 1)

    def test_malformed_names_still_count_and_persist_only_bounded_placeholder(self):
        self.configure(ip={'attempts': 2}, account={'enabled': False})
        self.assertEqual(self.rejected(name=None).status, 401)
        self.assertEqual(self.rejected(name='x' * 10000).status, 401)
        self.assertEqual(self.rejected(password='reader-password-long').status, 429)
        with self.store.connection() as db:
            events = db.execute('SELECT username FROM login_events WHERE success=0').fetchall()
        self.assertTrue(all(len(row[0]) <= 64 for row in events))

    def test_account_protection_cannot_lock_owner_out_from_other_source(self):
        self.configure(ip={'enabled': False}, account={'attempts': 2})
        self.rejected(); self.rejected()
        self.assertEqual(self.rejected(password='reader-password-long').status, 429)
        token, _ = self.store.login('reader', 'reader-password-long', address='192.0.2.10')
        self.assertIsNotNone(self.store.session(token))
        token, _ = self.store.login('admin', 'admin-password-long', address=self.address)
        self.assertIsNotNone(self.store.session(token))

    def test_unknown_and_disabled_accounts_have_identical_failure_and_block_policy(self):
        self.configure(ip={'enabled': False}, account={'attempts': 1})
        self.store.update_user('reader', enabled=False)
        errors = [self.rejected(name=name, password='reader-password-long') for name in ('reader', 'unknown')]
        self.assertEqual([str(error) for error in errors], [str(errors[0])] * 2)
        blocked = [self.rejected(name=name) for name in ('reader', 'unknown')]
        self.assertEqual([error.status for error in blocked], [429, 429])
        self.assertEqual(str(blocked[0]), str(blocked[1]))

    def test_unknown_username_performs_same_single_password_verification(self):
        with patch('titan.core.password_matches', return_value=False) as verify, patch('titan.core.password_hash') as new_hash:
            self.rejected(name='unknown')
            verify.assert_called_once()
            new_hash.assert_not_called()

    def test_sliding_window_forgets_old_failures_at_boundary(self):
        self.configure(ip={'attempts': 2, 'window_minutes': 1}, account={'enabled': False})
        with patch('titan.core.time.time', return_value=1000):
            self.rejected()
        with patch('titan.core.time.time', return_value=1060):
            self.rejected()
            self.assertEqual(self.protection.overview('admin')['blocks'], [])
        with patch('titan.core.time.time', return_value=1061):
            self.rejected()
            self.assertEqual(len(self.protection.overview('admin')['blocks']), 1)

    def test_expiry_and_blocked_attempts_do_not_extend_duration(self):
        self.configure(ip={'attempts': 1, 'window_minutes': 10, 'block_minutes': 1}, account={'enabled': False})
        with patch('titan.core.time.time', return_value=1000):
            self.rejected()
        with patch('titan.core.time.time', return_value=1030):
            error = self.rejected()
            self.assertEqual(error.retry_after, 30)
            self.assertEqual(self.protection.overview('admin')['blocks'][0]['expires'], 1060)
        with patch('titan.core.time.time', return_value=1060):
            token, _ = self.store.login('reader', 'reader-password-long', address=self.address)
            self.assertIsNotNone(self.store.session(token))
            self.assertEqual(self.protection.overview('admin')['blocks'], [])

    def test_window_and_active_block_survive_application_restart(self):
        self.configure(ip={'attempts': 2}, account={'enabled': False})
        self.rejected()
        restarted = Store(self.temp.name)
        self.assertEqual(self.rejected(store=restarted).status, 401)
        restarted = Store(self.temp.name)
        self.assertEqual(self.rejected(store=restarted, password='reader-password-long').status, 429)

    def test_two_factor_failure_and_replay_count_once_per_login(self):
        security = Security(self.store)
        setup = security.begin('reader', 'reader-password-long')
        recovery = security.confirm('reader', 'reader-password-long', totp(setup['secret'], int(time.time() // 30)))['recovery_codes'][0]
        self.configure(ip={'attempts': 2}, account={'enabled': False})
        self.assertEqual(self.rejected(password='reader-password-long', otp=None).status, 401)
        self.store.login('reader', 'reader-password-long', otp=recovery, address=self.address)
        self.assertEqual(self.rejected(password='reader-password-long', otp=recovery).status, 401)
        self.assertEqual(self.rejected(password='reader-password-long').status, 429)

    def test_block_does_not_consume_valid_recovery_code(self):
        security = Security(self.store)
        setup = security.begin('reader', 'reader-password-long')
        recovery = security.confirm('reader', 'reader-password-long', totp(setup['secret'], int(time.time() // 30)))['recovery_codes'][0]
        self.configure(ip={'attempts': 1}, account={'enabled': False})
        self.rejected()
        self.assertEqual(self.rejected(password='reader-password-long', otp=recovery).status, 429)
        self.store.login('reader', 'reader-password-long', otp=recovery, address='192.0.2.10')

    def test_manual_unblock_is_precise_and_starts_fresh_counter(self):
        self.configure(ip={'attempts': 2}, account={'enabled': False})
        self.rejected(); self.rejected()
        self.rejected(address='192.0.2.10'); self.rejected(address='192.0.2.10')
        block = next(item for item in self.protection.overview('admin')['blocks'] if item['address'] == self.address)
        result = self.protection.unblock('admin', block['id'])
        self.assertTrue(result['ok'])
        self.assertEqual([item['address'] for item in result['blocks']], ['192.0.2.10'])
        self.store.login('reader', 'reader-password-long', address=self.address)
        self.assertEqual(self.rejected().status, 401)
        self.assertEqual(len(self.protection.overview('admin')['blocks']), 1)

    def test_disabling_one_mode_clears_its_state_only(self):
        self.configure(ip={'attempts': 1}, account={'attempts': 1})
        self.rejected()
        result = self.configure(ip={'enabled': False})
        self.assertEqual([item['type'] for item in result['blocks']], ['account'])
        self.assertEqual(self.rejected().status, 429)
        self.configure(account={'enabled': False})
        self.store.login('reader', 'reader-password-long', address=self.address)

    def test_rule_change_keeps_existing_duration(self):
        self.configure(ip={'attempts': 1, 'block_minutes': 10}, account={'enabled': False})
        self.rejected()
        expires = self.protection.overview('admin')['blocks'][0]['expires']
        data = self.configure(ip={'block_minutes': 2})
        self.assertEqual(data['blocks'][0]['expires'], expires)

    def test_non_admin_and_disabled_admin_rejected_even_directly(self):
        overview = self.protection.overview('admin')
        for method in (lambda: self.protection.overview('reader'), lambda: self.protection.save('reader', overview['settings'], overview['revision']), lambda: self.protection.unblock('reader', 'a' * 32)):
            with self.assertRaises(Error) as error: method()
            self.assertEqual(error.exception.status, 403)
        self.store.create_user('otheradmin', 'otheradmin-password', 'admin', 'otheradmin')
        self.store.update_user('admin', enabled=False)
        with self.assertRaises(Error) as error: self.protection.overview('admin')
        self.assertEqual(error.exception.status, 403)

    def test_stale_editor_cannot_overwrite_other_admin(self):
        stale = self.protection.overview('admin')
        self.configure(ip={'attempts': 7})
        with self.assertRaises(Error) as error: self.protection.save('admin', stale['settings'], stale['revision'])
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.protection.overview('admin')['settings']['ip']['attempts'], 7)

    def test_strict_schema_and_numeric_bounds(self):
        mutations = [lambda p: p.update(schema=True), lambda p: p.update(extra=1), lambda p: p['ip'].update(enabled=1), lambda p: p['ip'].update(attempts='5'), lambda p: p['ip'].update(attempts=True), lambda p: p['ip'].update(attempts=0), lambda p: p['account'].update(attempts=101), lambda p: p['ip'].update(window_minutes=1441), lambda p: p['ip'].update(block_minutes=10081), lambda p: p['ip'].update(extra='x')]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                policy = copy.deepcopy(DEFAULTS); mutation(policy)
                with self.assertRaises(Error): validate_settings(policy)

    def test_bad_unblock_identifier_is_rejected(self):
        for value in (None, '', 1, '../file', 'a' * 31):
            with self.assertRaises(Error): self.protection.unblock('admin', value)
        with self.assertRaises(Error) as error: self.protection.unblock('admin', 'a' * 32)
        self.assertEqual(error.exception.status, 404)

    def test_parallel_store_instances_cannot_race_threshold(self):
        self.configure(ip={'attempts': 3}, account={'enabled': False})
        stores = [Store(self.temp.name) for _ in range(8)]
        with patch('titan.core.password_matches', return_value=False):
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda store: self.rejected(store=store).status, stores))
        self.assertEqual(results.count(401), 3)
        self.assertEqual(results.count(429), 5)
        self.assertEqual(len(self.protection.overview('admin')['blocks']), 1)

    def test_canonical_ipv4_mapped_ipv6_cannot_bypass_bucket(self):
        self.configure(ip={'attempts': 1}, account={'enabled': False})
        self.rejected(address='::ffff:192.0.2.9')
        self.assertEqual(self.rejected(address='192.0.2.9').status, 429)
        self.assertEqual(source_address('2001:0db8::1'), '2001:db8::1')

    def test_state_is_bounded_and_saturation_fails_closed(self):
        self.configure(account={'enabled': False})
        with patch('titan.login_protection.MAX_TRACKERS', 2):
            self.rejected(address='192.0.2.1'); self.rejected(address='192.0.2.2')
            self.assertEqual(self.rejected(address='192.0.2.3').status, 429)
            self.assertEqual(self.rejected(address='192.0.2.1').status, 401)
            with self.store.connection() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM login_protection_failures').fetchone()[0], 2)

    def test_configuration_restore_imports_policy_but_clears_temporary_locks(self):
        self.configure(ip={'attempts': 1}, account={'enabled': False})
        self.rejected()
        policy = self.protection.overview('admin')['settings']
        users = [self.store.user_record(name) for name in ('admin', 'reader')]
        database_import(self.store.path, {'users': users, 'config': {'login_protection': policy}})
        self.assertEqual(self.protection.overview('admin')['settings'], policy)
        self.assertEqual(self.protection.overview('admin')['blocks'], [])
        self.store.login('reader', 'reader-password-long', address=self.address)
        database_import(self.store.path, {'users': users, 'config': {}})
        self.assertEqual(self.protection.overview('admin')['settings'], DEFAULTS)

    def test_deleted_account_lock_does_not_affect_recreated_username(self):
        from titan.users import Users
        self.configure(ip={'enabled': False}, account={'attempts': 1})
        self.rejected()
        Users(self.store, Mock()).remove('admin', 'reader', 'reader')
        self.assertEqual(self.protection.overview('admin')['blocks'], [])
        self.store.create_user('reader', 'new-reader-password', 'user', 'reader')
        token, _ = self.store.login('reader', 'new-reader-password', address=self.address)
        self.assertIsNotNone(self.store.session(token))


if __name__ == '__main__':
    unittest.main()

import copy
import threading
import time
from unittest.mock import patch
import unittest
from types import SimpleNamespace
from titan.core import Error
from titan.unified_updates import UnifiedUpdates, KEY


class Store:
    def __init__(self):
        self.data = {}; self.enabled = True; self.channel = 'stable'; self.records = []
    def config(self, key, default=None): return copy.deepcopy(self.data.get(key, default))
    def set_config(self, key, value): self.data[key] = copy.deepcopy(value)
    def settings(self): return {'repository': 'ra5on/Titan', 'channel': self.channel}
    def user_record(self, actor): return {'enabled': self.enabled, 'role': 'admin' if actor == 'admin' else 'user'}
    def jobs(self): return self.records


class Agent:
    def __init__(self):
        self.calls = []
        self.web = {'available': True, 'latest': {'version': '0.9.0', 'image': 'sha256:'+'b'*64}, 'current': '0.8.0'}
        self.system = {'booted': {'digest': 'sha256:'+'a'*64}, 'health_confirmed': True}
        self.progress = {'status': 'idle'}
    def call(self, operation, **args):
        self.calls.append((operation, args))
        value = {'web_update_check': self.web, 'web_update_start': {'ok': True}, 'system_updates': self.system, 'update_progress': self.progress}[operation]
        if isinstance(value, Exception): raise value
        return copy.deepcopy(value)


class UnifiedUpdateTests(unittest.TestCase):
    def setUp(self):
        self.store, self.agent = Store(), Agent(); self.queue = []; self.installs = []; self.now = 1000
        self.offer = {'latest': 'v0.9.0', 'latest_titan_version': '0.9.0', 'available': True, 'signed': True,
                      'booted': {'digest': 'sha256:'+'a'*64}}
        def submit(actor, action, fn):
            self.queue.append(fn)
            return {'job': str(len(self.queue))}
        def install(actor, target, unified_token=None):
            self.installs.append((actor, target, unified_token))
            self.agent.system = {'reboot_required': True, 'staged': {'version': '0.9.0', 'digest': 'sha256:'+'c'*64}}
            return {**self.agent.system, 'ok': True}
        self.app = SimpleNamespace(store=self.store, agent=self.agent, demo=False, update_lock=threading.RLock(),
                                   update_check=lambda: copy.deepcopy(self.offer), jobs=SimpleNamespace(submit=submit), install_update=install)
        self.flow = UnifiedUpdates(self.app, clock=lambda: self.now, current_version='0.8.0')
    def automatic_policy(self):
        now = time.localtime(self.now)
        policy = {'repository': 'ra5on/Titan', 'channel': 'stable', 'installation': 'automatic',
                  'auto_check': True, 'check_interval': 'daily', 'window_day': now.tm_wday, 'window_hour': now.tm_hour}
        self.store.settings = lambda: dict(policy)
        self.store.users = lambda: [{'name': 'admin'}]
        self.app.unified_updates = self.flow
        return policy

    def test_automatic_web_update_uses_same_durable_plan(self):
        self.automatic_policy();self.offer = {'available': False}
        plan = self.flow.check('system', automatic=True)
        self.flow.start('system', plan['id'], automatic=True);self.queue.pop(0)()
        self.assertEqual(self.flow.load()['state'], 'web_starting')
        self.assertTrue(self.flow.load()['automatic'])
        UnifiedUpdates(self.app, clock=lambda:self.now, current_version='0.9.0').reconcile()
        self.assertEqual(self.flow.load()['state'], 'completed')

    def test_automatic_policy_revocation_stops_pending_execution(self):
        policy=self.automatic_policy();plan=self.flow.check('system',automatic=True)
        self.flow.start('system',plan['id'],automatic=True);policy['installation']='manual'
        with self.assertRaises(Error):self.queue.pop(0)()
        self.assertEqual(self.flow.load()['state'],'failed')
        self.assertFalse(any(op=='web_update_start' for op,args in self.agent.calls))

    def test_automatic_cannot_start_outside_window_or_impersonate_user(self):
        policy=self.automatic_policy();plan=self.flow.check('system',automatic=True)
        policy['window_hour']=(policy['window_hour']+1)%24
        with self.assertRaises(Error):self.flow.start('system',plan['id'],automatic=True)
        with self.assertRaises(Error):self.flow.check('admin',automatic=True)
        self.assertFalse(self.queue)

    def test_scheduler_discovers_web_only_offer_without_system_update(self):
        from titan.server import Application
        self.automatic_policy();self.offer={'available':False};self.now=100000
        current=time.localtime(1000)
        with patch('titan.server.time.localtime',return_value=current),patch('titan.server.time.time',return_value=self.now):
            Application.updater_tick(self.app)
        self.assertEqual(self.flow.load()['state'],'queued')
        self.assertTrue(self.flow.load()['automatic']);self.assertEqual(len(self.queue),1)
        Application.updater_tick(self.app);self.assertEqual(len(self.queue),1)

    def start(self):
        plan = self.flow.check('admin'); self.flow.start('admin', plan['id']); self.queue.pop(0)()
    def test_one_plan_survives_web_restart_then_system_reboot(self):
        self.start()
        self.assertEqual(self.flow.load()['state'], 'web_starting'); self.assertFalse(self.installs)
        new = UnifiedUpdates(self.app, clock=lambda: self.now, current_version='0.9.0')
        new.reconcile(); self.assertEqual(len(self.queue), 1); self.queue.pop(0)()
        self.assertEqual(new.load()['state'], 'restart_required'); self.assertEqual(self.installs[0][1], 'v0.9.0')
        self.agent.system = {'health_confirmed': True, 'booted': {'digest': 'sha256:'+'c'*64}}
        new.reconcile(); self.assertEqual(new.load()['state'], 'completed')
        self.assertEqual(len(new.load()['completed']), 2)
    def test_web_only_never_requests_reboot(self):
        self.offer = {'available': False}; self.start()
        new = UnifiedUpdates(self.app, current_version='0.9.0'); new.reconcile()
        self.assertEqual(new.load()['state'], 'completed'); self.assertFalse(self.installs)
    def test_system_only_prepares_and_waits_for_confirmation(self):
        self.agent.web = {'available': False}; self.start()
        self.assertEqual(self.flow.load()['state'], 'restart_required')
        self.assertFalse(any(op == 'system_reboot' for op, args in self.agent.calls))
    def test_partial_discovery_does_not_claim_current(self):
        self.offer = {'available': False}; self.agent.web = Error('network', 503)
        self.assertEqual(self.flow.check('admin')['state'], 'check_failed')
    def test_unsigned_system_not_installed(self):
        self.offer['signed'] = False; self.agent.web = {'available': False}
        self.assertEqual(self.flow.check('admin')['state'], 'check_failed'); self.assertFalse(self.installs)
    def test_old_token_expired_or_changed_channel_rejected(self):
        for kind in ('old', 'expired', 'channel'):
            with self.subTest(kind=kind):
                self.setUp(); plan=self.flow.check('admin')
                if kind == 'expired': self.now += 1801
                if kind == 'channel': self.store.channel='beta'
                with self.assertRaises(Error): self.flow.start('admin', 'old' if kind=='old' else plan['id'])
                self.assertFalse(self.queue)
    def test_source_change_after_queue_prevents_any_install(self):
        plan=self.flow.check('admin');self.flow.start('admin',plan['id']);self.store.channel='beta'
        with self.assertRaises(Error):self.queue.pop(0)()
        self.assertEqual(self.flow.load()['state'],'failed')
        self.assertFalse(any(op=='web_update_start' for op,args in self.agent.calls))
        self.assertFalse(self.installs)

    def test_duplicate_install_rejected(self):
        plan=self.flow.check('admin'); self.flow.start('admin', plan['id'])
        with self.assertRaises(Error): self.flow.start('admin', plan['id'])
    def test_changed_signed_web_image_rejected_before_switch(self):
        plan=self.flow.check('admin'); self.flow.start('admin', plan['id']); self.agent.web['latest']['image']='sha256:'+'d'*64
        with self.assertRaises(Error): self.queue.pop(0)()
        self.assertEqual(self.flow.load()['state'], 'failed')
        self.assertFalse(any(op=='web_update_start' for op,args in self.agent.calls))
    def test_revoked_administrator_cannot_continue_after_restart(self):
        self.start(); self.store.enabled=False
        new=UnifiedUpdates(self.app,current_version='0.9.0');new.reconcile()
        self.assertEqual(new.load()['state'],'failed');self.assertFalse(self.queue)
    def test_timeout_is_not_success(self):
        self.start();self.now+=901;self.flow.reconcile()
        self.assertEqual(self.flow.load()['state'],'failed')
    def test_interrupted_system_install_reconciles_prepared_slot(self):
        self.agent.web={'available':False};self.start()
        plan=self.flow.load();self.flow.save(plan,'system_running');self.flow.reconcile()
        self.assertEqual(self.flow.load()['state'],'restart_required');self.assertEqual(len(self.installs),1)
    def test_interrupted_writer_is_never_blindly_retried(self):
        self.agent.web={'available':False};self.start();self.flow.save(self.flow.load(),'system_running')
        self.agent.system={'health_confirmed':True};self.flow.reconcile()
        self.assertEqual(self.flow.load()['state'],'failed');self.assertEqual(len(self.installs),1)
    def test_wrong_booted_target_fails(self):
        self.agent.web={'available':False};self.start()
        self.agent.system={'health_confirmed':True,'booted':{'digest':'sha256:'+'a'*64}}
        self.flow.reconcile();self.assertEqual(self.flow.load()['state'],'failed')
    def test_rpc_outage_preserves_pending_target(self):
        self.agent.web={'available':False};self.start();expected=self.flow.load()['next_digest']
        self.agent.system=Error('offline',503);self.flow.reconcile()
        self.assertEqual(self.flow.load()['state'],'restart_required');self.assertEqual(self.flow.load()['next_digest'],expected)
    def test_regular_user_denied(self):
        with self.assertRaises(Error): self.flow.check('user')
    def test_no_new_check_overwrites_active_plan(self):
        self.start();old=self.flow.load()['id'];self.flow.check('admin');self.assertEqual(self.flow.load()['id'],old)

    def test_historic_failure_does_not_override_verified_target_boot(self):
        self.agent.web={'available':False};self.start()
        self.agent.system={'health_confirmed':True,'booted':{'digest':self.flow.load()['next_digest']},'last_failure':'older attempt'}
        self.flow.reconcile();self.assertEqual(self.flow.load()['state'],'completed')
    def test_old_process_does_not_overwrite_replacement_process_progress(self):
        original=self.agent.call
        def call(operation,**args):
            result=original(operation,**args)
            if operation=='web_update_start':
                replacement=UnifiedUpdates(self.app,current_version='0.9.0')
                replacement.reconcile()
            return result
        self.agent.call=call
        self.start();self.assertEqual(self.flow.load()['state'],'system_queued')

    def test_demo_does_not_suggest_a_real_blocked_installation(self):
        self.app.demo=True;self.offer={'latest':'v0.9.0','available':False}
        result=self.flow.check('admin')
        self.assertEqual(result['state'],'current');self.assertTrue(result['demo'])
        self.assertIn('Demo',result['message'])

    def test_system_actions_cannot_replace_active_plan(self):
        from titan.server import Application
        self.app.unified_updates=self.flow
        self.start()
        for op,args in [('update_rollback',{'expected_digest':'sha256:'+'a'*64,'confirmation':'ROLLBACK'}),
                        ('system_reboot',{'expected_digest':'sha256:'+'a'*64,'confirmation':'NEUSTART'})]:
            with self.assertRaises(Error):Application.system_action(self.app,'admin',op,args)
        self.assertFalse(any(op in ('update_rollback','system_reboot') for op,args in self.agent.calls))

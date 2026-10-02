import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from titan import debian_updates as updates
from titan.core import Error


class DebianABTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for name, path in [('STATE', root/'state.json'), ('BOOT_OK', root/'boot-ok'), ('LOCK', root/'update.lock')]:
            p = patch.object(updates, name, path); p.start(); self.addCleanup(p.stop)
        self.info = {'format':updates.FORMAT, 'platform':'debian-rauc', 'compatible':updates.COMPATIBLE,
                     'architecture':'x86_64', 'state_schema':1, 'release_id':'sha256:'+'a'*64,
                     'version':'0.4.6-alpha.1', 'release_stage':'alpha'}
        self.old = {**self.info, 'version':'0.4.5-alpha.1', 'release_id':'sha256:'+'b'*64}
        p = patch.object(updates, 'image_info', return_value=self.info); p.start(); self.addCleanup(p.stop)
        p = patch('titan.updates.architecture', return_value='x86_64'); p.start(); self.addCleanup(p.stop)
        p = patch('titan.updates.scheduled_reboot', return_value=None); p.start(); self.addCleanup(p.stop)
        self.rauc = {'compatible':updates.COMPATIBLE, 'boot_primary':'rootfs.0', 'slots':[
            {'rootfs.0':{'bootname':'A','state':'booted','device':'/dev/disk/by-partlabel/TITAN-A','type':'ext4','boot_status':'good'}},
            {'rootfs.1':{'bootname':'B','state':'inactive','device':'/dev/disk/by-partlabel/TITAN-B','type':'ext4','boot_status':'good'}}]}
        self.commands=[]
        def run(args, **kwargs):
            self.commands.append(args)
            return json.dumps(self.rauc) if args[:2]==['rauc','status'] and '--detailed' in args else ''
        p = patch.object(updates, 'run', side_effect=run); p.start(); self.addCleanup(p.stop)

    def state(self):
        return {'schema':1,'slots':{'A':{'identity':self.info,'confirmed':True},'B':{'identity':self.old,'confirmed':True}}}

    def test_each_boot_requires_new_health_confirmation(self):
        updates.save_state(self.state())
        self.assertFalse(updates.system_status()['rollback_available'])
        updates.BOOT_OK.write_text(self.info['release_id'])
        value=updates.system_status()
        self.assertTrue(value['health_confirmed'])
        self.assertEqual([x['slot'] for x in value['rollback_options']],['B'])
        self.assertTrue(value['rollback_available'])

    def test_unconfirmed_or_bad_slot_not_offered(self):
        state=self.state();state['slots']['B']['confirmed']=False;updates.save_state(state)
        self.assertEqual(updates.system_status()['rollback_options'],[])
        state['slots']['B']['confirmed']=True;updates.save_state(state)
        self.rauc['slots'][1]['rootfs.1']['boot_status']='bad'
        self.assertEqual(updates.system_status()['rollback_options'],[])

    def test_foreign_partition_fails_closed(self):
        self.rauc['slots'][1]['rootfs.1']['device']='/dev/sdc'
        with self.assertRaises(Error):updates.system_status()

    def test_unknown_primary_is_not_silently_accepted(self):
        self.rauc['boot_primary']='rootfs.2'
        with self.assertRaises(Error):updates.system_status()

    def test_untracked_activation_rejected(self):
        updates.save_state(self.state());self.rauc['boot_primary']='rootfs.1'
        with self.assertRaises(Error):updates.system_status()

    def test_pending_update_confirmed_only_after_health(self):
        state=self.state();state['slots']['A']['confirmed']=False
        state['pending']={'slot':'A','digest':self.info['release_id'],'kind':'update'}
        updates.save_state(state)
        updates.confirm_boot()
        self.assertNotIn('pending',updates.load_state())
        self.assertTrue(updates.load_state()['slots']['A']['confirmed'])
        self.assertEqual(updates.BOOT_OK.read_text().strip(),self.info['release_id'])
        self.assertIn(['rauc','status','mark-good','booted'],self.commands)

    def test_failed_candidate_is_removed_from_rollback_choices(self):
        state=self.state();state['pending']={'slot':'B','digest':self.old['release_id'],'kind':'update'}
        updates.save_state(state);updates.confirm_boot()
        self.assertFalse(updates.load_state()['slots']['B']['confirmed'])
        self.assertEqual(updates.load_state()['last_failure']['slot'],'B')
        self.assertIn(['rauc','status','mark-bad','rootfs.1'],self.commands)

    def test_health_failure_does_not_mark_good(self):
        updates.save_state(self.state())
        def run(args, **kwargs):
            if args[0]=='mountpoint':raise Error('missing mount')
            return json.dumps(self.rauc)
        with patch.object(updates,'run',side_effect=run):
            with self.assertRaises(Error):updates.confirm_boot()
        self.assertFalse(updates.BOOT_OK.exists())

    def test_bad_manifest_rejected_before_install(self):
        value={**self.info,'boot_test':'passed','runtime_test':'passed','update_test':'passed','rollback_test':'passed',
               'bundle':{'name':'titan-0.4.6-alpha.1-amd64.raucb','size':1024,'sha256':'c'*64},'rootfs_sha256':'d'*64}
        updates.validate_manifest(value)
        for field,bad in [('state_schema',2),('rollback_test','skipped'),('architecture','aarch64')]:
            with self.subTest(field=field),self.assertRaises(Error):updates.validate_manifest({**value,field:bad})
        for field,bad in [('size',True),('name','../../disk'),('sha256','wrong')]:
            with self.subTest(field=field),self.assertRaises(Error):updates.validate_manifest({**value,'bundle':{**value['bundle'],field:bad}})

    def test_stale_selection_never_activates_slot(self):
        updates.save_state(self.state());updates.BOOT_OK.write_text(self.info['release_id'])
        with self.assertRaises(Error):updates.rollback('ra5on/Titan','sha256:'+'c'*64,'ROLLBACK',Path('/unused'))
        self.assertFalse(any('mark-active' in cmd for cmd in self.commands))


if __name__=='__main__':unittest.main()

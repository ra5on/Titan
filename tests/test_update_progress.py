import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from titan import update_progress as progress
from titan.core import Error
from test_lifecycle_http import HTTPFixture


class ProgressTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        p=patch.object(progress,'PATH',Path(temp.name)/'progress.json');p.start();self.addCleanup(p.stop)

    def test_measured_download_then_write_does_not_keep_fake_percentage(self):
        @progress.tracked
        def install():
            progress.report('download',received=512,total=1024)
            value=progress.read()
            self.assertEqual(value['status'],'running')
            self.assertEqual((value['received'],value['total']),(512,1024))
            progress.report('writing')
            self.assertNotIn('received',progress.read())
            self.assertNotIn('total',progress.read())
        install()
        self.assertEqual(progress.read()['status'],'completed')
        self.assertEqual(progress.read()['phase'],'ready')
        self.assertEqual(progress.PATH.stat().st_mode & 0o777,0o600)

    def test_error_keeps_phase_without_leaking_exception_details(self):
        @progress.tracked
        def install():
            progress.report('verification')
            raise Error('private token')
        with self.assertRaises(Error):install()
        value=progress.read()
        self.assertEqual(value['status'],'failed')
        self.assertEqual(value['phase'],'verification')
        self.assertNotIn('private token',json.dumps(value))

    def test_restart_reports_interrupted_and_missing_file_is_idle(self):
        self.assertEqual(progress.read(),{'status':'idle'})
        progress.PATH.write_text(json.dumps({'id':'previous-process','status':'running','phase':'writing','started_at':1,'updated_at':10}))
        value=progress.read()
        self.assertEqual(value['status'],'interrupted')
        self.assertEqual(value['elapsed'],9)

    def test_progress_io_failure_does_not_abort_system_install(self):
        @progress.tracked
        def install():return 'prepared'
        with patch.object(progress,'atomic_json',side_effect=OSError('read only')), self.assertLogs('titan.update_progress'):
            self.assertEqual(install(),'prepared')


class ProgressHTTPTests(HTTPFixture,unittest.TestCase):
    def test_admin_only_uncached_read_without_mutation(self):
        for actor,code in ((None,401),('reader',403)):
            self.assertEqual(self.request('/api/updates/progress',actor=actor)[0],code)
        self.agent.call.assert_not_called()
        self.agent.call.return_value={'status':'running','phase':'writing'}
        code,value,headers=self.json_request('/api/updates/progress')
        self.assertEqual(code,200)
        self.assertEqual(value['phase'],'writing')
        self.agent.call.assert_called_once_with('update_progress')
        self.assertEqual(self.request('/api/updates/progress?cached=1')[0],400)

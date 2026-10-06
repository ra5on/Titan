"""Real demo HTTP/job regression for the browser's package installation payload."""
from http.server import ThreadingHTTPServer
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from titan.server import Application, Handler


class DemoPackageHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.app=Application(self.temporary.name,demo=True)
        self.csrf='demo-only'
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.app=self.app
        self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.app.stop.set();self.app.agent._temporary.cleanup();self.temporary.cleanup()

    def request(self,path,body=None):
        headers={'X-CSRF-Token':self.csrf,'Content-Type':'application/json'}
        request=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(request,timeout=5) as response:return response.status,json.loads(response.read())
        except urllib.error.HTTPError as response:return response.code,json.loads(response.read())

    def action(self,operation,arguments):
        status,queued=self.request('/api/actions',{'operation':operation,'arguments':arguments})
        self.assertEqual(status,202,queued)
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            job=next(item for item in self.app.store.jobs() if item['id']==queued['job'])
            if job['status'] in ('completed','failed'):return job
            time.sleep(.01)
        self.fail('Package job did not finish')

    def test_immich_default_form_job_and_package_management_are_functional(self):
        arguments={'app':'titan-immich','port':2283,'share':None,'network':{'mode':'default'},'hardware':[]}
        job=self.action('app_install',arguments)
        self.assertEqual(job['status'],'completed',job['result'])
        status,details=self.request('/api/package-details?app=titan-immich')
        self.assertEqual(status,200,details)
        self.assertTrue(details['ready']);self.assertEqual(details['total_services'],4)
        self.assertEqual(sum(service['ready'] for service in details['services']),4)
        status,logs=self.request('/api/package-logs?app=titan-immich&service=titan-immich-database&tail=10')
        self.assertEqual(status,200,logs);self.assertIn('[Demo]',logs['logs'])
        job=self.action('app_action',{'app':'titan-immich','action':'stop'})
        self.assertEqual(job['status'],'completed',job['result'])
        self.assertFalse(self.request('/api/package-details?app=titan-immich')[1]['ready'])
        job=self.action('package_repair',{'app':'titan-immich'})
        self.assertEqual(job['status'],'completed',job['result'])
        self.assertTrue(self.request('/api/package-details?app=titan-immich')[1]['ready'])

    def test_nextcloud_default_form_installs_complete_stack_without_secret_disclosure(self):
        arguments={'app':'titan-nextcloud-office','port':8088,'share':None,'hardware':[],
                   'options':{'username':'admin','password':'chosen-private-nextcloud-password','nas_host':'nas.local'}}
        job=self.action('app_install',arguments)
        self.assertEqual(job['status'],'completed',job['result'])
        status,details=self.request('/api/package-details?app=titan-nextcloud-office')
        self.assertEqual(status,200,details)
        self.assertEqual(details['total_services'],6);self.assertTrue(details['ready'])
        self.assertEqual(details['login']['username'],'admin')
        raw=json.dumps(details)
        for key in ('password','database_password','office_secret'):
            self.assertNotIn(self.app.agent._app_settings['titan-nextcloud-office'][key],raw)


if __name__=='__main__':unittest.main()

import unittest
from tests.test_lifecycle_http import HTTPFixture


class AppMemoryHTTPTests(HTTPFixture, unittest.TestCase):
    def test_preflight_is_authenticated_csrf_and_application_gated(self):
        body = {'app':'titan-nextcloud-office','options':{'resource_profile':'balanced','office_mode':'disabled'}}
        for kwargs, expected in (({'actor':None},401),({'actor':'reader'},403),({'csrf':'wrong'},403),
                                 ({'headers':{'Origin':'https://foreign.example'}},403)):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.request('/api/apps/memory-plan', body, **kwargs)[0], expected)
        self.agent.call.assert_not_called()
        self.agent.call.return_value = {'allowed':False,'available_bytes':1,'required_available_bytes':2,'plan':{}}
        status, result, _ = self.json_request('/api/apps/memory-plan', body)
        self.assertEqual(status, 200)
        self.assertFalse(result['allowed'])
        self.agent.call.assert_called_once_with('app_memory_preflight', **body)
        self.assertEqual(self.app.store.jobs(), [], 'Preflight must neither create a job nor start any container.')

    def test_preflight_never_accepts_credentials_or_host_memory_overrides(self):
        for body in ({}, {'app':'x','memory_available':2**60}, {'app':'x','options':None},
                     {'app':'x','options':{'password':'secret'}}, {'app':'x','options':{'memory_total':2**60}}):
            with self.subTest(body=body):
                self.assertEqual(self.request('/api/apps/memory-plan', body)[0], 400)
        self.agent.call.assert_not_called()


if __name__ == '__main__':
    unittest.main()

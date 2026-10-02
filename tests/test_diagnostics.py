import json
import unittest
from unittest.mock import Mock
from types import SimpleNamespace
from titan.core import Error
from titan.server import Handler
from titan.diagnostics import report


class DiagnosticsTests(unittest.TestCase):
    def handler(self, role):
        handler = Handler.__new__(Handler)
        agent = Mock()
        agent.call.return_value = {}
        handler.server = SimpleNamespace(app=SimpleNamespace(agent=agent, demo=False))
        handler.path = '/api/diagnostics?download=1'
        handler.user = Mock(return_value={'role': role, 'name': 'test'})
        handler.reply = Mock()
        return handler

    def test_download_requires_admin_and_has_fixed_attachment_name(self):
        handler = self.handler('user')
        with self.assertRaises(Error) as result:
            handler.get()
        self.assertEqual(result.exception.status, 403)
        handler.app.agent.call.assert_not_called()
        handler = self.handler('admin')
        handler.get()
        self.assertEqual(handler.reply.call_args.kwargs['extra']['Content-Disposition'],
                         'attachment; filename="titan-diagnostics.json"')

    def test_only_explicit_metrics_and_component_flags_are_exported(self):
        agent = Mock()
        agent.call.side_effect = [
            {'cpu_percent': 13.5, 'memory_total': 1024, 'token': 'NEVER-EXPORT',
             'password': 'NEVER-EXPORT', 'cpu_temperature': float('nan'),
             'service_details': {'web': {'active': True, 'state': 'active', 'logs': 'NEVER-EXPORT'}}},
            {'components': {'docker': {'available': True, 'missing': [], 'output': 'NEVER-EXPORT'},
                            'vms': {'available': False, 'kvm': False, 'missing': []}}}]
        value = report(agent)
        self.assertEqual(value['system']['cpu_percent'], 13.5)
        self.assertIsNone(value['system']['cpu_temperature'])
        self.assertTrue(value['components']['docker']['available'])
        self.assertFalse(value['components']['vms']['kvm'])
        self.assertNotIn('NEVER-EXPORT', json.dumps(value, allow_nan=False))

    def test_partial_failure_keeps_remaining_sections_and_omits_exception_content(self):
        agent = Mock()
        agent.call.side_effect = [RuntimeError('secret configuration'), {'components': {'docker': {'available': True}}}]
        value = report(agent, demo=True)
        self.assertTrue(value['demo'])
        self.assertTrue(value['components']['docker']['available'])
        self.assertEqual(value['errors'], [{'section': 'system', 'error': 'RuntimeError'}])
        self.assertNotIn('secret configuration', json.dumps(value))

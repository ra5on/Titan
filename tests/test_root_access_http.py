"""Real HTTP routing and authentication, with PTY/file RPCs replaced by mocks."""
from email.message import Message
import io
import json
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call

from titan.server import Application, Handler
from titan.terminal_http import terminal_owner


PASSWORD = 'root-admin-password-12345'
ID = 'a' * 64


class RootAccessHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(self.temp.name)
        self.app.store.setup('admin', PASSWORD)
        self.app.store.create_user('reader', 'reader-password-12345', 'user', 'reader')
        self.tokens = {'admin': self.app.store.login('admin', PASSWORD),
                       'second': self.app.store.login('admin', PASSWORD),
                       'reader': self.app.store.login('reader', 'reader-password-12345')}
        self.users = {name: self.app.store.session(token[0]) for name, token in self.tokens.items()}
        self.app.agent = Mock()
        self.app.agent.call.return_value = {'id': ID, 'cols': 100, 'rows': 30}
        self.app._start_terminal_reaper = Mock()

    def tearDown(self):
        self.app.close_all_terminals()
        self.temp.cleanup()

    def request(self, method, path, body=None, actor='admin', csrf='default', headers=None):
        handler = object.__new__(Handler)
        handler.server = SimpleNamespace(app=self.app)
        handler.command, handler.path = method, path
        handler.client_address = ('127.0.0.1', 12345)
        handler.close_connection = False
        handler.statuses = []
        handler.response_headers = []
        handler.send_response = lambda status: handler.statuses.append(status)
        handler.send_header = lambda key, value: handler.response_headers.append((key, value))
        handler.end_headers = lambda: None
        handler.headers = Message()
        values = {'Host': 'nas.test', 'Content-Type': 'application/json'}
        if actor:
            token, expected = self.tokens[actor]
            values['Cookie'] = 'titan_session=' + token
            if csrf is not None:
                values['X-CSRF-Token'] = expected if csrf == 'default' else csrf
        data = json.dumps(body).encode() if body is not None else b''
        values['Content-Length'] = str(len(data))
        values.update(headers or {})
        for key, value in values.items():
            handler.headers[key] = value
        handler.rfile, handler.wfile = io.BytesIO(data), io.BytesIO()
        (handler.do_POST if method == 'POST' else handler.do_GET)()
        return handler

    def enable(self):
        handler = self.request('POST', '/api/root-access', {'password': PASSWORD, 'minutes': 5})
        self.assertEqual(handler.statuses, [200], handler.wfile.getvalue())
        return json.loads(handler.wfile.getvalue())

    def test_routes_require_active_admin_and_mutations_require_csrf(self):
        for actor, status in ((None, 401), ('reader', 403)):
            for method, path, body in (('GET', '/api/root-access', None),
                ('POST', '/api/root-access', {'password': PASSWORD}),
                ('POST', '/api/root-terminal', {'action': 'create'}),
                ('GET', '/api/root-terminal/output?id=' + ID, None)):
                with self.subTest(actor=actor, path=path):
                    self.assertEqual(self.request(method, path, body, actor=actor).statuses, [status])
        for path, body in (('/api/root-access', {'password': PASSWORD}),
                           ('/api/root-access', {'enabled': False}),
                           ('/api/root-terminal', {'action': 'close', 'id': ID})):
            for csrf in (None, 'wrong'):
                self.assertEqual(self.request('POST', path, body, csrf=csrf).statuses, [403])
        self.assertFalse(self.app.root_access_grants)
        self.app.agent.call.assert_not_called()

    def test_foreign_origin_rejected_before_authorization_or_rpc(self):
        for headers in ({'Origin': 'https://evil.test'}, {'Sec-Fetch-Site': 'cross-site'}):
            self.assertEqual(self.request('POST', '/api/root-access', {'password': PASSWORD}, headers=headers).statuses, [403])
        self.enable()
        self.app.agent.call.reset_mock()
        self.assertEqual(self.request('GET', '/api/root-terminal/output?id=' + ID, headers={'Origin': 'https://evil.test'}).statuses, [403])
        self.app.agent.call.assert_not_called()

    def test_separate_login_has_no_grant_and_root_parameters_are_not_caller_selectable(self):
        self.enable()
        status = self.request('GET', '/api/root-access', actor='second')
        self.assertFalse(json.loads(status.wfile.getvalue())['enabled'])
        self.assertEqual(self.request('POST', '/api/root-terminal', {'action': 'create'}, actor='second').statuses, [403])
        for extra in ('root', 'user', 'owner', 'command', 'shell', 'cwd', 'allow_root', 'deadline'):
            self.assertEqual(self.request('POST', '/api/root-terminal', {'action': 'create', extra: 'injected'}).statuses, [400])
        self.app.agent.call.assert_not_called()
        self.assertEqual(self.request('POST', '/api/root-terminal', {'action': 'create'}).statuses, [200])
        self.app.agent.call.assert_called_with('root_terminal_create', owner=terminal_owner(self.users['admin']), cols=100, rows=30, deadline=self.app.root_access_grants[terminal_owner(self.users['admin'])]['deadline'])

    def test_status_and_output_queries_reject_duplicates_unknown_and_blank_parameters(self):
        self.enable()
        for path in ('/api/root-access?extra=', '/api/root-access?x=1',
                     '/api/root-terminal/output', '/api/root-terminal/output?id=',
                     '/api/root-terminal/output?id=' + ID + '&id=' + ID,
                     '/api/root-terminal/output?id=' + ID + '&token=',
                     '/api/root-terminal/output?id=' + ID + '&owner=admin'):
            with self.subTest(path=path):
                self.assertEqual(self.request('GET', path).statuses, [400])
        self.app.agent.call.assert_not_called()

    def test_disable_and_logout_close_root_pty_and_invalidate_grant(self):
        self.enable()
        self.request('POST', '/api/root-terminal', {'action': 'create'})
        self.app.agent.call.reset_mock()
        self.assertEqual(self.request('POST', '/api/root-access', {'enabled': False}).statuses, [200])
        self.app.agent.call.assert_called_once_with('root_terminal_close', owner=terminal_owner(self.users['admin']), id=ID)
        self.assertFalse(self.app.root_access_grants)
        self.enable()
        self.request('POST', '/api/root-terminal', {'action': 'create'})
        self.app.agent.call.reset_mock()
        self.assertEqual(self.request('POST', '/api/logout', {}).statuses, [200])
        self.app.agent.call.assert_called_once_with('root_terminal_close', owner=terminal_owner(self.users['admin']), id=ID)
        self.assertFalse(self.app.root_access_grants)
        self.assertEqual(self.request('POST', '/api/root-terminal', {'action': 'create'}).statuses, [401])

    def test_root_file_dispatch_is_derived_from_grant_not_request_fields(self):
        # Ordinary mode keeps the NAS-scoped trusted RPC; root mode uses its
        # separate fixed worker. The mock returns no real system-file content.
        self.app.agent.call.return_value = {'entries': [], 'total': 0}
        path = '/api/files?share=@system&path=var/srv/titan'
        self.assertEqual(self.request('GET', path).statuses, [200])
        self.assertEqual(self.app.agent.call.call_args.args, ('system_file',))

        self.enable()
        self.assertEqual(self.request('GET', '/api/files?share=@system&path=etc').statuses, [200])
        self.assertEqual(self.app.agent.call.call_args.args, ('root_system_file',))
        before = self.app.agent.call.call_count
        self.assertEqual(self.request('POST', '/api/files', {'share': '@system', 'action': 'read', 'path': 'etc/shadow', 'root_access': True}).statuses, [400])
        self.assertEqual(self.request('GET', '/api/files?share=@system&path=etc', actor='reader').statuses, [403])
        self.assertEqual(self.app.agent.call.call_count, before)
        self.app.root_access_grants[terminal_owner(self.users['admin'])]['deadline'] = time.monotonic() - 1
        self.request('GET', path)
        self.assertEqual(self.app.agent.call.call_args.args, ('system_file',))

    def test_root_cannot_be_requested_via_generic_actions_or_extra_file_arguments(self):
        for operation in ('root_terminal_create', 'root_system_file'):
            handler = self.request('POST', '/api/actions', {'operation': operation, 'arguments': {}})
            self.assertEqual(handler.statuses, [400])
        for name in ('root_access', 'canonicalized', 'user', 'root', 'destination_root'):
            body = {'share': '@system', 'action': 'upload', 'path': 'etc/injected', 'offset': 0, 'data': 'eA==', name: True}
            self.assertEqual(self.request('POST', '/api/files', body).statuses, [400])
        self.app.agent.call.assert_not_called()

    def test_stream_rechecks_root_grant_after_poll_and_suppresses_stale_output(self):
        self.enable()
        polls = 0
        def dispatch(operation, **arguments):
            nonlocal polls
            if operation == 'root_terminal_poll':
                polls += 1
                if polls == 1:
                    return {'data': '', 'eof': False}
                self.app.disable_root_access(self.users['admin'])
                return {'data': 'c2VjcmV0', 'eof': False}
            if operation == 'root_terminal_close':
                return {'closed': True}
            self.fail('Unexpected operation: ' + operation)
        self.app.agent.call.side_effect = dispatch
        handler = self.request('GET', '/api/root-terminal/output?id=' + ID)
        self.assertEqual(handler.statuses, [200])
        data = handler.wfile.getvalue()
        self.assertIn(b'event: exit', data)
        self.assertNotIn(b'event: output', data)
        self.assertNotIn(b'c2VjcmV0', data)
        self.assertFalse(self.app.terminal_sessions)
        self.assertFalse(self.app.terminal_streams)
        self.assertFalse(self.app.root_access_grants)


if __name__ == '__main__':
    unittest.main()

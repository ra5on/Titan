"""Bounded catalog GET retries retain transport and template safeguards."""
import errno
import io
import socket
import ssl
import unittest
from unittest.mock import Mock, patch
import urllib.error

from titan.app_stores import StoreMixin
from titan.core import Error
from titan.store_sources import download


class StoreDownloadTests(unittest.TestCase):
    url = 'https://api.github.com/repos/example/store?token=PRIVATE-QUERY'

    def http_error(self, status, headers=None):
        return urllib.error.HTTPError(self.url, status, 'PRIVATE-REASON', headers or {}, io.BytesIO(b'PRIVATE-RESPONSE'))

    def response(self, raw=b'catalog'):
        response = Mock()
        response.read.return_value = raw
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def run_download(self, outcomes, limit=1024):
        opener = Mock(); opener.open.side_effect = outcomes
        with patch('titan.store_sources.urllib.request.build_opener', return_value=opener), patch('titan.store_sources.time.sleep') as sleep:
            result = download(self.url, limit)
        return result, opener, sleep

    def test_transient_http_statuses_retry_then_return_the_same_bounded_get(self):
        for status in (408, 425, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                response = self.response()
                result, opener, sleep = self.run_download([self.http_error(status), response])
                self.assertEqual(result, b'catalog')
                self.assertEqual(opener.open.call_count, 2)
                sleep.assert_called_once_with(1)
                for call in opener.open.call_args_list:
                    self.assertEqual(call.args[0].full_url, self.url)
                    self.assertEqual(call.args[0].get_method(), 'GET')
                    self.assertEqual(call.kwargs['timeout'], 30)
                response.read.assert_called_once_with(1025)

    def test_retries_exhaust_with_http_code_and_no_remote_secret_material(self):
        opener = Mock(); opener.open.side_effect = [self.http_error(503) for _ in range(3)]
        with patch('titan.store_sources.urllib.request.build_opener', return_value=opener), patch('titan.store_sources.time.sleep') as sleep, self.assertRaises(Error) as caught:
            download(self.url, 1024)
        self.assertEqual(opener.open.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 3])
        self.assertEqual(caught.exception.status, 503)
        self.assertIn('HTTP 503', str(caught.exception))
        self.assertIn('3 Versuche', str(caught.exception))
        self.assertNotIn('PRIVATE', str(caught.exception))
        self.assertNotIn('github.com', str(caught.exception))

    def test_explicit_rate_limit_and_retry_after_are_bounded(self):
        for headers in ({'X-RateLimit-Remaining':'0'}, {'Retry-After':'3600'}):
            with self.subTest(headers=headers):
                _, opener, sleep = self.run_download([self.http_error(403, headers), self.response()])
                self.assertEqual(opener.open.call_count, 2)
                self.assertLessEqual(sleep.call_args.args[0], 10)
        _, _, sleep = self.run_download([self.http_error(429, {'Retry-After':'2'}), self.response()])
        sleep.assert_called_once_with(2)

    def test_permission_missing_resource_and_tls_errors_do_not_retry(self):
        errors = [self.http_error(code) for code in (401, 403, 404)] + [urllib.error.URLError(ssl.SSLCertVerificationError('PRIVATE-CERT')), urllib.error.URLError(socket.gaierror(socket.EAI_NONAME, 'PRIVATE-DNS'))]
        for failure in errors:
            with self.subTest(failure=type(failure).__name__):
                opener = Mock(); opener.open.side_effect = failure
                with patch('titan.store_sources.urllib.request.build_opener', return_value=opener), patch('titan.store_sources.time.sleep') as sleep, self.assertRaises(Error) as caught:
                    download(self.url, 1024)
                self.assertEqual(opener.open.call_count, 1)
                sleep.assert_not_called()
                self.assertNotIn('PRIVATE', str(caught.exception))

    def test_temporary_network_and_read_failures_retry_without_reparsing(self):
        for failure in (TimeoutError('PRIVATE-TIMEOUT'), urllib.error.URLError(socket.gaierror(socket.EAI_AGAIN, 'PRIVATE-DNS')), ConnectionResetError(errno.ECONNRESET, 'PRIVATE-CONNECTION')):
            with self.subTest(failure=type(failure).__name__):
                _, opener, sleep = self.run_download([failure, self.response()])
                self.assertEqual(opener.open.call_count, 2)
                sleep.assert_called_once_with(1)
        response = self.response(); response.read.side_effect = TimeoutError('PRIVATE-READ')
        _, opener, _ = self.run_download([response, self.response()])
        self.assertEqual(opener.open.call_count, 2)

    def test_redirect_and_download_limit_never_retry(self):
        for failure in (Error('Store-Weiterleitungen sind nicht erlaubt.'), self.response(b'12345')):
            opener = Mock(); opener.open.side_effect = [failure] if isinstance(failure, Error) else None
            if not isinstance(failure, Error): opener.open.return_value = failure
            with patch('titan.store_sources.urllib.request.build_opener', return_value=opener), patch('titan.store_sources.time.sleep') as sleep, self.assertRaises(Error):
                download(self.url, 4)
            self.assertEqual(opener.open.call_count, 1)
            sleep.assert_not_called()

    def test_download_retry_does_not_retry_invalid_catalog_json(self):
        with patch('titan.store_sources.download', return_value=b'not-json') as fetch, self.assertRaisesRegex(Error, 'JSONDecodeError'):
            StoreMixin.store_document('https://raw.githubusercontent.com/example/store/main/catalog.json')
        fetch.assert_called_once()


if __name__ == '__main__': unittest.main()

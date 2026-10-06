#!/usr/bin/env python3
"""Real Euro-Office conversion/save checks on the disposable package CI runner.

The browser editor/coauthoring remains a separate manual acceptance check. This
fixture exercises Titan's real HTTP handlers and binary revision checked writes,
not a mocked document engine. It never configures the runner's NAS services.
"""
from http.server import ThreadingHTTPServer
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from titan.core import Error
from titan.files import operate
from titan.office_gateway import engine_connection, save_path, sign
from titan.server import Application, Handler


def http_failure(stage, status, raw, cache_url=None):
    """Report protocol errors without logging signed URLs or cache capabilities."""
    try:
        payload = json.loads(raw)
        message = payload.get('message', '') if isinstance(payload, dict) else ''
    except (ValueError, UnicodeError):
        message = ''
    if not isinstance(message, str): message = ''
    message = re.sub(r'https?://[^\s]+', '[redacted URL]', message)
    message = re.sub(r'[A-Za-z0-9_+./=-]{32,}', '[redacted token]', message)
    message = ' '.join(message.split())[:240]
    details = 'HTTP ' + str(status) + (', ' + message if message else '')
    if cache_url:
        # These are our two generated test documents. Unknown path components
        # are never printed, even if an upstream engine changes its URL shape.
        segments = urllib.parse.urlsplit(cache_url).path.split('/')
        safe = []
        for value in segments:
            if value in ('', 'cache', 'files', 'data', 'output.docx', 'output.odt', 'Roundtrip.docx', 'Roundtrip.odt'):
                safe.append(value)
            elif re.fullmatch(r'conv_[a-f0-9]{64}_(?:docx|odt)', value):
                safe.append('conv_[document-key]_' + value.rsplit('_', 1)[1])
            elif re.fullmatch(r'[a-f0-9]{64}', value):
                safe.append('[document-key]')
            else:
                safe.append('[entry]')
        details += ', cache path ' + '/'.join(safe)
    return Error(stage + ' (' + details + ').')


class OfficeSmokeHandler(Handler):
    """Mirror Caddy's internal-port Host rewrite, leaving public routes strict."""
    def safe(self, function):
        path=urllib.parse.urlsplit(self.path).path
        internal=(self.command=='GET' and path=='/office/internal/file' or
                  self.command=='POST' and path=='/office/internal/callback')
        bridge_host=self.server.office_bridge_gateway+':5101'
        if internal and self.headers.get('Host')==bridge_host:
            # Production's 5101 Caddy listener forwards only these requests to
            # the web service with TITAN_ORIGIN_HOST. Do the same in this direct
            # fixture, without weakening Handler's normal origin/Host checks.
            self.headers.replace_header('Host',urllib.parse.urlsplit(self.app.origin).netloc)
        return super().safe(function)

    def log_message(self, *args):
        pass  # Signed capability URLs stay out of CI logs.


def document_bytes(text):
    """A small valid OOXML document, with no external relationships/macros."""
    from xml.sax.saxutils import escape
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml', '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + escape(text) + '</w:t></w:r></w:p><w:sectPr/></w:body></w:document>')
    return output.getvalue()


def run_office_gateway_smoke(base, options, run):
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise Error('Office runtime acceptance is restricted to the disposable CI runner.')
    container = json.loads(run(['docker', 'inspect', 'titan-titan-nextcloud-office-eurooffice']))[0]
    if container['Config']['Labels'].get('io.titan.app') != 'titan-nextcloud-office':
        raise Error('Unexpected Office test container.')
    endpoints = list(container['NetworkSettings']['Networks'].values())
    if len(endpoints) != 1 or container['State'].get('Health', {}).get('Status') != 'healthy':
        raise Error('Office test engine/network is not ready.')
    endpoint = endpoints[0]
    for name in ('IPAddress', 'Gateway'):
        address = ipaddress.ip_address(endpoint[name])
        if address.version != 4 or address.is_loopback or address.is_unspecified or not address.is_private:
            raise Error('Unexpected Office test network address.')
    runtime = {'secret': options['office_secret'], 'engine_origin': 'http://' + endpoint['IPAddress'] + ':80', 'bridge_gateway': endpoint['Gateway']}
    files = Path(base) / 'gateway-documents'
    files.mkdir(mode=0o700)
    document = files / 'Roundtrip.docx'
    odt_document = files / 'Original.odt'
    marker = 'Titan real document gateway ' + secrets.token_hex(12)
    original = document_bytes(marker)
    document.write_bytes(original)
    document.chmod(0o640)
    before = document.stat()
    origin = 'http://127.0.0.1:5101'
    app = Application(Path(base) / 'gateway-web', origin=origin)
    password = secrets.token_urlsafe(32)
    app.store.create_user('writer', password, 'user', 'writer')
    token, csrf = app.store.login('writer', password)
    operations = []

    class FileAgent:
        def call(self, operation, **arguments):
            if operation == 'app_office_runtime': return dict(runtime)
            if operation == 'shares': return [{'name': 'docs', 'path': str(files), 'readers': [], 'writers': ['writer']}]
            if operation not in ('file', 'office_write'):
                raise Error('The Office fixture does not grant host operations.', 403)
            user, share = arguments.pop('user'), arguments.pop('share')
            if user != 'writer' or share != 'docs' or arguments.pop('admin', False):
                raise Error('Document access denied.', 403)
            action = 'office_write' if operation == 'office_write' else arguments.pop('action')
            if action not in ('read', 'office_write') or arguments.get('path') not in (document.name,odt_document.name):
                raise Error('Document operation denied.', 403)
            if action == 'office_write': operations.append(operation)
            return operate(files, action, **arguments)

    app.agent = FileAgent()
    server = ThreadingHTTPServer(('0.0.0.0', 5101), OfficeSmokeHandler)
    server.app = app
    server.office_bridge_gateway=runtime['bridge_gateway']
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
    thread.start()

    def request(path, body=None, authenticated=True):
        headers = {'Content-Type': 'application/json', 'Origin': origin}
        if authenticated: headers.update({'Cookie': 'titan_session=' + token, 'X-CSRF-Token': csrf})
        query = urllib.request.Request(origin + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            with urllib.request.urlopen(query, timeout=60) as response: return response.status, response.read()
        except urllib.error.HTTPError as response:
            return response.code, response.read()

    def converter(filetype, outputtype, url, key=None):
        key = key or 'titan-ci-' + secrets.token_hex(16)
        payload = {'async': False, 'filetype': filetype, 'outputtype': outputtype, 'key': key, 'title': 'Roundtrip.' + outputtype, 'url': url}
        body = {**payload, 'token': sign(payload, runtime['secret'])}
        connection = engine_connection(runtime)
        connection.timeout = 180
        try:
            connection.request('POST', '/converter?shardkey=' + key, body=json.dumps(body).encode(), headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
            response = connection.getresponse()
            result = json.loads(response.read(65536))
            if response.status != 200 or result.get('error') or result.get('endConvert') is not True:
                raise Error('Real Office conversion failed (HTTP ' + str(response.status) + ', code ' + str(result.get('error', 'incomplete')) + ').')
            path = save_path(result.get('fileUrl', ''), runtime, origin)
            return runtime['engine_origin'] + path
        finally:
            connection.close()

    try:
        status, raw = request('/api/office/session', {'share': 'docs', 'path': document.name})
        if status != 200: raise http_failure('Real Office session creation failed', status, raw)
        session = urllib.parse.parse_qs(urllib.parse.urlsplit(json.loads(raw)['url']).query)['session'][0]
        status, raw = request('/api/office/config?session=' + session)
        if status != 200: raise http_failure('Real Office configuration failed', status, raw)
        config = json.loads(raw)['config']
        revision = app.store.config('office-sessions')[session]['revision']
        status, raw = request('/office-engine/web-apps/apps/api/documents/api.js')
        if status != 200 or b'DocsAPI' not in raw: raise http_failure('Real Office JavaScript proxy failed', status, raw)
        # The engine must fetch the capability URL itself over its Docker bridge.
        # Use this user's actual document key for the browser-cache proxy check.
        # Unrelated converter keys are deliberately not authorized by Titan.
        converted_odt = converter('docx', 'odt', config['document']['url'], config['document']['key'])
        status, odt = request('/office-engine' + save_path(converted_odt, runtime, origin))
        if status != 200: raise http_failure('Real Office converted-document proxy failed', status, odt, converted_odt)
        with zipfile.ZipFile(io.BytesIO(odt)) as archive:
            if archive.read('mimetype') != b'application/vnd.oasis.opendocument.text': raise Error('Office did not produce an ODT document.')
        odt_document.write_bytes(odt)
        odt_document.chmod(0o640)
        converted = converter('odt', 'docx', converted_odt)
        callback = '/office/internal/callback?session=' + session
        saved = {'key': config['document']['key'], 'status': 2, 'url': converted}
        status, raw = request(callback, {'token': sign({'payload': saved}, runtime['secret'])}, authenticated=False)
        if status != 200 or json.loads(raw).get('error') != 0: raise http_failure('Real Office binary save callback failed', status, raw)
        content = document.read_bytes()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if marker not in ''.join(ET.fromstring(archive.read('word/document.xml')).itertext()): raise Error('The converted document lost its text.')
        after = document.stat()
        if (before.st_uid, before.st_gid, before.st_mode & 0o777) != (after.st_uid, after.st_gid, after.st_mode & 0o777):
            raise Error('Office save changed document ownership or permissions.')
        if operations != ['office_write'] or app.store.config('office-sessions')[session]['revision'] == revision:
            raise Error('Office save did not use the revision checked file operation.')
        # Invalid signatures and arbitrary engine-fetch URLs may never overwrite.
        for body in ({'token': 'invalid'}, {'token': sign({'payload': {**saved, 'url': 'http://169.254.169.254/latest/meta-data/'}}, runtime['secret'])}):
            status, raw = request(callback, body, authenticated=False)
            if status != 200 or json.loads(raw).get('error') != 1 or document.read_bytes() != content:
                raise Error('Office refused-save protection failed.')
        status, raw = request('/office/internal/file?session=' + session, authenticated=False)
        if status != 200 or raw != content: raise Error('Office updated document fetch failed.')
        status, _ = request('/office/internal/file?session=invalid', authenticated=False)
        if status != 403: raise Error('Unsigned document fetch was not denied.')
        # Editing an ODT in the engine can yield OOXML: Titan must convert back
        # before replacing the original, never store DOCX bytes under .odt.
        status, raw = request('/api/office/session', {'share':'docs','path':odt_document.name})
        if status != 200: raise http_failure('Original-format Office session failed', status, raw)
        odt_session=urllib.parse.parse_qs(urllib.parse.urlsplit(json.loads(raw)['url']).query)['session'][0]
        odt_record=app.store.config('office-sessions')[odt_session]
        odt_before=odt_document.stat()
        status, raw=request('/office/internal/callback?session='+odt_session,
                            {'token':sign({'payload':{'key':odt_record['key'],'status':2,'url':converted,'filetype':'docx'}},runtime['secret'])},authenticated=False)
        if status != 200 or json.loads(raw).get('error') != 0: raise http_failure('Office original-format save callback failed', status, raw)
        with zipfile.ZipFile(io.BytesIO(odt_document.read_bytes())) as archive:
            if archive.read('mimetype') != b'application/vnd.oasis.opendocument.text': raise Error('Office original-format save changed ODT into another file type.')
            if marker not in ''.join(ET.fromstring(archive.read('content.xml')).itertext()): raise Error('Office original-format conversion lost the document text.')
        odt_after=odt_document.stat()
        if (odt_before.st_uid,odt_before.st_gid,odt_before.st_mode&0o777)!=(odt_after.st_uid,odt_after.st_gid,odt_after.st_mode&0o777):
            raise Error('Original-format Office save changed document permissions.')
        if operations != ['office_write','office_write']: raise Error('Original-format save did not use the validated file writer.')
        return {'gateway_fetch': True, 'engine_conversion': True, 'signed_save': True, 'preserved_permissions': True, 'rejected_invalid_saves': True, 'odt_format_preserved':True}
    finally:
        app.stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

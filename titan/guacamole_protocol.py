"""Bounded Guacamole handshake and RFC6455 framing for the Titan gateway.

Only the server chooses the destination. The browser never receives guacd's
connection ID, endpoint credentials, or an unrestricted guacd connection.
"""
import base64
import codecs
import hashlib
import struct

from .core import Error

LIMIT = 1024 * 1024


def instruction(*values):
    return (','.join(f'{len(str(value))}.{value}' for value in values) + ';').encode('utf-8')


class Instructions:
    def __init__(self):
        self.decoder = codecs.getincrementaldecoder('utf-8')('strict')
        self.buffer = ''

    def feed(self, data):
        self.buffer += self.decoder.decode(data)
        if len(self.buffer) > LIMIT:
            raise Error('Sitzungsnachricht zu groß.', 413)
        result = []
        while self.buffer:
            pos, values = 0, []
            while True:
                dot = self.buffer.find('.', pos)
                if dot < 0:
                    if len(self.buffer) - pos > 7:
                        raise Error('Ungültige Sitzungsnachricht.')
                    return result
                length = self.buffer[pos:dot]
                if not length.isascii() or not length.isdigit() or len(length) > 7 or int(length) > LIMIT:
                    raise Error('Ungültige Sitzungsnachricht.')
                end = dot + 1 + int(length)
                if end >= len(self.buffer):
                    return result
                values.append(self.buffer[dot + 1:end])
                if len(values) > 128:
                    raise Error('Zu viele Sitzungsparameter.')
                separator = self.buffer[end]
                pos = end + 1
                if separator == ';':
                    result.append(values)
                    self.buffer = self.buffer[pos:]
                    break
                if separator != ',':
                    raise Error('Ungültige Sitzungsnachricht.')
        return result


def handshake(stream, endpoint, width, height):
    # Read one instruction at a time: never consume the first display update.
    def receive():
        parser = Instructions()
        while True:
            data = stream.recv(1)
            if not data:
                raise Error('Guacamole hat die Verbindung geschlossen.', 503)
            values = parser.feed(data)
            if values:
                return values[0]
    stream.sendall(instruction('select', endpoint['protocol']))
    args = receive()
    if not args or args[0] != 'args':
        raise Error('Guacamole ist nicht bereit.', 503)
    stream.sendall(instruction('size', width, height, 96) + instruction('audio') +
                   instruction('video') + instruction('image', 'image/png', 'image/jpeg'))
    parameters = {'hostname': endpoint['hostname'], 'port': endpoint['port'],
                  'password': endpoint.get('password', ''), 'read-only': 'false',
                  'clipboard-encoding': 'UTF-8', 'enable-sftp': 'false'}
    stream.sendall(instruction('connect', *(('VERSION_1_0_0' if key.startswith('VERSION_') else parameters.get(key, '')) for key in args[1:])))
    ready = receive()
    if not ready or ready[0] != 'ready':
        raise Error('Verbindung zum Bildschirm fehlgeschlagen.', 503)


def websocket_accept(headers):
    try:
        key = headers['Sec-WebSocket-Key']
        if len(base64.b64decode(key, validate=True)) != 16:
            raise ValueError()
    except (ValueError, TypeError):
        raise Error('Ungültiger WebSocket-Schlüssel.') from None
    if (headers.get('Upgrade', '').lower() != 'websocket' or
            'upgrade' not in [value.strip().lower() for value in headers.get('Connection', '').split(',')] or
            headers.get('Sec-WebSocket-Version') != '13' or
            'guacamole' not in [value.strip() for value in headers.get('Sec-WebSocket-Protocol', '').split(',')]):
        raise Error('Guacamole-WebSocket erforderlich.')
    return base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()


def frame(data, opcode=1):
    size = len(data)
    length = bytes([size]) if size < 126 else b'\x7e' + struct.pack('!H', size) if size < 65536 else b'\x7f' + struct.pack('!Q', size)
    return bytes([0x80 | opcode]) + length + data


class Frames:
    def __init__(self):
        self.buffer = bytearray()
        self.fragment = None

    def feed(self, data):
        self.buffer.extend(data)
        messages = []
        while len(self.buffer) >= 2:
            first, second = self.buffer[:2]
            final, opcode, size, offset = bool(first & 128), first & 15, second & 127, 2
            if first & 0x70 or not second & 128 or opcode not in (0, 1, 8, 9, 10):
                raise Error('Ungültiger WebSocket-Rahmen.')
            if size in (126, 127):
                extra = 2 if size == 126 else 8
                if len(self.buffer) < 2 + extra:
                    break
                size = int.from_bytes(self.buffer[2:2 + extra], 'big'); offset += extra
            if size > LIMIT or (opcode >= 8 and (not final or size > 125)):
                raise Error('WebSocket-Nachricht zu groß oder ungültig.')
            if len(self.buffer) < offset + 4 + size:
                break
            mask = self.buffer[offset:offset + 4]; offset += 4
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(self.buffer[offset:offset + size]))
            del self.buffer[:offset + size]
            if opcode >= 8:
                messages.append((opcode, payload)); continue
            if opcode == 1:
                if self.fragment is not None:
                    raise Error('Ungültige WebSocket-Fragmente.')
                self.fragment = bytearray()
            elif self.fragment is None:
                raise Error('Fehlendes WebSocket-Fragment.')
            self.fragment.extend(payload)
            if len(self.fragment) > LIMIT:
                raise Error('WebSocket-Nachricht zu groß.')
            if final:
                payload = bytes(self.fragment); payload.decode('utf-8', 'strict')
                messages.append((1, payload)); self.fragment = None
        return messages

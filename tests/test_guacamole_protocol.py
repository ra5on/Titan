import base64
import socket
import struct
import threading
import unittest

from titan.core import Error
from titan.guacamole_protocol import Frames, Instructions, handshake, instruction, websocket_accept


def masked(value, opcode=1, final=True):
    mask = b'abcd'
    length = len(value)
    encoded = bytes([128 | length]) if length < 126 else bytes([254]) + struct.pack('!H', length)
    return bytes([(128 if final else 0) | opcode]) + encoded + mask + bytes(byte ^ mask[i % 4] for i, byte in enumerate(value))


class ProtocolTests(unittest.TestCase):
    def test_unicode_and_split_instructions(self):
        parser = Instructions()
        result = []
        for byte in instruction('name', 'Grüße 😀') + instruction('sync', 123):
            result += parser.feed(bytes([byte]))
        self.assertEqual(result, [['name', 'Grüße 😀'], ['sync', '123']])

    def test_fragmentation_and_interleaved_ping(self):
        parser = Frames()
        wire = masked(b'hel', final=False) + masked(b'ping', 9) + masked(b'lo', 0)
        results = []
        for byte in wire:
            results += parser.feed(bytes([byte]))
        self.assertEqual(results, [(9, b'ping'), (1, b'hello')])

    def test_rejects_unmasked_binary_oversize_and_unsolicited_continuation(self):
        for wire in [b'\x81\x01a', masked(b'a', 2), masked(b'a', 0), b'\x81\xff' + struct.pack('!Q', 2**40)]:
            with self.subTest(wire=wire), self.assertRaises(Error):
                Frames().feed(wire)

    def test_handshake_does_not_consume_display_and_keeps_credentials_server_side(self):
        client, server = socket.socketpair()
        self.addCleanup(client.close); self.addCleanup(server.close)
        client.settimeout(3); server.settimeout(3)
        received = []
        def guacd():
            parser = Instructions()
            while not received:
                received.extend(parser.feed(server.recv(4096)))
            server.sendall(instruction('args', 'VERSION_1_5_0', 'hostname', 'port', 'password'))
            while not any(item[0] == 'connect' for item in received):
                received.extend(parser.feed(server.recv(4096)))
            server.sendall(instruction('ready', '$private-guacd-id') + instruction('name', 'Screen'))
        worker = threading.Thread(target=guacd); worker.start()
        handshake(client, {'protocol':'vnc', 'hostname':'127.0.0.1', 'port':5900, 'password':'private'}, 800, 600)
        self.assertEqual(client.recv(4096), instruction('name', 'Screen'))
        worker.join(3)
        self.assertEqual(received[-1], ['connect', 'VERSION_1_0_0', '127.0.0.1', '5900', 'private'])

    def test_websocket_handshake(self):
        headers = {'Upgrade':'websocket', 'Connection':'keep-alive, Upgrade', 'Sec-WebSocket-Version':'13',
                   'Sec-WebSocket-Protocol':'guacamole', 'Sec-WebSocket-Key':'dGhlIHNhbXBsZSBub25jZQ=='}
        self.assertEqual(websocket_accept(headers), 's3pPLMBiTxaQ9kYGzzhZRbK+xOo=')
        for key in headers:
            with self.subTest(key=key), self.assertRaises(Error):
                websocket_accept({**headers, key:''})


if __name__ == '__main__':
    unittest.main()

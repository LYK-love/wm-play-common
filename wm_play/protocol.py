from __future__ import annotations

import json
import socket
import struct


MAGIC = b'DPM1'
MSG_FRAME = b'F'
MSG_KEY = b'K'
MSG_META = b'M'


def recv_exact(sock: socket.socket, n: int) -> bytes:
  out = bytearray()
  while len(out) < n:
    chunk = sock.recv(n - len(out))
    if not chunk:
      raise ConnectionError('socket closed')
    out.extend(chunk)
  return bytes(out)


def send_message(sock: socket.socket, msg_type: bytes, payload: bytes) -> None:
  sock.sendall(msg_type + struct.pack('!I', len(payload)) + payload)


def recv_message(sock: socket.socket) -> tuple[bytes, bytes]:
  header = recv_exact(sock, 5)
  msg_type = header[:1]
  length = struct.unpack('!I', header[1:])[0]
  payload = recv_exact(sock, length) if length else b''
  return msg_type, payload


def encode_meta(header_lines: list[str]) -> bytes:
  return json.dumps({'header_lines': header_lines}).encode('utf-8')


def decode_meta(payload: bytes) -> list[str]:
  if not payload:
    return []
  data = json.loads(payload.decode('utf-8'))
  header_lines = data.get('header_lines', [])
  return [str(x) for x in header_lines]

from __future__ import annotations

import io
import socket
import struct
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

import pygame

from .api import PlaySession
from .protocol import (
    MAGIC,
    MSG_FRAME,
    MSG_KEY,
    MSG_META,
    encode_meta,
    recv_message,
    send_message,
)


@dataclass
class SharedState:
  frame_jpeg: bytes = b''
  meta_payload: bytes = b''
  frame_id: int = 0
  running: bool = True
  paused: bool = False
  pressed_keys: set[int] = field(default_factory=set)
  commands: deque[str] = field(default_factory=deque)
  lock: threading.Lock = field(default_factory=threading.Lock)
  cond: threading.Condition = field(init=False)

  def __post_init__(self):
    self.cond = threading.Condition(self.lock)

  def set_frame(self, jpg: bytes, meta_payload: bytes = b'') -> None:
    with self.cond:
      self.frame_jpeg = jpg
      self.meta_payload = meta_payload
      self.frame_id += 1
      self.cond.notify_all()

  def get_frame_after(self, last_frame_id: int, timeout: float = 1.0):
    with self.cond:
      self.cond.wait_for(
          lambda: (self.frame_id != last_frame_id) or (not self.running),
          timeout=timeout)
      return self.frame_id, self.frame_jpeg, self.meta_payload

  def enqueue_command(self, cmd: str) -> None:
    with self.lock:
      self.commands.append(cmd)

  def dequeue_commands(self) -> list[str]:
    with self.lock:
      out = list(self.commands)
      self.commands.clear()
      return out

  def set_key(self, key: int, is_down: bool) -> None:
    with self.lock:
      if is_down:
        self.pressed_keys.add(key)
      else:
        self.pressed_keys.discard(key)

  def get_pressed_keys(self) -> set[int]:
    with self.lock:
      return set(self.pressed_keys)


def build_keymap_ordered(keymap):
  ordered = OrderedDict()
  for keys, act in sorted(keymap.items(), key=lambda item: -len(item[0])):
    ordered[keys] = act
  return ordered


def resolve_action(pressed_keys, keymap_ordered) -> int:
  for keys, act in keymap_ordered.items():
    if all(k in pressed_keys for k in keys):
      return act
  return 0


def handle_key_event(shared: SharedState, is_down: bool, key: int) -> None:
  if key in {pygame.K_w, pygame.K_a, pygame.K_s, pygame.K_d, pygame.K_SPACE}:
    shared.set_key(key, is_down)
    return
  if not is_down:
    return
  if key == pygame.K_RETURN:
    shared.enqueue_command('reset')
  elif key == pygame.K_PERIOD:
    shared.enqueue_command('toggle_pause')
  elif key == pygame.K_e:
    shared.enqueue_command('step_once')
  elif key == pygame.K_m:
    shared.enqueue_command('switch_controller')
  elif key == pygame.K_UP:
    shared.enqueue_command('horizon_plus')
  elif key == pygame.K_DOWN:
    shared.enqueue_command('horizon_minus')
  elif key == pygame.K_RIGHT:
    shared.enqueue_command('backend_next')
  elif key == pygame.K_LEFT:
    shared.enqueue_command('backend_prev')


def encode_jpeg(frame, quality: int) -> bytes:
  buf = io.BytesIO()
  frame.save(buf, format='JPEG', quality=quality, optimize=False, progressive=False)
  return buf.getvalue()


def run_game_loop(args, session: PlaySession, shared: SharedState) -> None:
  keymap_ordered = build_keymap_ordered(session.keymap)
  fps = args.stream_fps if args.stream_fps is not None else args.fps
  frame_dt = 1.0 / max(1, fps)

  session.reset()
  init_header = [] if args.no_header else session.header(0, {})
  shared.set_frame(
      encode_jpeg(session.render_frame(args.size, []), args.jpeg_quality),
      encode_meta(init_header))

  while shared.running:
    t0 = time.perf_counter()
    commands = shared.dequeue_commands()
    do_reset = False
    step_once = False
    for cmd in commands:
      if cmd == 'toggle_pause':
        with shared.lock:
          shared.paused = not shared.paused
        continue
      if cmd == 'step_once':
        step_once = True
        continue
      if cmd == 'reset':
        do_reset = True
      elif cmd == 'switch_controller':
        session.switch_controller()
      elif cmd == 'horizon_plus':
        session.adjust_horizon(+1)
      elif cmd == 'horizon_minus':
        session.adjust_horizon(-1)
      elif cmd == 'backend_next':
        session.switch_backend(+1)
      elif cmd == 'backend_prev':
        session.switch_backend(-1)

    if do_reset:
      session.reset()

    with shared.lock:
      paused = shared.paused
    if paused and not step_once:
      time.sleep(0.005)
      continue

    human_action = resolve_action(shared.get_pressed_keys(), keymap_ordered)
    action = session.choose_action(human_action)
    result = session.step(action)
    if result.done or result.trunc:
      session.reset()
    header = [] if args.no_header else session.header(action, result.info)
    shared.set_frame(
        encode_jpeg(session.render_frame(args.size, []), args.jpeg_quality),
        encode_meta(header))

    elapsed = time.perf_counter() - t0
    if elapsed < frame_dt:
      time.sleep(frame_dt - elapsed)


def serve_client(conn: socket.socket, shared: SharedState) -> None:
  conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
  conn.sendall(MAGIC)

  def recv_loop():
    try:
      while shared.running:
        msg_type, payload = recv_message(conn)
        if msg_type != MSG_KEY or len(payload) != 5:
          continue
        is_down = payload[0] == 1
        key = struct.unpack('!i', payload[1:])[0]
        handle_key_event(shared, is_down, key)
    except Exception:
      pass
    finally:
      shared.running = False
      with shared.cond:
        shared.cond.notify_all()

  recv_thread = threading.Thread(target=recv_loop, daemon=True)
  recv_thread.start()

  frame_id = -1
  try:
    while shared.running:
      frame_id, jpg, meta_payload = shared.get_frame_after(frame_id, timeout=1.0)
      if not jpg:
        continue
      send_message(conn, MSG_META, meta_payload)
      send_message(conn, MSG_FRAME, jpg)
  except Exception:
    pass
  finally:
    shared.running = False
    with shared.cond:
      shared.cond.notify_all()
    try:
      conn.close()
    except Exception:
      pass

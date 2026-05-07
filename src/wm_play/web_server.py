from __future__ import annotations

import base64
import io
import os
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any

import pygame
from flask import Flask, jsonify, send_from_directory
from flask_socketio import SocketIO

from .api import PlaySession


WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
app = Flask(__name__, static_folder=WEB_DIR)
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

_shared: WebSharedState | None = None
_session: PlaySession | None = None

ACTION_KEYS = {pygame.K_w, pygame.K_a, pygame.K_s, pygame.K_d, pygame.K_SPACE}


@dataclass
class WebSharedState:
  frame_jpeg: bytes = b''
  frame_id: int = 0
  state: dict[str, Any] = field(default_factory=dict)
  running: bool = True
  paused: bool = False
  target_fps: int = 15
  pressed_keys: set[int] = field(default_factory=set)
  events: deque[dict[str, Any]] = field(default_factory=deque)
  clients: int = 0
  lock: threading.Lock = field(default_factory=threading.Lock)
  cond: threading.Condition = field(init=False)

  def __post_init__(self):
    self.cond = threading.Condition(self.lock)

  def set_frame(self, jpg: bytes, state: dict[str, Any]) -> None:
    with self.cond:
      self.frame_jpeg = jpg
      self.state = state
      self.frame_id += 1
      self.cond.notify_all()

  def get_frame_after(self, last_frame_id: int, timeout: float = 1.0):
    with self.cond:
      self.cond.wait_for(
          lambda: self.frame_id != last_frame_id or not self.running,
          timeout=timeout)
      return self.frame_id, self.frame_jpeg, self.state

  def enqueue_event(self, event: dict[str, Any]) -> None:
    with self.lock:
      self.events.append(event)

  def dequeue_events(self) -> list[dict[str, Any]]:
    with self.lock:
      out = list(self.events)
      self.events.clear()
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


def _jpeg_from_pil(frame, quality: int) -> bytes:
  buf = io.BytesIO()
  frame.save(buf, format='JPEG', quality=quality, optimize=False, progressive=False)
  return buf.getvalue()


def _ram_edit_allowed(session: PlaySession, shared: WebSharedState) -> bool:
  with shared.lock:
    paused = bool(shared.paused)
  get_paused = getattr(session, 'get_paused', None)
  return paused and (not callable(get_paused) or bool(get_paused()))


def _session_supports_ram(session: PlaySession) -> bool:
  return callable(getattr(session, 'get_web_state', None)) and callable(
      getattr(session, '_read_rgb_frame', None))


def _session_is_real_only(session: PlaySession) -> bool:
  fn = getattr(session, 'is_real_only', None)
  if callable(fn):
    return bool(fn())
  for attr in ('wm_envs', 'wm_slots'):
    value = getattr(session, attr, None)
    if value:
      return False
  env = getattr(session, 'env', None)
  envs = getattr(env, 'envs', None)
  if envs is not None:
    return not any(hasattr(backend, 'horizon') for _, backend in envs)
  return True


def _render_state(
    args,
    session: PlaySession,
    shared: WebSharedState,
    action: int = 0,
    info: dict[str, Any] | None = None,
) -> tuple[bytes, dict[str, Any]]:
  info = info or {}
  with shared.lock:
    paused = bool(shared.paused)
    fps = int(shared.target_fps)

  ram_capable = _session_supports_ram(session) and _session_is_real_only(session)
  if ram_capable:
    frame = session._read_rgb_frame()
    from PIL import Image

    img = Image.fromarray(frame, mode='RGB').resize(
        (args.size, args.size), resample=Image.NEAREST)
    state = dict(session.get_web_state())
    state['ram_enabled'] = bool(state.get('all_dims') or state.get('focus_dims'))
  else:
    header = [] if args.no_header else session.header(action, info)
    img = session.render_frame(args.size, [])
    state = {
        'ram_enabled': False,
        'header_lines': header,
        'env_id': header[0] if header else 'world-model play',
        'last_action_name': _action_name(session, action),
    }

  state.update({
      'paused': paused,
      'fps': fps,
      'can_step_once': paused,
      'can_edit': paused and bool(state.get('ram_enabled')),
  })
  return _jpeg_from_pil(img, args.jpeg_quality), state


def _action_name(session: PlaySession, action: int) -> str:
  names = getattr(session, 'action_names', [])
  if 0 <= int(action) < len(names):
    return str(names[int(action)])
  return str(action)


def _process_event(
    event: dict[str, Any], session: PlaySession, shared: WebSharedState
) -> tuple[bool, bool, bool]:
  etype = event.get('type')
  if etype == 'keydown':
    key = int(event['key'])
    if key in ACTION_KEYS:
      shared.set_key(key, True)
      return False, False, False
    if key == pygame.K_RETURN:
      return True, False, False
    if key == pygame.K_PERIOD:
      with shared.lock:
        shared.paused = not shared.paused
      return False, False, True
    if key == pygame.K_e:
      return False, True, False
    if key == pygame.K_m:
      session.switch_controller()
      return False, False, True
    if key == pygame.K_RIGHT:
      session.switch_backend(+1)
      return False, False, True
    if key == pygame.K_LEFT:
      session.switch_backend(-1)
      return False, False, True
    if key == pygame.K_UP:
      session.adjust_horizon(+1)
      return False, False, True
    if key == pygame.K_DOWN:
      session.adjust_horizon(-1)
      return False, False, True
    if key in {pygame.K_MINUS, pygame.K_KP_MINUS}:
      with shared.lock:
        shared.target_fps = max(1, int(shared.target_fps) - 1)
      return False, False, True
    if key in {pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS}:
      with shared.lock:
        shared.target_fps = min(120, int(shared.target_fps) + 1)
      return False, False, True
    return False, False, False

  if etype == 'keyup':
    key = int(event['key'])
    if key in ACTION_KEYS:
      shared.set_key(key, False)
    return False, False, False

  if etype == 'set_fps':
    with shared.lock:
      shared.target_fps = max(1, min(120, int(event.get('fps', 15))))
    return False, False, True

  if etype == 'set_paused':
    with shared.lock:
      shared.paused = bool(event.get('paused', False))
    return False, False, True

  ram_events = {
      'quick_start': 'quick_start',
      'select_dim': '_set_selected_dim',
      'apply_dim_value': '_apply_dim_value_from_web',
      'persist_dim_value': '_persist_dim_value_from_web',
      'clear_persistent': '_clear_all_persistent',
      'toggle_recording': '_toggle_recording',
      'export_now': '_flush_recording',
      'delete_recording': '_discard_recording',
  }
  if etype in ram_events:
    if etype not in {'toggle_recording', 'export_now', 'delete_recording'}:
      if not _ram_edit_allowed(session, shared):
        return False, False, True
    fn = getattr(session, ram_events[etype], None)
    if callable(fn):
      if etype in {'select_dim'}:
        fn(int(event.get('dim', 0)))
      elif etype in {'apply_dim_value', 'persist_dim_value'}:
        fn(int(event.get('dim', 0)), int(event.get('value', 0)))
      elif etype == 'export_now':
        fn('manual_export')
      elif etype == 'delete_recording':
        fn()
      else:
        fn()
    return False, False, True

  if etype == 'unpersist_dim':
    if not _ram_edit_allowed(session, shared):
      return False, False, True
    pool = getattr(session, '_persistent_forces', None)
    if pool is not None:
      pool.pop(int(event.get('dim', -1)), None)
    return False, False, True

  return False, False, False


def run_web_game_loop(args, session: PlaySession, shared: WebSharedState) -> None:
  keymap_ordered = build_keymap_ordered(session.keymap)
  session.reset()
  jpg, state = _render_state(args, session, shared)
  shared.set_frame(jpg, state)

  while shared.running:
    t0 = time.perf_counter()
    do_reset = False
    step_once = False
    needs_render = False
    for event in shared.dequeue_events():
      reset_now, step_now, render_now = _process_event(event, session, shared)
      do_reset = do_reset or reset_now
      step_once = step_once or step_now
      needs_render = needs_render or render_now

    if do_reset:
      session.reset()
      needs_render = True

    with shared.lock:
      paused = shared.paused
      fps = max(1, int(shared.target_fps))

    if paused and not step_once:
      if needs_render:
        jpg, state = _render_state(args, session, shared)
        shared.set_frame(jpg, state)
      time.sleep(0.01)
      continue

    human_action = resolve_action(shared.get_pressed_keys(), keymap_ordered)
    action = session.choose_action(human_action)
    result = session.step(action)
    if result.done or result.trunc:
      session.reset()
    jpg, state = _render_state(args, session, shared, action, result.info)
    shared.set_frame(jpg, state)

    elapsed = time.perf_counter() - t0
    frame_dt = 1.0 / fps
    if elapsed < frame_dt:
      time.sleep(frame_dt - elapsed)


@app.route('/')
def index():
  return send_from_directory(WEB_DIR, 'index.html')


@app.route('/<path:path>')
def static_proxy(path):
  return send_from_directory(WEB_DIR, path)


@app.route('/snapshot')
def snapshot():
  if _shared is None or not _shared.frame_jpeg:
    return jsonify({'ready': False})
  with _shared.lock:
    jpg = _shared.frame_jpeg
    state = dict(_shared.state)
  return jsonify({
      'ready': True,
      'image': base64.b64encode(jpg).decode('utf-8'),
      **state,
  })


@socketio.on('connect')
def handle_connect():
  if _shared is not None:
    _shared.clients += 1
    if _shared.state:
      socketio.emit('state', _shared.state)
    if _shared.frame_jpeg:
      socketio.emit('frame', {
          'image': base64.b64encode(_shared.frame_jpeg).decode('utf-8'),
          **_shared.state,
      })


@socketio.on('disconnect')
def handle_disconnect():
  if _shared is not None:
    _shared.clients -= 1


@socketio.on('event')
def handle_event(data):
  if _shared is not None:
    _shared.enqueue_event(data)


def frame_publisher():
  last_frame_id = -1
  while _shared is not None and _shared.running:
    frame_id, jpg, state = _shared.get_frame_after(last_frame_id, timeout=1.0)
    if _shared is None or not _shared.running:
      break
    if frame_id == last_frame_id:
      continue
    last_frame_id = frame_id
    if _shared.clients > 0 and jpg:
      socketio.emit('frame', {
          'image': base64.b64encode(jpg).decode('utf-8'),
          **state,
      })


def run_web_server(args, session: PlaySession) -> None:
  global _shared, _session
  _session = session
  _shared = WebSharedState(target_fps=max(1, int(args.fps)))

  game_thread = threading.Thread(
      target=run_web_game_loop, args=(args, session, _shared), daemon=True)
  game_thread.start()
  pub_thread = threading.Thread(target=frame_publisher, daemon=True)
  pub_thread.start()

  host = getattr(args, 'web_host', '127.0.0.1')
  port = int(getattr(args, 'web_port', 9876))
  print(f'Web play server running at http://{host}:{port}')
  try:
    socketio.run(
        app,
        host=host,
        port=port,
        use_reloader=False,
        allow_unsafe_werkzeug=True)
  finally:
    if _shared is not None:
      _shared.running = False
      with _shared.cond:
        _shared.cond.notify_all()
    session.close()

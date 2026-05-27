from __future__ import annotations

import base64
import io
import logging
import os
import threading
import time
import warnings
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
warnings.filterwarnings(
    'ignore',
    message='pkg_resources is deprecated as an API.*',
    category=UserWarning,
)
import pygame
from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO

from .api import PlaySession
from .recording import PlayRecorder


WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
app = Flask(__name__, static_folder=WEB_DIR)
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

_shared: WebSharedState | None = None
_session: PlaySession | None = None

ACTION_KEYS = {pygame.K_w, pygame.K_a, pygame.K_s, pygame.K_d, pygame.K_SPACE}


def _action_to_int(action: Any) -> int:
  try:
    arr = np.asarray(action).reshape(-1)
    if arr.size:
      return int(arr[0])
  except Exception:
    pass
  try:
    return int(action)
  except Exception:
    return 0


def _has_items(value: Any) -> bool:
  if value is None:
    return False
  try:
    return len(value) > 0
  except TypeError:
    return bool(value)


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
  recorder: PlayRecorder | None = None
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


def _ram_capable(args, session: PlaySession) -> bool:
  return (
      bool(getattr(args, 'ram', False)) and
      _session_supports_ram(session) and
      _session_is_real_only(session))


def _set_session_paused(session: PlaySession, paused: bool) -> None:
  fn = getattr(session, 'set_paused', None)
  if callable(fn):
    fn(bool(paused))


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
  if info is None:
    info = getattr(session, 'last_info', {}) or {}
  else:
    info = info or {}
  with shared.lock:
    paused = bool(shared.paused)
    fps = int(shared.target_fps)

  ram_capable = _ram_capable(args, session)
  if ram_capable:
    frame = session._read_rgb_frame()
    from PIL import Image

    img = Image.fromarray(frame, mode='RGB').resize(
        (args.size, args.size), resample=Image.NEAREST)
    state = dict(session.get_web_state())
    state['ram_enabled'] = _has_items(state.get('all_dims')) or _has_items(state.get('focus_dims'))
  else:
    header = [] if getattr(args, 'no_header', False) else session.header(action, info)
    img = session.render_frame(args.size, [])
    state = {
        'ram_enabled': False,
        'header_lines': header,
        'env_id': header[0] if header else 'world-model play',
        'last_action_name': _action_name(session, action),
    }

  horizon = _session_horizon(session)
  horizon_editable = horizon is not None
  state.update({
      'paused': paused,
      'fps': fps,
      'horizon': horizon,
      'horizon_display': str(horizon) if horizon_editable else '∞',
      'horizon_editable': horizon_editable,
      'can_step_once': paused,
      'can_edit': paused and bool(state.get('ram_enabled')),
  })
  if shared.recorder is not None:
    state.update(shared.recorder.status())
  return _jpeg_from_pil(img, args.jpeg_quality), state


def _action_name(session: PlaySession, action: int) -> str:
  names = getattr(session, 'action_names', [])
  action_idx = _action_to_int(action)
  if 0 <= action_idx < len(names):
    return str(names[action_idx])
  return str(action_idx)


def _record_frame(args, session: PlaySession, ram_capable: bool) -> np.ndarray:
  if ram_capable and callable(getattr(session, '_read_rgb_frame', None)):
    return np.asarray(session._read_rgb_frame(), dtype=np.uint8)
  return np.asarray(session.render_frame(args.size, []).convert('RGB'), dtype=np.uint8)


def _record_ram(session: PlaySession, state: dict[str, Any], ram_capable: bool):
  if not ram_capable:
    return None
  ram = getattr(session, 'current_ram', None)
  if ram is None:
    ram = state.get('ram')
  return None if ram is None else np.asarray(ram, dtype=np.uint8)


def _record_metadata(session: PlaySession, state: dict[str, Any]) -> dict[str, Any]:
  fn = getattr(session, 'record_metadata', None)
  extra = fn() if callable(fn) else {}
  return {
      'env_id': state.get('env_id', getattr(session, 'env_id', '')),
      'backend': state.get('backend', None),
      'action_names': list(getattr(session, 'action_names', [])),
      **(extra or {}),
  }


def _session_horizon(session: PlaySession) -> int | None:
  value = getattr(session, 'horizon', None)
  if value is not None:
    try:
      return int(value)
    except (TypeError, ValueError):
      pass
  env = getattr(session, 'current_env', None)
  value = getattr(env, 'horizon', None)
  if value is not None:
    try:
      return int(value)
    except (TypeError, ValueError):
      pass
  current_backend_index = getattr(session, 'current_backend_index', None)
  if current_backend_index == 0:
    return None
  value = getattr(session, 'policy_context_length', None)
  if value is not None:
    try:
      return int(value)
    except (TypeError, ValueError):
      pass
  return None


def _set_session_horizon(session: PlaySession, horizon: int) -> bool:
  horizon = max(1, int(horizon))
  current = _session_horizon(session)
  if current is None:
    return False
  if horizon == current:
    return False
  setter = getattr(session, 'set_horizon', None)
  if callable(setter):
    setter(horizon)
    return True
  adjust = getattr(session, 'adjust_horizon', None)
  if callable(adjust):
    adjust(horizon - current)
    return True
  return False


def _process_record_event(
    etype: str,
    args,
    session: PlaySession,
    shared: WebSharedState,
) -> bool:
  if shared.recorder is None:
    return False
  if etype not in {'toggle_recording', 'export_now', 'delete_recording', 'export_snapshot'}:
    return False
  _, state = _render_state(args, session, shared)
  ram_capable = _ram_capable(args, session)
  frame = _record_frame(args, session, ram_capable)
  ram = _record_ram(session, state, ram_capable)
  metadata = _record_metadata(session, state)
  if etype == 'toggle_recording':
    shared.recorder.toggle(frame, ram, metadata)
  elif etype == 'export_now':
    shared.recorder.export('manual_export')
  elif etype == 'delete_recording':
    shared.recorder.discard()
  elif etype == 'export_snapshot':
    shared.recorder.export_snapshot(state, ram, metadata, 'manual_snapshot')
  return True


def _process_event(
    event: dict[str, Any], args, session: PlaySession, shared: WebSharedState
) -> tuple[bool, bool, bool]:
  etype = event.get('type')
  if etype == 'keydown':
    key = int(event['key'])
    mod = int(event.get('mod', 0))
    if key in ACTION_KEYS:
      shared.set_key(key, True)
      return False, False, False
    if key == pygame.K_RETURN:
      return True, False, False
    if key == pygame.K_PERIOD:
      with shared.lock:
        shared.paused = not shared.paused
        paused = shared.paused
      _set_session_paused(session, paused)
      return False, False, True
    if key == pygame.K_e:
      return False, True, False
    if key == pygame.K_o:
      _process_record_event('toggle_recording', args, session, shared)
      return False, False, True
    if key == pygame.K_m:
      session.switch_controller()
      return False, False, True
    if key == pygame.K_RIGHT:
      if mod & pygame.KMOD_SHIFT:
        switch_policy = getattr(session, 'switch_policy', None)
        if callable(switch_policy):
          switch_policy(+1)
        return False, False, True
      session.switch_backend(+1)
      return False, False, True
    if key == pygame.K_LEFT:
      if mod & pygame.KMOD_SHIFT:
        switch_policy = getattr(session, 'switch_policy', None)
        if callable(switch_policy):
          switch_policy(-1)
        return False, False, True
      session.switch_backend(-1)
      return False, False, True
    if key == pygame.K_UP:
      current_horizon = _session_horizon(session)
      if current_horizon is not None:
        if _set_session_horizon(session, current_horizon + 1):
          session.reset()
      return False, False, True
    if key == pygame.K_DOWN:
      current_horizon = _session_horizon(session)
      if current_horizon is not None:
        if _set_session_horizon(session, current_horizon - 1):
          session.reset()
      return False, False, True
    if key in {pygame.K_MINUS, pygame.K_KP_MINUS}:
      with shared.lock:
        shared.target_fps = max(1, int(shared.target_fps) - 1)
      return False, False, True
    if key in {pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS}:
      with shared.lock:
        shared.target_fps = min(120, int(shared.target_fps) + 1)
      return False, False, True
    fn = getattr(session, 'on_keydown', None)
    if callable(fn):
      fn(key, mod)
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

  if etype == 'set_horizon':
    try:
      if _set_session_horizon(session, int(event.get('horizon', 1))):
        session.reset()
    except (TypeError, ValueError):
      pass
    return False, False, True

  if etype == 'set_paused':
    with shared.lock:
      shared.paused = bool(event.get('paused', False))
      paused = shared.paused
    _set_session_paused(session, paused)
    return False, False, True

  if etype == 'switch_backend':
    session.switch_backend(int(event.get('direction', 1)))
    return False, False, True

  if etype == 'switch_policy':
    switch_policy = getattr(session, 'switch_policy', None)
    if callable(switch_policy):
      switch_policy(int(event.get('direction', 1)))
    return False, False, True

  if _process_record_event(etype, args, session, shared):
    return False, False, True

  ram_events = {
      'quick_start': 'quick_start',
      'select_dim': '_set_selected_dim',
      'apply_once': '_apply_selected_once',
      'apply_dim_value': '_apply_dim_value_from_web',
      'persist_selected': '_persist_selected',
      'persist_dim_value': '_persist_dim_value_from_web',
      'clear_persistent': '_clear_all_persistent',
      'clear_preview': '_clear_preview_from_web',
      'adjust_preview': '_adjust_preview',
  }
  if etype in ram_events:
    if etype not in {'toggle_recording', 'export_now', 'delete_recording', 'export_snapshot'}:
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
      elif etype == 'export_snapshot':
        fn('manual_snapshot')
      elif etype == 'adjust_preview':
        fn(int(event.get('delta', 0)))
      elif etype == 'delete_recording':
        fn()
      else:
        fn()
    return False, False, True

  if etype == 'set_preview_value':
    if not _ram_edit_allowed(session, shared):
      return False, False, True
    fn = getattr(session, '_set_preview_from_web', None)
    if callable(fn):
      fn(int(event.get('value', 0)))
    else:
      if hasattr(session, '_preview_raw_value'):
        session._preview_raw_value = int(event.get('value', 0))
      if hasattr(session, '_value_entry'):
        session._value_entry = str(event.get('value', ''))
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
  with shared.lock:
    shared.paused = bool(getattr(session, 'start_paused', False))
  _set_session_paused(session, shared.paused)
  jpg, state = _render_state(args, session, shared)
  shared.set_frame(jpg, state)

  while shared.running:
    t0 = time.perf_counter()
    do_reset = False
    step_once = False
    needs_render = False
    for event in shared.dequeue_events():
      reset_now, step_now, render_now = _process_event(event, args, session, shared)
      do_reset = do_reset or reset_now
      step_once = step_once or step_now
      needs_render = needs_render or render_now

    if do_reset:
      session.reset()
      needs_render = True

    with shared.lock:
      paused = shared.paused
      fps = max(1, int(shared.target_fps))
      clients = int(shared.clients)

    if paused and not step_once:
      if needs_render:
        jpg, state = _render_state(args, session, shared)
        shared.set_frame(jpg, state)
      time.sleep(0.01)
      continue

    if clients <= 0 and not step_once and not (
        shared.recorder is not None and shared.recorder.active):
      if needs_render:
        jpg, state = _render_state(args, session, shared)
        shared.set_frame(jpg, state)
      time.sleep(0.05)
      continue

    human_action = resolve_action(shared.get_pressed_keys(), keymap_ordered)
    action = session.choose_action(human_action)
    result = session.step(action)
    if shared.recorder is not None and shared.recorder.active:
      ram_capable = _ram_capable(args, session)
      _, state = _render_state(args, session, shared, action, result.info)
      shared.recorder.record_step(
          _action_to_int(action),
          result.reward,
          result.done,
          result.trunc,
          _record_frame(args, session, ram_capable),
          _record_ram(session, state, ram_capable))
      if result.done or result.trunc:
        shared.recorder.stop()
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


@app.route('/event', methods=['POST'])
def post_event():
  if _shared is not None:
    _shared.enqueue_event(request.get_json(silent=True) or {})
  return jsonify({'ok': True})


@socketio.on('connect')
def handle_connect():
  if _shared is not None:
    _shared.clients += 1
    if _session is not None:
      socketio.emit('config', {
          'env_id': getattr(_session, 'env_id', ''),
          'focus_dims': list(getattr(_session, 'focus_dims', [])),
          'signed_dims': list(getattr(_session, 'signed_dims', [])),
          'action_names': list(getattr(_session, 'action_names', [])),
      })
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
  _shared = WebSharedState(
      target_fps=max(1, int(args.fps)),
      recorder=PlayRecorder(
          getattr(args, 'export_dir', 'debug_outputs/wm_play_exports'),
          video_fps=max(1, int(args.fps))))

  game_thread = threading.Thread(
      target=run_web_game_loop, args=(args, session, _shared), daemon=True)
  game_thread.start()
  pub_thread = threading.Thread(target=frame_publisher, daemon=True)
  pub_thread.start()

  host = getattr(args, 'web_host', None) or getattr(args, 'host', '127.0.0.1')
  port = int(getattr(args, 'web_port', None) or getattr(args, 'port', 9876))
  logging.getLogger('werkzeug').setLevel(logging.ERROR)
  try:
    from flask import cli as flask_cli
    flask_cli.show_server_banner = lambda *args, **kwargs: None
  except Exception:
    pass
  print(f'Web play server running at http://{host}:{port}', flush=True)
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

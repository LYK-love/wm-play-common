from __future__ import annotations

import argparse
import importlib
import os
from typing import Any

import numpy as np
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
import pygame
from PIL import Image

from .api import RenderableGameEnv, StepResult
from .cli import add_remote_server_args, validate_remote_server_args
from .server_summary import print_remote_server_summary
from .session import EnvPlaySession, EnvSlot, obs_to_image
from .web_server import run_web_server


def _gym_candidates(backend: str):
  candidates = []
  if backend in {'auto', 'gymnasium'}:
    try:
      import gymnasium as gym

      candidates.append((gym, 'gymnasium'))
    except ImportError:
      if backend == 'gymnasium':
        raise SystemExit('gymnasium is not installed; install gymnasium or use --gym-backend gym')
  if backend in {'auto', 'gym'}:
    try:
      import gym

      candidates.append((gym, 'gym'))
    except ImportError:
      if backend == 'gym':
        raise SystemExit('gym is not installed; install gym or use --gym-backend gymnasium')
  if not candidates:
    raise SystemExit('Install gymnasium or gym to use standalone wm-play real-env mode.')
  return candidates


def _make_gym_env(gym, env_name: str, render_mode: str):
  if str(env_name).startswith('ALE/'):
    try:
      import ale_py

      register = getattr(gym, 'register_envs', None)
      if callable(register):
        register(ale_py)
    except ImportError:
      pass
  if render_mode:
    try:
      return gym.make(env_name, render_mode=render_mode)
    except TypeError:
      pass
  return gym.make(env_name)


def _reset_env(env, seed: int | None):
  try:
    out = env.reset(seed=seed) if seed is not None else env.reset()
  except TypeError:
    out = env.reset()
  if isinstance(out, tuple) and len(out) == 2:
    return out
  return out, {}


def _step_env(env, action: int):
  out = env.step(action)
  if isinstance(out, tuple) and len(out) == 5:
    obs, reward, done, trunc, info = out
    return obs, reward, done, trunc, info
  if isinstance(out, tuple) and len(out) == 4:
    obs, reward, done, info = out
    return obs, reward, done, False, info
  raise RuntimeError('Gym env step() must return 4 or 5 values.')


def _action_meanings(env, action_count: int) -> list[str]:
  for obj in (getattr(env, 'unwrapped', None), env):
    fn = getattr(obj, 'get_action_meanings', None)
    if callable(fn):
      try:
        names = [str(name).lower() for name in fn()]
        if len(names) == action_count:
          return names
      except Exception:
        pass
  return [str(i) for i in range(action_count)]


def _render_obs_or_env(env, obs: Any) -> Image.Image:
  arr = np.asarray(obs)
  if arr.ndim >= 2:
    return obs_to_image(obs)
  try:
    rendered = env.render()
    if rendered is not None:
      return obs_to_image(rendered)
  except TypeError:
    try:
      rendered = env.render(mode='rgb_array')
      if rendered is not None:
        return obs_to_image(rendered)
    except Exception:
      pass
  except Exception:
    pass
  return obs_to_image(obs)


def _build_keymap(action_names: list[str], action_count: int) -> dict[tuple[int, ...], int]:
  keymap: dict[tuple[int, ...], int] = {}
  token_keys = (
      ('UP', pygame.K_w),
      ('DOWN', pygame.K_s),
      ('LEFT', pygame.K_a),
      ('RIGHT', pygame.K_d),
      ('FIRE', pygame.K_SPACE),
  )
  for idx, name in enumerate(action_names):
    norm = ''.join(ch for ch in str(name).upper() if ch.isalnum())
    keys = tuple(sorted({key for token, key in token_keys if token in norm}))
    if keys:
      keymap[keys] = idx

  fallbacks = (
      ((pygame.K_SPACE,), 1),
      ((pygame.K_d,), 2),
      ((pygame.K_a,), 3),
      ((pygame.K_w,), 4),
      ((pygame.K_s,), 5),
  )
  for keys, idx in fallbacks:
    if idx < action_count:
      keymap.setdefault(keys, idx)
  return keymap


SIMPLE_ALE_FOCUS_FIELDS = {
    'breakout': (
        'flags', 'lives', 'last_action', 'paddle_x', 'ball_x_q8',
        'ball_y_q8', 'ball_vx_q8', 'ball_vy_q8', 'score',
        'episode_frame_number', 'rng_state', 'seed',
    ),
    'boxing': (
        'flags', 'last_action', 'opponent_last_action', 'player_x',
        'player_y', 'opponent_x', 'opponent_y', 'player_score',
        'opponent_score', 'player_cooldown', 'opponent_cooldown',
        'episode_frame_number', 'rng_state', 'seed',
    ),
}


def _ram_owner(env):
  return getattr(env, 'unwrapped', env)


def _ale_interface(env):
  return getattr(_ram_owner(env), 'ale', None)


def _read_env_ram(env) -> np.ndarray | None:
  owner = _ram_owner(env)
  reader = getattr(owner, 'get_ram', None)
  if callable(reader):
    try:
      ram = np.asarray(reader(), dtype=np.uint8)
      return ram.copy() if ram.ndim == 1 else None
    except Exception:
      return None
  ale = _ale_interface(env)
  reader = getattr(ale, 'getRAM', None)
  if callable(reader):
    try:
      ram = np.asarray(reader(), dtype=np.uint8)
      return ram.copy() if ram.ndim == 1 else None
    except Exception:
      return None
  return None


def _read_env_rgb(env, fallback: Any = None) -> np.ndarray:
  ale = _ale_interface(env)
  reader = getattr(ale, 'getScreenRGB', None)
  if callable(reader):
    try:
      frame = reader()
      if frame is None:
        frame = np.empty((210, 160, 3), dtype=np.uint8)
        reader(frame)
      return np.asarray(frame, dtype=np.uint8)
    except Exception:
      pass
  return np.asarray(_render_obs_or_env(env, fallback).convert('RGB'), dtype=np.uint8)


def _schema_fields(env) -> list[dict[str, Any]]:
  owner = _ram_owner(env)
  state_reader = getattr(owner, 'get_state', None)
  if not callable(state_reader):
    return []
  try:
    state = state_reader()
    module = importlib.import_module(type(state).__module__)
    describe = getattr(module, 'describe_ram', None)
    if not callable(describe):
      return []
    return [
        {
            'name': str(field.name),
            'offset': int(field.offset),
            'size': int(field.size),
            'encoding': str(field.encoding),
            'description': str(field.description),
            'mutable': bool(field.mutable),
        }
        for field in describe()
    ]
  except Exception:
    return []


def _simple_ale_game(ram: np.ndarray | None, fields: list[dict[str, Any]]) -> str | None:
  if ram is None or ram.size < 4 or not fields:
    return None
  magic = bytes(ram[:4])
  if magic == b'MBRK':
    return 'breakout'
  if magic == b'MBOX':
    return 'boxing'
  return None


def _decode_field(ram: np.ndarray, field: dict[str, Any]) -> str:
  offset = int(field['offset'])
  size = int(field['size'])
  raw = bytes(ram[offset:offset + size])
  encoding = str(field.get('encoding', '')).lower()
  if encoding == 'ascii':
    return raw.decode('ascii', errors='replace')
  if encoding.startswith('int'):
    return str(int.from_bytes(raw, 'little', signed=True))
  if encoding.startswith('uint') or encoding in {'direction', 'bitfield'}:
    return str(int.from_bytes(raw, 'little', signed=False))
  if 'bitset' in encoding:
    return f'0x{int.from_bytes(raw, "little"):x}'
  if encoding == 'zero':
    return '0'
  return str(int.from_bytes(raw, 'little')) if raw else ''


class GymRAMController:
  """Generic editable RAM bridge with optional complete-state semantics."""

  def __init__(self, env, env_name: str) -> None:
    self.env = env
    self.env_name = str(env_name)
    self.fields = _schema_fields(env)
    ram = _read_env_ram(env)
    self.game = _simple_ale_game(ram, self.fields)
    self.available = ram is not None
    self.complete_state = self.game is not None
    self.selected_dim = 0
    self.persistent: dict[int, int] = {}
    self.last_error = ''
    self._byte_specs = self._build_byte_specs(0 if ram is None else len(ram))
    focus = self._focus_offsets()
    if focus:
      self.selected_dim = focus[0]

  @property
  def schema_name(self) -> str:
    if self.game == 'breakout':
      return 'SimpleALE Breakout complete-state RAM (MBRK v1)'
    if self.game == 'boxing':
      return 'SimpleALE Boxing complete-state RAM (MBOX v1)'
    return 'ALE hardware RAM'

  @property
  def semantics(self) -> str:
    if self.complete_state:
      return ('All evolving game state, including RNG and action history, is '
              'encoded here; this is not the original Atari RAM layout.')
    return ('Raw environment RAM bytes; for real ALE this is an observation, '
            'not the complete emulator state.')

  def _build_byte_specs(self, count: int) -> list[dict[str, Any]]:
    specs = [
        {
            'name': f'ram_{dim}', 'field_name': f'ram_{dim}', 'field_offset': dim,
            'field_size': 1, 'encoding': 'uint8', 'description': '',
            'editable': True,
        }
        for dim in range(count)
    ]
    for field in self.fields:
      offset, size = int(field['offset']), int(field['size'])
      for byte_index in range(size):
        dim = offset + byte_index
        if not 0 <= dim < count:
          continue
        name = field['name'] if size == 1 else f"{field['name']}[{byte_index}]"
        specs[dim] = {
            'name': name,
            'field_name': field['name'],
            'field_offset': offset,
            'field_size': size,
            'encoding': field['encoding'],
            'description': field['description'],
            'editable': bool(field['mutable']),
        }
    return specs

  def _focus_offsets(self) -> list[int]:
    names = SIMPLE_ALE_FOCUS_FIELDS.get(self.game or '', ())
    by_name = {str(field['name']): int(field['offset']) for field in self.fields}
    offsets = [by_name[name] for name in names if name in by_name]
    if offsets:
      return offsets
    return list(range(min(16, len(self._byte_specs))))

  def read(self) -> np.ndarray | None:
    return _read_env_ram(self.env)

  def read_rgb(self, fallback: Any = None) -> np.ndarray:
    return _read_env_rgb(self.env, fallback)

  def _field_for_dim(self, dim: int) -> dict[str, Any] | None:
    if not 0 <= int(dim) < len(self._byte_specs):
      return None
    spec = self._byte_specs[int(dim)]
    offset = int(spec['field_offset'])
    return next((field for field in self.fields if int(field['offset']) == offset), None)

  def item(self, ram: np.ndarray, dim: int, *, focus: bool = False) -> dict[str, Any]:
    dim = int(dim)
    spec = self._byte_specs[dim]
    field = self._field_for_dim(dim)
    formatted = str(int(ram[dim]))
    if focus and field is not None:
      formatted = _decode_field(ram, field)
    return {
        'dim': dim,
        'name': spec['field_name'] if focus else spec['name'],
        'value': int(ram[dim]),
        'formatted': formatted,
        'field_value': _decode_field(ram, field) if field is not None else formatted,
        'encoding': spec['encoding'],
        'description': spec['description'],
        'editable': bool(spec['editable']),
        'selected': dim == self.selected_dim,
        'persistent': dim in self.persistent,
    }

  def write(self, dim: int, value: int) -> bool:
    dim, value = int(dim), int(value) % 256
    if not self.available or not 0 <= dim < len(self._byte_specs):
      self.last_error = f'RAM index {dim} is unavailable.'
      return False
    if not self._byte_specs[dim]['editable']:
      self.last_error = f"{self._byte_specs[dim]['field_name']} is read-only."
      return False
    owner = _ram_owner(self.env)
    try:
      atomic_writer = getattr(owner, 'set_ram', None)
      if callable(atomic_writer):
        ram = self.read()
        if ram is None:
          raise RuntimeError('RAM read failed before write')
        ram[dim] = value
        atomic_writer(ram)
      else:
        ale = _ale_interface(self.env)
        writer = getattr(ale, 'setRAM', None)
        if not callable(writer):
          raise RuntimeError('environment exposes no RAM writer')
        writer(dim, value)
      self.last_error = ''
      return True
    except Exception as exc:
      self.last_error = str(exc)
      return False

  def persist(self, dim: int, value: int) -> None:
    if self.write(dim, value):
      self.persistent[int(dim)] = int(value) % 256

  def apply_persistent(self) -> bool:
    changed = False
    for dim, value in tuple(self.persistent.items()):
      if self.write(dim, value):
        changed = True
      else:
        self.persistent.pop(dim, None)
    return changed

  def web_state(self, *, step: int, reward: float, episode_return: float,
                last_action: int, action_names: list[str]) -> dict[str, Any]:
    ram = self.read()
    if ram is None:
      return {'ram': [], 'focus_dims': [], 'all_dims': [], 'ram_error': self.last_error}
    focus_dims = [self.item(ram, dim, focus=True) for dim in self._focus_offsets()]
    all_dims = [self.item(ram, dim) for dim in range(len(ram))]
    selected = all_dims[self.selected_dim]
    action_name = (
        action_names[last_action] if 0 <= last_action < len(action_names)
        else str(last_action)
    )
    return {
        'ram': ram.tolist(),
        'ram_slot_count': int(len(ram)),
        'ram_schema_name': self.schema_name,
        'ram_semantics': self.semantics,
        'ram_game': self.game or 'real_ale',
        'ram_is_complete_state': self.complete_state,
        'ram_error': self.last_error,
        'selected_dim': self.selected_dim,
        'selected_name': selected['name'],
        'selected_editable': selected['editable'],
        'preview_value': int(ram[self.selected_dim]),
        'persistent_pool': {
            str(dim): {'value': value, 'name': self._byte_specs[dim]['name']}
            for dim, value in sorted(self.persistent.items())
        },
        'persistent_count': len(self.persistent),
        'focus_dims': focus_dims,
        'all_dims': all_dims,
        'step': int(step),
        'reward': float(reward),
        'return': float(episode_return),
        'last_action': int(last_action),
        'last_action_name': action_name,
        'env_id': self.env_name,
        'can_quick_start': False,
    }


class GymGameEnv(RenderableGameEnv):
  name: str

  def __init__(self, env_name: str, *, gym_backend: str = 'auto',
               render_mode: str = 'rgb_array', seed: int | None = None) -> None:
    last_error: Exception | None = None
    for gym, backend_name in _gym_candidates(gym_backend):
      try:
        self.env = _make_gym_env(gym, env_name, render_mode)
        self.backend_name = backend_name
        break
      except Exception as exc:
        last_error = exc
        if gym_backend != 'auto':
          raise
    else:
      raise SystemExit(f'Could not create env {env_name!r}: {last_error}')
    self.name = env_name
    self.pending_seed = seed
    self.step_count = 0
    self.episode_return = 0.0
    self.current_obs = None
    self.last_reward = 0.0
    self.last_action = 0

    action_space = getattr(self.env, 'action_space', None)
    action_count = getattr(action_space, 'n', None)
    if action_count is None:
      raise SystemExit('Standalone wm-play currently supports discrete action spaces only.')
    self.action_count = int(action_count)
    self.action_names = _action_meanings(self.env, self.action_count)
    self.keymap = _build_keymap(self.action_names, self.action_count)
    self.ram = GymRAMController(self.env, env_name)

  @property
  def ram_available(self) -> bool:
    return self.ram.available

  @property
  def current_ram(self) -> np.ndarray | None:
    return self.ram.read()

  def reset(self) -> tuple[Any, dict[str, Any]]:
    obs, info = _reset_env(self.env, self.pending_seed)
    self.pending_seed = None
    self.step_count = 0
    self.episode_return = 0.0
    self.last_reward = 0.0
    self.last_action = 0
    if self.ram.apply_persistent():
      obs = self._observation_after_ram_write(obs)
    self.current_obs = obs
    info = dict(info or {})
    info.update({'step': self.step_count, 'return': self.episode_return})
    return obs, info

  def step(self, action: int) -> StepResult:
    obs, reward, done, trunc, info = _step_env(self.env, int(action))
    self.step_count += 1
    self.episode_return += float(reward)
    self.last_reward = float(reward)
    self.last_action = int(action)
    if self.ram.apply_persistent():
      obs = self._observation_after_ram_write(obs)
    self.current_obs = obs
    info = dict(info or {})
    info.update({
        'step': self.step_count,
        'reward': float(reward),
        'return': self.episode_return,
        'done': bool(done),
        'trunc': bool(trunc),
    })
    return StepResult(obs=obs, reward=float(reward), done=bool(done),
                      trunc=bool(trunc), info=info)

  def render_frame(self, obs: Any, size: int):
    return _render_obs_or_env(self.env, obs).resize((size, size), resample=Image.NEAREST)

  def _observation_after_ram_write(self, fallback: Any):
    array = np.asarray(fallback)
    ram = self.ram.read()
    if ram is not None and array.shape == ram.shape:
      return ram
    if array.ndim in {2, 3}:
      return self.ram.read_rgb(fallback)
    return fallback

  def _read_ram(self):
    return self.ram.read()

  def _read_rgb_frame(self):
    return self.ram.read_rgb(self.current_obs)

  def _set_selected_dim(self, dim: int) -> None:
    if 0 <= int(dim) < len(self.ram._byte_specs):
      self.ram.selected_dim = int(dim)

  def _apply_selected_once(self) -> None:
    ram = self.ram.read()
    if ram is not None:
      self.ram.write(self.ram.selected_dim, int(ram[self.ram.selected_dim]))

  def _apply_dim_value_from_web(self, dim: int, value: int) -> None:
    self.ram.write(dim, value)

  def _persist_dim_value_from_web(self, dim: int, value: int) -> None:
    self.ram.persist(dim, value)

  def _persist_selected(self) -> None:
    ram = self.ram.read()
    if ram is not None:
      self.ram.persist(self.ram.selected_dim, int(ram[self.ram.selected_dim]))

  def _clear_all_persistent(self) -> None:
    self.ram.persistent.clear()

  def _clear_preview_from_web(self) -> None:
    self.ram.last_error = ''

  def get_web_state(self) -> dict[str, Any]:
    return self.ram.web_state(
        step=self.step_count,
        reward=self.last_reward,
        episode_return=self.episode_return,
        last_action=self.last_action,
        action_names=self.action_names)

  def record_metadata(self) -> dict[str, Any]:
    return {
        'env_id': self.name,
        'ram_schema_name': self.ram.schema_name if self.ram_available else '',
        'ram_is_complete_state': self.ram.complete_state,
    }

  def close(self) -> None:
    self.env.close()


def build_arg_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
      description='Run the shared wm-play browser UI against a real Gym environment.')
  parser.add_argument('--env-name', default='PongNoFrameskip-v4',
                      help='Gym/Gymnasium environment id for standalone real-env play.')
  parser.add_argument('--gym-backend', choices=['auto', 'gymnasium', 'gym'], default='auto',
                      help='Environment package to use. auto tries gymnasium, then gym.')
  parser.add_argument('--render-mode', default='rgb_array',
                      help='Render mode passed to gym.make when supported.')
  parser.add_argument('--seed', type=int, default=None,
                      help='Optional seed for the first environment reset.')
  add_remote_server_args(parser)
  return parser


def main(argv: list[str] | None = None) -> None:
  parser = build_arg_parser()
  args = parser.parse_args(argv)
  validate_remote_server_args(args)

  env = GymGameEnv(
      args.env_name,
      gym_backend=args.gym_backend,
      render_mode=args.render_mode,
      seed=args.seed)
  session = EnvPlaySession(
      envs=[EnvSlot(name=args.env_name, env=env)],
      action_names=env.action_names,
      keymap=env.keymap)

  print_remote_server_summary(
      project='wm-play',
      controller='human',
      real_env=True,
      wm_checkpoints=(),
      policy_checkpoints=(),
      ram_panel=bool(args.ram and env.ram_available),
      extras=(('env', args.env_name), ('gym', env.backend_name)),
      fps=args.fps,
      stream_fps=args.fps,
      size=args.size,
      jpeg_quality=args.jpeg_quality,
      tcp_host=args.web_host,
      tcp_port=args.web_port,
      client_command=f'open http://{args.web_host}:{args.web_port}')
  run_web_server(args, session)


if __name__ == '__main__':
  main()

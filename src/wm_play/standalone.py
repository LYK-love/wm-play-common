from __future__ import annotations

import argparse
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

    action_space = getattr(self.env, 'action_space', None)
    action_count = getattr(action_space, 'n', None)
    if action_count is None:
      raise SystemExit('Standalone wm-play currently supports discrete action spaces only.')
    self.action_count = int(action_count)
    self.action_names = _action_meanings(self.env, self.action_count)
    self.keymap = _build_keymap(self.action_names, self.action_count)

  def reset(self) -> tuple[Any, dict[str, Any]]:
    obs, info = _reset_env(self.env, self.pending_seed)
    self.pending_seed = None
    self.step_count = 0
    self.episode_return = 0.0
    info = dict(info or {})
    info.update({'step': self.step_count, 'return': self.episode_return})
    return obs, info

  def step(self, action: int) -> StepResult:
    obs, reward, done, trunc, info = _step_env(self.env, int(action))
    self.step_count += 1
    self.episode_return += float(reward)
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
      ram_panel=False,
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

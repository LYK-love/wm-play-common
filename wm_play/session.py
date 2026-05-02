from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from PIL import Image

from .api import GameEnv, PlaySession, StepResult


def _fmt_scalar(value: Any) -> str:
  if value is None:
    return '-'
  try:
    value = float(value)
  except Exception:
    return str(value)
  if abs(value - round(value)) < 1e-6:
    return str(int(round(value)))
  return f'{value:.2f}'


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


def obs_to_image(obs: Any) -> Image.Image:
  if isinstance(obs, Image.Image):
    return obs.convert('RGB')
  arr = np.asarray(obs)
  while arr.ndim > 3:
    arr = arr[0]
  if arr.ndim == 2:
    arr = np.repeat(arr[..., None], 3, axis=-1)
  if arr.ndim != 3:
    arr = np.zeros((64, 64, 3), dtype=np.uint8)
  if arr.shape[0] in (1, 3, 4) and arr.shape[-1] not in (1, 3, 4):
    arr = np.moveaxis(arr, 0, -1)
  if arr.shape[-1] == 1:
    arr = np.repeat(arr, 3, axis=-1)
  if arr.shape[-1] > 3:
    arr = arr[..., :3]
  if arr.dtype != np.uint8:
    if arr.size and np.nanmax(arr) <= 1.5:
      arr = arr * 255.0
    arr = np.clip(arr, 0, 255).astype(np.uint8)
  return Image.fromarray(arr).convert('RGB')


@dataclass
class EnvSlot:
  name: str
  env: GameEnv


class EnvPlaySession(PlaySession):
  """Generic play session for envs and WMs that already expose step(action)."""

  def __init__(
      self,
      envs: list[EnvSlot],
      action_names: list[str],
      keymap: dict[tuple[int, ...], int],
      render_fn: Callable[[Any, int], Image.Image] | None = None,
  ) -> None:
    if not envs:
      raise ValueError('EnvPlaySession requires at least one env.')
    self.envs = list(envs)
    self.action_names = list(action_names)
    self.keymap = dict(keymap)
    self.render_fn = render_fn
    self.current_index = 0
    self.current_obs = None
    self.last_info: dict[str, Any] = {}

  @property
  def current_env(self) -> GameEnv:
    return self.envs[self.current_index].env

  @property
  def current_name(self) -> str:
    return self.envs[self.current_index].name

  def reset(self) -> None:
    self.current_obs, self.last_info = self.current_env.reset()

  def switch_backend(self, direction: int) -> None:
    if len(self.envs) <= 1:
      return
    self.current_index = (self.current_index + direction) % len(self.envs)
    self.reset()

  def switch_controller(self) -> None:
    return

  def adjust_horizon(self, delta: int) -> None:
    update = getattr(self.current_env, 'adjust_horizon', None)
    if callable(update):
      update(delta)

  def choose_action(self, human_action: int) -> int:
    policy = getattr(self.current_env, 'choose_action', None)
    if callable(policy):
      return policy(human_action)
    return human_action

  def step(self, action: int) -> StepResult:
    result = self.current_env.step(action)
    self.current_obs = result.obs
    self.last_info = result.info or {}
    self.last_info.setdefault('backend', self.current_name)
    return result

  def header(self, action: int, info: dict[str, Any]) -> list[str]:
    info = info if isinstance(info, dict) else {}
    reward = info.get('reward')
    ret = info.get('return')
    step = info.get('step', info.get('steps', 0))
    action_name = info.get('action_name')
    action_idx = _action_to_int(action)
    if action_name is None:
      action_name = self.action_names[action_idx] if 0 <= action_idx < len(self.action_names) else str(action_idx)
    lines = [
        f'Env    : {self.current_index + 1}/{len(self.envs)} ({self.current_name})',
        f'Step   : {step}',
        f'Reward : {_fmt_scalar(reward)}',
        f'Return : {_fmt_scalar(ret)}',
        f'Action : {action_name}',
    ]
    return lines

  def render_frame(self, size: int, header_lines: list[str]):
    render = getattr(self.current_env, 'render_frame', None)
    if callable(render):
      return render(self.current_obs, size)
    if self.render_fn is not None:
      return self.render_fn(self.current_obs, size)
    return obs_to_image(self.current_obs).resize((size, size), resample=Image.NEAREST)

  def close(self) -> None:
    for slot in self.envs:
      slot.env.close()

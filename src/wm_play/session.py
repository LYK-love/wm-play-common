from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from PIL import Image

from .api import GameEnv, PixelPolicy, PlaySession, StepResult
from .server_summary import print_runtime_event
from .status import play_status_lines


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
      policies: list[PixelPolicy] | None = None,
  ) -> None:
    if not envs:
      raise ValueError('EnvPlaySession requires at least one env.')
    self.envs = list(envs)
    self.action_names = list(action_names)
    self.keymap = dict(keymap)
    self.render_fn = render_fn
    self.policies = list(policies or [])
    self.controller_index = 0
    self.selected_policy_index = 0
    self.current_index = 0
    self.current_obs = None
    self.last_info: dict[str, Any] = {}

  @property
  def current_env(self) -> GameEnv:
    return self.envs[self.current_index].env

  @property
  def current_name(self) -> str:
    return self.envs[self.current_index].name

  @property
  def current_kind(self) -> str:
    return 'model' if self.horizon is not None else 'real'

  @property
  def horizon(self) -> int | None:
    value = getattr(self.current_env, 'horizon', None)
    if value is None:
      return None
    try:
      return int(value)
    except (TypeError, ValueError):
      return None

  def reset(self) -> None:
    self.current_obs, self.last_info = self.current_env.reset()
    for policy in self.policies:
      reset = getattr(policy, 'reset', None)
      if callable(reset):
        reset()

  def switch_backend(self, direction: int) -> None:
    if len(self.envs) <= 1:
      return
    self.current_index = (self.current_index + direction) % len(self.envs)
    self.reset()
    print_runtime_event(
        'backend',
        f'{self.current_name}[{self.current_index + 1}/{len(self.envs)}]')

  def switch_controller(self) -> None:
    if self.policies:
      if self.controller_index == 0 and self.selected_policy_index:
        self.controller_index = self.selected_policy_index + 1
      else:
        self.controller_index = (self.controller_index + 1) % (1 + len(self.policies))
      if self.controller_index > 0:
        self.selected_policy_index = self.controller_index - 1
    print_runtime_event('controller', self._control_label())

  def switch_policy(self, direction: int) -> None:
    if not self.policies:
      return
    self.selected_policy_index = (self.selected_policy_index + int(direction)) % len(self.policies)
    self.controller_index = self.selected_policy_index + 1
    reset = getattr(self.policies[self.selected_policy_index], 'reset', None)
    if callable(reset):
      reset()
    print_runtime_event(
        'policy',
        f'{self.selected_policy_index + 1}/{len(self.policies)} '
        f'({self.policies[self.selected_policy_index].name})')

  def adjust_horizon(self, delta: int) -> None:
    update = getattr(self.current_env, 'adjust_horizon', None)
    if callable(update):
      update(delta)

  def set_horizon(self, horizon: int) -> None:
    update = getattr(self.current_env, 'set_horizon', None)
    if callable(update):
      update(horizon)
      print_runtime_event('wm horizon', self.horizon)
      return
    current = getattr(self.current_env, 'horizon', None)
    if current is not None:
      try:
        setattr(self.current_env, 'horizon', max(1, int(horizon)))
        print_runtime_event('wm horizon', self.horizon)
        return
      except (AttributeError, TypeError, ValueError):
        pass
      try:
        self.adjust_horizon(int(horizon) - int(current))
      except (TypeError, ValueError):
        pass

  def choose_action(self, human_action: int) -> int:
    if self.controller_index > 0 and self.policies:
      result = self.policies[self.controller_index - 1].act(self.current_obs)
      return _action_to_int(result.action)
    policy = getattr(self.current_env, 'choose_action', None)
    if callable(policy):
      return policy(human_action)
    return human_action

  def _control_label(self) -> str:
    if self.controller_index > 0 and self.policies:
      return self.policies[self.controller_index - 1].name
    return 'human'

  def step(self, action: int) -> StepResult:
    result = self.current_env.step(action)
    self.current_obs = result.obs
    self.last_info = result.info or {}
    self.last_info.setdefault('backend', self.current_name)
    return result

  def header(self, action: int, info: dict[str, Any]) -> list[str]:
    info = info if isinstance(info, dict) else {}
    control = info.get('control')
    if control is None:
      control = self._control_label()
    action_name = info.get('action_name')
    action_idx = _action_to_int(action)
    if action_name is None:
      action_name = self.action_names[action_idx] if 0 <= action_idx < len(self.action_names) else str(action_idx)
    status = {
        'env_name': self.current_name,
        'env_kind': self.current_kind,
        'control': control,
        'step': info.get('step', info.get('steps', 0)),
        'reward': info.get('reward'),
        'return': info.get('return'),
        'action_name': action_name,
        'terminal': info.get('terminal', info.get('term', info.get('is_terminal'))),
        'continuation': info.get('continuation', info.get('cont_prob', info.get('cont'))),
        'done': info.get('done'),
        'trunc': info.get('trunc'),
    }
    return play_status_lines(status, info.get('status_extras'))

  def record_metadata(self) -> dict[str, Any]:
    return {
        'backend': self.current_name,
        'backend_index': int(self.current_index),
        'backend_count': int(len(self.envs)),
        'controller': self._control_label(),
        'policy_index': int(self.selected_policy_index),
        'policy_count': int(len(self.policies)),
        'policy_label': (
            self.policies[self.selected_policy_index].name
            if self.policies else ''),
    }

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

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .api import PlaySession
from .recording import PlayRecorder


ActionFn = Callable[[int, PlaySession], int]


@dataclass
class HeadlessRollout:
  """In-memory result from running a play backend without the web frontend."""

  frames: np.ndarray
  actions: np.ndarray
  rewards: np.ndarray
  done: np.ndarray
  trunc: np.ndarray
  infos: list[dict[str, Any]]
  metadata: dict[str, Any]
  exported_paths: list[str]


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


def _frame(session: PlaySession, size: int) -> np.ndarray:
  image = session.render_frame(int(size), [])
  return np.asarray(image.convert('RGB'), dtype=np.uint8)


def _ram(session: PlaySession):
  ram = getattr(session, 'current_ram', None)
  if ram is not None:
    return np.asarray(ram, dtype=np.uint8)
  reader = getattr(session, '_read_ram', None)
  if callable(reader):
    value = reader()
    if value is not None:
      return np.asarray(value, dtype=np.uint8)
  return None


def _metadata(session: PlaySession, extra: dict[str, Any] | None = None):
  fn = getattr(session, 'record_metadata', None)
  metadata = fn() if callable(fn) else {}
  out = {
      'env_id': getattr(session, 'env_id', ''),
      'action_names': list(getattr(session, 'action_names', [])),
      'horizon': getattr(session, 'horizon', None),
      **(metadata or {}),
      **(extra or {}),
  }
  return out


def run_episode(
    session: PlaySession,
    *,
    max_steps: int,
    action_fn: ActionFn | None = None,
    human_action: int = 0,
    reset: bool = True,
    stop_on_done: bool = True,
    size: int = 256,
    export_dir: str | Path | None = None,
    fps: int = 15,
    export_reason: str = 'headless_rollout',
    metadata: dict[str, Any] | None = None,
) -> HeadlessRollout:
  """Run a ``PlaySession`` without starting the web frontend.

  This is the notebook/evaluation counterpart to ``wm_play.web_server``. It
  drives the same backend/session API as the browser loop: choose an action,
  call ``session.step(action)``, render a frame, and optionally export the
  trajectory with ``PlayRecorder``.
  """

  if int(max_steps) <= 0:
    raise ValueError('max_steps must be positive.')
  if reset:
    session.reset()

  meta = _metadata(session, metadata)
  frames = [_frame(session, size)]
  actions = []
  rewards = []
  done = []
  trunc = []
  infos: list[dict[str, Any]] = []

  recorder = None
  if export_dir is not None:
    recorder = PlayRecorder(export_dir, video_fps=fps)
    recorder.start(frames[0], _ram(session), meta)

  for step in range(int(max_steps)):
    base_action = action_fn(step, session) if action_fn is not None else human_action
    action = session.choose_action(int(base_action))
    result = session.step(action)
    action_int = _action_to_int(action)
    next_frame = _frame(session, size)
    next_ram = _ram(session)

    actions.append(action_int)
    rewards.append(float(result.reward))
    done.append(bool(result.done))
    trunc.append(bool(result.trunc))
    infos.append(dict(result.info or {}))
    frames.append(next_frame)

    if recorder is not None:
      recorder.record_step(
          action_int,
          float(result.reward),
          bool(result.done),
          bool(result.trunc),
          next_frame,
          next_ram)

    if stop_on_done and (bool(result.done) or bool(result.trunc)):
      break

  exported_paths: list[str] = []
  if recorder is not None:
    recorder.stop()
    recorder.export(export_reason)
    exported_paths = list(recorder.last_exported_paths)

  return HeadlessRollout(
      frames=np.asarray(frames, dtype=np.uint8),
      actions=np.asarray(actions, dtype=np.int64),
      rewards=np.asarray(rewards, dtype=np.float32),
      done=np.asarray(done, dtype=bool),
      trunc=np.asarray(trunc, dtype=bool),
      infos=infos,
      metadata=meta,
      exported_paths=exported_paths)

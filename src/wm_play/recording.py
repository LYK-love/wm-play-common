from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np


def _jsonable(value: Any) -> Any:
  if isinstance(value, np.ndarray):
    return value.tolist()
  if isinstance(value, np.generic):
    return value.item()
  if isinstance(value, dict):
    return {str(k): _jsonable(v) for k, v in value.items()}
  if isinstance(value, (list, tuple)):
    return [_jsonable(v) for v in value]
  return value


def _save_video(path: Path, frames: np.ndarray, fps: int) -> str | None:
  if frames.ndim != 4 or frames.shape[0] == 0:
    return None
  try:
    import imageio.v2 as imageio
  except ImportError:
    return 'imageio is not installed; install imageio and imageio-ffmpeg to enable mp4 export'
  attempts = [
      {
          'fps': max(1, int(fps)),
          'codec': 'libx264',
          'quality': 9,
          'pixelformat': 'yuv420p',
          'macro_block_size': None,
      },
      {'fps': max(1, int(fps)), 'codec': 'libx264'},
  ]
  errors = []
  for kwargs in attempts:
    try:
      imageio.mimsave(str(path), frames, **kwargs)
      return None
    except Exception as exc:  # pragma: no cover - depends on system ffmpeg.
      errors.append(f'{type(exc).__name__}: {exc}')
  return (
      f'{errors[-1] if errors else "unknown error"}. Install imageio-ffmpeg '
      'or system ffmpeg with libx264 support to enable mp4 export'
  )


class PlayRecorder:
  """Generic web-play recorder.

  It records frame/action/reward/done/trunc for every play session. If the
  server is in RAM mode and the adapter exposes RAM, it also records RAM after
  each transition and includes RAM snapshots in manual snapshot exports.
  """

  def __init__(self, export_dir: str | Path, video_fps: int = 15):
    self.export_dir = Path(export_dir).expanduser()
    self.export_dir.mkdir(parents=True, exist_ok=True)
    self.video_fps = max(1, int(video_fps))
    self.active = False
    self.buffer: dict[str, Any] | None = None
    self.episode_idx = 0
    self.last_exported_path: str | None = None
    self.last_exported_paths: list[str] = []
    self.last_export_error: str | None = None

  def status(self) -> dict[str, Any]:
    return {
        'recording': bool(self.active),
        'recording_pending': self.buffer is not None and not self.active,
        'record_frame_count': len(self.buffer['frames']) if self.buffer else 0,
        'record_action_count': len(self.buffer['actions']) if self.buffer else 0,
        'last_exported_path': self.last_exported_path,
        'last_exported_paths': list(self.last_exported_paths),
        'last_export_error': self.last_export_error,
    }

  def start(self, frame: np.ndarray, ram: np.ndarray | None, metadata: dict[str, Any]) -> None:
    if self.buffer is not None:
      return
    self.active = True
    self.buffer = {
        'frames': [np.asarray(frame, dtype=np.uint8).copy()],
        'ram': [] if ram is None else [np.asarray(ram, dtype=np.uint8).copy()],
        'actions': [],
        'rewards': [],
        'done': [],
        'trunc': [],
        'metadata': _jsonable(metadata),
    }
    self.last_exported_path = None
    self.last_exported_paths = []
    self.last_export_error = None

  def stop(self) -> None:
    self.active = False

  def toggle(
      self, frame: np.ndarray, ram: np.ndarray | None, metadata: dict[str, Any]
  ) -> None:
    if self.active:
      self.stop()
    else:
      self.start(frame, ram, metadata)

  def discard(self) -> None:
    if self.active:
      return
    self.buffer = None
    self.last_exported_path = 'Recording deleted'
    self.last_exported_paths = []
    self.last_export_error = None

  def record_step(
      self,
      action: int,
      reward: float,
      done: bool,
      trunc: bool,
      frame: np.ndarray,
      ram: np.ndarray | None,
  ) -> None:
    if not self.active or self.buffer is None:
      return
    self.buffer['actions'].append(int(action))
    self.buffer['rewards'].append(float(reward))
    self.buffer['done'].append(bool(done))
    self.buffer['trunc'].append(bool(trunc))
    self.buffer['frames'].append(np.asarray(frame, dtype=np.uint8).copy())
    if ram is not None:
      self.buffer['ram'].append(np.asarray(ram, dtype=np.uint8).copy())

  def export(self, reason: str = 'manual_export') -> None:
    if self.active or self.buffer is None:
      return
    frames_np = np.asarray(self.buffer['frames'], dtype=np.uint8)
    if frames_np.shape[0] == 0:
      self.buffer = None
      return
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    stem = f'play_episode_{self.episode_idx:04d}_{reason}_{stamp}'
    npz_path = self.export_dir / f'{stem}.npz'
    mp4_path = self.export_dir / f'{stem}.mp4'
    json_path = self.export_dir / f'{stem}.json'

    payload = {
        'frames': frames_np,
        'actions': np.asarray(self.buffer['actions'], dtype=np.int64),
        'rewards': np.asarray(self.buffer['rewards'], dtype=np.float32),
        'done': np.asarray(self.buffer['done'], dtype=bool),
        'trunc': np.asarray(self.buffer['trunc'], dtype=bool),
    }
    if self.buffer['ram']:
      payload['ram'] = np.asarray(self.buffer['ram'], dtype=np.uint8)
    np.savez_compressed(npz_path, **payload)

    video_error = _save_video(mp4_path, frames_np, self.video_fps)
    meta = dict(self.buffer['metadata'])
    meta.update({
        'reason': reason,
        'num_frames': int(len(frames_np)),
        'num_actions': int(len(payload['actions'])),
        'has_ram': bool(self.buffer['ram']),
        'npz': str(npz_path),
        'mp4': None if video_error else str(mp4_path),
        'video_error': video_error,
    })
    json_path.write_text(json.dumps(_jsonable(meta), indent=2))

    self.last_exported_path = str(json_path)
    self.last_exported_paths = [str(npz_path), str(json_path)]
    self.last_export_error = None if not video_error else f'mp4 skipped: {video_error}'
    if not video_error:
      self.last_exported_paths.insert(1, str(mp4_path))
    self.episode_idx += 1
    self.buffer = None

  def export_snapshot(
      self,
      state: dict[str, Any],
      ram: np.ndarray | None,
      metadata: dict[str, Any],
      reason: str = 'manual_snapshot',
  ) -> None:
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    stem = f'play_snapshot_{self.episode_idx:04d}_{reason}_{stamp}'
    path = self.export_dir / f'{stem}.json'
    snapshot = {
        'reason': reason,
        'metadata': _jsonable(metadata),
        'state': _jsonable(state),
        'ram': None if ram is None else np.asarray(ram, dtype=np.uint8).tolist(),
    }
    path.write_text(json.dumps(snapshot, indent=2))
    self.last_exported_path = str(path)
    self.last_exported_paths = [str(path)]
    self.last_export_error = None

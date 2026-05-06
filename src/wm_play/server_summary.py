from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class CheckpointEntry:
  name: str
  path: str


def _fmt_bool(value: bool) -> str:
  return 'enabled' if value else 'disabled'


def _line(label: str, value: str) -> str:
  return f'  {label:<12}: {value}'


def _print_checkpoint_group(title: str, entries: Sequence[CheckpointEntry]) -> None:
  if not entries:
    return
  suffix = 'checkpoint' if len(entries) == 1 else 'checkpoints'
  print(_line(title, f'{len(entries)} {suffix}'))
  for idx, entry in enumerate(entries, start=1):
    name = entry.name or f'wm{idx - 1}'
    print(f'    {idx}. {name}: {entry.path}')


def print_remote_server_summary(
    *,
    project: str,
    controller: str,
    tcp_host: str,
    tcp_port: int,
    client_command: str,
    real_env: bool = True,
    wm_checkpoints: Sequence[CheckpointEntry] = (),
    component_checkpoints: Sequence[CheckpointEntry] = (),
    extras: Iterable[tuple[str, object]] = (),
    fps: int | None = None,
    stream_fps: int | None = None,
    size: int | None = None,
    jpeg_quality: int | None = None,
) -> None:
  """Print a compact startup summary shared by project adapters."""

  print('Remote play server')
  print(_line('project', project))
  print(_line('controller', controller))
  print(_line('real env', _fmt_bool(real_env)))
  if wm_checkpoints:
    _print_checkpoint_group('wm backends', wm_checkpoints)
  else:
    print(_line('wm backends', 'none'))
  if component_checkpoints:
    _print_checkpoint_group('components', component_checkpoints)
  for key, value in extras:
    if value is not None and value != '':
      print(_line(str(key), str(value)))
  stream_parts = []
  if fps is not None:
    stream_parts.append(f'loop={fps}fps')
  if stream_fps is not None:
    stream_parts.append(f'stream={stream_fps}fps')
  if size is not None:
    stream_parts.append(f'size={size}')
  if jpeg_quality is not None:
    stream_parts.append(f'jpeg={jpeg_quality}')
  if stream_parts:
    print(_line('render', ', '.join(stream_parts)))
  print(_line('listen', f'{tcp_host}:{tcp_port}'))
  print(_line('web', client_command))

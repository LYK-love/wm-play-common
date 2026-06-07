"""Public terminal-output contract for browser play servers.

Project adapters should use this module for user-facing remote-play output.
The contract is intentionally small:

- startup output begins with ``Remote play server`` and then aligned
  ``label: value`` rows;
- checkpoint groups use ``N checkpoint(s)`` plus numbered ``name: path`` rows;
- runtime state changes use ``> label       : value`` via
  :func:`print_runtime_event`;
- project-specific diagnostics may be printed before the summary, but shared
  play-server state should keep this format.
"""

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


def print_runtime_event(label: str, value: object) -> None:
  """Print one shared runtime event, such as backend/controller/horizon."""
  print(f'> {label:<12}: {value}', flush=True)


def _print_checkpoint_group(title: str, entries: Sequence[CheckpointEntry]) -> None:
  if not entries:
    return
  suffix = 'checkpoint' if len(entries) == 1 else 'checkpoints'
  print(_line(title, f'{len(entries)} {suffix}'), flush=True)
  for idx, entry in enumerate(entries, start=1):
    name = entry.name or f'wm{idx - 1}'
    print(f'    {idx}. {name}: {entry.path}', flush=True)


def print_remote_server_summary(
    *,
    project: str,
    controller: str,
    tcp_host: str,
    tcp_port: int,
    client_command: str,
    real_env: bool = True,
    wm_checkpoints: Sequence[CheckpointEntry] = (),
    policy_checkpoints: Sequence[CheckpointEntry] = (),
    component_checkpoints: Sequence[CheckpointEntry] = (),
    extras: Iterable[tuple[str, object]] = (),
    fps: int | None = None,
    stream_fps: int | None = None,
    size: int | None = None,
    jpeg_quality: int | None = None,
    ram_panel: bool | None = None,
) -> None:
  """Print the shared startup summary for all browser play adapters."""

  print('Remote play server', flush=True)
  print(_line('project', project), flush=True)
  print(_line('controller', controller), flush=True)
  print(_line('real env', _fmt_bool(real_env)), flush=True)
  if wm_checkpoints:
    _print_checkpoint_group('wm backends', wm_checkpoints)
  else:
    print(_line('wm backends', 'none'), flush=True)
  if component_checkpoints:
    _print_checkpoint_group('components', component_checkpoints)
  if policy_checkpoints:
    _print_checkpoint_group('policies', policy_checkpoints)
  if ram_panel is not None:
    print(_line('ram panel', _fmt_bool(ram_panel)), flush=True)
  for key, value in extras:
    if value is not None and value != '':
      print(_line(str(key), str(value)), flush=True)
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
    print(_line('render', ', '.join(stream_parts)), flush=True)
  print(_line('listen', f'{tcp_host}:{tcp_port}'), flush=True)
  print(_line('web', client_command), flush=True)

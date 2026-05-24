from __future__ import annotations

from typing import Any, Iterable, Mapping


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


def _fmt_env(status: Mapping[str, Any]) -> str:
  name = status.get('env_name') or status.get('env') or status.get('backend') or 'env'
  kind = status.get('env_kind') or status.get('kind')
  return str(name) if not kind else f'{name} ({kind})'


def _first_present(status: Mapping[str, Any], keys: Iterable[str]) -> Any:
  for key in keys:
    if key in status and status[key] is not None:
      return status[key]
  return None


def _termination_line(status: Mapping[str, Any]) -> str:
  cont = _first_present(status, ('continuation', 'cont_prob', 'cont'))
  if cont is not None:
    return f'Cont   : {_fmt_scalar(cont)}'
  term = _first_present(status, ('terminal', 'term', 'is_terminal', 'done'))
  return f'Term   : {_fmt_scalar(term)}'


def _extra_lines(extras: Any) -> list[str]:
  if not extras:
    return []
  if isinstance(extras, Mapping):
    return [f'{key}: {value}' for key, value in extras.items()]
  lines = []
  for item in extras if isinstance(extras, Iterable) and not isinstance(extras, str) else [extras]:
    if isinstance(item, tuple) and len(item) == 2:
      lines.append(f'{item[0]}: {item[1]}')
    elif item:
      lines.append(str(item))
  return lines


def play_status_lines(status: Mapping[str, Any] | None, extras: Any = None) -> list[str]:
  """Render common browser status lines for project-specific play adapters.

  Adapters should pass only facts here. This function owns the UI wording and
  intentionally omits horizon because the shared toolbar already displays it.
  """
  status = status or {}
  lines = [
      f'Env    : {_fmt_env(status)}',
      f'Control: {status.get("control", "-")}',
      f'Step   : {_fmt_scalar(status.get("step", status.get("timestep")))}',
      f'Reward : {_fmt_scalar(status.get("reward"))}',
      _termination_line(status),
      f'Return : {_fmt_scalar(status.get("return"))}',
      f'Action : {status.get("action_name", status.get("action", "-"))}',
  ]
  if status.get('done'):
    lines.append('State  : done')
  elif status.get('trunc'):
    lines.append('State  : truncated')
  lines.extend(_extra_lines(extras))
  return lines


def play_status_columns(status: Mapping[str, Any] | None, extras: Any = None) -> list[list[str]]:
  return [play_status_lines(status, extras)]

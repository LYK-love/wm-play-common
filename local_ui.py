from __future__ import annotations

import numpy as np
import pygame

from .api import PlaySession


def _find_font(size: int):
  candidates = [
      'Menlo',
      'Monaco',
      'Consolas',
      'DejaVu Sans Mono',
      'Liberation Mono',
      'Courier New',
  ]
  for name in candidates:
    path = pygame.font.match_font(name)
    if path:
      return pygame.font.Font(path, size)
  return pygame.font.Font(None, size)


def _draw_header(screen, header_lines: list[str], width: int, y0: int, fixed_height: int = 0) -> int:
  if fixed_height > 0:
    pygame.draw.rect(screen, (0, 0, 0), pygame.Rect(0, y0, width, fixed_height))
    pygame.draw.line(screen, (255, 255, 255), (0, y0 + fixed_height - 1), (width, y0 + fixed_height - 1), 1)
    if not header_lines:
      return fixed_height
  elif not header_lines:
    return 0
  font = _find_font(20)
  line_h = font.get_linesize()
  pad_x = 12
  pad_y = 8
  col_gap = 20
  cols = 2 if len(header_lines) > 6 else 1
  rows = (len(header_lines) + cols - 1) // cols
  panel_h = fixed_height if fixed_height > 0 else pad_y * 2 + rows * line_h
  max_rows = max(1, (panel_h - pad_y * 2) // line_h)
  rows = min(rows, max_rows)
  panel = pygame.Rect(0, y0, width, panel_h)
  if fixed_height <= 0:
    pygame.draw.rect(screen, (0, 0, 0), panel)
    pygame.draw.line(screen, (255, 255, 255), (0, y0 + panel_h - 1), (width, y0 + panel_h - 1), 1)
  col_w = max(1, (width - pad_x * 2 - col_gap * (cols - 1)) // cols)
  for idx, line in enumerate(header_lines):
    col = idx // rows
    row = idx % rows
    x = pad_x + col * (col_w + col_gap)
    y = y0 + pad_y + row * line_h
    surf = font.render(str(line), True, (245, 245, 245))
    screen.blit(surf, (x, y))
  return panel_h


def draw_frame(screen, frame, header_lines: list[str] | None = None) -> None:
  surf = pygame.surfarray.make_surface(np.array(frame).transpose((1, 0, 2)))
  screen.fill((0, 0, 0))
  fixed_header_h = max(0, screen.get_height() - surf.get_height())
  header_h = _draw_header(screen, header_lines or [], surf.get_width(), 0, fixed_header_h)
  screen.blit(surf, (0, header_h))
  pygame.display.flip()


def print_controls(action_names: list[str], keymap: dict[tuple[int, ...], int]) -> None:
  print('\nControls:\n')
  print('enter : reset')
  print('.     : pause/unpause')
  print('e     : single-step while paused')
  print('m     : switch controller (human/policy)')
  print('left/right : switch backend (wm/real)')
  print('up/down    : change wm horizon')
  print('\nActions:\n')
  inv = {}
  for keys, act in keymap.items():
    names = ' + '.join(pygame.key.name(k) for k in keys)
    inv[names] = act
  for names, act in inv.items():
    if act < len(action_names):
      print(f'{names:<18} -> {action_names[act]}')
  print('')


def run_local_session(args, session: PlaySession) -> None:
  pygame.init()
  print_controls(session.action_names, session.keymap)
  header_height = 0 if args.no_header else 240
  screen = pygame.display.set_mode((args.size, args.size + header_height))
  pygame.display.set_caption('Interactive Play')
  clock = pygame.time.Clock()

  session.reset()
  paused = False
  should_stop = False
  last_action = 0
  last_info = {}

  while not should_stop:
    do_one_step = False
    human_action = 0
    pygame.event.pump()

    for event in pygame.event.get():
      if event.type == pygame.QUIT:
        should_stop = True
      if event.type != pygame.KEYDOWN:
        continue
      if event.key == pygame.K_RETURN:
        session.reset()
      elif event.key == pygame.K_PERIOD:
        paused = not paused
        print('Paused.' if paused else 'Resumed.')
      elif event.key == pygame.K_e:
        do_one_step = True
      elif event.key == pygame.K_m:
        session.switch_controller()
      elif event.key == pygame.K_LEFT:
        session.switch_backend(-1)
      elif event.key == pygame.K_RIGHT:
        session.switch_backend(+1)
      elif event.key == pygame.K_UP:
        session.adjust_horizon(+1)
      elif event.key == pygame.K_DOWN:
        session.adjust_horizon(-1)

    pressed = pygame.key.get_pressed()
    for keys, action in sorted(session.keymap.items(), key=lambda item: -len(item[0])):
      if all(pressed[key] for key in keys):
        human_action = action
        break

    if not paused or do_one_step:
      action = session.choose_action(human_action)
      result = session.step(action)
      last_action = action
      last_info = result.info
      if result.done or result.trunc:
        session.reset()

    header = [] if args.no_header else session.header(last_action, last_info)
    draw_frame(screen, session.render_frame(args.size, []), header)
    clock.tick(args.fps)

  session.close()
  pygame.quit()

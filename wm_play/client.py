from __future__ import annotations

import io
import queue
import socket
import struct
import threading

from PIL import Image
import pygame

from .protocol import (
    MAGIC,
    MSG_FRAME,
    MSG_KEY,
    MSG_META,
    decode_meta,
    recv_exact,
    recv_message,
    send_message,
)


def decode_jpeg_to_surface(jpg: bytes) -> pygame.Surface:
  img = Image.open(io.BytesIO(jpg)).convert('RGB')
  return pygame.image.fromstring(img.tobytes(), img.size, 'RGB')


def find_font(size: int):
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


def draw_header(screen, header_lines: list[str], width: int, height: int) -> int:
  if height <= 0:
    return 0
  pygame.draw.rect(screen, (0, 0, 0), pygame.Rect(0, 0, width, height))
  pygame.draw.line(screen, (255, 255, 255), (0, height - 1), (width, height - 1), 1)
  if not header_lines:
    return height
  font = find_font(22)
  line_h = font.get_linesize()
  pad_x = 14
  pad_y = 8
  col_gap = 24
  cols = 2 if len(header_lines) > 6 else 1
  rows = (len(header_lines) + cols - 1) // cols
  max_rows = max(1, (height - pad_y * 2) // line_h)
  rows = min(rows, max_rows)
  col_w = max(1, (width - pad_x * 2 - col_gap * (cols - 1)) // cols)
  for idx, line in enumerate(header_lines):
    col = idx // rows
    row = idx % rows
    x = pad_x + col * (col_w + col_gap)
    y = pad_y + row * line_h
    surf = font.render(str(line), True, (245, 245, 245))
    screen.blit(surf, (x, y))
  return height


def run_remote_client(args, title: str = 'World Model Remote Play') -> None:
  sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
  sock.connect((args.host, args.port))
  if recv_exact(sock, 4) != MAGIC:
    raise RuntimeError('Bad server magic')

  pygame.init()
  flags = pygame.RESIZABLE
  if args.fullscreen:
    flags |= pygame.FULLSCREEN
  screen = pygame.display.set_mode((args.width, args.height), flags)
  pygame.display.set_caption(title)
  clock = pygame.time.Clock()

  frame_q: queue.Queue[tuple[pygame.Surface, list[str]]] = queue.Queue(maxsize=2)
  running = True
  latest_surface = None
  latest_header_lines: list[str] = []
  stretch = bool(args.stretch)

  def recv_loop():
    nonlocal running
    current_header_lines: list[str] = []
    try:
      while running:
        msg_type, payload = recv_message(sock)
        if msg_type == MSG_META:
          current_header_lines = decode_meta(payload)
          continue
        if msg_type != MSG_FRAME:
          continue
        item = (decode_jpeg_to_surface(payload), list(current_header_lines))
        while frame_q.full():
          try:
            frame_q.get_nowait()
          except queue.Empty:
            break
        frame_q.put_nowait(item)
    except Exception:
      running = False

  thread = threading.Thread(target=recv_loop, daemon=True)
  thread.start()

  movement_keys = {pygame.K_w, pygame.K_a, pygame.K_s, pygame.K_d, pygame.K_SPACE}

  while running:
    for event in pygame.event.get():
      if event.type == pygame.QUIT:
        running = False
        break
      if event.type == pygame.KEYDOWN:
        if event.key == pygame.K_ESCAPE:
          running = False
          break
        if event.key == pygame.K_f:
          stretch = not stretch
          continue
        payload = struct.pack('!Bi', 1, int(event.key))
        try:
          send_message(sock, MSG_KEY, payload)
        except Exception:
          running = False
          break
      if event.type == pygame.KEYUP:
        if event.key in movement_keys:
          payload = struct.pack('!Bi', 0, int(event.key))
          try:
            send_message(sock, MSG_KEY, payload)
          except Exception:
            running = False
            break
      if event.type == pygame.VIDEORESIZE and not args.fullscreen:
        screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)

    try:
      while True:
        latest_surface, latest_header_lines = frame_q.get_nowait()
    except queue.Empty:
      pass

    if latest_surface is not None:
      sw, sh = screen.get_size()
      iw, ih = latest_surface.get_size()
      screen.fill((0, 0, 0))
      header_h = draw_header(screen, latest_header_lines, sw, args.header_height)
      if stretch:
        dw, dh = sw, max(1, sh - header_h)
        x, y = 0, header_h
      else:
        avail_h = max(1, sh - header_h)
        scale = min(sw / max(1, iw), avail_h / max(1, ih))
        dw, dh = max(1, int(iw * scale)), max(1, int(ih * scale))
        x = (sw - dw) // 2
        y = header_h + (avail_h - dh) // 2
      if (dw, dh) != (iw, ih):
        draw = pygame.transform.scale(latest_surface, (dw, dh))
      else:
        draw = latest_surface
      screen.blit(draw, (x, y))
      pygame.display.flip()

    clock.tick(120)

  try:
    sock.close()
  except Exception:
    pass
  pygame.quit()

from __future__ import annotations

import argparse


def add_local_play_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
  parser.add_argument('--controller', choices=['human', 'policy'], default='human')
  parser.add_argument('--size', type=int, default=640)
  parser.add_argument('--fps', type=int, default=15)
  parser.add_argument('--no-header', action='store_true')
  return parser


def add_remote_server_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
  parser.add_argument('--controller', choices=['human', 'policy'], default='human')
  parser.add_argument('--fps', type=int, default=15,
                      help='Simulation tick rate used by the remote loop.')
  parser.add_argument('--size', type=int, default=640,
                      help='Rendered frame size before JPEG encoding.')
  parser.add_argument('--no-header', action='store_true')
  parser.add_argument('--jpeg-quality', type=int, default=90,
                      help='JPEG quality for streamed frames, valid range [1, 95].')
  parser.add_argument('--stream-fps', type=int, default=None,
                      help='Streaming frame rate cap; if set, it drives the main loop cadence.')
  parser.add_argument('--tcp-host', type=str, default='0.0.0.0',
                      help='TCP bind host for the remote play server.')
  parser.add_argument('--tcp-port', type=int, default=9876,
                      help='TCP bind port for the remote play server.')
  return parser


def validate_remote_server_args(args) -> None:
  if not (1 <= args.jpeg_quality <= 95):
    raise SystemExit('--jpeg-quality must be in [1, 95].')


def add_remote_client_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
  parser.add_argument('--host', type=str, required=True, help='Remote server host.')
  parser.add_argument('--port', type=int, default=9876, help='Remote server TCP port.')
  parser.add_argument('--width', type=int, default=1280, help='Initial client window width.')
  parser.add_argument('--height', type=int, default=900, help='Initial client window height.')
  parser.add_argument('--fullscreen', action='store_true', help='Start client in fullscreen mode.')
  parser.add_argument('--stretch', action='store_true',
                      help='Stretch frame to fill window instead of preserving aspect ratio.')
  parser.add_argument('--header-height', type=int, default=150,
                      help='Fixed status panel height in pixels. Use 0 to hide panel space.')
  return parser

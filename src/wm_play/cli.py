from __future__ import annotations

import argparse


def add_remote_server_args(
    parser: argparse.ArgumentParser,
    *,
    controller_default: str = 'human',
    fps_default: int = 15,
    size_default: int = 640,
    jpeg_quality_default: int = 90,
) -> argparse.ArgumentParser:
  parser.add_argument('--controller', choices=['human', 'policy'], default=controller_default)
  parser.add_argument('--fps', type=int, default=fps_default,
                      help='Simulation tick rate used by the remote loop.')
  parser.add_argument('--size', type=int, default=size_default,
                      help='Rendered frame size before JPEG encoding.')
  parser.add_argument('--no-header', action='store_true')
  parser.add_argument('--jpeg-quality', type=int, default=jpeg_quality_default,
                      help='JPEG quality for streamed frames, valid range [1, 95].')
  parser.add_argument('--web-host', type=str, default='127.0.0.1',
                      help='Web bind host.')
  parser.add_argument('--web-port', type=int, default=9876,
                      help='Web bind port.')
  return parser


def validate_remote_server_args(args) -> None:
  if not (1 <= args.jpeg_quality <= 95):
    raise SystemExit('--jpeg-quality must be in [1, 95].')

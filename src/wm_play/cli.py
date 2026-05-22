from __future__ import annotations

import argparse


def add_remote_server_args(
    parser: argparse.ArgumentParser,
    *,
    include_controller: bool = True,
    controller_default: str = 'human',
    fps_default: int = 15,
    size_default: int = 640,
    jpeg_quality_default: int = 90,
) -> argparse.ArgumentParser:
  if include_controller:
    parser.add_argument('--controller', choices=['human', 'policy'], default=controller_default)
  parser.add_argument('--fps', type=int, default=fps_default,
                      help='Simulation tick rate used by the remote loop.')
  parser.add_argument('--size', type=int, default=size_default,
                      help='Rendered frame size before JPEG encoding.')
  parser.add_argument('--no-header', action='store_true')
  parser.add_argument('--ram', action='store_true',
                      help='Enable RAM panel mode. This only takes effect for '
                           'real-env-only sessions whose adapter exposes RAM.')
  parser.add_argument('--jpeg-quality', type=int, default=jpeg_quality_default,
                      help='JPEG quality for streamed frames, valid range [1, 95].')
  parser.add_argument('--export-dir', type=str, default='debug_outputs/wm_play_exports',
                      help='Directory for web play recordings and snapshots.')
  parser.add_argument('--web-host', type=str, default='127.0.0.1',
                      help='Web bind host.')
  parser.add_argument('--web-port', type=int, default=9876,
                      help='Web bind port.')
  return parser


def add_pixel_policy_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
  """Add generic pixel-space policy controller checkpoint flags.

  Projects are responsible for loading the checkpoint format and wrapping it as
  a ``PixelPolicy``. The common web loop only calls ``policy.act(pixel_obs)``.
  """
  parser.add_argument('--policy-checkpoint', action='append', default=[],
                      help='Repeatable policy checkpoint path. Policies consume '
                           'pixel observations through the wm_play PixelPolicy '
                           'interface and are independent from WM backends.')
  parser.add_argument('--policy-name', action='append', default=[],
                      help='Optional repeatable policy display name. If omitted, '
                           'the name is inferred from the policy checkpoint path.')
  return parser


def validate_remote_server_args(args) -> None:
  if not (1 <= args.jpeg_quality <= 95):
    raise SystemExit('--jpeg-quality must be in [1, 95].')

from __future__ import annotations

import argparse


def add_atari_env_args(
    parser: argparse.ArgumentParser,
    *,
    dest: str = 'env_name',
    default: str | None = None,
    required: bool = False,
    option_strings: tuple[str, ...] = ('--env-id',),
) -> argparse.ArgumentParser:
  parser.add_argument(
      *option_strings,
      dest=dest,
      default=default,
      required=required,
      help='Atari environment id, e.g. ALE/Pong-v5 or PongNoFrameskip-v4.')
  return parser


def add_device_arg(
    parser: argparse.ArgumentParser,
    *,
    default: str = 'cuda',
) -> argparse.ArgumentParser:
  parser.add_argument('--device', default=default,
                      help='Torch device used by model and policy inference.')
  return parser


def add_remote_server_args(
    parser: argparse.ArgumentParser,
    *,
    include_controller: bool = False,
    controller_default: str = 'human',
    fps_default: int = 15,
    size_default: int = 640,
    jpeg_quality_default: int = 90,
) -> argparse.ArgumentParser:
  parser.set_defaults(controller=controller_default)
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


def add_wm_horizon_arg(
    parser: argparse.ArgumentParser,
    *,
    default: int = 512,
) -> argparse.ArgumentParser:
  parser.add_argument('--wm-horizon', type=int, default=default,
                      help='Episode horizon for WM play backends. The web '
                           'Horizon control edits this value.')
  return parser


def add_pixel_policy_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
  """Add generic pixel-space policy controller checkpoint flags.

  Projects are responsible for loading the checkpoint format and wrapping it as
  a ``PixelPolicy``. The common web loop only calls ``policy.act(pixel_obs)``.
  """
  parser.add_argument('--policy-checkpoint', action='append', default=[],
                      help='Repeatable policy checkpoint path or policy run directory. '
                           'Project loaders may resolve directories to latest policy ckpts. '
                           'Policies consume '
                           'pixel observations through the wm_play PixelPolicy '
                           'interface and are independent from WM backends.')
  parser.add_argument('--additional-policy-controller',
                      action=argparse.BooleanOptionalAction,
                      default=False,
                      help='Enable policy checkpoints as additional selectable controllers.')
  parser.add_argument('--policy-name', action='append', default=[],
                      help='Optional repeatable policy display name. If omitted, '
                           'the name is inferred from the policy checkpoint path.')
  return parser


def add_world_model_checkpoint_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
  """Add generic world-model backend checkpoint flags.

  Projects are responsible for loading checkpoint formats and constructing
  pixel-space ``GameEnv`` backends from them.
  """
  parser.add_argument('--wm-checkpoint', action='append', default=[],
                      help='Repeatable world-model checkpoint path. Each value '
                           'adds one selectable WM backend.')
  parser.add_argument('--wm-name', action='append', default=[],
                      help='Optional repeatable WM display name. If omitted, '
                           'the name is inferred from the WM checkpoint path.')
  return parser


def add_wm_bootstrap_dataset_arg(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
  parser.add_argument('--wm-bootstrap-dataset', default='',
                      help='Offline episode root/file used when '
                           '--wm-initial-source=dataset.')
  return parser


def add_wm_terminal_args(
    parser: argparse.ArgumentParser,
    *,
    default: bool = True,
) -> argparse.ArgumentParser:
  group = parser.add_mutually_exclusive_group()
  group.add_argument('--wm-respect-terminal', dest='wm_respect_terminal',
                     action='store_true',
                     help='Respect WM terminal predictions. This is the default.'
                          if default else 'Respect WM terminal predictions.')
  group.add_argument('--wm-ignore-terminal', dest='wm_respect_terminal',
                     action='store_false',
                     help='Ignore WM terminal predictions and keep rolling out '
                          'until reset/backend switch.')
  parser.set_defaults(wm_respect_terminal=default)
  return parser


def add_world_model_initial_source_arg(
    parser: argparse.ArgumentParser,
    *,
    default: str = 'real',
    choices: tuple[str, ...] = ('real', 'prior', 'dataset'),
) -> argparse.ArgumentParser:
  """Add the shared WM reset-initialization mode flag.

  Projects that need an external environment observation to bootstrap a WM
  latent should use this flag when they also support prior-only resets.
  """
  parser.add_argument(
      '--wm-initial-source',
      choices=choices,
      default=default,
      help='How WM rollouts are initialized. "real" lets the adapter use a '
           'real-env reset observation to bootstrap WM state. "prior" samples '
           'the initial latent from the WM prior and decodes the first '
           'observation without querying the real env when supported. "dataset" uses an '
           'offline bootstrap observation instead of new real-env data.')
  return parser


def add_play_checkpoint_args(
    parser: argparse.ArgumentParser,
    *,
    include_wm: bool = True,
    include_policy: bool = True,
) -> argparse.ArgumentParser:
  """Add the shared checkpoint-selection CLI for browser play tools."""
  if include_wm:
    add_world_model_checkpoint_args(parser)
  if include_policy:
    add_pixel_policy_args(parser)
  return parser


def validate_remote_server_args(args) -> None:
  if not (1 <= args.jpeg_quality <= 95):
    raise SystemExit('--jpeg-quality must be in [1, 95].')

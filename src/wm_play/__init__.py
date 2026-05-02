"""Shared interactive play framework for real envs and world models.

Import concrete modules directly, for example:

  from wm_play.api import GameEnv, StepResult
  from wm_play.cli import add_remote_client_args

The package initializer intentionally avoids eager imports so lightweight clients
only need their actual runtime dependencies.
"""

"""Shared interactive play framework for real envs and world models."""
from .api import GameEnv, PlaySession, RenderableGameEnv, StepResult
from .session import EnvPlaySession, EnvSlot, obs_to_image

__all__ = [
    'EnvPlaySession',
    'EnvSlot',
    'GameEnv',
    'PlaySession',
    'RenderableGameEnv',
    'StepResult',
    'obs_to_image',
    'add_local_play_args',
    'add_remote_client_args',
    'add_remote_server_args',
    'validate_remote_server_args',
]

from .cli import add_local_play_args, add_remote_client_args, add_remote_server_args, validate_remote_server_args

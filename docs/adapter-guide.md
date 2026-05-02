# Adapter Guide

Use this guide when adding a new action-conditioned world model.

## Minimal Environment Adapter

Implement `GameEnv`:

```python
from wm_play.api import GameEnv, StepResult

class MyWorldModelEnv(GameEnv):
    @property
    def action_count(self) -> int:
        return 6

    def reset(self) -> StepResult:
        return StepResult(obs=..., reward=0.0, done=False, trunc=False, info={})

    def step(self, action: int) -> StepResult:
        return StepResult(obs=..., reward=..., done=..., trunc=False, info={})
```

`obs` should usually contain an `image` entry with shape `H x W x C` and dtype `uint8`.

## Project-Specific CLI

Use `wm_play.cli` for common options, then add model-specific flags in the project:

```python
from wm_play.cli import add_remote_server_args

parser.add_argument('--config', required=True)
parser.add_argument('--checkpoint', action='append', default=[])
add_remote_server_args(parser)
```

Keep component names in the model project. For example, DIAMOND can expose `--denoiser-ckpt`, while Dreamer can expose `--dyn-checkpoint` or `--rew-checkpoint`.

## Reuse Existing Loops

- Local play: call `wm_play.local_ui.run_local_session(args, session)`.
- Remote server: call `wm_play.remote.run_game_loop(args, session, shared)` and `serve_client()`.
- Remote client: call `wm_play.client.run_remote_client(args, title='My Model Remote Play')`.

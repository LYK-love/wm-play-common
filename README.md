# wm-play-common

`wm-play-common` is a small framework for interactive play with real environments and action-conditioned world models. It provides the shared play contract, UI loops, TCP protocol, and common CLI arguments used by DreamerV3, DIAMOND, OC-STORM, and STORM adapters.

The framework deliberately does **not** load model checkpoints or own model-specific configuration. Each model project implements its own adapter for config parsing, checkpoint/component loading, image encode/decode, latent-state handling, and policy integration.

## Core Contract

World models and real environments are adapted to the same step-style API:

```python
obs, reward, done, trunc, info = env.step(action)
```

In this package, the normalized interface is `wm_play.api.GameEnv`:

```python
from wm_play.api import GameEnv, StepResult

class MyEnv(GameEnv):
    @property
    def action_count(self) -> int:
        return 6

    def reset(self) -> StepResult:
        ...

    def step(self, action: int) -> StepResult:
        ...
```

Use `wm_play.session.EnvPlaySession` when your environment already follows this contract. Write a project adapter when the model needs custom loading, latent-state transitions, render logic, or policy control.

## What This Repo Provides

- `wm_play.api`: common `GameEnv`, `RenderableGameEnv`, `PlaySession`, and `StepResult` types.
- `wm_play.session`: generic play-session implementation for step-style envs.
- `wm_play.local_ui`: local pygame UI loop.
- `wm_play.remote`: server-side remote-play loop and frame streaming.
- `wm_play.client`: reusable native TCP client.
- `wm_play.protocol`: compact TCP message protocol.
- `wm_play.cli`: common CLI argument helpers.

## Repository Layout

```text
wm-play-common/
  README.md
  pyproject.toml
  docs/
    architecture.md
    adapter-guide.md
  src/
    wm_play/
      api.py
      cli.py
      client.py
      local_ui.py
      protocol.py
      remote.py
      session.py
```

There is also a root-level `__init__.py` compatibility shim. It allows this repository to be mounted directly as a submodule named `wm_play` while still keeping the installable package in `src/wm_play`.

## Installation

For normal package usage:

```bash
python -m pip install -e /path/to/wm-play-common
```

For submodule usage, mount this repository at a package-like path, for example:

```text
project-root/
  wm_play/        # submodule pointing to wm-play-common
  project_adapter/
```

Then `import wm_play.cli` works through the compatibility shim.

## Dependencies

The native client needs only:

- Python 3.10+
- `pygame`
- `Pillow`

The local/server UI path also uses `numpy`. Model projects may require their own runtime stacks, for example JAX or PyTorch.

## Extension Boundary

Shared framework responsibilities:

- UI behavior and controls
- remote protocol
- frame streaming
- common CLI flags such as `--controller`, `--fps`, `--size`, `--tcp-host`, `--tcp-port`
- generic session state for real envs and world models

Model-project responsibilities:

- config files and model-specific CLI flags
- full-checkpoint and component-checkpoint loading
- model-specific component names
- image encoder/decoder glue
- latent rollout logic
- reward/terminal predictor invocation
- policy checkpoint integration

This boundary is intentional: new world models should only implement an adapter, not copy UI/protocol/client code.

# wm-play-common

`wm-play-common` provides the shared browser-based play infrastructure for
action-conditioned world models and real environments. Model projects provide
their own adapters for config parsing, checkpoint loading, environment
construction, latent rollout, rendering, and policy integration.

## Contract

Adapters expose a `PlaySession` with the usual step semantics:

```python
result = session.step(action)
obs = result.obs
reward = result.reward
done = result.done
trunc = result.trunc
info = result.info
```

The web server owns the control loop, keyboard handling, pause/reset/step,
server-side FPS control, JPEG frame streaming, and optional RAM panel plumbing.

## Provides

- `wm_play.api`: `GameEnv`, `RenderableGameEnv`, `PlaySession`, `StepResult`
- `wm_play.session`: generic session wrapper for simple step-style envs
- `wm_play.web_server`: Flask/SocketIO browser UI and server-side game loop
- `wm_play.cli`: shared play CLI flags
- `wm_play.server_summary`: compact startup summary formatting

There is no pygame/native client. The client side is always a browser:

```bash
ssh -N -L 9876:127.0.0.1:9876 <ssh-host>
```

Then open `http://127.0.0.1:9876`.

If the browser runs on the same machine as the server, skip SSH and open the
server URL directly, for example `http://127.0.0.1:9876`.

The client machine does not need the model project's conda environment, model
frameworks, CUDA, checkpoints, or `wm-play-common`; all model/env code runs on
the server.

## RAM Mode

RAM mode is explicit. Pass `--ram` to the project server to request the RAM
panel. The common web layer only enables it when the session is real-env-only
and the adapter exposes RAM read/write hooks; otherwise the normal play UI is
used.

## Layout

```text
wm-play-common/
  README.md
  pyproject.toml
  src/wm_play/
    api.py
    cli.py
    server_summary.py
    session.py
    web_server.py
    web/
      index.html
      app.js
      styles.css
```

The root-level `__init__.py` is a compatibility shim so this repository can be
mounted directly as a submodule named `wm_play`.

## Install

Standalone:

```bash
python -m pip install -e /path/to/wm-play-common
```

Submodule:

```bash
git submodule update --init --recursive
python -m pip install -e ./wm_play
```

DIAMOND uses `./src/wm_play` as its submodule path.

## RAM Panel Rule

The RAM panel is optional and appears only when the project adapter exposes RAM
state/edit methods and the server is running real env only. If any WM backend is
loaded, the UI stays in normal play mode without RAM controls.

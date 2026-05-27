# wm-play-common

`wm-play-common` provides the shared browser-based play infrastructure for
action-conditioned world models and real environments. Model projects provide
their own adapters for config parsing, checkpoint loading, environment
construction, latent rollout, rendering, and policy integration.

## Contract

Adapters expose a pixel-space `PlaySession` with Gym-style step semantics:

```python
result = session.step(action)
obs = result.obs
reward = result.reward
done = result.done
trunc = result.trunc
info = result.info
```

`result.obs` must be renderable pixels, or a dict containing renderable pixel
observations. Latent world models must keep encoder/RSSM/transformer state
inside the adapter and decode every displayed observation back to pixel space.
The common loop should be able to treat real envs and WMs as:

```python
next_o, next_r, done, trunc, info = env.step(current_act)
```

Policies plugged into the tool follow the same boundary. A `PixelPolicy` sees
pixel observations from the current backend and returns an action; latent
policies can do their own encoding internally, but the shared play layer never
depends on latent tensors.

The web server owns the control loop, keyboard handling, pause/reset/step,
backend switching, policy/controller switching, server-side FPS control, WM
horizon edits, JPEG frame streaming, and optional generic RAM panel plumbing.
It also owns trajectory recording/export: frames, actions, rewards, done/trunc
flags, metadata, and RAM arrays when RAM mode is active. Project adapters still
own model/env semantics. For example, an Atari adapter provides Pong-specific
RAM slot names and quick-start behavior.

The browser control bar exposes one forward-only selector for each mode family:
`Next Controller` cycles `human` and all loaded policy controllers, and
`Next Env` cycles the real environment and loaded world-model backends. Do not
add separate previous buttons or policy-specific selector buttons to project
copies of the shared UI. Keyboard hints should mirror the same contract:
`M` means next controller and Right means next env/backend. The server may keep
older keyboard events as compatibility aliases, but they are not part of the
visible browser UI contract.

Browser play always opens on the real environment with human control:

```text
backend    = real
controller = human
```

World-model backends and policy controllers may be loaded at startup, but they
must be additional selectable modes. Users switch to them live through the
shared backend/controller controls. CLI compatibility flags such as
`--controller` must not change the initial browser state.

`session.horizon is None` means the active backend has no finite WM rollout
horizon, which is how real-env backends are shown in the UI (`∞`). Finite WM
backends expose `horizon` and `set_horizon(...)`; the common web layer resets
the current game after a horizon change so backend state and UI state stay
consistent.

The common browser status panel is rendered by `wm_play.status`. Project
adapters should pass facts through `info["play_status"]` or `StepResult.info`
instead of formatting their own UI strings. The shared fields are `env_name`,
`env_kind`, `control`, `step`, `reward`, `return`, `action_name`,
`terminal`/`term`/`is_terminal`, `continuation`/`cont_prob`/`cont`, `done`, and
`trunc`. The panel always displays reward and a termination-related signal.
Projects that predict terminal should pass `terminal`; projects that predict
continuation should pass `continuation` or `cont_prob`, which is shown as
`Cont`. Adapters can add a small number of project-specific lines through
`info["status_extras"]`, for example an OC-STORM KV-cache indicator. Horizon is
intentionally not part of these status lines because the shared toolbar already
has a horizon control.

## Output Contract

All remote play servers should use `wm_play.server_summary` for shared terminal
output. Startup output begins with:

```text
Remote play server
  project     : <project>
  controller  : <controller>
  real env    : enabled|disabled
  wm backends : N checkpoint(s)|none
    1. <name>: <path>
  components  : N checkpoint(s)
    1. <name>: <path>
  policies    : N checkpoint(s)
    1. <name>: <path>
  ram panel   : enabled|disabled
  <extra>     : <value>
  render      : loop=<fps>fps, stream=<fps>fps, size=<px>, jpeg=<quality>
  listen      : <host>:<port>
  web         : open http://<server-ip>:<port>
```

Only print sections that apply. Project-specific diagnostics, such as model
loading messages, may appear before the summary. Shared play-server state
should keep the format above.

Runtime events use:

```text
> backend     : <name>[<index>/<count>]
> controller  : <name>
> policy      : <index>/<count> (<name>)
> wm horizon  : <steps>|none
```

Use `print_runtime_event(label, value)` instead of hand-formatting these lines.

## Provides

- `wm_play.api`: `GameEnv`, `RenderableGameEnv`, `PlaySession`, `PixelPolicy`,
  `PolicyAction`, `StepResult`
- `wm_play.status`: shared play status formatting for the browser and legacy
  pygame headers
- `wm_play.session`: generic session wrapper for simple step-style envs
- `wm_play.web_server`: Flask/SocketIO browser UI and server-side game loop
- `wm_play.recording`: generic trajectory recorder and exporter
- `wm_play.cli`: shared play CLI flags
- `wm_play.server_summary`: compact startup summary formatting

The shared CLI helpers define common browser-play flags such as
`--wm-checkpoint`, `--wm-name`, `--policy-checkpoint`, and `--policy-name`.
Projects still own checkpoint loading, but user-facing commands should use
these names consistently across adapters.

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

The common layer treats RAM as editable byte slots plus optional adapter hooks.
It does not define game-specific RAM meanings. Slot labels, focused dimensions,
and convenience actions such as Pong serve setup belong in the project adapter.

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
      vendor/
        socket.io.min.js
```

The root-level `__init__.py` is a compatibility shim so this repository can be
mounted directly as a submodule named `wm_play`.

The browser UI uses a vendored Socket.IO client from the npm
`socket.io-client` package. This avoids loading `/socket.io/socket.io.js` from
the Python server, which can fail when Flask-SocketIO and the browser client
protocol versions do not match.

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

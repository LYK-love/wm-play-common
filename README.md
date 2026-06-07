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
This same contract is used by the browser frontend and by headless notebook or
evaluation code; backend adapters should not depend on Flask, SocketIO, or any
browser-only state.
The common loop should be able to treat real envs and WMs as:

```python
next_o, next_r, done, trunc, info = env.step(current_act)
```

Policies plugged into the tool follow the same boundary. A `PixelPolicy` sees
pixel observations from the current backend and returns an action; latent
policies can do their own encoding internally, but the shared play layer never
depends on latent tensors.
Optional policy diagnostics, such as entropy, value, logits, or action
probabilities, belong in `PolicyAction.info` or project `StepResult.info`; only
the selected action is part of the required control path.

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
shared backend/controller controls. Remote play CLIs should not expose a
controller-selection flag; the initial browser controller is always `human`,
and users can switch controller live through the shared UI.

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

Optional adapter extension points:

- `record_metadata() -> dict`: extra JSON metadata for web and headless
  trajectory exports.
- `get_web_state() -> dict`: project-specific browser state. Keep shared keys
  aligned with the common frontend and add project keys only for real project
  UI needs.
- `render_frame(size, header_lines)`: project-specific rendering. Prefer
  returning pixels through `obs` when possible.
- Project-specific bootstrap helpers are allowed for headless evaluation, for
  example Dreamer's `DreamerWorldModelEnv.bootstrap_from_observation(obs)` for
  initializing multiple WMs from the same dataset observation.

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
- `wm_play.headless`: browser-free `run_episode()` rollout helper and
  `HeadlessRollout` result for notebooks and batch evaluation
- `wm_play.status`: shared play status formatting for the browser and legacy
  pygame headers
- `wm_play.session`: generic session wrapper for simple step-style envs
- `wm_play.web_server`: Flask/SocketIO browser UI and server-side game loop
- `wm_play.recording`: generic trajectory recorder and exporter
- `wm_play.cli`: shared play CLI flags
- `wm_play.server_summary`: compact startup summary formatting
- `wm_play.standalone`: real-env-only `wm-play` runner

The shared CLI helpers define common browser-play flags such as
`--env-id`, `--wm-checkpoint`, `--wm-name`, `--policy-checkpoint`,
`--policy-name`, `--wm-horizon`, `--wm-initial-source`, and
`--wm-bootstrap-dataset`. Projects still own checkpoint loading, but
user-facing commands should use these names consistently across adapters.

## Headless API

Notebook and evaluation code can use the same backend/session contract without
starting the frontend:

```python
from wm_play.headless import run_episode

session.reset()
session.switch_backend(+1)   # choose a WM backend, if the session has one
session.switch_controller()  # choose a configured policy, if desired

rollout = run_episode(
    session,
    max_steps=512,
    size=256,
    fps=15,
    export_dir="artifacts/play_rollouts",
    export_reason="eval_preview",
)

frames = rollout.frames
actions = rollout.actions
paths = rollout.exported_paths
```

The headless helper calls `session.choose_action(...)`, `session.step(...)`, and
`session.render_frame(...)`, matching the web loop's semantics. It returns
in-memory arrays and can also export the same `npz`/`mp4`/`json` artifacts as
the browser recorder.

## Standalone Real Env

`wm-play-common` also installs a small standalone real-env runner:

```bash
python -m pip install -e "/path/to/wm-play-common[gym]"
wm-play --env-id PongNoFrameskip-v4 --web-port 9876
```

For local source-tree testing without installing the console script:

```bash
PYTHONPATH=src python -m wm_play --env-id PongNoFrameskip-v4 --web-port 9876
```

The standalone runner opens the shared browser UI with only the real
environment loaded:

```text
backend    = real
controller = human
wm         = none
policy     = none
```

It lazy-loads `gymnasium` first and then falls back to `gym`; install one of
those packages plus the environment package/ROMs needed by the selected
`--env-id`. The common runner supports discrete action spaces. It maps
Atari-style action names to the shared `W/A/S/D/Space` controls when the env
exposes `get_action_meanings()`, and falls back to simple numeric actions for
generic discrete envs.

The standalone command intentionally does not load WM checkpoints or policy
checkpoints. Those require project-specific adapters because checkpoint
formats, model state, latent rollout, and policy preprocessing are owned by
each WM project.

## Project Adapter Contract

A project that wants to plug a WM backend into `wm-play-common` must expose a
pixel-space `GameEnv` or `PlaySession` boundary. The common loop should be able
to call:

```python
obs, info = env.reset()
result = env.step(action)
frame = session.render_frame(size, header_lines)
```

Required WM/backend behavior:

- `reset()` returns `(obs, info)`.
- `step(action)` returns `StepResult(obs, reward, done, trunc, info)`.
- `obs` is renderable pixels, or the adapter implements `render_frame(...)`.
- Finite WM rollouts expose `horizon`; real envs expose `horizon = None`.
- If horizon is editable, provide `set_horizon(horizon)` or
  `adjust_horizon(delta)`.
- Backends are selectable modes. Browser play still starts on the real env.
- WMs that normally need a real-env reset observation to initialize latent state
  should expose `--wm-initial-source real|prior|dataset` for the modes they
  support.
  `real` means the real reset observation is used only as a bootstrap input;
  the displayed step-0 observation should still be decoded by the WM. `prior`
  means the initial latent is sampled from the WM prior, so the WM backend does
  not query the real env during reset. `dataset` means reset bootstraps from an
  existing offline dataset via `--wm-bootstrap-dataset`.

Policy controllers use the pixel-level `PixelPolicy` interface:

```python
class MyPolicy:
  name = "policy1"

  def reset(self) -> None:
    ...

  def act(self, obs) -> PolicyAction:
    ...
```

The `obs` passed to `act()` is the current backend's pixel observation. If a
policy needs latent state, frame stacking, torch tensors, action repeats, or
checkpoint-specific preprocessing, the project adapter handles that internally
and returns only `PolicyAction(action=...)` to the common layer.

Adapter CLIs should use the shared helpers from `wm_play.cli`:

```python
add_remote_server_args(parser)
add_play_checkpoint_args(parser)
```

Project adapters then validate/load their own `--wm-checkpoint`,
`--policy-checkpoint`, `--wm-name`, `--policy-name`, and optional
`--wm-initial-source` values, construct the project-specific backends/policies,
and pass them to either `EnvPlaySession` or their own `PlaySession`
implementation before calling `run_web_server(...)`.

Startup output should be printed through `print_remote_server_summary(...)`,
and runtime selector changes should use `print_runtime_event(...)`, so all WM
projects expose the same terminal and browser behavior.

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
    standalone.py
    server_summary.py
    session.py
    web_server.py
    __main__.py
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

# Architecture

`wm-play-common` separates model-agnostic play infrastructure from model-specific adapters.

## Layers

- Adapter layer: implemented by each model project. It loads config/checkpoints and exposes one or more `GameEnv` instances.
- Session layer: `EnvPlaySession` tracks active backend, controller mode, pause/reset state, rewards, and display metadata.
- UI layer: `local_ui` renders local pygame sessions; `remote` streams frames over TCP; `client` receives frames and sends key events.
- Protocol layer: `protocol` defines small binary messages for frames, metadata, and key events.

## Backend Switching

A play session can contain a real environment plus zero or more world-model environments. Switching the active backend should reset the target backend so stale hidden state from the previous visit is not reused accidentally.

## Rendering

The client renders status/header text locally whenever metadata is streamed separately from the game image. This keeps text sharp and allows the game viewport to remain a fixed size across real and WM backends.

# wm-play-common

Shared interactive play framework for real environments and action-conditioned world models.

The core contract is:

```python
obs, reward, done, trunc, info = env.step(action)
```

Projects provide model-specific adapters for config loading, checkpoint loading, encode/decode, policy, and rendering. This package provides the high-level API, local UI, remote protocol, remote loop, generic step-style session, and common CLI arguments.

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class StepResult:
  """One backend transition.

  Stable fields are consumed by both the web frontend and headless evaluators.
  Project-specific diagnostics, such as policy entropy, value estimates,
  logits, cache state, or model-specific termination scores, belong in
  ``info``. UI-facing extra status lines should use ``info["status_extras"]``.
  """

  obs: Any
  reward: float
  done: bool
  trunc: bool
  info: dict[str, Any]


@dataclass
class PolicyAction:
  """Action selected by a pixel policy.

  ``action`` is the only required field. ``info`` is reserved for optional
  policy diagnostics such as entropy, value, logits, or action probabilities.
  Adapters can copy selected diagnostics into ``StepResult.info`` or
  ``status_extras`` when they should be visible in the shared frontend.
  """

  action: Any
  info: dict[str, Any] | None = None


class PixelPolicy(Protocol):
  """Pixel-space policy interface for wm-play.

  Latent-space projects should do their encoder/RSSM work inside ``act()`` so
  the outer game loop can stay at ``act = policy(obs)``.
  """

  name: str

  def reset(self) -> None:
    ...

  def act(self, obs: Any) -> PolicyAction:
    ...


class GameEnv(ABC):
  name: str

  @abstractmethod
  def reset(self) -> tuple[Any, dict[str, Any]]:
    raise NotImplementedError

  @abstractmethod
  def step(self, action: int) -> StepResult:
    raise NotImplementedError

  def close(self) -> None:
    pass


class RenderableGameEnv(GameEnv):

  def render_frame(self, obs: Any, size: int):
    raise NotImplementedError


class PlaySession(Protocol):
  """Frontend-facing session contract.

  The web UI and the headless API both drive this interface. Project adapters
  should keep model-specific state behind this boundary and expose facts through
  ``StepResult.info``, ``header()``, ``record_metadata()``, or optional
  project-specific web state methods.
  """

  action_names: list[str]
  keymap: dict[tuple[int, ...], int]
  current_obs: Any

  @property
  def horizon(self) -> int | None:
    ...

  def reset(self) -> None:
    ...

  def switch_backend(self, direction: int) -> None:
    ...

  def switch_controller(self) -> None:
    ...

  def switch_policy(self, direction: int) -> None:
    ...

  def adjust_horizon(self, delta: int) -> None:
    ...

  def set_horizon(self, horizon: int) -> None:
    ...

  def choose_action(self, human_action: int) -> int:
    ...

  def step(self, action: int) -> StepResult:
    ...

  def header(self, action: int, info: dict[str, Any]) -> list[str]:
    ...

  def render_frame(self, size: int, header_lines: list[str]):
    ...

  def close(self) -> None:
    ...

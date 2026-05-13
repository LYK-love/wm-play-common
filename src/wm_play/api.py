from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class StepResult:
  obs: Any
  reward: float
  done: bool
  trunc: bool
  info: dict[str, Any]


@dataclass
class PolicyAction:
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
  action_names: list[str]
  keymap: dict[tuple[int, ...], int]
  current_obs: Any

  def reset(self) -> None:
    ...

  def switch_backend(self, direction: int) -> None:
    ...

  def switch_controller(self) -> None:
    ...

  def adjust_horizon(self, delta: int) -> None:
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

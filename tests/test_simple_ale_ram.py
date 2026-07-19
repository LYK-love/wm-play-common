from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from wm_play.headless import run_episode
from wm_play.session import EnvPlaySession, EnvSlot
from wm_play.standalone import GymGameEnv, GymRAMController
from wm_play.web_server import WebSharedState, _ram_capable, _render_state


@pytest.mark.parametrize(
    ("env_name", "magic", "game", "focus_name"),
    [
        ("simple_ale:SimpleALE/Breakout-v5", b"MBRK", "breakout", "paddle_x"),
        ("simple_ale:SimpleALE/Boxing-v5", b"MBOX", "boxing", "player_x"),
    ],
)
def test_simple_ale_schema_is_discovered_from_the_environment(
    env_name: str, magic: bytes, game: str, focus_name: str
) -> None:
    pytest.importorskip("simple_ale")
    env = GymGameEnv(env_name, gym_backend="gymnasium", seed=7)
    session = EnvPlaySession(
        [EnvSlot(env_name, env)], env.action_names, env.keymap
    )
    session.reset()
    state = session.get_web_state()

    assert session.ram_available
    assert bytes(session.current_ram[:4]) == magic
    assert state["ram_game"] == game
    assert state["ram_is_complete_state"] is True
    assert "complete-state RAM" in state["ram_schema_name"]
    assert "not the original Atari RAM layout" in state["ram_semantics"]
    assert len(state["all_dims"]) == 128
    assert focus_name in {item["name"] for item in state["focus_dims"]}
    assert state["all_dims"][0]["editable"] is False
    session.close()


def test_simple_ale_ram_edit_and_persistence_use_atomic_state_writes() -> None:
    pytest.importorskip("simple_ale")
    env = GymGameEnv(
        "simple_ale:SimpleALE/Breakout-v5", gym_backend="gymnasium", seed=3
    )
    env.reset()

    original_magic = int(env.current_ram[0])
    env._apply_dim_value_from_web(0, 0)
    assert int(env.current_ram[0]) == original_magic
    assert "read-only" in env.ram.last_error

    env._apply_dim_value_from_web(8, 40)
    assert int(env.current_ram[8]) == 40
    assert env.ram.last_error == ""

    env._persist_dim_value_from_web(8, 41)
    result = env.step(3)
    assert int(env.current_ram[8]) == 41
    np.testing.assert_array_equal(result.obs, env._read_rgb_frame())
    assert env.get_web_state()["persistent_count"] == 1
    env.close()


def test_boxing_field_values_are_decoded_with_its_own_schema() -> None:
    pytest.importorskip("simple_ale")
    env = GymGameEnv(
        "simple_ale:SimpleALE/Boxing-v5", gym_backend="gymnasium", seed=5
    )
    env.reset()
    env._apply_dim_value_from_web(12, 9)
    state = env.get_web_state()
    player_score = next(
        item for item in state["focus_dims"] if item["name"] == "player_score"
    )
    assert player_score["formatted"] == "9"
    assert player_score["description"] == "Player score, capped at 100."
    env.close()


def test_headless_rollout_records_simple_ale_ram_after_session_delegation() -> None:
    pytest.importorskip("simple_ale")
    env_name = "simple_ale:SimpleALE/Boxing-v5"
    env = GymGameEnv(env_name, gym_backend="gymnasium", seed=11)
    session = EnvPlaySession(
        [EnvSlot(env_name, env)], env.action_names, env.keymap
    )
    rollout = run_episode(session, max_steps=8, human_action=0, size=64)
    assert rollout.frames.shape == (9, 64, 64, 3)
    assert rollout.actions.shape == (8,)
    assert session.current_ram.shape == (128,)
    assert session.record_metadata()["ram_is_complete_state"] is True
    assert _ram_capable(SimpleNamespace(ram=True), session)
    session.close()


def test_browser_state_enables_semantic_ram_panel() -> None:
    pytest.importorskip("simple_ale")
    env_name = "simple_ale:SimpleALE/Breakout-v5"
    env = GymGameEnv(env_name, gym_backend="gymnasium", seed=13)
    session = EnvPlaySession(
        [EnvSlot(env_name, env)], env.action_names, env.keymap
    )
    session.reset()
    shared = WebSharedState(paused=True)
    args = SimpleNamespace(
        ram=True, size=96, jpeg_quality=85, no_header=False
    )
    jpeg, state = _render_state(args, session, shared)
    assert jpeg.startswith(b"\xff\xd8")
    assert state["ram_enabled"] is True
    assert state["can_edit"] is True
    assert state["ram_is_complete_state"] is True
    assert state["ram_schema_name"].startswith("SimpleALE Breakout")
    session.close()


def test_generic_ale_ram_is_explicitly_not_called_complete_state() -> None:
    class FakeALE:
        def __init__(self) -> None:
            self.ram = np.arange(128, dtype=np.uint8)

        def getRAM(self):
            return self.ram.copy()

        def setRAM(self, dim: int, value: int) -> None:
            self.ram[int(dim)] = int(value)

    owner = SimpleNamespace(ale=FakeALE())
    controller = GymRAMController(SimpleNamespace(unwrapped=owner), "ALE/Pong-v5")
    state = controller.web_state(
        step=0, reward=0.0, episode_return=0.0,
        last_action=0, action_names=["noop"]
    )
    assert controller.available
    assert controller.complete_state is False
    assert state["ram_schema_name"] == "ALE hardware RAM"
    assert "not the complete emulator state" in state["ram_semantics"]


def test_real_ale_and_simple_ale_semantics_are_not_conflated() -> None:
    pytest.importorskip("ale_py")
    env = GymGameEnv("ALE/Pong-v5", gym_backend="gymnasium", seed=2)
    env.reset()
    state = env.get_web_state()
    assert env.ram_available
    assert state["ram_slot_count"] == 128
    assert state["ram_schema_name"] == "ALE hardware RAM"
    assert state["ram_is_complete_state"] is False
    assert "not the complete emulator state" in state["ram_semantics"]
    env.close()

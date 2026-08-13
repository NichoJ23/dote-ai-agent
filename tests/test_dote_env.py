"""
Pytest suite for DotEEnv Gymnasium API conformance.

Tests with mocked IPC using the ACTUAL wire format from the mod.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "agent"))

from dote_env import ACTION_COMMANDS, MAX_HEROES, MAX_ROOMS, DotEEnv
from guidelines_config import GuidelinesConfig
from state_parser import StateParser


# --- Test fixtures ---


def _make_state_dict(turn=1, phase="Strategy", dust=8.0, hero_hp=200.0, num_mobs=1):
    """Create a valid state dict matching actual mod wire format."""
    mobs = [{"type": f"Zed_{i}", "room_index": 1, "hp": 50.0, "max_hp": 80.0, "target_type": "AntiHeroMob"}
            for i in range(num_mobs)]
    return {
        "turn": turn,
        "floor": 1,
        "game_phase": phase,
        "crystal_state": "Plugged",
        "exit_room_index": 1,
        "start_room_index": 0,
        "resources": {
            "industry": 40.0, "food": 25.0, "science": 10.0,
            "dust": dust, "dust_max": 12.0,
            "industry_per_turn": 5.0, "food_per_turn": 3.0, "science_per_turn": 2.0,
            "dust_per_turn": 0.0, "room_power_cost": 1.0, "powered_room_count": 1,
        },
        "rooms": [
            {"index": 0, "is_powered": True, "is_auto_powered": True, "is_exit_room": False,
             "is_start_room": True, "is_fully_opened": True, "depth": 0,
             "suffers_emp": False, "emp_turns_remaining": 0, "dust_loot_amount": 0,
             "has_artifact": False, "has_stele": False,
             "adjacent_room_indices": [1], "major_module_name": "IndGen",
             "minor_module_names": [], "minor_slot_count": 2,
             "hero_count": 1, "mob_count": 0, "npc_count": 0},
            {"index": 1, "is_powered": False, "is_auto_powered": False, "is_exit_room": True,
             "is_start_room": False, "is_fully_opened": True, "depth": 1,
             "suffers_emp": False, "emp_turns_remaining": 0, "dust_loot_amount": 0,
             "has_artifact": False, "has_stele": False,
             "adjacent_room_indices": [0], "major_module_name": None,
             "minor_module_names": [], "minor_slot_count": 2,
             "hero_count": 0, "mob_count": num_mobs, "npc_count": 0},
        ],
        "closed_doors": [],
        "heroes": [
            {"name": "Max O'Kane", "faction": "Prisoner", "room_index": 0,
             "hp": hero_hp, "max_hp": 250.0, "level": 2,
             "has_crystal": False, "is_operating": False, "operating_module_name": None,
             "is_recruitable": False, "is_recruited": True,
             "active_skills": [{"name": "Punch", "cooldown_turns": 3, "remaining_cooldown": 0, "is_activated": False}],
             "passive_skills": [{"name": "Operate"}],
             "equipment": [{"slot_category": "Weapon", "item_name": "Sword"}]},
        ],
        "mobs": mobs,
        "merchants": [],
        "recruitable_heroes": [],
        "dropped_items": [],
        "backpack_items": [],
        "shared_inventory_items": [],
        "researchable_blueprints": [],
    }


@pytest.fixture
def mock_env():
    """Create a DotEEnv with mocked IPC client."""
    env = DotEEnv(guidelines=GuidelinesConfig(), connect_timeout=1.0)
    env._ipc = MagicMock()
    env._ipc.is_connected = True
    env._connected = True
    return env


# --- Tests ---


class TestSpaces:
    def test_observation_space_is_dict(self, mock_env):
        from gymnasium import spaces
        assert isinstance(mock_env.observation_space, spaces.Dict)

    def test_observation_space_keys(self, mock_env):
        expected = {"adjacency", "door_state", "node_features", "hero_features", "resources", "game_meta"}
        assert set(mock_env.observation_space.spaces.keys()) == expected

    def test_observation_space_shapes(self, mock_env):
        obs = mock_env.observation_space
        assert obs["adjacency"].shape == (MAX_ROOMS, MAX_ROOMS)
        assert obs["door_state"].shape == (MAX_ROOMS, MAX_ROOMS)
        assert obs["node_features"].shape == (MAX_ROOMS, 12)
        assert obs["hero_features"].shape == (MAX_HEROES, 9)
        assert obs["resources"].shape == (8,)
        assert obs["game_meta"].shape == (9,)

    def test_action_space_is_dict(self, mock_env):
        from gymnasium import spaces
        assert isinstance(mock_env.action_space, spaces.Dict)

    def test_action_space_keys(self, mock_env):
        expected = {"command_type", "target_room", "hero_index", "entity_id_hash"}
        assert set(mock_env.action_space.spaces.keys()) == expected

    def test_action_space_dimensions(self, mock_env):
        act = mock_env.action_space
        assert act["command_type"].n == len(ACTION_COMMANDS)
        assert act["target_room"].n == MAX_ROOMS
        assert act["hero_index"].n == MAX_HEROES

    def test_sample_observation_in_space(self, mock_env):
        sample = mock_env.observation_space.sample()
        assert mock_env.observation_space.contains(sample)

    def test_sample_action_in_space(self, mock_env):
        sample = mock_env.action_space.sample()
        assert mock_env.action_space.contains(sample)


class TestReset:
    def test_reset_returns_tuple(self, mock_env):
        mock_env._ipc.receive_state.return_value = _make_state_dict()
        mock_env._ipc.send_action.return_value = {"success": True}
        obs, info = mock_env.reset()
        assert isinstance(obs, dict)
        assert isinstance(info, dict)

    def test_reset_observation_in_space(self, mock_env):
        mock_env._ipc.receive_state.return_value = _make_state_dict()
        mock_env._ipc.send_action.return_value = {"success": True}
        obs, _ = mock_env.reset()
        assert mock_env.observation_space.contains(obs)

    def test_reset_info_keys(self, mock_env):
        mock_env._ipc.receive_state.return_value = _make_state_dict()
        mock_env._ipc.send_action.return_value = {"success": True}
        _, info = mock_env.reset()
        assert "turn" in info
        assert "game_phase" in info
        assert "crystal_state" in info

    def test_reset_sends_unpause(self, mock_env):
        mock_env._ipc.receive_state.return_value = _make_state_dict()
        mock_env._ipc.send_action.return_value = {"success": True}
        mock_env.reset()
        mock_env._ipc.send_action.assert_called_with("UNPAUSE_GAME", {})


class TestStep:
    def _setup(self, mock_env, state_dict=None):
        if state_dict is None:
            state_dict = _make_state_dict()
        mock_env._ipc.receive_state.return_value = state_dict
        mock_env._ipc.send_action.return_value = {"success": True}
        mock_env.reset()

    def test_step_returns_5_tuple(self, mock_env):
        self._setup(mock_env)
        mock_env._ipc.receive_state.return_value = _make_state_dict(turn=2)
        mock_env._ipc.send_action.return_value = {"success": True}
        result = mock_env.step(mock_env.action_space.sample())
        assert len(result) == 5

    def test_step_observation_in_space(self, mock_env):
        self._setup(mock_env)
        mock_env._ipc.receive_state.return_value = _make_state_dict(turn=2)
        mock_env._ipc.send_action.return_value = {"success": True}
        obs, _, _, _, _ = mock_env.step(mock_env.action_space.sample())
        assert mock_env.observation_space.contains(obs)

    def test_step_reward_is_float(self, mock_env):
        self._setup(mock_env)
        mock_env._ipc.receive_state.return_value = _make_state_dict(turn=2)
        mock_env._ipc.send_action.return_value = {"success": True}
        _, reward, _, _, _ = mock_env.step(mock_env.action_space.sample())
        assert isinstance(reward, float)

    def test_step_terminated_on_crystal_destroyed(self, mock_env):
        self._setup(mock_env)
        dead_state = _make_state_dict(turn=2)
        dead_state["crystal_state"] = "Unplugged"
        mock_env._ipc.receive_state.return_value = dead_state
        mock_env._ipc.send_action.return_value = {"success": True}
        _, _, terminated, _, _ = mock_env.step(mock_env.action_space.sample())
        assert terminated is True

    def test_step_info_has_action_result(self, mock_env):
        self._setup(mock_env)
        mock_env._ipc.receive_state.return_value = _make_state_dict(turn=2)
        mock_env._ipc.send_action.return_value = {"success": True}
        _, _, _, _, info = mock_env.step(mock_env.action_space.sample())
        assert "action_result" in info
        assert "action_sent" in info


class TestReward:
    def test_room_exploration_reward(self, mock_env):
        # More rooms in curr = rooms explored
        prev = _make_state_dict(turn=1)
        curr = _make_state_dict(turn=2)
        # Add a new room to curr
        curr["rooms"].append({
            "index": 2, "is_powered": False, "is_auto_powered": False,
            "is_exit_room": False, "is_start_room": False, "is_fully_opened": True,
            "depth": 2, "suffers_emp": False, "emp_turns_remaining": 0,
            "dust_loot_amount": 0, "has_artifact": False, "has_stele": False,
            "adjacent_room_indices": [1], "major_module_name": None,
            "minor_module_names": [], "minor_slot_count": 2,
            "hero_count": 0, "mob_count": 0, "npc_count": 0,
        })
        prev_state = StateParser().parse(prev)
        curr_state = StateParser().parse(curr)
        mock_env._current_state = curr_state
        reward = mock_env._compute_reward(prev_state, curr_state)
        assert reward >= 10.0

    def test_dust_reward(self, mock_env):
        prev = _make_state_dict(turn=1, dust=5.0)
        curr = _make_state_dict(turn=2, dust=8.0)
        prev_state = StateParser().parse(prev)
        curr_state = StateParser().parse(curr)
        reward = mock_env._compute_reward(prev_state, curr_state)
        assert reward >= 15.0  # +5 * 3

    def test_hp_loss_penalty(self, mock_env):
        prev = _make_state_dict(turn=1, hero_hp=250.0)
        curr = _make_state_dict(turn=2, hero_hp=200.0)
        prev_state = StateParser().parse(prev)
        curr_state = StateParser().parse(curr)
        reward = mock_env._compute_reward(prev_state, curr_state)
        # 50 HP lost / 250 max = 20% lost, penalty = -0.05 * 20 = -1.0
        assert reward <= -1.0 + 0.01

    def test_crystal_destroyed_penalty(self, mock_env):
        prev = _make_state_dict(turn=1)
        curr = _make_state_dict(turn=2)
        curr["crystal_state"] = "Unplugged"
        prev_state = StateParser().parse(prev)
        curr_state = StateParser().parse(curr)
        reward = mock_env._compute_reward(prev_state, curr_state)
        assert reward <= -100.0

    def test_mob_killed_reward(self, mock_env):
        prev = _make_state_dict(turn=1, num_mobs=3)
        curr = _make_state_dict(turn=2, num_mobs=1)
        prev_state = StateParser().parse(prev)
        curr_state = StateParser().parse(curr)
        reward = mock_env._compute_reward(prev_state, curr_state)
        assert reward >= 2.0

    def test_hero_death_penalty(self, mock_env):
        prev = _make_state_dict(turn=1)
        curr = _make_state_dict(turn=2)
        curr["heroes"] = []
        prev_state = StateParser().parse(prev)
        curr_state = StateParser().parse(curr)
        reward = mock_env._compute_reward(prev_state, curr_state)
        assert reward <= -20.0

    def test_no_reward_first_step(self, mock_env):
        curr = StateParser().parse(_make_state_dict(turn=1))
        assert mock_env._compute_reward(None, curr) == 0.0


class TestClose:
    def test_close_disconnects(self, mock_env):
        mock_env.close()
        mock_env._ipc.disconnect.assert_called_once()
        assert mock_env._connected is False

    def test_close_idempotent(self, mock_env):
        mock_env._connected = False
        mock_env.close()
        mock_env._ipc.disconnect.assert_not_called()


class TestRender:
    def test_render_json(self, mock_env):
        mock_env.render_mode = "json"
        mock_env._ipc.receive_state.return_value = _make_state_dict()
        mock_env._ipc.send_action.return_value = {"success": True}
        mock_env.reset()
        output = mock_env.render()
        assert output is not None
        assert "turn" in output

    def test_render_human(self, mock_env):
        mock_env.render_mode = "human"
        mock_env._ipc.receive_state.return_value = _make_state_dict()
        mock_env._ipc.send_action.return_value = {"success": True}
        mock_env.reset()
        output = mock_env.render()
        assert "Turn" in output
        assert "Crystal" in output

    def test_render_none(self, mock_env):
        mock_env.render_mode = None
        assert mock_env.render() is None

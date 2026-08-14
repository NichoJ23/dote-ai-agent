"""
Unit tests for rl_env.py — RL environment observation building, action translation, masking.

Tests the offline components (no IPC connection needed).
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "agent"))

from action_masking import NUM_OPTIONS, StrategicOption
from rl_config import RLConfig
from rl_env import (
    GAME_META_DIM,
    HERO_FEATURE_DIM,
    MAX_HEROES,
    MAX_MOBS,
    MAX_MODULES,
    MAX_ROOMS,
    MOB_FEATURE_DIM,
    RESOURCE_DIM,
    ROOM_FEATURE_DIM,
    RLEnv,
)
from state_parser import GameStatePayload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_state(**overrides) -> GameStatePayload:
    """Build a minimal valid game state."""
    defaults = {
        "turn": 3,
        "floor": 1,
        "game_phase": "Strategy",
        "crystal_state": "Plugged",
        "exit_room_index": 3,
        "start_room_index": 0,
        "resources": {
            "industry": 50, "food": 30, "science": 20,
            "dust": 5, "dust_max": 10,
            "industry_per_turn": 5, "food_per_turn": 3, "science_per_turn": 2,
            "dust_per_turn": 0, "room_power_cost": 1, "powered_room_count": 2,
        },
        "rooms": [
            {"index": 0, "is_powered": True, "is_auto_powered": True, "is_start_room": True,
             "adjacent_room_indices": [1], "minor_slot_count": 2, "is_fully_opened": True,
             "major_module_name": "MajorModule_Major0002_LVL1"},
            {"index": 1, "is_powered": True, "is_auto_powered": False,
             "adjacent_room_indices": [0, 2], "minor_slot_count": 3, "is_fully_opened": True},
            {"index": 2, "is_powered": False, "is_auto_powered": False,
             "adjacent_room_indices": [1, 3], "minor_slot_count": 2, "is_fully_opened": True},
            {"index": 3, "is_powered": False, "is_auto_powered": False, "is_exit_room": True,
             "adjacent_room_indices": [2], "minor_slot_count": 2, "is_fully_opened": True},
        ],
        "closed_doors": [],
        "heroes": [
            {"name": "Max", "room_index": 0, "hp": 100, "max_hp": 100, "level": 2,
             "faction": "Prisoner", "is_usable": True,
             "passive_skills": [{"name": "Operate"}],
             "active_skills": [{"name": "Dash", "cooldown_turns": 3, "remaining_cooldown": 0}],
             "equipment": [{"slot_category": "Weapon", "item_name": "Sword"}]},
            {"name": "Gork", "room_index": 1, "hp": 80, "max_hp": 100, "level": 1,
             "faction": "Native", "is_usable": True,
             "passive_skills": [{"name": "Repair"}],
             "equipment": []},
        ],
        "mobs": [
            {"type": "Zed", "room_index": 2, "hp": 30, "max_hp": 50, "target_type": "AntiHeroMob"},
        ],
        "merchants": [],
        "recruitable_heroes": [],
        "dropped_items": [],
        "backpack_items": [],
        "shared_inventory_items": [],
        "researchable_blueprints": [],
        "buildable_blueprints": [
            {"name": "MinorModule_Minor0004_LVL1", "module_name": "Minor0004",
             "category": "MinorModule_Offense", "level": 1, "industry_cost": 10},
        ],
    }
    defaults.update(overrides)
    return GameStatePayload.model_validate(defaults)


def _make_env_with_state(state: GameStatePayload) -> RLEnv:
    """Create an RLEnv with mocked IPC, pre-loaded with a state."""
    with patch("rl_env.IpcClient"):
        env = RLEnv()
    env._current_state = state
    env._prev_state = None
    env._connected = True
    return env


# ---------------------------------------------------------------------------
# Observation Space
# ---------------------------------------------------------------------------


class TestObservationSpace:
    def test_observation_space_keys(self):
        with patch("rl_env.IpcClient"):
            env = RLEnv()
        expected_keys = {
            "adjacency", "door_state", "power_state", "power_reachable",
            "room_features", "hero_features", "mob_features",
            "resources", "game_meta", "action_mask",
        }
        assert set(env.observation_space.spaces.keys()) == expected_keys

    def test_observation_shapes(self):
        env = _make_env_with_state(_base_state())
        obs = env._build_observation(env._current_state)

        assert obs["adjacency"].shape == (MAX_ROOMS, MAX_ROOMS)
        assert obs["door_state"].shape == (MAX_ROOMS, MAX_ROOMS)
        assert obs["power_state"].shape == (MAX_ROOMS,)
        assert obs["power_reachable"].shape == (MAX_ROOMS,)
        assert obs["room_features"].shape == (MAX_ROOMS, ROOM_FEATURE_DIM)
        assert obs["hero_features"].shape == (MAX_HEROES, HERO_FEATURE_DIM)
        assert obs["mob_features"].shape == (MAX_MOBS, MOB_FEATURE_DIM)
        assert obs["resources"].shape == (RESOURCE_DIM,)
        assert obs["game_meta"].shape == (GAME_META_DIM,)
        assert obs["action_mask"].shape == (NUM_OPTIONS,)

    def test_observation_dtypes(self):
        env = _make_env_with_state(_base_state())
        obs = env._build_observation(env._current_state)

        assert obs["adjacency"].dtype == np.int8
        assert obs["door_state"].dtype == np.int8
        assert obs["power_state"].dtype == np.int8
        assert obs["power_reachable"].dtype == np.int8
        assert obs["room_features"].dtype == np.float32
        assert obs["hero_features"].dtype == np.float32
        assert obs["mob_features"].dtype == np.float32
        assert obs["resources"].dtype == np.float32
        assert obs["game_meta"].dtype == np.float32
        assert obs["action_mask"].dtype == np.int8


# ---------------------------------------------------------------------------
# Adjacency & Door State
# ---------------------------------------------------------------------------


class TestAdjacencyDoorState:
    def test_adjacency_reflects_room_connections(self):
        env = _make_env_with_state(_base_state())
        obs = env._build_observation(env._current_state)
        adj = obs["adjacency"]
        # Room 0-1 connected
        assert adj[0, 1] == 1
        assert adj[1, 0] == 1
        # Room 1-2 connected
        assert adj[1, 2] == 1
        # Room 0-2 NOT connected
        assert adj[0, 2] == 0

    def test_door_state_all_open(self):
        """Base state has no closed doors — all edges should be open."""
        env = _make_env_with_state(_base_state())
        obs = env._build_observation(env._current_state)
        ds = obs["door_state"]
        # Room 0-1 open
        assert ds[0, 1] == 1
        assert ds[1, 2] == 1
        assert ds[2, 3] == 1

    def test_door_state_with_closed_door(self):
        state = _base_state(closed_doors=[{"room1_index": 2, "room2_index": 3}])
        env = _make_env_with_state(state)
        obs = env._build_observation(state)
        ds = obs["door_state"]
        # 2-3 closed
        assert ds[2, 3] == 0
        assert ds[3, 2] == 0
        # 1-2 still open
        assert ds[1, 2] == 1


# ---------------------------------------------------------------------------
# Power State & Reachability
# ---------------------------------------------------------------------------


class TestPowerState:
    def test_power_state_correct(self):
        env = _make_env_with_state(_base_state())
        obs = env._build_observation(env._current_state)
        ps = obs["power_state"]
        assert ps[0] == 1  # auto-powered
        assert ps[1] == 1  # powered
        assert ps[2] == 0  # unpowered
        assert ps[3] == 0  # unpowered

    def test_power_reachable_from_crystal(self):
        """Rooms 0 and 1 are powered and connected via open doors."""
        env = _make_env_with_state(_base_state())
        obs = env._build_observation(env._current_state)
        pr = obs["power_reachable"]
        assert pr[0] == 1  # Crystal room
        assert pr[1] == 1  # Connected powered room
        assert pr[2] == 0  # Not powered
        assert pr[3] == 0  # Not powered

    def test_power_reachable_broken_by_closed_door(self):
        """If door between 0 and 1 is closed, room 1 is not reachable."""
        state = _base_state(closed_doors=[{"room1_index": 0, "room2_index": 1}])
        env = _make_env_with_state(state)
        obs = env._build_observation(state)
        pr = obs["power_reachable"]
        assert pr[0] == 1  # Crystal room always reachable from itself
        assert pr[1] == 0  # Door closed — can't reach


# ---------------------------------------------------------------------------
# Room Features
# ---------------------------------------------------------------------------


class TestRoomFeatures:
    def test_room_features_populated(self):
        env = _make_env_with_state(_base_state())
        obs = env._build_observation(env._current_state)
        rf = obs["room_features"]
        # Room 0: powered, auto_powered, start_room, has major module
        assert rf[0, 0] == 1.0  # is_powered
        assert rf[0, 1] == 1.0  # is_auto_powered
        assert rf[0, 2] == 1.0  # is_start_room
        assert rf[0, 3] == 0.0  # not exit room
        assert rf[0, 11] == 1.0  # has_major_module

    def test_unexplored_rooms_have_default(self):
        env = _make_env_with_state(_base_state())
        obs = env._build_observation(env._current_state)
        rf = obs["room_features"]
        # Room 10 doesn't exist — should be -1 (default)
        assert rf[10, 0] == -1.0

    def test_distances_computed(self):
        env = _make_env_with_state(_base_state())
        obs = env._build_observation(env._current_state)
        rf = obs["room_features"]
        # Room 0: distance to crystal = 0, distance to exit = 3
        assert rf[0, 18] == 0.0  # dist_to_crystal
        assert rf[0, 19] == 3.0  # dist_to_exit
        # Room 3: distance to crystal = 3, distance to exit = 0
        assert rf[3, 18] == 3.0
        assert rf[3, 19] == 0.0


# ---------------------------------------------------------------------------
# Hero Features
# ---------------------------------------------------------------------------


class TestHeroFeatures:
    def test_hero_features_populated(self):
        env = _make_env_with_state(_base_state())
        obs = env._build_observation(env._current_state)
        hf = obs["hero_features"]
        # Max: room 0, full HP, level 2, has Operate passive
        assert hf[0, 0] == 0.0   # room_index
        assert hf[0, 1] == 1.0   # hp_ratio (100/100)
        assert hf[0, 2] == 2.0   # level
        assert hf[0, 8] == 1.0   # has_operate
        assert hf[0, 9] == 0.0   # no repair
        # Gork: room 1, 80% HP, has Repair passive
        assert hf[1, 0] == 1.0   # room_index
        assert hf[1, 1] == pytest.approx(0.8)  # hp_ratio
        assert hf[1, 8] == 0.0   # no operate
        assert hf[1, 9] == 1.0   # has_repair

    def test_no_hero_slots_default(self):
        env = _make_env_with_state(_base_state())
        obs = env._build_observation(env._current_state)
        hf = obs["hero_features"]
        # Slot 2+ should be -1 (no hero)
        assert hf[2, 0] == -1.0
        assert hf[5, 0] == -1.0


# ---------------------------------------------------------------------------
# Mob Features
# ---------------------------------------------------------------------------


class TestMobFeatures:
    def test_mob_features_populated(self):
        env = _make_env_with_state(_base_state())
        obs = env._build_observation(env._current_state)
        mf = obs["mob_features"]
        # Mob 0: room 2, 60% HP, AntiHeroMob
        assert mf[0, 0] == 2.0  # room_index
        assert mf[0, 1] == pytest.approx(0.6)  # hp_ratio 30/50
        assert mf[0, 2] == 0.0  # AntiHeroMob -> 0

    def test_empty_mob_slots(self):
        env = _make_env_with_state(_base_state())
        obs = env._build_observation(env._current_state)
        mf = obs["mob_features"]
        assert mf[1, 0] == -1.0  # No second mob


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


class TestResources:
    def test_resources_correct(self):
        env = _make_env_with_state(_base_state())
        obs = env._build_observation(env._current_state)
        r = obs["resources"]
        assert r[0] == 50.0   # industry
        assert r[1] == 30.0   # food
        assert r[2] == 20.0   # science
        assert r[3] == 5.0    # dust
        assert r[4] == 10.0   # dust_max
        assert r[8] == 2.0    # dust_used (2 rooms * 1 cost)
        assert r[9] == 3.0    # dust_available (5 - 2)


# ---------------------------------------------------------------------------
# Game Meta
# ---------------------------------------------------------------------------


class TestGameMeta:
    def test_game_meta_correct(self):
        env = _make_env_with_state(_base_state())
        obs = env._build_observation(env._current_state)
        gm = obs["game_meta"]
        assert gm[0] == 3.0   # turn
        assert gm[1] == 1.0   # floor
        assert gm[2] == 0.0   # phase (Strategy = 0)
        assert gm[3] == 4.0   # num_rooms
        assert gm[4] == 2.0   # num_heroes
        assert gm[5] == 1.0   # num_mobs
        assert gm[7] == 1.0   # crystal_safe
        assert gm[8] == 3.0   # exit_room_index


# ---------------------------------------------------------------------------
# Action Mask in Observation
# ---------------------------------------------------------------------------


class TestActionMaskInObs:
    def test_mask_included_in_observation(self):
        env = _make_env_with_state(_base_state())
        obs = env._build_observation(env._current_state)
        mask = obs["action_mask"]
        assert mask.shape == (NUM_OPTIONS,)
        # WAIT always valid
        assert mask[StrategicOption.WAIT] == 1

    def test_mask_reflects_state(self):
        state = _base_state()
        state.resources.food = 0  # Can't heal or recruit
        env = _make_env_with_state(state)
        obs = env._build_observation(state)
        mask = obs["action_mask"]
        assert mask[StrategicOption.HEAL_HERO] == 0
        assert mask[StrategicOption.RECRUIT_HERO] == 0


# ---------------------------------------------------------------------------
# Action Translation
# ---------------------------------------------------------------------------


class TestActionTranslation:
    def test_wait_action(self):
        env = _make_env_with_state(_base_state())
        cmd, params = env._translate_action(StrategicOption.WAIT, 0, 0, 0)
        assert cmd == "WAIT"
        assert params == {}

    def test_power_room_action(self):
        env = _make_env_with_state(_base_state())
        cmd, params = env._translate_action(StrategicOption.POWER_ROOM, 2, 0, 0)
        assert cmd == "POWER_ROOM"
        assert params == {"room_index": 2}

    def test_depower_room_action(self):
        env = _make_env_with_state(_base_state())
        cmd, params = env._translate_action(StrategicOption.DEPOWER_ROOM, 1, 0, 0)
        assert cmd == "UNPOWER_ROOM"
        assert params == {"room_index": 1}

    def test_build_module_action(self):
        env = _make_env_with_state(_base_state())
        cmd, params = env._translate_action(StrategicOption.BUILD_MODULE, 1, 0, 0)
        assert cmd == "BUILD_MODULE"
        assert params["room_index"] == 1
        assert params["module_name"] == "MinorModule_Minor0004_LVL1"
        assert params["slot_type"] == "minor"

    def test_position_hero_direct_destination(self):
        """POSITION_HERO sends MOVE_HERO directly to target room (no hop-by-hop)."""
        env = _make_env_with_state(_base_state())
        cmd, params = env._translate_action(StrategicOption.POSITION_HERO, 3, 0, 0)
        assert cmd == "MOVE_HERO"
        assert params["hero_name"] == "Max"
        assert params["target_room_index"] == 3  # Direct to room 3, not next hop
        # Should track the move target
        assert env._hero_move_targets["Max"] == 3

    def test_open_door_action(self):
        env = _make_env_with_state(_base_state())
        # Hero 0 (Max) is in room 0, open door to room 2
        cmd, params = env._translate_action(StrategicOption.OPEN_DOOR, 2, 0, 0)
        assert cmd == "OPEN_DOOR"
        assert params["hero_name"] == "Max"
        assert params["from_room_index"] == 0
        assert params["target_room_index"] == 2

    def test_level_up_hero_action(self):
        env = _make_env_with_state(_base_state())
        cmd, params = env._translate_action(StrategicOption.LEVEL_UP_HERO, 0, 1, 0)
        assert cmd == "LEVEL_UP_HERO"
        assert params["hero_name"] == "Gork"  # hero_target=1

    def test_heal_hero_action(self):
        env = _make_env_with_state(_base_state())
        cmd, params = env._translate_action(StrategicOption.HEAL_HERO, 0, 0, 0)
        assert cmd == "HEAL_HERO"
        assert params["hero_name"] == "Max"
        assert params["food_amount"] >= 1

    def test_research_action(self):
        state = _base_state(researchable_blueprints=[{"name": "BP_Test", "science_cost": 10}])
        env = _make_env_with_state(state)
        cmd, params = env._translate_action(StrategicOption.RESEARCH, 0, 0, 0)
        assert cmd == "RESEARCH"
        assert params["blueprint_name"] == "BP_Test"

    def test_initiate_escape_action(self):
        env = _make_env_with_state(_base_state())
        cmd, params = env._translate_action(StrategicOption.INITIATE_ESCAPE, 0, 0, 0)
        assert cmd == "PICK_UP_CRYSTAL"
        assert params["hero_name"] == "Max"

    def test_dismiss_hero_action(self):
        env = _make_env_with_state(_base_state())
        cmd, params = env._translate_action(StrategicOption.DISMISS_HERO, 0, 1, 0)
        assert cmd == "DISMISS_HERO"
        assert params["hero_name"] == "Gork"


# ---------------------------------------------------------------------------
# Movement Tracking
# ---------------------------------------------------------------------------


class TestMovementTracking:
    def test_move_target_cleared_on_arrival(self):
        env = _make_env_with_state(_base_state())
        env._hero_move_targets["Max"] = 2
        # Simulate Max arriving at room 2
        env._current_state.heroes[0].room_index = 2
        env._update_move_targets()
        assert "Max" not in env._hero_move_targets

    def test_move_target_persists_while_in_transit(self):
        env = _make_env_with_state(_base_state())
        env._hero_move_targets["Max"] = 3
        # Max still in room 0 (in transit)
        env._update_move_targets()
        assert "Max" in env._hero_move_targets
        assert env._hero_move_targets["Max"] == 3

    def test_hero_busy_flag_in_observation(self):
        """Heroes with active move targets should show is_busy=1 in features."""
        env = _make_env_with_state(_base_state())
        env._hero_move_targets["Max"] = 3
        obs = env._build_observation(env._current_state)
        hf = obs["hero_features"]
        assert hf[0, 5] == 1.0  # Max is busy
        assert hf[1, 5] == 0.0  # Gork is not busy


# ---------------------------------------------------------------------------
# Action Space
# ---------------------------------------------------------------------------


class TestActionSpace:
    def test_action_space_keys(self):
        with patch("rl_env.IpcClient"):
            env = RLEnv()
        assert set(env.action_space.spaces.keys()) == {"option", "room_target", "hero_target", "entity_target"}

    def test_action_space_ranges(self):
        with patch("rl_env.IpcClient"):
            env = RLEnv()
        assert env.action_space["option"].n == NUM_OPTIONS
        assert env.action_space["room_target"].n == MAX_ROOMS
        assert env.action_space["hero_target"].n == MAX_HEROES
        assert env.action_space["entity_target"].n == MAX_MODULES


# ---------------------------------------------------------------------------
# Observation conforms to observation_space
# ---------------------------------------------------------------------------


class TestObservationConformance:
    def test_observation_conforms_to_space(self):
        env = _make_env_with_state(_base_state())
        obs = env._build_observation(env._current_state)
        # Check each key is within bounds
        for key, space in env.observation_space.spaces.items():
            assert key in obs, f"Missing key: {key}"
            assert obs[key].shape == space.shape, f"Shape mismatch for {key}: {obs[key].shape} vs {space.shape}"
            assert obs[key].dtype == space.dtype, f"Dtype mismatch for {key}: {obs[key].dtype} vs {space.dtype}"

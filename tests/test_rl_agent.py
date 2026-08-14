"""
Unit tests for rl_agent.py, ppo_trainer.py, curriculum.py, micro_controller.py, escape_controller.py.
"""

import sys
from pathlib import Path

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "agent"))

from action_masking import NUM_OPTIONS, StrategicOption
from curriculum import CurriculumManager
from escape_controller import EscapeControllerNetwork, NUM_ESCAPE_ACTIONS
from micro_controller import MicroControllerNetwork, NUM_COMBAT_ACTIONS
from networks import PolicyNetwork
from ppo_trainer import PPOTrainer, RolloutBuffer
from rl_agent import RLAgent
from rl_config import CurriculumConfig, CurriculumStage, PPOConfig, RLConfig
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
)
from state_parser import GameStatePayload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dummy_obs(batch_size: int = 1) -> dict[str, torch.Tensor]:
    return {
        "adjacency": torch.zeros(batch_size, MAX_ROOMS, MAX_ROOMS, dtype=torch.int8),
        "door_state": torch.zeros(batch_size, MAX_ROOMS, MAX_ROOMS, dtype=torch.int8),
        "power_state": torch.zeros(batch_size, MAX_ROOMS, dtype=torch.int8),
        "power_reachable": torch.zeros(batch_size, MAX_ROOMS, dtype=torch.int8),
        "room_features": torch.randn(batch_size, MAX_ROOMS, ROOM_FEATURE_DIM),
        "hero_features": torch.randn(batch_size, MAX_HEROES, HERO_FEATURE_DIM),
        "mob_features": torch.full((batch_size, MAX_MOBS, MOB_FEATURE_DIM), -1.0),
        "resources": torch.randn(batch_size, RESOURCE_DIM),
        "game_meta": torch.randn(batch_size, GAME_META_DIM),
        "action_mask": torch.ones(batch_size, NUM_OPTIONS, dtype=torch.int8),
    }


def _base_state(**overrides) -> GameStatePayload:
    defaults = {
        "turn": 3, "floor": 1, "game_phase": "Strategy",
        "crystal_state": "Plugged", "exit_room_index": 3, "start_room_index": 0,
        "resources": {"industry": 50, "food": 30, "science": 20, "dust": 5, "dust_max": 10,
                      "industry_per_turn": 5, "food_per_turn": 3, "science_per_turn": 2,
                      "dust_per_turn": 0, "room_power_cost": 1, "powered_room_count": 2},
        "rooms": [
            {"index": 0, "is_powered": True, "is_auto_powered": True, "is_start_room": True,
             "adjacent_room_indices": [1], "minor_slot_count": 2, "is_fully_opened": True},
            {"index": 1, "is_powered": True, "is_auto_powered": False,
             "adjacent_room_indices": [0, 2], "minor_slot_count": 3, "is_fully_opened": True},
            {"index": 2, "is_powered": False, "adjacent_room_indices": [1, 3], "minor_slot_count": 2,
             "is_fully_opened": True},
            {"index": 3, "is_powered": False, "is_exit_room": True,
             "adjacent_room_indices": [2], "minor_slot_count": 2, "is_fully_opened": True},
        ],
        "closed_doors": [],
        "heroes": [
            {"name": "Max", "room_index": 0, "hp": 100, "max_hp": 100, "level": 2,
             "faction": "Prisoner", "is_usable": True,
             "passive_skills": [{"name": "Operate"}], "equipment": []},
            {"name": "Gork", "room_index": 1, "hp": 80, "max_hp": 100, "level": 1,
             "faction": "Native", "is_usable": True, "equipment": []},
        ],
        "mobs": [], "merchants": [], "recruitable_heroes": [],
        "dropped_items": [], "researchable_blueprints": [], "buildable_blueprints": [],
    }
    defaults.update(overrides)
    return GameStatePayload.model_validate(defaults)


# ---------------------------------------------------------------------------
# Micro-Controller
# ---------------------------------------------------------------------------


class TestMicroController:
    def test_forward_shapes(self):
        net = MicroControllerNetwork()
        obs = _dummy_obs(batch_size=3)
        value, action_dist, room_dist, hero_dist = net(obs)
        assert value.shape == (3,)
        assert action_dist.sample().shape == (3,)
        assert room_dist.sample().shape == (3,)

    def test_act_output(self):
        net = MicroControllerNetwork()
        obs = _dummy_obs(batch_size=2)
        action_dict, log_prob, value = net.act(obs)
        assert action_dict["combat_action"].shape == (2,)
        assert log_prob.shape == (2,)
        assert value.shape == (2,)


# ---------------------------------------------------------------------------
# Escape Controller
# ---------------------------------------------------------------------------


class TestEscapeController:
    def test_forward_shapes(self):
        net = EscapeControllerNetwork()
        obs = _dummy_obs(batch_size=2)
        value, action_dist, room_dist, hero_dist = net(obs)
        assert value.shape == (2,)
        assert action_dist.sample().shape == (2,)

    def test_act_output(self):
        net = EscapeControllerNetwork()
        obs = _dummy_obs(batch_size=1)
        action_dict, log_prob, value = net.act(obs)
        assert "escape_action" in action_dict
        assert action_dict["escape_action"].shape == (1,)


# ---------------------------------------------------------------------------
# RLAgent
# ---------------------------------------------------------------------------


class TestRLAgent:
    def test_select_action_returns_dict_or_none(self):
        agent = RLAgent()
        state = _base_state()
        action = agent.select_action(state)
        # Should return a dict with command/parameters or None
        if action is not None:
            assert "command" in action
            assert "parameters" in action

    def test_select_action_game_over_returns_none(self):
        agent = RLAgent()
        state = _base_state(crystal_state="Unplugged", is_level_over=True)
        for h in state.heroes:
            h.has_crystal = False
        action = agent.select_action(state)
        assert action is None

    def test_reset_clears_state(self):
        agent = RLAgent()
        agent._escape_initiated = True
        agent._crystal_carrier = "Max"
        agent.reset()
        assert agent._escape_initiated is False
        assert agent._crystal_carrier is None

    def test_combat_phase_uses_micro_controller(self):
        agent = RLAgent()
        state = _base_state(game_phase="Action")
        # Should use micro_controller (returns None or a move/heal command)
        action = agent.select_action(state)
        if action is not None:
            assert action["command"] in ("MOVE_HERO", "HEAL_HERO")

    def test_escape_phase_uses_escape_controller(self):
        agent = RLAgent()
        agent._escape_initiated = True
        state = _base_state()
        action = agent.select_action(state)
        # Escape controller produces escape-related commands or None
        if action is not None:
            assert action["command"] in (
                "PICK_UP_CRYSTAL", "POWER_ROOM", "UNPOWER_ROOM",
                "MOVE_HERO", "PLUG_CRYSTAL_EXIT"
            )

    def test_checkpoint_save_load(self, tmp_path):
        agent = RLAgent()
        path = tmp_path / "test_checkpoint.pt"
        agent.save_checkpoint(path)
        assert path.exists()

        # Load into new agent
        agent2 = RLAgent()
        agent2.load_checkpoint(path)
        # Verify weights match
        for p1, p2 in zip(agent.policy_net.parameters(), agent2.policy_net.parameters()):
            assert torch.equal(p1, p2)


# ---------------------------------------------------------------------------
# RolloutBuffer
# ---------------------------------------------------------------------------


class TestRolloutBuffer:
    def test_add_and_size(self):
        buffer = RolloutBuffer(capacity=100)
        obs = _dummy_obs(batch_size=1)
        action = {"option": torch.tensor(0), "room_target": torch.tensor(1),
                  "hero_target": torch.tensor(0), "entity_target": torch.tensor(0)}
        buffer.add(obs, action, torch.tensor(0.5), torch.tensor(1.0), 1.0, False)
        assert buffer.size == 1

    def test_compute_advantages(self):
        buffer = RolloutBuffer(capacity=10)
        obs = _dummy_obs(batch_size=1)
        action = {"option": torch.tensor(0), "room_target": torch.tensor(0),
                  "hero_target": torch.tensor(0), "entity_target": torch.tensor(0)}
        # Add 5 transitions
        for i in range(5):
            buffer.add(obs, action, torch.tensor(-1.0), torch.tensor(0.0), 1.0, False)
        buffer.compute_advantages(last_value=0.0, gamma=0.99, gae_lambda=0.95)
        # Advantages should be computed (non-zero for positive rewards)
        assert buffer.advantages[:5].abs().sum() > 0

    def test_get_batches(self):
        buffer = RolloutBuffer(capacity=20)
        obs = _dummy_obs(batch_size=1)
        action = {"option": torch.tensor(0), "room_target": torch.tensor(0),
                  "hero_target": torch.tensor(0), "entity_target": torch.tensor(0)}
        for i in range(20):
            buffer.add(obs, action, torch.tensor(-1.0), torch.tensor(0.0), 1.0, i == 19)
        buffer.compute_advantages(last_value=0.0)
        batches = buffer.get_batches(batch_size=8)
        assert len(batches) == 3  # 20/8 = 2.5 → 3 batches
        # Each batch has correct keys
        assert "obs" in batches[0]
        assert "actions" in batches[0]
        assert "advantages" in batches[0]

    def test_reset(self):
        buffer = RolloutBuffer(capacity=10)
        obs = _dummy_obs(batch_size=1)
        action = {"option": torch.tensor(0), "room_target": torch.tensor(0),
                  "hero_target": torch.tensor(0), "entity_target": torch.tensor(0)}
        buffer.add(obs, action, torch.tensor(0.0), torch.tensor(0.0), 0.0, False)
        assert buffer.size == 1
        buffer.reset()
        assert buffer.size == 0


# ---------------------------------------------------------------------------
# PPOTrainer
# ---------------------------------------------------------------------------


class TestPPOTrainer:
    def test_update_runs_without_error(self):
        net = PolicyNetwork()
        config = PPOConfig(num_epochs=2, batch_size=4, rollout_steps=8)
        trainer = PPOTrainer(net, config)
        buffer = RolloutBuffer(capacity=8)

        obs = _dummy_obs(batch_size=1)
        action = {"option": torch.tensor(0), "room_target": torch.tensor(0),
                  "hero_target": torch.tensor(0), "entity_target": torch.tensor(0)}
        for i in range(8):
            buffer.add(obs, action, torch.tensor(-2.0), torch.tensor(0.5), 1.0, i == 7)

        buffer.compute_advantages(last_value=0.0)
        metrics = trainer.update(buffer)

        assert "policy_loss" in metrics
        assert "value_loss" in metrics
        assert "entropy" in metrics
        assert metrics["num_updates"] > 0

    def test_optimizer_updates_weights(self):
        net = PolicyNetwork()
        trainer = PPOTrainer(net, PPOConfig(num_epochs=1, batch_size=4))
        buffer = RolloutBuffer(capacity=4)

        obs = _dummy_obs(batch_size=1)
        action = {"option": torch.tensor(1), "room_target": torch.tensor(2),
                  "hero_target": torch.tensor(0), "entity_target": torch.tensor(0)}
        for i in range(4):
            buffer.add(obs, action, torch.tensor(-1.0), torch.tensor(1.0), 5.0, i == 3)

        # Save initial weights
        initial_param = next(net.parameters()).clone()
        buffer.compute_advantages(last_value=0.0)
        trainer.update(buffer)
        # Weights should have changed
        updated_param = next(net.parameters())
        assert not torch.equal(initial_param, updated_param)


# ---------------------------------------------------------------------------
# CurriculumManager
# ---------------------------------------------------------------------------


class TestCurriculumManager:
    def test_starts_at_stage_0(self):
        cm = CurriculumManager()
        assert cm.stage_index == 0
        assert cm.stage_name == "floor_1_survival"

    def test_records_episodes(self):
        cm = CurriculumManager()
        cm.record_episode(True)
        cm.record_episode(False)
        assert cm.total_episodes == 2
        assert cm.episodes_in_stage == 2
        assert cm.success_rate == 0.5

    def test_advances_when_threshold_met(self):
        config = CurriculumConfig(stages=[
            CurriculumStage(name="stage1", min_episodes=5, success_threshold=0.6),
            CurriculumStage(name="stage2", min_episodes=5, success_threshold=0.8),
        ])
        cm = CurriculumManager(config)
        # Record enough successes to advance
        for _ in range(50):
            cm.record_episode(True)
        # Should have advanced by now (50 episodes, 100% success > 0.6 threshold)
        assert cm.stage_index == 1
        assert cm.stage_name == "stage2"

    def test_does_not_advance_from_last_stage(self):
        config = CurriculumConfig(stages=[
            CurriculumStage(name="only_stage", min_episodes=1, success_threshold=1.0),
        ])
        cm = CurriculumManager(config)
        for _ in range(100):
            cm.record_episode(True)
        assert cm.stage_index == 0  # Can't advance past last

    def test_force_stage(self):
        cm = CurriculumManager()
        cm.force_stage(2)
        assert cm.stage_index == 2
        assert cm.stage_name == "full_game"

    def test_get_metrics(self):
        cm = CurriculumManager()
        cm.record_episode(True)
        metrics = cm.get_metrics()
        assert "curriculum/stage_name" in metrics
        assert metrics["curriculum/total_episodes"] == 1

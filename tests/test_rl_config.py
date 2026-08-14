"""
Unit tests for rl_config.py — RL training configuration loading and defaults.
"""

import sys
import tempfile
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "agent"))

from rl_config import (
    CoreRewardWeights,
    CurriculumConfig,
    CurriculumStage,
    GuidelineRewardWeights,
    NetworkConfig,
    PPOConfig,
    RewardConfig,
    RLConfig,
    TrainingConfig,
)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_ppo_defaults(self):
        cfg = PPOConfig()
        assert cfg.learning_rate == 3e-4
        assert cfg.gamma == 0.99
        assert cfg.gae_lambda == 0.95
        assert cfg.clip_ratio == 0.2
        assert cfg.num_epochs == 4
        assert cfg.batch_size == 64
        assert cfg.rollout_steps == 2048

    def test_network_defaults(self):
        cfg = NetworkConfig()
        assert cfg.shared_embedding_dim == 512
        assert cfg.graph_encoder_hidden == 256
        assert cfg.activation == "relu"

    def test_core_reward_defaults(self):
        cfg = CoreRewardWeights()
        assert cfg.floor_escaped == 200.0
        assert cfg.game_over == -200.0
        assert cfg.invalid_action == -1.0

    def test_guideline_reward_defaults_all_enabled(self):
        cfg = GuidelineRewardWeights()
        assert cfg.enabled_power is True
        assert cfg.enabled_operate is True
        assert cfg.enabled_escape is True
        assert cfg.enabled_combat is True
        assert cfg.enabled_equipment is True
        assert cfg.enabled_recruit is True
        assert cfg.enabled_industry is True

    def test_curriculum_has_4_stages(self):
        cfg = CurriculumConfig()
        assert len(cfg.stages) == 4
        assert cfg.stages[0].name == "floor_1_survival"
        assert cfg.stages[1].name == "multi_floor"
        assert cfg.stages[2].name == "full_game"
        assert cfg.stages[3].name == "mastery"

    def test_full_config_defaults(self):
        cfg = RLConfig()
        assert isinstance(cfg.ppo, PPOConfig)
        assert isinstance(cfg.network, NetworkConfig)
        assert isinstance(cfg.rewards, RewardConfig)
        assert isinstance(cfg.curriculum, CurriculumConfig)
        assert isinstance(cfg.training, TrainingConfig)


# ---------------------------------------------------------------------------
# From dict (partial overrides)
# ---------------------------------------------------------------------------


class TestFromDict:
    def test_empty_dict_gives_defaults(self):
        cfg = RLConfig.from_dict({})
        assert cfg.ppo.learning_rate == 3e-4
        assert cfg.rewards.core.floor_escaped == 200.0

    def test_partial_override_ppo(self):
        cfg = RLConfig.from_dict({"ppo": {"learning_rate": 1e-3, "gamma": 0.95}})
        assert cfg.ppo.learning_rate == 1e-3
        assert cfg.ppo.gamma == 0.95
        # Others stay default
        assert cfg.ppo.clip_ratio == 0.2

    def test_partial_override_rewards(self):
        cfg = RLConfig.from_dict({
            "rewards": {
                "core": {"floor_escaped": 500.0},
                "guidelines": {"enabled_power": False, "power_chain_broken": -10.0},
            }
        })
        assert cfg.rewards.core.floor_escaped == 500.0
        assert cfg.rewards.core.game_over == -200.0  # default
        assert cfg.rewards.guidelines.enabled_power is False
        assert cfg.rewards.guidelines.power_chain_broken == -10.0

    def test_partial_override_curriculum(self):
        cfg = RLConfig.from_dict({
            "curriculum": {
                "current_stage_index": 2,
                "stages": [
                    {"name": "custom_stage", "max_floors": 6, "success_threshold": 0.7},
                ],
            }
        })
        assert cfg.curriculum.current_stage_index == 2
        assert len(cfg.curriculum.stages) == 1
        assert cfg.curriculum.stages[0].name == "custom_stage"
        assert cfg.curriculum.stages[0].max_floors == 6

    def test_unknown_keys_ignored(self):
        cfg = RLConfig.from_dict({
            "ppo": {"unknown_key": 999, "learning_rate": 5e-4},
            "totally_unknown_section": {"foo": "bar"},
        })
        assert cfg.ppo.learning_rate == 5e-4


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


class TestFileIO:
    def test_save_and_load_yaml(self, tmp_path):
        original = RLConfig()
        original.ppo.learning_rate = 1e-5
        original.rewards.core.floor_escaped = 999.0

        yaml_path = tmp_path / "test_config.yaml"
        original.save(yaml_path)

        loaded = RLConfig.from_file(yaml_path)
        assert loaded.ppo.learning_rate == 1e-5
        assert loaded.rewards.core.floor_escaped == 999.0
        # Check non-modified fields preserved
        assert loaded.ppo.gamma == 0.99
        assert loaded.network.shared_embedding_dim == 512

    def test_load_json(self, tmp_path):
        import json as json_mod

        data = {
            "ppo": {"learning_rate": 2e-4},
            "training": {"max_episodes": 500},
        }
        json_path = tmp_path / "config.json"
        json_path.write_text(json_mod.dumps(data), encoding="utf-8")

        cfg = RLConfig.from_file(json_path)
        assert cfg.ppo.learning_rate == 2e-4
        assert cfg.training.max_episodes == 500

    def test_load_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            RLConfig.from_file("/nonexistent/path/config.yaml")

    def test_to_dict_roundtrip(self):
        cfg = RLConfig()
        d = cfg.to_dict()
        assert isinstance(d, dict)
        assert "ppo" in d
        assert "rewards" in d
        assert d["ppo"]["learning_rate"] == 3e-4


# ---------------------------------------------------------------------------
# Curriculum Stage Properties
# ---------------------------------------------------------------------------


class TestCurriculumStage:
    def test_stage_defaults(self):
        stage = CurriculumStage()
        assert stage.max_floors == 1
        assert stage.success_threshold == 0.6
        assert stage.guideline_shaping_enabled is True
        assert stage.time_scale == 4.0
        assert stage.randomize_heroes is False

    def test_mastery_stage_never_advances(self):
        cfg = CurriculumConfig()
        mastery = cfg.stages[-1]
        assert mastery.success_threshold == 1.0  # Impossible to exceed
        assert mastery.name == "mastery"

    def test_stage_progression_max_floors_increases(self):
        cfg = CurriculumConfig()
        floors = [s.max_floors for s in cfg.stages]
        assert floors == [1, 4, 12, 12]

"""
RL Config: Training hyperparameters, reward weights, curriculum stage definitions.

All RL training configuration lives in a single YAML file. This module defines
the typed dataclass structure and provides loading/saving utilities.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


# ---------------------------------------------------------------------------
# Reward Weight Configuration
# ---------------------------------------------------------------------------


@dataclass
class CoreRewardWeights:
    """Reward weights that are always active (non-toggleable)."""

    floor_escaped: float = 200.0
    game_over: float = -200.0
    hero_died: float = -50.0
    room_explored: float = 5.0
    invalid_action: float = -1.0
    successful_action: float = 0.1
    wait_penalty: float = -0.05
    industry_built: float = 3.0
    module_built: float = 1.5
    research_completed: float = 4.0
    item_equipped: float = 1.0
    dust_collected_per_unit: float = 0.5
    floor_progress_scale: float = 100.0  # Multiplied by (floor / 12)
    production_per_turn_scale: float = 0.1  # Multiplied by (ind + food + sci per turn)


@dataclass
class GuidelineRewardWeights:
    """Toggle-able reward shaping terms based on game guidelines."""

    # GL-POWER: Power chain awareness
    power_chain_broken: float = -3.0
    power_chain_optimal: float = 1.0
    enabled_power: bool = True

    # GL-OPERATE: Operate bonus awareness
    operator_placed: float = 2.0
    operator_interrupted: float = -2.0
    enabled_operate: bool = True

    # GL-ESCAPE: Escape timing
    escape_all_doors_open: float = 5.0
    escape_early_but_safe: float = 2.0
    overstayed: float = -10.0
    enabled_escape: bool = True

    # GL-COMBAT: Combat positioning
    spawn_blocked: float = 2.0
    hero_took_heavy_damage: float = -1.0
    hero_healed_wisely: float = 0.5
    enabled_combat: bool = True

    # GL-EQUIPMENT: Equipment matching
    weapon_class_match: float = 2.0
    weapon_class_mismatch: float = -1.0
    enabled_equipment: bool = True

    # GL-RECRUIT: Recruitment decisions
    recruited_useful_hero: float = 30.0
    dismissed_for_upgrade: float = 10.0
    enabled_recruit: bool = True

    # GL-INDUSTRY: Cross-floor resource planning
    floor_exit_industry_scale: float = 5.0  # Multiplied by (industry / 100)
    enabled_industry: bool = True


@dataclass
class RewardConfig:
    """Combined reward configuration."""

    core: CoreRewardWeights = field(default_factory=CoreRewardWeights)
    guidelines: GuidelineRewardWeights = field(default_factory=GuidelineRewardWeights)


# ---------------------------------------------------------------------------
# Training Hyperparameters
# ---------------------------------------------------------------------------


@dataclass
class PPOConfig:
    """PPO algorithm hyperparameters."""

    learning_rate: float = 3e-4
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_ratio: float = 0.2
    value_loss_coef: float = 0.5
    entropy_coef: float = 0.01
    max_grad_norm: float = 0.5
    num_epochs: int = 4
    batch_size: int = 64
    rollout_steps: int = 2048  # Steps per rollout before update
    normalize_advantages: bool = True


@dataclass
class NetworkConfig:
    """Neural network architecture parameters."""

    shared_embedding_dim: int = 512
    graph_encoder_hidden: int = 256
    entity_encoder_hidden: int = 256
    param_head_hidden: int = 128
    value_head_hidden: int = 256
    micro_controller_hidden: int = 128
    escape_controller_hidden: int = 128
    activation: str = "relu"  # "relu", "tanh", "gelu"


# ---------------------------------------------------------------------------
# Curriculum Configuration
# ---------------------------------------------------------------------------


@dataclass
class CurriculumStage:
    """A single curriculum training stage."""

    name: str = ""
    max_floors: int = 1  # Max floors per episode (1 = Floor 1 only)
    success_threshold: float = 0.6  # Advance when success rate exceeds this
    min_episodes: int = 100  # Minimum episodes before considering advancement
    guideline_shaping_enabled: bool = True  # Whether GL rewards are active
    time_scale: float = 4.0  # Game speed multiplier for training
    randomize_heroes: bool = False  # Randomize starting hero selection


@dataclass
class CurriculumConfig:
    """Curriculum learning configuration."""

    stages: list[CurriculumStage] = field(default_factory=lambda: [
        CurriculumStage(
            name="floor_1_survival",
            max_floors=1,
            success_threshold=0.6,
            min_episodes=100,
            guideline_shaping_enabled=True,
            time_scale=4.0,
            randomize_heroes=False,
        ),
        CurriculumStage(
            name="multi_floor",
            max_floors=4,
            success_threshold=0.5,
            min_episodes=500,
            guideline_shaping_enabled=True,
            time_scale=4.0,
            randomize_heroes=False,
        ),
        CurriculumStage(
            name="full_game",
            max_floors=12,
            success_threshold=0.3,
            min_episodes=1000,
            guideline_shaping_enabled=False,
            time_scale=4.0,
            randomize_heroes=True,
        ),
        CurriculumStage(
            name="mastery",
            max_floors=12,
            success_threshold=1.0,  # Never auto-advance (final stage)
            min_episodes=0,
            guideline_shaping_enabled=False,
            time_scale=8.0,
            randomize_heroes=True,
        ),
    ])
    current_stage_index: int = 0


# ---------------------------------------------------------------------------
# Training Run Configuration
# ---------------------------------------------------------------------------


@dataclass
class TrainingConfig:
    """Top-level configuration for an RL training run."""

    # Episode / run management
    max_episodes: int = 10000
    eval_interval: int = 50  # Evaluate every N episodes
    checkpoint_interval: int = 100  # Save checkpoint every N episodes
    log_interval: int = 10  # Log metrics every N episodes

    # Game settings
    difficulty: str = "easy"
    default_heroes: list[str] = field(
        default_factory=lambda: ["Hero_H0001", "Hero_H0003"]
    )
    ship: str = "Pod"

    # Paths
    checkpoint_dir: str = "checkpoints"
    log_dir: str = "logs/rl"
    metrics_dir: str = "metrics/rl"


# ---------------------------------------------------------------------------
# Top-Level RL Config
# ---------------------------------------------------------------------------


@dataclass
class RLConfig:
    """Complete RL training configuration. Load from YAML."""

    ppo: PPOConfig = field(default_factory=PPOConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    rewards: RewardConfig = field(default_factory=RewardConfig)
    curriculum: CurriculumConfig = field(default_factory=CurriculumConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)

    @classmethod
    def from_file(cls, path: str | Path) -> "RLConfig":
        """
        Load configuration from a YAML or JSON file.

        Unknown keys are silently ignored; missing keys use defaults.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"RL config not found: {path}")

        text = path.read_text(encoding="utf-8")

        if path.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(text) or {}
        elif path.suffix == ".json":
            data = json.loads(text)
        else:
            try:
                data = yaml.safe_load(text) or {}
            except yaml.YAMLError:
                data = json.loads(text)

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "RLConfig":
        """Create config from a (possibly partial) dict."""
        ppo_data = data.get("ppo", {})
        network_data = data.get("network", {})
        rewards_data = data.get("rewards", {})
        curriculum_data = data.get("curriculum", {})
        training_data = data.get("training", {})

        # Build nested reward config
        reward_cfg = RewardConfig(
            core=_build_dataclass(CoreRewardWeights, rewards_data.get("core", {})),
            guidelines=_build_dataclass(
                GuidelineRewardWeights, rewards_data.get("guidelines", {})
            ),
        )

        # Build curriculum stages
        curriculum_cfg = CurriculumConfig()
        if "stages" in curriculum_data:
            curriculum_cfg.stages = [
                _build_dataclass(CurriculumStage, s)
                for s in curriculum_data["stages"]
            ]
        if "current_stage_index" in curriculum_data:
            curriculum_cfg.current_stage_index = curriculum_data["current_stage_index"]

        return cls(
            ppo=_build_dataclass(PPOConfig, ppo_data),
            network=_build_dataclass(NetworkConfig, network_data),
            rewards=reward_cfg,
            curriculum=curriculum_cfg,
            training=_build_dataclass(TrainingConfig, training_data),
        )

    def to_dict(self) -> dict:
        """Serialize to a dict for saving."""
        from dataclasses import asdict
        return asdict(self)

    def save(self, path: str | Path) -> None:
        """Save configuration to a YAML file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()
        path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_dataclass(cls, data: dict):
    """Construct a dataclass from a dict, ignoring unknown keys."""
    if not data:
        return cls()
    valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    return cls(**filtered)

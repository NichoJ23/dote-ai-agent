"""
Curriculum Manager: Tracks training progress and auto-advances stages.

Stages progress from simple (Floor 1 only) to complex (full game, no shaping).
Advancement happens when the agent achieves the success threshold for the
minimum number of episodes.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Optional

from rl_config import CurriculumConfig, CurriculumStage

logger = logging.getLogger(__name__)


class CurriculumManager:
    """
    Manages curriculum training stages.

    Tracks episode outcomes and automatically advances to the next stage
    when the success rate exceeds the threshold for the minimum episode count.
    """

    def __init__(self, config: Optional[CurriculumConfig] = None):
        self.config = config or CurriculumConfig()
        self._stage_idx = self.config.current_stage_index
        self._episode_outcomes: deque[bool] = deque(maxlen=200)
        self._total_episodes = 0
        self._episodes_in_stage = 0

    @property
    def current_stage(self) -> CurriculumStage:
        """Get the current curriculum stage."""
        return self.config.stages[self._stage_idx]

    @property
    def stage_index(self) -> int:
        """Current stage index."""
        return self._stage_idx

    @property
    def stage_name(self) -> str:
        """Current stage name."""
        return self.current_stage.name

    @property
    def max_floors(self) -> int:
        """Max floors for the current stage."""
        return self.current_stage.max_floors

    @property
    def guideline_shaping_enabled(self) -> bool:
        """Whether guideline reward shaping is active."""
        return self.current_stage.guideline_shaping_enabled

    @property
    def time_scale(self) -> float:
        """Game speed for current stage."""
        return self.current_stage.time_scale

    @property
    def randomize_heroes(self) -> bool:
        """Whether to randomize starting heroes."""
        return self.current_stage.randomize_heroes

    @property
    def success_rate(self) -> float:
        """Current rolling success rate."""
        if not self._episode_outcomes:
            return 0.0
        return sum(self._episode_outcomes) / len(self._episode_outcomes)

    @property
    def total_episodes(self) -> int:
        """Total episodes across all stages."""
        return self._total_episodes

    @property
    def episodes_in_stage(self) -> int:
        """Episodes completed in current stage."""
        return self._episodes_in_stage

    def record_episode(self, success: bool) -> bool:
        """
        Record an episode outcome and check for stage advancement.

        Args:
            success: Whether the episode was successful (escaped the target floor).

        Returns:
            True if the stage was advanced.
        """
        self._episode_outcomes.append(success)
        self._total_episodes += 1
        self._episodes_in_stage += 1

        # Check for advancement
        if self._should_advance():
            self._advance_stage()
            return True

        return False

    def _should_advance(self) -> bool:
        """Check if we should advance to the next stage."""
        stage = self.current_stage

        # Don't advance from the last stage
        if self._stage_idx >= len(self.config.stages) - 1:
            return False

        # Need minimum episodes in this stage
        if self._episodes_in_stage < stage.min_episodes:
            return False

        # Need sufficient success rate
        if self.success_rate < stage.success_threshold:
            return False

        # Need enough data points for a reliable estimate
        if len(self._episode_outcomes) < min(50, stage.min_episodes):
            return False

        return True

    def _advance_stage(self) -> None:
        """Advance to the next curriculum stage."""
        old_name = self.current_stage.name
        self._stage_idx += 1
        self._episodes_in_stage = 0
        self._episode_outcomes.clear()
        new_name = self.current_stage.name
        logger.info(
            f"Curriculum advanced: {old_name} → {new_name} "
            f"(total episodes: {self._total_episodes})"
        )

    def force_stage(self, stage_index: int) -> None:
        """Manually set the curriculum stage."""
        if 0 <= stage_index < len(self.config.stages):
            self._stage_idx = stage_index
            self._episodes_in_stage = 0
            self._episode_outcomes.clear()
            logger.info(f"Curriculum forced to stage: {self.current_stage.name}")

    def get_metrics(self) -> dict:
        """Get curriculum metrics for logging."""
        return {
            "curriculum/stage_index": self._stage_idx,
            "curriculum/stage_name": self.stage_name,
            "curriculum/success_rate": self.success_rate,
            "curriculum/episodes_in_stage": self._episodes_in_stage,
            "curriculum/total_episodes": self._total_episodes,
            "curriculum/max_floors": self.max_floors,
            "curriculum/guideline_shaping": self.guideline_shaping_enabled,
        }

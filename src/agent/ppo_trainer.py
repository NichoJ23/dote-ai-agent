"""
PPO Trainer: Proximal Policy Optimization training loop with rollout buffer.

Based on the CleanRL PPO pattern:
  1. Collect rollout (on-policy)
  2. Compute advantages (GAE)
  3. PPO clipped surrogate loss
  4. Multiple epochs over minibatches
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

from action_masking import NUM_OPTIONS
from networks import PolicyNetwork
from rl_config import PPOConfig, RLConfig
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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rollout Buffer
# ---------------------------------------------------------------------------


class RolloutBuffer:
    """
    On-policy rollout buffer for PPO.

    Stores transitions from a single rollout, then computes advantages
    and returns for training.
    """

    def __init__(self, capacity: int = 2048, device: str = "cpu"):
        self.capacity = capacity
        self.device = torch.device(device)
        self.pos = 0
        self.full = False

        # Observation storage (flattened for simplicity)
        self.obs_keys = [
            "adjacency", "door_state", "power_state", "power_reachable",
            "room_features", "hero_features", "mob_features",
            "resources", "game_meta", "action_mask",
        ]
        self.obs_buffers: dict[str, torch.Tensor] = {}

        # Action storage
        self.options = torch.zeros(capacity, dtype=torch.long, device=self.device)
        self.room_targets = torch.zeros(capacity, dtype=torch.long, device=self.device)
        self.hero_targets = torch.zeros(capacity, dtype=torch.long, device=self.device)
        self.entity_targets = torch.zeros(capacity, dtype=torch.long, device=self.device)

        # Scalar storage
        self.log_probs = torch.zeros(capacity, device=self.device)
        self.values = torch.zeros(capacity, device=self.device)
        self.rewards = torch.zeros(capacity, device=self.device)
        self.dones = torch.zeros(capacity, device=self.device)

        # Computed during flush
        self.advantages = torch.zeros(capacity, device=self.device)
        self.returns = torch.zeros(capacity, device=self.device)

        self._initialized = False

    def _init_obs_buffers(self, obs: dict[str, torch.Tensor]) -> None:
        """Initialize observation buffers from first observation."""
        for key in self.obs_keys:
            shape = obs[key].shape[1:]  # Remove batch dim
            self.obs_buffers[key] = torch.zeros(
                (self.capacity, *shape), dtype=obs[key].dtype, device=self.device
            )
        self._initialized = True

    def add(
        self,
        obs: dict[str, torch.Tensor],
        action: dict[str, torch.Tensor],
        log_prob: torch.Tensor,
        value: torch.Tensor,
        reward: float,
        done: bool,
    ) -> None:
        """Add a single transition to the buffer."""
        if not self._initialized:
            self._init_obs_buffers(obs)

        idx = self.pos

        # Store observation (remove batch dim)
        for key in self.obs_keys:
            self.obs_buffers[key][idx] = obs[key].squeeze(0)

        # Store action
        self.options[idx] = action["option"].item() if isinstance(action["option"], torch.Tensor) else action["option"]
        self.room_targets[idx] = action["room_target"].item() if isinstance(action["room_target"], torch.Tensor) else action["room_target"]
        self.hero_targets[idx] = action["hero_target"].item() if isinstance(action["hero_target"], torch.Tensor) else action["hero_target"]
        self.entity_targets[idx] = action["entity_target"].item() if isinstance(action["entity_target"], torch.Tensor) else action["entity_target"]

        # Store scalars
        self.log_probs[idx] = log_prob.item() if isinstance(log_prob, torch.Tensor) else log_prob
        self.values[idx] = value.item() if isinstance(value, torch.Tensor) else value
        self.rewards[idx] = reward
        self.dones[idx] = float(done)

        self.pos += 1
        if self.pos >= self.capacity:
            self.full = True
            self.pos = 0

    @property
    def size(self) -> int:
        """Number of transitions stored."""
        return self.capacity if self.full else self.pos

    def compute_advantages(
        self,
        last_value: float,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
    ) -> None:
        """
        Compute GAE advantages and returns.

        Args:
            last_value: V(s_T+1) for bootstrapping.
            gamma: Discount factor.
            gae_lambda: GAE lambda.
        """
        size = self.size
        last_gae = 0.0

        for t in reversed(range(size)):
            if t == size - 1:
                next_value = last_value
                next_done = 0.0
            else:
                next_value = self.values[t + 1].item()
                next_done = self.dones[t + 1].item()

            delta = (
                self.rewards[t].item()
                + gamma * next_value * (1.0 - next_done)
                - self.values[t].item()
            )
            last_gae = delta + gamma * gae_lambda * (1.0 - next_done) * last_gae
            self.advantages[t] = last_gae

        self.returns[:size] = self.advantages[:size] + self.values[:size]

    def get_batches(self, batch_size: int) -> list[dict]:
        """
        Generate minibatches for PPO update.

        Returns:
            List of batch dicts, each containing obs, actions, old_log_probs,
            advantages, returns.
        """
        size = self.size
        indices = np.arange(size)
        np.random.shuffle(indices)

        batches = []
        for start in range(0, size, batch_size):
            end = min(start + batch_size, size)
            batch_indices = indices[start:end]
            batch_idx = torch.tensor(batch_indices, dtype=torch.long, device=self.device)

            batch = {
                "obs": {key: buf[batch_idx] for key, buf in self.obs_buffers.items()},
                "actions": {
                    "option": self.options[batch_idx],
                    "room_target": self.room_targets[batch_idx],
                    "hero_target": self.hero_targets[batch_idx],
                    "entity_target": self.entity_targets[batch_idx],
                },
                "old_log_probs": self.log_probs[batch_idx],
                "advantages": self.advantages[batch_idx],
                "returns": self.returns[batch_idx],
            }
            batches.append(batch)

        return batches

    def reset(self) -> None:
        """Clear the buffer."""
        self.pos = 0
        self.full = False


# ---------------------------------------------------------------------------
# PPO Trainer
# ---------------------------------------------------------------------------


class PPOTrainer:
    """
    PPO training logic.

    Handles:
      - Optimization step (clipped surrogate + value loss + entropy bonus)
      - Multiple epochs over minibatches
      - Gradient clipping
      - Advantage normalization
    """

    def __init__(
        self,
        policy_net: PolicyNetwork,
        config: Optional[PPOConfig] = None,
        device: str = "cpu",
    ):
        self.policy_net = policy_net
        self.config = config or PPOConfig()
        self.device = torch.device(device)

        self.optimizer = optim.Adam(
            policy_net.parameters(),
            lr=self.config.learning_rate,
            eps=1e-5,
        )

        # Metrics from last update
        self.last_policy_loss = 0.0
        self.last_value_loss = 0.0
        self.last_entropy = 0.0
        self.last_total_loss = 0.0
        self.last_clip_fraction = 0.0

    def update(self, buffer: RolloutBuffer) -> dict[str, float]:
        """
        Perform a full PPO update over the rollout buffer.

        Args:
            buffer: Filled rollout buffer with computed advantages.

        Returns:
            Dict of training metrics.
        """
        total_policy_loss = 0.0
        total_value_loss = 0.0
        total_entropy = 0.0
        total_clip_frac = 0.0
        num_updates = 0

        for epoch in range(self.config.num_epochs):
            batches = buffer.get_batches(self.config.batch_size)

            for batch in batches:
                obs = batch["obs"]
                actions = batch["actions"]
                old_log_probs = batch["old_log_probs"]
                advantages = batch["advantages"]
                returns = batch["returns"]

                # Normalize advantages
                if self.config.normalize_advantages and len(advantages) > 1:
                    advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

                # Get action mask from obs
                action_mask = obs["action_mask"]

                # Evaluate actions
                new_log_probs, entropy, values = self.policy_net.evaluate_actions(
                    obs, action_mask, actions
                )

                # Policy loss (clipped surrogate)
                ratio = torch.exp(new_log_probs - old_log_probs)
                clip_ratio = self.config.clip_ratio
                surr1 = ratio * advantages
                surr2 = torch.clamp(ratio, 1.0 - clip_ratio, 1.0 + clip_ratio) * advantages
                policy_loss = -torch.min(surr1, surr2).mean()

                # Value loss
                value_loss = F.mse_loss(values, returns)

                # Entropy bonus
                entropy_loss = -entropy.mean()

                # Total loss
                loss = (
                    policy_loss
                    + self.config.value_loss_coef * value_loss
                    + self.config.entropy_coef * entropy_loss
                )

                # Optimize
                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(
                    self.policy_net.parameters(), self.config.max_grad_norm
                )
                self.optimizer.step()

                # Track metrics
                with torch.no_grad():
                    clip_frac = ((ratio - 1.0).abs() > clip_ratio).float().mean().item()

                total_policy_loss += policy_loss.item()
                total_value_loss += value_loss.item()
                total_entropy += entropy.mean().item()
                total_clip_frac += clip_frac
                num_updates += 1

        # Average metrics
        n = max(num_updates, 1)
        self.last_policy_loss = total_policy_loss / n
        self.last_value_loss = total_value_loss / n
        self.last_entropy = total_entropy / n
        self.last_total_loss = (total_policy_loss + total_value_loss) / n
        self.last_clip_fraction = total_clip_frac / n

        return {
            "policy_loss": self.last_policy_loss,
            "value_loss": self.last_value_loss,
            "entropy": self.last_entropy,
            "clip_fraction": self.last_clip_fraction,
            "num_updates": num_updates,
        }


# Need F for mse_loss
import torch.nn.functional as F

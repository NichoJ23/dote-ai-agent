"""
Micro-Controller: Action-phase combat policy network.

A smaller, separate policy that handles hero decisions during combat waves:
  - Reposition heroes to block spawns or fight mobs
  - Retreat critically wounded heroes
  - Emergency heal commands
  - Wait (let auto-combat resolve)
"""

from __future__ import annotations

from enum import IntEnum
from typing import Optional

import torch
import torch.nn as nn
from torch.distributions import Categorical

from rl_config import NetworkConfig
from rl_env import HERO_FEATURE_DIM, MAX_HEROES, MAX_ROOMS, ROOM_FEATURE_DIM


# ---------------------------------------------------------------------------
# Combat Actions
# ---------------------------------------------------------------------------


class CombatAction(IntEnum):
    """Actions available during combat."""
    REPOSITION_HERO = 0  # Move hero to a room
    HEAL_HERO = 1        # Emergency heal
    WAIT = 2             # Let auto-combat handle it


NUM_COMBAT_ACTIONS = len(CombatAction)


# ---------------------------------------------------------------------------
# Micro-Controller Network
# ---------------------------------------------------------------------------


class MicroControllerNetwork(nn.Module):
    """
    Lightweight policy network for Action phase decisions.

    Input: combat-specific observation (hero features + room features + mob counts)
    Output: per-hero action (reposition/heal/wait) + target room for repositioning
    """

    def __init__(self, config: Optional[NetworkConfig] = None):
        super().__init__()
        cfg = config or NetworkConfig()
        hidden = cfg.micro_controller_hidden

        # Input: hero_features (flattened) + room power/mob summary + resource snippet
        # Simplified input compared to full encoder
        input_size = MAX_HEROES * HERO_FEATURE_DIM + MAX_ROOMS * 3 + 4
        # Room summary: 3 features per room (is_powered, mob_count, hero_count)
        # Resource snippet: food, dust, num_mobs, is_spawning

        self.encoder = nn.Sequential(
            nn.Linear(input_size, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
        )

        # Action type head: per-hero action (reposition/heal/wait)
        self.action_head = nn.Sequential(
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, MAX_HEROES * NUM_COMBAT_ACTIONS),
        )

        # Room target head: which room to reposition to
        self.room_head = nn.Sequential(
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, MAX_ROOMS),
        )

        # Hero selection head: which hero to act on first
        self.hero_head = nn.Sequential(
            nn.Linear(hidden, MAX_HEROES),
        )

        # Value head for combat phase
        self.value_head = nn.Sequential(
            nn.Linear(hidden, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
        )

    def forward(
        self, obs: dict[str, torch.Tensor]
    ) -> tuple[torch.Tensor, Categorical, Categorical, Categorical]:
        """
        Forward pass for combat decisions.

        Args:
            obs: Dict with hero_features, room_features, resources, game_meta.

        Returns:
            (value, action_dist, room_dist, hero_dist)
        """
        batch_size = obs["hero_features"].shape[0]

        # Build compact input
        hero_flat = obs["hero_features"].reshape(batch_size, -1).float()

        # Room summary: extract (is_powered, mob_count, hero_count) per room
        room_feats = obs["room_features"].float()  # (batch, MAX_ROOMS, ROOM_FEAT_DIM)
        # Indices: 0=is_powered, 14=mob_count, 13=hero_count
        room_summary = room_feats[:, :, [0, 14, 13]].reshape(batch_size, -1)  # (batch, MAX_ROOMS*3)

        # Resource snippet
        resources = obs["resources"].float()  # (batch, RESOURCE_DIM)
        game_meta = obs["game_meta"].float()  # (batch, GAME_META_DIM)
        # food=idx1, dust=idx3, num_mobs=idx5(game_meta), spawning info
        resource_snippet = torch.cat([
            resources[:, 1:2],   # food
            resources[:, 3:4],   # dust
            game_meta[:, 5:6],   # num_mobs
            game_meta[:, 2:3],   # phase (should be 1 for action)
        ], dim=-1)  # (batch, 4)

        x = torch.cat([hero_flat, room_summary, resource_snippet], dim=-1)
        embedding = self.encoder(x)

        # Action distribution (per-hero, flattened)
        action_logits = self.action_head(embedding)  # (batch, MAX_HEROES * NUM_COMBAT_ACTIONS)
        action_logits = action_logits.view(batch_size, MAX_HEROES, NUM_COMBAT_ACTIONS)
        # For simplicity, we output one action for the "primary hero to act on"
        # The hero_head selects which hero, then action_head gives that hero's action

        hero_logits = self.hero_head(embedding)  # (batch, MAX_HEROES)
        room_logits = self.room_head(embedding)  # (batch, MAX_ROOMS)

        # Use first hero's action logits as the action distribution
        # (in practice, we select hero first then use that hero's row)
        hero_dist = Categorical(logits=hero_logits)

        # Mean over hero dimension for action (simplified)
        mean_action_logits = action_logits.mean(dim=1)  # (batch, NUM_COMBAT_ACTIONS)
        action_dist = Categorical(logits=mean_action_logits)

        room_dist = Categorical(logits=room_logits)

        value = self.value_head(embedding).squeeze(-1)  # (batch,)

        return value, action_dist, room_dist, hero_dist

    def act(
        self, obs: dict[str, torch.Tensor], deterministic: bool = False
    ) -> tuple[dict[str, torch.Tensor], torch.Tensor, torch.Tensor]:
        """
        Select a combat action.

        Returns:
            (action_dict, log_prob, value)
            action_dict: {"combat_action": (batch,), "room_target": (batch,), "hero_target": (batch,)}
        """
        value, action_dist, room_dist, hero_dist = self.forward(obs)

        if deterministic:
            action = action_dist.probs.argmax(dim=-1)
            room = room_dist.probs.argmax(dim=-1)
            hero = hero_dist.probs.argmax(dim=-1)
        else:
            action = action_dist.sample()
            room = room_dist.sample()
            hero = hero_dist.sample()

        log_prob = (
            action_dist.log_prob(action)
            + room_dist.log_prob(room)
            + hero_dist.log_prob(hero)
        )

        action_dict = {
            "combat_action": action,
            "room_target": room,
            "hero_target": hero,
        }

        return action_dict, log_prob, value

"""
Escape Controller: Specialized policy for the escape phase.

Handles:
  - Crystal carrier selection
  - Power reallocation for escape path
  - Hero role assignment (carrier, escort, blocker, exit-waiter)
  - Exit timing decisions (plug crystal or wait for stragglers)
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
# Escape Actions
# ---------------------------------------------------------------------------


class EscapeAction(IntEnum):
    """High-level escape decisions."""
    PICK_UP_CRYSTAL = 0       # Assign carrier + pick up crystal
    POWER_ROOM = 1            # Power a room on escape path
    DEPOWER_ROOM = 2          # Depower a room off escape path
    MOVE_HERO_TO_EXIT = 3     # Move a hero toward exit
    MOVE_HERO_TO_BLOCK = 4    # Position hero as spawn blocker
    PLUG_CRYSTAL = 5          # Plug crystal at exit (end floor)
    WAIT = 6                  # Let heroes move / wait for arrival


NUM_ESCAPE_ACTIONS = len(EscapeAction)


# ---------------------------------------------------------------------------
# Escape Controller Network
# ---------------------------------------------------------------------------


class EscapeControllerNetwork(nn.Module):
    """
    Policy network for escape-phase decisions.

    Simplified architecture since escape is a shorter, more focused phase.
    """

    def __init__(self, config: Optional[NetworkConfig] = None):
        super().__init__()
        cfg = config or NetworkConfig()
        hidden = cfg.escape_controller_hidden

        # Input: hero features + room power/distance features + escape-specific info
        input_size = MAX_HEROES * HERO_FEATURE_DIM + MAX_ROOMS * 4 + 6
        # Room features: is_powered, is_on_escape_path, distance_to_exit, mob_count
        # Escape info: crystal_carried, carrier_room, exit_room, heroes_at_exit, heroes_alive, floor

        self.encoder = nn.Sequential(
            nn.Linear(input_size, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
        )

        # Action head
        self.action_head = nn.Linear(hidden, NUM_ESCAPE_ACTIONS)

        # Room target head (for power/depower/block decisions)
        self.room_head = nn.Sequential(
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, MAX_ROOMS),
        )

        # Hero target head (for carrier/mover selection)
        self.hero_head = nn.Linear(hidden, MAX_HEROES)

        # Value head
        self.value_head = nn.Sequential(
            nn.Linear(hidden, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
        )

    def forward(
        self, obs: dict[str, torch.Tensor]
    ) -> tuple[torch.Tensor, Categorical, Categorical, Categorical]:
        """
        Forward pass.

        Returns:
            (value, action_dist, room_dist, hero_dist)
        """
        batch_size = obs["hero_features"].shape[0]

        hero_flat = obs["hero_features"].reshape(batch_size, -1).float()

        # Room escape features: is_powered(0), is_on_escape_path(17), dist_to_exit(19), mob_count(14)
        room_feats = obs["room_features"].float()
        room_escape = room_feats[:, :, [0, 17, 19, 14]].reshape(batch_size, -1)  # (batch, MAX_ROOMS*4)

        # Escape-specific info from game_meta and hero features
        game_meta = obs["game_meta"].float()
        # crystal_safe(7), exit_room(8), num_heroes(4), floor(1), num_mobs(5), phase(2)
        escape_info = game_meta[:, [7, 8, 4, 1, 5, 2]]  # (batch, 6)

        x = torch.cat([hero_flat, room_escape, escape_info], dim=-1)
        embedding = self.encoder(x)

        action_logits = self.action_head(embedding)
        room_logits = self.room_head(embedding)
        hero_logits = self.hero_head(embedding)

        action_dist = Categorical(logits=action_logits)
        room_dist = Categorical(logits=room_logits)
        hero_dist = Categorical(logits=hero_logits)

        value = self.value_head(embedding).squeeze(-1)

        return value, action_dist, room_dist, hero_dist

    def act(
        self, obs: dict[str, torch.Tensor], deterministic: bool = False
    ) -> tuple[dict[str, torch.Tensor], torch.Tensor, torch.Tensor]:
        """
        Select an escape action.

        Returns:
            (action_dict, log_prob, value)
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
            "escape_action": action,
            "room_target": room,
            "hero_target": hero,
        }

        return action_dict, log_prob, value

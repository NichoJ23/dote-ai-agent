"""
Neural network definitions for the RL agent.

Architecture (design §11.7):
  - Shared encoder: graph MLP + entity MLP → fusion → 512-d embedding
  - Option head: 16-way softmax with action mask
  - Parameter heads: per-option small MLPs producing categorical distributions
  - Value head: scalar V(s) from shared embedding
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Categorical

from action_masking import NUM_OPTIONS, StrategicOption
from rl_config import NetworkConfig
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


# ---------------------------------------------------------------------------
# Activation helper
# ---------------------------------------------------------------------------

def _get_activation(name: str) -> nn.Module:
    if name == "relu":
        return nn.ReLU()
    elif name == "tanh":
        return nn.Tanh()
    elif name == "gelu":
        return nn.GELU()
    else:
        return nn.ReLU()


# ---------------------------------------------------------------------------
# Shared Encoder
# ---------------------------------------------------------------------------


class SharedEncoder(nn.Module):
    """
    Shared feature encoder for the RL agent.

    Takes the full observation dict and produces a fixed-size embedding.

    Components:
      - Graph encoder: flattened adjacency + power + room features → MLP
      - Entity encoder: hero + mob features → MLP with mean pooling
      - Resource/meta encoder: resources + game_meta → MLP
      - Fusion: concatenate all → MLP → shared embedding
    """

    def __init__(self, config: Optional[NetworkConfig] = None):
        super().__init__()
        self.config = config or NetworkConfig()
        act = _get_activation(self.config.activation)

        # Graph encoder input: adjacency (flattened upper triangle) + power_state + power_reachable + room_features
        # Upper triangle of MAX_ROOMS x MAX_ROOMS = MAX_ROOMS*(MAX_ROOMS-1)//2
        adj_size = MAX_ROOMS * (MAX_ROOMS - 1) // 2
        graph_input_size = adj_size + MAX_ROOMS + MAX_ROOMS + MAX_ROOMS * ROOM_FEATURE_DIM
        self.graph_encoder = nn.Sequential(
            nn.Linear(graph_input_size, self.config.graph_encoder_hidden),
            act,
            nn.Linear(self.config.graph_encoder_hidden, self.config.graph_encoder_hidden),
            act,
        )

        # Entity encoder input: hero_features (flattened) + mob summary
        hero_input_size = MAX_HEROES * HERO_FEATURE_DIM
        mob_summary_size = 16  # Compressed mob info
        entity_input_size = hero_input_size + mob_summary_size
        self.entity_encoder = nn.Sequential(
            nn.Linear(entity_input_size, self.config.entity_encoder_hidden),
            act,
            nn.Linear(self.config.entity_encoder_hidden, self.config.entity_encoder_hidden),
            act,
        )

        # Mob compressor: variable mobs → fixed summary
        self.mob_compressor = nn.Sequential(
            nn.Linear(MOB_FEATURE_DIM, 16),
            act,
        )

        # Resource/meta encoder
        resource_meta_size = RESOURCE_DIM + GAME_META_DIM
        self.resource_encoder = nn.Sequential(
            nn.Linear(resource_meta_size, 64),
            act,
            nn.Linear(64, 64),
            act,
        )

        # Fusion layer
        fusion_input_size = (
            self.config.graph_encoder_hidden
            + self.config.entity_encoder_hidden
            + 64  # resource encoder output
        )
        self.fusion = nn.Sequential(
            nn.Linear(fusion_input_size, self.config.shared_embedding_dim),
            act,
            nn.Linear(self.config.shared_embedding_dim, self.config.shared_embedding_dim),
            act,
        )

    def forward(self, obs: dict[str, torch.Tensor]) -> torch.Tensor:
        """
        Encode observation into shared embedding.

        Args:
            obs: Dict of tensors matching the observation space.
                 Each tensor has batch dimension: (batch, ...).

        Returns:
            Shared embedding tensor of shape (batch, shared_embedding_dim).
        """
        batch_size = obs["adjacency"].shape[0]

        # --- Graph features ---
        # Extract upper triangle of adjacency
        adj = obs["adjacency"].float()
        triu_indices = torch.triu_indices(MAX_ROOMS, MAX_ROOMS, offset=1)
        adj_flat = adj[:, triu_indices[0], triu_indices[1]]  # (batch, adj_size)

        power_state = obs["power_state"].float()  # (batch, MAX_ROOMS)
        power_reachable = obs["power_reachable"].float()  # (batch, MAX_ROOMS)
        room_feats = obs["room_features"].reshape(batch_size, -1)  # (batch, MAX_ROOMS * ROOM_FEAT)

        graph_input = torch.cat([adj_flat, power_state, power_reachable, room_feats], dim=-1)
        graph_emb = self.graph_encoder(graph_input)

        # --- Entity features ---
        hero_feats = obs["hero_features"].reshape(batch_size, -1)  # (batch, MAX_HEROES * HERO_FEAT)

        # Mob compression: mean pool over valid mobs (non-negative room_index)
        mob_feats = obs["mob_features"].float()  # (batch, MAX_MOBS, MOB_FEAT)
        mob_mask = (mob_feats[:, :, 0] >= 0).float().unsqueeze(-1)  # (batch, MAX_MOBS, 1)
        mob_encoded = self.mob_compressor(mob_feats)  # (batch, MAX_MOBS, 16)
        mob_sum = (mob_encoded * mob_mask).sum(dim=1)  # (batch, 16)
        mob_count = mob_mask.sum(dim=1).clamp(min=1.0)  # (batch, 1)
        mob_summary = mob_sum / mob_count  # (batch, 16)

        entity_input = torch.cat([hero_feats, mob_summary], dim=-1)
        entity_emb = self.entity_encoder(entity_input)

        # --- Resource/meta ---
        resources = obs["resources"].float()  # (batch, RESOURCE_DIM)
        game_meta = obs["game_meta"].float()  # (batch, GAME_META_DIM)
        resource_input = torch.cat([resources, game_meta], dim=-1)
        resource_emb = self.resource_encoder(resource_input)

        # --- Fusion ---
        fused = torch.cat([graph_emb, entity_emb, resource_emb], dim=-1)
        embedding = self.fusion(fused)

        return embedding


# ---------------------------------------------------------------------------
# Option Head (Level 1 policy)
# ---------------------------------------------------------------------------


class OptionHead(nn.Module):
    """
    Produces a distribution over strategic options (16-way) with action masking.
    """

    def __init__(self, embedding_dim: int = 512):
        super().__init__()
        self.fc = nn.Linear(embedding_dim, NUM_OPTIONS)

    def forward(
        self, embedding: torch.Tensor, action_mask: torch.Tensor
    ) -> Categorical:
        """
        Args:
            embedding: (batch, embedding_dim) shared embedding.
            action_mask: (batch, NUM_OPTIONS) int8 mask (1=valid, 0=masked).

        Returns:
            Categorical distribution over valid options.
        """
        logits = self.fc(embedding)
        # Apply mask: set invalid options to -inf
        mask_bool = action_mask.bool()
        logits = logits.masked_fill(~mask_bool, float("-inf"))
        return Categorical(logits=logits)


# ---------------------------------------------------------------------------
# Parameter Heads (Level 2 policy)
# ---------------------------------------------------------------------------


class ParameterHeads(nn.Module):
    """
    Per-option parameter heads. Each option gets a small MLP that produces
    categorical distributions over its parameters (room, hero, entity).

    Only the selected option's head is evaluated during forward pass.
    """

    def __init__(self, embedding_dim: int = 512, hidden_dim: int = 128):
        super().__init__()

        # Room target head (used by: POWER, DEPOWER, BUILD, DESTROY, POSITION, OPEN_DOOR)
        self.room_head = nn.Sequential(
            nn.Linear(embedding_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, MAX_ROOMS),
        )

        # Hero target head (used by: POSITION, OPEN_DOOR, LEVEL_UP, HEAL, DISMISS, EQUIP, etc.)
        self.hero_head = nn.Sequential(
            nn.Linear(embedding_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, MAX_HEROES),
        )

        # Entity target head (used by: BUILD module_id, RESEARCH blueprint_id, BUY item_id, etc.)
        self.entity_head = nn.Sequential(
            nn.Linear(embedding_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, MAX_MODULES),
        )

    def forward(
        self, embedding: torch.Tensor, selected_option: torch.Tensor
    ) -> tuple[Categorical, Categorical, Categorical]:
        """
        Produce parameter distributions for all heads.

        In practice, only the relevant parameters matter for the selected option,
        but we compute all for simplicity (gradients only flow through used params
        via the log_prob computation in training).

        Args:
            embedding: (batch, embedding_dim)
            selected_option: (batch,) selected option indices (not used for computation,
                           but could be used for option-conditioned heads in future).

        Returns:
            (room_dist, hero_dist, entity_dist) — Categorical distributions.
        """
        room_logits = self.room_head(embedding)
        hero_logits = self.hero_head(embedding)
        entity_logits = self.entity_head(embedding)

        return (
            Categorical(logits=room_logits),
            Categorical(logits=hero_logits),
            Categorical(logits=entity_logits),
        )


# ---------------------------------------------------------------------------
# Value Head
# ---------------------------------------------------------------------------


class ValueHead(nn.Module):
    """Scalar state-value prediction V(s)."""

    def __init__(self, embedding_dim: int = 512, hidden_dim: int = 256):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(embedding_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, embedding: torch.Tensor) -> torch.Tensor:
        """Returns (batch, 1) value estimates."""
        return self.net(embedding)


# ---------------------------------------------------------------------------
# Full Policy Network
# ---------------------------------------------------------------------------


class PolicyNetwork(nn.Module):
    """
    Complete policy network combining all components.

    Usage:
        net = PolicyNetwork(config)
        embedding = net.encode(obs)
        option_dist = net.get_option_distribution(embedding, mask)
        option = option_dist.sample()
        room_dist, hero_dist, entity_dist = net.get_param_distributions(embedding, option)
        value = net.get_value(embedding)
    """

    def __init__(self, config: Optional[NetworkConfig] = None):
        super().__init__()
        self.config = config or NetworkConfig()

        self.encoder = SharedEncoder(self.config)
        self.option_head = OptionHead(self.config.shared_embedding_dim)
        self.param_heads = ParameterHeads(
            self.config.shared_embedding_dim,
            self.config.param_head_hidden,
        )
        self.value_head = ValueHead(
            self.config.shared_embedding_dim,
            self.config.value_head_hidden,
        )

    def encode(self, obs: dict[str, torch.Tensor]) -> torch.Tensor:
        """Encode observation to shared embedding."""
        return self.encoder(obs)

    def get_option_distribution(
        self, embedding: torch.Tensor, action_mask: torch.Tensor
    ) -> Categorical:
        """Get option distribution with masking applied."""
        return self.option_head(embedding, action_mask)

    def get_param_distributions(
        self, embedding: torch.Tensor, selected_option: torch.Tensor
    ) -> tuple[Categorical, Categorical, Categorical]:
        """Get parameter distributions for the selected option."""
        return self.param_heads(embedding, selected_option)

    def get_value(self, embedding: torch.Tensor) -> torch.Tensor:
        """Get state value estimate."""
        return self.value_head(embedding)

    def act(
        self, obs: dict[str, torch.Tensor], action_mask: torch.Tensor, deterministic: bool = False
    ) -> tuple[dict[str, torch.Tensor], torch.Tensor, torch.Tensor]:
        """
        Full forward pass: select action + compute log_prob + value.

        Args:
            obs: Observation dict (batch dim required, even if batch=1).
            action_mask: (batch, NUM_OPTIONS) validity mask.
            deterministic: If True, use argmax instead of sampling.

        Returns:
            (action_dict, log_prob, value) where:
              - action_dict: {"option": (batch,), "room_target": (batch,),
                             "hero_target": (batch,), "entity_target": (batch,)}
              - log_prob: (batch,) total log probability of the action
              - value: (batch,) state value estimate
        """
        embedding = self.encode(obs)

        # Option selection
        option_dist = self.get_option_distribution(embedding, action_mask)
        if deterministic:
            option = option_dist.probs.argmax(dim=-1)
        else:
            option = option_dist.sample()

        # Parameter selection
        room_dist, hero_dist, entity_dist = self.get_param_distributions(embedding, option)
        if deterministic:
            room = room_dist.probs.argmax(dim=-1)
            hero = hero_dist.probs.argmax(dim=-1)
            entity = entity_dist.probs.argmax(dim=-1)
        else:
            room = room_dist.sample()
            hero = hero_dist.sample()
            entity = entity_dist.sample()

        # Compute total log_prob
        log_prob = (
            option_dist.log_prob(option)
            + room_dist.log_prob(room)
            + hero_dist.log_prob(hero)
            + entity_dist.log_prob(entity)
        )

        # Value
        value = self.value_head(embedding).squeeze(-1)

        action_dict = {
            "option": option,
            "room_target": room,
            "hero_target": hero,
            "entity_target": entity,
        }

        return action_dict, log_prob, value

    def evaluate_actions(
        self,
        obs: dict[str, torch.Tensor],
        action_mask: torch.Tensor,
        actions: dict[str, torch.Tensor],
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Evaluate log_prob and entropy for given actions (used in PPO update).

        Args:
            obs: Observation batch.
            action_mask: (batch, NUM_OPTIONS) mask.
            actions: {"option", "room_target", "hero_target", "entity_target"} tensors.

        Returns:
            (log_prob, entropy, value) all shape (batch,).
        """
        embedding = self.encode(obs)

        option_dist = self.get_option_distribution(embedding, action_mask)
        room_dist, hero_dist, entity_dist = self.get_param_distributions(
            embedding, actions["option"]
        )

        log_prob = (
            option_dist.log_prob(actions["option"])
            + room_dist.log_prob(actions["room_target"])
            + hero_dist.log_prob(actions["hero_target"])
            + entity_dist.log_prob(actions["entity_target"])
        )

        entropy = (
            option_dist.entropy()
            + room_dist.entropy()
            + hero_dist.entropy()
            + entity_dist.entropy()
        )

        value = self.value_head(embedding).squeeze(-1)

        return log_prob, entropy, value

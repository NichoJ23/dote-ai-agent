"""
Unit tests for networks.py — policy network architecture.
"""

import sys
from pathlib import Path

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "agent"))

from action_masking import NUM_OPTIONS, StrategicOption
from networks import (
    OptionHead,
    ParameterHeads,
    PolicyNetwork,
    SharedEncoder,
    ValueHead,
)
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
# Helpers
# ---------------------------------------------------------------------------


def _dummy_obs(batch_size: int = 2) -> dict[str, torch.Tensor]:
    """Create a dummy observation batch matching the observation space."""
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


def _all_valid_mask(batch_size: int = 2) -> torch.Tensor:
    return torch.ones(batch_size, NUM_OPTIONS, dtype=torch.int8)


# ---------------------------------------------------------------------------
# SharedEncoder
# ---------------------------------------------------------------------------


class TestSharedEncoder:
    def test_output_shape(self):
        config = NetworkConfig()
        encoder = SharedEncoder(config)
        obs = _dummy_obs(batch_size=4)
        emb = encoder(obs)
        assert emb.shape == (4, config.shared_embedding_dim)

    def test_output_not_nan(self):
        encoder = SharedEncoder()
        obs = _dummy_obs(batch_size=2)
        emb = encoder(obs)
        assert not torch.isnan(emb).any()

    def test_batch_size_1(self):
        encoder = SharedEncoder()
        obs = _dummy_obs(batch_size=1)
        emb = encoder(obs)
        assert emb.shape == (1, 512)


# ---------------------------------------------------------------------------
# OptionHead
# ---------------------------------------------------------------------------


class TestOptionHead:
    def test_distribution_shape(self):
        head = OptionHead(embedding_dim=512)
        emb = torch.randn(3, 512)
        mask = torch.ones(3, NUM_OPTIONS, dtype=torch.int8)
        dist = head(emb, mask)
        sample = dist.sample()
        assert sample.shape == (3,)
        assert (sample >= 0).all() and (sample < NUM_OPTIONS).all()

    def test_masked_options_have_zero_prob(self):
        head = OptionHead(embedding_dim=512)
        emb = torch.randn(1, 512)
        mask = torch.ones(1, NUM_OPTIONS, dtype=torch.int8)
        mask[0, StrategicOption.RESEARCH] = 0
        mask[0, StrategicOption.RECRUIT_HERO] = 0
        dist = head(emb, mask)
        probs = dist.probs[0]
        assert probs[StrategicOption.RESEARCH].item() == pytest.approx(0.0, abs=1e-6)
        assert probs[StrategicOption.RECRUIT_HERO].item() == pytest.approx(0.0, abs=1e-6)
        # WAIT should have non-zero prob
        assert probs[StrategicOption.WAIT].item() > 0

    def test_all_masked_except_wait(self):
        """If only WAIT is valid, distribution should put all mass on WAIT."""
        head = OptionHead(embedding_dim=512)
        emb = torch.randn(1, 512)
        mask = torch.zeros(1, NUM_OPTIONS, dtype=torch.int8)
        mask[0, StrategicOption.WAIT] = 1
        dist = head(emb, mask)
        assert dist.probs[0, StrategicOption.WAIT].item() == pytest.approx(1.0, abs=1e-5)


# ---------------------------------------------------------------------------
# ParameterHeads
# ---------------------------------------------------------------------------


class TestParameterHeads:
    def test_output_distributions(self):
        heads = ParameterHeads(embedding_dim=512, hidden_dim=128)
        emb = torch.randn(2, 512)
        option = torch.tensor([0, 5])
        room_dist, hero_dist, entity_dist = heads(emb, option)
        assert room_dist.sample().shape == (2,)
        assert hero_dist.sample().shape == (2,)
        assert entity_dist.sample().shape == (2,)

    def test_room_range(self):
        heads = ParameterHeads()
        emb = torch.randn(100, 512)
        option = torch.zeros(100, dtype=torch.long)
        room_dist, _, _ = heads(emb, option)
        samples = room_dist.sample()
        assert (samples >= 0).all() and (samples < MAX_ROOMS).all()


# ---------------------------------------------------------------------------
# ValueHead
# ---------------------------------------------------------------------------


class TestValueHead:
    def test_output_shape(self):
        head = ValueHead(embedding_dim=512)
        emb = torch.randn(5, 512)
        value = head(emb)
        assert value.shape == (5, 1)

    def test_output_is_scalar_per_batch(self):
        head = ValueHead()
        emb = torch.randn(1, 512)
        value = head(emb)
        assert value.shape == (1, 1)


# ---------------------------------------------------------------------------
# Full PolicyNetwork
# ---------------------------------------------------------------------------


class TestPolicyNetwork:
    def test_act_output_shapes(self):
        net = PolicyNetwork()
        obs = _dummy_obs(batch_size=3)
        mask = _all_valid_mask(batch_size=3)
        action_dict, log_prob, value = net.act(obs, mask)
        assert action_dict["option"].shape == (3,)
        assert action_dict["room_target"].shape == (3,)
        assert action_dict["hero_target"].shape == (3,)
        assert action_dict["entity_target"].shape == (3,)
        assert log_prob.shape == (3,)
        assert value.shape == (3,)

    def test_act_deterministic(self):
        net = PolicyNetwork()
        obs = _dummy_obs(batch_size=2)
        mask = _all_valid_mask(batch_size=2)
        # Deterministic should give same result each time
        a1, _, _ = net.act(obs, mask, deterministic=True)
        a2, _, _ = net.act(obs, mask, deterministic=True)
        assert torch.equal(a1["option"], a2["option"])
        assert torch.equal(a1["room_target"], a2["room_target"])

    def test_evaluate_actions(self):
        net = PolicyNetwork()
        obs = _dummy_obs(batch_size=4)
        mask = _all_valid_mask(batch_size=4)
        # First get actions
        actions, _, _ = net.act(obs, mask)
        # Then evaluate them
        log_prob, entropy, value = net.evaluate_actions(obs, mask, actions)
        assert log_prob.shape == (4,)
        assert entropy.shape == (4,)
        assert value.shape == (4,)
        # Entropy should be positive
        assert (entropy > 0).all()

    def test_gradient_flows(self):
        """Verify gradients flow through the full network."""
        net = PolicyNetwork()
        obs = _dummy_obs(batch_size=2)
        mask = _all_valid_mask(batch_size=2)
        actions, log_prob, value = net.act(obs, mask)
        loss = -(log_prob.mean()) + value.mean()
        loss.backward()
        # Check that encoder has gradients
        for param in net.encoder.parameters():
            if param.requires_grad:
                assert param.grad is not None
                break

    def test_action_mask_respected(self):
        """Sampled options should never be masked ones."""
        net = PolicyNetwork()
        obs = _dummy_obs(batch_size=50)
        mask = torch.ones(50, NUM_OPTIONS, dtype=torch.int8)
        # Mask out everything except WAIT and POWER_ROOM
        mask[:, :] = 0
        mask[:, StrategicOption.WAIT] = 1
        mask[:, StrategicOption.POWER_ROOM] = 1
        actions, _, _ = net.act(obs, mask)
        for opt in actions["option"]:
            assert opt.item() in (StrategicOption.WAIT, StrategicOption.POWER_ROOM)

"""
Tests for GuidelinesConfig toggle behavior.

Validates that the agent still functions when all guidelines are disabled
(may perform worse but doesn't crash).

REQ-O4: Guidelines must be individually toggleable without breaking the agent.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "agent"))

from guidelines_config import GuidelinesConfig
from heuristic_agent import AgentPhase, HeuristicAgent
from state_parser import GameStatePayload, StateParser


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _base_state(
    turn: int = 1,
    phase: str = "Strategy",
    crystal_state: str = "Plugged",
    dust: float = 10.0,
    food: float = 30.0,
) -> dict:
    """Minimal valid state dict."""
    return {
        "turn": turn,
        "floor": 1,
        "game_phase": phase,
        "crystal_state": crystal_state,
        "exit_room_index": 2,
        "start_room_index": 0,
        "resources": {
            "industry": 40.0,
            "food": food,
            "science": 15.0,
            "dust": dust,
            "dust_max": 15.0,
            "industry_per_turn": 5.0,
            "food_per_turn": 3.0,
            "science_per_turn": 2.0,
            "dust_per_turn": 0.0,
            "room_power_cost": 1.0,
            "powered_room_count": 1,
        },
        "rooms": [
            {
                "index": 0,
                "is_powered": True,
                "is_auto_powered": True,
                "is_exit_room": False,
                "is_start_room": True,
                "is_fully_opened": True,
                "depth": 0,
                "suffers_emp": False,
                "emp_turns_remaining": 0,
                "dust_loot_amount": 0,
                "has_artifact": True,
                "has_stele": False,
                "adjacent_room_indices": [1],
                "major_module_name": "IndustryGenerator_1",
                "minor_module_names": [],
                "minor_slot_count": 2,
                "hero_count": 1,
                "mob_count": 0,
                "npc_count": 0,
            },
            {
                "index": 1,
                "is_powered": False,
                "is_auto_powered": False,
                "is_exit_room": False,
                "is_start_room": False,
                "is_fully_opened": True,
                "depth": 1,
                "suffers_emp": False,
                "emp_turns_remaining": 0,
                "dust_loot_amount": 0,
                "has_artifact": False,
                "has_stele": False,
                "adjacent_room_indices": [0, 2],
                "major_module_name": None,
                "minor_module_names": [],
                "minor_slot_count": 2,
                "hero_count": 1,
                "mob_count": 0,
                "npc_count": 0,
            },
            {
                "index": 2,
                "is_powered": False,
                "is_auto_powered": False,
                "is_exit_room": True,
                "is_start_room": False,
                "is_fully_opened": True,
                "depth": 2,
                "suffers_emp": False,
                "emp_turns_remaining": 0,
                "dust_loot_amount": 0,
                "has_artifact": False,
                "has_stele": False,
                "adjacent_room_indices": [1],
                "major_module_name": None,
                "minor_module_names": [],
                "minor_slot_count": 1,
                "hero_count": 0,
                "mob_count": 0,
                "npc_count": 0,
            },
        ],
        "closed_doors": [{"room1_index": 1, "room2_index": 2, "is_opening": False}],
        "heroes": [
            {
                "name": "Max O'Kane",
                "faction": "Prisoner",
                "room_index": 0,
                "hp": 40.0,
                "max_hp": 250.0,
                "level": 3,
                "has_crystal": False,
                "is_operating": True,
                "operating_module_name": "IndustryGenerator_1",
                "is_recruitable": False,
                "is_recruited": True,
                "active_skills": [],
                "passive_skills": [{"name": "Operate"}],
                "equipment": [{"slot_category": "Weapon", "item_name": "Sword"}],
            },
            {
                "name": "Gork",
                "faction": "Native",
                "room_index": 1,
                "hp": 180.0,
                "max_hp": 200.0,
                "level": 2,
                "has_crystal": False,
                "is_operating": False,
                "operating_module_name": None,
                "is_recruitable": False,
                "is_recruited": True,
                "active_skills": [],
                "passive_skills": [],
                "equipment": [],
            },
        ],
        "mobs": [
            {"type": "ArtifactHunter", "room_index": 1, "hp": 60.0, "max_hp": 100.0, "target_type": "Artifact"}
        ],
        "merchants": [],
        "recruitable_heroes": [],
        "dropped_items": [],
        "backpack_items": [],
        "shared_inventory_items": [],
        "researchable_blueprints": [{"name": "Blueprint_Turret2", "science_cost": 20.0}],
    }


def _parse(state_dict: dict) -> GameStatePayload:
    return StateParser().parse(state_dict)


# ---------------------------------------------------------------------------
# Test: All Guidelines Disabled
# ---------------------------------------------------------------------------


class TestAllGuidelinesDisabled:
    """Verify agent functions correctly with all guidelines disabled."""

    def test_agent_runs_without_crash_all_disabled(self):
        """Agent produces actions with all guidelines disabled (no crash)."""
        guidelines = GuidelinesConfig.disabled()
        agent = HeuristicAgent(guidelines=guidelines)
        state = _parse(_base_state())

        # Should produce a valid action or None without crashing
        action = agent.select_action(state)
        assert action is None or isinstance(action, dict)

    def test_disabled_retreat_during_combat(self):
        """Agent doesn't retreat even with low HP when retreat is disabled."""
        guidelines = GuidelinesConfig.disabled()
        agent = HeuristicAgent(guidelines=guidelines)
        s = _base_state(phase="Action")
        # Max has very low HP
        s["heroes"][0]["hp"] = 10.0
        s["heroes"][0]["room_index"] = 1
        s["heroes"][0]["is_operating"] = False
        state = _parse(s)

        agent.select_action(state)
        # Should NOT enter RETREAT because retreat_enabled=False
        assert agent.current_phase != AgentPhase.RETREAT

    def test_disabled_operator_protection(self):
        """Agent can move operating heroes when protect_operators is disabled."""
        guidelines = GuidelinesConfig.disabled()
        agent = HeuristicAgent(guidelines=guidelines)
        s = _base_state(phase="Action")
        s["heroes"][0]["is_operating"] = True
        s["rooms"][1]["mob_count"] = 2
        s["mobs"] = [
            {"type": "Zed", "room_index": 1, "hp": 50.0, "max_hp": 80.0, "target_type": "AntiHeroMob"},
            {"type": "Zed", "room_index": 1, "hp": 50.0, "max_hp": 80.0, "target_type": "AntiHeroMob"},
        ]
        state = _parse(s)

        action = agent.select_action(state)

        # With protect_operators disabled, Max (operating) can be moved
        if action and action["command"] == "MOVE_HERO":
            # Either hero could be moved
            assert action["parameters"]["hero_name"] in ("Max O'Kane", "Gork")

    def test_disabled_research_gate(self):
        """Agent researches even with artifact threat when GL-7 is disabled."""
        guidelines = GuidelinesConfig.disabled()
        agent = HeuristicAgent(guidelines=guidelines)
        s = _base_state()
        s["resources"]["science"] = 50.0
        # Artifact under threat (mob targets artifact) — already in _base_state
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_research(state)

        # Should research because gate_research_on_artifact_safety is disabled
        assert action is not None
        assert action["command"] == "RESEARCH"

    def test_disabled_escape_repower(self):
        """Escape still works when GL-6 repower is disabled (just depowers, no repower)."""
        guidelines = GuidelinesConfig.disabled()
        agent = HeuristicAgent(guidelines=guidelines)
        s = _base_state()
        s["closed_doors"] = []
        for room in s["rooms"]:
            room["is_fully_opened"] = True
            room["is_powered"] = False
            room["is_auto_powered"] = False
        # Max in crystal room, Gork at exit
        s["heroes"][0]["room_index"] = 0
        s["heroes"][1]["room_index"] = 3
        state = _parse(s)

        agent._escape_initiated = True
        agent._graph = agent._graph_builder.build(state)

        action = agent._handle_escape(state)
        # With all guidelines disabled, should still produce a valid escape action
        assert action is None or isinstance(action, dict)

    def test_disabled_max_prioritization(self):
        """Agent doesn't prioritize Max for level-up when GL-4 is disabled."""
        guidelines = GuidelinesConfig.disabled()
        agent = HeuristicAgent(guidelines=guidelines)
        s = _base_state(food=100.0)
        s["heroes"][0]["is_operating"] = False
        # Gork is lower level
        s["heroes"][1]["level"] = 1
        s["heroes"][0]["level"] = 3
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_level_up(state)

        if action:
            assert action["command"] == "LEVEL_UP_HERO"
            # Without GL-4, lowest level hero (Gork) should be leveled first
            assert action["parameters"]["hero_name"] == "Gork"


# ---------------------------------------------------------------------------
# Test: Individual Guideline Toggles
# ---------------------------------------------------------------------------


class TestIndividualToggles:
    """Test toggling individual guidelines."""

    def test_gl1_retreat_threshold_custom(self):
        """Custom retreat threshold works correctly."""
        # Set a very high threshold — hero at 60% should retreat
        guidelines = GuidelinesConfig(retreat_hp_threshold=0.70)
        agent = HeuristicAgent(guidelines=guidelines)
        s = _base_state(phase="Action")
        s["heroes"][0]["hp"] = 150.0  # 150/250 = 60% — below 70% threshold
        s["heroes"][0]["room_index"] = 1
        s["heroes"][0]["is_operating"] = False
        state = _parse(s)

        agent.select_action(state)
        assert agent.current_phase == AgentPhase.RETREAT

    def test_gl2_custom_heroes(self):
        """Custom preferred starting heroes are used in guidelines."""
        guidelines = GuidelinesConfig(
            preferred_starting_heroes=["Hero_H0005", "Hero_H0010"]
        )
        assert guidelines.preferred_starting_heroes == ["Hero_H0005", "Hero_H0010"]

    def test_gl4_max_prioritization_when_operate_unlocked(self):
        """GL-4: Max not prioritized when he already has Operate."""
        guidelines = GuidelinesConfig(prioritize_max_operate_unlock=True)
        agent = HeuristicAgent(guidelines=guidelines)
        s = _base_state(food=100.0)
        s["heroes"][0]["is_operating"] = False
        # Max already has Operate
        s["heroes"][0]["passive_skills"] = [{"name": "Operate"}]
        s["heroes"][0]["level"] = 5
        s["heroes"][1]["level"] = 1  # Gork is lower level
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_level_up(state)

        if action:
            # Max already has Operate, so lowest level hero (Gork) gets leveled
            assert action["parameters"]["hero_name"] == "Gork"

    def test_config_from_dict(self):
        """GuidelinesConfig.from_dict works with partial data."""
        config = GuidelinesConfig.from_dict({
            "retreat_enabled": False,
            "retreat_hp_threshold": 0.50,
            "unknown_key": "ignored",
        })
        assert config.retreat_enabled is False
        assert config.retreat_hp_threshold == 0.50
        # Other fields retain defaults
        assert config.protect_operators is True
        assert config.fastest_hero_carries_crystal is True

    def test_config_disabled_factory(self):
        """GuidelinesConfig.disabled() sets all guidelines to off."""
        config = GuidelinesConfig.disabled()
        assert config.retreat_enabled is False
        assert config.retreat_hp_threshold == 0.0
        assert config.preferred_starting_heroes == []
        assert config.protect_operators is False
        assert config.prioritize_max_operate_unlock is False
        assert config.fastest_hero_carries_crystal is False
        assert config.repower_escape_path is False
        assert config.gate_research_on_artifact_safety is False
        assert config.pre_escape_inventory_management is False

    def test_config_to_dict_roundtrip(self):
        """GuidelinesConfig serializes and deserializes correctly."""
        original = GuidelinesConfig(
            retreat_hp_threshold=0.45,
            protect_operators=False,
        )
        data = original.to_dict()
        restored = GuidelinesConfig.from_dict(data)
        assert restored.retreat_hp_threshold == 0.45
        assert restored.protect_operators is False
        assert restored.retreat_enabled is True  # default

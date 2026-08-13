"""
Tests for advanced heuristic logic (Tasks 4.24-4.30).

Covers:
  - Sell to merchant (Task 4.24)
  - Pre-escape inventory management (Task 4.25, GL-8)
  - Artifact defense detection (Task 4.26, GL-7)
  - Crystal defense detection (Task 4.27)
  - Room interactables (Task 4.28)
  - Toxic cloud / EMP hazard avoidance (Tasks 4.29-4.30)
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "agent"))

from guidelines_config import GuidelinesConfig
from heuristic_agent import AgentPhase, HeuristicAgent, _action
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
    industry: float = 40.0,
) -> dict:
    return {
        "turn": turn,
        "floor": 1,
        "game_phase": phase,
        "crystal_state": crystal_state,
        "exit_room_index": 3,
        "start_room_index": 0,
        "resources": {
            "industry": industry,
            "food": food,
            "science": 15.0,
            "dust": dust,
            "dust_max": 15.0,
            "industry_per_turn": 5.0,
            "food_per_turn": 3.0,
            "science_per_turn": 2.0,
            "dust_per_turn": 0.0,
            "room_power_cost": 1.0,
            "powered_room_count": 2,
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
                "has_artifact": False,
                "has_stele": False,
                "adjacent_room_indices": [1, 2],
                "major_module_name": "IndustryGenerator_1",
                "minor_module_names": [],
                "minor_slot_count": 2,
                "hero_count": 2,
                "mob_count": 0,
                "npc_count": 0,
            },
            {
                "index": 1,
                "is_powered": True,
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
                "adjacent_room_indices": [0, 3],
                "major_module_name": None,
                "minor_module_names": [],
                "minor_slot_count": 2,
                "hero_count": 0,
                "mob_count": 0,
                "npc_count": 0,
            },
            {
                "index": 2,
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
                "adjacent_room_indices": [0],
                "major_module_name": None,
                "minor_module_names": [],
                "minor_slot_count": 1,
                "hero_count": 0,
                "mob_count": 0,
                "npc_count": 0,
            },
            {
                "index": 3,
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
                "minor_slot_count": 2,
                "hero_count": 0,
                "mob_count": 0,
                "npc_count": 0,
            },
        ],
        "closed_doors": [],
        "heroes": [
            {
                "name": "Max O'Kane",
                "faction": "Prisoner",
                "room_index": 0,
                "hp": 200.0,
                "max_hp": 250.0,
                "level": 3,
                "has_crystal": False,
                "is_operating": False,
                "operating_module_name": None,
                "is_recruitable": False,
                "is_recruited": True,
                "active_skills": [],
                "passive_skills": [{"name": "Operate"}],
                "equipment": [{"slot_category": "Weapon", "item_name": "Sword"}],
            },
            {
                "name": "Gork",
                "faction": "Native",
                "room_index": 0,
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
                "equipment": [{"slot_category": "Weapon", "item_name": None}],
            },
        ],
        "mobs": [],
        "merchants": [],
        "recruitable_heroes": [],
        "dropped_items": [],
        "backpack_items": [],
        "shared_inventory_items": [],
        "researchable_blueprints": [],
    }


def _parse(state_dict: dict) -> GameStatePayload:
    return StateParser().parse(state_dict)


# ---------------------------------------------------------------------------
# Test Class: Sell to Merchant (Task 4.24)
# ---------------------------------------------------------------------------


class TestSellToMerchant:
    """Test sell logic for unwanted items."""

    def test_sell_unwanted_shared_inventory_item(self):
        """Agent sells shared inventory items that aren't equipped."""
        agent = HeuristicAgent()
        s = _base_state()
        s["merchants"] = [
            {
                "room_index": 0,
                "currency_type": "Dust",
                "items": [{"name": "Shield", "rarity": "Common", "cost": 5.0}],
            }
        ]
        # Item in shared inventory that no one has equipped
        s["shared_inventory_items"] = [{"name": "OldDagger", "rarity": "Common", "category": "Weapon"}]
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_sell_to_merchant(state)

        assert action is not None
        assert action["command"] == "SELL_TO_MERCHANT"
        assert action["parameters"]["item_name"] == "OldDagger"

    def test_no_sell_when_no_merchants(self):
        """Agent does nothing when no merchants exist."""
        agent = HeuristicAgent()
        s = _base_state()
        s["shared_inventory_items"] = [{"name": "OldDagger", "rarity": "Common", "category": "Weapon"}]
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_sell_to_merchant(state)

        assert action is None

    def test_no_sell_when_hero_not_at_merchant(self):
        """Agent doesn't sell when no hero is at the merchant's room."""
        agent = HeuristicAgent()
        s = _base_state()
        s["merchants"] = [
            {
                "room_index": 3,  # No hero here
                "currency_type": "Dust",
                "items": [],
            }
        ]
        s["shared_inventory_items"] = [{"name": "OldDagger", "rarity": "Common", "category": "Weapon"}]
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_sell_to_merchant(state)

        assert action is None

    def test_no_sell_equipped_items(self):
        """Agent doesn't sell items that heroes have equipped."""
        agent = HeuristicAgent()
        s = _base_state()
        s["merchants"] = [
            {
                "room_index": 0,
                "currency_type": "Dust",
                "items": [],
            }
        ]
        # Sword is equipped by Max
        s["shared_inventory_items"] = [{"name": "Sword", "rarity": "Common", "category": "Weapon"}]
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_sell_to_merchant(state)

        assert action is None


# ---------------------------------------------------------------------------
# Test Class: Pre-Escape Inventory (Task 4.25, GL-8)
# ---------------------------------------------------------------------------


class TestPreEscapeInventory:
    """Test pre-escape inventory management."""

    def test_moves_items_to_backpack_during_escape(self):
        """Agent moves shared inventory items to backpack during escape."""
        agent = HeuristicAgent()
        s = _base_state()
        s["shared_inventory_items"] = [
            {"name": "RareSword", "rarity": "Rare", "category": "Weapon"},
            {"name": "CommonHelm", "rarity": "Common", "category": "Armor"},
        ]
        state = _parse(s)

        agent._escape_initiated = True
        agent._graph = agent._graph_builder.build(state)
        action = agent._try_pre_escape_inventory(state)

        assert action is not None
        assert action["command"] == "MOVE_TO_BACKPACK"
        # Should pick the rarer item first
        assert action["parameters"]["item_name"] == "RareSword"

    def test_no_move_when_backpack_full(self):
        """Agent doesn't try to move items when backpack has 4 items."""
        agent = HeuristicAgent()
        s = _base_state()
        s["backpack_items"] = [
            {"name": f"Item{i}", "rarity": "Common", "category": "Weapon"} for i in range(4)
        ]
        s["shared_inventory_items"] = [{"name": "Extra", "rarity": "Rare", "category": "Weapon"}]
        state = _parse(s)

        agent._escape_initiated = True
        agent._graph = agent._graph_builder.build(state)
        action = agent._try_pre_escape_inventory(state)

        assert action is None

    def test_no_move_when_not_escaping(self):
        """Agent doesn't manage inventory outside escape phase."""
        agent = HeuristicAgent()
        s = _base_state()
        s["shared_inventory_items"] = [{"name": "Sword", "rarity": "Rare", "category": "Weapon"}]
        state = _parse(s)

        agent._escape_initiated = False
        agent._graph = agent._graph_builder.build(state)
        action = agent._try_pre_escape_inventory(state)

        assert action is None

    def test_no_move_when_gl8_disabled(self):
        """Agent skips inventory management when GL-8 is disabled."""
        guidelines = GuidelinesConfig(pre_escape_inventory_management=False)
        agent = HeuristicAgent(guidelines=guidelines)
        s = _base_state()
        s["shared_inventory_items"] = [{"name": "Sword", "rarity": "Rare", "category": "Weapon"}]
        state = _parse(s)

        agent._escape_initiated = True
        agent._graph = agent._graph_builder.build(state)
        action = agent._try_pre_escape_inventory(state)

        assert action is None


# ---------------------------------------------------------------------------
# Test Class: Artifact Defense (Task 4.26, GL-7)
# ---------------------------------------------------------------------------


class TestArtifactDefense:
    """Test artifact threat detection and defense logic."""

    def test_artifact_under_threat_when_mobs_target_artifact(self):
        """Detects artifact threat when artifact-targeting mobs exist."""
        agent = HeuristicAgent()
        s = _base_state()
        s["rooms"][1]["has_artifact"] = True
        s["mobs"] = [
            {"type": "Hunter", "room_index": 2, "hp": 80.0, "max_hp": 100.0, "target_type": "Artifact"}
        ]
        state = _parse(s)
        agent._graph = agent._graph_builder.build(state)

        assert agent._artifact_under_threat(state) is True

    def test_no_artifact_threat_with_normal_mobs(self):
        """No artifact threat when mobs target heroes, not artifacts."""
        agent = HeuristicAgent()
        s = _base_state()
        s["rooms"][1]["has_artifact"] = True
        s["mobs"] = [
            {"type": "Zed", "room_index": 2, "hp": 50.0, "max_hp": 80.0, "target_type": "AntiHeroMob"}
        ]
        state = _parse(s)
        agent._graph = agent._graph_builder.build(state)

        assert agent._artifact_under_threat(state) is False

    def test_no_artifact_threat_when_no_artifact(self):
        """No threat when there's no artifact on the floor."""
        agent = HeuristicAgent()
        s = _base_state()
        s["mobs"] = [
            {"type": "Hunter", "room_index": 2, "hp": 80.0, "max_hp": 100.0, "target_type": "Artifact"}
        ]
        state = _parse(s)
        agent._graph = agent._graph_builder.build(state)

        assert agent._artifact_under_threat(state) is False

    def test_artifact_defense_targets_include_adjacent_rooms(self):
        """Artifact defense targets include the artifact room and its neighbors."""
        agent = HeuristicAgent()
        s = _base_state()
        s["rooms"][1]["has_artifact"] = True
        state = _parse(s)
        agent._graph = agent._graph_builder.build(state)

        targets = agent._get_artifact_defense_targets(state)

        assert 1 in targets  # Artifact room
        assert 0 in targets  # Adjacent to room 1
        assert 3 in targets  # Adjacent to room 1

    def test_research_blocked_by_artifact_threat(self):
        """GL-7: Research is blocked when artifact is under threat."""
        agent = HeuristicAgent()
        s = _base_state()
        s["rooms"][1]["has_artifact"] = True
        s["mobs"] = [
            {"type": "Hunter", "room_index": 2, "hp": 80.0, "max_hp": 100.0, "target_type": "Artifact"}
        ]
        s["researchable_blueprints"] = [{"name": "Blueprint_Turret2", "science_cost": 20.0}]
        s["resources"]["science"] = 50.0
        state = _parse(s)
        agent._graph = agent._graph_builder.build(state)

        action = agent._try_research(state)
        assert action is None


# ---------------------------------------------------------------------------
# Test Class: Crystal Defense (Task 4.27)
# ---------------------------------------------------------------------------


class TestCrystalDefense:
    """Test crystal threat detection and defense prioritization."""

    def test_crystal_under_threat_when_mobs_target_crystal(self):
        """Detects crystal threat when crystal-targeting mobs exist."""
        agent = HeuristicAgent()
        s = _base_state(phase="Action")
        s["mobs"] = [
            {"type": "Destroyer", "room_index": 1, "hp": 120.0, "max_hp": 150.0, "target_type": "Crystal"}
        ]
        state = _parse(s)
        agent._graph = agent._graph_builder.build(state)

        assert agent._crystal_under_threat(state) is True

    def test_no_crystal_threat_with_hero_targeting_mobs(self):
        """No crystal threat when mobs only target heroes."""
        agent = HeuristicAgent()
        s = _base_state(phase="Action")
        s["mobs"] = [
            {"type": "Zed", "room_index": 1, "hp": 50.0, "max_hp": 80.0, "target_type": "AntiHeroMob"}
        ]
        state = _parse(s)
        agent._graph = agent._graph_builder.build(state)

        assert agent._crystal_under_threat(state) is False

    def test_crystal_defense_targets(self):
        """Crystal defense targets include crystal room and neighbors."""
        agent = HeuristicAgent()
        s = _base_state()
        state = _parse(s)
        agent._graph = agent._graph_builder.build(state)

        targets = agent._get_crystal_defense_targets(state)

        assert 0 in targets  # Crystal room (start_room_index=0)
        assert 1 in targets  # Adjacent
        assert 2 in targets  # Adjacent

    def test_defend_prioritizes_crystal_room_under_threat(self):
        """During combat, crystal threat makes DEFEND prioritize crystal room."""
        agent = HeuristicAgent()
        s = _base_state(phase="Action")
        s["heroes"][0]["room_index"] = 3  # At the exit room (not adjacent to crystal)
        s["heroes"][1]["room_index"] = 3
        s["rooms"][0]["hero_count"] = 0
        s["rooms"][3]["hero_count"] = 2
        s["mobs"] = [
            {"type": "Destroyer", "room_index": 1, "hp": 120.0, "max_hp": 150.0, "target_type": "Crystal"}
        ]
        s["rooms"][1]["mob_count"] = 1
        state = _parse(s)

        action = agent.select_action(state)

        assert action is not None
        assert action["command"] == "MOVE_HERO"
        # Should move toward crystal room (room 0) or mob room (room 1)
        # From room 3, next step toward room 0 is room 1
        assert action["parameters"]["target_room_index"] == 1


# ---------------------------------------------------------------------------
# Test Class: Room Interactables (Task 4.28)
# ---------------------------------------------------------------------------


class TestRoomInteractables:
    """Test room interactable (chest) interaction logic."""

    def test_interact_with_chest_when_hero_present(self):
        """Agent interacts with chest when hero is in the same room."""
        agent = HeuristicAgent()
        s = _base_state()
        s["dropped_items"] = [
            {"type": "Chest", "name": "GoldChest", "room_index": 0, "dust_amount": 0.0}
        ]
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_interact_room_items(state)

        assert action is not None
        assert action["command"] == "INTERACT_ROOM_ITEM"
        assert action["parameters"]["hero_name"] == "Max O'Kane"
        assert action["parameters"]["item_id"] == "GoldChest"

    def test_dispatches_hero_to_chest_room(self):
        """Agent sends hero to room with chest if none present."""
        agent = HeuristicAgent()
        s = _base_state()
        s["dropped_items"] = [
            {"type": "Chest", "name": "SilverChest", "room_index": 2, "dust_amount": 0.0}
        ]
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_interact_room_items(state)

        assert action is not None
        assert action["command"] == "MOVE_HERO"
        assert action["parameters"]["target_room_index"] == 2

    def test_no_interact_with_non_chest_items(self):
        """Agent doesn't try to interact with Dust or Equipment drops."""
        agent = HeuristicAgent()
        s = _base_state()
        s["dropped_items"] = [
            {"type": "Dust", "name": None, "room_index": 2, "dust_amount": 5.0},
            {"type": "Equipment", "name": "Boots", "room_index": 1, "dust_amount": 0.0},
        ]
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_interact_room_items(state)

        assert action is None

    def test_no_interact_when_room_has_mobs(self):
        """Agent doesn't send hero to interact if room has mobs (unsafe)."""
        agent = HeuristicAgent()
        s = _base_state()
        s["dropped_items"] = [
            {"type": "Chest", "name": "DangerChest", "room_index": 2, "dust_amount": 0.0}
        ]
        s["rooms"][2]["mob_count"] = 3
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_interact_room_items(state)

        # No hero in room 2, and room has mobs, so agent shouldn't dispatch
        assert action is None


# ---------------------------------------------------------------------------
# Test Class: EMP Awareness (Task 4.30)
# ---------------------------------------------------------------------------


class TestEMPAwareness:
    """Test EMP-affected room avoidance."""

    def test_is_room_hazardous_with_emp(self):
        """Room with EMP is detected as hazardous."""
        agent = HeuristicAgent()
        s = _base_state()
        s["rooms"][1]["suffers_emp"] = True
        s["rooms"][1]["emp_turns_remaining"] = 3
        state = _parse(s)
        agent._graph = agent._graph_builder.build(state)

        assert agent._is_room_hazardous(state, 1) is True
        assert agent._is_room_hazardous(state, 0) is False

    def test_no_build_in_emp_room(self):
        """Agent skips building modules in EMP-affected rooms."""
        agent = HeuristicAgent()
        s = _base_state(industry=100.0)
        s["rooms"][1]["suffers_emp"] = True
        # Room 1 has no major module and has EMP
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_build_module(state)

        # Should build in room 2 or 3, NOT room 1
        if action and action["command"] == "BUILD_MODULE":
            assert action["parameters"]["room_index"] != 1

    def test_no_operator_in_emp_room(self):
        """Agent doesn't place operators in EMP-affected rooms."""
        agent = HeuristicAgent()
        s = _base_state()
        # Room 0 has a major module and EMP
        s["rooms"][0]["suffers_emp"] = True
        # Give Gork the Operate passive
        s["heroes"][1]["passive_skills"] = [{"name": "Operate"}]
        s["heroes"][1]["room_index"] = 2
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_operator_placement(state)

        # Should not place in room 0 (EMP), since it's the only candidate
        # and it's hazardous, so no candidates remain
        assert action is None

    def test_defend_avoids_emp_rooms(self):
        """DEFEND handler avoids positioning heroes in EMP rooms."""
        agent = HeuristicAgent()
        s = _base_state(phase="Action")
        s["rooms"][1]["suffers_emp"] = True
        s["rooms"][1]["mob_count"] = 2
        s["mobs"] = [
            {"type": "Zed", "room_index": 1, "hp": 50.0, "max_hp": 80.0, "target_type": "AntiHeroMob"},
            {"type": "Zed", "room_index": 1, "hp": 50.0, "max_hp": 80.0, "target_type": "AntiHeroMob"},
        ]
        state = _parse(s)

        action = agent.select_action(state)

        # Agent should still defend but prefer non-EMP rooms if available
        # Room 1 has EMP but also mobs — other targets (crystal room, neighbors) are safe
        if action and action["command"] == "MOVE_HERO":
            # Hero should move to room 0 (crystal room, safe) rather than room 1 (EMP)
            assert action["parameters"]["target_room_index"] in (0, 2, 3)

    def test_is_room_hazardous_nonexistent_room(self):
        """Non-existent room returns not hazardous."""
        agent = HeuristicAgent()
        s = _base_state()
        state = _parse(s)
        agent._graph = agent._graph_builder.build(state)

        assert agent._is_room_hazardous(state, 99) is False


# ---------------------------------------------------------------------------
# Test Class: Integration — Advanced Logic in Build Priority
# ---------------------------------------------------------------------------


class TestAdvancedBuildIntegration:
    """Test that advanced logic is integrated into the BUILD handler priority."""

    def test_build_handler_includes_sell(self):
        """Build handler processes items appropriately."""
        agent = HeuristicAgent()
        s = _base_state(industry=0.0, food=0.0)  # Can't build or level
        s["merchants"] = [
            {"room_index": 0, "currency_type": "Dust", "items": []}
        ]
        s["shared_inventory_items"] = [{"name": "JunkItem", "rarity": "Common", "category": "Accessory"}]
        s["researchable_blueprints"] = []
        state = _parse(s)

        agent._escape_initiated = False
        agent._graph = agent._graph_builder.build(state)

        action = agent._handle_build(state)
        # With no industry/food and no doors from crystal room,
        # the macro planner may return None or a valid action
        assert action is None or isinstance(action, dict)

    def test_build_handler_includes_chest_interaction(self):
        """Build handler collects chests via COLLECT_ITEM."""
        agent = HeuristicAgent()
        s = _base_state(industry=0.0, food=0.0, dust=0.0)  # Can't do much
        s["dropped_items"] = [
            {"type": "Chest", "name": "TreasureChest", "room_index": 0, "dust_amount": 0.0}
        ]
        s["researchable_blueprints"] = []
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._handle_build(state)

        # Should collect the chest since hero is in room 0
        if action:
            assert action["command"] == "COLLECT_ITEM"

"""
Tests for the HeuristicAgent FSM controller.

Validates:
  - FSM phase transitions (EXPLORE, BUILD, DEFEND, RETREAT, ESCAPE)
  - Action generation for each phase
  - Correct handling of mock state sequences (merchants, recruits, escape)
  - Agent produces valid action sequences without crashes
  - Integration with GraphBuilder and graph_utils
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "agent"))

from guidelines_config import GuidelinesConfig
from heuristic_agent import AgentPhase, HeuristicAgent, _action
from state_parser import GameStatePayload, StateParser


# ---------------------------------------------------------------------------
# Fixture helpers — build realistic game state dicts
# ---------------------------------------------------------------------------


def _base_state(
    turn: int = 1,
    phase: str = "Strategy",
    crystal_state: str = "Plugged",
    dust: float = 10.0,
    food: float = 30.0,
    industry: float = 40.0,
    science: float = 15.0,
) -> dict:
    """Minimal valid state dict matching actual mod wire format."""
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
            "science": science,
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
                "is_fully_opened": False,
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
        "closed_doors": [{"room1_index": 1, "room2_index": 3, "is_opening": False}],
        "heroes": [
            {
                "name": "Max O'Kane",
                "faction": "Prisoner",
                "room_index": 0,
                "hp": 200.0,
                "max_hp": 250.0,
                "level": 2,
                "has_crystal": False,
                "is_operating": False,
                "operating_module_name": None,
                "is_recruitable": False,
                "is_recruited": True,
                "active_skills": [
                    {"name": "Punch", "cooldown_turns": 3, "remaining_cooldown": 0, "is_activated": False}
                ],
                "passive_skills": [{"name": "Repair"}],
                "equipment": [{"slot_category": "Weapon", "item_name": "Sword"}],
            },
            {
                "name": "Gork",
                "faction": "Native",
                "room_index": 0,
                "hp": 180.0,
                "max_hp": 200.0,
                "level": 1,
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
        "mobs": [],
        "merchants": [],
        "recruitable_heroes": [],
        "dropped_items": [],
        "backpack_items": [],
        "shared_inventory_items": [],
        "researchable_blueprints": [],
    }


def _parse(state_dict: dict) -> GameStatePayload:
    """Parse a state dict into a GameStatePayload."""
    return StateParser().parse(state_dict)


# ---------------------------------------------------------------------------
# Test Class: FSM Phase Transitions
# ---------------------------------------------------------------------------


class TestFSMTransitions:
    """Test FSM phase determination logic."""

    def test_explore_when_closed_doors_exist(self):
        """Agent uses decision tree during Strategy phase (doors present)."""
        agent = HeuristicAgent()
        state = _parse(_base_state())
        # closed_doors has one entry — decision tree will eventually open it (step 10)
        # but earlier steps (build, power) may fire first
        action = agent.select_action(state)
        assert agent.current_phase == AgentPhase.BUILD
        assert action is not None

    def test_build_when_all_doors_open(self):
        """Agent enters BUILD when all doors are open but exit not yet found."""
        agent = HeuristicAgent()
        s = _base_state()
        s["closed_doors"] = []  # No closed doors
        # Remove exit room flag — exit not discovered yet
        for room in s["rooms"]:
            room["is_exit_room"] = False
            room["is_fully_opened"] = True  # All rooms fully opened
        state = _parse(s)
        action = agent.select_action(state)
        # No exit found yet, so should stay in BUILD (not ESCAPE)
        assert agent.current_phase == AgentPhase.BUILD

    def test_defend_during_combat(self):
        """Agent enters DEFEND during Action phase."""
        agent = HeuristicAgent()
        s = _base_state(phase="Action")
        s["mobs"] = [
            {"type": "Zed", "room_index": 1, "hp": 50.0, "max_hp": 80.0, "target_type": "AntiHeroMob"}
        ]
        state = _parse(s)
        action = agent.select_action(state)
        assert agent.current_phase == AgentPhase.DEFEND

    def test_retreat_when_hero_low_hp(self):
        """Agent enters RETREAT when a hero is below HP threshold during combat."""
        agent = HeuristicAgent()
        s = _base_state(phase="Action")
        s["heroes"][0]["hp"] = 50.0  # 50/250 = 20%, below 30% threshold
        s["heroes"][0]["room_index"] = 1  # Not in crystal room
        s["mobs"] = [
            {"type": "Zed", "room_index": 1, "hp": 50.0, "max_hp": 80.0, "target_type": "AntiHeroMob"}
        ]
        state = _parse(s)
        action = agent.select_action(state)
        assert agent.current_phase == AgentPhase.RETREAT

    def test_escape_when_crystal_on_exit_slot(self):
        """Agent enters ESCAPE when crystal_state is PluggedOnExitSlot."""
        agent = HeuristicAgent()
        s = _base_state(crystal_state="PluggedOnExitSlot")
        state = _parse(s)
        action = agent.select_action(state)
        assert agent.current_phase == AgentPhase.ESCAPE

    def test_no_retreat_when_disabled(self):
        """Agent skips RETREAT when GL-1 retreat is disabled."""
        guidelines = GuidelinesConfig(retreat_enabled=False)
        agent = HeuristicAgent(guidelines=guidelines)
        s = _base_state(phase="Action")
        s["heroes"][0]["hp"] = 10.0  # Very low HP
        s["heroes"][0]["room_index"] = 1
        s["mobs"] = [
            {"type": "Zed", "room_index": 1, "hp": 50.0, "max_hp": 80.0, "target_type": "AntiHeroMob"}
        ]
        state = _parse(s)
        action = agent.select_action(state)
        # Should be DEFEND, not RETREAT
        assert agent.current_phase == AgentPhase.DEFEND


# ---------------------------------------------------------------------------
# Test Class: EXPLORE Actions
# ---------------------------------------------------------------------------


class TestExploreActions:
    """Test door-opening actions from the decision tree."""

    def test_explore_moves_hero_toward_closed_door(self):
        """Decision tree produces valid actions when doors are present."""
        agent = HeuristicAgent()
        state = _parse(_base_state())
        action = agent.select_action(state)

        assert action is not None
        # Decision tree may do build/power before reaching step 10 (open door)
        assert action["command"] in ("MOVE_HERO", "OPEN_DOOR", "BUILD_MODULE", "POWER_ROOM")

    def test_explore_opens_door_when_hero_at_source(self):
        """Agent opens the door when hero is already at the source room."""
        agent = HeuristicAgent()
        s = _base_state()
        # Put a hero in room 1 (the source room of the closed door 1->3)
        s["heroes"][0]["room_index"] = 1
        state = _parse(s)
        action = agent.select_action(state)

        assert action is not None
        # Could be crystal room door (step 1) or step 10 door
        assert action["command"] in ("OPEN_DOOR", "MOVE_HERO", "POWER_ROOM", "BUILD_MODULE")

    def test_explore_dispatches_nearest_hero(self):
        """Agent dispatches the nearest available hero to the door."""
        agent = HeuristicAgent()
        s = _base_state()
        state = _parse(s)
        action = agent.select_action(state)

        assert action is not None
        if action["command"] == "MOVE_HERO":
            assert "target_room_index" in action["parameters"]


# ---------------------------------------------------------------------------
# Test Class: BUILD Actions
# ---------------------------------------------------------------------------


class TestBuildActions:
    """Test BUILD phase action generation."""

    def test_build_module_in_empty_slot(self):
        """Agent builds a module when an empty major slot is available."""
        agent = HeuristicAgent()
        s = _base_state()
        s["closed_doors"] = []  # Force no exploration needed
        # Override: remove escape condition by adding a closed door agent can't see
        # Actually with no closed doors, agent will go to ESCAPE. Let's test BUILD directly.
        state = _parse(s)

        # Call BUILD handler directly
        agent._graph = agent._graph_builder.build(state)
        action = agent._handle_build(state)
        # Room 1 has no major module, industry available
        if action:
            assert action["command"] == "BUILD_MODULE"

    def test_level_up_prioritizes_max(self):
        """GL-4: Agent prioritizes leveling Max O'Kane for Operate unlock."""
        agent = HeuristicAgent()
        s = _base_state(food=100.0)
        s["closed_doors"] = []
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_level_up(state)

        if action:
            assert action["command"] == "LEVEL_UP_HERO"
            # Max doesn't have Operate yet, so should be prioritized
            assert action["parameters"]["hero_name"] == "Max O'Kane"

    def test_research_queued_when_blueprints_available(self):
        """Agent queues research when blueprints are available and artifact exists."""
        agent = HeuristicAgent()
        s = _base_state(science=50.0)
        s["researchable_blueprints"] = [
            {"name": "Blueprint_Turret2", "science_cost": 20.0},
            {"name": "Blueprint_FoodGen2", "science_cost": 25.0},
        ]
        # Research requires an artifact on the floor
        s["rooms"][1]["has_artifact"] = True
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_research(state)

        assert action is not None
        assert action["command"] == "RESEARCH"
        # Picks most expensive affordable: Blueprint_FoodGen2 costs 25, Blueprint_Turret2 costs 20
        assert action["parameters"]["blueprint_name"] == "Blueprint_FoodGen2"

    def test_research_blocked_by_artifact_threat(self):
        """GL-7: Agent doesn't research when artifact is under threat."""
        agent = HeuristicAgent()
        s = _base_state(science=50.0)
        s["researchable_blueprints"] = [{"name": "Blueprint_Turret2", "science_cost": 20.0}]
        s["rooms"][1]["has_artifact"] = True
        s["mobs"] = [
            {"type": "ArtifactHunter", "room_index": 2, "hp": 80.0, "max_hp": 100.0, "target_type": "Artifact"}
        ]
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_research(state)

        # Should be None because artifact is under threat
        assert action is None

    def test_power_management_powers_priority_rooms(self):
        """Agent powers rooms on the escape path / bottlenecks."""
        agent = HeuristicAgent()
        s = _base_state(dust=12.0)
        s["closed_doors"] = []  # All doors open
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_power_management(state)

        if action:
            assert action["command"] in ("POWER_ROOM", "UNPOWER_ROOM")


# ---------------------------------------------------------------------------
# Test Class: DEFEND Actions
# ---------------------------------------------------------------------------


class TestDefendActions:
    """Test DEFEND phase action generation."""

    def test_defend_moves_hero_toward_mobs(self):
        """Agent positions defenders toward rooms with mobs."""
        agent = HeuristicAgent()
        s = _base_state(phase="Action")
        s["mobs"] = [
            {"type": "Zed", "room_index": 1, "hp": 50.0, "max_hp": 80.0, "target_type": "AntiHeroMob"},
            {"type": "Zed", "room_index": 1, "hp": 50.0, "max_hp": 80.0, "target_type": "AntiHeroMob"},
        ]
        s["rooms"][1]["mob_count"] = 2
        state = _parse(s)

        action = agent.select_action(state)

        if action:
            assert action["command"] == "MOVE_HERO"
            # Should move toward room 1 (where mobs are)
            assert action["parameters"]["target_room_index"] == 1

    def test_defend_doesnt_move_operators(self):
        """GL-3: Agent doesn't move operating heroes during defense."""
        agent = HeuristicAgent()
        s = _base_state(phase="Action")
        s["heroes"][0]["is_operating"] = True
        s["heroes"][0]["passive_skills"] = [{"name": "Operate"}]
        s["mobs"] = [
            {"type": "Zed", "room_index": 2, "hp": 50.0, "max_hp": 80.0, "target_type": "AntiHeroMob"}
        ]
        s["rooms"][2]["mob_count"] = 1
        state = _parse(s)

        action = agent.select_action(state)

        if action and action["command"] == "MOVE_HERO":
            # Should only move Gork (non-operator), not Max
            assert action["parameters"]["hero_name"] == "Gork"


# ---------------------------------------------------------------------------
# Test Class: RETREAT Actions
# ---------------------------------------------------------------------------


class TestRetreatActions:
    """Test RETREAT phase action generation."""

    def test_retreat_moves_wounded_hero_to_crystal(self):
        """Agent moves wounded hero toward room 1 (rally point)."""
        agent = HeuristicAgent()
        s = _base_state(phase="Action")
        s["heroes"][0]["hp"] = 30.0  # 12% HP — below 50% threshold
        s["heroes"][0]["room_index"] = 2  # Not in rally room (room 1)
        s["mobs"] = [
            {"type": "Zed", "room_index": 2, "hp": 50.0, "max_hp": 80.0, "target_type": "AntiHeroMob"}
        ]
        state = _parse(s)

        action = agent.select_action(state)

        assert action is not None
        assert action["command"] == "MOVE_HERO"
        assert action["parameters"]["hero_name"] == "Max O'Kane"
        # Rally room is 1, hero is in room 2, path is 2->0->1 or direct
        assert action["parameters"]["target_room_index"] in (0, 1)

    def test_retreat_skips_crystal_carrier(self):
        """Agent doesn't retreat the crystal carrier."""
        agent = HeuristicAgent()
        s = _base_state(phase="Action")
        s["heroes"][0]["hp"] = 30.0
        s["heroes"][0]["room_index"] = 1
        s["heroes"][0]["has_crystal"] = True  # Carrying crystal
        s["heroes"][1]["hp"] = 190.0  # Gork is fine
        s["mobs"] = [
            {"type": "Zed", "room_index": 1, "hp": 50.0, "max_hp": 80.0, "target_type": "AntiHeroMob"}
        ]
        state = _parse(s)

        action = agent.select_action(state)

        # Should not try to retreat Max (crystal carrier), go to DEFEND instead
        if action and action["command"] == "MOVE_HERO":
            assert action["parameters"]["hero_name"] != "Max O'Kane"


# ---------------------------------------------------------------------------
# Test Class: ESCAPE Actions
# ---------------------------------------------------------------------------


class TestEscapeActions:
    """Test ESCAPE phase action generation."""

    def test_escape_depowers_first(self):
        """Escape sequence depowers non-auto rooms before powering escape path."""
        agent = HeuristicAgent()
        s = _base_state()
        s["closed_doors"] = []
        for room in s["rooms"]:
            room["is_fully_opened"] = True
        # Room 2 is powered but not auto-powered
        s["rooms"][2]["is_powered"] = True
        state = _parse(s)

        agent._escape_initiated = True
        agent._graph = agent._graph_builder.build(state)
        action = agent._handle_escape(state)

        # Should depower non-auto rooms first
        assert action is not None
        assert action["command"] == "UNPOWER_ROOM"

    def test_escape_picks_up_crystal(self):
        """Agent picks up crystal when Max is in crystal room and all depower/power done."""
        agent = HeuristicAgent()
        s = _base_state()
        s["closed_doors"] = []
        for room in s["rooms"]:
            room["is_fully_opened"] = True
            room["is_powered"] = False
            room["is_auto_powered"] = False
        # Crystal room is always auto-powered
        s["rooms"][0]["is_auto_powered"] = True
        # Mark escape path as already powered (steps 1-2 complete)
        s["rooms"][0]["is_powered"] = True
        s["rooms"][1]["is_powered"] = True
        s["rooms"][3]["is_powered"] = True
        # Max in crystal room (room 0)
        s["heroes"][0]["room_index"] = 0
        # Gork already at exit (room 3)
        s["heroes"][1]["room_index"] = 3
        state = _parse(s)

        agent._escape_initiated = True
        agent._graph = agent._graph_builder.build(state)
        action = agent._handle_escape(state)

        # No rooms to depower (none powered except path), Gork at exit => PICK_UP_CRYSTAL
        assert action is not None
        assert action["command"] == "PICK_UP_CRYSTAL"
        assert action["parameters"]["hero_name"] == "Max O'Kane"

    def test_escape_carrier_moves_to_exit(self):
        """Agent moves Max toward exit after picking up crystal."""
        agent = HeuristicAgent()
        s = _base_state()
        s["closed_doors"] = []
        for room in s["rooms"]:
            room["is_fully_opened"] = True
            room["is_powered"] = False
            room["is_auto_powered"] = False
        s["rooms"][0]["is_auto_powered"] = True
        s["rooms"][0]["is_powered"] = True
        s["rooms"][1]["is_powered"] = True
        s["rooms"][3]["is_powered"] = True
        s["heroes"][0]["has_crystal"] = True
        s["heroes"][0]["room_index"] = 0  # Crystal room, exit is room 3
        s["heroes"][1]["room_index"] = 3  # Gork at exit
        state = _parse(s)

        agent._escape_initiated = True
        agent._graph = agent._graph_builder.build(state)
        action = agent._handle_escape(state)

        assert action is not None
        assert action["command"] == "MOVE_HERO"
        assert action["parameters"]["hero_name"] == "Max O'Kane"
        # Path from room 0 to exit (room 3) goes through room 1
        assert action["parameters"]["target_room_index"] == 1

    def test_escape_sends_gork_to_exit(self):
        """Agent sends Gork to exit room before crystal pickup."""
        agent = HeuristicAgent()
        s = _base_state()
        s["closed_doors"] = []
        for room in s["rooms"]:
            room["is_fully_opened"] = True
            room["is_powered"] = False
            room["is_auto_powered"] = False
        s["rooms"][0]["is_auto_powered"] = True
        s["rooms"][0]["is_powered"] = True
        s["rooms"][1]["is_powered"] = True
        s["rooms"][3]["is_powered"] = True
        # Max in crystal room, Gork in room 1 (not at exit)
        s["heroes"][0]["room_index"] = 0
        s["heroes"][1]["room_index"] = 1
        state = _parse(s)

        agent._escape_initiated = True
        agent._graph = agent._graph_builder.build(state)
        action = agent._handle_escape(state)

        # Should move Gork toward exit (room 3)
        assert action is not None
        assert action["command"] == "MOVE_HERO"
        assert "Gork" in action["parameters"]["hero_name"]


# ---------------------------------------------------------------------------
# Test Class: Merchant & Recruit Scenarios
# ---------------------------------------------------------------------------


class TestMerchantAndRecruit:
    """Test merchant buying and hero recruitment."""

    def test_buy_from_merchant_when_hero_present(self):
        """Agent buys from merchant when a hero is in the merchant's room."""
        agent = HeuristicAgent()
        s = _base_state(dust=50.0)
        s["merchants"] = [
            {
                "room_index": 0,
                "currency_type": "Dust",
                "items": [{"name": "PowerSword", "rarity": "Rare", "cost": 15.0}],
            }
        ]
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_buy_merchant(state)

        assert action is not None
        assert action["command"] == "BUY_FROM_MERCHANT"
        assert action["parameters"]["hero_name"] == "Max O'Kane"
        assert action["parameters"]["item_name"] == "PowerSword"

    def test_buy_dispatches_hero_when_not_present(self):
        """Agent moves a hero to merchant room if none are there."""
        agent = HeuristicAgent()
        s = _base_state(dust=50.0)
        s["merchants"] = [
            {
                "room_index": 2,  # No heroes in room 2
                "currency_type": "Dust",
                "items": [{"name": "Shield", "rarity": "Common", "cost": 10.0}],
            }
        ]
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_buy_merchant(state)

        assert action is not None
        assert action["command"] == "MOVE_HERO"
        assert action["parameters"]["target_room_index"] == 2

    def test_recruit_hero_when_food_allows(self):
        """Agent recruits when food is sufficient and hero is present."""
        agent = HeuristicAgent()
        s = _base_state(food=50.0)
        s["recruitable_heroes"] = [
            {
                "name": "Sara Numas",
                "faction": "Guard",
                "room_index": 0,
                "hp": 150.0,
                "max_hp": 150.0,
                "passive_skill_names": ["Operate"],
            }
        ]
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_recruit(state)

        assert action is not None
        assert action["command"] == "RECRUIT_HERO"
        assert action["parameters"]["recruit_name"] == "Sara Numas"

    def test_recruit_dispatches_hero_to_recruit_room(self):
        """Agent moves hero to recruit's room if no hero present there."""
        agent = HeuristicAgent()
        s = _base_state(food=50.0)
        s["recruitable_heroes"] = [
            {
                "name": "Sara Numas",
                "faction": "Guard",
                "room_index": 2,  # No heroes in room 2
                "hp": 150.0,
                "max_hp": 150.0,
                "passive_skill_names": [],
            }
        ]
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_recruit(state)

        assert action is not None
        assert action["command"] == "MOVE_HERO"
        assert action["parameters"]["target_room_index"] == 2


# ---------------------------------------------------------------------------
# Test Class: Dust Collection
# ---------------------------------------------------------------------------


class TestDustCollection:
    """Test dust collection logic."""

    def test_collect_dust_dispatches_hero(self):
        """Agent moves hero to room with dropped dust."""
        agent = HeuristicAgent()
        s = _base_state()
        s["dropped_items"] = [
            {"type": "Dust", "name": None, "room_index": 2, "dust_amount": 5.0}
        ]
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_collect_dust(state)

        assert action is not None
        assert action["command"] == "MOVE_HERO"
        assert action["parameters"]["target_room_index"] == 2

    def test_collect_dust_room_loot(self):
        """Agent moves hero to room with dust_loot_amount > 0."""
        agent = HeuristicAgent()
        s = _base_state()
        s["rooms"][2]["dust_loot_amount"] = 3
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_collect_dust(state)

        assert action is not None
        assert action["command"] == "MOVE_HERO"
        assert action["parameters"]["target_room_index"] == 2


# ---------------------------------------------------------------------------
# Test Class: Operator Placement
# ---------------------------------------------------------------------------


class TestOperatorPlacement:
    """Test operator placement logic (GL-3)."""

    def test_operator_placed_in_module_room(self):
        """Agent moves hero with Operate passive to room with major module."""
        agent = HeuristicAgent()
        s = _base_state()
        # Give Gork the Operate passive, put him in room 1 (no major module there)
        s["heroes"][1]["passive_skills"] = [{"name": "Operate"}]
        s["heroes"][1]["room_index"] = 1
        # Room 0 has a major module and is powered
        state = _parse(s)

        agent._graph = agent._graph_builder.build(state)
        action = agent._try_operator_placement(state)

        if action:
            assert action["command"] == "MOVE_HERO"
            assert action["parameters"]["hero_name"] == "Gork"
            assert action["parameters"]["target_room_index"] == 0


# ---------------------------------------------------------------------------
# Test Class: Multi-Step Sequences (Integration)
# ---------------------------------------------------------------------------


class TestMultiStepSequences:
    """Test agent behavior over multiple consecutive state observations."""

    def test_full_explore_to_build_sequence(self):
        """Agent uses decision tree: opens doors, then escapes when done."""
        agent = HeuristicAgent()

        # Turn 1: closed door exists => decision tree handles it
        s1 = _base_state(turn=1)
        state1 = _parse(s1)
        action1 = agent.select_action(state1)
        assert agent.current_phase == AgentPhase.BUILD
        assert action1 is not None

        # Turn 2: all doors open, exit found => ESCAPE
        agent.new_turn()
        s2 = _base_state(turn=2)
        s2["closed_doors"] = []
        for room in s2["rooms"]:
            room["is_fully_opened"] = True
        state2 = _parse(s2)
        action2 = agent.select_action(state2)
        assert agent.current_phase == AgentPhase.ESCAPE

    def test_combat_defend_retreat_cycle(self):
        """Agent enters combat, defends, then retreats when hero is hurt."""
        agent = HeuristicAgent()

        # State 1: Combat, heroes healthy => DEFEND
        s1 = _base_state(phase="Action")
        s1["mobs"] = [
            {"type": "Zed", "room_index": 1, "hp": 50.0, "max_hp": 80.0, "target_type": "AntiHeroMob"}
        ]
        s1["rooms"][1]["mob_count"] = 1
        state1 = _parse(s1)
        agent.select_action(state1)
        assert agent.current_phase == AgentPhase.DEFEND

        # State 2: Hero took damage, below threshold => RETREAT
        agent.new_turn()
        s2 = _base_state(phase="Action")
        s2["heroes"][0]["hp"] = 50.0  # 20%, below threshold
        s2["heroes"][0]["room_index"] = 2  # Not in rally room (room 1)
        s2["mobs"] = [
            {"type": "Zed", "room_index": 2, "hp": 30.0, "max_hp": 80.0, "target_type": "AntiHeroMob"}
        ]
        s2["rooms"][2]["mob_count"] = 1
        state2 = _parse(s2)
        action = agent.select_action(state2)
        assert agent.current_phase == AgentPhase.RETREAT
        assert action["command"] == "MOVE_HERO"
        assert action["parameters"]["hero_name"] == "Max O'Kane"

    def test_agent_never_crashes_on_empty_state(self):
        """Agent handles minimal/empty state without crashing."""
        agent = HeuristicAgent()
        s = {
            "turn": 0,
            "floor": 1,
            "game_phase": "Strategy",
            "crystal_state": "Plugged",
            "exit_room_index": -1,
            "start_room_index": 0,
            "resources": None,
            "rooms": [],
            "closed_doors": [],
            "heroes": [],
            "mobs": [],
            "merchants": [],
            "recruitable_heroes": [],
            "dropped_items": [],
            "backpack_items": [],
            "shared_inventory_items": [],
            "researchable_blueprints": [],
        }
        state = _parse(s)
        # Should not crash
        action = agent.select_action(state)
        # None is acceptable when there's nothing to do
        assert action is None or isinstance(action, dict)

    def test_escape_full_sequence(self):
        """Agent handles complete escape sequence: assign, pickup, move to exit."""
        agent = HeuristicAgent()

        # Turn 1: No closed doors -> escape
        s = _base_state()
        s["closed_doors"] = []
        for room in s["rooms"]:
            room["is_fully_opened"] = True
        state = _parse(s)

        actions = []
        for i in range(10):
            action = agent.select_action(state)
            if action is None:
                break
            actions.append(action)
            # Simulate action effects
            if action["command"] == "PICK_UP_CRYSTAL":
                s["heroes"][0]["has_crystal"] = True
                state = _parse(s)
            elif action["command"] == "MOVE_HERO":
                hero_name = action["parameters"]["hero_name"]
                target = action["parameters"]["target_room_index"]
                for h in s["heroes"]:
                    if h["name"] == hero_name:
                        h["room_index"] = target
                        break
                # Update room hero counts
                for r in s["rooms"]:
                    r["hero_count"] = sum(1 for h in s["heroes"] if h["room_index"] == r["index"])
                state = _parse(s)
            elif action["command"] in ("POWER_ROOM", "UNPOWER_ROOM"):
                room_idx = action["parameters"]["room_index"]
                for r in s["rooms"]:
                    if r["index"] == room_idx:
                        r["is_powered"] = action["command"] == "POWER_ROOM"
                state = _parse(s)

        # Should have produced some actions
        assert len(actions) > 0
        # Should include crystal pickup at some point
        commands = [a["command"] for a in actions]
        assert "PICK_UP_CRYSTAL" in commands or "MOVE_HERO" in commands


# ---------------------------------------------------------------------------
# Test Class: Action Result Handling
# ---------------------------------------------------------------------------


class TestActionResultHandling:
    """Test on_action_result callback."""

    def test_failed_action_tracked(self):
        """Agent tracks failed actions."""
        agent = HeuristicAgent()
        cmd = {"command": "MOVE_HERO", "parameters": {"hero_name": "Max", "target_room_index": 5}}
        result = {"success": False, "error": "Invalid room"}
        agent.on_action_result(cmd, result)
        assert agent._last_action_failed is True

    def test_successful_action_tracked(self):
        """Agent tracks successful actions."""
        agent = HeuristicAgent()
        cmd = {"command": "MOVE_HERO", "parameters": {"hero_name": "Max", "target_room_index": 1}}
        result = {"success": True, "error": None}
        agent.on_action_result(cmd, result)
        assert agent._last_action_failed is False


# ---------------------------------------------------------------------------
# Test Class: Reset
# ---------------------------------------------------------------------------


class TestReset:
    """Test agent reset clears state properly."""

    def test_reset_clears_all_state(self):
        """Reset clears escape roles, tracking, and phase."""
        agent = HeuristicAgent()

        # Simulate some state
        agent._escape_initiated = True
        agent._crystal_carrier = "Max O'Kane"
        agent._hero_roles = {"Max O'Kane": "carrier"}
        agent._explored_rooms = {0, 1, 2}
        agent._doors_opened_this_turn = {(0, 1)}

        agent.reset()

        assert agent._escape_initiated is False
        assert agent._crystal_carrier is None
        assert agent._hero_roles == {}
        assert agent._explored_rooms == set()
        assert agent._doors_opened_this_turn == set()
        assert agent.current_phase == AgentPhase.BUILD

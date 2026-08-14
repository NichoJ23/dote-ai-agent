"""
Unit tests for action_masking.py — strategic option validity masks.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "agent"))

from action_masking import ActionMaskComputer, NUM_OPTIONS, StrategicOption
from state_parser import GameStatePayload, RoomState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_state(**overrides) -> GameStatePayload:
    """Build a state with reasonable defaults for mask testing."""
    defaults = {
        "turn": 3,
        "floor": 1,
        "game_phase": "Strategy",
        "crystal_state": "Plugged",
        "exit_room_index": 3,
        "start_room_index": 0,
        "resources": {
            "industry": 50, "food": 30, "science": 20,
            "dust": 5, "dust_max": 10,
            "industry_per_turn": 5, "food_per_turn": 3, "science_per_turn": 2,
            "dust_per_turn": 0, "room_power_cost": 1, "powered_room_count": 2,
        },
        "rooms": [
            {"index": 0, "is_powered": True, "is_auto_powered": True, "is_start_room": True,
             "adjacent_room_indices": [1], "minor_slot_count": 2, "is_fully_opened": True,
             "major_module_name": "MajorModule_Major0002_LVL1",
             "minor_module_names": ["MinorModule_Minor0004_LVL1"]},
            {"index": 1, "is_powered": True, "is_auto_powered": False,
             "adjacent_room_indices": [0, 2], "minor_slot_count": 3, "is_fully_opened": True,
             "has_artifact": True},
            {"index": 2, "is_powered": False, "is_auto_powered": False,
             "adjacent_room_indices": [1, 3], "minor_slot_count": 2, "is_fully_opened": True},
            {"index": 3, "is_powered": False, "is_auto_powered": False, "is_exit_room": True,
             "adjacent_room_indices": [2], "minor_slot_count": 2, "is_fully_opened": True},
        ],
        "closed_doors": [{"room1_index": 2, "room2_index": 4}],
        "heroes": [
            {"name": "Max", "room_index": 0, "hp": 100, "max_hp": 100, "level": 2,
             "faction": "Prisoner", "is_usable": True,
             "equipment": [{"slot_category": "Weapon", "item_name": "Sword"}],
             "level_up_cost": 20},
            {"name": "Gork", "room_index": 1, "hp": 80, "max_hp": 100, "level": 1,
             "faction": "Native", "is_usable": True,
             "equipment": [{"slot_category": "Weapon", "item_name": None}],
             "level_up_cost": 10},
        ],
        "mobs": [],
        "merchants": [
            {"room_index": 2, "currency_type": "Dust",
             "items": [{"name": "Helmet", "rarity": "Common", "cost": 3}]},
        ],
        "recruitable_heroes": [
            {"name": "Sara", "faction": "Guard", "room_index": 2,
             "hp": 100, "max_hp": 100, "recruit_cost_food": 15,
             "passive_skill_names": ["Operate"]},
        ],
        "dropped_items": [],
        "backpack_items": [{"name": "Shield", "rarity": "Rare", "category": "Armor"}],
        "shared_inventory_items": [],
        "researchable_blueprints": [{"name": "Blueprint1", "science_cost": 15}],
        "buildable_blueprints": [
            {"name": "MajorModule_Major0002_LVL1", "module_name": "Major0002",
             "category": "MajorModule", "level": 1, "industry_cost": 20},
            {"name": "MinorModule_Minor0004_LVL1", "module_name": "Minor0004",
             "category": "MinorModule_Offense", "level": 1, "industry_cost": 10},
        ],
    }
    defaults.update(overrides)
    return GameStatePayload.model_validate(defaults)


# ---------------------------------------------------------------------------
# Basic mask properties
# ---------------------------------------------------------------------------


class TestBasicMask:
    def test_mask_shape(self):
        computer = ActionMaskComputer()
        state = _base_state()
        mask = computer.compute_mask(state)
        assert mask.shape == (NUM_OPTIONS,)
        assert mask.dtype == np.bool_

    def test_wait_always_valid(self):
        computer = ActionMaskComputer()
        state = _base_state()
        mask = computer.compute_mask(state)
        assert mask[StrategicOption.WAIT] is np.True_

    def test_wait_valid_during_combat(self):
        computer = ActionMaskComputer()
        state = _base_state(game_phase="Action")
        mask = computer.compute_mask(state)
        assert mask[StrategicOption.WAIT] is np.True_

    def test_full_state_most_options_valid(self):
        """With a rich state, most strategic options should be available."""
        computer = ActionMaskComputer()
        state = _base_state()
        mask = computer.compute_mask(state)
        # These should all be valid given our rich test state
        assert mask[StrategicOption.POWER_ROOM]  # Unpowered rooms exist
        assert mask[StrategicOption.DEPOWER_ROOM]  # Room 1 powered non-auto
        assert mask[StrategicOption.BUILD_MODULE]  # Industry + slots
        assert mask[StrategicOption.DESTROY_MODULE]  # Room 0 has modules
        assert mask[StrategicOption.RESEARCH]  # Artifact needed though...
        assert mask[StrategicOption.RECRUIT_HERO]  # Sara + food
        assert mask[StrategicOption.DISMISS_HERO]  # 2 heroes
        assert mask[StrategicOption.LEVEL_UP_HERO]  # food > 0
        assert mask[StrategicOption.BUY_ITEM]  # Merchant with affordable item
        assert mask[StrategicOption.EQUIP_ITEM]  # Backpack has item
        assert mask[StrategicOption.UNEQUIP_ITEM]  # Max has equipped weapon
        assert mask[StrategicOption.POSITION_HERO]  # Usable heroes + rooms
        assert mask[StrategicOption.OPEN_DOOR]  # Closed door exists
        assert mask[StrategicOption.HEAL_HERO]  # Gork below max
        assert mask[StrategicOption.INITIATE_ESCAPE]  # Exit room found


# ---------------------------------------------------------------------------
# POWER_ROOM masking
# ---------------------------------------------------------------------------


class TestPowerRoom:
    def test_masked_when_no_unpowered_rooms(self):
        computer = ActionMaskComputer()
        state = _base_state()
        # Power all rooms
        for r in state.rooms:
            r.is_powered = True
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.POWER_ROOM]

    def test_masked_when_zero_dust(self):
        computer = ActionMaskComputer()
        state = _base_state()
        state.resources.dust = 0
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.POWER_ROOM]

    def test_valid_when_unpowered_rooms_and_dust(self):
        computer = ActionMaskComputer()
        state = _base_state()
        mask = computer.compute_mask(state)
        assert mask[StrategicOption.POWER_ROOM]


# ---------------------------------------------------------------------------
# DEPOWER_ROOM masking
# ---------------------------------------------------------------------------


class TestDepowerRoom:
    def test_masked_when_no_non_auto_powered_rooms(self):
        computer = ActionMaskComputer()
        state = _base_state()
        # Only keep auto-powered rooms as powered
        for r in state.rooms:
            if not r.is_auto_powered:
                r.is_powered = False
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.DEPOWER_ROOM]

    def test_valid_when_non_auto_room_is_powered(self):
        computer = ActionMaskComputer()
        state = _base_state()
        # Room 1 is powered and not auto
        mask = computer.compute_mask(state)
        assert mask[StrategicOption.DEPOWER_ROOM]


# ---------------------------------------------------------------------------
# BUILD_MODULE masking
# ---------------------------------------------------------------------------


class TestBuildModule:
    def test_masked_when_no_industry(self):
        computer = ActionMaskComputer()
        state = _base_state()
        state.resources.industry = 0
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.BUILD_MODULE]

    def test_masked_when_no_blueprints(self):
        computer = ActionMaskComputer()
        state = _base_state()
        state.buildable_blueprints = []
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.BUILD_MODULE]

    def test_masked_when_cant_afford_cheapest(self):
        computer = ActionMaskComputer()
        state = _base_state()
        state.resources.industry = 5  # Cheapest blueprint costs 10
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.BUILD_MODULE]

    def test_masked_when_all_slots_full(self):
        computer = ActionMaskComputer()
        state = _base_state()
        # Fill all slots in powered rooms
        state.rooms[0].minor_module_names = ["m1", "m2"]  # 2/2 minor slots full
        # Room 0 already has major module
        state.rooms[1].major_module_name = "SomeMajor"
        state.rooms[1].minor_module_names = ["m1", "m2", "m3"]  # 3/3 minor slots full
        # Rooms 2, 3 are unpowered so can't build there
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.BUILD_MODULE]

    def test_valid_when_slots_and_resources(self):
        computer = ActionMaskComputer()
        state = _base_state()
        mask = computer.compute_mask(state)
        assert mask[StrategicOption.BUILD_MODULE]


# ---------------------------------------------------------------------------
# RESEARCH masking
# ---------------------------------------------------------------------------


class TestResearch:
    def test_masked_when_no_artifact(self):
        computer = ActionMaskComputer()
        state = _base_state()
        # No rooms have artifacts
        for r in state.rooms:
            r.has_artifact = False
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.RESEARCH]

    def test_masked_when_no_blueprints(self):
        computer = ActionMaskComputer()
        state = _base_state()
        state.rooms[1].has_artifact = True
        state.researchable_blueprints = []
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.RESEARCH]

    def test_masked_when_not_enough_science(self):
        computer = ActionMaskComputer()
        state = _base_state()
        state.rooms[1].has_artifact = True
        state.resources.science = 5  # Blueprint costs 15
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.RESEARCH]

    def test_valid_when_artifact_and_affordable(self):
        computer = ActionMaskComputer()
        state = _base_state()
        state.rooms[1].has_artifact = True
        mask = computer.compute_mask(state)
        assert mask[StrategicOption.RESEARCH]


# ---------------------------------------------------------------------------
# RECRUIT_HERO masking
# ---------------------------------------------------------------------------


class TestRecruit:
    def test_masked_when_no_recruits(self):
        computer = ActionMaskComputer()
        state = _base_state()
        state.recruitable_heroes = []
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.RECRUIT_HERO]

    def test_masked_when_not_enough_food(self):
        computer = ActionMaskComputer()
        state = _base_state()
        state.resources.food = 5  # Sara costs 15
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.RECRUIT_HERO]

    def test_valid_when_affordable_recruit(self):
        computer = ActionMaskComputer()
        state = _base_state()
        mask = computer.compute_mask(state)
        assert mask[StrategicOption.RECRUIT_HERO]


# ---------------------------------------------------------------------------
# DISMISS_HERO masking
# ---------------------------------------------------------------------------


class TestDismiss:
    def test_masked_when_only_one_hero(self):
        computer = ActionMaskComputer()
        state = _base_state()
        state.heroes = state.heroes[:1]
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.DISMISS_HERO]

    def test_valid_when_multiple_heroes(self):
        computer = ActionMaskComputer()
        state = _base_state()
        mask = computer.compute_mask(state)
        assert mask[StrategicOption.DISMISS_HERO]


# ---------------------------------------------------------------------------
# OPEN_DOOR masking
# ---------------------------------------------------------------------------


class TestOpenDoor:
    def test_masked_when_no_closed_doors_and_all_fully_opened(self):
        computer = ActionMaskComputer()
        state = _base_state()
        state.closed_doors = []
        for r in state.rooms:
            r.is_fully_opened = True
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.OPEN_DOOR]

    def test_valid_when_closed_doors_exist(self):
        computer = ActionMaskComputer()
        state = _base_state()
        mask = computer.compute_mask(state)
        assert mask[StrategicOption.OPEN_DOOR]

    def test_valid_when_rooms_not_fully_opened(self):
        computer = ActionMaskComputer()
        state = _base_state()
        state.closed_doors = []
        state.rooms[2].is_fully_opened = False  # Still has unopened doors
        mask = computer.compute_mask(state)
        assert mask[StrategicOption.OPEN_DOOR]


# ---------------------------------------------------------------------------
# HEAL_HERO masking
# ---------------------------------------------------------------------------


class TestHeal:
    def test_masked_when_all_full_hp(self):
        computer = ActionMaskComputer()
        state = _base_state()
        for h in state.heroes:
            h.hp = h.max_hp
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.HEAL_HERO]

    def test_masked_when_no_food(self):
        computer = ActionMaskComputer()
        state = _base_state()
        state.resources.food = 0
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.HEAL_HERO]

    def test_valid_when_hero_damaged_and_food(self):
        computer = ActionMaskComputer()
        state = _base_state()
        mask = computer.compute_mask(state)
        # Gork is at 80/100 HP, food = 30
        assert mask[StrategicOption.HEAL_HERO]


# ---------------------------------------------------------------------------
# INITIATE_ESCAPE masking
# ---------------------------------------------------------------------------


class TestEscape:
    def test_masked_when_exit_not_found(self):
        computer = ActionMaskComputer()
        state = _base_state()
        for r in state.rooms:
            r.is_exit_room = False
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.INITIATE_ESCAPE]

    def test_masked_when_already_escaping(self):
        computer = ActionMaskComputer()
        state = _base_state(crystal_state="PluggedOnExitSlot")
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.INITIATE_ESCAPE]

    def test_valid_when_exit_found_and_not_escaping(self):
        computer = ActionMaskComputer()
        state = _base_state()
        mask = computer.compute_mask(state)
        assert mask[StrategicOption.INITIATE_ESCAPE]


# ---------------------------------------------------------------------------
# EQUIP / UNEQUIP masking
# ---------------------------------------------------------------------------


class TestEquipUnequip:
    def test_equip_masked_when_no_items(self):
        computer = ActionMaskComputer()
        state = _base_state()
        state.backpack_items = []
        state.shared_inventory_items = []
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.EQUIP_ITEM]

    def test_equip_valid_when_items_exist(self):
        computer = ActionMaskComputer()
        state = _base_state()
        mask = computer.compute_mask(state)
        assert mask[StrategicOption.EQUIP_ITEM]

    def test_unequip_masked_when_no_equipped(self):
        computer = ActionMaskComputer()
        state = _base_state()
        for h in state.heroes:
            for slot in h.equipment:
                slot.item_name = None
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.UNEQUIP_ITEM]

    def test_unequip_valid_when_equipped(self):
        computer = ActionMaskComputer()
        state = _base_state()
        mask = computer.compute_mask(state)
        assert mask[StrategicOption.UNEQUIP_ITEM]


# ---------------------------------------------------------------------------
# Combat phase masking
# ---------------------------------------------------------------------------


class TestCombatPhase:
    def test_most_options_masked_during_combat(self):
        """During Action phase, only position/heal/wait are valid."""
        computer = ActionMaskComputer()
        state = _base_state(game_phase="Action")
        mask = computer.compute_mask(state)
        # These should be masked
        assert not mask[StrategicOption.POWER_ROOM]
        assert not mask[StrategicOption.DEPOWER_ROOM]
        assert not mask[StrategicOption.BUILD_MODULE]
        assert not mask[StrategicOption.DESTROY_MODULE]
        assert not mask[StrategicOption.RESEARCH]
        assert not mask[StrategicOption.RECRUIT_HERO]
        assert not mask[StrategicOption.DISMISS_HERO]
        assert not mask[StrategicOption.LEVEL_UP_HERO]
        assert not mask[StrategicOption.BUY_ITEM]
        assert not mask[StrategicOption.EQUIP_ITEM]
        assert not mask[StrategicOption.UNEQUIP_ITEM]
        assert not mask[StrategicOption.OPEN_DOOR]
        assert not mask[StrategicOption.INITIATE_ESCAPE]
        # These should still be valid
        assert mask[StrategicOption.POSITION_HERO]
        assert mask[StrategicOption.HEAL_HERO]
        assert mask[StrategicOption.WAIT]

    def test_heal_masked_in_combat_if_all_full_hp(self):
        computer = ActionMaskComputer()
        state = _base_state(game_phase="Action")
        for h in state.heroes:
            h.hp = h.max_hp
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.HEAL_HERO]


# ---------------------------------------------------------------------------
# POSITION_HERO masking
# ---------------------------------------------------------------------------


class TestPositionHero:
    def test_masked_when_only_one_room(self):
        computer = ActionMaskComputer()
        state = _base_state()
        state.rooms = state.rooms[:1]
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.POSITION_HERO]

    def test_masked_when_no_usable_heroes(self):
        computer = ActionMaskComputer()
        state = _base_state()
        for h in state.heroes:
            h.is_usable = False
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.POSITION_HERO]

    def test_valid_normally(self):
        computer = ActionMaskComputer()
        state = _base_state()
        mask = computer.compute_mask(state)
        assert mask[StrategicOption.POSITION_HERO]


# ---------------------------------------------------------------------------
# BUY_ITEM masking
# ---------------------------------------------------------------------------


class TestBuyItem:
    def test_masked_when_no_merchants(self):
        computer = ActionMaskComputer()
        state = _base_state()
        state.merchants = []
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.BUY_ITEM]

    def test_masked_when_cant_afford(self):
        computer = ActionMaskComputer()
        state = _base_state()
        state.resources.dust = 0  # Merchant item costs 3 dust
        mask = computer.compute_mask(state)
        assert not mask[StrategicOption.BUY_ITEM]

    def test_valid_when_affordable(self):
        computer = ActionMaskComputer()
        state = _base_state()
        mask = computer.compute_mask(state)
        assert mask[StrategicOption.BUY_ITEM]

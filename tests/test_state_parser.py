"""
Unit tests for StateParser.

Tests the ACTUAL wire format produced by src/mod/Ipc/JsonSerializer.cs.
Covers: rooms, heroes, mobs, merchants, recruits, dropped items, backpack,
shared inventory, passive/active skills, equipment, resources, closed doors.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "agent"))

from pydantic import ValidationError

from state_parser import (
    ActiveSkill,
    BackpackItem,
    ClosedDoor,
    DroppedItem,
    EquipmentSlot,
    GamePhase,
    GameStatePayload,
    HeroState,
    MerchantItem,
    MerchantState,
    MobState,
    PassiveSkill,
    RecruitableHero,
    ResourceState,
    RoomState,
    StateParser,
)


# --- Fixtures ---


def _full_state_dict():
    """A complete state dict matching the actual mod output format."""
    return {
        "turn": 7,
        "floor": 2,
        "game_phase": "Action",
        "crystal_state": "Plugged",
        "exit_room_index": 4,
        "start_room_index": 0,
        "resources": {
            "industry": 55.0,
            "food": 30.0,
            "science": 22.0,
            "dust": 9.0,
            "dust_max": 14.0,
            "industry_per_turn": 7.0,
            "food_per_turn": 4.0,
            "science_per_turn": 3.0,
            "dust_per_turn": 1.0,
            "room_power_cost": 1.0,
            "powered_room_count": 3,
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
                "major_module_name": "IndustryGenerator",
                "minor_module_names": ["FoodModule"],
                "minor_slot_count": 4,
                "hero_count": 1,
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
                "suffers_emp": True,
                "emp_turns_remaining": 2,
                "dust_loot_amount": 3,
                "has_artifact": True,
                "has_stele": False,
                "adjacent_room_indices": [0, 3],
                "major_module_name": None,
                "minor_module_names": [],
                "minor_slot_count": 2,
                "hero_count": 1,
                "mob_count": 2,
                "npc_count": 1,
            },
        ],
        "closed_doors": [
            {"room1_index": 1, "room2_index": 3, "is_opening": False},
        ],
        "heroes": [
            {
                "name": "Max O'Kane",
                "faction": "Prisoner",
                "room_index": 0,
                "hp": 180.5,
                "max_hp": 250.0,
                "level": 3,
                "has_crystal": False,
                "is_operating": True,
                "operating_module_name": "IndustryGenerator",
                "is_recruitable": False,
                "is_recruited": True,
                "active_skills": [
                    {"name": "Punch", "cooldown_turns": 3, "remaining_cooldown": 0, "is_activated": False},
                    {"name": "War Cry", "cooldown_turns": 5, "remaining_cooldown": 2, "is_activated": False},
                ],
                "passive_skills": [
                    {"name": "Operate"},
                    {"name": "Repair"},
                ],
                "equipment": [
                    {"slot_category": "Weapon", "item_name": "Crystal Blade"},
                    {"slot_category": "Armor", "item_name": None},
                    {"slot_category": "Accessory", "item_name": "Speed Ring"},
                ],
            },
            {
                "name": "Gork",
                "faction": "Native",
                "room_index": 1,
                "hp": 300.0,
                "max_hp": 300.0,
                "level": 2,
                "has_crystal": False,
                "is_operating": False,
                "operating_module_name": None,
                "is_recruitable": False,
                "is_recruited": True,
                "active_skills": [
                    {"name": "Rage", "cooldown_turns": 4, "remaining_cooldown": 3, "is_activated": False},
                ],
                "passive_skills": [{"name": "Fast"}],
                "equipment": [
                    {"slot_category": "Weapon", "item_name": "Battle Axe"},
                ],
            },
        ],
        "mobs": [
            {"type": "Silic Zoner", "room_index": 1, "hp": 45.0, "max_hp": 80.0, "target_type": "AntiHeroMob"},
            {"type": "Necrophage", "room_index": 1, "hp": 60.0, "max_hp": 60.0, "target_type": "Crystal"},
        ],
        "merchants": [
            {
                "room_index": 0,
                "currency_type": "Dust",
                "items": [
                    {"name": "Titanium Plate", "rarity": "Uncommon", "cost": 7.0},
                    {"name": "Jet Boots", "rarity": "Common", "cost": 5.0},
                ],
            }
        ],
        "recruitable_heroes": [
            {
                "name": "Sara Numas",
                "faction": "Mezari",
                "room_index": 1,
                "hp": 120.0,
                "max_hp": 120.0,
                "passive_skill_names": ["Operate", "Heal"],
            }
        ],
        "dropped_items": [
            {"type": "Dust", "name": None, "room_index": 1, "dust_amount": 4.0},
            {"type": "Equipment", "name": "Old Shield", "room_index": 0, "dust_amount": 0.0},
        ],
        "backpack_items": [
            {"name": "Ancient Relic", "rarity": "Legendary", "category": "Accessory"},
        ],
        "shared_inventory_items": [
            {"name": "Rusty Sword", "rarity": "Common", "category": "Weapon"},
            {"name": "Leather Vest", "rarity": "Common", "category": "Armor"},
        ],
        "researchable_blueprints": [
            {"name": "LaserTurret", "science_cost": 20.0},
            {"name": "ShieldModule", "science_cost": 15.0},
            {"name": "FoodGen_Mk2", "science_cost": 30.0},
        ],
    }


@pytest.fixture
def parser():
    return StateParser()


@pytest.fixture
def full_state(parser):
    return parser.parse(_full_state_dict())


# --- Tests ---


class TestBasicParsing:
    def test_parse_turn(self, full_state):
        assert full_state.turn == 7

    def test_parse_floor(self, full_state):
        assert full_state.floor == 2

    def test_parse_game_phase_action(self, full_state):
        assert full_state.game_phase == GamePhase.ACTION

    def test_parse_game_phase_strategy(self, parser):
        raw = _full_state_dict()
        raw["game_phase"] = "Strategy"
        state = parser.parse(raw)
        assert state.game_phase == GamePhase.STRATEGY

    def test_parse_crystal_state(self, full_state):
        assert full_state.crystal_state == "Plugged"

    def test_parse_exit_room_index(self, full_state):
        assert full_state.exit_room_index == 4

    def test_parse_start_room_index(self, full_state):
        assert full_state.start_room_index == 0

    def test_is_crystal_safe(self, full_state):
        assert full_state.is_crystal_safe is True

    def test_is_game_over(self, parser):
        raw = _full_state_dict()
        raw["crystal_state"] = "Unplugged"
        state = parser.parse(raw)
        assert state.is_game_over is True

    def test_is_escaping(self, parser):
        raw = _full_state_dict()
        raw["crystal_state"] = "PluggedOnExitSlot"
        state = parser.parse(raw)
        assert state.is_escaping is True


class TestResources:
    def test_resource_values(self, full_state):
        r = full_state.resources
        assert r.industry == 55.0
        assert r.food == 30.0
        assert r.science == 22.0
        assert r.dust == 9.0
        assert r.dust_max == 14.0

    def test_per_turn_rates(self, full_state):
        r = full_state.resources
        assert r.industry_per_turn == 7.0
        assert r.food_per_turn == 4.0
        assert r.science_per_turn == 3.0
        assert r.dust_per_turn == 1.0

    def test_power_info(self, full_state):
        r = full_state.resources
        assert r.room_power_cost == 1.0
        assert r.powered_room_count == 3

    def test_null_resources(self, parser):
        raw = _full_state_dict()
        raw["resources"] = None
        state = parser.parse(raw)
        assert state.resources is None


class TestRooms:
    def test_room_count(self, full_state):
        assert len(full_state.rooms) == 2

    def test_room_index(self, full_state):
        assert full_state.rooms[0].index == 0
        assert full_state.rooms[1].index == 1

    def test_room_power_state(self, full_state):
        assert full_state.rooms[0].is_powered is True
        assert full_state.rooms[0].is_auto_powered is True

    def test_room_start_exit(self, full_state):
        assert full_state.rooms[0].is_start_room is True
        assert full_state.rooms[0].is_exit_room is False

    def test_room_adjacency(self, full_state):
        assert full_state.rooms[0].adjacent_room_indices == [1, 2]
        assert full_state.rooms[1].adjacent_room_indices == [0, 3]

    def test_room_modules(self, full_state):
        r0 = full_state.rooms[0]
        assert r0.major_module_name == "IndustryGenerator"
        assert r0.minor_module_names == ["FoodModule"]
        assert r0.minor_slot_count == 4

    def test_room_emp(self, full_state):
        assert full_state.rooms[1].suffers_emp is True
        assert full_state.rooms[1].emp_turns_remaining == 2

    def test_room_artifact(self, full_state):
        assert full_state.rooms[1].has_artifact is True

    def test_room_unit_counts(self, full_state):
        assert full_state.rooms[0].hero_count == 1
        assert full_state.rooms[1].mob_count == 2
        assert full_state.rooms[1].npc_count == 1


class TestClosedDoors:
    def test_closed_door_count(self, full_state):
        assert len(full_state.closed_doors) == 1

    def test_closed_door_indices(self, full_state):
        door = full_state.closed_doors[0]
        assert door.room1_index == 1
        assert door.room2_index == 3
        assert door.is_opening is False


class TestHeroes:
    def test_hero_count(self, full_state):
        assert len(full_state.heroes) == 2

    def test_hero_basic_stats(self, full_state):
        hero = full_state.heroes[0]
        assert hero.name == "Max O'Kane"
        assert hero.hp == 180.5
        assert hero.max_hp == 250.0
        assert hero.level == 3
        assert hero.room_index == 0

    def test_hero_faction(self, full_state):
        assert full_state.heroes[0].faction == "Prisoner"
        assert full_state.heroes[1].faction == "Native"

    def test_hero_crystal(self, full_state):
        assert full_state.heroes[0].has_crystal is False

    def test_hero_operating(self, full_state):
        assert full_state.heroes[0].is_operating is True
        assert full_state.heroes[0].operating_module_name == "IndustryGenerator"
        assert full_state.heroes[1].is_operating is False

    def test_hero_active_skills(self, full_state):
        skills = full_state.heroes[0].active_skills
        assert len(skills) == 2
        assert skills[0].name == "Punch"
        assert skills[0].cooldown_turns == 3
        assert skills[0].remaining_cooldown == 0
        assert skills[1].name == "War Cry"
        assert skills[1].remaining_cooldown == 2

    def test_hero_passive_skills(self, full_state):
        passives = full_state.heroes[0].passive_skills
        assert len(passives) == 2
        assert passives[0].name == "Operate"
        assert passives[1].name == "Repair"

    def test_hero_equipment(self, full_state):
        equip = full_state.heroes[0].equipment
        assert len(equip) == 3
        assert equip[0].slot_category == "Weapon"
        assert equip[0].item_name == "Crystal Blade"
        assert equip[1].slot_category == "Armor"
        assert equip[1].item_name is None  # empty slot
        assert equip[2].item_name == "Speed Ring"


class TestMobs:
    def test_mob_count(self, full_state):
        assert len(full_state.mobs) == 2

    def test_mob_data(self, full_state):
        mob = full_state.mobs[0]
        assert mob.type == "Silic Zoner"
        assert mob.room_index == 1
        assert mob.hp == 45.0
        assert mob.max_hp == 80.0
        assert mob.target_type == "AntiHeroMob"

    def test_crystal_targeting_mob(self, full_state):
        assert full_state.mobs[1].target_type == "Crystal"


class TestMerchants:
    def test_merchant_count(self, full_state):
        assert len(full_state.merchants) == 1

    def test_merchant_room_and_currency(self, full_state):
        m = full_state.merchants[0]
        assert m.room_index == 0
        assert m.currency_type == "Dust"

    def test_merchant_items(self, full_state):
        items = full_state.merchants[0].items
        assert len(items) == 2
        assert items[0].name == "Titanium Plate"
        assert items[0].rarity == "Uncommon"
        assert items[0].cost == 7.0


class TestRecruitableHeroes:
    def test_recruit_count(self, full_state):
        assert len(full_state.recruitable_heroes) == 1

    def test_recruit_info(self, full_state):
        r = full_state.recruitable_heroes[0]
        assert r.name == "Sara Numas"
        assert r.faction == "Mezari"
        assert r.room_index == 1
        assert r.hp == 120.0
        assert r.max_hp == 120.0

    def test_recruit_passives(self, full_state):
        passives = full_state.recruitable_heroes[0].passive_skill_names
        assert "Operate" in passives
        assert "Heal" in passives


class TestDroppedItems:
    def test_dropped_item_count(self, full_state):
        assert len(full_state.dropped_items) == 2

    def test_dust_item(self, full_state):
        dust = full_state.dropped_items[0]
        assert dust.type == "Dust"
        assert dust.room_index == 1
        assert dust.dust_amount == 4.0
        assert dust.name is None

    def test_equipment_item(self, full_state):
        equip = full_state.dropped_items[1]
        assert equip.type == "Equipment"
        assert equip.name == "Old Shield"
        assert equip.room_index == 0


class TestInventory:
    def test_backpack_items(self, full_state):
        assert len(full_state.backpack_items) == 1
        item = full_state.backpack_items[0]
        assert item.name == "Ancient Relic"
        assert item.rarity == "Legendary"
        assert item.category == "Accessory"

    def test_shared_inventory(self, full_state):
        assert len(full_state.shared_inventory_items) == 2
        assert full_state.shared_inventory_items[0].name == "Rusty Sword"

    def test_researchable_blueprints(self, full_state):
        assert len(full_state.researchable_blueprints) == 3
        bp_names = [bp.name for bp in full_state.researchable_blueprints]
        assert "LaserTurret" in bp_names
        assert full_state.researchable_blueprints[0].science_cost == 20.0


class TestValidation:
    def test_invalid_game_phase_raises(self, parser):
        raw = _full_state_dict()
        raw["game_phase"] = "InvalidPhase"
        with pytest.raises(ValidationError):
            parser.parse(raw)

    def test_missing_room_index_raises(self, parser):
        raw = _full_state_dict()
        del raw["rooms"][0]["index"]
        with pytest.raises(ValidationError):
            parser.parse(raw)

    def test_missing_hero_name_raises(self, parser):
        raw = _full_state_dict()
        del raw["heroes"][0]["name"]
        with pytest.raises(ValidationError):
            parser.parse(raw)


class TestLenientParsing:
    def test_unknown_fields_ignored(self, parser):
        raw = _full_state_dict()
        raw["unknown_top_level_field"] = "ignored"
        raw["heroes"][0]["unknown_hero_field"] = 999
        state = parser.parse_lenient(raw)
        assert state.turn == 7

    def test_minimal_state(self, parser):
        raw = {
            "turn": 1,
            "floor": 1,
            "game_phase": "Strategy",
            "crystal_state": "Plugged",
            "exit_room_index": 0,
            "start_room_index": 0,
            "rooms": [{"index": 0}],
            "closed_doors": [],
            "heroes": [{"name": "TestHero"}],
            "mobs": [],
            "merchants": [],
            "recruitable_heroes": [],
            "dropped_items": [],
            "backpack_items": [],
            "shared_inventory_items": [],
            "researchable_blueprints": [],
        }
        state = parser.parse(raw)
        assert state.turn == 1
        assert state.heroes[0].name == "TestHero"
        assert state.heroes[0].faction == ""

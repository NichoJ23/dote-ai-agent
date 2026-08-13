"""
Tests for the metrics module (FloorMetrics and RunMetrics).

Validates:
  - FloorMetrics state tracking from game observations
  - Action recording
  - RunMetrics aggregation
  - JSON serialization/deserialization
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "agent"))

from metrics import FloorMetrics, RunMetrics
from state_parser import GameStatePayload, StateParser


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_state(
    turn: int = 1,
    rooms: int = 3,
    mobs: int = 0,
    heroes: int = 2,
    dust: float = 10.0,
    closed_doors: int = 1,
) -> dict:
    """Create a minimal state dict for metrics testing."""
    room_list = []
    for i in range(rooms):
        adj = []
        if i > 0:
            adj.append(i - 1)
        if i < rooms - 1:
            adj.append(i + 1)
        room_list.append({
            "index": i,
            "is_powered": i == 0,
            "is_auto_powered": i == 0,
            "is_exit_room": i == rooms - 1,
            "is_start_room": i == 0,
            "is_fully_opened": True,
            "depth": i,
            "suffers_emp": False,
            "emp_turns_remaining": 0,
            "dust_loot_amount": 0,
            "has_artifact": False,
            "has_stele": False,
            "adjacent_room_indices": adj,
            "major_module_name": "IndGen" if i == 0 else None,
            "minor_module_names": ["Turret"] if i == 1 else [],
            "minor_slot_count": 2,
            "hero_count": 0,
            "mob_count": 0,
            "npc_count": 0,
        })

    closed = []
    for i in range(closed_doors):
        if i < rooms - 1:
            closed.append({"room1_index": i, "room2_index": i + 1, "is_opening": False})

    hero_list = []
    for i in range(heroes):
        hero_list.append({
            "name": f"Hero_{i}",
            "faction": "Guard",
            "room_index": 0,
            "hp": 200.0,
            "max_hp": 250.0,
            "level": 1,
            "has_crystal": False,
            "is_operating": False,
            "operating_module_name": None,
            "is_recruitable": False,
            "is_recruited": True,
            "active_skills": [],
            "passive_skills": [],
            "equipment": [],
        })

    mob_list = []
    for i in range(mobs):
        mob_list.append({
            "type": "Zed",
            "room_index": 1,
            "hp": 50.0,
            "max_hp": 80.0,
            "target_type": "AntiHeroMob",
        })

    return {
        "turn": turn,
        "floor": 1,
        "game_phase": "Strategy",
        "crystal_state": "Plugged",
        "exit_room_index": rooms - 1,
        "start_room_index": 0,
        "resources": {
            "industry": 40.0,
            "food": 25.0,
            "science": 10.0,
            "dust": dust,
            "dust_max": 15.0,
            "industry_per_turn": 5.0,
            "food_per_turn": 3.0,
            "science_per_turn": 2.0,
            "dust_per_turn": 0.0,
            "room_power_cost": 1.0,
            "powered_room_count": 1,
        },
        "rooms": room_list,
        "closed_doors": closed,
        "heroes": hero_list,
        "mobs": mob_list,
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
# Test: FloorMetrics
# ---------------------------------------------------------------------------


class TestFloorMetrics:
    """Test FloorMetrics state tracking."""

    def test_initial_state(self):
        """FloorMetrics starts with zeros."""
        fm = FloorMetrics()
        assert fm.turns_survived == 0
        assert fm.rooms_explored == 0
        assert fm.mobs_killed == 0
        assert fm.actions_taken == 0
        assert fm.outcome == ""

    def test_update_from_state_tracks_turns(self):
        """update_from_state records the highest turn number."""
        fm = FloorMetrics()
        state1 = _parse(_make_state(turn=1))
        state2 = _parse(_make_state(turn=5))
        fm.update_from_state(state1)
        fm.update_from_state(state2)
        assert fm.turns_survived == 5

    def test_update_from_state_tracks_rooms(self):
        """update_from_state counts rooms explored."""
        fm = FloorMetrics()
        state1 = _parse(_make_state(rooms=2))
        fm.update_from_state(state1)
        assert fm.rooms_explored == 2

        state2 = _parse(_make_state(rooms=5))
        fm.update_from_state(state2)
        assert fm.rooms_explored == 5

    def test_update_from_state_tracks_mobs_killed(self):
        """Mob count decrease is tracked as kills."""
        fm = FloorMetrics()
        state1 = _parse(_make_state(mobs=5))
        fm.update_from_state(state1)

        state2 = _parse(_make_state(mobs=2))
        fm.update_from_state(state2)
        assert fm.mobs_killed == 3

    def test_update_from_state_tracks_heroes_lost(self):
        """Hero count decrease is tracked as losses."""
        fm = FloorMetrics()
        state1 = _parse(_make_state(heroes=3))
        fm.update_from_state(state1)

        state2 = _parse(_make_state(heroes=2))
        fm.update_from_state(state2)
        assert fm.heroes_lost == 1

    def test_update_from_state_tracks_resource_peaks(self):
        """Peak resource values are recorded."""
        fm = FloorMetrics()
        state1 = _parse(_make_state(dust=5.0))
        fm.update_from_state(state1)
        assert fm.peak_dust == 5.0

        state2 = _parse(_make_state(dust=12.0))
        fm.update_from_state(state2)
        assert fm.peak_dust == 12.0

        # Peak should not decrease
        state3 = _parse(_make_state(dust=3.0))
        fm.update_from_state(state3)
        assert fm.peak_dust == 12.0

    def test_record_action(self):
        """Action recording tracks counts and breakdown."""
        fm = FloorMetrics()
        fm.record_action("MOVE_HERO", True)
        fm.record_action("MOVE_HERO", True)
        fm.record_action("BUILD_MODULE", False)
        fm.record_action("OPEN_DOOR", True)

        assert fm.actions_taken == 4
        assert fm.actions_failed == 1
        assert fm.action_breakdown == {"MOVE_HERO": 2, "BUILD_MODULE": 1, "OPEN_DOOR": 1}

    def test_start_and_finish(self):
        """Start/finish timing and outcome."""
        fm = FloorMetrics()
        fm.start()
        fm.finish("escaped")
        assert fm.outcome == "escaped"
        assert fm.duration_seconds >= 0.0

    def test_to_dict(self):
        """Serialization to dict works."""
        fm = FloorMetrics(floor_number=2, turns_survived=10, mobs_killed=5)
        fm.record_action("MOVE_HERO", True)
        fm.finish("escaped")

        d = fm.to_dict()
        assert d["floor_number"] == 2
        assert d["turns_survived"] == 10
        assert d["mobs_killed"] == 5
        assert d["outcome"] == "escaped"
        assert d["actions_taken"] == 1
        assert "MOVE_HERO" in d["action_breakdown"]

    def test_doors_opened_tracking(self):
        """Doors opened are tracked from closed door count changes."""
        fm = FloorMetrics()
        state1 = _parse(_make_state(rooms=5, closed_doors=4))
        fm.update_from_state(state1)

        state2 = _parse(_make_state(rooms=5, closed_doors=2))
        fm.update_from_state(state2)
        assert fm.doors_opened == 2


# ---------------------------------------------------------------------------
# Test: RunMetrics
# ---------------------------------------------------------------------------


class TestRunMetrics:
    """Test RunMetrics aggregation and serialization."""

    def test_initial_state(self):
        """RunMetrics starts empty."""
        rm = RunMetrics()
        assert rm.total_floors_survived == 0
        assert rm.floors_completed == []
        assert rm.run_id != ""
        assert rm.start_time != ""

    def test_add_floor(self):
        """Adding floor metrics is tracked."""
        rm = RunMetrics()
        fm1 = FloorMetrics(floor_number=1, turns_survived=15, outcome="escaped")
        fm2 = FloorMetrics(floor_number=2, turns_survived=20, outcome="game_over")

        rm.add_floor(fm1)
        rm.add_floor(fm2)

        assert rm.total_floors_survived == 1  # Only fm1 escaped
        assert len(rm.floors_completed) == 2

    def test_aggregate_properties(self):
        """Aggregate statistics are computed correctly."""
        rm = RunMetrics()
        fm1 = FloorMetrics(floor_number=1, turns_survived=10, rooms_explored=5, mobs_killed=8)
        fm1.record_action("MOVE_HERO", True)
        fm1.record_action("BUILD_MODULE", True)
        fm2 = FloorMetrics(floor_number=2, turns_survived=7, rooms_explored=3, mobs_killed=4)
        fm2.record_action("OPEN_DOOR", True)

        rm.add_floor(fm1)
        rm.add_floor(fm2)

        assert rm.total_turns == 17
        assert rm.total_rooms_explored == 8
        assert rm.total_mobs_killed == 12
        assert rm.total_actions == 3

    def test_to_dict(self):
        """Full serialization to dict."""
        rm = RunMetrics(run_id="test_run_123")
        fm = FloorMetrics(floor_number=1, turns_survived=10, outcome="escaped")
        rm.add_floor(fm)
        rm.finish("escaped_all")

        d = rm.to_dict()
        assert d["run_id"] == "test_run_123"
        assert d["final_outcome"] == "escaped_all"
        assert d["total_floors_survived"] == 1
        assert len(d["floors"]) == 1
        assert d["floors"][0]["outcome"] == "escaped"

    def test_save_and_load(self):
        """RunMetrics can be saved to and loaded from JSON file."""
        rm = RunMetrics(run_id="save_test")
        fm = FloorMetrics(floor_number=1, turns_survived=8, mobs_killed=3, outcome="game_over")
        fm.record_action("MOVE_HERO", True)
        rm.add_floor(fm)
        rm.finish("game_over")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = Path(f.name)

        try:
            rm.save(path)
            assert path.exists()

            # Load and verify
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["run_id"] == "save_test"
            assert data["final_outcome"] == "game_over"
            assert data["floors"][0]["mobs_killed"] == 3
        finally:
            path.unlink(missing_ok=True)

    def test_finish_sets_outcome(self):
        """finish() sets the final outcome."""
        rm = RunMetrics()
        rm.finish("aborted")
        assert rm.final_outcome == "aborted"

    def test_heroes_lost_aggregation(self):
        """Total heroes lost is aggregated across floors."""
        rm = RunMetrics()
        fm1 = FloorMetrics(heroes_lost=1)
        fm2 = FloorMetrics(heroes_lost=2)
        rm.add_floor(fm1)
        rm.add_floor(fm2)
        assert rm.total_heroes_lost == 3

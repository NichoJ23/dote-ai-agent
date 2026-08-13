"""
Metrics: Tracks per-floor and per-run statistics for the heuristic agent.

Collects:
  - Turns survived
  - Rooms explored
  - Doors opened
  - Resources gathered (peak values)
  - Heroes lost
  - Items equipped
  - Merchants visited (items bought)
  - Modules built
  - Mobs killed (estimated from delta)
  - Floor outcome (escaped / game_over)
  - Actions taken (total + per-type breakdown)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from state_parser import GameStatePayload


@dataclass
class FloorMetrics:
    """Metrics for a single floor playthrough."""

    floor_number: int = 1
    turns_survived: int = 0
    rooms_explored: int = 0
    doors_opened: int = 0
    modules_built: int = 0
    mobs_killed: int = 0
    heroes_lost: int = 0
    heroes_recruited: int = 0
    items_equipped: int = 0
    items_bought: int = 0
    dust_collected: float = 0.0
    peak_industry: float = 0.0
    peak_food: float = 0.0
    peak_science: float = 0.0
    peak_dust: float = 0.0
    actions_taken: int = 0
    actions_failed: int = 0
    action_breakdown: dict[str, int] = field(default_factory=dict)
    outcome: str = ""  # "escaped" | "game_over" | "in_progress"
    duration_seconds: float = 0.0

    # Internal tracking (not serialized)
    _start_time: float = field(default=0.0, repr=False)
    _prev_mob_count: int = field(default=0, repr=False)
    _prev_hero_count: int = field(default=0, repr=False)
    _prev_rooms: int = field(default=0, repr=False)
    _prev_doors_closed: int = field(default=0, repr=False)

    def start(self) -> None:
        """Mark the start of floor timing."""
        self._start_time = time.time()

    def finish(self, outcome: str) -> None:
        """Mark the end of the floor."""
        self.outcome = outcome
        self.duration_seconds = time.time() - self._start_time

    def record_action(self, command: str, success: bool) -> None:
        """Record an action attempt."""
        self.actions_taken += 1
        self.action_breakdown[command] = self.action_breakdown.get(command, 0) + 1
        if not success:
            self.actions_failed += 1

    def update_from_state(self, state: GameStatePayload) -> None:
        """Update metrics from a new game state observation."""
        # Turn tracking
        self.turns_survived = max(self.turns_survived, state.turn)
        self.floor_number = state.floor

        # Room exploration
        current_rooms = len(state.rooms)
        if current_rooms > self._prev_rooms:
            self.rooms_explored = current_rooms
        self._prev_rooms = current_rooms

        # Doors opened (total closed doors decreasing means doors opened)
        current_closed = len(state.closed_doors)
        if self._prev_doors_closed > 0 and current_closed < self._prev_doors_closed:
            self.doors_opened += self._prev_doors_closed - current_closed
        self._prev_doors_closed = current_closed

        # Modules
        self.modules_built = sum(
            (1 if r.major_module_name else 0) + len(r.minor_module_names)
            for r in state.rooms
        )

        # Mobs killed (estimated from count decrease)
        current_mobs = len(state.mobs)
        if current_mobs < self._prev_mob_count:
            self.mobs_killed += self._prev_mob_count - current_mobs
        self._prev_mob_count = current_mobs

        # Heroes lost
        current_heroes = len(state.heroes)
        if current_heroes < self._prev_hero_count and self._prev_hero_count > 0:
            self.heroes_lost += self._prev_hero_count - current_heroes
        self._prev_hero_count = current_heroes

        # Resource peaks
        if state.resources:
            self.peak_industry = max(self.peak_industry, state.resources.industry)
            self.peak_food = max(self.peak_food, state.resources.food)
            self.peak_science = max(self.peak_science, state.resources.science)
            self.peak_dust = max(self.peak_dust, state.resources.dust)

    def to_dict(self) -> dict:
        """Serialize to a dict (excludes internal tracking fields)."""
        return {
            "floor_number": self.floor_number,
            "turns_survived": self.turns_survived,
            "rooms_explored": self.rooms_explored,
            "doors_opened": self.doors_opened,
            "modules_built": self.modules_built,
            "mobs_killed": self.mobs_killed,
            "heroes_lost": self.heroes_lost,
            "heroes_recruited": self.heroes_recruited,
            "items_equipped": self.items_equipped,
            "items_bought": self.items_bought,
            "dust_collected": self.dust_collected,
            "peak_industry": self.peak_industry,
            "peak_food": self.peak_food,
            "peak_science": self.peak_science,
            "peak_dust": self.peak_dust,
            "actions_taken": self.actions_taken,
            "actions_failed": self.actions_failed,
            "action_breakdown": self.action_breakdown,
            "outcome": self.outcome,
            "duration_seconds": round(self.duration_seconds, 2),
        }


@dataclass
class RunMetrics:
    """Aggregated metrics across all floors in a single game run."""

    run_id: str = ""
    start_time: str = ""
    floors_completed: list[FloorMetrics] = field(default_factory=list)
    total_floors_survived: int = 0
    final_outcome: str = ""  # "escaped_all" | "game_over" | "aborted"

    def __post_init__(self):
        if not self.start_time:
            self.start_time = time.strftime("%Y-%m-%d %H:%M:%S")
        if not self.run_id:
            self.run_id = f"run_{int(time.time())}"

    def add_floor(self, floor_metrics: FloorMetrics) -> None:
        """Add completed floor metrics."""
        self.floors_completed.append(floor_metrics)
        if floor_metrics.outcome == "escaped":
            self.total_floors_survived += 1

    def finish(self, outcome: str) -> None:
        """Mark the run as complete."""
        self.final_outcome = outcome

    @property
    def total_turns(self) -> int:
        return sum(f.turns_survived for f in self.floors_completed)

    @property
    def total_rooms_explored(self) -> int:
        return sum(f.rooms_explored for f in self.floors_completed)

    @property
    def total_mobs_killed(self) -> int:
        return sum(f.mobs_killed for f in self.floors_completed)

    @property
    def total_heroes_lost(self) -> int:
        return sum(f.heroes_lost for f in self.floors_completed)

    @property
    def total_actions(self) -> int:
        return sum(f.actions_taken for f in self.floors_completed)

    def to_dict(self) -> dict:
        """Serialize full run metrics."""
        return {
            "run_id": self.run_id,
            "start_time": self.start_time,
            "total_floors_survived": self.total_floors_survived,
            "final_outcome": self.final_outcome,
            "summary": {
                "total_turns": self.total_turns,
                "total_rooms_explored": self.total_rooms_explored,
                "total_mobs_killed": self.total_mobs_killed,
                "total_heroes_lost": self.total_heroes_lost,
                "total_actions": self.total_actions,
            },
            "floors": [f.to_dict() for f in self.floors_completed],
        }

    def save(self, path: str | Path) -> None:
        """Save run metrics to a JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    def print_summary(self) -> None:
        """Print a human-readable summary to stdout."""
        print(f"\n{'='*60}")
        print(f"  Run: {self.run_id}")
        print(f"  Outcome: {self.final_outcome}")
        print(f"  Floors survived: {self.total_floors_survived}")
        print(f"  Total turns: {self.total_turns}")
        print(f"  Total rooms explored: {self.total_rooms_explored}")
        print(f"  Total mobs killed: {self.total_mobs_killed}")
        print(f"  Total heroes lost: {self.total_heroes_lost}")
        print(f"  Total actions: {self.total_actions}")
        print(f"{'='*60}")
        for floor in self.floors_completed:
            print(
                f"  Floor {floor.floor_number}: "
                f"{floor.outcome} | "
                f"{floor.turns_survived} turns | "
                f"{floor.rooms_explored} rooms | "
                f"{floor.mobs_killed} kills | "
                f"{floor.duration_seconds:.1f}s"
            )
        print(f"{'='*60}\n")

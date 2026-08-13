"""
HeuristicAgent: Finite-state machine controller for autonomous Dungeon of the ENDLESS play.

Implements the full macro/micro/escape hierarchy with configurable learning guidelines (GL-1..GL-8).

FSM States:
  EXPLORE  — Open unexplored doors, discover the map.
  BUILD    — Construct modules, research, manage resources during tactical pause.
  DEFEND   — Position heroes in bottleneck rooms during enemy waves.
  RETREAT  — Pull wounded heroes toward crystal room.
  ESCAPE   — Crystal carrier runs to exit; others guard/block.

The agent produces one action per select_action() call.
The caller (run_agent.py) is responsible for looping until the game advances.
"""

from __future__ import annotations

import logging
from enum import Enum, auto
from typing import Optional

import networkx as nx

from base_agent import BaseAgent
from graph_builder import GraphBuilder
from graph_utils import (
    bottleneck_rooms,
    escape_path_rooms,
    reachable_rooms,
    room_centrality_scores,
    rooms_with_mobs,
    shortest_path_to_crystal,
    shortest_path_to_exit,
    unopened_doors,
)
from guidelines_config import GuidelinesConfig
from state_parser import (
    DroppedItem,
    GamePhase,
    GameStatePayload,
    HeroState,
    MerchantState,
    RecruitableHero,
    RoomState,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FSM State Enum
# ---------------------------------------------------------------------------


class AgentPhase(Enum):
    """High-level FSM states for the heuristic agent."""

    EXPLORE = auto()
    BUILD = auto()
    DEFEND = auto()
    RETREAT = auto()
    ESCAPE = auto()


# ---------------------------------------------------------------------------
# Action helper — builds the dict consumed by IpcClient.send_action()
# ---------------------------------------------------------------------------


def _action(command: str, **params) -> dict:
    """Build an action command dict."""
    return {"command": command, "parameters": params}


# ---------------------------------------------------------------------------
# HeuristicAgent
# ---------------------------------------------------------------------------


class HeuristicAgent(BaseAgent):
    """
    Phase 4 baseline: finite-state machine with rule-based macro + micro logic.

    Macro-Planner (during STRATEGY phase):
      - Explore (open doors)
      - Build/repair modules (Industry > Food > Defense)
      - Queue research
      - Level up heroes (GL-4: Max first for Operate unlock)
      - Evaluate merchants / buy upgrades
      - Recruit heroes when food allows
      - Equip items optimally
      - Collect dropped dust
      - Place operators (GL-3)
      - Manage power (centrality-based)

    Micro-Controller (during ACTION phase):
      - Position heroes in bottleneck rooms
      - Retreat wounded heroes (GL-1)

    Escape-Planner:
      - Fastest hero carries crystal (GL-5)
      - Repower escape path (GL-6)
      - Assign hero roles (guard, block, exit-wait)
    """

    def __init__(self, guidelines: Optional[GuidelinesConfig] = None):
        super().__init__(guidelines)
        self._phase = AgentPhase.BUILD
        self._graph_builder = GraphBuilder()
        self._graph: Optional[nx.Graph] = None
        self._prev_state: Optional[GameStatePayload] = None

        # Tracking for multi-step plans
        self._pending_moves: list[dict] = []  # Queued move actions
        self._escape_initiated = False
        self._crystal_carrier: Optional[str] = None
        self._hero_roles: dict[str, str] = {}  # hero_name -> "carrier" | "guard" | "blocker" | "exit_wait"
        self._explored_rooms: set[int] = set()
        self._built_modules_this_turn: set[str] = set()  # room:slot keys built this tick
        self._leveled_this_turn: set[str] = set()
        self._powered_this_turn: set[int] = set()
        self._unpowered_this_turn: set[int] = set()
        self._collected_this_turn: set[str] = set()
        self._recruited_this_turn: set[str] = set()
        self._equipped_this_turn: set[str] = set()
        self._bought_this_turn: set[str] = set()
        self._researched_this_turn: set[str] = set()
        self._repaired_this_turn: set[str] = set()
        self._doors_opened_this_turn: set[tuple[int, int]] = set()
        self._failed_actions: set[str] = set()  # Blacklisted action keys for this turn
        self._hero_positions: dict[str, int] = {}  # Tracks hero positions from successful moves
        self._moves_issued_this_turn: set[str] = set()  # Hero names that already got a move this turn
        self._built_industry_this_floor = False  # Only build 1 industry gen per floor
        self._last_action_failed = False

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    def select_action(self, state: GameStatePayload) -> Optional[dict]:
        """
        Main entry point: determine FSM phase, then delegate to appropriate handler.
        """
        # Build/refresh graph
        self._graph = self._graph_builder.build(state)
        self._update_explored_rooms(state)

        # Determine FSM state
        self._phase = self._determine_phase(state)

        # Clear move tracking when phase changes back to Strategy
        # (heroes have finished moving after combat)
        if state.game_phase.is_planning:
            self._moves_issued_this_turn.clear()

        logger.debug(f"FSM phase: {self._phase.name}, game_phase: {state.game_phase}")

        # If we have pending moves queued, execute next one
        if self._pending_moves:
            return self._pending_moves.pop(0)

        # Delegate to phase handler
        if self._phase == AgentPhase.ESCAPE:
            action = self._handle_escape(state)
        elif self._phase == AgentPhase.RETREAT:
            action = self._handle_retreat(state)
        elif self._phase == AgentPhase.DEFEND:
            action = self._handle_defend(state)
        else:
            # BUILD phase — the decision tree handles everything
            # including door opening (steps 1 and 10)
            action = self._handle_build(state)

        # Guard: never send MOVE_HERO to a room the hero is already in
        # Also prevent issuing multiple moves for the same hero in one turn
        if action and action.get("command") == "MOVE_HERO":
            hero_name = action["parameters"].get("hero_name")
            target = action["parameters"].get("target_room_index")
            # Check both the state (may be stale) and our tracked positions
            hero = next((h for h in state.heroes if h.name == hero_name), None)
            actual_room = self._hero_positions.get(hero_name, hero.room_index if hero else None)
            if actual_room == target:
                logger.debug(f"Suppressed no-op move: {hero_name} already in room {target}")
                return None
            # Only one move per hero per turn (hero is in transit)
            if hero_name in self._moves_issued_this_turn:
                logger.debug(f"Suppressed duplicate move: {hero_name} already moving this turn")
                return None

        return action

    def reset(self) -> None:
        """Reset all internal state for a new floor/episode."""
        self._phase = AgentPhase.BUILD
        self._graph = None
        self._prev_state = None
        self._pending_moves.clear()
        self._escape_initiated = False
        self._crystal_carrier = None
        self._hero_roles.clear()
        self._explored_rooms.clear()
        self._built_industry_this_floor = False
        self._clear_turn_tracking()

    def on_action_result(self, command: dict, result: dict) -> None:
        """Track failed actions to avoid retry loops."""
        self._last_action_failed = not result.get("success", False)
        if self._last_action_failed:
            # Blacklist the action so we don't retry it this turn
            cmd = command.get("command", "")
            params = command.get("parameters", {})
            # Build a unique key for this specific action
            if cmd == "BUILD_MODULE":
                key = f"{params.get('room_index')}:{params.get('slot_type', 'major')}"
                self._failed_actions.add(key)
            elif cmd == "RESEARCH":
                key = params.get("blueprint_name", "")
                self._failed_actions.add(key)
            elif cmd == "MOVE_HERO":
                key = f"move:{params.get('hero_name')}:{params.get('target_room_index')}"
                self._failed_actions.add(key)
            else:
                # Generic blacklist by command + first param value
                key = f"{cmd}:{next(iter(params.values()), '')}"
                self._failed_actions.add(key)
            logger.warning(f"Action failed: {cmd} - {result.get('error')}")
        else:
            # Track successful moves to update our internal position model
            cmd = command.get("command", "")
            params = command.get("parameters", {})
            if cmd == "MOVE_HERO":
                hero_name = params.get("hero_name")
                target = params.get("target_room_index")
                if hero_name is not None and target is not None:
                    self._hero_positions[hero_name] = target
                    self._moves_issued_this_turn.add(hero_name)
            elif cmd == "OPEN_DOOR":
                # Hero enters the newly opened room
                hero_name = params.get("hero_name")
                target = params.get("target_room_index")
                if hero_name is not None and target is not None and target >= 0:
                    self._hero_positions[hero_name] = target
            elif cmd == "BUILD_MODULE":
                # Track industry gen built
                module_name = params.get("module_name", "")
                if "Major0002" in module_name:
                    self._built_industry_this_floor = True

    def new_turn(self) -> None:
        """Called by the runner when a new turn (state update) is received."""
        self._clear_turn_tracking()

    # ------------------------------------------------------------------
    # FSM Phase Determination (Task 4.18)
    # ------------------------------------------------------------------

    def _determine_phase(self, state: GameStatePayload) -> AgentPhase:
        """
        Determine the current FSM phase based on game state.

        Priority order:
          1. ESCAPE — if crystal is on exit slot or escape conditions met
          2. RETREAT — if any hero below HP threshold during combat
          3. DEFEND — if in combat (Action phase)
          4. EXPLORE — if there are unexplored doors during Strategy
          5. BUILD — default during Strategy phase
        """
        # Escape conditions: crystal already unplugged to exit, or all doors opened
        if state.is_escaping:
            return AgentPhase.ESCAPE
        if self._escape_initiated:
            return AgentPhase.ESCAPE
        if self._should_initiate_escape(state):
            self._escape_initiated = True
            return AgentPhase.ESCAPE

        # During combat (Action phase)
        if state.game_phase.is_combat:
            # Check retreat condition (GL-1)
            if self._any_hero_needs_retreat(state):
                return AgentPhase.RETREAT
            return AgentPhase.DEFEND

        # During Strategy (planning) phase — use the decision tree directly
        return AgentPhase.BUILD

    def _should_initiate_escape(self, state: GameStatePayload) -> bool:
        """
        Check if escape should be initiated (REQ-E6).
        Escape when:
          1. The exit room has been discovered (present in state.rooms)
          2. No unexplored doors remain on the floor
        """
        if not state.game_phase.is_planning:
            return False
        if self._graph is None:
            return False

        # Exit room must have been discovered
        exit_found = any(r.is_exit_room for r in state.rooms)
        if not exit_found:
            return False

        # No closed doors remaining (check state directly — most reliable)
        if state.closed_doors:
            return False

        # Double-check graph
        closed = unopened_doors(self._graph)
        if len(closed) > 0:
            return False

        # No rooms that aren't fully opened
        for room in state.rooms:
            if not room.is_fully_opened:
                return False

        return True

    def _any_hero_needs_retreat(self, state: GameStatePayload) -> bool:
        """Check if any hero is below the retreat HP threshold (GL-1)."""
        if not self.guidelines.retreat_enabled:
            return False
        threshold = self.guidelines.retreat_hp_threshold
        for hero in state.heroes:
            if hero.max_hp > 0 and (hero.hp / hero.max_hp) < threshold:
                if not hero.has_crystal:  # Crystal carrier can't retreat normally
                    return True
        return False

    def _has_unexplored_doors(self, state: GameStatePayload) -> bool:
        """Check if there are still closed doors to explore."""
        # Direct check: state.closed_doors always has the ground truth
        if state.closed_doors:
            return True
        # Check the graph for closed edges
        if self._graph is not None:
            closed = unopened_doors(self._graph)
            if len(closed) > 0:
                return True
        # Also check if any room reports it's not fully opened
        for room in state.rooms:
            if not room.is_fully_opened:
                return True
        return False

    # ------------------------------------------------------------------
    # EXPLORE State (Task 4.3)
    # ------------------------------------------------------------------

    def _handle_explore(self, state: GameStatePayload) -> Optional[dict]:
        """
        EXPLORE: Find nearest unexplored door, dispatch hero, open it.

        Logic:
          1. Find all closed doors (from graph edges OR from rooms not fully opened)
          2. Pick the closest one to any available hero
          3. If hero is already at the door's source room, open it
          4. Otherwise, move hero to the source room first
        """
        if self._graph is None:
            return None

        closed = unopened_doors(self._graph)

        # Also detect "implicit" closed doors: rooms that aren't fully opened
        # but whose closed doors don't appear in the graph (early game scenario)
        rooms_not_fully_opened = [
            r for r in state.rooms if not r.is_fully_opened
        ]

        # Also check closed_doors directly from state — the graph may not
        # have edges for rooms that aren't yet in state.rooms
        explicit_closed_doors = [
            (d.room1_index, d.room2_index) for d in state.closed_doors
        ]

        if not closed and not rooms_not_fully_opened and not explicit_closed_doors:
            # No more doors to explore — transition to BUILD
            return self._handle_build(state)

        # Filter closed doors that were already attempted this turn
        closed = [(a, b) for (a, b) in closed
                  if (a, b) not in self._doors_opened_this_turn
                  and (b, a) not in self._doors_opened_this_turn]

        # Get available (non-operating) heroes
        available_heroes = self._get_available_heroes(state)
        if not available_heroes:
            return self._handle_build(state)

        # If we have explicit closed doors in the graph, use them
        if closed:
            # Find best hero + door pair (minimum travel distance)
            best_hero = None
            best_door = None
            best_dist = float("inf")

            for hero in available_heroes:
                for door_a, door_b in closed:
                    # Hero can reach door_a (the explored side) through open doors
                    path = self._path_through_open_doors(hero.room_index, door_a)
                    if path:
                        dist = len(path) - 1
                        if dist < best_dist:
                            best_dist = dist
                            best_hero = hero
                            best_door = (door_a, door_b)

                    # Or door_b if that side is explored
                    path = self._path_through_open_doors(hero.room_index, door_b)
                    if path:
                        dist = len(path) - 1
                        if dist < best_dist:
                            best_dist = dist
                            best_hero = hero
                            best_door = (door_b, door_a)

            if best_hero is not None and best_door is not None:
                from_room, target_room = best_door

                # If hero is already at the door's source room, open the door
                if best_hero.room_index == from_room:
                    self._doors_opened_this_turn.add((from_room, target_room))
                    return _action(
                        "OPEN_DOOR",
                        hero_name=best_hero.name,
                        from_room_index=from_room,
                        target_room_index=target_room,
                    )

                # Otherwise, move hero toward the door source
                path = self._path_through_open_doors(best_hero.room_index, from_room)
                if path and len(path) >= 2:
                    return _action(
                        "MOVE_HERO",
                        hero_name=best_hero.name,
                        target_room_index=path[1],  # Next step on path
                    )

        # Implicit closed doors: room is not fully opened but doors aren't in graph
        # The hero needs to open a door FROM this room. Use adjacent_room_indices
        # from the room state to find valid door targets.
        if rooms_not_fully_opened:
            for room in rooms_not_fully_opened:
                # Find adjacent rooms that aren't in the graph (unexplored)
                explored_indices = {r.index for r in state.rooms}
                unexplored_neighbors = [
                    adj for adj in room.adjacent_room_indices
                    if adj not in explored_indices
                ]
                if not unexplored_neighbors:
                    # All neighbors explored, but maybe doors still closed in graph
                    continue

                # Pick the first unexplored neighbor as target
                target_room = unexplored_neighbors[0]
                door_key = (room.index, target_room)
                if door_key in self._doors_opened_this_turn:
                    continue

                # Find a hero to send
                hero_in_room = next(
                    (h for h in available_heroes if h.room_index == room.index),
                    None,
                )
                if hero_in_room:
                    self._doors_opened_this_turn.add(door_key)
                    return _action(
                        "OPEN_DOOR",
                        hero_name=hero_in_room.name,
                        from_room_index=room.index,
                        target_room_index=target_room,
                    )

                # Move nearest hero to the room
                closest = self._closest_hero_to_room(available_heroes, room.index)
                if closest and closest.room_index != room.index:
                    path = self._path_through_open_doors(closest.room_index, room.index)
                    if path and len(path) >= 2:
                        return _action(
                            "MOVE_HERO",
                            hero_name=closest.name,
                            target_room_index=path[1],
                        )

        # Use closed_doors from state directly — covers cases where
        # adjacent_room_indices is empty but closed_doors list has entries
        if explicit_closed_doors:
            explored_indices = {r.index for r in state.rooms}
            for room1, room2 in explicit_closed_doors:
                door_key = (room1, room2)
                if door_key in self._doors_opened_this_turn or (room2, room1) in self._doors_opened_this_turn:
                    continue

                # Determine which side the hero can reach
                from_room = None
                target = None
                if room1 in explored_indices:
                    from_room = room1
                    target = room2
                elif room2 in explored_indices:
                    from_room = room2
                    target = room1
                else:
                    continue  # Neither side is explored

                # Find a hero at or near the from_room
                hero_in_room = next(
                    (h for h in available_heroes if h.room_index == from_room),
                    None,
                )
                if hero_in_room:
                    self._doors_opened_this_turn.add(door_key)
                    return _action(
                        "OPEN_DOOR",
                        hero_name=hero_in_room.name,
                        from_room_index=from_room,
                        target_room_index=target,
                    )

                # Move nearest hero to from_room
                closest = self._closest_hero_to_room(available_heroes, from_room)
                if closest and closest.room_index != from_room:
                    path = self._path_through_open_doors(closest.room_index, from_room)
                    if path and len(path) >= 2:
                        return _action(
                            "MOVE_HERO",
                            hero_name=closest.name,
                            target_room_index=path[1],
                        )
                    # If no path through open doors, hero might already be in the room
                    # (only 1 room case — hero IS in from_room)
                    if closest.room_index == from_room:
                        self._doors_opened_this_turn.add(door_key)
                        return _action(
                            "OPEN_DOOR",
                            hero_name=closest.name,
                            from_room_index=from_room,
                            target_room_index=target,
                        )

        return self._handle_build(state)

    # ------------------------------------------------------------------
    # BUILD State (Tasks 4.4-4.6)
    # ------------------------------------------------------------------

    def _handle_build(self, state: GameStatePayload) -> Optional[dict]:
        """
        BUILD: Explicit 10-step decision tree for the macro-planner.

        Priority order:
          1. Open a door from the crystal room (if multiple, pick one)
          2. Power closest unpowered rooms using excess dust
          3. Build one industry generator on the newest room (highest index)
          4. Build prisoner prods (minor) in room 1 until slots full or no industry
          5. Research most expensive affordable blueprint (if artifact exists and idle)
          6. Collect dropped items (send hero to pick up)
          7. Recruit heroes if affordable
          8. Buy cheapest merchant item if affordable, equip to Gork > Max
          9. Move Gork to room 1 if not there
          10. Open any remaining doors; if none, start escape
        """
        # --- Step 1: Open door from crystal room ---
        action = self._macro_open_crystal_room_door(state)
        if action:
            return action

        # --- Step 2: Power closest unpowered rooms with excess dust ---
        action = self._macro_power_rooms(state)
        if action:
            return action

        # --- Step 3: Build one industry generator on newest room ---
        action = self._macro_build_industry(state)
        if action:
            return action

        # --- Step 4: Build prisoner prods in room 1 ---
        action = self._macro_build_prisoner_prods(state)
        if action:
            return action

        # --- Step 5: Research (most expensive affordable) ---
        action = self._try_research(state)
        if action:
            return action

        # --- Step 6: Collect items on the floor ---
        action = self._macro_collect_items(state)
        if action:
            return action

        # --- Step 7: Recruit heroes ---
        action = self._macro_recruit(state)
        if action:
            return action

        # --- Step 8: Buy from merchant ---
        action = self._macro_buy_merchant(state)
        if action:
            return action

        # --- Step 8.5: Equip items from inventory ---
        action = self._macro_equip_items(state)
        if action:
            return action

        # --- Step 9: Position Gork in room 1 ---
        action = self._macro_position_gork(state)
        if action:
            return action

        # --- Step 10: Open any remaining door, or signal escape ---
        action = self._macro_open_any_door(state)
        if action:
            return action

        # Nothing left to do in BUILD
        return None

    # ------------------------------------------------------------------
    # Macro-Planner Steps (Decision Tree)
    # ------------------------------------------------------------------

    # Module blueprint IDs (confirmed from runtime observation)
    INDUSTRY_GENERATOR = "MajorModule_Major0002_LVL1"
    PRISONER_PROD = "MinorModule_Minor0004_LVL1"
    DUST_PER_POWERED_ROOM = 10  # Cost to power one room

    def _macro_open_crystal_room_door(self, state: GameStatePayload) -> Optional[dict]:
        """Step 1: Open a door from the crystal room if one exists. Uses Max."""
        crystal_room = state.start_room_index

        # Check state.closed_doors for a door touching the crystal room
        for door in state.closed_doors:
            if door.room1_index == crystal_room or door.room2_index == crystal_room:
                from_room = crystal_room
                target_room = door.room2_index if door.room1_index == crystal_room else door.room1_index
                door_key = (from_room, target_room)
                if door_key in self._doors_opened_this_turn:
                    continue

                # Prefer Max for exploration
                max_hero = next(
                    (h for h in state.heroes
                     if "Max" in h.name and not h.is_operating
                     and self._hero_room(h) == crystal_room),
                    None,
                )
                hero = max_hero
                if hero is None:
                    # Fall back to any hero in crystal room
                    hero = next(
                        (h for h in state.heroes
                         if self._hero_room(h) == crystal_room and not h.is_operating),
                        None,
                    )
                if hero:
                    self._doors_opened_this_turn.add(door_key)
                    return _action(
                        "OPEN_DOOR",
                        hero_name=hero.name,
                        from_room_index=from_room,
                        target_room_index=target_room,
                    )
        return None

    def _macro_power_rooms(self, state: GameStatePayload) -> Optional[dict]:
        """
        Step 2: Power closest unpowered rooms using excess dust.
        Excess dust = total dust - (powered_rooms * 10).
        """
        if state.resources is None:
            return None

        total_dust = state.resources.dust
        powered_count = state.resources.powered_room_count
        excess_dust = total_dust - (powered_count * self.DUST_PER_POWERED_ROOM)

        if excess_dust < self.DUST_PER_POWERED_ROOM:
            return None

        # Find unpowered rooms, prefer closest to crystal room
        unpowered = [
            r for r in state.rooms
            if not r.is_powered and not r.is_auto_powered
            and r.index not in self._powered_this_turn
            and not r.suffers_emp
        ]
        if not unpowered:
            return None

        # Sort by distance to crystal room (use depth as proxy)
        unpowered.sort(key=lambda r: r.depth)

        room = unpowered[0]
        self._powered_this_turn.add(room.index)
        return _action("POWER_ROOM", room_index=room.index)

    def _macro_build_industry(self, state: GameStatePayload) -> Optional[dict]:
        """
        Step 3: Build one industry generator on the newest discovered room
        (highest index) if no industry gen has been built on this floor yet.
        """
        if self._built_industry_this_floor:
            return None
        if state.resources is None:
            return None

        # Also check state in case we're resuming mid-floor
        has_industry = any(
            r.major_module_name is not None and "Major0002" in (r.major_module_name or "")
            for r in state.rooms
        )
        if has_industry:
            self._built_industry_this_floor = True
            return None

        # Can we afford it?
        if state.resources.industry < 10:
            return None

        # Find the newest room (highest index) that has an empty major slot
        candidates = [
            r for r in state.rooms
            if r.major_module_name is None
            and not r.is_start_room  # Crystal room slot is special
            and not r.suffers_emp
            and f"{r.index}:major" not in self._built_modules_this_turn
            and f"{r.index}:major" not in self._failed_actions
        ]
        if not candidates:
            return None

        # Pick highest index (most recently discovered)
        room = max(candidates, key=lambda r: r.index)
        self._built_modules_this_turn.add(f"{room.index}:major")
        return _action(
            "BUILD_MODULE",
            room_index=room.index,
            module_name=self.INDUSTRY_GENERATOR,
            slot_type="major",
        )

    def _macro_build_prisoner_prods(self, state: GameStatePayload) -> Optional[dict]:
        """
        Step 4: Build prisoner prods (minor turrets) in room 1 until
        all minor slots are full or we can't afford more.
        """
        if state.resources is None:
            return None
        if state.resources.industry < 8:
            return None

        # Find room 1 (first room opened from crystal room)
        room1 = next((r for r in state.rooms if r.index == 1), None)
        if room1 is None:
            return None

        minor_used = len(room1.minor_module_names)
        if minor_used >= room1.minor_slot_count:
            return None  # All slots full

        room_key = f"1:minor:{minor_used}"
        if room_key in self._built_modules_this_turn or room_key in self._failed_actions:
            return None

        self._built_modules_this_turn.add(room_key)
        return _action(
            "BUILD_MODULE",
            room_index=1,
            module_name=self.PRISONER_PROD,
            slot_type="minor",
        )

    def _macro_collect_items(self, state: GameStatePayload) -> Optional[dict]:
        """
        Step 6: Send a hero to pick up any dropped items on the floor.
        """
        if not state.dropped_items:
            return None

        available = self._get_available_heroes(state)
        if not available:
            return None

        for item in state.dropped_items:
            item_key = f"collect:{item.room_index}:{item.name}"
            if item_key in self._collected_this_turn:
                continue

            # Hero already in the room? Item auto-collects for dust/equipment.
            hero_in_room = next(
                (h for h in state.heroes if h.room_index == item.room_index),
                None,
            )
            if hero_in_room:
                self._collected_this_turn.add(item_key)
                # For chests, need explicit interact
                if item.type == "Chest":
                    return _action(
                        "COLLECT_ITEM",
                        hero_name=hero_in_room.name,
                        item_name=item.name or "",
                    )
                continue  # Dust/equipment auto-collects

            # Move nearest hero there
            closest = self._closest_hero_to_room(available, item.room_index)
            if closest and closest.room_index != item.room_index:
                self._collected_this_turn.add(item_key)
                path = self._path_through_open_doors(closest.room_index, item.room_index)
                if path and len(path) >= 2:
                    return _action(
                        "MOVE_HERO",
                        hero_name=closest.name,
                        target_room_index=path[1],
                    )

        return None

    def _macro_recruit(self, state: GameStatePayload) -> Optional[dict]:
        """
        Step 7: Recruit heroes if we can afford the food cost.
        Dispatches a hero to the recruit's room first if needed.
        """
        if not state.recruitable_heroes:
            return None
        if state.resources is None:
            return None

        food = state.resources.food

        for recruit in state.recruitable_heroes:
            if recruit.name in self._recruited_this_turn:
                continue

            # Check if we can afford it (use actual cost from wire format)
            if recruit.recruit_cost_food > 0 and food < recruit.recruit_cost_food:
                continue

            # Find a hero in the recruit's room
            hero_in_room = next(
                (h for h in state.heroes if h.room_index == recruit.room_index),
                None,
            )
            if hero_in_room:
                self._recruited_this_turn.add(recruit.name)
                return _action(
                    "RECRUIT_HERO",
                    recruiter_hero_name=hero_in_room.name,
                    recruit_name=recruit.name,
                )

            # Dispatch a hero to the recruit
            available = self._get_available_heroes(state)
            if available:
                closest = self._closest_hero_to_room(available, recruit.room_index)
                if closest and closest.room_index != recruit.room_index:
                    path = self._path_through_open_doors(closest.room_index, recruit.room_index)
                    if path and len(path) >= 2:
                        return _action(
                            "MOVE_HERO",
                            hero_name=closest.name,
                            target_room_index=path[1],
                        )

        return None

    def _macro_buy_merchant(self, state: GameStatePayload) -> Optional[dict]:
        """
        Step 8: Buy the cheapest item from a merchant if affordable.
        Equip to Gork if possible, Max otherwise.
        Dispatches a hero to the merchant's room first if needed.
        """
        if not state.merchants:
            return None
        if state.resources is None:
            return None

        for merchant in state.merchants:
            if not merchant.items:
                continue

            # Find cheapest item we can afford
            currency = self._get_currency_amount(state, merchant.currency_type)
            affordable_items = [
                item for item in merchant.items
                if item.cost <= currency
                and f"{merchant.room_index}:{item.name}" not in self._bought_this_turn
            ]
            if not affordable_items:
                continue

            cheapest = min(affordable_items, key=lambda i: i.cost)

            # Check if a hero is in the merchant's room
            hero_in_room = next(
                (h for h in state.heroes if h.room_index == merchant.room_index),
                None,
            )
            if hero_in_room:
                self._bought_this_turn.add(f"{merchant.room_index}:{cheapest.name}")
                return _action(
                    "BUY_FROM_MERCHANT",
                    hero_name=hero_in_room.name,
                    item_name=cheapest.name,
                    merchant_room_index=merchant.room_index,
                )

            # Dispatch hero to merchant room (prefer Gork, then Max)
            gork = next((h for h in state.heroes if "Gork" in h.name), None)
            hero_to_send = gork if gork and not gork.is_operating else None
            if hero_to_send is None:
                available = self._get_available_heroes(state)
                hero_to_send = self._closest_hero_to_room(available, merchant.room_index) if available else None

            if hero_to_send and hero_to_send.room_index != merchant.room_index:
                path = self._path_through_open_doors(hero_to_send.room_index, merchant.room_index)
                if path and len(path) >= 2:
                    return _action(
                        "MOVE_HERO",
                        hero_name=hero_to_send.name,
                        target_room_index=path[1],
                    )

        return None

    def _macro_equip_items(self, state: GameStatePayload) -> Optional[dict]:
        """
        Step 8.5: Equip items from backpack/shared inventory to heroes.
        Prioritize equipping to Max first, then Gork.
        """
        all_items = state.backpack_items + state.shared_inventory_items
        if not all_items:
            return None

        # Order heroes: Max first, then Gork, then others
        heroes_ordered = sorted(
            state.heroes,
            key=lambda h: (0 if "Max" in h.name else 1 if "Gork" in h.name else 2),
        )

        for item in all_items:
            if item.name in self._equipped_this_turn:
                continue
            if not item.category:
                continue

            for hero in heroes_ordered:
                # Find an empty slot matching this item's category
                slot_match = next(
                    (s for s in hero.equipment
                     if s.slot_category == item.category and s.item_name is None),
                    None,
                )
                if slot_match:
                    self._equipped_this_turn.add(item.name)
                    return _action(
                        "EQUIP_ITEM",
                        hero_name=hero.name,
                        item_name=item.name,
                    )

        return None

    def _macro_position_gork(self, state: GameStatePayload) -> Optional[dict]:
        """
        Step 9: Move Gork to room 1 if he's not there already.
        Room 1 is the first opened room (defensive position).
        Only do this if there are other heroes alive (if Gork is solo, skip).
        """
        gork = next((h for h in state.heroes if "Gork" in h.name), None)
        if gork is None:
            return None
        if gork.is_operating:
            return None

        # Don't reposition Gork if he's the only hero alive — he needs to explore
        other_heroes = [h for h in state.heroes if "Gork" not in h.name]
        if not other_heroes:
            return None

        # Use tracked position if available (handles stale state)
        gork_room = self._hero_positions.get(gork.name, gork.room_index)
        if gork_room == 1:
            return None  # Already there

        # Check room 1 exists
        room1 = next((r for r in state.rooms if r.index == 1), None)
        if room1 is None:
            return None

        path = self._path_through_open_doors(gork_room, 1)
        if path and len(path) >= 2:
            return _action(
                "MOVE_HERO",
                hero_name=gork.name,
                target_room_index=path[1],
            )
        return None

    def _macro_open_any_door(self, state: GameStatePayload) -> Optional[dict]:
        """
        Step 10: Open any remaining unexplored door.
        Prefer Max for exploration, but use any available hero if Max is dead.
        If no doors left, this returns None (escape will be triggered by FSM).
        """
        # Find exploration hero: prefer Max, fall back to any available
        explorer = next(
            (h for h in state.heroes if "Max" in h.name and not h.is_operating),
            None,
        )
        if explorer is None:
            available = self._get_available_heroes(state)
            explorer = available[0] if available else None
        if explorer is None:
            return None

        explorer_room = explorer.room_index
        explorer_moved = explorer.name in self._moves_issued_this_turn

        for door in state.closed_doors:
            from_room = None
            target = None
            explored = {r.index for r in state.rooms}

            if door.room1_index in explored:
                from_room = door.room1_index
                target = door.room2_index
            elif door.room2_index in explored:
                from_room = door.room2_index
                target = door.room1_index
            else:
                continue

            door_key = (from_room, target)
            if door_key in self._doors_opened_this_turn:
                continue

            if explorer_room == from_room and not explorer_moved:
                # Explorer is confirmed at the door's source — open it
                self._doors_opened_this_turn.add(door_key)
                return _action(
                    "OPEN_DOOR",
                    hero_name=explorer.name,
                    from_room_index=from_room,
                    target_room_index=target,
                )

            # Explorer isn't at the door source (or just moved) — move them there
            if not explorer_moved:
                path = self._path_through_open_doors(explorer_room, from_room)
                if path and len(path) >= 2:
                    return _action(
                        "MOVE_HERO",
                        hero_name=explorer.name,
                        target_room_index=path[1],
                    )

        return None

    def _try_build_module(self, state: GameStatePayload) -> Optional[dict]:
        """
        Build modules in empty slots.
        Priority: Industry > Food > Defense (minor turrets).
        Only build if we can afford it.
        Skips the start room (crystal room has special constraints).
        Skips rooms that suffered a failed build this turn.
        """
        if state.resources is None:
            return None

        industry = state.resources.industry

        # Find rooms with empty major slots (no major module)
        for room in state.rooms:
            # Skip crystal/start room — its major slot is used by the crystal
            if room.is_start_room:
                continue
            room_key = f"{room.index}:major"
            if room_key in self._built_modules_this_turn:
                continue
            if room_key in self._failed_actions:
                continue
            if room.major_module_name is None and not room.suffers_emp:
                # Prioritize: Industry if low production, Food next, then Science
                module = self._select_major_module(state, room)
                if module and industry >= 10:  # Approximate cost check
                    self._built_modules_this_turn.add(room_key)
                    return _action(
                        "BUILD_MODULE",
                        room_index=room.index,
                        module_name=module,
                        slot_type="major",
                    )

        # Build minor modules (defensive turrets) in rooms with open minor slots
        for room in state.rooms:
            if room.is_start_room:
                continue
            minor_used = len(room.minor_module_names)
            if minor_used < room.minor_slot_count and not room.suffers_emp:
                room_key = f"{room.index}:minor:{minor_used}"
                if room_key in self._built_modules_this_turn:
                    continue
                if room_key in self._failed_actions:
                    continue
                if industry >= 8:  # Approximate minor module cost
                    module = self._select_minor_module(state, room)
                    if module:
                        self._built_modules_this_turn.add(room_key)
                        return _action(
                            "BUILD_MODULE",
                            room_index=room.index,
                            module_name=module,
                            slot_type="minor",
                        )

        return None

    def _select_major_module(self, state: GameStatePayload, room: RoomState) -> Optional[str]:
        """
        Select the best major module to build in a room.
        Priority: Industry > Food > Science.
        """
        if state.resources is None:
            return None

        # Simple heuristic: if we have fewer industry producers, build industry
        industry_count = sum(
            1 for r in state.rooms
            if r.major_module_name and "Ind" in (r.major_module_name or "")
        )
        food_count = sum(
            1 for r in state.rooms
            if r.major_module_name and "Food" in (r.major_module_name or "")
        )

        if industry_count <= food_count:
            return "IndustryGenerator_1"  # Basic industry module
        return "FoodGenerator_1"  # Basic food module

    def _select_minor_module(self, state: GameStatePayload, room: RoomState) -> Optional[str]:
        """Select a minor module for defense."""
        return "Turret_1"  # Basic turret

    def _try_research(self, state: GameStatePayload) -> Optional[dict]:
        """Queue research from available blueprints (Task 4.5)."""
        if not state.researchable_blueprints:
            return None
        if state.resources is None:
            return None

        # Research requires an artifact on the floor
        has_artifact = any(r.has_artifact for r in state.rooms)
        if not has_artifact:
            return None

        # Check artifact safety (GL-7)
        if self.guidelines.gate_research_on_artifact_safety:
            if self._artifact_under_threat(state):
                return None

        available_science = state.resources.science

        # Pick the most expensive blueprint we can afford
        affordable = [
            bp for bp in state.researchable_blueprints
            if bp.science_cost <= available_science
            and bp.name not in self._researched_this_turn
            and bp.name not in self._failed_actions
        ]
        if not affordable:
            return None

        # Sort by cost descending — pick most expensive affordable
        affordable.sort(key=lambda bp: bp.science_cost, reverse=True)
        chosen = affordable[0]
        self._researched_this_turn.add(chosen.name)
        return _action("RESEARCH", blueprint_name=chosen.name)

    def _try_level_up(self, state: GameStatePayload) -> Optional[dict]:
        """
        Level up heroes using food (Task 4.7).
        GL-4: Prioritize Max O'Kane until Operate is unlocked.
        """
        if state.resources is None:
            return None
        food = state.resources.food

        heroes_to_level = []
        for hero in state.heroes:
            if hero.name in self._leveled_this_turn:
                continue
            # Can we afford it? level_up_cost isn't in wire format, use heuristic
            level_cost = hero.level * 5 + 10  # Approximate cost formula
            if food >= level_cost:
                heroes_to_level.append(hero)

        if not heroes_to_level:
            return None

        # GL-4: Prioritize Max O'Kane for Operate unlock
        if self.guidelines.prioritize_max_operate_unlock:
            max_hero = next(
                (h for h in heroes_to_level if "Max" in h.name or "H0001" in h.name),
                None,
            )
            if max_hero:
                has_operate = any(
                    p.name.lower() == "operate" for p in max_hero.passive_skills
                )
                if not has_operate:
                    self._leveled_this_turn.add(max_hero.name)
                    return _action("LEVEL_UP_HERO", hero_name=max_hero.name)

        # Level up whoever is available (lowest level first)
        heroes_to_level.sort(key=lambda h: h.level)
        hero = heroes_to_level[0]
        self._leveled_this_turn.add(hero.name)
        return _action("LEVEL_UP_HERO", hero_name=hero.name)

    def _try_buy_merchant(self, state: GameStatePayload) -> Optional[dict]:
        """
        Evaluate merchant items and buy upgrades (Task 4.8).
        Buy if item is meaningful upgrade and dust/currency allows.
        """
        if not state.merchants:
            return None
        if state.resources is None:
            return None

        for merchant in state.merchants:
            for item in merchant.items:
                item_key = f"{merchant.room_index}:{item.name}"
                if item_key in self._bought_this_turn:
                    continue

                # Check if we can afford it
                currency_amount = self._get_currency_amount(state, merchant.currency_type)
                if currency_amount < item.cost:
                    continue

                # Find a hero in the merchant's room
                hero_in_room = next(
                    (h for h in state.heroes if h.room_index == merchant.room_index),
                    None,
                )
                if hero_in_room is None:
                    # Dispatch a hero to the merchant (will be handled next tick)
                    available = self._get_available_heroes(state)
                    if available:
                        closest = self._closest_hero_to_room(available, merchant.room_index)
                        if closest and closest.room_index != merchant.room_index:
                            return _action(
                                "MOVE_HERO",
                                hero_name=closest.name,
                                target_room_index=merchant.room_index,
                            )
                    continue

                self._bought_this_turn.add(item_key)
                return _action(
                    "BUY_FROM_MERCHANT",
                    hero_name=hero_in_room.name,
                    item_name=item.name,
                    merchant_room_index=merchant.room_index,
                )

        return None

    def _try_recruit(self, state: GameStatePayload) -> Optional[dict]:
        """
        Recruit heroes when food allows (Task 4.9).
        Dispatch a hero to the recruit's room first if needed.
        """
        if not state.recruitable_heroes:
            return None
        if state.resources is None:
            return None

        food = state.resources.food

        for recruit in state.recruitable_heroes:
            if recruit.name in self._recruited_this_turn:
                continue

            # Approximate recruit cost (not in wire format, use heuristic)
            recruit_cost = 20  # Default food cost estimate
            if food < recruit_cost:
                continue

            # Find a hero in the recruit's room
            hero_in_room = next(
                (h for h in state.heroes if h.room_index == recruit.room_index),
                None,
            )
            if hero_in_room is None:
                # Dispatch a hero to recruit location
                available = self._get_available_heroes(state)
                if available:
                    closest = self._closest_hero_to_room(available, recruit.room_index)
                    if closest and closest.room_index != recruit.room_index:
                        return _action(
                            "MOVE_HERO",
                            hero_name=closest.name,
                            target_room_index=recruit.room_index,
                        )
                continue

            self._recruited_this_turn.add(recruit.name)
            return _action(
                "RECRUIT_HERO",
                recruiter_hero_name=hero_in_room.name,
                recruit_name=recruit.name,
            )

        return None

    def _try_equip(self, state: GameStatePayload) -> Optional[dict]:
        """
        Equip items from backpack or shared inventory to heroes (Task 4.10).
        Evaluate which hero benefits most from each item.
        """
        # Check backpack and shared inventory for equippable items
        all_items = state.backpack_items + state.shared_inventory_items
        if not all_items:
            return None

        for item in all_items:
            if item.name in self._equipped_this_turn:
                continue
            if not item.category:
                continue

            # Find a hero with an empty slot matching this item's category
            for hero in state.heroes:
                slot_match = next(
                    (s for s in hero.equipment if s.slot_category == item.category and s.item_name is None),
                    None,
                )
                if slot_match:
                    self._equipped_this_turn.add(item.name)
                    return _action(
                        "EQUIP_ITEM",
                        hero_name=hero.name,
                        item_name=item.name,
                    )

        return None

    def _try_collect_dust(self, state: GameStatePayload) -> Optional[dict]:
        """
        Collect dropped dust by moving heroes to dust rooms (Task 4.11).
        Dispatch nearest non-operating hero.
        """
        dust_items = [
            item for item in state.dropped_items
            if item.type == "Dust" and item.room_index not in self._collected_this_turn
        ]
        if not dust_items:
            # Also check rooms with dust_loot_amount
            dust_rooms = [
                r for r in state.rooms
                if r.dust_loot_amount > 0 and r.index not in self._collected_this_turn
            ]
            if not dust_rooms:
                return None
            # Move a hero to collect
            available = self._get_available_heroes(state)
            if not available:
                return None
            for room in dust_rooms:
                hero_in_room = next(
                    (h for h in state.heroes if h.room_index == room.index),
                    None,
                )
                if hero_in_room:
                    # Hero is already there, dust auto-collects
                    self._collected_this_turn.add(room.index)
                    continue
                closest = self._closest_hero_to_room(available, room.index)
                if closest:
                    self._collected_this_turn.add(room.index)
                    return _action(
                        "MOVE_HERO",
                        hero_name=closest.name,
                        target_room_index=room.index,
                    )
            return None

        # Move hero to dust item room
        available = self._get_available_heroes(state)
        if not available:
            return None

        for item in dust_items:
            hero_in_room = next(
                (h for h in state.heroes if h.room_index == item.room_index),
                None,
            )
            if hero_in_room:
                self._collected_this_turn.add(item.room_index)
                continue  # Auto-collected
            closest = self._closest_hero_to_room(available, item.room_index)
            if closest:
                self._collected_this_turn.add(item.room_index)
                return _action(
                    "MOVE_HERO",
                    hero_name=closest.name,
                    target_room_index=item.room_index,
                )

        return None

    def _try_operator_placement(self, state: GameStatePayload) -> Optional[dict]:
        """
        Place heroes with Operate passive in rooms with major modules (Task 4.12, GL-3).
        Prefer safe rooms (powered, no mobs, away from frontline).
        """
        if not self.guidelines.protect_operators:
            return None

        # Find heroes with Operate passive who aren't already operating
        operators = [
            h for h in state.heroes
            if self._has_passive(h, "Operate") and not h.is_operating
        ]
        if not operators:
            return None

        # Find rooms with major modules that aren't being operated
        operated_rooms = {
            h.room_index for h in state.heroes if h.is_operating
        }
        candidate_rooms = [
            r for r in state.rooms
            if r.major_module_name is not None
            and r.index not in operated_rooms
            and r.is_powered
            and r.mob_count == 0
            and not self._is_room_hazardous(state, r.index)
        ]
        if not candidate_rooms:
            return None

        # Sort candidate rooms: prefer crystal room area (safe), then by depth
        candidate_rooms.sort(key=lambda r: r.depth)

        for operator in operators:
            if operator.room_index in operated_rooms:
                continue
            for room in candidate_rooms:
                if room.index == operator.room_index:
                    # Already in the room — hero will auto-operate
                    break
                # Move operator to the room
                path = self._path_through_open_doors(operator.room_index, room.index)
                if path and len(path) >= 2:
                    return _action(
                        "MOVE_HERO",
                        hero_name=operator.name,
                        target_room_index=path[1],
                    )
                break

        return None

    def _try_power_management(self, state: GameStatePayload) -> Optional[dict]:
        """
        Power allocation using room centrality (Task 4.6).
        Power high-centrality rooms on the crystal-to-exit path.
        Unpower dead-end rooms to save dust budget.
        """
        if self._graph is None or state.resources is None:
            return None

        dust = state.resources.dust
        dust_max = state.resources.dust_max
        power_cost = state.resources.room_power_cost or 1

        # Rooms we want powered: crystal path + bottlenecks
        path = escape_path_rooms(self._graph)
        bottlenecks = bottleneck_rooms(self._graph, top_n=5)
        priority_rooms = set(path + bottlenecks)

        # Power unpowered priority rooms if we have dust budget
        for room in state.rooms:
            if room.index in self._powered_this_turn:
                continue
            if room.index in priority_rooms and not room.is_powered and not room.is_auto_powered:
                # Check if we can afford to power it
                powered_count = state.resources.powered_room_count
                total_cost = (powered_count + 1) * power_cost
                if dust > total_cost:
                    self._powered_this_turn.add(room.index)
                    return _action("POWER_ROOM", room_index=room.index)

        # Unpower non-priority rooms to free dust (if budget is tight)
        if dust < dust_max * 0.4:
            for room in state.rooms:
                if room.index in self._unpowered_this_turn:
                    continue
                if (
                    room.is_powered
                    and not room.is_auto_powered
                    and room.index not in priority_rooms
                    and room.mob_count == 0
                    and room.hero_count == 0
                ):
                    self._unpowered_this_turn.add(room.index)
                    return _action("UNPOWER_ROOM", room_index=room.index)

        return None

    # ------------------------------------------------------------------
    # DEFEND State (Task 4.13)
    # ------------------------------------------------------------------

    def _handle_defend(self, state: GameStatePayload) -> Optional[dict]:
        """
        DEFEND: Position non-operator heroes in bottleneck rooms during waves.

        Logic:
          - Identify rooms where mobs are present or approaching
          - Position heroes in bottleneck rooms to block enemy paths
          - Don't move operators (GL-3)
          - Don't move crystal carrier
          - Heroes auto-target closest enemy (no focus-fire commands needed)
          - Prioritize crystal/artifact defense when targeted (Tasks 4.26, 4.27)
          - Avoid hazardous rooms (toxic clouds, EMP) (Tasks 4.29, 4.30)
        """
        if self._graph is None:
            return None

        # Get defensive heroes (non-operating, non-carrying-crystal)
        defenders = [
            h for h in state.heroes
            if not h.is_operating and not h.has_crystal
            and (not self.guidelines.protect_operators or not self._has_passive(h, "Operate"))
        ]
        if not defenders:
            return None

        # Identify high-priority defense rooms
        defense_targets = set()

        # Task 4.27: Crystal under threat — prioritize crystal room
        if self._crystal_under_threat(state):
            crystal_targets = self._get_crystal_defense_targets(state)
            defense_targets.update(crystal_targets)

        # Task 4.26: Artifact under threat — prioritize artifact rooms
        if self._artifact_under_threat(state):
            artifact_targets = self._get_artifact_defense_targets(state)
            defense_targets.update(artifact_targets)

        # Standard: rooms with mobs + adjacent rooms
        mob_rooms = rooms_with_mobs(self._graph)
        if mob_rooms:
            defense_targets.update(mob_rooms)
            for room_idx in mob_rooms:
                for neighbor in self._graph.neighbors(room_idx):
                    edge_data = self._graph.edges[room_idx, neighbor]
                    if edge_data.get("is_open", False):
                        node_data = self._graph.nodes.get(neighbor, {})
                        if node_data.get("is_powered", False):
                            defense_targets.add(neighbor)

        # Always include crystal room
        crystal_room = state.start_room_index
        defense_targets.add(crystal_room)

        if not defense_targets:
            return None

        # Task 4.29/4.30: Remove hazardous rooms from targets
        safe_targets = {
            r for r in defense_targets
            if not self._is_room_hazardous(state, r)
        }
        # Fall back to all targets if all are hazardous
        if not safe_targets:
            safe_targets = defense_targets

        # Position defenders toward threat
        for hero in defenders:
            if hero.room_index in safe_targets:
                continue  # Already in a good position

            # Find closest safe defense target
            best_target = None
            best_dist = float("inf")
            for target in safe_targets:
                path = self._path_through_open_doors(hero.room_index, target)
                if path:
                    dist = len(path) - 1
                    if dist < best_dist:
                        best_dist = dist
                        best_target = target

            if best_target is not None and best_dist > 0:
                path = self._path_through_open_doors(hero.room_index, best_target)
                if path and len(path) >= 2:
                    return _action(
                        "MOVE_HERO",
                        hero_name=hero.name,
                        target_room_index=path[1],
                    )

        return None

    # ------------------------------------------------------------------
    # RETREAT State (Task 4.14)
    # ------------------------------------------------------------------

    def _handle_retreat(self, state: GameStatePayload) -> Optional[dict]:
        """
        RETREAT: Move wounded heroes toward room 1 (defensive rally point).

        If HP < threshold, move toward room 1 where Gork and prisoner prods defend.
        Exception: fall back to crystal room (room 0) if mobs are detected IN room 1.
        """
        if not self.guidelines.retreat_enabled:
            return self._handle_defend(state)

        threshold = self.guidelines.retreat_hp_threshold

        # Rally room is room 1, unless room 1 has mobs — then fall back to crystal room
        rally_room = 1
        room1 = next((r for r in state.rooms if r.index == 1), None)
        if room1 and room1.mob_count > 0:
            rally_room = state.start_room_index  # Fall back to crystal room

        for hero in state.heroes:
            if hero.has_crystal:
                continue
            if hero.max_hp <= 0:
                continue
            hero_room = self._hero_room(hero)
            hp_ratio = hero.hp / hero.max_hp
            if hp_ratio < threshold and hero_room != rally_room:
                # Move toward rally room
                path = self._path_through_open_doors(hero_room, rally_room)
                if path and len(path) >= 2:
                    return _action(
                        "MOVE_HERO",
                        hero_name=hero.name,
                        target_room_index=path[1],
                    )

        # All wounded heroes are at crystal room or no one needs retreat
        # Fall through to DEFEND
        return self._handle_defend(state)

    # ------------------------------------------------------------------
    # ESCAPE State (Tasks 4.15-4.17)
    # ------------------------------------------------------------------

    def _handle_escape(self, state: GameStatePayload) -> Optional[dict]:
        """
        ESCAPE: Orchestrate floor escape.

        Sequence:
          1. Depower all non-auto-powered rooms (frees dust)
          2. Power rooms on escape path (crystal room → exit)
          3. Send Gork to exit room to wait
          4. Move Max to crystal room
          5. Pick up crystal
          6. Move Max (with crystal) to exit room
          7. Exit the floor
        """
        if self._graph is None:
            return None

        exit_room = state.exit_room_index
        crystal_room = state.start_room_index
        escape_path = escape_path_rooms(self._graph)

        # Find heroes
        max_hero = next((h for h in state.heroes if "Max" in h.name), None)
        gork = next((h for h in state.heroes if "Gork" in h.name), None)

        if max_hero is None:
            return None

        # --- Step 1: Depower all non-auto rooms NOT on escape path ---
        escape_path_set = set(escape_path) if escape_path else set()
        for room in state.rooms:
            if (
                room.is_powered
                and not room.is_auto_powered
                and room.index not in escape_path_set
                and room.index not in self._unpowered_this_turn
            ):
                self._unpowered_this_turn.add(room.index)
                return _action("UNPOWER_ROOM", room_index=room.index)

        # --- Step 2: Power escape path rooms ---
        if escape_path:
            for room_idx in escape_path:
                if room_idx in self._powered_this_turn:
                    continue
                room = next((r for r in state.rooms if r.index == room_idx), None)
                if room and not room.is_powered and not room.is_auto_powered:
                    self._powered_this_turn.add(room_idx)
                    return _action("POWER_ROOM", room_index=room_idx)

        # --- Step 3: Send Gork to exit room ---
        if gork and gork.room_index != exit_room:
            gork_room = self._hero_room(gork)
            if gork_room != exit_room and gork.name not in self._moves_issued_this_turn:
                path = self._path_through_open_doors(gork_room, exit_room)
                if path and len(path) >= 2:
                    return _action(
                        "MOVE_HERO",
                        hero_name=gork.name,
                        target_room_index=path[1],
                    )

        # --- Step 4: Move Max to crystal room (if he doesn't have crystal yet) ---
        if not max_hero.has_crystal:
            max_room = max_hero.room_index
            if max_room != crystal_room:
                if max_hero.name not in self._moves_issued_this_turn:
                    path = self._path_through_open_doors(max_room, crystal_room)
                    if path and len(path) >= 2:
                        return _action(
                            "MOVE_HERO",
                            hero_name=max_hero.name,
                            target_room_index=path[1],
                        )
                return None  # Wait for Max to arrive
            else:
                # --- Step 5: Pick up crystal ---
                return _action("PICK_UP_CRYSTAL", hero_name=max_hero.name)

        # --- Step 6: Move Max (with crystal) to exit room ---
        if max_hero.has_crystal:
            max_room = max_hero.room_index
            if max_room != exit_room:
                if max_hero.name not in self._moves_issued_this_turn:
                    path = self._path_through_open_doors(max_room, exit_room)
                    if path and len(path) >= 2:
                        return _action(
                            "MOVE_HERO",
                            hero_name=max_hero.name,
                            target_room_index=path[1],
                        )
                return None  # Wait for Max to arrive
            else:
                # Max is at exit with crystal — send EXIT_FLOOR command
                return _action("EXIT_FLOOR")

        return None

    # ------------------------------------------------------------------
    # Advanced Logic (Tasks 4.24-4.30)
    # ------------------------------------------------------------------

    def _try_sell_to_merchant(self, state: GameStatePayload) -> Optional[dict]:
        """
        Sell unwanted items to merchants (Task 4.24).

        Sell items from shared inventory that don't fit any hero's empty slot
        and are lower rarity than what's already equipped.
        """
        if not state.merchants:
            return None

        # Gather equipped item names for comparison
        equipped_names = set()
        for hero in state.heroes:
            for slot in hero.equipment:
                if slot.item_name:
                    equipped_names.add(slot.item_name)

        # Find items in shared inventory that are not equipped and not in backpack
        sellable_items = [
            item for item in state.shared_inventory_items
            if item.name not in equipped_names
        ]
        if not sellable_items:
            return None

        # Find a merchant with a hero present in the room
        for merchant in state.merchants:
            hero_in_room = next(
                (h for h in state.heroes if h.room_index == merchant.room_index),
                None,
            )
            if hero_in_room is None:
                continue

            for item in sellable_items:
                sell_key = f"sell:{item.name}"
                if sell_key in self._bought_this_turn:  # Reuse tracking to prevent loops
                    continue
                self._bought_this_turn.add(sell_key)
                return _action(
                    "SELL_TO_MERCHANT",
                    hero_name=hero_in_room.name,
                    merchant_id="",  # Wire format may not need this
                    item_name=item.name,
                )

        return None

    def _try_pre_escape_inventory(self, state: GameStatePayload) -> Optional[dict]:
        """
        Move valuable items to backpack before escape (GL-8, Task 4.25).

        Backpack has 4 slots; items there persist between floors.
        Move the best items from shared inventory to backpack before escaping.
        """
        if not self.guidelines.pre_escape_inventory_management:
            return None
        if not self._escape_initiated:
            return None

        # Max 4 backpack slots
        backpack_count = len(state.backpack_items)
        if backpack_count >= 4:
            return None

        # Move shared inventory items to backpack, prioritizing by rarity
        rarity_order = {"Legendary": 4, "Epic": 3, "Rare": 2, "Uncommon": 1, "Common": 0}
        sorted_items = sorted(
            state.shared_inventory_items,
            key=lambda i: rarity_order.get(i.rarity, 0),
            reverse=True,
        )

        for item in sorted_items:
            return _action("MOVE_TO_BACKPACK", item_name=item.name)

        return None

    def _try_interact_room_items(self, state: GameStatePayload) -> Optional[dict]:
        """
        Interact with room items: chests, banquets, machines (Task 4.28).

        Only interact with "safe" items (Chests are always free).
        Skip risky interactables unless the reward is clearly worth it.
        """
        # Find chest-type dropped items
        interactables = [
            item for item in state.dropped_items
            if item.type == "Chest"
        ]
        if not interactables:
            return None

        for item in interactables:
            interact_key = f"interact:{item.room_index}:{item.name}"
            if interact_key in self._collected_this_turn:
                continue

            # Find a hero in the item's room
            hero_in_room = next(
                (h for h in state.heroes if h.room_index == item.room_index),
                None,
            )
            if hero_in_room:
                self._collected_this_turn.add(interact_key)
                return _action(
                    "INTERACT_ROOM_ITEM",
                    hero_name=hero_in_room.name,
                    item_id=item.name or "",
                )

            # Dispatch a hero (only if the room is safe)
            room = next((r for r in state.rooms if r.index == item.room_index), None)
            if room and room.mob_count == 0:
                available = self._get_available_heroes(state)
                if available:
                    closest = self._closest_hero_to_room(available, item.room_index)
                    if closest and closest.room_index != item.room_index:
                        self._collected_this_turn.add(interact_key)
                        return _action(
                            "MOVE_HERO",
                            hero_name=closest.name,
                            target_room_index=item.room_index,
                        )

        return None

    def _artifact_under_threat(self, state: GameStatePayload) -> bool:
        """
        Check if artifact-targeting mobs exist on the floor (GL-7, Task 4.26).

        Returns True if there are artifact-targeting mobs AND an artifact exists,
        meaning the macro-planner should prioritize artifact defense over research.
        """
        artifact_rooms = [r for r in state.rooms if r.has_artifact]
        if not artifact_rooms:
            return False
        artifact_mobs = [m for m in state.mobs if m.target_type == "Artifact"]
        return len(artifact_mobs) > 0

    def _crystal_under_threat(self, state: GameStatePayload) -> bool:
        """
        Check if crystal-targeting mobs are present (Task 4.27).

        When True, the micro-controller should shift defensive priority
        to the crystal room and adjacent rooms.
        """
        crystal_mobs = [m for m in state.mobs if m.target_type == "Crystal"]
        return len(crystal_mobs) > 0

    def _is_room_hazardous(self, state: GameStatePayload, room_index: int) -> bool:
        """
        Check if a room has environmental hazards (toxic cloud or EMP) (Tasks 4.29-4.30).

        Used by micro-controller to avoid positioning heroes in dangerous rooms
        and macro-controller to avoid assigning operators there.
        """
        room = next((r for r in state.rooms if r.index == room_index), None)
        if room is None:
            return False
        # EMP: modules don't work (Task 4.30)
        if room.suffers_emp:
            return True
        # Toxic cloud: not currently in wire format, but prepared for expansion
        # Would check a hypothetical room.has_toxic_cloud field
        return False

    def _get_artifact_defense_targets(self, state: GameStatePayload) -> list[int]:
        """
        Get room indices that need artifact defense (Task 4.26).

        Returns rooms containing artifacts plus their powered neighbors
        where heroes should be positioned.
        """
        artifact_rooms = [r.index for r in state.rooms if r.has_artifact]
        defense_targets = set(artifact_rooms)

        # Add adjacent rooms to artifact rooms (defense perimeter)
        if self._graph:
            for room_idx in artifact_rooms:
                for neighbor in self._graph.neighbors(room_idx):
                    edge_data = self._graph.edges[room_idx, neighbor]
                    if edge_data.get("is_open", False):
                        defense_targets.add(neighbor)

        return list(defense_targets)

    def _get_crystal_defense_targets(self, state: GameStatePayload) -> list[int]:
        """
        Get room indices for crystal defense when crystal-targeting mobs appear (Task 4.27).

        Prioritize the crystal room itself and its immediate neighbors.
        """
        crystal_room = state.start_room_index
        defense_targets = {crystal_room}

        if self._graph and crystal_room in self._graph:
            for neighbor in self._graph.neighbors(crystal_room):
                edge_data = self._graph.edges[crystal_room, neighbor]
                if edge_data.get("is_open", False):
                    defense_targets.add(neighbor)

        return list(defense_targets)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_available_heroes(self, state: GameStatePayload) -> list[HeroState]:
        """Get heroes that can be dispatched (not operating, not carrying crystal)."""
        heroes = []
        for h in state.heroes:
            if h.has_crystal:
                continue
            if h.is_operating and self.guidelines.protect_operators:
                continue
            heroes.append(h)
        return heroes

    def _hero_room(self, hero: HeroState) -> int:
        """Get the hero's effective room (tracked position or state position)."""
        return self._hero_positions.get(hero.name, hero.room_index)

    def _closest_hero_to_room(
        self, heroes: list[HeroState], target_room: int
    ) -> Optional[HeroState]:
        """Find the hero closest to a target room via open doors."""
        best_hero = None
        best_dist = float("inf")
        for hero in heroes:
            hero_room = self._hero_room(hero)
            if hero_room == target_room:
                return hero
            path = self._path_through_open_doors(hero_room, target_room)
            if path:
                dist = len(path) - 1
                if dist < best_dist:
                    best_dist = dist
                    best_hero = hero
        return best_hero

    def _path_through_open_doors(self, from_room: int, to_room: int) -> list[int]:
        """Find shortest path using only open doors."""
        if self._graph is None:
            return []
        if from_room == to_room:
            return [from_room]
        # Build subgraph of open doors
        open_edges = [
            (u, v)
            for u, v, d in self._graph.edges(data=True)
            if d.get("is_open", False)
        ]
        if not open_edges:
            return []
        subgraph = self._graph.edge_subgraph(open_edges).copy()
        # Add isolated nodes
        for node in self._graph.nodes:
            if node not in subgraph:
                subgraph.add_node(node, **self._graph.nodes[node])
        try:
            return nx.shortest_path(subgraph, from_room, to_room)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    def _has_passive(self, hero: HeroState, passive_name: str) -> bool:
        """Check if a hero has a specific passive skill."""
        return any(p.name.lower() == passive_name.lower() for p in hero.passive_skills)

    def _get_currency_amount(self, state: GameStatePayload, currency_type: str) -> float:
        """Get the current amount of a currency type."""
        if state.resources is None:
            return 0.0
        currency_map = {
            "Dust": state.resources.dust,
            "Food": state.resources.food,
            "Industry": state.resources.industry,
            "Science": state.resources.science,
        }
        return currency_map.get(currency_type, 0.0)

    def _update_explored_rooms(self, state: GameStatePayload) -> None:
        """Track which rooms have been explored (present in state = explored)."""
        for room in state.rooms:
            self._explored_rooms.add(room.index)

    def _clear_turn_tracking(self) -> None:
        """Clear per-turn action tracking sets."""
        self._built_modules_this_turn.clear()
        self._leveled_this_turn.clear()
        self._powered_this_turn.clear()
        self._unpowered_this_turn.clear()
        self._collected_this_turn.clear()
        self._recruited_this_turn.clear()
        self._equipped_this_turn.clear()
        self._bought_this_turn.clear()
        self._researched_this_turn.clear()
        self._repaired_this_turn.clear()
        self._doors_opened_this_turn.clear()
        self._failed_actions.clear()
        self._hero_positions.clear()
        self._moves_issued_this_turn.clear()
        self._last_action_failed = False

    @property
    def current_phase(self) -> AgentPhase:
        """Get the current FSM phase."""
        return self._phase

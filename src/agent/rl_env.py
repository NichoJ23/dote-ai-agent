"""
RLEnv: Enhanced Gymnasium environment for RL training on Dungeon of the ENDLESS.

Key differences from DotEEnv (Phase 3):
  - Hierarchical action space: Level 1 = StrategicOption, Level 2 = parameters
  - Action masking: impossible actions masked before policy sees them
  - Direct-destination movement (no hop-by-hop)
  - Multi-action per strategy turn: agent takes actions until WAIT or OPEN_DOOR
  - Richer observation space with power-reachability, distances, hero flags
  - Configurable reward shaping via RewardConfig
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from action_masking import ActionMaskComputer, NUM_OPTIONS, StrategicOption
from graph_builder import GraphBuilder
from graph_utils import escape_path_rooms, shortest_path_to_crystal, shortest_path_to_exit
from ipc_client import IpcClient
from reward_shaping import RewardShaper
from rl_config import RLConfig, RewardConfig
from state_parser import GamePhase, GameStatePayload, StateParser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_ROOMS = 30
MAX_HEROES = 6
MAX_MOBS = 50
MAX_MODULES = 40       # Max buildable blueprints tracked
MAX_RESEARCH = 20      # Max researchable blueprints
MAX_RECRUITS = 4       # Max recruitable heroes at once
MAX_MERCHANT_ITEMS = 12  # Max merchant items across all merchants
MAX_INVENTORY = 20     # Max backpack + shared inventory items

# Room feature count
ROOM_FEATURE_DIM = 20
# Hero feature count
HERO_FEATURE_DIM = 22
# Mob feature count
MOB_FEATURE_DIM = 5
# Game meta count
GAME_META_DIM = 12
# Resource count
RESOURCE_DIM = 10


# ---------------------------------------------------------------------------
# RLEnv
# ---------------------------------------------------------------------------


class RLEnv(gym.Env):
    """
    Gymnasium environment for RL training on Dungeon of the ENDLESS.

    Observation space: Dict with spatial graph, entity features, resources,
    available actions context, and game metadata.

    Action space: Dict with:
      - option: Discrete(NUM_OPTIONS) — which strategic option to take
      - room_target: Discrete(MAX_ROOMS) — target room for the option
      - hero_target: Discrete(MAX_HEROES) — which hero to act on/with
      - entity_target: Discrete(max_entities) — for modules/items/research

    The environment also provides an "action_mask" in the info dict (and via
    the observation) for invalid action filtering.
    """

    metadata = {"render_modes": ["human", "json"]}

    def __init__(
        self,
        host: str = "127.0.0.1",
        state_port: int = 5555,
        action_port: int = 5556,
        config: Optional[RLConfig] = None,
        render_mode: Optional[str] = None,
        connect_timeout: float = 300.0,
        recv_timeout: float = 30.0,
    ):
        super().__init__()
        self.render_mode = render_mode
        self._config = config or RLConfig()

        # IPC
        self._ipc = IpcClient(
            host=host,
            state_port=state_port,
            action_port=action_port,
            connect_timeout=connect_timeout,
            recv_timeout=recv_timeout,
        )

        # Components
        self._parser = StateParser()
        self._graph_builder = GraphBuilder()
        self._mask_computer = ActionMaskComputer()
        self._reward_shaper = RewardShaper(self._config.rewards)

        # State
        self._current_state: Optional[GameStatePayload] = None
        self._prev_state: Optional[GameStatePayload] = None
        self._connected = False
        self._step_count = 0
        self._episode_reward = 0.0

        # Hero movement tracking: hero_name -> target_room_index
        self._hero_move_targets: dict[str, int] = {}

        # Hero collection tracking: hero_name -> item_room_index
        # Hero stays busy until is_gathering_item goes false after arriving
        self._hero_collecting: dict[str, int] = {}

        # --- Observation space ---
        self.observation_space = spaces.Dict({
            "adjacency": spaces.Box(0, 1, (MAX_ROOMS, MAX_ROOMS), dtype=np.int8),
            "door_state": spaces.Box(0, 1, (MAX_ROOMS, MAX_ROOMS), dtype=np.int8),
            "power_state": spaces.Box(0, 1, (MAX_ROOMS,), dtype=np.int8),
            "power_reachable": spaces.Box(0, 1, (MAX_ROOMS,), dtype=np.int8),
            "room_features": spaces.Box(-1, 200, (MAX_ROOMS, ROOM_FEATURE_DIM), dtype=np.float32),
            "hero_features": spaces.Box(-1, 1000, (MAX_HEROES, HERO_FEATURE_DIM), dtype=np.float32),
            "mob_features": spaces.Box(-1, 1000, (MAX_MOBS, MOB_FEATURE_DIM), dtype=np.float32),
            "resources": spaces.Box(-100, 10000, (RESOURCE_DIM,), dtype=np.float32),
            "game_meta": spaces.Box(-1, 10000, (GAME_META_DIM,), dtype=np.float32),
            "action_mask": spaces.Box(0, 1, (NUM_OPTIONS,), dtype=np.int8),
        })

        # --- Action space ---
        self.action_space = spaces.Dict({
            "option": spaces.Discrete(NUM_OPTIONS),
            "room_target": spaces.Discrete(MAX_ROOMS),
            "hero_target": spaces.Discrete(MAX_HEROES),
            "entity_target": spaces.Discrete(MAX_MODULES),
        })

    # ------------------------------------------------------------------
    # Gymnasium API
    # ------------------------------------------------------------------

    def reset(
        self, *, seed: Optional[int] = None, options: Optional[dict] = None
    ) -> tuple[dict, dict]:
        """Connect to game, receive initial state, return first observation."""
        super().reset(seed=seed)

        if not self._connected:
            self._ipc.connect()
            self._connected = True

        # Unpause to start
        self._ipc.send_action("UNPAUSE_GAME", {})

        # Wait for initial state
        raw_state = self._ipc.receive_state(timeout=60.0)
        self._current_state = self._parser.parse(raw_state)
        self._prev_state = None
        self._step_count = 0
        self._episode_reward = 0.0
        self._hero_move_targets.clear()
        self._hero_collecting.clear()

        obs = self._build_observation(self._current_state)
        info = self._build_info(self._current_state)
        return obs, info

    def step(self, action: dict) -> tuple[dict, float, bool, bool, dict]:
        """
        Execute one action step.

        During Strategy phase, the agent can take multiple actions per game turn.
        Each call to step() executes one action. When the agent selects WAIT,
        the turn is considered complete (but the env doesn't force a door open).
        When the agent selects OPEN_DOOR, it transitions to Action phase.

        Args:
            action: Dict with 'option', 'room_target', 'hero_target', 'entity_target'.

        Returns:
            (observation, reward, terminated, truncated, info)
        """
        option = StrategicOption(int(action["option"]))
        room_target = int(action["room_target"])
        hero_target = int(action["hero_target"])
        entity_target = int(action["entity_target"])

        # Clamp parameters to valid targets for the chosen option
        room_target, hero_target, entity_target = self._clamp_parameters(
            option, room_target, hero_target, entity_target
        )

        # Translate to game command
        command, parameters = self._translate_action(
            option, room_target, hero_target, entity_target
        )

        # Execute action
        action_result = None
        if command == "WAIT":
            # No-op: don't send anything to game, just get next state
            action_result = {"success": True}
        else:
            action_result = self._ipc.send_action(command, parameters)

        # Receive fresh state after action
        if command != "WAIT":
            raw_state = self._ipc.receive_state()
            self._prev_state = self._current_state
            self._current_state = self._parser.parse(raw_state)
        else:
            # For WAIT, we still get a state (periodic push or just keep current)
            self._prev_state = self._current_state
            try:
                raw_state = self._ipc.receive_state(timeout=2.0)
                self._current_state = self._parser.parse(raw_state)
            except Exception:
                pass  # Keep current state if no new state arrives

        # Update hero movement tracking
        self._update_move_targets()

        # Compute reward
        action_dict = {"command": command, "parameters": parameters}
        reward = self._reward_shaper.compute_reward(
            self._prev_state, self._current_state, action_dict, action_result
        )
        self._step_count += 1
        self._episode_reward += reward

        # Check termination
        terminated = self._current_state.is_game_over
        truncated = False

        # Build observation
        obs = self._build_observation(self._current_state)
        info = self._build_info(self._current_state)
        info["action_result"] = action_result
        info["action_sent"] = action_dict
        info["episode_reward"] = self._episode_reward

        return obs, reward, terminated, truncated, info

    def close(self) -> None:
        """Disconnect IPC."""
        if self._connected:
            try:
                self._ipc.disconnect()
            except Exception:
                pass
            self._connected = False

    # ------------------------------------------------------------------
    # Action Translation
    # ------------------------------------------------------------------

    def _translate_action(
        self,
        option: StrategicOption,
        room_target: int,
        hero_target: int,
        entity_target: int,
    ) -> tuple[str, dict]:
        """
        Translate hierarchical action into a concrete game command + parameters.

        Uses direct-destination for MOVE_HERO (no hop-by-hop).
        """
        state = self._current_state

        # Resolve hero name from index
        hero_name = ""
        if state and hero_target < len(state.heroes):
            hero_name = state.heroes[hero_target].name

        if option == StrategicOption.WAIT:
            return "WAIT", {}

        elif option == StrategicOption.POWER_ROOM:
            return "POWER_ROOM", {"room_index": room_target}

        elif option == StrategicOption.DEPOWER_ROOM:
            return "UNPOWER_ROOM", {"room_index": room_target}

        elif option == StrategicOption.BUILD_MODULE:
            module_name = self._resolve_buildable_module(entity_target)
            slot_type = "minor"
            if module_name and "Major" in module_name:
                slot_type = "major"
            return "BUILD_MODULE", {
                "room_index": room_target,
                "module_name": module_name,
                "slot_type": slot_type,
            }

        elif option == StrategicOption.DESTROY_MODULE:
            module_name = self._resolve_room_module(room_target, entity_target)
            return "SELL_MODULE", {
                "room_index": room_target,
                "module_name": module_name,
            }

        elif option == StrategicOption.RESEARCH:
            blueprint_name = self._resolve_research(entity_target)
            return "RESEARCH", {"blueprint_name": blueprint_name}

        elif option == StrategicOption.RECRUIT_HERO:
            recruit_name = self._resolve_recruit(entity_target)
            return "RECRUIT_HERO", {
                "recruiter_hero_name": hero_name,
                "recruit_name": recruit_name,
            }

        elif option == StrategicOption.DISMISS_HERO:
            return "DISMISS_HERO", {"hero_name": hero_name}

        elif option == StrategicOption.LEVEL_UP_HERO:
            return "LEVEL_UP_HERO", {"hero_name": hero_name}

        elif option == StrategicOption.BUY_ITEM:
            item_name, merchant_room = self._resolve_merchant_item(entity_target)
            return "BUY_FROM_MERCHANT", {
                "hero_name": hero_name,
                "item_name": item_name,
                "merchant_room_index": merchant_room,
            }

        elif option == StrategicOption.EQUIP_ITEM:
            item_name = self._resolve_inventory_item(entity_target)
            return "EQUIP_ITEM", {
                "hero_name": hero_name,
                "item_name": item_name,
            }

        elif option == StrategicOption.UNEQUIP_ITEM:
            slot_categories = ["Weapon", "Armor", "Accessory"]
            slot = slot_categories[entity_target % len(slot_categories)]
            return "UNEQUIP_ITEM", {
                "hero_name": hero_name,
                "slot_category": slot,
            }

        elif option == StrategicOption.POSITION_HERO:
            # Direct destination movement — game auto-paths
            self._hero_move_targets[hero_name] = room_target
            return "MOVE_HERO", {
                "hero_name": hero_name,
                "target_room_index": room_target,
            }

        elif option == StrategicOption.OPEN_DOOR:
            # Find the hero's current room and open a door from there
            from_room = 0
            if state and hero_target < len(state.heroes):
                from_room = state.heroes[hero_target].room_index
            return "OPEN_DOOR", {
                "hero_name": hero_name,
                "from_room_index": from_room,
                "target_room_index": room_target,
            }

        elif option == StrategicOption.HEAL_HERO:
            # Heal with a reasonable food amount (10% of current food, min 1)
            food_amount = 1
            if state and state.resources:
                food_amount = max(1, int(state.resources.food * 0.1))
            return "HEAL_HERO", {
                "hero_name": hero_name,
                "food_amount": food_amount,
            }

        elif option == StrategicOption.INITIATE_ESCAPE:
            # Pick up crystal — the RL agent will handle the full escape sequence
            # via subsequent actions (move carrier to exit, plug crystal)
            return "PICK_UP_CRYSTAL", {"hero_name": hero_name}

        elif option == StrategicOption.COLLECT_ITEM:
            # Move hero to the room with the item; mark as busy until pickup completes
            # The hero must stand idle in the room for ~2s for auto-collection
            item_room = self._resolve_item_room(entity_target)
            self._hero_move_targets[hero_name] = item_room
            # Tag this as a collection move so we know to keep hero idle after arrival
            self._hero_collecting[hero_name] = item_room
            return "MOVE_HERO", {
                "hero_name": hero_name,
                "target_room_index": item_room,
            }

        return "WAIT", {}

    # ------------------------------------------------------------------
    # Entity Resolution Helpers
    # ------------------------------------------------------------------

    def _resolve_buildable_module(self, idx: int) -> str:
        """Resolve entity_target index to a buildable blueprint name."""
        if not self._current_state or not self._current_state.buildable_blueprints:
            return ""
        blueprints = self._current_state.buildable_blueprints
        idx = idx % len(blueprints)
        return blueprints[idx].name

    def _resolve_room_module(self, room_idx: int, entity_idx: int) -> str:
        """Resolve a module installed in a specific room."""
        if not self._current_state:
            return ""
        for room in self._current_state.rooms:
            if room.index == room_idx:
                modules = []
                if room.major_module_name:
                    modules.append(room.major_module_name)
                modules.extend(room.minor_module_names)
                if modules:
                    return modules[entity_idx % len(modules)]
        return ""

    def _resolve_research(self, idx: int) -> str:
        """Resolve entity_target to a researchable blueprint name."""
        if not self._current_state or not self._current_state.researchable_blueprints:
            return ""
        blueprints = self._current_state.researchable_blueprints
        idx = idx % len(blueprints)
        return blueprints[idx].name

    def _resolve_recruit(self, idx: int) -> str:
        """Resolve entity_target to a recruitable hero name."""
        if not self._current_state or not self._current_state.recruitable_heroes:
            return ""
        recruits = self._current_state.recruitable_heroes
        idx = idx % len(recruits)
        return recruits[idx].name

    def _resolve_merchant_item(self, idx: int) -> tuple[str, int]:
        """Resolve entity_target to (item_name, merchant_room_index)."""
        if not self._current_state or not self._current_state.merchants:
            return "", 0
        # Flatten all merchant items
        all_items = []
        for merchant in self._current_state.merchants:
            for item in merchant.items:
                all_items.append((item.name, merchant.room_index))
        if not all_items:
            return "", 0
        idx = idx % len(all_items)
        return all_items[idx]

    def _resolve_inventory_item(self, idx: int) -> str:
        """Resolve entity_target to an inventory item name."""
        if not self._current_state:
            return ""
        all_items = list(self._current_state.backpack_items) + list(
            self._current_state.shared_inventory_items
        )
        if not all_items:
            return ""
        idx = idx % len(all_items)
        return all_items[idx].name

    def _resolve_item_room(self, idx: int) -> int:
        """Resolve entity_target to the room_index of a dropped item."""
        if not self._current_state or not self._current_state.dropped_items:
            return 0
        items = self._current_state.dropped_items
        idx = idx % len(items)
        return items[idx].room_index

    # ------------------------------------------------------------------
    # Movement Tracking
    # ------------------------------------------------------------------

    def _update_move_targets(self) -> None:
        """Clear move targets for heroes that have arrived at their destination."""
        if not self._current_state:
            return
        arrived = []
        for hero_name, target_room in self._hero_move_targets.items():
            hero = next(
                (h for h in self._current_state.heroes if h.name == hero_name), None
            )
            if hero and hero.room_index == target_room:
                # If this hero is collecting, don't clear the move target yet —
                # keep them busy until is_gathering_item goes false
                if hero_name in self._hero_collecting:
                    if not hero.is_gathering_item:
                        # Pickup complete (or never started — items may already be gone)
                        arrived.append(hero_name)
                        del self._hero_collecting[hero_name]
                    # else: still gathering, stay busy
                else:
                    arrived.append(hero_name)
        for name in arrived:
            del self._hero_move_targets[name]

    # ------------------------------------------------------------------
    # Parameter Clamping
    # ------------------------------------------------------------------

    def _clamp_parameters(
        self,
        option: StrategicOption,
        room_target: int,
        hero_target: int,
        entity_target: int,
    ) -> tuple[int, int, int]:
        """
        Clamp raw network outputs to valid parameter values for the chosen option.

        The network still learns WHICH option to pick (strategic decision).
        This just ensures the parameters are valid targets so the action
        doesn't fail due to impossible room/hero/entity combinations.

        Returns:
            (clamped_room, clamped_hero, clamped_entity)
        """
        state = self._current_state
        if state is None:
            return room_target, hero_target, entity_target

        # Clamp hero_target to valid hero index
        num_heroes = len(state.heroes)
        if num_heroes > 0:
            hero_target = hero_target % num_heroes
        else:
            hero_target = 0

        # Clamp based on option type
        if option == StrategicOption.OPEN_DOOR:
            # Room target must be an adjacent unexplored room (closed door target)
            # Hero must be usable
            hero_target = self._pick_usable_hero(state, hero_target)
            room_target = self._pick_valid_door_target(state, hero_target)

        elif option == StrategicOption.POSITION_HERO:
            hero_target = self._pick_usable_hero(state, hero_target)
            # Room target: any explored room (rooms in state)
            if state.rooms:
                room_target = state.rooms[room_target % len(state.rooms)].index

        elif option == StrategicOption.COLLECT_ITEM:
            hero_target = self._pick_usable_hero(state, hero_target)
            # Entity target indexes into dropped_items (resolved in _translate)
            if state.dropped_items:
                entity_target = entity_target % len(state.dropped_items)

        elif option == StrategicOption.POWER_ROOM:
            # Room must be unpowered and non-auto
            unpowered = [r.index for r in state.rooms if not r.is_powered and not r.is_auto_powered]
            if unpowered:
                room_target = unpowered[room_target % len(unpowered)]

        elif option == StrategicOption.DEPOWER_ROOM:
            # Room must be powered and non-auto
            powered = [r.index for r in state.rooms if r.is_powered and not r.is_auto_powered]
            if powered:
                room_target = powered[room_target % len(powered)]

        elif option == StrategicOption.BUILD_MODULE:
            # Room must be powered with available slots
            buildable_rooms = []
            for r in state.rooms:
                if not (r.is_powered or r.is_auto_powered):
                    continue
                if r.major_module_name is None or len(r.minor_module_names) < r.minor_slot_count:
                    buildable_rooms.append(r.index)
            if buildable_rooms:
                room_target = buildable_rooms[room_target % len(buildable_rooms)]
            # Entity target indexes into buildable_blueprints (resolved in _translate)
            if state.buildable_blueprints:
                entity_target = entity_target % len(state.buildable_blueprints)

        elif option == StrategicOption.DESTROY_MODULE:
            # Room must have modules
            rooms_with_modules = [
                r.index for r in state.rooms
                if r.major_module_name or r.minor_module_names
            ]
            if rooms_with_modules:
                room_target = rooms_with_modules[room_target % len(rooms_with_modules)]

        elif option == StrategicOption.RESEARCH:
            if state.researchable_blueprints:
                entity_target = entity_target % len(state.researchable_blueprints)

        elif option == StrategicOption.RECRUIT_HERO:
            hero_target = self._pick_usable_hero(state, hero_target)
            if state.recruitable_heroes:
                entity_target = entity_target % len(state.recruitable_heroes)

        elif option == StrategicOption.BUY_ITEM:
            hero_target = self._pick_usable_hero(state, hero_target)
            all_items = [(it, m) for m in state.merchants for it in m.items]
            if all_items:
                entity_target = entity_target % len(all_items)

        elif option == StrategicOption.EQUIP_ITEM:
            all_items = list(state.backpack_items) + list(state.shared_inventory_items)
            if all_items:
                entity_target = entity_target % len(all_items)

        elif option == StrategicOption.HEAL_HERO:
            # Pick a hero that's actually damaged
            damaged = [i for i, h in enumerate(state.heroes) if h.hp < h.max_hp]
            if damaged:
                hero_target = damaged[hero_target % len(damaged)]

        elif option == StrategicOption.LEVEL_UP_HERO:
            # Any hero is valid (game checks food cost internally)
            pass

        elif option == StrategicOption.INITIATE_ESCAPE:
            # Pick a usable hero for crystal pickup
            hero_target = self._pick_usable_hero(state, hero_target)

        return room_target, hero_target, entity_target

    def _pick_usable_hero(self, state: GameStatePayload, preferred: int) -> int:
        """Pick a usable hero index, preferring the given index."""
        if preferred < len(state.heroes) and state.heroes[preferred].is_usable:
            return preferred
        # Fall back to first usable hero
        for i, h in enumerate(state.heroes):
            if h.is_usable:
                return i
        return preferred  # No usable hero — will fail but that's fine

    def _pick_valid_door_target(self, state: GameStatePayload, hero_idx: int) -> int:
        """Pick a valid door target room for OPEN_DOOR based on where the hero is."""
        hero = state.heroes[hero_idx] if hero_idx < len(state.heroes) else None
        if not hero:
            return 0

        hero_room = hero.room_index

        # Option 1: closed_doors list — find one where hero is on one side
        for door in state.closed_doors:
            if door.room1_index == hero_room:
                return door.room2_index
            if door.room2_index == hero_room:
                return door.room1_index

        # Option 2: rooms not fully opened — find adjacent unexplored
        for room in state.rooms:
            if room.index == hero_room and not room.is_fully_opened:
                explored_indices = {r.index for r in state.rooms}
                for adj in room.adjacent_room_indices:
                    if adj not in explored_indices:
                        return adj

        # Option 3: any closed door on the floor (hero may need to move first)
        if state.closed_doors:
            return state.closed_doors[0].room2_index

        # Fallback: target_room_index=-1 tells the mod "open any door from hero's room"
        return -1

    # ------------------------------------------------------------------
    # Observation Building
    # ------------------------------------------------------------------

    def _build_observation(self, state: GameStatePayload) -> dict:
        """Build the full observation dict from game state."""
        graph = self._graph_builder.build(state)

        # Adjacency + door state matrices
        adjacency = np.zeros((MAX_ROOMS, MAX_ROOMS), dtype=np.int8)
        door_state = np.zeros((MAX_ROOMS, MAX_ROOMS), dtype=np.int8)
        for u, v, data in graph.edges(data=True):
            if u < MAX_ROOMS and v < MAX_ROOMS:
                adjacency[u, v] = 1
                adjacency[v, u] = 1
                if data.get("is_open", False):
                    door_state[u, v] = 1
                    door_state[v, u] = 1

        # Power state
        power_state = np.zeros(MAX_ROOMS, dtype=np.int8)
        for room in state.rooms:
            if room.index < MAX_ROOMS and (room.is_powered or room.is_auto_powered):
                power_state[room.index] = 1

        # Power reachable (BFS from crystal through powered open-door chain)
        power_reachable = np.zeros(MAX_ROOMS, dtype=np.int8)
        crystal_room = state.start_room_index
        if crystal_room < MAX_ROOMS and crystal_room in graph:
            visited = set()
            queue = [crystal_room]
            while queue:
                r = queue.pop(0)
                if r in visited:
                    continue
                visited.add(r)
                if r < MAX_ROOMS:
                    power_reachable[r] = 1
                for neighbor in graph.neighbors(r):
                    if neighbor in visited:
                        continue
                    edge = graph.edges[r, neighbor]
                    if not edge.get("is_open", False):
                        continue
                    ndata = graph.nodes.get(neighbor, {})
                    if ndata.get("is_powered", False) or ndata.get("is_auto_powered", False):
                        queue.append(neighbor)

        # Room features
        room_features = np.full((MAX_ROOMS, ROOM_FEATURE_DIM), -1.0, dtype=np.float32)
        for room in state.rooms:
            if room.index >= MAX_ROOMS:
                continue
            # Compute distances
            dist_to_crystal = self._graph_distance(graph, room.index, state.start_room_index)
            dist_to_exit = self._graph_distance(graph, room.index, state.exit_room_index)
            minor_slots_free = room.minor_slot_count - len(room.minor_module_names)
            has_major = 1.0 if room.major_module_name else 0.0
            is_on_escape = 0.0
            if state.exit_room_index >= 0:
                try:
                    epath = escape_path_rooms(graph, state.start_room_index, state.exit_room_index)
                    is_on_escape = 1.0 if room.index in epath else 0.0
                except Exception:
                    pass

            room_features[room.index] = [
                float(room.is_powered or room.is_auto_powered),  # 0
                float(room.is_auto_powered),                     # 1
                float(room.is_start_room),                       # 2
                float(room.is_exit_room),                        # 3
                float(room.depth),                               # 4
                float(room.suffers_emp),                         # 5
                float(room.emp_turns_remaining),                 # 6
                float(room.has_artifact),                        # 7
                float(room.has_stele),                           # 8
                float(room.minor_slot_count),                    # 9
                float(minor_slots_free),                         # 10
                has_major,                                       # 11
                float(len(room.minor_module_names)),             # 12
                float(room.hero_count),                          # 13
                float(room.mob_count),                           # 14
                float(room.npc_count),                           # 15
                float(room.dust_loot_amount),                    # 16
                is_on_escape,                                    # 17
                float(dist_to_crystal),                          # 18
                float(dist_to_exit),                             # 19
            ]

        # Hero features
        hero_features = np.full((MAX_HEROES, HERO_FEATURE_DIM), -1.0, dtype=np.float32)
        faction_map = {"Other": 0, "Guard": 1, "Prisoner": 2, "Native": 3}
        weapon_class_map = {"Melee": 1, "Ranged": 2, "Support": 3}
        for i, hero in enumerate(state.heroes[:MAX_HEROES]):
            hp_ratio = hero.hp / hero.max_hp if hero.max_hp > 0 else 0.0
            is_busy = 1.0 if hero.name in self._hero_move_targets else 0.0
            has_operate = 1.0 if any(p.name == "Operate" for p in hero.passive_skills) else 0.0
            has_repair = 1.0 if any(p.name == "Repair" for p in hero.passive_skills) else 0.0
            dist_to_exit_h = self._graph_distance(graph, hero.room_index, state.exit_room_index)
            dist_to_crystal_h = self._graph_distance(graph, hero.room_index, state.start_room_index)

            # Skill tree derived features
            weapon_class_id = float(weapon_class_map.get(hero.weapon_class or "", 0))
            total_skills = float(len(hero.skill_tree)) if hero.skill_tree else 0.0
            unlocked_skills = float(sum(1 for e in hero.skill_tree if e.is_unlocked)) if hero.skill_tree else 0.0
            # Next unlock: smallest unlock_hero_level > current level (0 if none remain)
            next_unlock = 0.0
            if hero.skill_tree:
                future = [e.unlock_hero_level for e in hero.skill_tree if not e.is_unlocked]
                if future:
                    next_unlock = float(min(future))

            hero_features[i] = [
                float(hero.room_index),          # 0
                hp_ratio,                        # 1
                float(hero.level),               # 2
                float(hero.has_crystal),         # 3
                float(hero.is_operating),        # 4
                is_busy,                         # 5
                float(hero.is_usable),           # 6
                float(len(hero.passive_skills)), # 7
                has_operate,                     # 8
                has_repair,                      # 9
                float(len(hero.active_skills)),  # 10
                float(len(hero.equipment)),      # 11
                float(faction_map.get(hero.faction, 0)),  # 12
                weapon_class_id,                 # 13
                0.0,  # level_up_cost (approximate)               # 14
                float(dist_to_exit_h),           # 15
                float(dist_to_crystal_h),        # 16
                float(hero.is_gathering_item),   # 17
                total_skills,                    # 18: total skills in tree
                unlocked_skills,                 # 19: skills unlocked so far
                next_unlock,                     # 20: next hero level that grants a new skill
                total_skills - unlocked_skills,  # 21: skills remaining to unlock
            ]

        # Mob features
        mob_features = np.full((MAX_MOBS, MOB_FEATURE_DIM), -1.0, dtype=np.float32)
        target_type_map = {
            "AntiHeroMob": 0, "AntiModuleMob": 1, "Crystal": 2, "Artifact": 3,
        }
        for i, mob in enumerate(state.mobs[:MAX_MOBS]):
            hp_ratio = mob.hp / mob.max_hp if mob.max_hp > 0 else 0.0
            dist_crystal = self._graph_distance(graph, mob.room_index, state.start_room_index)
            room_powered = 0.0
            for r in state.rooms:
                if r.index == mob.room_index:
                    room_powered = float(r.is_powered or r.is_auto_powered)
                    break
            mob_features[i] = [
                float(mob.room_index),                              # 0
                hp_ratio,                                           # 1
                float(target_type_map.get(mob.target_type, 0)),     # 2
                float(dist_crystal),                                # 3
                room_powered,                                       # 4
            ]

        # Resources
        res = state.resources
        if res:
            dust_used = res.powered_room_count * res.room_power_cost
            dust_available = res.dust - dust_used
            resources = np.array([
                res.industry, res.food, res.science, res.dust, res.dust_max,
                res.industry_per_turn, res.food_per_turn, res.science_per_turn,
                dust_used, dust_available,
            ], dtype=np.float32)
        else:
            resources = np.zeros(RESOURCE_DIM, dtype=np.float32)

        # Game meta
        phase_map = {
            GamePhase.STRATEGY: 0, GamePhase.TACTICAL_PAUSE: 0,
            GamePhase.ACTION: 1, GamePhase.WAVE_ACTIVE: 1,
            GamePhase.GAME_OVER: 2, GamePhase.ESCAPING: 3,
        }
        is_last_floor = 1.0 if state.floor >= 12 else 0.0
        total_doors = sum(
            len(r.adjacent_room_indices) for r in state.rooms
        ) // 2  # Each edge counted twice

        game_meta = np.array([
            float(state.turn),
            float(state.floor),
            float(phase_map.get(state.game_phase, 0)),
            float(len(state.rooms)),
            float(len(state.heroes)),
            float(len(state.mobs)),
            float(len(state.closed_doors)),
            float(state.is_crystal_safe),
            float(state.exit_room_index),
            float(state.time_scale),
            is_last_floor,
            float(total_doors),
        ], dtype=np.float32)

        # Action mask
        mask = self._mask_computer.compute_mask(state)
        action_mask = mask.astype(np.int8)

        return {
            "adjacency": adjacency,
            "door_state": door_state,
            "power_state": power_state,
            "power_reachable": power_reachable,
            "room_features": room_features,
            "hero_features": hero_features,
            "mob_features": mob_features,
            "resources": resources,
            "game_meta": game_meta,
            "action_mask": action_mask,
        }

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    def _build_info(self, state: GameStatePayload) -> dict:
        """Build info dict."""
        mask = self._mask_computer.compute_mask(state)
        return {
            "turn": state.turn,
            "floor": state.floor,
            "game_phase": state.game_phase.value,
            "crystal_state": state.crystal_state,
            "num_rooms": len(state.rooms),
            "num_heroes": len(state.heroes),
            "num_mobs": len(state.mobs),
            "step_count": self._step_count,
            "action_mask": mask,
            "hero_move_targets": dict(self._hero_move_targets),
        }

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _graph_distance(self, graph, src: int, dst: int) -> int:
        """Shortest path distance between two rooms via open doors. -1 if unreachable."""
        if src == dst:
            return 0
        if src not in graph or dst not in graph:
            return -1
        try:
            import networkx as nx
            # Only traverse open doors
            open_subgraph = nx.Graph()
            for u, v, data in graph.edges(data=True):
                if data.get("is_open", False):
                    open_subgraph.add_edge(u, v)
            if src not in open_subgraph or dst not in open_subgraph:
                return -1
            path = nx.shortest_path(open_subgraph, src, dst)
            return len(path) - 1
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return -1

    def render(self) -> Optional[str]:
        """Render current state."""
        if self.render_mode == "human" and self._current_state:
            s = self._current_state
            res = s.resources
            res_str = (
                f"I={res.industry:.0f} F={res.food:.0f} S={res.science:.0f} D={res.dust:.0f}/{res.dust_max:.0f}"
                if res else "N/A"
            )
            mask = self._mask_computer.compute_mask(s)
            valid_options = [StrategicOption(i).name for i in range(NUM_OPTIONS) if mask[i]]
            return (
                f"Turn {s.turn} Floor {s.floor} | {s.game_phase.value} | Crystal: {s.crystal_state}\n"
                f"Resources: {res_str}\n"
                f"Heroes: {len(s.heroes)} | Mobs: {len(s.mobs)} | Rooms: {len(s.rooms)}\n"
                f"Valid options: {', '.join(valid_options)}\n"
                f"Step: {self._step_count} | Episode reward: {self._episode_reward:.1f}"
            )
        return None

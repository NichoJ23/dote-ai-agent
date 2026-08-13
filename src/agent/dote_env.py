"""
DotEEnv: Gymnasium-compatible environment wrapping Dungeon of the ENDLESS.

Communicates with the BepInEx mod via TCP IPC (using IpcClient).
Converts raw JSON state into structured observations using StateParser and GraphBuilder.
Exposes standard reset()/step() API for RL algorithms or custom controllers.
"""

from __future__ import annotations

from typing import Any, Optional

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from graph_builder import GraphBuilder
from graph_utils import escape_path_rooms
from guidelines_config import GuidelinesConfig
from ipc_client import IpcClient
from state_parser import GamePhase, GameStatePayload, StateParser


# Maximum dimensions for fixed-size arrays in observation space.
# These are generous upper bounds for Dungeon of the ENDLESS floor layouts.
MAX_ROOMS = 30
MAX_HEROES = 6
MAX_MOBS = 50

# Action command types (maps discrete index -> command string)
ACTION_COMMANDS = [
    "MOVE_HERO",
    "OPEN_DOOR",
    "BUILD_MODULE",
    "REPAIR_MODULE",
    "POWER_ROOM",
    "UNPOWER_ROOM",
    "HEAL_HERO",
    "LEVEL_UP_HERO",
    "RECRUIT_HERO",
    "BUY_FROM_MERCHANT",
    "EQUIP_ITEM",
    "UNEQUIP_ITEM",
    "COLLECT_ITEM",
    "PICK_UP_CRYSTAL",
    "RESEARCH",
    "PAUSE_GAME",
    "UNPAUSE_GAME",
]


class DotEEnv(gym.Env):
    """
    Gymnasium environment for Dungeon of the ENDLESS.

    Observation space: Dict with fixed-size arrays representing:
      - room node features (adjacency, power, modules, units, EMP)
      - door/edge state matrix
      - hero feature vectors
      - global resource vector
      - game metadata

    Action space: Dict with:
      - command_type: Discrete index into ACTION_COMMANDS
      - target_room: Target room index
      - hero_index: Which hero to command
      - entity_id_hash: Hashed identifier for items/merchants/recruits
    """

    metadata = {"render_modes": ["human", "json"]}

    def __init__(
        self,
        host: str = "127.0.0.1",
        state_port: int = 5555,
        action_port: int = 5556,
        config_path: Optional[str] = None,
        guidelines: Optional[GuidelinesConfig] = None,
        render_mode: Optional[str] = None,
        connect_timeout: float = 300.0,
        recv_timeout: float = 30.0,
    ):
        """
        Initialize the DotE environment.

        Args:
            host: IPC host address.
            state_port: Port for receiving game state.
            action_port: Port for sending actions.
            config_path: Path to guidelines YAML/JSON config. Ignored if guidelines provided.
            guidelines: Pre-built GuidelinesConfig. Takes priority over config_path.
            render_mode: "human" or "json" or None.
            connect_timeout: Max seconds to wait for IPC connection.
            recv_timeout: Max seconds to wait for state/response messages.
        """
        super().__init__()

        self.render_mode = render_mode

        # Load guidelines
        if guidelines is not None:
            self.guidelines = guidelines
        elif config_path is not None:
            self.guidelines = GuidelinesConfig.from_file(config_path)
        else:
            self.guidelines = GuidelinesConfig()

        # IPC client (not connected until reset)
        self._ipc = IpcClient(
            host=host,
            state_port=state_port,
            action_port=action_port,
            connect_timeout=connect_timeout,
            recv_timeout=recv_timeout,
        )

        # Parsing and graph building
        self._parser = StateParser()
        self._graph_builder = GraphBuilder()

        # Internal state tracking
        self._current_state: Optional[GameStatePayload] = None
        self._prev_state: Optional[GameStatePayload] = None
        self._connected = False
        self._step_count = 0

        # --- Define observation space ---
        self.observation_space = spaces.Dict(
            {
                # Adjacency matrix: MAX_ROOMS x MAX_ROOMS binary
                "adjacency": spaces.Box(
                    low=0, high=1, shape=(MAX_ROOMS, MAX_ROOMS), dtype=np.int8
                ),
                # Door state matrix: MAX_ROOMS x MAX_ROOMS (1=open, 0=closed/no-edge)
                "door_state": spaces.Box(
                    low=0, high=1, shape=(MAX_ROOMS, MAX_ROOMS), dtype=np.int8
                ),
                # Node features: [is_powered, is_auto_powered, is_start_room, is_exit_room,
                #                  depth, suffers_emp, has_artifact, minor_slot_count,
                #                  hero_count, mob_count, has_major_module, num_minor_modules]
                "node_features": spaces.Box(
                    low=-1,
                    high=100,
                    shape=(MAX_ROOMS, 12),
                    dtype=np.float32,
                ),
                # Hero features: [room_index, hp_ratio, level, has_crystal,
                #                  is_operating, num_passive_skills, num_active_skills,
                #                  num_equipment, faction_id]
                "hero_features": spaces.Box(
                    low=-1,
                    high=1000,
                    shape=(MAX_HEROES, 9),
                    dtype=np.float32,
                ),
                # Resource vector: [industry, food, science, dust, dust_max,
                #                    ind_per_turn, food_per_turn, sci_per_turn]
                "resources": spaces.Box(
                    low=-100, high=10000, shape=(8,), dtype=np.float32
                ),
                # Game state: [turn, floor, phase_id, num_rooms, num_heroes, num_mobs,
                #              num_closed_doors, crystal_safe, exit_room_index]
                "game_meta": spaces.Box(
                    low=-1, high=10000, shape=(9,), dtype=np.float32
                ),
            }
        )

        # --- Define action space ---
        self.action_space = spaces.Dict(
            {
                # Which command to execute
                "command_type": spaces.Discrete(len(ACTION_COMMANDS)),
                # Target room index (0 to MAX_ROOMS-1)
                "target_room": spaces.Discrete(MAX_ROOMS),
                # Which hero to command (index into heroes list)
                "hero_index": spaces.Discrete(MAX_HEROES),
                # Hashed entity identifier (for items, merchants, recruits, modules)
                "entity_id_hash": spaces.Discrete(1000),
            }
        )

    def reset(
        self, *, seed: Optional[int] = None, options: Optional[dict] = None
    ) -> tuple[dict, dict]:
        """
        Reset the environment: connect to game, unpause, receive initial state.

        Returns:
            (observation, info) tuple.
        """
        super().reset(seed=seed)

        # Connect if not already connected
        if not self._connected:
            self._ipc.connect()
            self._connected = True

        # Send unpause to start the game
        self._ipc.send_action("UNPAUSE_GAME", {})

        # Wait for first state
        raw_state = self._ipc.receive_state(timeout=60.0)
        self._current_state = self._parser.parse(raw_state)
        self._prev_state = None
        self._step_count = 0

        obs = self._build_observation(self._current_state)
        info = self._build_info(self._current_state)

        return obs, info

    def step(self, action: dict) -> tuple[dict, float, bool, bool, dict]:
        """
        Execute an action and return the resulting observation.

        Args:
            action: Dict matching the action_space.

        Returns:
            (observation, reward, terminated, truncated, info) tuple.
        """
        # Translate action dict to ActionCommand
        command_str = ACTION_COMMANDS[int(action["command_type"])]
        parameters = self._build_action_parameters(action, command_str)

        # Send action to game
        result = self._ipc.send_action(command_str, parameters)

        # Receive next state
        raw_state = self._ipc.receive_state()
        self._prev_state = self._current_state
        self._current_state = self._parser.parse(raw_state)
        self._step_count += 1

        # Build observation
        obs = self._build_observation(self._current_state)

        # Compute reward
        reward = self._compute_reward(self._prev_state, self._current_state)

        # Check termination (crystal unplugged = game over)
        terminated = self._current_state.is_game_over

        truncated = False

        # Build info
        info = self._build_info(self._current_state)
        info["action_result"] = result
        info["action_sent"] = {"command": command_str, "parameters": parameters}

        return obs, reward, terminated, truncated, info

    def close(self) -> None:
        """Cleanly disconnect IPC sockets."""
        if self._connected:
            try:
                self._ipc.disconnect()
            except Exception:
                pass
            self._connected = False

    def _compute_reward(
        self, prev: Optional[GameStatePayload], curr: GameStatePayload
    ) -> float:
        """
        Compute reward based on state transition.

        Reward = +10 * (delta rooms explored)
               +  5 * (delta dust gained)
               -  0.05 * (percentage HP lost per hero, summed)
               -100 * (crystal destroyed)
               +  2 * (delta modules built)
               +  1 * (delta mobs killed)
               + 50 * (floor escaped successfully)
               - 20 * (hero died)
        """
        if prev is None:
            return 0.0

        reward = 0.0

        # Delta rooms explored (more rooms in the list = more explored)
        reward += 10.0 * max(0, len(curr.rooms) - len(prev.rooms))

        # Delta dust
        prev_dust = prev.resources.dust if prev.resources else 0.0
        curr_dust = curr.resources.dust if curr.resources else 0.0
        dust_delta = curr_dust - prev_dust
        if dust_delta > 0:
            reward += 5.0 * dust_delta

        # Delta hero HP lost as percentage of max HP (-0.5 per 1% lost)
        prev_hp_map = {h.name: (h.hp, h.max_hp) for h in prev.heroes}
        curr_hp_map = {h.name: (h.hp, h.max_hp) for h in curr.heroes}
        total_pct_lost = 0.0
        for hero_name, (prev_hp, prev_max) in prev_hp_map.items():
            if prev_max <= 0:
                continue
            curr_hp, curr_max = curr_hp_map.get(hero_name, (0.0, prev_max))
            # Use current max_hp as the reference (accounts for level-ups)
            ref_max = curr_max if curr_max > 0 else prev_max
            hp_diff = prev_hp - curr_hp
            if hp_diff > 0:
                pct_lost = (hp_diff / ref_max) * 100.0  # as percentage points
                total_pct_lost += pct_lost
        reward -= 0.05 * total_pct_lost

        # Crystal destroyed
        if curr.is_game_over and not prev.is_game_over:
            reward -= 100.0

        # Delta modules built
        prev_modules = sum(
            (1 if r.major_module_name else 0) + len(r.minor_module_names)
            for r in prev.rooms
        )
        curr_modules = sum(
            (1 if r.major_module_name else 0) + len(r.minor_module_names)
            for r in curr.rooms
        )
        modules_delta = curr_modules - prev_modules
        if modules_delta > 0:
            reward += 2.0 * modules_delta

        # Delta mobs killed (fewer mobs = mobs killed)
        mobs_delta = len(prev.mobs) - len(curr.mobs)
        if mobs_delta > 0:
            reward += 1.0 * mobs_delta

        # Floor escaped successfully (crystal on exit slot)
        if curr.is_escaping and not prev.is_escaping:
            reward += 50.0

        # Hero died (was in prev but not in curr)
        prev_hero_names = {h.name for h in prev.heroes}
        curr_hero_names = {h.name for h in curr.heroes}
        heroes_lost = prev_hero_names - curr_hero_names
        reward -= 20.0 * len(heroes_lost)

        return reward

    def _build_observation(self, state: GameStatePayload) -> dict:
        """Convert game state to observation dict matching observation_space."""
        # Build graph
        graph = self._graph_builder.build(state)

        # Adjacency matrix
        adjacency = np.zeros((MAX_ROOMS, MAX_ROOMS), dtype=np.int8)
        for u, v in graph.edges:
            if u < MAX_ROOMS and v < MAX_ROOMS:
                adjacency[u, v] = 1
                adjacency[v, u] = 1

        # Door state matrix (1 = open)
        door_state = np.zeros((MAX_ROOMS, MAX_ROOMS), dtype=np.int8)
        for u, v, data in graph.edges(data=True):
            if u < MAX_ROOMS and v < MAX_ROOMS and data.get("is_open", False):
                door_state[u, v] = 1
                door_state[v, u] = 1

        # Node features
        node_features = np.full((MAX_ROOMS, 12), -1.0, dtype=np.float32)
        for node, data in graph.nodes(data=True):
            if node < MAX_ROOMS:
                node_features[node] = [
                    float(data.get("is_powered", False)),
                    float(data.get("is_auto_powered", False)),
                    float(data.get("is_start_room", False)),
                    float(data.get("is_exit_room", False)),
                    float(data.get("depth", 0)),
                    float(data.get("suffers_emp", False)),
                    float(data.get("has_artifact", False)),
                    float(data.get("minor_slot_count", 0)),
                    float(data.get("hero_count", 0)),
                    float(data.get("mob_count", 0)),
                    float(1 if data.get("major_module_name") else 0),
                    float(len(data.get("minor_module_names", []))),
                ]

        # Hero features
        # Faction mapping for numeric encoding
        faction_map = {"Other": 0, "Guard": 1, "Prisoner": 2, "Native": 3}
        hero_features = np.full((MAX_HEROES, 9), -1.0, dtype=np.float32)
        for i, hero in enumerate(state.heroes[:MAX_HEROES]):
            hp_ratio = hero.hp / hero.max_hp if hero.max_hp > 0 else 0.0
            hero_features[i] = [
                float(hero.room_index),
                hp_ratio,
                float(hero.level),
                float(hero.has_crystal),
                float(hero.is_operating),
                float(len(hero.passive_skills)),
                float(len(hero.active_skills)),
                float(len(hero.equipment)),
                float(faction_map.get(hero.faction, 0)),
            ]

        # Resources vector
        res = state.resources
        if res:
            resources = np.array(
                [
                    res.industry,
                    res.food,
                    res.science,
                    res.dust,
                    res.dust_max,
                    res.industry_per_turn,
                    res.food_per_turn,
                    res.science_per_turn,
                ],
                dtype=np.float32,
            )
        else:
            resources = np.zeros(8, dtype=np.float32)

        # Game meta
        phase_map = {
            GamePhase.STRATEGY: 0,
            GamePhase.TACTICAL_PAUSE: 0,
            GamePhase.ACTION: 1,
            GamePhase.WAVE_ACTIVE: 1,
            GamePhase.GAME_OVER: 2,
            GamePhase.ESCAPING: 3,
        }
        game_meta = np.array(
            [
                float(state.turn),
                float(state.floor),
                float(phase_map.get(state.game_phase, 0)),
                float(len(state.rooms)),
                float(len(state.heroes)),
                float(len(state.mobs)),
                float(len(state.closed_doors)),
                float(state.is_crystal_safe),
                float(state.exit_room_index),
            ],
            dtype=np.float32,
        )

        return {
            "adjacency": adjacency,
            "door_state": door_state,
            "node_features": node_features,
            "hero_features": hero_features,
            "resources": resources,
            "game_meta": game_meta,
        }

    def _build_action_parameters(self, action: dict, command: str) -> dict:
        """
        Translate the action space dict into command-specific parameters.

        The agent provides generic indices; we map them to game-specific identifiers
        based on current state.
        """
        hero_idx = int(action["hero_index"])
        target_room = int(action["target_room"])
        entity_hash = int(action["entity_id_hash"])

        # Get hero name from index (heroes identified by name in this game)
        hero_name = ""
        if self._current_state and hero_idx < len(self._current_state.heroes):
            hero_name = self._current_state.heroes[hero_idx].name

        params: dict[str, Any] = {}

        if command == "MOVE_HERO":
            params = {"hero_name": hero_name, "target_room_index": target_room}

        elif command == "OPEN_DOOR":
            from_room = 0
            if self._current_state and hero_idx < len(self._current_state.heroes):
                from_room = self._current_state.heroes[hero_idx].room_index
            params = {
                "hero_name": hero_name,
                "from_room_index": from_room,
                "target_room_index": target_room,
            }

        elif command == "BUILD_MODULE":
            params = {
                "room_index": target_room,
                "module_name": f"module_{entity_hash}",
                "slot_type": "major",
            }

        elif command == "REPAIR_MODULE":
            params = {
                "hero_name": hero_name,
                "room_index": target_room,
                "module_name": f"module_{entity_hash}",
            }

        elif command in ("POWER_ROOM", "UNPOWER_ROOM"):
            params = {"room_index": target_room}

        elif command == "HEAL_HERO":
            params = {"hero_name": hero_name, "food_amount": max(1, entity_hash % 20)}

        elif command == "LEVEL_UP_HERO":
            params = {"hero_name": hero_name}

        elif command == "RECRUIT_HERO":
            recruit_name = ""
            if self._current_state and entity_hash < len(self._current_state.recruitable_heroes):
                recruit_name = self._current_state.recruitable_heroes[entity_hash].name
            params = {"recruiter_hero_name": hero_name, "recruit_name": recruit_name}

        elif command == "BUY_FROM_MERCHANT":
            item_name = ""
            if self._current_state and self._current_state.merchants:
                merchant = self._current_state.merchants[entity_hash % len(self._current_state.merchants)]
                if merchant.items:
                    item_name = merchant.items[entity_hash % len(merchant.items)].name
            params = {"hero_name": hero_name, "item_name": item_name}

        elif command == "EQUIP_ITEM":
            params = {
                "hero_name": hero_name,
                "item_name": f"item_{entity_hash}",
            }

        elif command == "UNEQUIP_ITEM":
            slot_categories = ["Weapon", "Armor", "Accessory"]
            params = {
                "hero_name": hero_name,
                "slot_category": slot_categories[entity_hash % 3],
            }

        elif command == "COLLECT_ITEM":
            item_name = ""
            if self._current_state and entity_hash < len(self._current_state.dropped_items):
                item_name = self._current_state.dropped_items[entity_hash].name or ""
            params = {"hero_name": hero_name, "item_name": item_name}

        elif command == "PICK_UP_CRYSTAL":
            params = {"hero_name": hero_name}

        elif command == "RESEARCH":
            blueprint = ""
            if self._current_state and entity_hash < len(self._current_state.researchable_blueprints):
                blueprint = self._current_state.researchable_blueprints[entity_hash].name
            params = {"blueprint_name": blueprint}

        elif command in ("PAUSE_GAME", "UNPAUSE_GAME"):
            params = {}

        return params

    def _build_info(self, state: GameStatePayload) -> dict:
        """Build the info dict returned alongside observations."""
        return {
            "turn": state.turn,
            "floor": state.floor,
            "game_phase": state.game_phase.value,
            "crystal_state": state.crystal_state,
            "num_rooms": len(state.rooms),
            "num_heroes": len(state.heroes),
            "num_mobs": len(state.mobs),
            "num_closed_doors": len(state.closed_doors),
            "step_count": self._step_count,
            "guidelines": self.guidelines.to_dict(),
        }

    def render(self) -> Optional[str]:
        """Render current state."""
        if self.render_mode == "json" and self._current_state:
            return self._current_state.model_dump_json(indent=2)
        elif self.render_mode == "human" and self._current_state:
            s = self._current_state
            res = s.resources
            res_str = f"I={res.industry:.0f} F={res.food:.0f} S={res.science:.0f} D={res.dust:.0f}/{res.dust_max:.0f}" if res else "N/A"
            lines = [
                f"Turn {s.turn} Floor {s.floor} | Phase: {s.game_phase.value} | Crystal: {s.crystal_state}",
                f"Resources: {res_str}",
                f"Heroes: {len(s.heroes)} | Mobs: {len(s.mobs)} | Rooms: {len(s.rooms)} | Closed Doors: {len(s.closed_doors)}",
            ]
            return "\n".join(lines)
        return None

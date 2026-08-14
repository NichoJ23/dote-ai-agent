"""
RLAgent: Reinforcement learning agent for Dungeon of the ENDLESS.

Orchestrates the strategic brain (PolicyNetwork), micro-controller (combat),
and escape controller based on the current game phase.

Extends BaseAgent so it can be used with the existing run_agent.py infrastructure.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import torch

from action_masking import ActionMaskComputer, NUM_OPTIONS, StrategicOption
from base_agent import BaseAgent
from escape_controller import EscapeControllerNetwork, EscapeAction
from micro_controller import MicroControllerNetwork, CombatAction
from networks import PolicyNetwork
from rl_config import RLConfig
from rl_env import (
    MAX_HEROES,
    MAX_MOBS,
    MAX_MODULES,
    MAX_ROOMS,
    HERO_FEATURE_DIM,
    MOB_FEATURE_DIM,
    ROOM_FEATURE_DIM,
    RESOURCE_DIM,
    GAME_META_DIM,
)
from state_parser import GamePhase, GameStatePayload

logger = logging.getLogger(__name__)


class RLAgent(BaseAgent):
    """
    RL-based agent for autonomous play.

    Uses three networks:
      - PolicyNetwork: strategic decisions during Strategy phase
      - MicroControllerNetwork: combat decisions during Action phase
      - EscapeControllerNetwork: escape-phase decisions

    The agent translates observations to actions compatible with the IPC protocol.
    """

    def __init__(
        self,
        config: Optional[RLConfig] = None,
        checkpoint_path: Optional[str | Path] = None,
        device: str = "cpu",
        deterministic: bool = False,
    ):
        super().__init__(guidelines=None)
        self.config = config or RLConfig()
        self.device = torch.device(device)
        self.deterministic = deterministic

        # Networks
        self.policy_net = PolicyNetwork(self.config.network).to(self.device)
        self.micro_net = MicroControllerNetwork(self.config.network).to(self.device)
        self.escape_net = EscapeControllerNetwork(self.config.network).to(self.device)

        # Action masking — disable DESTROY_MODULE in early curriculum stages
        disable_destroy = self.config.curriculum.stages[self.config.curriculum.current_stage_index].guideline_shaping_enabled
        self._mask_computer = ActionMaskComputer(disable_destroy_module=disable_destroy)

        # Internal state
        self._escape_initiated = False
        self._crystal_carrier: Optional[str] = None

        # Load checkpoint if provided
        if checkpoint_path:
            self.load_checkpoint(checkpoint_path)

    def select_action(self, state: GameStatePayload) -> Optional[dict]:
        """
        Select an action based on current game state.

        Delegates to the appropriate controller based on game phase:
          - Strategy phase → strategic brain (PolicyNetwork)
          - Action phase → micro-controller
          - Escape initiated → escape controller
        """
        if state.is_game_over:
            return None

        # Escape phase
        if self._escape_initiated or state.is_escaping:
            return self._escape_action(state)

        # Combat phase
        if state.game_phase.is_combat:
            return self._combat_action(state)

        # Strategy phase
        return self._strategic_action(state)

    def reset(self) -> None:
        """Reset internal state for a new episode/floor."""
        self._escape_initiated = False
        self._crystal_carrier = None

    def on_action_result(self, command: dict, result: dict) -> None:
        """Track escape initiation."""
        if command.get("command") == "PICK_UP_CRYSTAL" and result.get("success"):
            self._escape_initiated = True
            self._crystal_carrier = command.get("parameters", {}).get("hero_name")

    # ------------------------------------------------------------------
    # Strategic Brain (Strategy Phase)
    # ------------------------------------------------------------------

    def _strategic_action(self, state: GameStatePayload) -> Optional[dict]:
        """Use PolicyNetwork to select a strategic option and parameterize it."""
        obs = self._state_to_obs_tensor(state)
        mask = self._mask_computer.compute_mask(state)
        mask_tensor = torch.tensor(mask, dtype=torch.int8, device=self.device).unsqueeze(0)

        # Log valid options
        valid_options = [StrategicOption(i).name for i in range(NUM_OPTIONS) if mask[i]]
        logger.debug(f"Valid options: {valid_options}")

        with torch.no_grad():
            action_dict, _, _ = self.policy_net.act(obs, mask_tensor, deterministic=self.deterministic)

        option = StrategicOption(action_dict["option"].item())
        room_target = action_dict["room_target"].item()
        hero_target = action_dict["hero_target"].item()
        entity_target = action_dict["entity_target"].item()

        logger.info(f"Chose: {option.name} | room={room_target} hero={hero_target} entity={entity_target} | from {len(valid_options)} options: [{', '.join(valid_options)}]")

        # Translate to game command (reuse rl_env logic inline)
        return self._translate_strategic_action(state, option, room_target, hero_target, entity_target)

    # ------------------------------------------------------------------
    # Micro-Controller (Action Phase)
    # ------------------------------------------------------------------

    def _combat_action(self, state: GameStatePayload) -> Optional[dict]:
        """Use MicroControllerNetwork for combat decisions."""
        obs = self._state_to_obs_tensor(state)

        with torch.no_grad():
            action_dict, _, _ = self.micro_net.act(obs, deterministic=self.deterministic)

        combat_action = CombatAction(action_dict["combat_action"].item())
        room_target = action_dict["room_target"].item()
        hero_target = action_dict["hero_target"].item()

        if combat_action == CombatAction.WAIT:
            return None  # Let auto-combat handle it

        hero_name = self._get_hero_name(state, hero_target)
        if not hero_name:
            return None

        if combat_action == CombatAction.REPOSITION_HERO:
            return {"command": "MOVE_HERO", "parameters": {
                "hero_name": hero_name, "target_room_index": room_target
            }}
        elif combat_action == CombatAction.HEAL_HERO:
            food_amount = max(1, int((state.resources.food if state.resources else 0) * 0.1))
            return {"command": "HEAL_HERO", "parameters": {
                "hero_name": hero_name, "food_amount": food_amount
            }}

        return None

    # ------------------------------------------------------------------
    # Escape Controller
    # ------------------------------------------------------------------

    def _escape_action(self, state: GameStatePayload) -> Optional[dict]:
        """Use EscapeControllerNetwork for escape decisions."""
        obs = self._state_to_obs_tensor(state)

        with torch.no_grad():
            action_dict, _, _ = self.escape_net.act(obs, deterministic=self.deterministic)

        escape_action = EscapeAction(action_dict["escape_action"].item())
        room_target = action_dict["room_target"].item()
        hero_target = action_dict["hero_target"].item()

        hero_name = self._get_hero_name(state, hero_target)

        if escape_action == EscapeAction.WAIT:
            return None

        if escape_action == EscapeAction.PICK_UP_CRYSTAL:
            if hero_name:
                return {"command": "PICK_UP_CRYSTAL", "parameters": {"hero_name": hero_name}}

        elif escape_action == EscapeAction.POWER_ROOM:
            return {"command": "POWER_ROOM", "parameters": {"room_index": room_target}}

        elif escape_action == EscapeAction.DEPOWER_ROOM:
            return {"command": "UNPOWER_ROOM", "parameters": {"room_index": room_target}}

        elif escape_action in (EscapeAction.MOVE_HERO_TO_EXIT, EscapeAction.MOVE_HERO_TO_BLOCK):
            if hero_name:
                return {"command": "MOVE_HERO", "parameters": {
                    "hero_name": hero_name, "target_room_index": room_target
                }}

        elif escape_action == EscapeAction.PLUG_CRYSTAL:
            # Use the crystal carrier
            carrier = self._crystal_carrier or (hero_name if hero_name else "")
            if carrier:
                return {"command": "PLUG_CRYSTAL_EXIT", "parameters": {"hero_name": carrier}}

        return None

    # ------------------------------------------------------------------
    # Observation Conversion
    # ------------------------------------------------------------------

    def _state_to_obs_tensor(self, state: GameStatePayload) -> dict[str, torch.Tensor]:
        """
        Convert a GameStatePayload into the tensor observation format
        expected by the networks.

        This is a lightweight version of RLEnv._build_observation that
        works without the full env infrastructure.
        """
        from graph_builder import GraphBuilder
        from graph_utils import escape_path_rooms

        graph_builder = GraphBuilder()
        graph = graph_builder.build(state)

        # Adjacency + door state
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

        # Power reachable
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
            minor_slots_free = room.minor_slot_count - len(room.minor_module_names)
            has_major = 1.0 if room.major_module_name else 0.0
            room_features[room.index] = [
                float(room.is_powered or room.is_auto_powered),
                float(room.is_auto_powered),
                float(room.is_start_room),
                float(room.is_exit_room),
                float(room.depth),
                float(room.suffers_emp),
                float(room.emp_turns_remaining),
                float(room.has_artifact),
                float(room.has_stele),
                float(room.minor_slot_count),
                float(minor_slots_free),
                has_major,
                float(len(room.minor_module_names)),
                float(room.hero_count),
                float(room.mob_count),
                float(room.npc_count),
                float(room.dust_loot_amount),
                0.0,  # is_on_escape_path (simplified)
                0.0,  # dist_to_crystal (simplified)
                0.0,  # dist_to_exit (simplified)
            ]

        # Hero features
        hero_features = np.full((MAX_HEROES, HERO_FEATURE_DIM), -1.0, dtype=np.float32)
        faction_map = {"Other": 0, "Guard": 1, "Prisoner": 2, "Native": 3}
        weapon_class_map = {"Melee": 1, "Ranged": 2, "Support": 3}
        for i, hero in enumerate(state.heroes[:MAX_HEROES]):
            hp_ratio = hero.hp / hero.max_hp if hero.max_hp > 0 else 0.0
            has_operate = 1.0 if any(p.name == "Operate" for p in hero.passive_skills) else 0.0
            has_repair = 1.0 if any(p.name == "Repair" for p in hero.passive_skills) else 0.0
            weapon_class_id = float(weapon_class_map.get(hero.weapon_class or "", 0))

            # Skill tree derived features
            total_skills = float(len(hero.skill_tree)) if hero.skill_tree else 0.0
            unlocked_skills = float(sum(1 for e in hero.skill_tree if e.is_unlocked)) if hero.skill_tree else 0.0
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
                0.0,                             # 5: is_busy (simplified — no move tracking in agent)
                float(hero.is_usable),           # 6
                float(len(hero.passive_skills)), # 7
                has_operate,                     # 8
                has_repair,                      # 9
                float(len(hero.active_skills)),  # 10
                float(len(hero.equipment)),      # 11
                float(faction_map.get(hero.faction, 0)),  # 12
                weapon_class_id,                 # 13
                float(hero.level_up_cost),       # 14: level_up_cost
                0.0,                             # 15: dist_to_exit (simplified)
                0.0,                             # 16: dist_to_crystal (simplified)
                float(hero.is_gathering_item),   # 17
                total_skills,                    # 18
                unlocked_skills,                 # 19
                next_unlock,                     # 20
                total_skills - unlocked_skills,  # 21
            ]

        # Mob features
        mob_features = np.full((MAX_MOBS, MOB_FEATURE_DIM), -1.0, dtype=np.float32)
        target_map = {"AntiHeroMob": 0, "AntiModuleMob": 1, "Crystal": 2, "Artifact": 3}
        for i, mob in enumerate(state.mobs[:MAX_MOBS]):
            hp_ratio = mob.hp / mob.max_hp if mob.max_hp > 0 else 0.0
            mob_features[i] = [
                float(mob.room_index), hp_ratio,
                float(target_map.get(mob.target_type, 0)),
                0.0, 0.0,
            ]

        # Resources
        res = state.resources
        if res:
            dust_used = res.powered_room_count * res.room_power_cost
            resources = np.array([
                res.industry, res.food, res.science, res.dust, res.dust_max,
                res.industry_per_turn, res.food_per_turn, res.science_per_turn,
                dust_used, res.dust - dust_used,
            ], dtype=np.float32)
        else:
            resources = np.zeros(RESOURCE_DIM, dtype=np.float32)

        # Game meta
        phase_map = {GamePhase.STRATEGY: 0, GamePhase.TACTICAL_PAUSE: 0,
                     GamePhase.ACTION: 1, GamePhase.WAVE_ACTIVE: 1,
                     GamePhase.GAME_OVER: 2, GamePhase.ESCAPING: 3}
        game_meta = np.array([
            float(state.turn), float(state.floor),
            float(phase_map.get(state.game_phase, 0)),
            float(len(state.rooms)), float(len(state.heroes)),
            float(len(state.mobs)), float(len(state.closed_doors)),
            float(state.is_crystal_safe), float(state.exit_room_index),
            float(state.time_scale), float(1 if state.floor >= 12 else 0),
            float(sum(len(r.adjacent_room_indices) for r in state.rooms) // 2),
        ], dtype=np.float32)

        # Action mask
        mask = self._mask_computer.compute_mask(state)
        action_mask = mask.astype(np.int8)

        # Convert to tensors with batch dim
        def _t(arr):
            return torch.tensor(arr, device=self.device).unsqueeze(0)

        return {
            "adjacency": _t(adjacency),
            "door_state": _t(door_state),
            "power_state": _t(power_state),
            "power_reachable": _t(power_reachable),
            "room_features": _t(room_features),
            "hero_features": _t(hero_features),
            "mob_features": _t(mob_features),
            "resources": _t(resources),
            "game_meta": _t(game_meta),
            "action_mask": _t(action_mask),
        }

    # ------------------------------------------------------------------
    # Action Translation
    # ------------------------------------------------------------------

    def _translate_strategic_action(
        self, state: GameStatePayload,
        option: StrategicOption, room_target: int, hero_target: int, entity_target: int,
    ) -> Optional[dict]:
        """Translate a strategic option into a game command dict."""
        hero_name = self._get_hero_name(state, hero_target)

        if option == StrategicOption.WAIT:
            return None

        elif option == StrategicOption.POWER_ROOM:
            return {"command": "POWER_ROOM", "parameters": {"room_index": room_target}}

        elif option == StrategicOption.DEPOWER_ROOM:
            return {"command": "UNPOWER_ROOM", "parameters": {"room_index": room_target}}

        elif option == StrategicOption.BUILD_MODULE:
            module_name = ""
            if state.buildable_blueprints:
                idx = entity_target % len(state.buildable_blueprints)
                module_name = state.buildable_blueprints[idx].name
            slot_type = "minor"
            if module_name and "Major" in module_name:
                slot_type = "major"
            return {"command": "BUILD_MODULE", "parameters": {
                "room_index": room_target, "module_name": module_name, "slot_type": slot_type
            }}

        elif option == StrategicOption.DESTROY_MODULE:
            module_name = self._resolve_room_module(state, room_target, entity_target)
            return {"command": "SELL_MODULE", "parameters": {
                "room_index": room_target, "module_name": module_name
            }}

        elif option == StrategicOption.RESEARCH:
            blueprint_name = ""
            if state.researchable_blueprints:
                idx = entity_target % len(state.researchable_blueprints)
                blueprint_name = state.researchable_blueprints[idx].name
            return {"command": "RESEARCH", "parameters": {"blueprint_name": blueprint_name}}

        elif option == StrategicOption.RECRUIT_HERO:
            recruit_name = ""
            if state.recruitable_heroes:
                idx = entity_target % len(state.recruitable_heroes)
                recruit_name = state.recruitable_heroes[idx].name
            return {"command": "RECRUIT_HERO", "parameters": {
                "recruiter_hero_name": hero_name or "", "recruit_name": recruit_name
            }}

        elif option == StrategicOption.DISMISS_HERO:
            return {"command": "DISMISS_HERO", "parameters": {"hero_name": hero_name or ""}}

        elif option == StrategicOption.LEVEL_UP_HERO:
            return {"command": "LEVEL_UP_HERO", "parameters": {"hero_name": hero_name or ""}}

        elif option == StrategicOption.BUY_ITEM:
            item_name, merchant_room = "", 0
            if state.merchants:
                all_items = [(it.name, m.room_index) for m in state.merchants for it in m.items]
                if all_items:
                    idx = entity_target % len(all_items)
                    item_name, merchant_room = all_items[idx]
            return {"command": "BUY_FROM_MERCHANT", "parameters": {
                "hero_name": hero_name or "", "item_name": item_name,
                "merchant_room_index": merchant_room
            }}

        elif option == StrategicOption.EQUIP_ITEM:
            item_name = ""
            all_items = list(state.backpack_items) + list(state.shared_inventory_items)
            if all_items:
                idx = entity_target % len(all_items)
                item_name = all_items[idx].name
            return {"command": "EQUIP_ITEM", "parameters": {
                "hero_name": hero_name or "", "item_name": item_name
            }}

        elif option == StrategicOption.UNEQUIP_ITEM:
            slots = ["Weapon", "Armor", "Accessory"]
            slot = slots[entity_target % len(slots)]
            return {"command": "UNEQUIP_ITEM", "parameters": {
                "hero_name": hero_name or "", "slot_category": slot
            }}

        elif option == StrategicOption.POSITION_HERO:
            return {"command": "MOVE_HERO", "parameters": {
                "hero_name": hero_name or "", "target_room_index": room_target
            }}

        elif option == StrategicOption.OPEN_DOOR:
            from_room = state.heroes[hero_target].room_index if hero_target < len(state.heroes) else 0
            return {"command": "OPEN_DOOR", "parameters": {
                "hero_name": hero_name or "", "from_room_index": from_room,
                "target_room_index": room_target
            }}

        elif option == StrategicOption.HEAL_HERO:
            food_amount = max(1, int((state.resources.food if state.resources else 0) * 0.1))
            return {"command": "HEAL_HERO", "parameters": {
                "hero_name": hero_name or "", "food_amount": food_amount
            }}

        elif option == StrategicOption.INITIATE_ESCAPE:
            self._escape_initiated = True
            return {"command": "PICK_UP_CRYSTAL", "parameters": {"hero_name": hero_name or ""}}

        elif option == StrategicOption.COLLECT_ITEM:
            # Move hero to room with dropped item; agent tracks busy until pickup done
            item_room = 0
            if state.dropped_items:
                idx = entity_target % len(state.dropped_items)
                item_room = state.dropped_items[idx].room_index
            return {"command": "MOVE_HERO", "parameters": {
                "hero_name": hero_name or "", "target_room_index": item_room
            }}

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_hero_name(self, state: GameStatePayload, hero_idx: int) -> Optional[str]:
        """Get hero name by index, or None if invalid."""
        if hero_idx < len(state.heroes):
            return state.heroes[hero_idx].name
        return None

    def _resolve_room_module(self, state: GameStatePayload, room_idx: int, entity_idx: int) -> str:
        """Find a module name in a room by entity index."""
        for room in state.rooms:
            if room.index == room_idx:
                modules = []
                if room.major_module_name:
                    modules.append(room.major_module_name)
                modules.extend(room.minor_module_names)
                if modules:
                    return modules[entity_idx % len(modules)]
        return ""

    # ------------------------------------------------------------------
    # Checkpoint Management
    # ------------------------------------------------------------------

    def save_checkpoint(self, path: str | Path) -> None:
        """Save all network weights to a file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save({
            "policy_net": self.policy_net.state_dict(),
            "micro_net": self.micro_net.state_dict(),
            "escape_net": self.escape_net.state_dict(),
        }, path)
        logger.info(f"Checkpoint saved: {path}")

    def load_checkpoint(self, path: str | Path) -> None:
        """Load network weights from a file."""
        path = Path(path)
        if not path.exists():
            logger.warning(f"Checkpoint not found: {path}")
            return
        checkpoint = torch.load(path, map_location=self.device, weights_only=True)
        self.policy_net.load_state_dict(checkpoint["policy_net"])
        self.micro_net.load_state_dict(checkpoint["micro_net"])
        self.escape_net.load_state_dict(checkpoint["escape_net"])
        logger.info(f"Checkpoint loaded: {path}")

"""
Reward Shaping: Configurable reward function with toggle-able guideline shaping terms.

Computes reward from (prev_state, curr_state, action, action_result) tuples.
Core rewards are always active. Guideline-shaped rewards can be toggled on/off
via RewardConfig to support curriculum training.
"""

from __future__ import annotations

import logging
from typing import Optional

import networkx as nx

from graph_builder import GraphBuilder
from rl_config import CoreRewardWeights, GuidelineRewardWeights, RewardConfig
from state_parser import GameStatePayload, HeroState, RoomState

logger = logging.getLogger(__name__)


class RewardShaper:
    """
    Computes per-step rewards from state transitions.

    Core rewards (always active):
      - Floor escaped / game over / hero died
      - Room explored / invalid action / successful action
      - Module built / research completed / item equipped / dust collected
      - Floor progress bonus / wait penalty

    Guideline-shaped rewards (toggle-able):
      - Power chain awareness (GL-POWER)
      - Operate bonus awareness (GL-OPERATE)
      - Escape timing (GL-ESCAPE)
      - Combat positioning (GL-COMBAT)
      - Equipment matching (GL-EQUIPMENT)
      - Recruitment decisions (GL-RECRUIT)
      - Cross-floor industry (GL-INDUSTRY)
    """

    def __init__(self, config: Optional[RewardConfig] = None):
        self.config = config or RewardConfig()
        self._graph_builder = GraphBuilder()
        # Track heroes dismissed this step (so they don't trigger hero_died penalty)
        self._dismissed_this_step: set[str] = set()
        # Track recent actions for oscillation detection (last 10 action signatures)
        self._recent_actions: list[str] = []

    @property
    def core(self) -> CoreRewardWeights:
        return self.config.core

    @property
    def gl(self) -> GuidelineRewardWeights:
        return self.config.guidelines

    def compute_reward(
        self,
        prev_state: Optional[GameStatePayload],
        curr_state: GameStatePayload,
        action: Optional[dict] = None,
        action_result: Optional[dict] = None,
    ) -> float:
        """
        Compute the total reward for a single step.

        Args:
            prev_state: State before the action (None on first step).
            curr_state: State after the action.
            action: The action dict that was sent (command + parameters).
            action_result: The result dict from the mod (success, error, metadata).

        Returns:
            Total reward (float).
        """
        if prev_state is None:
            return 0.0

        reward = 0.0

        # --- Core Rewards ---
        reward += self._core_rewards(prev_state, curr_state, action, action_result)

        # --- Guideline-Shaped Rewards ---
        reward += self._guideline_rewards(prev_state, curr_state, action, action_result)

        return reward

    # ------------------------------------------------------------------
    # Core Rewards (always active)
    # ------------------------------------------------------------------

    def _core_rewards(
        self,
        prev: GameStatePayload,
        curr: GameStatePayload,
        action: Optional[dict],
        result: Optional[dict],
    ) -> float:
        reward = 0.0

        # Floor escaped
        if curr.is_escaping and not prev.is_escaping:
            reward += self.core.floor_escaped
            # Floor progress bonus
            reward += self.core.floor_progress_scale * (curr.floor / 12.0)

        # Game over (crystal destroyed)
        if curr.is_game_over and not prev.is_game_over:
            reward += self.core.game_over

        # Hero died (exclude dismissed heroes — handled separately in GL-RECRUIT)
        prev_heroes = {h.name for h in prev.heroes}
        curr_heroes = {h.name for h in curr.heroes}
        heroes_lost = prev_heroes - curr_heroes
        # Filter out heroes that were dismissed this step
        self._dismissed_this_step.clear()
        if action and action.get("command") == "DISMISS_HERO" and result and result.get("success"):
            dismissed_name = action.get("parameters", {}).get("hero_name", "")
            if dismissed_name:
                self._dismissed_this_step.add(dismissed_name)
        combat_deaths = heroes_lost - self._dismissed_this_step
        reward += self.core.hero_died * len(combat_deaths)

        # Room explored (new rooms in state)
        new_rooms = len(curr.rooms) - len(prev.rooms)
        if new_rooms > 0:
            reward += self.core.room_explored * new_rooms

        # Action validity
        if result is not None:
            if result.get("success", False):
                reward += self.core.successful_action
            else:
                reward += self.core.invalid_action

        # Wait penalty (agent chose to do nothing)
        if action and action.get("command") == "WAIT":
            reward += self.core.wait_penalty

        # Repeat/oscillation penalty — detect toggling power or moving heroes back and forth
        if action and result and result.get("success", False):
            action_sig = self._get_action_signature(action)
            inverse_sig = self._get_inverse_signature(action)
            # Check if the inverse of this action was done recently
            if inverse_sig and inverse_sig in self._recent_actions:
                reward += self.core.repeat_action_penalty
            # Track this action
            self._recent_actions.append(action_sig)
            if len(self._recent_actions) > 10:
                self._recent_actions.pop(0)

        # Module built
        prev_modules = self._count_modules(prev)
        curr_modules = self._count_modules(curr)
        modules_built = curr_modules - prev_modules
        if modules_built > 0:
            # Check if any are industry generators
            industry_built = self._count_industry_modules(curr) - self._count_industry_modules(prev)
            if industry_built > 0:
                reward += self.core.industry_built * industry_built
                modules_built -= industry_built
            reward += self.core.module_built * modules_built

        # Module destroyed by mobs (not sold by agent)
        if modules_built < 0:
            was_sell_action = (action and action.get("command") == "SELL_MODULE" and result and result.get("success"))
            # Penalty applies regardless of whether it was sold or destroyed by mobs
            # (selling is just as wasteful as losing it — the industry is gone either way)
            destroyed_cost = self._estimate_destroyed_module_cost(prev, curr)
            reward += self.core.module_destroyed_cost_scale * destroyed_cost

        # Research completed
        prev_blueprints = len(prev.researchable_blueprints)
        curr_blueprints = len(curr.researchable_blueprints)
        if curr_blueprints < prev_blueprints and action and action.get("command") == "RESEARCH":
            reward += self.core.research_completed

        # Item equipped
        if action and action.get("command") == "EQUIP_ITEM" and result and result.get("success"):
            reward += self.core.item_equipped

        # Heal hero penalty (food is valuable, healing should be a last resort)
        if action and action.get("command") == "HEAL_HERO" and result and result.get("success"):
            reward += self.core.heal_hero_penalty

        # Dust collected / lost
        prev_dust = prev.resources.dust if prev.resources else 0
        curr_dust = curr.resources.dust if curr.resources else 0
        dust_delta = curr_dust - prev_dust
        if dust_delta > 0:
            # Don't reward dust "gained" from depowering a room (that's just freed dust, not collected)
            was_depower = (action and action.get("command") == "UNPOWER_ROOM" and result and result.get("success"))
            if not was_depower:
                reward += self.core.dust_collected_per_unit * dust_delta
        elif dust_delta < 0:
            # Dust lost (mobs hitting crystal) — don't penalize if agent spent dust on powering
            was_power_action = (action and action.get("command") == "POWER_ROOM" and result and result.get("success"))
            if not was_power_action:
                reward += self.core.dust_lost_per_unit * abs(dust_delta)

        # Per-turn production reward (only on turn change / door open)
        # Fires when turn advances (new rooms = door opened, or turn counter changed)
        if curr.turn > prev.turn and curr.resources:
            total_production = (
                curr.resources.industry_per_turn
                + curr.resources.food_per_turn
                + curr.resources.science_per_turn
            )
            reward += self.core.production_per_turn_scale * total_production

        return reward

    # ------------------------------------------------------------------
    # Guideline-Shaped Rewards (toggle-able)
    # ------------------------------------------------------------------

    def _guideline_rewards(
        self,
        prev: GameStatePayload,
        curr: GameStatePayload,
        action: Optional[dict],
        result: Optional[dict],
    ) -> float:
        reward = 0.0

        reward += self._gl_power(prev, curr, action, result)
        reward += self._gl_operate(prev, curr, action, result)
        reward += self._gl_escape(prev, curr, action, result)
        reward += self._gl_combat(prev, curr, action, result)
        reward += self._gl_equipment(prev, curr, action, result)
        reward += self._gl_recruit(prev, curr, action, result)
        reward += self._gl_industry(prev, curr, action, result)

        return reward

    def _gl_power(
        self, prev: GameStatePayload, curr: GameStatePayload,
        action: Optional[dict], result: Optional[dict],
    ) -> float:
        """GL-POWER: Reward for maintaining good power chains, penalty for breaking them."""
        if not self.gl.enabled_power:
            return 0.0

        reward = 0.0

        # Detect if we just depowered a room
        if action and action.get("command") == "UNPOWER_ROOM" and result and result.get("success"):
            room_idx = action.get("parameters", {}).get("room_index", -1)

            # Penalty for depowering a room that has modules (waste of investment)
            room = self._get_room(curr, room_idx)
            if room:
                module_cost = self._estimate_room_module_cost(room, curr)
                if module_cost > 0:
                    reward += self.gl.depower_module_room_cost_scale * module_cost

            # Check if depowering broke the power chain (disconnected rooms from crystal)
            prev_powered_reachable = self._powered_reachable_count(prev)
            curr_powered_reachable = self._powered_reachable_count(curr)

            if curr_powered_reachable < prev_powered_reachable:
                # Depowering cut off rooms from crystal
                rooms_lost = prev_powered_reachable - curr_powered_reachable
                reward += self.gl.power_chain_broken * rooms_lost

        # Detect if we just powered a room that extends the longest powered chain
        if action and action.get("command") == "POWER_ROOM" and result and result.get("success"):
            curr_powered_reachable = self._powered_reachable_count(curr)
            prev_powered_reachable = self._powered_reachable_count(prev)

            if curr_powered_reachable > prev_powered_reachable:
                reward += self.gl.power_chain_optimal

        return reward

    def _gl_operate(
        self, prev: GameStatePayload, curr: GameStatePayload,
        action: Optional[dict], result: Optional[dict],
    ) -> float:
        """GL-OPERATE: Reward for placing operators, penalty for interrupting them."""
        if not self.gl.enabled_operate:
            return 0.0

        reward = 0.0

        # Detect new operator placement
        prev_operating = {h.name for h in prev.heroes if h.is_operating}
        curr_operating = {h.name for h in curr.heroes if h.is_operating}

        new_operators = curr_operating - prev_operating
        if new_operators:
            reward += self.gl.operator_placed * len(new_operators)

        # Detect operator interruption (was operating, now not — and we moved them)
        interrupted = prev_operating - curr_operating
        if interrupted and action and action.get("command") == "MOVE_HERO":
            moved_hero = action.get("parameters", {}).get("hero_name", "")
            if moved_hero in interrupted:
                reward += self.gl.operator_interrupted

        return reward

    def _gl_escape(
        self, prev: GameStatePayload, curr: GameStatePayload,
        action: Optional[dict], result: Optional[dict],
    ) -> float:
        """GL-ESCAPE: Reward for good escape timing."""
        if not self.gl.enabled_escape:
            return 0.0

        reward = 0.0

        # Floor just escaped
        if curr.is_escaping and not prev.is_escaping:
            # Did we open all doors first? (maximum resources gathered)
            if not curr.closed_doors:
                reward += self.gl.escape_all_doors_open
            else:
                # Escaped early — could be wise or premature
                reward += self.gl.escape_early_but_safe

        # Overstayed: game over after many doors opened (opened lots but died)
        if curr.is_game_over and not prev.is_game_over:
            # If we had very few closed doors left, we overstayed
            if len(prev.closed_doors) <= 2 and len(prev.rooms) > 6:
                reward += self.gl.overstayed

        # Hero moved to exit room during escape (crystal already picked up)
        if action and action.get("command") == "MOVE_HERO" and result and result.get("success"):
            # Check if crystal is being carried (escape in progress)
            crystal_carried = any(h.has_crystal for h in curr.heroes)
            if crystal_carried:
                target_room = action.get("parameters", {}).get("target_room_index", -1)
                if target_room == curr.exit_room_index and curr.exit_room_index >= 0:
                    reward += self.gl.hero_moved_to_exit

        return reward

    def _gl_combat(
        self, prev: GameStatePayload, curr: GameStatePayload,
        action: Optional[dict], result: Optional[dict],
    ) -> float:
        """GL-COMBAT: Reward for spawn blocking, penalty for heavy damage."""
        if not self.gl.enabled_combat:
            return 0.0

        reward = 0.0

        # Detect spawn blocking: hero in unpowered room during Action phase
        if curr.game_phase.is_combat:
            for hero in curr.heroes:
                room = self._get_room(curr, hero.room_index)
                if room and not room.is_powered and not room.is_auto_powered:
                    # Hero is in an unpowered room — potential spawn blocker
                    # Only reward if there are actually mobs that could spawn
                    if curr.is_spawning_mobs:
                        reward += self.gl.spawn_blocked * 0.1  # Small per-step bonus

        # Hero took heavy damage (dropped below 30% HP)
        for curr_hero in curr.heroes:
            prev_hero = self._find_hero(prev, curr_hero.name)
            if prev_hero is None:
                continue
            prev_ratio = prev_hero.hp / prev_hero.max_hp if prev_hero.max_hp > 0 else 1.0
            curr_ratio = curr_hero.hp / curr_hero.max_hp if curr_hero.max_hp > 0 else 1.0
            if prev_ratio >= 0.3 and curr_ratio < 0.3:
                reward += self.gl.hero_took_heavy_damage

        # Hero healed wisely (healed when below 30%)
        if action and action.get("command") == "HEAL_HERO" and result and result.get("success"):
            hero_name = action.get("parameters", {}).get("hero_name", "")
            prev_hero = self._find_hero(prev, hero_name)
            if prev_hero and prev_hero.max_hp > 0:
                if (prev_hero.hp / prev_hero.max_hp) < 0.3:
                    reward += self.gl.hero_healed_wisely

        # Hero moved to crystal room to defend against mobs
        if action and action.get("command") == "MOVE_HERO" and result and result.get("success"):
            target_room = action.get("parameters", {}).get("target_room_index", -1)
            crystal_room = curr.start_room_index
            if target_room == crystal_room:
                # Check if there are mobs in or near the crystal room
                mobs_at_crystal = any(m.room_index == crystal_room for m in curr.mobs)
                if mobs_at_crystal:
                    reward += self.gl.hero_moved_to_crystal_defense

        return reward

    def _gl_equipment(
        self, prev: GameStatePayload, curr: GameStatePayload,
        action: Optional[dict], result: Optional[dict],
    ) -> float:
        """GL-EQUIPMENT: Reward for equipping compatible weapons."""
        if not self.gl.enabled_equipment:
            return 0.0

        # Only applies when equipping
        if not (action and action.get("command") == "EQUIP_ITEM" and result and result.get("success")):
            return 0.0

        # For now, any successful equip that was to the right slot category counts
        # Full weapon-class checking would require the mod to expose weapon_class on items
        # and hero weapon_class compatibility — for now we just give the base reward
        # (item_equipped in core covers this; GL adds nothing extra until weapon class data exists)
        return 0.0

    def _gl_recruit(
        self, prev: GameStatePayload, curr: GameStatePayload,
        action: Optional[dict], result: Optional[dict],
    ) -> float:
        """GL-RECRUIT: Reward for recruiting useful heroes."""
        if not self.gl.enabled_recruit:
            return 0.0

        reward = 0.0

        if action and action.get("command") == "RECRUIT_HERO" and result and result.get("success"):
            # Check if the recruited hero has useful passives
            recruit_name = action.get("parameters", {}).get("recruit_name", "")
            recruit = next(
                (r for r in prev.recruitable_heroes if r.name == recruit_name), None
            )
            if recruit:
                useful_passives = {"Operate", "Repair", "Fast"}
                has_useful = any(
                    p in useful_passives for p in recruit.passive_skill_names
                )
                if has_useful:
                    reward += self.gl.recruited_useful_hero
                else:
                    # Still some reward for recruiting, just less
                    reward += self.gl.recruited_useful_hero * 0.3

        # Dismiss logic: penalty depends on context
        if action and action.get("command") == "DISMISS_HERO" and result and result.get("success"):
            party_size = len(prev.heroes)
            has_recruitable = bool(prev.recruitable_heroes)
            if party_size >= 4 and has_recruitable:
                # Dismissing to make room for a better hero — net 0 with recruit reward
                reward += self.gl.dismissed_for_upgrade
            else:
                # Wasteful dismiss — no replacement available or party not full
                reward += self.gl.dismissed_wasteful

        return reward

    def _gl_industry(
        self, prev: GameStatePayload, curr: GameStatePayload,
        action: Optional[dict], result: Optional[dict],
    ) -> float:
        """GL-INDUSTRY: Reward for carrying industry between floors."""
        if not self.gl.enabled_industry:
            return 0.0

        # Only applies at floor transitions
        if curr.is_escaping and not prev.is_escaping:
            industry = curr.resources.industry if curr.resources else 0
            if industry > 0:
                return self.gl.floor_exit_industry_scale * (industry / 100.0)

        return 0.0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _count_modules(self, state: GameStatePayload) -> int:
        """Count total modules built across all rooms."""
        total = 0
        for room in state.rooms:
            if room.major_module_name:
                total += 1
            total += len(room.minor_module_names)
        return total

    def _count_industry_modules(self, state: GameStatePayload) -> int:
        """Count industry generator modules (Major0002)."""
        count = 0
        for room in state.rooms:
            if room.major_module_name and "Major0002" in room.major_module_name:
                count += 1
        return count

    def _estimate_destroyed_module_cost(self, prev: GameStatePayload, curr: GameStatePayload) -> float:
        """
        Estimate total industry cost of modules that were destroyed between states.

        Compares modules per-room. Uses buildable_blueprints to look up costs,
        falls back to a default estimate (15 industry) if not found.
        """
        # Build a cost lookup from buildable blueprints
        cost_lookup: dict[str, float] = {}
        for bp in curr.buildable_blueprints:
            cost_lookup[bp.name] = bp.industry_cost
        for bp in prev.buildable_blueprints:
            cost_lookup[bp.name] = bp.industry_cost

        default_cost = 15.0  # Reasonable default if blueprint cost unknown
        total_cost = 0.0

        # Compare per-room
        curr_rooms = {r.index: r for r in curr.rooms}
        for prev_room in prev.rooms:
            curr_room = curr_rooms.get(prev_room.index)
            if curr_room is None:
                continue

            # Check major module
            if prev_room.major_module_name and not curr_room.major_module_name:
                cost = cost_lookup.get(prev_room.major_module_name, default_cost)
                total_cost += cost

            # Check minor modules
            prev_minors = set(prev_room.minor_module_names)
            curr_minors = set(curr_room.minor_module_names)
            destroyed_minors = prev_minors - curr_minors
            for module_name in destroyed_minors:
                cost = cost_lookup.get(module_name, default_cost)
                total_cost += cost

        return total_cost

    def _powered_reachable_count(self, state: GameStatePayload) -> int:
        """Count rooms reachable from crystal via powered chain."""
        if not state.rooms:
            return 0

        graph = self._graph_builder.build(state)
        crystal_room = state.start_room_index

        if crystal_room not in graph:
            return 0

        # BFS through powered rooms connected via open doors
        visited = set()
        queue = [crystal_room]
        while queue:
            room_idx = queue.pop(0)
            if room_idx in visited:
                continue
            visited.add(room_idx)
            for neighbor in graph.neighbors(room_idx):
                if neighbor in visited:
                    continue
                edge_data = graph.edges[room_idx, neighbor]
                if not edge_data.get("is_open", False):
                    continue
                node_data = graph.nodes.get(neighbor, {})
                if node_data.get("is_powered", False) or node_data.get("is_auto_powered", False):
                    queue.append(neighbor)

        return len(visited)

    def _get_room(self, state: GameStatePayload, room_index: int) -> Optional[RoomState]:
        """Find a room by index."""
        for room in state.rooms:
            if room.index == room_index:
                return room
        return None

    def _estimate_room_module_cost(self, room: RoomState, state: GameStatePayload) -> float:
        """Estimate total industry cost of modules in a room."""
        cost_lookup: dict[str, float] = {}
        for bp in state.buildable_blueprints:
            cost_lookup[bp.name] = bp.industry_cost

        default_cost = 15.0
        total = 0.0
        if room.major_module_name:
            total += cost_lookup.get(room.major_module_name, default_cost)
        for minor in room.minor_module_names:
            total += cost_lookup.get(minor, default_cost)
        return total

    def _find_hero(self, state: GameStatePayload, name: str) -> Optional[HeroState]:
        """Find a hero by name in a state."""
        for hero in state.heroes:
            if hero.name == name:
                return hero
        return None

    def _get_action_signature(self, action: dict) -> str:
        """Get a compact signature for an action (for oscillation detection)."""
        cmd = action.get("command", "")
        params = action.get("parameters", {})
        if cmd == "POWER_ROOM":
            return f"POWER:{params.get('room_index')}"
        elif cmd == "UNPOWER_ROOM":
            return f"UNPOWER:{params.get('room_index')}"
        elif cmd == "MOVE_HERO":
            return f"MOVE:{params.get('hero_name')}→{params.get('target_room_index')}"
        elif cmd == "POSITION_HERO":
            return f"MOVE:{params.get('hero_name')}→{params.get('target_room_index')}"
        return f"{cmd}"

    def _get_inverse_signature(self, action: dict) -> Optional[str]:
        """Get the signature of the inverse action (what would undo this)."""
        cmd = action.get("command", "")
        params = action.get("parameters", {})
        if cmd == "POWER_ROOM":
            return f"UNPOWER:{params.get('room_index')}"
        elif cmd == "UNPOWER_ROOM":
            return f"POWER:{params.get('room_index')}"
        elif cmd in ("MOVE_HERO", "POSITION_HERO"):
            # The inverse of moving hero X to room Y is moving hero X FROM room Y
            # We detect this by checking if we recently moved this hero elsewhere
            hero_name = params.get("hero_name", "")
            # Check if this hero was recently moved — any prior MOVE of same hero = oscillation
            for prev_sig in reversed(self._recent_actions):
                if prev_sig.startswith(f"MOVE:{hero_name}→"):
                    # Same hero moved again = likely oscillation
                    return prev_sig
            return None
        return None

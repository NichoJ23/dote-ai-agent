"""
Action Masking: Compute valid action masks from game state.

Only masks clearly IMPOSSIBLE actions (hard constraints). Soft strategic
decisions remain unmasked — the agent learns those through reward signals.

The mask is a boolean array of length NUM_OPTIONS (16) where True = valid, False = masked.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Optional

import numpy as np

from state_parser import GameStatePayload, HeroState, RoomState


# ---------------------------------------------------------------------------
# Strategic Options Enum (matches design §11.4)
# ---------------------------------------------------------------------------


class StrategicOption(IntEnum):
    """High-level strategic options the agent can select."""

    POWER_ROOM = 0
    DEPOWER_ROOM = 1
    BUILD_MODULE = 2
    DESTROY_MODULE = 3
    RESEARCH = 4
    RECRUIT_HERO = 5
    DISMISS_HERO = 6
    LEVEL_UP_HERO = 7
    BUY_ITEM = 8
    EQUIP_ITEM = 9
    UNEQUIP_ITEM = 10
    POSITION_HERO = 11
    OPEN_DOOR = 12
    HEAL_HERO = 13
    INITIATE_ESCAPE = 14
    COLLECT_ITEM = 15
    WAIT = 16


NUM_OPTIONS = len(StrategicOption)


# ---------------------------------------------------------------------------
# Action Mask Computer
# ---------------------------------------------------------------------------


class ActionMaskComputer:
    """
    Computes which strategic options are valid given the current game state.

    Only masks physically impossible actions:
      - No resources to perform action
      - No valid targets (no rooms to power, no heroes to level, etc.)
      - Prerequisite not met (no artifact for research, exit not found for escape)

    Does NOT mask strategic decisions:
      - Which room to power (all unpowered rooms remain valid targets)
      - Whether to buy an expensive item vs save dust
      - Whether opening another door is too risky
    """

    def __init__(self, disable_destroy_module: bool = False):
        """
        Args:
            disable_destroy_module: If True, DESTROY_MODULE is always masked.
                                   Useful for early curriculum stages.
        """
        self._disable_destroy_module = disable_destroy_module

    def compute_mask(self, state: GameStatePayload) -> np.ndarray:
        """
        Compute the action validity mask.

        Args:
            state: Current game state.

        Returns:
            Boolean numpy array of shape (NUM_OPTIONS,). True = valid option.
        """
        mask = np.zeros(NUM_OPTIONS, dtype=np.bool_)

        # WAIT is always valid
        mask[StrategicOption.WAIT] = True

        # Only allow strategic actions during Strategy phase
        if not state.game_phase.is_planning:
            # During combat, only POSITION_HERO, HEAL_HERO, and WAIT are valid
            mask[StrategicOption.POSITION_HERO] = self._can_position_hero(state)
            mask[StrategicOption.HEAL_HERO] = self._can_heal(state)
            return mask

        # Strategy phase — check each option
        mask[StrategicOption.POWER_ROOM] = self._can_power_room(state)
        mask[StrategicOption.DEPOWER_ROOM] = self._can_depower_room(state)
        mask[StrategicOption.BUILD_MODULE] = self._can_build_module(state)
        mask[StrategicOption.DESTROY_MODULE] = self._can_destroy_module(state) and not self._disable_destroy_module
        mask[StrategicOption.RESEARCH] = self._can_research(state)
        mask[StrategicOption.RECRUIT_HERO] = self._can_recruit(state)
        mask[StrategicOption.DISMISS_HERO] = self._can_dismiss(state)
        mask[StrategicOption.LEVEL_UP_HERO] = self._can_level_up(state)
        mask[StrategicOption.BUY_ITEM] = self._can_buy_item(state)
        mask[StrategicOption.EQUIP_ITEM] = self._can_equip_item(state)
        mask[StrategicOption.UNEQUIP_ITEM] = self._can_unequip_item(state)
        mask[StrategicOption.POSITION_HERO] = self._can_position_hero(state)
        mask[StrategicOption.OPEN_DOOR] = self._can_open_door(state)
        mask[StrategicOption.HEAL_HERO] = self._can_heal(state)
        mask[StrategicOption.INITIATE_ESCAPE] = self._can_initiate_escape(state)
        mask[StrategicOption.COLLECT_ITEM] = self._can_collect_item(state)

        return mask

    # ------------------------------------------------------------------
    # Individual option checks
    # ------------------------------------------------------------------

    def _can_power_room(self, state: GameStatePayload) -> bool:
        """Can we power at least one unpowered room?"""
        if not state.resources:
            return False
        # Need available dust (dust > rooms_currently_powered * cost)
        dust_available = state.resources.dust - state.resources.powered_room_count * state.resources.room_power_cost
        if dust_available <= 0:
            # Check simple: dust > 0 and there are unpowered rooms
            if state.resources.dust <= 0:
                return False
        # Need at least one unpowered, non-auto room that's explored
        return any(
            not r.is_powered and not r.is_auto_powered
            for r in state.rooms
        )

    def _can_depower_room(self, state: GameStatePayload) -> bool:
        """Can we depower at least one currently powered room?"""
        return any(
            r.is_powered and not r.is_auto_powered
            for r in state.rooms
        )

    def _can_build_module(self, state: GameStatePayload) -> bool:
        """Can we build at least one module?"""
        if not state.resources:
            return False
        if state.resources.industry <= 0:
            return False
        # Need unlocked blueprints
        if not state.buildable_blueprints:
            return False
        # Need at least one room with an available slot
        # Check if any blueprint is affordable
        cheapest_cost = min(bp.industry_cost for bp in state.buildable_blueprints)
        if state.resources.industry < cheapest_cost:
            return False
        # Check for available slots
        for room in state.rooms:
            if not room.is_powered and not room.is_auto_powered:
                continue  # Can only build in powered rooms
            # Major slot available?
            if room.major_module_name is None:
                return True
            # Minor slots available?
            if len(room.minor_module_names) < room.minor_slot_count:
                return True
        return False

    def _can_destroy_module(self, state: GameStatePayload) -> bool:
        """Can we destroy/sell at least one built module?"""
        for room in state.rooms:
            if room.major_module_name is not None:
                return True
            if room.minor_module_names:
                return True
        return False

    def _can_research(self, state: GameStatePayload) -> bool:
        """Can we initiate research?"""
        # Need an artifact on the floor
        has_artifact = any(r.has_artifact for r in state.rooms)
        if not has_artifact:
            return False
        # Need researchable blueprints
        if not state.researchable_blueprints:
            return False
        # Need science for at least one blueprint
        if not state.resources:
            return False
        cheapest = min(bp.science_cost for bp in state.researchable_blueprints)
        return state.resources.science >= cheapest

    def _can_recruit(self, state: GameStatePayload) -> bool:
        """Can we recruit at least one hero?"""
        if not state.recruitable_heroes:
            return False
        if not state.resources:
            return False
        # Need food for at least one recruit
        cheapest = min(r.recruit_cost_food for r in state.recruitable_heroes)
        return state.resources.food >= cheapest

    def _can_dismiss(self, state: GameStatePayload) -> bool:
        """Can we dismiss a hero? (Need more than 1 hero.)"""
        return len(state.heroes) > 1

    def _can_level_up(self, state: GameStatePayload) -> bool:
        """Can we level up at least one hero? Hero must not be max level and we must afford it."""
        if not state.resources:
            return False
        if state.resources.food <= 0:
            return False
        if not state.heroes:
            return False
        # A hero can be leveled if level_up_cost > 0 (0 = max level) and we can afford it
        return any(
            h.level_up_cost > 0 and state.resources.food >= h.level_up_cost
            for h in state.heroes
        )

    def _can_buy_item(self, state: GameStatePayload) -> bool:
        """Can we buy from at least one merchant?"""
        if not state.merchants:
            return False
        if not state.resources:
            return False
        # Check if we can afford at least one item
        for merchant in state.merchants:
            for item in merchant.items:
                if merchant.currency_type == "Dust" and state.resources.dust >= item.cost:
                    return True
                elif merchant.currency_type == "Food" and state.resources.food >= item.cost:
                    return True
                elif merchant.currency_type == "Industry" and state.resources.industry >= item.cost:
                    return True
                elif merchant.currency_type == "Science" and state.resources.science >= item.cost:
                    return True
        return False

    def _can_equip_item(self, state: GameStatePayload) -> bool:
        """Can we equip at least one item from inventory?"""
        has_items = bool(state.backpack_items) or bool(state.shared_inventory_items)
        has_heroes = len(state.heroes) > 0
        return has_items and has_heroes

    def _can_unequip_item(self, state: GameStatePayload) -> bool:
        """Can we unequip at least one item from a hero?"""
        for hero in state.heroes:
            for slot in hero.equipment:
                if slot.item_name is not None:
                    return True
        return False

    def _can_position_hero(self, state: GameStatePayload) -> bool:
        """Can we move at least one hero?"""
        # Need at least one usable hero and at least 2 rooms
        if len(state.rooms) < 2:
            return False
        return any(h.is_usable for h in state.heroes)

    def _can_open_door(self, state: GameStatePayload) -> bool:
        """Can we open at least one closed door?"""
        if not state.closed_doors:
            # Also check rooms that aren't fully opened
            return any(not r.is_fully_opened for r in state.rooms)
        # Need a usable hero to open the door
        return any(h.is_usable for h in state.heroes)

    def _can_heal(self, state: GameStatePayload) -> bool:
        """Can we heal at least one hero?"""
        if not state.resources:
            return False
        if state.resources.food <= 0:
            return False
        # Need at least one hero below max HP
        return any(h.hp < h.max_hp for h in state.heroes)

    def _can_initiate_escape(self, state: GameStatePayload) -> bool:
        """Can we start the escape sequence?"""
        # Exit room must be discovered
        exit_found = any(r.is_exit_room for r in state.rooms)
        if not exit_found:
            return False
        # Can't already be escaping
        if state.is_escaping:
            return False
        # Need at least one usable hero
        return any(h.is_usable for h in state.heroes)

    def _can_collect_item(self, state: GameStatePayload) -> bool:
        """Can we send a hero to collect dropped items?"""
        # Need dropped items on the floor
        if not state.dropped_items:
            return False
        # Need at least one usable hero
        return any(h.is_usable for h in state.heroes)

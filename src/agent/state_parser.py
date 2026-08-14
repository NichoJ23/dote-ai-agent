"""
StateParser: Deserializes raw JSON game state from the C# mod into typed Pydantic models.

Matches the ACTUAL wire format produced by src/mod/Ipc/JsonSerializer.cs.
Uses Pydantic v2 for validation with snake_case field names matching the JSON output.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# --- Enums ---


class GamePhase(str, Enum):
    """Game phase as sent by the mod."""
    STRATEGY = "Strategy"       # Planning phase (doors closed, no enemies spawning)
    ACTION = "Action"           # Wave active (enemies spawning/fighting)
    # Future: game over and escaping states may be added
    # For robustness, we also accept these if the mod evolves:
    TACTICAL_PAUSE = "tactical_pause"
    WAVE_ACTIVE = "wave_active"
    GAME_OVER = "game_over"
    ESCAPING = "escaping"

    @property
    def is_planning(self) -> bool:
        """True if this is a planning/strategy phase (no active combat)."""
        return self in (GamePhase.STRATEGY, GamePhase.TACTICAL_PAUSE)

    @property
    def is_combat(self) -> bool:
        """True if enemies are active."""
        return self in (GamePhase.ACTION, GamePhase.WAVE_ACTIVE)


# --- Sub-models ---


class ResourceState(BaseModel):
    industry: float = 0.0
    food: float = 0.0
    science: float = 0.0
    dust: float = 0.0
    dust_max: float = 0.0
    industry_per_turn: float = 0.0
    food_per_turn: float = 0.0
    science_per_turn: float = 0.0
    dust_per_turn: float = 0.0
    room_power_cost: float = 0.0
    powered_room_count: int = 0


class RoomState(BaseModel):
    index: int
    is_powered: bool = False
    is_auto_powered: bool = False
    is_exit_room: bool = False
    is_start_room: bool = False
    is_fully_opened: bool = False
    depth: int = 0
    suffers_emp: bool = False
    emp_turns_remaining: int = 0
    dust_loot_amount: int = 0
    has_artifact: bool = False
    has_stele: bool = False
    adjacent_room_indices: list[int] = Field(default_factory=list)
    major_module_name: Optional[str] = None
    minor_module_names: list[str] = Field(default_factory=list)
    minor_slot_count: int = 0
    hero_count: int = 0
    mob_count: int = 0
    npc_count: int = 0


class ClosedDoor(BaseModel):
    room1_index: int
    room2_index: int
    is_opening: bool = False


class ActiveSkill(BaseModel):
    name: str
    cooldown_turns: int = 0
    remaining_cooldown: int = 0
    is_activated: bool = False


class PassiveSkill(BaseModel):
    name: str


class EquipmentSlot(BaseModel):
    slot_category: str  # "Weapon", "Armor", "Accessory", or game-specific like "ItemHero#1"
    item_name: Optional[str] = None


class HeroState(BaseModel):
    name: str
    faction: str = ""
    room_index: int = 0
    hp: float = 0.0
    max_hp: float = 1.0
    level: int = 1
    has_crystal: bool = False
    is_operating: bool = False
    operating_module_name: Optional[str] = None
    is_gathering_item: bool = False  # Hero is mid-pickup animation; moving cancels it
    is_recruitable: bool = False
    is_recruited: bool = True

    # Combat stats (computed from equipment, level, passives)
    attack: float = 0.0           # AttackPower
    defense: float = 0.0          # Defense
    speed: float = 0.0            # MoveSpeed
    wit: float = 0.0              # Wit (module operation effectiveness)
    attack_cooldown: float = 0.0  # Time between attacks

    active_skills: list[ActiveSkill] = Field(default_factory=list)
    passive_skills: list[PassiveSkill] = Field(default_factory=list)
    equipment: list[EquipmentSlot] = Field(default_factory=list)


class MobState(BaseModel):
    type: str = ""
    room_index: int = 0
    hp: float = 0.0
    max_hp: float = 1.0
    target_type: str = ""  # "AntiHeroMob", "AntiModuleMob", "Artifact", "Crystal", etc.


class MerchantItem(BaseModel):
    name: str
    rarity: str = ""
    cost: float = 0.0


class MerchantState(BaseModel):
    room_index: int = 0
    currency_type: str = "Dust"  # "Dust", "Food", "Industry", "Science"
    items: list[MerchantItem] = Field(default_factory=list)


class RecruitableHero(BaseModel):
    name: str
    faction: str = ""
    room_index: int = 0
    hp: float = 0.0
    max_hp: float = 1.0
    recruit_cost_food: float = 0.0
    passive_skill_names: list[str] = Field(default_factory=list)


class DroppedItem(BaseModel):
    type: str  # "Dust", "Equipment", "Chest"
    name: Optional[str] = None
    room_index: int = 0
    dust_amount: float = 0.0


class BackpackItem(BaseModel):
    name: str
    rarity: str = ""
    category: str = ""  # Slot category this item fits


class ResearchBlueprint(BaseModel):
    name: str
    science_cost: float = 0.0


class BuildableBlueprint(BaseModel):
    """An unlocked module blueprint that can be built."""
    name: str                     # Blueprint name (e.g., "MajorModule_Major0002_LVL1")
    module_name: str = ""         # Module config name (e.g., "Major0002")
    category: str = ""            # "MajorModule", "MinorModule_Support", "MinorModule_Offense", "MinorModule_Debuff"
    level: int = 1                # Module level tier
    industry_cost: float = 0.0    # Current industry cost to build


# --- Top-level payload ---


class GameStatePayload(BaseModel):
    """
    Full game state payload matching the actual C# JsonSerializer output.
    """

    turn: int = 0
    floor: int = 1
    game_phase: GamePhase = GamePhase.STRATEGY
    crystal_state: str = "Plugged"  # "Plugged", "Unplugged", "PluggedOnExitSlot"
    exit_room_index: int = -1
    start_room_index: int = 0
    resources: Optional[ResourceState] = None
    rooms: list[RoomState] = Field(default_factory=list)
    closed_doors: list[ClosedDoor] = Field(default_factory=list)
    heroes: list[HeroState] = Field(default_factory=list)
    mobs: list[MobState] = Field(default_factory=list)
    merchants: list[MerchantState] = Field(default_factory=list)
    recruitable_heroes: list[RecruitableHero] = Field(default_factory=list)
    dropped_items: list[DroppedItem] = Field(default_factory=list)
    backpack_items: list[BackpackItem] = Field(default_factory=list)
    shared_inventory_items: list[BackpackItem] = Field(default_factory=list)
    researchable_blueprints: list[ResearchBlueprint] = Field(default_factory=list)
    buildable_blueprints: list[BuildableBlueprint] = Field(default_factory=list)
    time_scale: float = 1.0

    @field_validator("researchable_blueprints", mode="before")
    @classmethod
    def _coerce_blueprints(cls, v):
        """Accept both plain strings and {name, science_cost} dicts."""
        if not isinstance(v, list):
            return v
        result = []
        for item in v:
            if isinstance(item, str):
                result.append({"name": item, "science_cost": 0.0})
            else:
                result.append(item)
        return result

    # --- Convenience properties ---

    @property
    def crystal_room_index(self) -> int:
        """Find the room containing the crystal (start room)."""
        return self.start_room_index

    @property
    def is_crystal_safe(self) -> bool:
        """True if crystal is still plugged."""
        return self.crystal_state in ("Plugged", "PluggedOnExitSlot")

    @property
    def is_game_over(self) -> bool:
        """True if crystal is destroyed (unplugged and no hero carrying it)."""
        if self.crystal_state != "Unplugged":
            return False
        # If a hero is carrying it, it's not game over — just in transit
        return not any(h.has_crystal for h in self.heroes)

    @property
    def is_escaping(self) -> bool:
        """True if crystal is on the exit slot."""
        return self.crystal_state == "PluggedOnExitSlot"


# --- Parser class ---


class StateParser:
    """
    Parses raw JSON dicts (from IPC) into validated GameStatePayload instances.

    Usage:
        parser = StateParser()
        state = parser.parse(raw_json_dict)
    """

    def parse(self, raw: dict) -> GameStatePayload:
        """
        Parse and validate a raw JSON dict into a GameStatePayload.

        Args:
            raw: Dict decoded from the JSON wire format (from IpcClient.receive_state()).

        Returns:
            Validated GameStatePayload instance.

        Raises:
            pydantic.ValidationError: If the payload doesn't match the expected schema.
        """
        return GameStatePayload.model_validate(raw)

    def parse_lenient(self, raw: dict) -> GameStatePayload:
        """
        Parse with lenient handling: unknown fields are ignored,
        missing optional fields get defaults.

        Useful during development when the mod may send extra/experimental fields.
        """
        return GameStatePayload.model_validate(raw, strict=False)

# Design: Autonomous AI Agent for Dungeon of the ENDLESS

#[[file:master-plan.md]]
#[[file:requirements.md]]

---

## 1. System Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                  GAME PROCESS (Unity Mono)                       │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              BepInEx Plugin (DotEAgentMod)                 │  │
│  │                                                           │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  │  │
│  │  │ StateExtractor│  │ActionInjector│  │  IpcBridge       │  │  │
│  │  │ (IStateHook) │  │(IActionHook)│  │  (TCP Sockets)   │  │  │
│  │  └──────┬───────┘  └──────▲──────┘  └───────┬──────────┘  │  │
│  │         │                  │                  │             │  │
│  │         │    Hooks into Assembly-CSharp.dll   │             │  │
│  │  ┌──────▼──────────────────┴──────────────────▼──────────┐  │  │
│  │  │  DungeonHook │ HeroHook │ MobHook │ ResourceHook      │  │  │
│  │  │  MerchantHook │ RecruitHook │ ItemHook                │  │  │
│  │  └────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└──────────────────────────────────┬──────────────────────────────┘
                                   │ TCP (localhost)
                          Port 5555│(State)
                          Port 5556│(Actions)
┌──────────────────────────────────▼──────────────────────────────┐
│                     PYTHON AI AGENT ENGINE                        │
│                                                                  │
│  ┌────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │
│  │  IpcClient     │  │  DotEEnv         │  │  AgentController │  │
│  │  (TCP socket)  │──▶│  (gymnasium.Env) │──▶│  (FSM / Policy) │  │
│  └────────────────┘  └──────────────────┘  └─────────────────┘  │
│                              │                       │            │
│                       ┌──────▼──────┐         ┌──────▼──────┐    │
│                       │  GraphState │         │ MacroPlanner │    │
│                       │  (NetworkX) │         │ MicroControl │    │
│                       └─────────────┘         │ EscapePlanner│    │
│                                               └─────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. C# Interface Definitions

### 2.1 Core Plugin Interfaces

```csharp
namespace DotEAgent.Core
{
    /// <summary>
    /// Marker interface for all game state hook components.
    /// Each hook is responsible for extracting state from one game subsystem.
    /// </summary>
    public interface IStateHook
    {
        /// <summary>Unique identifier for this hook (e.g., "dungeon", "hero").</summary>
        string HookId { get; }

        /// <summary>Whether this hook has been successfully bound to game internals.</summary>
        bool IsBound { get; }

        /// <summary>Binds to in-memory game objects via reflection. Called once on plugin load.</summary>
        void Bind();

        /// <summary>Extracts current state as a serializable data object.</summary>
        object ExtractState();
    }

    /// <summary>
    /// Processes incoming action commands and executes them against game internals.
    /// </summary>
    public interface IActionHandler
    {
        /// <summary>The command verb this handler responds to (e.g., "MOVE_HERO").</summary>
        string CommandType { get; }

        /// <summary>
        /// Validates preconditions (e.g., hero in correct room for door open).
        /// Returns null if valid, or an error string if invalid.
        /// </summary>
        string ValidatePreconditions(ActionCommand command);

        /// <summary>Validates and executes the action. Returns success/failure result.</summary>
        ActionResult Execute(ActionCommand command);
    }

    /// <summary>
    /// Result of an action execution attempt.
    /// </summary>
    public class ActionResult
    {
        public bool Success { get; set; }
        public string Error { get; set; }
        public Dictionary<string, object> Metadata { get; set; }
    }

    /// <summary>
    /// Deserialized action command received from the Python agent.
    /// </summary>
    public class ActionCommand
    {
        public string Command { get; set; }
        public Dictionary<string, object> Parameters { get; set; }
        public long Timestamp { get; set; }
    }
}
```

### 2.2 State Hook Implementations

```csharp
namespace DotEAgent.Hooks
{
    /// <summary>
    /// Extracts dungeon-level state: room graph, power states, crystal location, door open/closed edges.
    /// </summary>
    public interface IDungeonHook : IStateHook
    {
        DungeonState GetDungeonState();
    }

    /// <summary>
    /// Extracts hero states: HP, position, abilities, passives, faction, equipment, speed.
    /// </summary>
    public interface IHeroHook : IStateHook
    {
        List<HeroState> GetHeroStates();
    }

    /// <summary>
    /// Extracts mob states: HP, position, target, attack cooldowns.
    /// </summary>
    public interface IMobHook : IStateHook
    {
        List<MobState> GetMobStates();
    }

    /// <summary>
    /// Extracts global resource balances and production rates.
    /// </summary>
    public interface IResourceHook : IStateHook
    {
        ResourceState GetResourceState();
    }

    /// <summary>
    /// Extracts available merchants on the floor and their inventory.
    /// </summary>
    public interface IMerchantHook : IStateHook
    {
        List<MerchantState> GetMerchantStates();
    }

    /// <summary>
    /// Extracts heroes available for recruitment on the floor.
    /// </summary>
    public interface IRecruitHook : IStateHook
    {
        List<RecruitableHero> GetRecruitableHeroes();
    }

    /// <summary>
    /// Extracts dropped items (dust piles, equipment) on the floor.
    /// </summary>
    public interface IItemHook : IStateHook
    {
        List<DroppedItem> GetDroppedItems();
    }
}
```

### 2.3 IPC Bridge Interface

```csharp
namespace DotEAgent.Ipc
{
    /// <summary>
    /// Manages raw TCP socket lifecycle and message routing.
    /// Uses length-prefixed framing: [4-byte big-endian length][UTF-8 JSON payload].
    /// </summary>
    public interface IIpcBridge : IDisposable
    {
        /// <summary>Starts TCP listener on port 5555 (state) and port 5556 (actions).</summary>
        void Start();

        /// <summary>Sends serialized game state to the connected Python client on port 5555.</summary>
        void SendState(GameStatePayload state);

        /// <summary>Polls for incoming action commands on port 5556 (non-blocking).</summary>
        ActionCommand PollAction(int timeoutMs);

        /// <summary>Sends an action result response back to the Python agent on port 5556.</summary>
        void SendResponse(ActionResult result);

        /// <summary>Current connection status.</summary>
        bool IsConnected { get; }
    }
}
```

### 2.4 State Data Models

```csharp
namespace DotEAgent.Models
{
    public class GameStatePayload
    {
        public int Turn { get; set; }
        public string GamePhase { get; set; }  // "tactical_pause" | "wave_active" | "game_over" | "escaping"
        public ResourceState Resources { get; set; }
        public List<RoomState> Rooms { get; set; }
        public List<HeroState> Heroes { get; set; }
        public List<MobState> Mobs { get; set; }
        public List<MerchantState> Merchants { get; set; }
        public List<RecruitableHero> RecruitableHeroes { get; set; }
        public List<DroppedItem> DroppedItems { get; set; }
        public int ExitRoomId { get; set; }
        public PayloadMetadata Meta { get; set; }
    }

    public class ResourceState
    {
        public int Industry { get; set; }
        public int Food { get; set; }
        public int Science { get; set; }
        public int Dust { get; set; }
        public int DustMax { get; set; }
        public int IndustryPerTurn { get; set; }
        public int FoodPerTurn { get; set; }
        public int SciencePerTurn { get; set; }
    }

    public class RoomState
    {
        public int Id { get; set; }
        public bool Powered { get; set; }
        public bool AutoPowered { get; set; }       // Cannot be unpowered (e.g., crystal room)
        public bool HasCrystal { get; set; }
        public bool IsExplored { get; set; }
        public bool IsExitRoom { get; set; }
        public List<DoorState> Doors { get; set; }  // Per-door open/closed status
        public List<string> InstalledModules { get; set; }
        public List<string> DamagedModules { get; set; }
        public int MajorSlots { get; set; }
        public int MinorSlots { get; set; }
        public int MajorSlotsUsed { get; set; }
        public int MinorSlotsUsed { get; set; }
    }

    public class DoorState
    {
        public int TargetRoomId { get; set; }
        public bool IsOpen { get; set; }
    }

    public class HeroState
    {
        public string Id { get; set; }
        public string Name { get; set; }
        public string Faction { get; set; }         // Relevant for faction-based passive synergies
        public int RoomId { get; set; }
        public float Hp { get; set; }
        public float MaxHp { get; set; }
        public float Attack { get; set; }
        public float Defense { get; set; }
        public float Speed { get; set; }
        public int Level { get; set; }
        public int LevelUpCost { get; set; }        // Food cost to level up
        public List<AbilityState> Abilities { get; set; }
        public List<PassiveAbility> Passives { get; set; }
        public List<EquipmentSlot> Equipment { get; set; }
        public bool IsOperating { get; set; }       // Currently operating a module
        public bool IsCarryingCrystal { get; set; }
    }

    public class PassiveAbility
    {
        public string Name { get; set; }            // e.g., "Operate", "Repair", "Fast"
        public string Description { get; set; }
        public bool IsUnlocked { get; set; }        // Some passives unlock at higher levels
        public int UnlockLevel { get; set; }
    }

    public class AbilityState
    {
        public string Name { get; set; }
        public bool IsUnlocked { get; set; }        // Unlocked via leveling
        public bool IsReady { get; set; }
        public float Cooldown { get; set; }
        public int UnlockLevel { get; set; }
    }

    public class EquipmentSlot
    {
        public string SlotType { get; set; }        // "weapon" | "armor" | "accessory"
        public string ItemId { get; set; }          // null if empty
        public string ItemName { get; set; }
    }

    public class MobState
    {
        public string Id { get; set; }
        public string Type { get; set; }
        public int RoomId { get; set; }
        public float Hp { get; set; }
        public float MaxHp { get; set; }
        public float AttackCooldown { get; set; }
    }

    public class MerchantState
    {
        public string Id { get; set; }
        public int RoomId { get; set; }
        public List<MerchantItem> Inventory { get; set; }
    }

    public class MerchantItem
    {
        public string ItemId { get; set; }
        public string ItemName { get; set; }
        public string SlotType { get; set; }
        public int CostDust { get; set; }
        public Dictionary<string, float> Stats { get; set; }
    }

    public class RecruitableHero
    {
        public string Id { get; set; }
        public string Name { get; set; }
        public string Faction { get; set; }
        public int RoomId { get; set; }
        public int RecruitCostFood { get; set; }
        public List<PassiveAbility> Passives { get; set; }
        public float BaseAttack { get; set; }
        public float BaseDefense { get; set; }
        public float BaseSpeed { get; set; }
    }

    public class DroppedItem
    {
        public string Id { get; set; }
        public string Type { get; set; }            // "dust" | "equipment"
        public int RoomId { get; set; }
        public int DustAmount { get; set; }         // Only for dust type
        public string ItemName { get; set; }        // Only for equipment type
        public string SlotType { get; set; }        // Only for equipment type
    }

    public class PayloadMetadata
    {
        public long TimestampMs { get; set; }
        public int SequenceNumber { get; set; }
        public List<string> Warnings { get; set; }  // Null-ref substitutions flagged here
    }
}
```

---

## 3. JSON Payload Schemas

### 3.1 Game State Observation (C# → Python, Port 5555)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "GameStatePayload",
  "type": "object",
  "required": ["turn", "game_phase", "resources", "rooms", "heroes", "mobs", "merchants", "recruitable_heroes", "dropped_items", "exit_room_id", "meta"],
  "properties": {
    "turn": {
      "type": "integer",
      "minimum": 0
    },
    "game_phase": {
      "type": "string",
      "enum": ["tactical_pause", "wave_active", "game_over", "escaping"]
    },
    "exit_room_id": {
      "type": "integer",
      "description": "Room ID of the floor exit"
    },
    "resources": {
      "type": "object",
      "required": ["industry", "food", "science", "dust", "dust_max"],
      "properties": {
        "industry": { "type": "integer", "minimum": 0 },
        "food": { "type": "integer", "minimum": 0 },
        "science": { "type": "integer", "minimum": 0 },
        "dust": { "type": "integer", "minimum": 0 },
        "dust_max": { "type": "integer", "minimum": 0 },
        "industry_per_turn": { "type": "integer" },
        "food_per_turn": { "type": "integer" },
        "science_per_turn": { "type": "integer" }
      }
    },
    "rooms": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "powered", "auto_powered", "has_crystal", "is_explored", "is_exit_room", "doors"],
        "properties": {
          "id": { "type": "integer" },
          "powered": { "type": "boolean" },
          "auto_powered": { "type": "boolean", "description": "True if room cannot be unpowered" },
          "has_crystal": { "type": "boolean" },
          "is_explored": { "type": "boolean" },
          "is_exit_room": { "type": "boolean" },
          "doors": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["target_room_id", "is_open"],
              "properties": {
                "target_room_id": { "type": "integer" },
                "is_open": { "type": "boolean" }
              }
            },
            "description": "Each door connecting this room to another, with open/closed status"
          },
          "installed_modules": { "type": "array", "items": { "type": "string" } },
          "damaged_modules": { "type": "array", "items": { "type": "string" } },
          "major_slots": { "type": "integer", "minimum": 0 },
          "minor_slots": { "type": "integer", "minimum": 0 },
          "major_slots_used": { "type": "integer", "minimum": 0 },
          "minor_slots_used": { "type": "integer", "minimum": 0 }
        }
      }
    },
    "heroes": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "name", "faction", "room_id", "hp", "max_hp", "speed", "level", "abilities", "passives", "equipment"],
        "properties": {
          "id": { "type": "string" },
          "name": { "type": "string" },
          "faction": { "type": "string", "description": "Hero faction for passive synergies" },
          "room_id": { "type": "integer" },
          "hp": { "type": "number", "minimum": 0 },
          "max_hp": { "type": "number", "minimum": 1 },
          "attack": { "type": "number" },
          "defense": { "type": "number" },
          "speed": { "type": "number", "description": "Movement speed; used to pick crystal carrier" },
          "level": { "type": "integer", "minimum": 1 },
          "level_up_cost": { "type": "integer", "minimum": 0 },
          "abilities": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["name", "is_unlocked", "is_ready", "cooldown"],
              "properties": {
                "name": { "type": "string" },
                "is_unlocked": { "type": "boolean" },
                "is_ready": { "type": "boolean" },
                "cooldown": { "type": "number", "minimum": 0 },
                "unlock_level": { "type": "integer" }
              }
            },
            "description": "Heroes have up to 2 active abilities, unlocked via leveling"
          },
          "passives": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["name", "is_unlocked"],
              "properties": {
                "name": { "type": "string" },
                "description": { "type": "string" },
                "is_unlocked": { "type": "boolean" },
                "unlock_level": { "type": "integer" }
              }
            }
          },
          "equipment": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["slot_type"],
              "properties": {
                "slot_type": { "type": "string", "enum": ["weapon", "armor", "accessory"] },
                "item_id": { "type": ["string", "null"] },
                "item_name": { "type": ["string", "null"] }
              }
            }
          },
          "is_operating": { "type": "boolean", "description": "Hero is operating a module (moving cancels this)" },
          "is_carrying_crystal": { "type": "boolean" }
        }
      }
    },
    "mobs": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "type", "room_id", "hp", "max_hp"],
        "properties": {
          "id": { "type": "string" },
          "type": { "type": "string" },
          "room_id": { "type": "integer" },
          "hp": { "type": "number", "minimum": 0 },
          "max_hp": { "type": "number", "minimum": 1 },
          "attack_cooldown": { "type": "number", "minimum": 0 }
        }
      }
    },
    "merchants": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "room_id", "inventory"],
        "properties": {
          "id": { "type": "string" },
          "room_id": { "type": "integer" },
          "inventory": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["item_id", "item_name", "cost_dust"],
              "properties": {
                "item_id": { "type": "string" },
                "item_name": { "type": "string" },
                "slot_type": { "type": "string" },
                "cost_dust": { "type": "integer", "minimum": 0 },
                "stats": { "type": "object", "additionalProperties": { "type": "number" } }
              }
            }
          }
        }
      }
    },
    "recruitable_heroes": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "name", "faction", "room_id", "recruit_cost_food"],
        "properties": {
          "id": { "type": "string" },
          "name": { "type": "string" },
          "faction": { "type": "string" },
          "room_id": { "type": "integer" },
          "recruit_cost_food": { "type": "integer" },
          "passives": { "type": "array", "items": { "$ref": "#/properties/heroes/items/properties/passives/items" } },
          "base_attack": { "type": "number" },
          "base_defense": { "type": "number" },
          "base_speed": { "type": "number" }
        }
      }
    },
    "dropped_items": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "type", "room_id"],
        "properties": {
          "id": { "type": "string" },
          "type": { "type": "string", "enum": ["dust", "equipment"] },
          "room_id": { "type": "integer" },
          "dust_amount": { "type": "integer", "minimum": 0 },
          "item_name": { "type": ["string", "null"] },
          "slot_type": { "type": ["string", "null"] }
        }
      }
    },
    "meta": {
      "type": "object",
      "required": ["timestamp_ms", "sequence_number"],
      "properties": {
        "timestamp_ms": { "type": "integer" },
        "sequence_number": { "type": "integer", "minimum": 0 },
        "warnings": { "type": "array", "items": { "type": "string" } }
      }
    }
  }
}
```

### 3.2 Action Command (Python → C#, Port 5556)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ActionCommand",
  "type": "object",
  "required": ["command", "parameters"],
  "properties": {
    "command": {
      "type": "string",
      "enum": [
        "MOVE_HERO",
        "OPEN_DOOR",
        "BUILD_MODULE",
        "SELL_MODULE",
        "REPAIR_MODULE",
        "POWER_ROOM",
        "UNPOWER_ROOM",
        "USE_ABILITY",
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
        "UNPAUSE_GAME"
      ]
    },
    "parameters": {
      "type": "object"
    },
    "timestamp": {
      "type": "integer"
    }
  }
}
```

### 3.3 Action Command Parameter Schemas

#### MOVE_HERO
```json
{ "hero_id": "string (required)", "target_room_id": "integer (required)" }
```

#### OPEN_DOOR
Hero must be in `from_room_id` to open the door (REQ-U7, REQ-W4).
```json
{ "hero_id": "string (required)", "from_room_id": "integer (required)", "target_room_id": "integer (required)" }
```

#### BUILD_MODULE
```json
{ "room_id": "integer (required)", "module_name": "string (required)", "slot_type": "'major' | 'minor' (required)" }
```

#### REPAIR_MODULE
```json
{ "hero_id": "string (required)", "room_id": "integer (required)", "module_name": "string (required)" }
```

#### POWER_ROOM / UNPOWER_ROOM
Cannot unpower auto-powered rooms.
```json
{ "room_id": "integer (required)" }
```

#### USE_ABILITY
```json
{ "hero_id": "string (required)", "target_id": "string (optional)" }
```

#### HEAL_HERO
```json
{ "hero_id": "string (required)", "food_amount": "integer (required)" }
```

#### LEVEL_UP_HERO
```json
{ "hero_id": "string (required)" }
```

#### RECRUIT_HERO
Hero performing recruitment must be in the same room as the recruitable hero.
```json
{ "recruiter_hero_id": "string (required)", "recruit_id": "string (required)" }
```

#### BUY_FROM_MERCHANT
Hero must be in the merchant's room.
```json
{ "hero_id": "string (required)", "merchant_id": "string (required)", "item_id": "string (required)" }
```

#### SELL_TO_MERCHANT
Hero must be in the merchant's room. Sells from backpack or shared inventory.
```json
{ "hero_id": "string (required)", "merchant_id": "string (required)", "item_id": "string (required)" }
```

#### EQUIP_ITEM
```json
{ "hero_id": "string (required)", "item_id": "string (required)", "slot_type": "'weapon' | 'armor' | 'accessory' (required)" }
```

#### UNEQUIP_ITEM
```json
{ "hero_id": "string (required)", "slot_type": "'weapon' | 'armor' | 'accessory' (required)" }
```

#### COLLECT_ITEM
Hero must be in the item's room.
```json
{ "hero_id": "string (required)", "item_id": "string (required)" }
```

#### PICK_UP_CRYSTAL
Hero must be in the crystal room.
```json
{ "hero_id": "string (required)" }
```

#### RESEARCH
```json
{ "research_id": "string (required)" }
```

#### MOVE_TO_BACKPACK
Moves an item from shared inventory to backpack (persists between floors). Fails if backpack is full (4 slots).
```json
{ "item_id": "string (required)" }
```

#### MOVE_TO_SHARED_INVENTORY
Moves an item from backpack to shared inventory (frees a backpack slot; item will be lost on floor exit if not equipped).
```json
{ "item_id": "string (required)" }
```

#### INTERACT_ROOM_ITEM
Hero must be in the item's room. Triggers a room interactable (chest, machine, etc.).
```json
{ "hero_id": "string (required)", "item_id": "string (required)" }
```

### 3.4 Action Result Response (C# → Python, Port 5556 REP)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ActionResult",
  "type": "object",
  "required": ["success"],
  "properties": {
    "success": { "type": "boolean" },
    "error": {
      "type": ["string", "null"],
      "description": "Human-readable error if success=false (e.g., 'Hero not in source room for door open')"
    },
    "metadata": {
      "type": "object",
      "description": "Additional context (e.g., resulting hero position after move)"
    }
  }
}
```

---

## 4. Python Component Design

### 4.1 Gymnasium Environment (`DotEEnv`)

```python
class DotEEnv(gymnasium.Env):
    """
    Gymnasium-compatible environment wrapping Dungeon of the ENDLESS
    via ZeroMQ IPC to the BepInEx mod.
    """

    metadata = {"render_modes": ["human", "json"]}

    # Observation space: Dict space with graph + resource vector + hero/mob features
    observation_space: spaces.Dict

    # Action space: Dict with command type + parameters
    action_space: spaces.Dict

    def __init__(self, host="localhost", state_port=5555, action_port=5556, config_path=None): ...
    def reset(self, seed=None, options=None) -> tuple[dict, dict]: ...
    def step(self, action) -> tuple[dict, float, bool, bool, dict]: ...
    def close(self) -> None: ...
    def _compute_reward(self, prev_state: dict, curr_state: dict) -> float: ...
    def _build_observation(self, raw_state: dict) -> dict: ...
```

### 4.2 Reward Function

```
Reward = +10 * (ΔRooms Explored)
       +  5 * (ΔDust Gained)
       -  0.1 * (ΔHero HP Lost across all heroes)  // Low penalty; heroes heal to full after combat
       - 100 * (Crystal Destroyed flag)
       +  2 * (ΔModules Built)
       +  1 * (ΔMobs Killed)
       + 50 * (Floor Escaped successfully)
       - 20 * (Hero Died)                          // Much heavier than taking damage
```

### 4.3 Agent Controller Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto

class AgentPhase(Enum):
    EXPLORE = auto()
    BUILD = auto()
    DEFEND = auto()
    RETREAT = auto()
    ESCAPE = auto()


@dataclass
class GuidelinesConfig:
    """Removable learning guidelines (GL-1 through GL-6)."""
    retreat_hp_threshold: float = 0.30
    preferred_starting_heroes: list[str] = None  # ["Max O'Kane", "Gork"]
    prioritize_max_operate_unlock: bool = True
    protect_operators: bool = True
    fastest_hero_carries_crystal: bool = True
    repower_escape_path: bool = True

    def __post_init__(self):
        if self.preferred_starting_heroes is None:
            self.preferred_starting_heroes = ["Max O'Kane", "Gork"]


class BaseAgent(ABC):
    """Abstract base for all agent controllers."""

    def __init__(self, guidelines: GuidelinesConfig | None = None):
        self.guidelines = guidelines or GuidelinesConfig()

    @abstractmethod
    def select_action(self, observation: dict, phase: str) -> dict:
        """Given current observation and game phase, return an ActionCommand dict."""
        ...

    @abstractmethod
    def reset(self) -> None:
        """Reset internal state for a new episode."""
        ...


class HeuristicAgent(BaseAgent):
    """
    Phase 4 baseline: finite-state machine with rule-based macro + micro logic.

    Macro-Planner responsibilities (tactical_pause):
      - Build/repair modules (prioritize Industry → Food → Defense)
      - Queue research
      - Level up heroes (prioritize Max → Operate unlock per GL-4)
      - Evaluate merchants and buy beneficial items
      - Recruit heroes when food allows
      - Equip items optimally per hero role
      - Dispatch heroes to collect dropped dust
      - Place operators in safe rooms (GL-3)
      - Decide when to open next door (explore)
      - Initiate escape when no doors remain (REQ-E6)

    Micro-Controller responsibilities (wave_active):
      - Position heroes in bottleneck rooms to block spawns
      - Retreat heroes below HP threshold (GL-1)
      - Heroes auto-target closest enemy (REQ-U6) — no focus-fire needed

    Escape-Planner responsibilities (escaping):
      - Assign crystal to fastest hero (GL-5)
      - Reorganize power for escape path safety (GL-6)
      - Crystal carrier runs straight to exit
      - Other heroes: guard carrier, block spawns, or wait at exit
    """

    def select_action(self, observation: dict, phase: str) -> dict: ...
    def reset(self) -> None: ...
```

---

## 5. Technology Decisions & Constraints

| Decision | Rationale |
|----------|-----------|
| Raw TCP sockets (length-prefixed JSON) | .NET 3.5 compatible; no external dependencies; simple for turn-based request/response; NetMQ requires .NET 4.x+ |
| JSON with manual/SimpleJSON serialization | Human-readable for debugging; .NET 3.5 has no built-in JSON (no Newtonsoft without nuget); lightweight embedded parser |
| NetworkX for graph state | Mature library with centrality, shortest-path, and connectivity algorithms built-in |
| BepInEx (sc2ad patched build) | Only BepInEx variant that works with Unity 5.0.3; standard releases crash on this Mono version |
| Gymnasium API | Industry standard for RL environments; compatible with SB3, RLlib, CleanRL |
| Hierarchical FSM before RL | Establishes a working baseline without training infrastructure; validates IPC correctness |
| Per-door state tracking | Supports loops in room graph where all rooms explored but doors still closed |
| GuidelinesConfig dataclass | Externalizes heuristic rules for easy toggle/removal in later phases |
| .NET 3.5 target framework | Unity 5.0.3 embeds Mono 2.x which only supports .NET 2.0/3.5 class libraries |

---

## 6. Error Handling Strategy

| Scenario | C# Behavior | Python Behavior |
|----------|-------------|-----------------|
| Python not connected | Retry TCP accept every 2s; log warning; game continues | N/A |
| Python timeout (>5s) | Pause game; log error | Raise `TimeoutError`; attempt reconnect |
| Malformed action JSON | Return `ActionResult{success=false, error="..."}` | Log warning; retry with corrected format |
| Hero not in room for door/merchant/recruit | Return `ActionResult{success=false, error="Hero must be in room X"}` | Agent re-plans with corrected hero dispatch |
| Attempt to unpower auto-powered room | Return `ActionResult{success=false, error="Room is auto-powered"}` | Skip room in power reallocation |
| Null reference in extraction | Substitute default; add to `meta.warnings` | Flag in observation metadata |
| Game crash/exit | Dispose sockets gracefully in `OnDestroy()` | Detect socket disconnect; call `env.close()` |
| TCP frame corruption | Discard buffer; reset connection | Re-connect and re-sync |

---

## 7. Key Game Mechanics (Design Constraints)

| Mechanic | Implication for Agent |
|----------|----------------------|
| Heroes auto-target closest enemy | No focus-fire commands; positioning IS the tactical lever |
| Door opening requires hero presence | Agent must plan hero movement before exploration |
| Rooms can form loops | Door state (open/closed) tracked per-edge, not just room explored flag |
| Auto-powered rooms cannot be unpowered | Power reallocation must skip these; schema flags them |
| Operating a module is cancelled by moving | Operator heroes should not be moved unless necessary |
| Crystal carrier cannot fight | Escape route must be pre-cleared or guarded |
| Factions affect passive synergies | Equipment/placement decisions factor faction alignment |
| Items are auto-collected | Heroes don't interact with items; standing in room auto-picks up after short delay. COLLECT_ITEM action = MOVE_HERO to item's room |
| Repair requires passive skill | Only heroes with "Repair" passive (or item granting it) can repair. Hero must be in the room with damaged modules — repairs happen automatically. Creates operate-vs-repair tradeoff when only operator heroes have Repair |


---

## 8. Implementation Deviations & Discoveries (Phases 2–3.5)

This section documents deviations from the original design discovered during implementation.

### 8.1 Actual Wire Format (differs from Section 3 schemas)

The C# `JsonSerializer` produces snake_case JSON with these key differences from the original design:

**Top-level payload:**
| Original Design | Actual Wire Format | Notes |
|---|---|---|
| `game_phase`: "tactical_pause" / "wave_active" | `game_phase`: "Strategy" / "Action" | Game's internal names |
| `exit_room_id` | `exit_room_index` | |
| `meta` object | Not present | No metadata envelope |
| — | `floor` (int) | Floor number added |
| — | `crystal_state` ("Plugged"/"Unplugged"/"PluggedOnExitSlot") | Crystal status |
| — | `start_room_index` | Crystal room |
| — | `closed_doors` (separate list) | Not embedded per-room |
| — | `backpack_items` / `shared_inventory_items` | Inventory tracking |
| — | `researchable_blueprints` | Available research options |
| `resources` always present | `resources` can be `null` | Null during startup |

**Rooms:**
| Original | Actual | Notes |
|---|---|---|
| `id` | `index` | |
| `powered` | `is_powered` | |
| `auto_powered` | `is_auto_powered` | |
| `has_crystal` | — (use `start_room_index`) | Crystal tracked at top level |
| `is_explored` | — (room exists in list = explored) | Only opened rooms are sent |
| `doors` (per-room list) | `adjacent_room_indices` + top-level `closed_doors` | Door state is separate |
| `installed_modules` / `damaged_modules` | `major_module_name` + `minor_module_names` | 1 major slot, N minor slots |
| `major_slots` / `minor_slots` | `minor_slot_count` (major is always 0 or 1) | |
| — | `depth`, `suffers_emp`, `emp_turns_remaining` | Added for strategy |
| — | `has_artifact`, `has_stele` | Added for defense decisions |
| — | `hero_count`, `mob_count`, `npc_count` | Embedded counts |
| — | `dust_loot_amount` | Uncollected dust in room |
| — | `is_fully_opened` | All doors from this room opened |

**Heroes:**
| Original | Actual | Notes |
|---|---|---|
| `id` (unique string) | — (use `name` as identifier) | Heroes identified by name |
| `room_id` | `room_index` | |
| `hp`, `max_hp`, `attack`, `defense`, `speed` | `hp`, `max_hp`, `attack`, `defense`, `speed`, `wit`, `attack_cooldown` | Full combat stats from SimulationProperties |
| `abilities` (with cooldown/unlock) | `active_skills` [{name, skill_level, unlock_level, cooldown_turns, remaining_cooldown, is_activated}] | Includes tier and unlock info |
| `passives` (with unlock status) | `passive_skills` [{name, skill_level, unlock_level}] | Includes tier and level at which it was unlocked |
| `equipment` [{slot_type, item_id, item_name}] | `equipment` [{slot_category, item_name, weapon_type, attack_type}] | Weapon classification on items |
| `is_carrying_crystal` | `has_crystal` | |
| — | `weapon_class` | Hero's innate attack type from HeroConfig.AttackType |
| — | `skill_tree` [{skill_name, base_name, is_active, skill_level, unlock_hero_level, is_unlocked}] | Full skill progression tree |
| — | `operating_module_name` | Which module being operated |
| — | `is_recruitable`, `is_recruited` | Recruitment state |

**Mobs:**
| Original | Actual | Notes |
|---|---|---|
| `id` | — (no unique ID) | |
| `room_id` | `room_index` | |
| `attack_cooldown` | — | Not exposed |
| — | `target_type` | "AntiHeroMob", "AntiModuleMob", "Crystal", "Artifact" |

**Merchants:**
| Original | Actual | Notes |
|---|---|---|
| `id` | — | |
| `room_id` | `room_index` | |
| `inventory` [{item_id, item_name, slot_type, cost_dust, stats}] | `items` [{name, rarity, cost, category, weapon_type, attack_type}] + `currency_type` | Includes weapon classification |

**Recruitable Heroes:**
| Original | Actual | Notes |
|---|---|---|
| Full hero stats + passives objects | `name`, `faction`, `weapon_class`, `room_index`, `hp`, `max_hp`, `recruit_cost_food`, `active_skill_names`, `passive_skill_names`, `skill_tree` | Full ability tree for evaluation |

**Dropped Items:**
| Original | Actual | Notes |
|---|---|---|
| `id`, `type`, `room_id`, etc. | `type` ("Dust"/"Equipment"/"Chest"), `name`, `room_index`, `dust_amount`, `category`, `weapon_type`, `attack_type` | Includes weapon classification for equipment |

### 8.2 IPC Protocol

- **No ZeroMQ** — uses raw TCP sockets with 4-byte big-endian length-prefixed JSON framing (ZeroMQ requires .NET 4.x+)
- **Port 5555**: State push (mod → Python), sent on turn/phase change
- **Port 5556**: Action request/response (Python → mod → Python)
- **IPC works before dungeon loads** — menu commands (QUERY_MENU_STATE, START_NEW_GAME, CONTINUE_GAME) are processed from the main menu

### 8.3 Game Difficulty

The game only has two difficulties:
- `Easy` — this is the "normal" difficulty (game's joke naming: displayed as "Too Easy")
- `Normal` — this is actually hard (displayed as "Easy" in-game)

The agent defaults to `Easy` (the actual normal difficulty).

### 8.4 Game Phases

| Wire Value | Meaning |
|---|---|
| `"Strategy"` | Planning phase — no enemies, build/move/explore |
| `"Action"` | Wave active — enemies spawning and fighting |

Crystal state is tracked separately via `crystal_state`:
- `"Plugged"` — normal play
- `"Unplugged"` — crystal destroyed (game over)
- `"PluggedOnExitSlot"` — floor escape in progress

### 8.5 Hero & Ship Config Names

Heroes use config names like `Hero_H0001`, `Hero_H0003`, etc. Key mappings:
- `Hero_H0001` = Max O'Kane (Prisoner faction)
- `Hero_H0003` = Gork (Native faction)

Ships use simple names: `Pod`, `Infirmary`, `Drill`, `Organic`, etc.
Default: `Pod` (always unlocked).

### 8.6 ResourceHook Player Reference

`Player.LocalPlayer` can be null during early initialization. The ResourceHook uses a fallback:
1. Try `Player.LocalPlayer`
2. Fallback to `Player.GetPlayerByID(Player.GetPlayerIDs()[0])`
3. If both fail, return partial data (Dust and production rates from Dungeon singleton, zero for Food/Industry/Science)

---

## 9. Phase 3.5: Game Launch & Run Management

### 9.1 New Action Commands (Pre-Dungeon)

These work from the main menu before any dungeon is loaded:

**QUERY_MENU_STATE** → Response metadata:
```json
{
  "in_dungeon": false,
  "has_save": true,
  "available_heroes": ["Hero_H0001", "Hero_H0003", ...],
  "selectable_heroes": ["Hero_H0001", "Hero_H0003", ...],
  "available_ships": ["Pod", "Infirmary", "Drill", ...]
}
```

**START_NEW_GAME** → Parameters:
```json
{
  "hero_names": ["Hero_H0001", "Hero_H0003"],
  "ship_name": "Pod",
  "difficulty": "easy"
}
```
Internally calls: `SetInputMode(MouseKeyboard)`, `Dungeon.SetShip()`, `Dungeon.SetSelectedHeroes()`, `Dungeon.SetGameDifficulty()`, `IGameControlService.StartNewSinglePlayerGame()`.

**CONTINUE_GAME** → No parameters.
Internally calls: `SetInputMode(MouseKeyboard)`, `GameSave.GetBestSPSaveData()`, `IGameControlService.StartSavedSinglePlayerGame(saveKey)`.

### 9.2 Python GameLauncher Class

```python
launcher = GameLauncher(use_steam=True)
launcher.launch_and_connect()       # Launch game + connect IPC
menu = launcher.query_menu_state()  # Get available heroes/ships (retries if game still loading)
launcher.start_new_game(heroes=["Hero_H0001", "Hero_H0003"], ship="Pod", difficulty="easy")
state = launcher.wait_for_dungeon() # Block until dungeon state arrives

# Or high-level convenience:
state = launcher.start_or_continue()  # Defaults: Pod, Easy, Max + Gork
```

### 9.3 Architecture Change

The `Plugin.Update()` loop now runs `AcceptClients()` and `actionRouter.ProcessActions()` **before** the state binding check. This allows menu commands to be processed while on the main menu (before `StateManager.IsBound` is true).

---

## 10. Python-Side File Map (Phase 3)

| File | Purpose |
|------|---------|
| `src/agent/pyproject.toml` | Project metadata + dependencies |
| `src/agent/ipc_client.py` | TCP IPC client (Phase 2) |
| `src/agent/state_parser.py` | Pydantic models matching actual wire format |
| `src/agent/graph_builder.py` | GameStatePayload → NetworkX graph |
| `src/agent/graph_utils.py` | Pathfinding, centrality, reachability utilities |
| `src/agent/dote_env.py` | Gymnasium environment wrapper (DotEEnv) |
| `src/agent/guidelines_config.py` | Configurable heuristic guidelines (YAML/JSON) |
| `src/agent/game_launcher.py` | Game lifecycle management (launch, start, continue) |

---

## 11. Phase 5: Reinforcement Learning Agent

### 11.1 Overview & Philosophy

The RL agent replaces the hard-coded heuristic decision tree with a learned policy that improves through self-play. The core design principles:

1. **Almost nothing hard-coded.** The agent discovers optimal strategies through trial and error rather than following scripted rules.
2. **Toggle-able guidelines as reward shaping.** The existing `GuidelinesConfig` concepts (GL-1 through GL-8) become optional reward shaping signals that can be enabled during early training to accelerate convergence, then disabled to let the agent find novel strategies.
3. **Hierarchical action decomposition.** A single monolithic policy over the entire action space would be intractable. Instead, the agent uses a hierarchical structure: a high-level "strategic brain" that decides WHAT to do, and low-level "tactical modules" that decide HOW to do it.
4. **Direct room movement.** Unlike the heuristic agent's hop-by-hop pathfinding, the RL agent issues MOVE_HERO commands directly to the final destination room. The game's internal A* pathfinding (`Mover.MoveToPosition` via `Seeker`/`ABPath`) handles multi-room traversal automatically.
5. **Learn from failures gracefully.** Invalid actions (hero not usable, insufficient resources, wrong room) return failed results from the mod. The agent receives a small negative reward for invalid actions and learns to avoid them — no hard masking of the entire action space needed, only masking of clearly impossible actions (e.g., building modules that aren't unlocked).

### 11.2 Architecture: Hierarchical RL with Options Framework

```
┌──────────────────────────────────────────────────────────────────┐
│                     RL AGENT (Python)                             │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              STRATEGIC BRAIN (High-Level Policy)            │  │
│  │                                                            │  │
│  │  Observation → Option Selection (what to do next)          │  │
│  │  Options: Power, Build, Research, Recruit, Equip,          │  │
│  │           LevelUp, Buy, OpenDoor, PositionHeroes,          │  │
│  │           InitiateEscape, Heal, DestroyModule, Wait        │  │
│  └───────────────────────────┬────────────────────────────────┘  │
│                              │ Selected Option                    │
│  ┌───────────────────────────▼────────────────────────────────┐  │
│  │            TACTICAL MODULES (Low-Level Policies)            │  │
│  │                                                            │  │
│  │  Each option has a parameterization sub-policy:            │  │
│  │  - PowerOption: which room to power/depower                │  │
│  │  - BuildOption: which module, which room                   │  │
│  │  - PositionOption: which hero, which room                  │  │
│  │  - DoorOption: which hero, which door                      │  │
│  │  - etc.                                                    │  │
│  └───────────────────────────┬────────────────────────────────┘  │
│                              │ Concrete ActionCommand             │
│  ┌───────────────────────────▼────────────────────────────────┐  │
│  │              ACTION EXECUTOR                                │  │
│  │                                                            │  │
│  │  - Validates basic preconditions (action masking)          │  │
│  │  - Sends command to game via IPC                           │  │
│  │  - Waits for result + fresh state                          │  │
│  │  - Reports success/failure back to learning system         │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              MICRO-CONTROLLER (Action Phase)                │  │
│  │                                                            │  │
│  │  Separate policy activated during wave_active phase:       │  │
│  │  - Hero repositioning in response to spawns               │  │
│  │  - Retreat decisions for low-HP heroes                     │  │
│  │  - Heal commands for critical heroes                       │  │
│  │  - Spawn-blocking positioning decisions                    │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              ESCAPE CONTROLLER                              │  │
│  │                                                            │  │
│  │  Activated when escape is initiated:                       │  │
│  │  - Power reallocation for escape path                      │  │
│  │  - Crystal carrier selection + routing                     │  │
│  │  - Escort/blocker/straggler assignment                     │  │
│  │  - Exit timing decisions                                   │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### 11.3 State Representation (Enhanced Observation Space)

The existing `DotEEnv` observation space is a good starting point but needs enrichment for RL. The RL agent needs a richer, more informative observation to learn from:

```python
observation_space = Dict({
    # --- Spatial / Graph ---
    "adjacency": Box(0, 1, (MAX_ROOMS, MAX_ROOMS), int8),       # Room connectivity
    "door_state": Box(0, 1, (MAX_ROOMS, MAX_ROOMS), int8),      # Open/closed doors
    "power_state": Box(0, 1, (MAX_ROOMS,), int8),               # Per-room power
    "power_reachable": Box(0, 1, (MAX_ROOMS,), int8),           # Reachable from crystal via powered chain

    # --- Room Features (per-room) ---
    "room_features": Box(-1, 200, (MAX_ROOMS, 20), float32),
    # Features per room:
    #   is_powered, is_auto_powered, is_start_room, is_exit_room,
    #   depth, suffers_emp, emp_turns_remaining, has_artifact, has_stele,
    #   minor_slot_count, minor_slots_free, has_major_module,
    #   num_minor_modules, hero_count, mob_count, npc_count,
    #   dust_loot_amount, is_on_escape_path, distance_to_crystal,
    #   distance_to_exit

    # --- Hero Features ---
    "hero_features": Box(-1, 1000, (MAX_HEROES, 22), float32),
    # Per hero:
    #   room_index, hp_ratio, level, has_crystal, is_operating,
    #   is_busy, is_usable, num_passive_skills, has_operate_passive,
    #   has_repair_passive, num_active_skills, num_equipment,
    #   faction_id, weapon_class_id, level_up_cost,
    #   distance_to_exit, distance_to_crystal, is_gathering_item,
    #   total_skills_in_tree, unlocked_skills, next_unlock_level,
    #   skills_remaining_to_unlock

    # --- Mob Features (variable count, padded) ---
    "mob_features": Box(-1, 1000, (MAX_MOBS, 6), float32),
    # Per mob: room_index, hp_ratio, target_type_id, distance_to_crystal,
    #          is_in_powered_room, mob_type_id

    # --- Resources ---
    "resources": Box(-100, 10000, (10,), float32),
    # industry, food, science, dust, dust_max,
    # ind_per_turn, food_per_turn, sci_per_turn,
    # dust_used (rooms_powered * 10), dust_available (dust - dust_used)

    # --- Available Actions Context ---
    "unlocked_modules": Box(0, 1, (MAX_MODULES,), int8),        # Which modules can be built
    "researchable": Box(0, 1, (MAX_RESEARCH,), int8),           # Available research options
    "recruitable_heroes": Box(-1, 100, (MAX_RECRUITS, 8), float32),  # Stats of available recruits
    "merchant_items": Box(-1, 1000, (MAX_MERCHANT_ITEMS, 6), float32),  # Items for sale
    "inventory_items": Box(-1, 100, (MAX_INVENTORY, 6), float32),  # Backpack + shared items
    "hero_equipment_compat": Box(0, 1, (MAX_HEROES, MAX_INVENTORY), int8),  # Can hero equip item?

    # --- Game Meta ---
    "game_meta": Box(-1, 10000, (12,), float32),
    # turn, floor, phase_id, num_rooms, num_heroes, num_mobs,
    # num_closed_doors, crystal_safe, exit_room_index,
    # time_scale, is_last_floor (floor==12), total_doors_on_floor
})
```

### 11.4 Action Space Design (Hierarchical)

Rather than one flat Discrete space over all possible (command × parameter) combinations, the agent uses a two-level action:

**Level 1: Option Selection (Strategic Brain)**

```python
# High-level options the agent can choose from each decision step
class StrategicOption(Enum):
    POWER_ROOM = 0          # Power an unpowered room
    DEPOWER_ROOM = 1        # Depower a powered room (to free dust)
    BUILD_MODULE = 2        # Build a module in a room
    DESTROY_MODULE = 3      # Sell/destroy a built module
    RESEARCH = 4            # Research a blueprint at an artifact
    RECRUIT_HERO = 5        # Recruit a discovered hero
    DISMISS_HERO = 6        # Dismiss a current hero (to make room)
    LEVEL_UP_HERO = 7       # Level up a hero
    BUY_ITEM = 8            # Buy from a merchant
    EQUIP_ITEM = 9          # Equip an item to a hero
    UNEQUIP_ITEM = 10       # Unequip an item from a hero
    POSITION_HERO = 11      # Move a hero to a specific room
    OPEN_DOOR = 12          # Open a closed door
    HEAL_HERO = 13          # Heal a hero with food
    INITIATE_ESCAPE = 14    # Begin the escape sequence
    WAIT = 15               # Do nothing this decision step (end turn)
```

**Level 2: Option Parameterization (Tactical Module)**

Each option has a dedicated parameter head that produces the specific arguments:

| Option | Parameters Needed |
|--------|-------------------|
| POWER_ROOM | room_index |
| DEPOWER_ROOM | room_index |
| BUILD_MODULE | room_index, module_id |
| DESTROY_MODULE | room_index, module_id |
| RESEARCH | research_id |
| RECRUIT_HERO | recruit_id, recruiter_hero_index |
| DISMISS_HERO | hero_index |
| LEVEL_UP_HERO | hero_index |
| BUY_ITEM | merchant_item_id, hero_index |
| EQUIP_ITEM | item_id, hero_index |
| UNEQUIP_ITEM | hero_index, slot_type |
| POSITION_HERO | hero_index, room_index |
| OPEN_DOOR | hero_index, door_id (from_room, to_room) |
| HEAL_HERO | hero_index, food_amount |
| INITIATE_ESCAPE | (no params — triggers escape controller) |
| WAIT | (no params) |

### 11.5 Action Masking

To improve training efficiency, clearly impossible actions are masked out BEFORE the policy network sees them. This is not hard-coding strategy — it's preventing the agent from wasting training steps on physically impossible commands:

**Always masked (hard constraints):**
- BUILD_MODULE when: no unlocked modules, no available slots in any room, zero industry
- RESEARCH when: no artifact on floor, no researchable blueprints, already researching
- RECRUIT_HERO when: no recruitable heroes on floor, zero food
- BUY_ITEM when: no merchants on floor, zero dust
- EQUIP_ITEM when: no items in inventory
- OPEN_DOOR when: no closed doors remain
- POWER_ROOM when: no unpowered rooms or dust_available <= 0
- DEPOWER_ROOM when: no powered (non-auto) rooms
- DISMISS_HERO when: only 1 hero remains
- LEVEL_UP_HERO when: not enough food for any hero's level_up_cost
- HEAL_HERO when: all heroes at full HP or zero food
- INITIATE_ESCAPE when: exit room not discovered, or already escaping
- POSITION_HERO when: all heroes busy/not usable

**Never masked (soft constraints the agent must learn):**
- "Should I power this room vs that room?" — agent learns room value
- "Is it worth depowering room X to power room Y?" — agent learns chain importance
- "Should I buy this item or save dust?" — agent learns resource economy
- "Should I open more doors or escape now?" — agent learns risk assessment

### 11.6 Decision Timing & Game Loop Integration

```
┌─────────────────────────────────────────────────────┐
│                  STRATEGY PHASE                       │
│                                                      │
│  while game_phase == Strategy:                       │
│    1. Receive fresh state from mod                   │
│    2. Build observation                              │
│    3. Strategic brain selects option                  │
│    4. If option == WAIT: break (end turn — let the   │
│       heuristic or environment open a door to        │
│       advance to Action phase)                       │
│    5. Tactical module parameterizes the option       │
│    6. Action executor sends command + waits result   │
│    7. Receive post-action state                      │
│    8. Compute step reward                            │
│    9. Store transition in replay buffer              │
│   10. Repeat (agent can take multiple actions per    │
│       strategy phase)                                │
│                                                      │
│  Note: Door opening advances to Action phase.        │
│  The agent must open a door itself (option 12)       │
│  when it decides to — this is how it "ends its       │
│  strategy turn."                                     │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│                  ACTION PHASE                         │
│                                                      │
│  while game_phase == Action:                         │
│    1. Receive state (mobs spawning, fighting)        │
│    2. Micro-controller policy decides:               │
│       - Reposition heroes (react to spawn rooms)     │
│       - Retreat low-HP heroes                        │
│       - Heal critically wounded heroes               │
│       - Block spawns in unpowered rooms              │
│    3. If no action needed: WAIT (game resolves       │
│       combat automatically via hero auto-targeting)  │
│    4. Store transitions for micro-controller         │
│                                                      │
│  Action phase ends when all mobs are dead →          │
│  returns to Strategy phase.                          │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│                  ESCAPE PHASE                         │
│                                                      │
│  Triggered by INITIATE_ESCAPE option:                │
│    1. Escape controller policy takes over:           │
│       - Select crystal carrier                       │
│       - Reallocate power (escape path priority)      │
│       - Assign hero roles (carrier/escort/blocker)   │
│       - Route all heroes                             │
│    2. During escape waves (Action sub-phase):        │
│       - Micro-controller handles combat              │
│    3. Crystal arrives at exit → PLUG_CRYSTAL_EXIT    │
│    4. Floor complete → NEXT_FLOOR or game end        │
└─────────────────────────────────────────────────────┘
```

### 11.7 Network Architecture

The policy network uses a **multi-headed architecture** with shared feature extraction:

```
Input Observation
       │
       ▼
┌─────────────────────────────────────────┐
│         SHARED ENCODER                   │
│                                         │
│  ┌──────────────┐  ┌────────────────┐   │
│  │ Graph Encoder │  │ Entity Encoder │   │
│  │ (GNN or MLP  │  │ (Heroes, Mobs, │   │
│  │  on flattened │  │  Items, etc.)  │   │
│  │  adjacency +  │  │  (MLP / Set    │   │
│  │  room feats)  │  │   Transformer) │   │
│  └──────┬───────┘  └───────┬────────┘   │
│         │                   │            │
│         └─────────┬─────────┘            │
│                   ▼                      │
│         ┌─────────────────┐              │
│         │  Fusion Layer    │              │
│         │  (concat + MLP)  │              │
│         └────────┬────────┘              │
└──────────────────┼───────────────────────┘
                   │ Shared Embedding (512-d)
                   │
       ┌───────────┼───────────────────┐
       │           │                   │
       ▼           ▼                   ▼
┌─────────────┐ ┌──────────┐  ┌──────────────┐
│ Option Head │ │Value Head│  │ Param Heads  │
│ (16-way     │ │ (scalar  │  │ (per-option  │
│  softmax    │ │  V(s))   │  │  sub-policy) │
│  + mask)    │ │          │  │              │
└─────────────┘ └──────────┘  └──────────────┘
```

**Design decisions:**
- **GNN vs flattened MLP for graph:** Start with flattened adjacency + room features through MLP (simpler, faster to iterate). Graduate to GNN (Graph Attention Network) if the agent struggles with spatial reasoning.
- **Set Transformer for entities:** Heroes/mobs/items are variable-count, order-invariant entities. A lightweight attention mechanism handles this better than fixed padding.
- **Separate param heads:** Each option has its own small MLP that produces the parameters for that option. Only the selected option's head is evaluated (saves compute).

### 11.8 Training Algorithm: PPO with Auxiliary Objectives

**Primary algorithm: PPO (Proximal Policy Optimization)**

Rationale:
- Works well with discrete hierarchical action spaces
- Stable training (important when environment is slow — one game instance)
- Compatible with action masking
- Well-supported in CleanRL / SB3 / RLlib

**Auxiliary training signals (to accelerate learning):**
- **Action validity prediction:** Auxiliary head predicts whether an action will succeed or fail. Provides gradient signal even when the main reward is sparse.
- **State value prediction per floor:** Predicts expected final reward for the floor. Helps with credit assignment across the many steps per floor.
- **Opponent modeling (optional):** Predicts where mobs will spawn next based on room power/door state patterns.

### 11.9 Reward Function (Enhanced)

The reward function is the primary mechanism for encoding "soft" domain knowledge. Guidelines become reward shaping terms that can be toggled:

```python
# --- Core Rewards (always active) ---
R_floor_escaped = +200.0            # Successfully escape a floor
R_game_over = -200.0                # Crystal destroyed
R_hero_died = -50.0                 # A hero died
R_room_explored = +5.0              # Opened a new door / discovered new room
R_invalid_action = -1.0             # Attempted an impossible action
R_successful_action = +0.1          # Any valid action executed
R_floor_progress = +100.0 * (floor / 12)  # Reaching higher floors is exponentially more valuable
R_wait_penalty = -0.05              # Small penalty for choosing WAIT (encourages action)

# --- Resource Economy (always active) ---
R_industry_built = +3.0             # Built an industry module
R_module_built = +1.5               # Built any other module
R_research_completed = +4.0         # Completed a research
R_item_equipped = +1.0              # Equipped an item to a compatible hero
R_dust_collected = +0.5 * amount    # Collected dust from floor

# --- Guideline-Shaped Rewards (toggle-able) ---
# GL-POWER: Power chain awareness
R_power_chain_broken = -3.0         # Depowered a room that disconnected others from crystal
R_power_chain_optimal = +1.0        # Powered a room that extends the longest powered chain

# GL-OPERATE: Operate bonus awareness
R_operator_placed = +2.0            # Hero with Operate passive placed on major module
R_operator_interrupted = -2.0       # Moved an operating hero (losing bonus)

# GL-ESCAPE: Escape timing
R_escape_all_doors_open = +5.0      # Escaped after opening all doors (max resources gathered)
R_escape_early_but_safe = +2.0      # Escaped before all doors (survived with judgment)
R_overstayed = -10.0                # Died because opened too many doors on dangerous floor

# GL-COMBAT: Combat positioning
R_spawn_blocked = +2.0              # Hero in unpowered room blocked spawns
R_hero_took_heavy_damage = -1.0     # Hero dropped below 30% HP
R_hero_healed_wisely = +0.5         # Healed a hero who was in genuine danger

# GL-EQUIPMENT: Equipment matching
R_weapon_class_match = +2.0         # Equipped a weapon matching hero's weapon class
R_weapon_class_mismatch = -1.0      # Equipped incompatible weapon (will fail or be suboptimal)

# GL-RECRUIT: Recruitment decisions
R_recruited_useful_hero = +3.0      # Recruited hero with operate/repair passive or good faction synergy
R_dismissed_for_upgrade = +1.0      # Dismissed a weaker hero to recruit a stronger one

# GL-INDUSTRY: Cross-floor resource planning
R_floor_exit_industry_high = +5.0 * (industry / 100)  # Reward leaving floor with industry to carry
```

### 11.10 Training Infrastructure

**Self-play loop:**
```
┌───────────────────────────────────────────────────────┐
│                  TRAINING LOOP                          │
│                                                        │
│  for episode in range(num_episodes):                   │
│    1. game_launcher.start_new_game(...)                 │
│    2. for floor in range(1, 13):                       │
│       a. Collect rollout (steps until floor ends)      │
│       b. Store in replay buffer                        │
│       c. If floor_escaped: NEXT_FLOOR                  │
│       d. If game_over: break                           │
│    3. Compute advantages + returns                     │
│    4. PPO update (multiple epochs over buffer)         │
│    5. Log metrics (TensorBoard / W&B)                  │
│    6. Every N episodes: save checkpoint                │
│    7. Every M episodes: evaluate without exploration   │
│    8. game_launcher.return_to_menu() → restart         │
└───────────────────────────────────────────────────────┘
```

**Time scale for training:** The mod already supports `Time.timeScale`. For training, increase to 4x–8x to accelerate gameplay. The IPC polling intervals scale with timeScale already.

**Curriculum learning (phased difficulty):**

| Stage | Duration | Focus | Guideline Rewards |
|-------|----------|-------|-------------------|
| Stage 1: Survive Floor 1 | ~500 episodes | Learn basic actions, avoid invalid commands, open doors, build modules | All enabled (max shaping) |
| Stage 2: Multi-floor | ~2000 episodes | Learn escape timing, floor transitions, resource carry-over | All enabled |
| Stage 3: Full game | ~5000 episodes | Reach floor 12, complex combat, recruitment decisions | Gradually disable shaping |
| Stage 4: Mastery | Ongoing | Optimize win rate, discover novel strategies | All shaping disabled |

### 11.11 Guidelines as Training Scaffolding

Each former heuristic "guideline" becomes a reward-shaping signal that the agent can learn to follow or violate:

| Guideline | Heuristic Behavior | RL Training Signal | Can Be Disabled? |
|-----------|-------------------|-------------------|-----------------|
| GL-1 (Retreat) | Hard retreat at 30% HP | Negative reward for hero death; no forced retreat | Yes — agent learns its own risk tolerance |
| GL-2 (Starting heroes) | Always pick Max + Gork | Train with fixed heroes initially; randomize later | Yes — agent tries different compositions |
| GL-3 (Protect operators) | Never move operating heroes | Negative reward for interrupting operate | Yes — agent may learn when interruption is worth it |
| GL-4 (Max Operate unlock) | Prioritize Max leveling | Bonus for unlocking Operate on any hero | Yes — agent decides leveling priority |
| GL-5 (Fastest carrier) | Always assign fastest to crystal | No constraint — agent picks who carries | Yes — fully learned |
| GL-6 (Repower escape) | Scripted repower of exit path | Bonus for keeping exit path powered during escape | Yes — agent learns escape power management |
| GL-7 (Artifact safety) | Don't research if artifact endangered | Negative reward if artifact destroyed while researching | Yes — agent learns artifact defense |
| GL-8 (Pre-escape inventory) | Move items to backpack before escape | Reward for carrying items to next floor | Yes — agent learns item persistence |

### 11.12 Micro-Controller (Action Phase Policy)

During the Action phase, a separate (smaller) policy network controls hero positioning in combat:

**Observation (combat-specific):**
- Mob spawn locations + counts per room
- Hero positions + HP ratios
- Powered/unpowered room map (spawn-blocking potential)
- Modules in danger (mobs in room with modules)
- Crystal room threat level

**Actions (combat-only):**
- REPOSITION_HERO(hero_idx, room_idx) — move hero to a different room
- HEAL_HERO(hero_idx) — emergency heal
- WAIT — let auto-combat resolve (heroes auto-target nearest enemy)

**Key learned behaviors:**
- Heroes in unpowered rooms block mob spawns until spawning ceases — then should move to fight
- Moving an operating hero loses the operate bonus for a turn (cost/benefit)
- Retreating a near-death hero is better than losing them entirely
- Crystal room must be defended if crystal-targeting mobs appear

### 11.13 Escape Controller

The escape phase has unique dynamics that warrant a specialized policy:

**Trigger:** Strategic brain selects INITIATE_ESCAPE option.

**Decisions (learned, not scripted):**
1. **Crystal carrier selection** — any hero can carry, agent learns who is safest/fastest
2. **Power reallocation** — which rooms to power on the exit path, which to depower
3. **Hero roles:**
   - Carrier: picks up crystal, moves to exit room
   - Escort: moves ahead of carrier, fights mobs on path
   - Blocker: stands in depowered room to block spawns
   - Exit-waiter: already at exit room
4. **Abandon decision:** If carrier is going to die, should the crystal be dropped? If stragglers can't reach exit, should they be left behind?

**Exit condition:** All heroes (or just carrier + essential escorts) in exit room → PLUG_CRYSTAL_EXIT.

### 11.14 Movement Design (No Hop-by-Hop)

The RL agent issues MOVE_HERO commands with the **final destination room** directly:

```python
# Heuristic agent (old): hop-by-hop
path = shortest_path(hero.room, target)
action = MOVE_HERO(hero, path[1])  # Only next room in chain

# RL agent (new): direct destination
action = MOVE_HERO(hero, target_room)  # Game auto-paths via A*
```

**Why this works:** The game's `Hero.MoveToRoom()` → `RequestMoveToPosition(room.CenterPosition)` → `Mover.MoveToPosition()` uses `Pathfinding.Seeker.StartPath()` (A* pathfinding library) to compute and follow a path through multiple rooms automatically. The hero walks through intermediate rooms without additional commands.

**Implication for state tracking:** After issuing MOVE_HERO to a distant room, the hero's `room_index` in state updates as they pass through each intermediate room. The agent should consider the hero "busy" until they arrive at the target room. The `is_usable` field on heroes already tracks this — a moving hero remains usable (can be re-directed) but the agent should learn not to constantly re-route heroes.

### 11.15 Handling Known Pitfalls (Lessons from Heuristic Agent)

Based on the issues documented in `docs/heuristic-agent-notes.md`:

| Pitfall | RL Agent Approach |
|---------|-------------------|
| #1 Movement not instant | Agent observes hero.room_index updating over time. Busy heroes have lower action priority. Step reward doesn't fire until hero arrives. |
| #2 "Not usable" during animations | Invalid action penalty (-1.0). Agent learns timing. Action masking on `hero.is_usable == false`. |
| #3 Room index shuffling | Already solved by OpeningIndex+1 stable IDs. No change needed. |
| #4 State staleness | Environment always waits for post-action state push before computing next observation. |
| #5 Crystal state confusion | `is_game_over` uses `is_level_over` as primary signal. Observation includes crystal_safe flag. |
| #6 Item pickup timing | No explicit wait. Agent observes items disappearing from state over time. Small delayed reward when dust/items collected. |
| #7 Research requires artifact | Action mask: RESEARCH masked when no artifact present. |
| #8 Action timeouts (30s) | RL inference is fast (<100ms). Not a concern. |
| #9 Time scale | Training uses higher timeScale (4x–8x). State push rates scale automatically. |
| #10 Floor transitions | Handled by training loop (not the policy). NEXT_FLOOR is a meta-action between episodes. |
| #11 ResourceHook null after transitions | Already fixed in mod. Training loop handles floor boundaries. |
| #12 Optimistic state updates | Never assume success. Only update internal state after confirmed result. |
| #13 WAIT blocking other actions | Hierarchical design: WAIT is one option among many. Other options always available. |
| #15 Door opens advance turns | Part of the environment dynamics. Agent learns that OPEN_DOOR transitions to Action phase. |
| #16 Game over detection | Environment uses `is_level_over` flag. Episode terminates correctly. |

### 11.16 Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| RL Algorithm | PPO (CleanRL implementation) | Simple, stable, well-understood; CleanRL is single-file, easy to customize for hierarchical actions |
| Neural Network | PyTorch | Industry standard, good debugging, compatible with everything |
| Action Masking | Custom mask computation in env | `InvalidActionMasking` pattern from CleanRL reference impl |
| Logging | Weights & Biases (W&B) + TensorBoard | Real-time training curves, hyperparameter tracking, episode recording |
| Checkpointing | PyTorch save/load + periodic eval | Save best model by floor-reached metric |
| Curriculum | Manual stage progression based on success rate | Move to next stage when >60% success rate in current |
| Replay Buffer | On-policy (PPO rollout buffer) | PPO is on-policy; no separate replay buffer needed |
| Vectorized Envs | Single environment (game instance) | Game is heavyweight; no parallel envs possible on one machine |

### 11.17 File Map (Phase 5)

| File | Purpose |
|------|---------|
| `src/agent/rl_agent.py` | Main RLAgent class (extends BaseAgent), orchestrates strategic/micro/escape |
| `src/agent/rl_env.py` | Enhanced Gymnasium env with richer observations, action masking, hierarchical action space |
| `src/agent/networks.py` | PyTorch network definitions (shared encoder, option head, param heads, value head) |
| `src/agent/ppo_trainer.py` | PPO training loop with rollout collection, advantage estimation, policy updates |
| `src/agent/action_masking.py` | Action mask computation from game state (hard constraints only) |
| `src/agent/reward_shaping.py` | Configurable reward function with toggle-able guideline shaping terms |
| `src/agent/curriculum.py` | Curriculum manager: tracks success rates, advances training stages |
| `src/agent/micro_controller.py` | Action-phase combat policy (smaller network) |
| `src/agent/escape_controller.py` | Escape-phase policy |
| `src/agent/train_rl.py` | Training entry point: game launch, training loop, logging, checkpoints |
| `src/agent/eval_rl.py` | Evaluation script: load checkpoint, play without exploration, record metrics |
| `src/agent/rl_config.py` | Training hyperparameters + reward weights + curriculum config (YAML) |


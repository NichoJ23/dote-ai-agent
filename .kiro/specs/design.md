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
| `hp`, `max_hp`, `attack`, `defense`, `speed` | `hp`, `max_hp` only (+ `level`) | No attack/defense/speed stats exposed |
| `abilities` (with cooldown/unlock) | `active_skills` [{name, cooldown_turns, remaining_cooldown, is_activated}] | Different structure |
| `passives` (with unlock status) | `passive_skills` [{name}] | No unlock tracking — all listed = unlocked |
| `equipment` [{slot_type, item_id, item_name}] | `equipment` [{slot_category, item_name}] | No item_id, slot uses game categories |
| `is_carrying_crystal` | `has_crystal` | |
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
| `inventory` [{item_id, item_name, slot_type, cost_dust, stats}] | `items` [{name, rarity, cost}] + `currency_type` | Simpler structure |

**Recruitable Heroes:**
| Original | Actual | Notes |
|---|---|---|
| Full hero stats + passives objects | `name`, `faction`, `room_index`, `hp`, `max_hp`, `passive_skill_names` (string list) | Minimal data |

**Dropped Items:**
| Original | Actual | Notes |
|---|---|---|
| `id`, `type`, `room_id`, etc. | `type` ("Dust"/"Equipment"/"Chest"), `name`, `room_index`, `dust_amount` | Simpler |

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

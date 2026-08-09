# Design: Autonomous AI Agent for Dungeon of the ENDLESS

#[[file:master-plan.md]]

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
│  │  │ (IStateHook) │  │(IActionHook)│  │  (NetMQ PUB/SUB) │  │  │
│  │  └──────┬───────┘  └──────▲──────┘  └───────┬──────────┘  │  │
│  │         │                  │                  │             │  │
│  │         │    Hooks into Assembly-CSharp.dll   │             │  │
│  │  ┌──────▼──────────────────┴──────────────────▼──────────┐  │  │
│  │  │  DungeonHook │ HeroHook │ MobHook │ ResourceHook      │  │  │
│  │  └────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└──────────────────────────────────┬──────────────────────────────┘
                                   │ ZeroMQ (tcp://localhost)
                          Port 5555│(State PUB)
                          Port 5556│(Action REP)
┌──────────────────────────────────▼──────────────────────────────┐
│                     PYTHON AI AGENT ENGINE                        │
│                                                                  │
│  ┌────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │
│  │  IpcClient     │  │  DotEEnv         │  │  AgentController │  │
│  │  (pyzmq)       │──▶│  (gymnasium.Env) │──▶│  (FSM / Policy) │  │
│  └────────────────┘  └──────────────────┘  └─────────────────┘  │
│                              │                       │            │
│                       ┌──────▼──────┐         ┌──────▼──────┐    │
│                       │  GraphState │         │ MacroPlanner │    │
│                       │  (NetworkX) │         │ MicroControl │    │
│                       └─────────────┘         └─────────────┘    │
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
    /// Extracts dungeon-level state: room graph, power states, crystal location.
    /// </summary>
    public interface IDungeonHook : IStateHook
    {
        DungeonState GetDungeonState();
    }

    /// <summary>
    /// Extracts hero states: HP, position, abilities, equipment.
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
}
```

### 2.3 IPC Bridge Interface

```csharp
namespace DotEAgent.Ipc
{
    /// <summary>
    /// Manages the ZeroMQ socket lifecycle and message routing.
    /// </summary>
    public interface IIpcBridge : IDisposable
    {
        /// <summary>Initializes PUB socket on port 5555 and REP socket on port 5556.</summary>
        void Start();

        /// <summary>Publishes serialized game state to connected subscribers.</summary>
        void PublishState(GameStatePayload state);

        /// <summary>Polls for incoming action commands (non-blocking).</summary>
        ActionCommand PollAction(int timeoutMs = 100);

        /// <summary>Sends an action result response back to the Python agent.</summary>
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
        public string GamePhase { get; set; }  // "tactical_pause" | "wave_active" | "game_over"
        public ResourceState Resources { get; set; }
        public List<RoomState> Rooms { get; set; }
        public List<HeroState> Heroes { get; set; }
        public List<MobState> Mobs { get; set; }
        public PayloadMetadata Meta { get; set; }
    }

    public class ResourceState
    {
        public int Industry { get; set; }
        public int Food { get; set; }
        public int Science { get; set; }
        public int Dust { get; set; }
        public int DustMax { get; set; }
    }

    public class RoomState
    {
        public int Id { get; set; }
        public bool Powered { get; set; }
        public bool HasCrystal { get; set; }
        public bool IsExplored { get; set; }
        public List<int> ConnectedIds { get; set; }
        public List<string> InstalledModules { get; set; }
        public int MajorSlots { get; set; }
        public int MinorSlots { get; set; }
        public int MajorSlotsUsed { get; set; }
        public int MinorSlotsUsed { get; set; }
    }

    public class HeroState
    {
        public string Id { get; set; }
        public string Name { get; set; }
        public int RoomId { get; set; }
        public float Hp { get; set; }
        public float MaxHp { get; set; }
        public float Attack { get; set; }
        public float Defense { get; set; }
        public float Speed { get; set; }
        public bool AbilityReady { get; set; }
        public float AbilityCooldown { get; set; }
        public List<string> Inventory { get; set; }
    }

    public class MobState
    {
        public string Id { get; set; }
        public string Type { get; set; }
        public int RoomId { get; set; }
        public float Hp { get; set; }
        public float MaxHp { get; set; }
        public string TargetHeroId { get; set; }
        public float AttackCooldown { get; set; }
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
  "required": ["turn", "game_phase", "resources", "rooms", "heroes", "mobs", "meta"],
  "properties": {
    "turn": {
      "type": "integer",
      "minimum": 0,
      "description": "Current game turn number"
    },
    "game_phase": {
      "type": "string",
      "enum": ["tactical_pause", "wave_active", "game_over"],
      "description": "Current phase of the game loop"
    },
    "resources": {
      "type": "object",
      "required": ["industry", "food", "science", "dust", "dust_max"],
      "properties": {
        "industry": { "type": "integer", "minimum": 0 },
        "food": { "type": "integer", "minimum": 0 },
        "science": { "type": "integer", "minimum": 0 },
        "dust": { "type": "integer", "minimum": 0 },
        "dust_max": { "type": "integer", "minimum": 0 }
      }
    },
    "rooms": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "powered", "has_crystal", "is_explored", "connected_ids"],
        "properties": {
          "id": { "type": "integer" },
          "powered": { "type": "boolean" },
          "has_crystal": { "type": "boolean" },
          "is_explored": { "type": "boolean" },
          "connected_ids": {
            "type": "array",
            "items": { "type": "integer" }
          },
          "installed_modules": {
            "type": "array",
            "items": { "type": "string" }
          },
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
        "required": ["id", "name", "room_id", "hp", "max_hp"],
        "properties": {
          "id": { "type": "string" },
          "name": { "type": "string" },
          "room_id": { "type": "integer" },
          "hp": { "type": "number", "minimum": 0 },
          "max_hp": { "type": "number", "minimum": 1 },
          "attack": { "type": "number" },
          "defense": { "type": "number" },
          "speed": { "type": "number" },
          "ability_ready": { "type": "boolean" },
          "ability_cooldown": { "type": "number", "minimum": 0 },
          "inventory": {
            "type": "array",
            "items": { "type": "string" }
          }
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
          "target_hero_id": { "type": ["string", "null"] },
          "attack_cooldown": { "type": "number", "minimum": 0 }
        }
      }
    },
    "meta": {
      "type": "object",
      "required": ["timestamp_ms", "sequence_number"],
      "properties": {
        "timestamp_ms": { "type": "integer" },
        "sequence_number": { "type": "integer", "minimum": 0 },
        "warnings": {
          "type": "array",
          "items": { "type": "string" }
        }
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
        "POWER_ROOM",
        "UNPOWER_ROOM",
        "USE_ABILITY",
        "HEAL_HERO",
        "LEVEL_UP_HERO",
        "PAUSE_GAME",
        "UNPAUSE_GAME"
      ],
      "description": "Action verb identifying the command type"
    },
    "parameters": {
      "type": "object",
      "description": "Command-specific parameters (see section 3.3)"
    },
    "timestamp": {
      "type": "integer",
      "description": "Unix timestamp (ms) when the command was issued"
    }
  }
}
```

### 3.3 Action Command Parameter Schemas

#### MOVE_HERO
```json
{
  "hero_id": "string (required) - ID of the hero to move",
  "target_room_id": "integer (required) - destination room ID"
}
```

#### OPEN_DOOR
```json
{
  "from_room_id": "integer (required) - room the hero is currently in",
  "target_room_id": "integer (required) - adjacent unexplored room to open"
}
```

#### BUILD_MODULE
```json
{
  "room_id": "integer (required) - room to build in",
  "module_name": "string (required) - module type identifier",
  "slot_type": "string (required) - 'major' or 'minor'"
}
```

#### POWER_ROOM / UNPOWER_ROOM
```json
{
  "room_id": "integer (required) - target room ID"
}
```

#### USE_ABILITY
```json
{
  "hero_id": "string (required) - hero using the ability",
  "target_id": "string (optional) - target entity if ability requires one"
}
```

#### HEAL_HERO
```json
{
  "hero_id": "string (required) - hero to heal",
  "food_amount": "integer (required) - amount of food resource to spend"
}
```

#### LEVEL_UP_HERO
```json
{
  "hero_id": "string (required) - hero to level up",
  "stat": "string (required) - 'attack' | 'defense' | 'speed' | 'hp'"
}
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
      "description": "Human-readable error message if success=false"
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

    # Observation space: Dict space with graph + resource vector
    observation_space: spaces.Dict

    # Action space: MultiDiscrete(action_type, target_room, target_entity)
    action_space: spaces.MultiDiscrete

    def __init__(self, host: str = "localhost", state_port: int = 5555, action_port: int = 5556): ...
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
       -  0.5 * (ΔHero HP Lost across all heroes)
       - 100 * (Crystal Destroyed flag)
       +  2 * (ΔModules Built)
       +  1 * (ΔMobs Killed)
```

### 4.3 Agent Controller Interface

```python
from abc import ABC, abstractmethod

class BaseAgent(ABC):
    """Abstract base for all agent controllers."""

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
    States: EXPLORE, BUILD, DEFEND, RETREAT
    """

    def select_action(self, observation: dict, phase: str) -> dict: ...
    def reset(self) -> None: ...
```

---

## 5. Technology Decisions & Constraints

| Decision | Rationale |
|----------|-----------|
| ZeroMQ (PUB/SUB + REQ/REP) | Sub-millisecond latency, no HTTP overhead, native C#/Python bindings |
| JSON over MessagePack | Human-readable for debugging; schema validation available; acceptable perf for turn-based |
| NetworkX for graph state | Mature library with centrality, shortest-path, and connectivity algorithms built-in |
| BepInEx 5.4 Mono | Stable Unity mod loader; avoids IL2CPP complications; large community |
| Gymnasium API | Industry standard for RL environments; compatible with SB3, RLlib, CleanRL |
| Hierarchical FSM before RL | Establishes a working baseline without training infrastructure; validates IPC correctness |

---

## 6. Error Handling Strategy

| Scenario | C# Behavior | Python Behavior |
|----------|-------------|-----------------|
| Python not connected | Retry every 2s; log warning; game continues | N/A |
| Python timeout (>5s) | Pause game; log error | Raise `TimeoutError`; attempt reconnect |
| Malformed action JSON | Return `ActionResult{success=false, error="..."}` | Log warning; retry with corrected format |
| Null reference in extraction | Substitute default; add to `meta.warnings` | Flag in observation metadata |
| Game crash/exit | Dispose sockets gracefully in `OnDestroy()` | Detect socket disconnect; call `env.close()` |

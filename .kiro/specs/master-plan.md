# Master Planning Document: Autonomous AI Agent for *Dungeon of the ENDLESS*

This master plan outlines the system design, environment setup, and implementation roadmap for an autonomous AI agent capable of playing *Dungeon of the ENDLESS* via memory reflection and programmatic control.

---

## 1. System Architecture Overview

The system bypasses computer vision completely by hooking directly into the game's Unity Mono engine. State memory is serialized and streamed to a local Python process, where an AI policy computes high-level strategic decisions and low-level tactical commands, streaming them back for in-game execution.

```
+-----------------------------------------------------------------------------------+
|                            DUNGEON OF THE ENDLESS GAME PROCESS                     |
|                                                                                   |
|   +---------------------------------------------------------------------------+   |
|   |                      Unity C# Runtime (Assembly-CSharp)                    |   |
|   |    DungeonManager  |  HeroManager  |  MobManager  |  ResourceManagement   |   |
|   +-------------------------------------+-------------------------------------+   |
|                                         | Reflection / Method Hooks               |
|   +-------------------------------------v-------------------------------------+   |
|   |                       BepInEx Mod Plugin (C# / .NET)                      |   |
|   |  - State Extractor: Serializes room graph, heroes, mobs, resources to JSON  |   |
|   |  - Action Injector: Calls internal methods (e.g., Hero.MoveTo, BuildModule)|   |
|   +-------------------------------------+-------------------------------------+   |
+-----------------------------------------|-----------------------------------------+
                                          |
                      ZeroMQ TCP Socket (Localhost:5555)
                      - Port 5555: Game State (C# -> Python)
                      - Port 5556: Action Commands (Python -> C#)
                                          |
+-----------------------------------------v-----------------------------------------+
|                               PYTHON AI AGENT ENGINE                              |
|                                                                                   |
|   +---------------------------------------------------------------------------+   |
|   |                       Gymnasium Environment Wrapper                       |   |
|   |  - step(action) -> parse JSON state, calculate reward, check game over    |   |
|   +-------------------------------------+-------------------------------------+   |
|   |                                     | Observation & Action Space              |
|   +-------------------------------------v-------------------------------------+   |
|   |                     Hierarchical Decision Controller                      |   |
|   |  - High-Level Macro Planner: Resource allocation, room un-fogging, wave   |   |
|   |    defense positioning (Rule-based / MCTS / State-Machine)                |   |
|   |  - Low-Level Micro Controller: Hero ability timing, retreating, focus-fire  |   |
|   +---------------------------------------------------------------------------+   |
+-----------------------------------------------------------------------------------+

```

---

## 2. Recommended Development Environment & Tooling

* **Agentic IDE & Spec Framework:** **Kiro IDE (`kiro.dev`)**
* Use Kiro's Spec-Driven Development framework to generate `.kiro/specs/` markdown files for each component layer.
* Define steering rules (`.kiro/steering.md`) to guide code generation across both C# (.NET Framework 4.x) and Python 3.10+.


* **Coding Assistant:** **GitHub Copilot**
* Integrated directly into Kiro/VS Code for inline autocompletion during C# decompilation research and Python Gymnasium wrapper construction.


* **C# Decompiler & Reverse Engineering:** **dnSpy**
* Used to inspect `Dungeon of the ENDLESS/DungeonOfTheEndless_Data/Managed/Assembly-CSharp.dll` and map native method signatures.


* **Mod Framework:** **BepInEx 5.4 (x86/x64 Mono)**
* Lightweight C# plugin loader that injects custom code into Unity runtime without modifying core game files on disk.


* **IPC Networking Protocol:** **ZeroMQ (`NetMQ` for C#, `pyzmq` for Python)**
* Ultra-low latency TCP pub/sub and req/rep messaging socket protocol.


* **Python AI Framework:** **Python 3.10+, Gymnasium, Stable-Baselines3, NetworkX**
* `NetworkX` manages the room topology graph; `Gymnasium` exposes standard `reset()` and `step()` API loops for standard RL or custom controllers.



---

## 3. Component Breakdown

### Layer 1: Unity State Extractor & Action Injector (C# Mod)

The C# plugin resides inside the Unity process memory and extracts the underlying game state object model every tick or phase transition.

* **Target Classes to Hook (`Assembly-CSharp.dll`):**
* `Dungeon`: Map layout, room power states, unlit rooms, door linkages.
* `Room`: Module slots, major/minor turrets built, Dust generator status, present enemies.
* `Hero`: Health points, active abilities, current room ID, inventory/equipment, move target.
* `Mob`: Health points, target priority, current room ID, attack cooldowns.
* `Player`: Dust, Food, Industry, and Science balances.


* **Execution Logic:**
* Pause state management via `GameManager.Pause()`.
* Command execution hooks invoking `Hero.OrderMove()`, `Room.BuildModule()`, `Dungeon.PowerRoom()`, and `Door.Open()`.



### Layer 2: IPC Communications Bridge

Communication runs asynchronously using JSON payloads serialized over ZeroMQ sockets.

* **State Observation Payload (C# -> Python):**
```json
{
  "turn": 12,
  "game_phase": "tactical_pause",
  "resources": {"industry": 45, "food": 30, "science": 18, "dust": 12},
  "rooms": [
    {"id": 0, "powered": true, "has_crystal": true, "connected_ids": [1, 2]},
    {"id": 1, "powered": false, "has_crystal": false, "connected_ids": [0]}
  ],
  "heroes": [
    {"id": "Opbot", "room_id": 0, "hp": 250, "max_hp": 250, "ability_ready": true}
  ]
}

```


* **Action Command Payload (Python -> C#):**
```json
{
  "command": "OPEN_DOOR",
  "parameters": {"from_room_id": 0, "target_room_id": 1}
}

```



### Layer 3: Python Environment Wrapper (`DotEEnv`)

Converts raw IPC messaging into a standard `gymnasium.Env` interface.

* **Observation Space:**
* Graph tensor representing room connectivity, power allocation, and unit densities.
* Feature vector representing player global resources and active cooldown timers.


* **Action Space:**
* Discrete action tuples: `(Action_Type, Target_Room_ID, Target_Entity_ID)`.


* **Reward Function:**

$$\text{Reward} = +10(\Delta \text{Rooms Unlocked}) + 5(\Delta \text{Dust}) - 0.5(\Delta \text{Hero HP Lost}) - 100(\text{Crystal Destroyed})$$



### Layer 4: AI Decision Engine & Strategic Controller

Due to the distinct turn phases in *Dungeon of the ENDLESS*, the decision engine is structured as a two-tier hierarchy:

1. **Macro-Planner (Planning Phase - Paused Game):**
* Operates when no wave is active.
* Evaluates resource production choices (Industry vs. Food vs. Science generators).
* Determines room powering priority based on Dust constraints and bottleneck room topology using graph centrality algorithms (`NetworkX`).


2. **Micro-Controller (Wave Defense Phase - Real-Time):**
* Operates when doors are opened and waves spawn.
* Controls hero movement, focus-firing target prioritization, and active ability timing.
* Executes tactical fallbacks toward the Crystal Room if hero health drops below critical thresholds.



---

## 4. Phased Implementation Roadmap

| Phase | Core Focus | Key Deliverables |
| --- | --- | --- |
| **Phase 1: Game Decompilation & Hooking** | Reverse engineering with `dnSpy` | Setup BepInEx environment; locate `DungeonManager` and `HeroManager` instances; log resource values to console. |
| **Phase 2: IPC Messaging & Action Control** | Two-way communication | Implement `NetMQ` socket in C# and `pyzmq` in Python; verify automated hero movements triggered from Python scripts. |
| **Phase 3: State Graph Construction** | Environment modeling | Build Python parser converting room linkage arrays into `NetworkX` graph representations; implement state JSON schemas. |
| **Phase 4: Heuristic Baseline Agent** | Rule-based controller | Construct a finite-state machine macro-planner that plays through Floor 1 autonomously without human intervention. |
| **Phase 5: Advanced Policy Training** | Hierarchical RL / Optimization | Train micro-tactical execution policies using Stable-Baselines3 (PPO) or integrate a high-level search planner (MCTS). |
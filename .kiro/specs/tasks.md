# Tasks: Autonomous AI Agent for Dungeon of the ENDLESS

#[[file:master-plan.md]]
#[[file:requirements.md]]
#[[file:design.md]]

---

## Phase 1: Game Decompilation & Hooking

> **Goal:** Establish the BepInEx mod environment, locate key game classes via dnSpy, and prove we can read live game state from within the Unity process.

| # | Task | Dependencies | Deliverable | Reqs Covered |
|---|------|--------------|-------------|--------------|
| 1.1 | Install BepInEx 5.4 (Mono x86/x64) into the Dungeon of the ENDLESS game directory and verify it loads with console output on game launch. | — | `BepInEx/` folder in game dir; log showing "BepInEx loaded" | REQ-U4 |
| 1.2 | Open `Assembly-CSharp.dll` in dnSpy; document the class hierarchy for `Dungeon`, `Room`, `Hero`, `Mob`, and `Player` resource fields. Export a markdown reference of target fields and method signatures. | 1.1 | `docs/decompilation-reference.md` | REQ-U1 |
| 1.3 | Create the C# mod project (`DotEAgentMod.csproj`) targeting .NET Framework 4.7.2 with BepInEx plugin boilerplate (`BaseUnityPlugin` subclass). | 1.1 | `src/mod/DotEAgentMod.csproj`, `Plugin.cs` | REQ-U4 |
| 1.4 | Implement `IStateHook` interface and a stub `DungeonHook` class that uses reflection to locate the singleton `Dungeon` instance at runtime. | 1.2, 1.3 | `src/mod/Hooks/DungeonHook.cs` | REQ-U1 |
| 1.5 | Implement `ResourceHook` that reads Industry, Food, Science, and Dust values from the `Player` resource manager via reflection. | 1.2, 1.3 | `src/mod/Hooks/ResourceHook.cs` | REQ-U1 |
| 1.6 | Implement `HeroHook` that iterates the hero collection and extracts HP, room ID, ability cooldowns, and equipment. | 1.2, 1.3 | `src/mod/Hooks/HeroHook.cs` | REQ-U1 |
| 1.7 | Implement `MobHook` that iterates active mobs and extracts HP, room ID, target, and attack cooldown. | 1.2, 1.3 | `src/mod/Hooks/MobHook.cs` | REQ-U1 |
| 1.8 | Wire all hooks into the plugin's `Update()` loop; log a formatted summary of resources and hero positions to the BepInEx console each turn. | 1.4–1.7 | Console output confirming live state reads | REQ-E1 |
| 1.9 | Write unit tests (xUnit) for the data model serialization (`GameStatePayload` → JSON round-trip). | 1.3 | `tests/DotEAgent.Tests/SerializationTests.cs` | REQ-U3 |

---

## Phase 2: IPC Messaging & Action Control

> **Goal:** Establish two-way ZeroMQ communication and prove that a Python script can trigger an in-game hero movement.

| # | Task | Dependencies | Deliverable | Reqs Covered |
|---|------|--------------|-------------|--------------|
| 2.1 | Add `NetMQ` NuGet package to the mod project; implement `IIpcBridge` with PUB socket on port 5555 and REP socket on port 5556. | 1.3 | `src/mod/Ipc/IpcBridge.cs` | REQ-U3, REQ-S3 |
| 2.2 | Implement the state publishing logic: serialize `GameStatePayload` to JSON and publish on each phase transition or configurable tick. | 1.8, 2.1 | State messages flowing on port 5555 | REQ-E1, REQ-O1 |
| 2.3 | Implement the action polling logic: non-blocking poll on REP socket, deserialize `ActionCommand`, route to appropriate `IActionHandler`. | 2.1 | `src/mod/Ipc/ActionRouter.cs` | REQ-E2 |
| 2.4 | Implement `MoveHeroHandler` (`IActionHandler`) that calls the game's internal hero move method. | 1.2, 1.6, 2.3 | `src/mod/Actions/MoveHeroHandler.cs` | REQ-E2 |
| 2.5 | Implement `OpenDoorHandler` that triggers door opening between adjacent rooms. | 1.2, 1.4, 2.3 | `src/mod/Actions/OpenDoorHandler.cs` | REQ-E2 |
| 2.6 | Implement `BuildModuleHandler` that calls the module build method for a specified room and slot. | 1.2, 2.3 | `src/mod/Actions/BuildModuleHandler.cs` | REQ-E2 |
| 2.7 | Implement `PowerRoomHandler` and `UnpowerRoomHandler` for toggling room power state. | 1.2, 2.3 | `src/mod/Actions/PowerRoomHandler.cs` | REQ-E2 |
| 2.8 | Implement error handling: malformed JSON returns `ActionResult{success=false}`; Python timeout triggers game pause. | 2.3 | Error paths in `ActionRouter.cs` | REQ-W1, REQ-W2 |
| 2.9 | Implement retry/reconnection logic in `IpcBridge`: if Python is not connected, retry every 2 seconds with BepInEx log warnings. | 2.1 | Reconnection loop in `IpcBridge.cs` | REQ-S3 |
| 2.10 | Create Python IPC client (`ipc_client.py`) using `pyzmq` SUB on port 5555 and REQ on port 5556. | 2.1 | `src/agent/ipc_client.py` | REQ-U3 |
| 2.11 | Write a Python integration test script that connects, receives one state message, sends a `MOVE_HERO` command, and asserts a success response. | 2.2, 2.4, 2.10 | `tests/test_ipc_integration.py` | REQ-E2 |
| 2.12 | Verify end-to-end: launch game with mod, run Python script, observe hero movement in-game. Document with screenshots/logs. | 2.11 | `docs/ipc-verification.md` | US-2, US-3 |

---

## Phase 3: State Graph Construction

> **Goal:** Build the Python-side environment wrapper that converts raw JSON state into a structured NetworkX graph and exposes a Gymnasium-compatible interface.

| # | Task | Dependencies | Deliverable | Reqs Covered |
|---|------|--------------|-------------|--------------|
| 3.1 | Create Python project structure with `pyproject.toml`; declare dependencies (`pyzmq`, `gymnasium`, `networkx`, `numpy`). | — | `src/agent/pyproject.toml` | REQ-U5 |
| 3.2 | Implement `StateParser` class that deserializes the raw JSON state payload and validates it against the JSON schema. | 2.10, 3.1 | `src/agent/state_parser.py` | REQ-U3 |
| 3.3 | Implement `GraphBuilder` that converts the `rooms` array into a NetworkX `Graph` with node attributes (powered, has_crystal, modules, unit counts). | 3.2 | `src/agent/graph_builder.py` | US-5 |
| 3.4 | Add graph utility functions: `shortest_path_to_crystal()`, `unpowered_neighbors()`, `room_centrality_scores()`, `bottleneck_rooms()`. | 3.3 | `src/agent/graph_utils.py` | US-5 |
| 3.5 | Define the `observation_space` as a `gymnasium.spaces.Dict` containing the graph adjacency matrix, node feature matrix, hero feature vector, and resource vector. | 3.3, 3.1 | Observation space definition in `dote_env.py` | US-4 |
| 3.6 | Define the `action_space` as `gymnasium.spaces.Dict` with discrete command type, target room, and target entity. | 3.1 | Action space definition in `dote_env.py` | US-4 |
| 3.7 | Implement `DotEEnv.__init__()`: create IPC client, define spaces, set initial state. | 2.10, 3.5, 3.6 | `src/agent/dote_env.py` | US-4 |
| 3.8 | Implement `DotEEnv.reset()`: send UNPAUSE command, wait for first state message, build initial observation. | 3.7 | `reset()` method | US-4 |
| 3.9 | Implement `DotEEnv.step(action)`: translate action to `ActionCommand` JSON, send via IPC, receive next state, compute reward, detect termination. | 3.7, 3.2 | `step()` method | US-4, REQ-E3 |
| 3.10 | Implement `_compute_reward()` per the design spec reward function (rooms explored, dust, HP lost, crystal destroyed, modules built, mobs killed). | 3.9 | Reward computation in `dote_env.py` | US-4 |
| 3.11 | Implement `DotEEnv.close()`: cleanly disconnect ZeroMQ sockets. | 3.7 | `close()` method | US-4 |
| 3.12 | Write Pytest suite validating Gymnasium API conformance: `check_env()` from `gymnasium.utils.env_checker`. | 3.7–3.11 | `tests/test_dote_env.py` | US-4 |
| 3.13 | Write unit tests for `GraphBuilder` and `graph_utils` with mock room data. | 3.3, 3.4 | `tests/test_graph.py` | US-5 |

---

## Phase 4: Heuristic Baseline Agent

> **Goal:** Build a finite-state machine controller that can autonomously play through Floor 1 without human intervention, validating the entire pipeline.

| # | Task | Dependencies | Deliverable | Reqs Covered |
|---|------|--------------|-------------|--------------|
| 4.1 | Implement `BaseAgent` abstract class with `select_action()` and `reset()` interface. | 3.1 | `src/agent/base_agent.py` | — |
| 4.2 | Implement `HeuristicAgent` FSM skeleton with states: `EXPLORE`, `BUILD`, `DEFEND`, `RETREAT`. Define transition conditions. | 4.1 | `src/agent/heuristic_agent.py` | US-6 |
| 4.3 | Implement `EXPLORE` state logic: identify nearest unexplored room using graph shortest path; issue `OPEN_DOOR` command with closest hero. | 3.4, 4.2 | EXPLORE behavior in `heuristic_agent.py` | US-6 |
| 4.4 | Implement `BUILD` state logic: after exploration, evaluate available slots and resources; prioritize Industry generators, then Food, then defensive modules. | 3.3, 4.2 | BUILD behavior in `heuristic_agent.py` | US-8 |
| 4.5 | Implement power allocation logic: use `room_centrality_scores()` and Dust budget to determine which rooms to power, prioritizing the crystal path. | 3.4, 4.4 | Power management in `heuristic_agent.py` | US-8 |
| 4.6 | Implement `DEFEND` state logic (micro-controller): on wave start, position heroes in bottleneck rooms; assign focus-fire targets by lowest mob HP. | 3.4, 4.2 | DEFEND behavior in `heuristic_agent.py` | US-7 |
| 4.7 | Implement `RETREAT` state logic: if any hero HP < 30% max, issue `MOVE_HERO` toward Crystal Room; transition back to DEFEND when healed or wave ends. | 4.6 | RETREAT behavior in `heuristic_agent.py` | REQ-S2, US-7 |
| 4.8 | Implement FSM transition logic: determine current state based on `game_phase`, hero HP ratios, and unexplored room count. | 4.3–4.7 | State transitions in `heuristic_agent.py` | US-6 |
| 4.9 | Implement the main game loop runner (`run_agent.py`): instantiate `DotEEnv`, create `HeuristicAgent`, loop `step()` until terminated. | 3.7, 4.2 | `src/agent/run_agent.py` | US-6 |
| 4.10 | Add logging and metrics collection: turns survived, rooms explored, resources gathered, heroes lost, per-floor outcome. | 4.9 | `src/agent/metrics.py` | — |
| 4.11 | Run 5 automated Floor 1 playthroughs; record success/failure; tune heuristic thresholds (power budget, retreat HP%, explore priority). | 4.9, 4.10 | `docs/baseline-results.md` | Acceptance: 3/5 success |
| 4.12 | Write integration test: mock IPC with recorded state sequences; assert agent produces valid action sequences without crashes. | 4.2, 3.12 | `tests/test_heuristic_agent.py` | US-6 |

---

## Dependency Graph (Critical Path)

```
Phase 1:  1.1 → 1.2 → 1.4─┐
                1.3─────────┼→ 1.8 → 1.9
                1.5─────────┤
                1.6─────────┤
                1.7─────────┘

Phase 2:  1.8 ──→ 2.1 → 2.2 ──→ 2.11 → 2.12
                   │  → 2.3 → 2.4─┤
                   │         → 2.5─┤
                   │         → 2.6─┤
                   │         → 2.7─┤
                   │         → 2.8─┘
                   │  → 2.9
                   └──→ 2.10 ────→ 2.11

Phase 3:  2.10 → 3.1 → 3.2 → 3.3 → 3.4 → 3.5─┐
                              │              3.6─┼→ 3.7 → 3.8 → 3.9 → 3.10 → 3.12
                              └→ 3.13            └→ 3.11

Phase 4:  3.7 → 4.1 → 4.2 → 4.3─┐
                          │ → 4.4─┤→ 4.8 → 4.9 → 4.10 → 4.11
                          │ → 4.5─┤
                          │ → 4.6 → 4.7─┘
                          └→ 4.12
```

---

## Summary

| Phase | Tasks | Estimated Effort | Key Risk |
|-------|-------|------------------|----------|
| Phase 1 | 9 | 1–2 weeks | Reflection targets may be obfuscated or change between game versions |
| Phase 2 | 12 | 1–2 weeks | NetMQ threading conflicts with Unity main thread |
| Phase 3 | 13 | 1–2 weeks | Observation space dimensionality; variable room count across floors |
| Phase 4 | 12 | 2–3 weeks | Heuristic tuning; wave difficulty scaling beyond simple rules |
| **Total** | **46** | **5–9 weeks** | — |

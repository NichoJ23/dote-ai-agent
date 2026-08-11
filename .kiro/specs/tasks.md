# Tasks: Autonomous AI Agent for Dungeon of the ENDLESS

#[[file:master-plan.md]]
#[[file:requirements.md]]
#[[file:design.md]]

---

## Phase 1: Game Decompilation & Hooking

> **Goal:** Establish the BepInEx mod environment, locate key game classes via dnSpy, and prove we can read live game state — including door states, passives, factions, merchants, and recruits — from within the Unity process.

| # | Task | Dependencies | Deliverable | Reqs Covered |
|---|------|--------------|-------------|--------------|
| 1.1 | ~~Install BepInEx 5.4 (Mono x86/x64) into the Dungeon of the ENDLESS game directory and verify it loads with console output on game launch.~~ ✅ DONE | — | `BepInEx/` folder in game dir; log showing "BepInEx loaded" | REQ-U4 |
| 1.2 | ~~Open `Assembly-CSharp.dll` in dnSpy; document the class hierarchy for `Dungeon`, `Room`, `Hero`, `Mob`, `Player`, `Door`, `Merchant`, `Equipment`, and passive/faction fields. Export a markdown reference of target fields and method signatures.~~ ✅ DONE | 1.1 | `docs/decompilation-reference.md` | REQ-U1 |
| 1.3 | ~~Create the C# mod project (`DotEAgentMod.csproj`) targeting .NET Framework 3.5 with BepInEx plugin boilerplate (`BaseUnityPlugin` subclass). Reference game's `Assembly-CSharp.dll` and Unity engine DLLs from the Managed folder.~~ ✅ DONE | 1.1 | `src/mod/DotEAgentMod.csproj`, `Plugin.cs` | REQ-U4 |
| 1.4 | ~~Implement `IStateHook` interface and a stub `DungeonHook` class that uses reflection to locate the singleton `Dungeon` instance at runtime. Extract room graph including per-door open/closed status and auto-powered flag.~~ ✅ DONE | 1.2, 1.3 | `src/mod/Hooks/DungeonHook.cs` | REQ-U1 |
| 1.5 | ~~Implement `ResourceHook` that reads Industry, Food, Science, Dust values and per-turn production rates from the `Player` resource manager via reflection.~~ ✅ DONE | 1.2, 1.3 | `src/mod/Hooks/ResourceHook.cs` | REQ-U1 |
| 1.6 | ~~Implement `HeroHook` that iterates the hero collection and extracts HP, room ID, speed, level, both active abilities (name, unlock status, cooldown each), faction, passive abilities (including unlock status/level), equipment slots, operating state, and crystal-carrying state.~~ ✅ DONE | 1.2, 1.3 | `src/mod/Hooks/HeroHook.cs` | REQ-U1 |
| 1.7 | ~~Implement `MobHook` that iterates active mobs and extracts HP, room ID, type, and attack cooldown.~~ ✅ DONE | 1.2, 1.3 | `src/mod/Hooks/MobHook.cs` | REQ-U1 |
| 1.8 | ~~Implement `MerchantHook` that detects merchants on the floor, their room ID, and their inventory (items, costs, stats).~~ ✅ DONE | 1.2, 1.3 | `src/mod/Hooks/MerchantHook.cs` | REQ-U1 |
| 1.9 | ~~Implement `RecruitHook` that detects recruitable heroes, their room, cost, faction, passives, and base stats.~~ ✅ DONE | 1.2, 1.3 | `src/mod/Hooks/RecruitHook.cs` | REQ-U1 |
| 1.10 | ~~Implement `ItemHook` that detects dropped items (dust piles, equipment) on the floor with room ID and metadata.~~ ✅ DONE | 1.2, 1.3 | `src/mod/Hooks/ItemHook.cs` | REQ-U1 |
| 1.11 | ~~Wire all hooks into the plugin's `Update()` loop; log a formatted summary of resources, hero positions, door states, merchants, and recruits to the BepInEx console each turn.~~ ✅ DONE | 1.4–1.10 | Console output confirming live state reads | REQ-E1 |
| 1.12 | ~~Write unit tests (xUnit) for the data model serialization (`GameStatePayload` → JSON round-trip), covering new fields: doors, auto_powered, passives, faction, equipment, merchants, recruits, dropped items.~~ ⏭️ SKIPPED — covered by in-game playtesting | 1.3 | `tests/DotEAgent.Tests/SerializationTests.cs` | REQ-U3 |

---

## Phase 2: IPC Messaging & Action Control

> **Goal:** Establish two-way TCP communication and prove that a Python script can trigger in-game actions including hero movement, door opening (with hero presence validation), module building, merchant purchases, recruitment, and item equipping.

| # | Task | Dependencies | Deliverable | Reqs Covered |
|---|------|--------------|-------------|--------------|
| 2.1 | ~~Implement `IIpcBridge` using raw TCP sockets (`System.Net.Sockets.TcpListener`/`TcpClient`): listener on port 5555 (state push to Python) and port 5556 (action request/response). Use 4-byte big-endian length-prefix framing. No external dependencies.~~ ✅ DONE | 1.3 | `src/mod/Ipc/IpcBridge.cs` | REQ-U3, REQ-S3 |
| 2.2 | ~~Implement a .NET 3.5-compatible JSON serializer (embed SimpleJSON or MiniJSON) for `GameStatePayload` serialization. Implement state sending: serialize and push to connected client on port 5555 each phase transition.~~ ✅ DONE | 1.11, 2.1 | `src/mod/Ipc/JsonSerializer.cs`, state flow on port 5555 | REQ-E1, REQ-O1 |
| 2.3 | ~~Implement the action polling logic: non-blocking read on port 5556 TCP stream, deserialize `ActionCommand` from length-prefixed JSON, route to appropriate `IActionHandler` via `ActionRouter`. Add `ValidatePreconditions()` check before execution.~~ ✅ DONE | 2.1 | `src/mod/Ipc/ActionRouter.cs` | REQ-E2 |
| 2.4 | ~~Implement `MoveHeroHandler` that calls the game's internal hero move method.~~ ✅ DONE | 1.2, 1.6, 2.3 | `src/mod/Actions/MoveHeroHandler.cs` | REQ-E2 |
| 2.5 | Implement `OpenDoorHandler` that validates hero is in `from_room_id` before triggering door open. Return error if hero not present (REQ-W4). | 1.2, 1.4, 2.3 | `src/mod/Actions/OpenDoorHandler.cs` | REQ-U7, REQ-W4 |
| 2.6 | Implement `BuildModuleHandler` and `RepairModuleHandler` for constructing and repairing modules. | 1.2, 2.3 | `src/mod/Actions/BuildModuleHandler.cs`, `RepairModuleHandler.cs` | REQ-E2 |
| 2.7 | Implement `PowerRoomHandler` and `UnpowerRoomHandler`; reject unpower attempts on auto-powered rooms. | 1.2, 2.3 | `src/mod/Actions/PowerRoomHandler.cs` | REQ-E2 |
| 2.8 | Implement `RecruitHeroHandler` that validates recruiter hero is in the same room as the recruit, deducts food cost. | 1.2, 2.3 | `src/mod/Actions/RecruitHeroHandler.cs` | REQ-E2, US-9 |
| 2.9 | Implement `BuyFromMerchantHandler` that validates hero is in merchant's room, deducts dust cost. | 1.2, 2.3 | `src/mod/Actions/BuyFromMerchantHandler.cs` | REQ-E2, US-9 |
| 2.10 | Implement `EquipItemHandler` and `UnequipItemHandler` for managing hero equipment slots. | 1.2, 2.3 | `src/mod/Actions/EquipItemHandler.cs` | REQ-E2, US-9 |
| 2.11 | Implement `CollectItemHandler` that validates hero is in the item's room before collecting. | 1.2, 2.3 | `src/mod/Actions/CollectItemHandler.cs` | REQ-E7, US-9 |
| 2.12 | Implement `PickUpCrystalHandler` that validates hero is in crystal room; sets `is_carrying_crystal`. | 1.2, 2.3 | `src/mod/Actions/PickUpCrystalHandler.cs` | REQ-E2, US-10 |
| 2.13 | Implement `LevelUpHeroHandler` and `HealHeroHandler`. | 1.2, 2.3 | `src/mod/Actions/LevelUpHeroHandler.cs`, `HealHeroHandler.cs` | REQ-E2 |
| 2.14 | Implement `ResearchHandler` for queueing research. | 1.2, 2.3 | `src/mod/Actions/ResearchHandler.cs` | REQ-E2, US-8 |
| 2.15 | Implement error handling: malformed JSON returns `ActionResult{success=false}`; Python timeout triggers game pause. | 2.3 | Error paths in `ActionRouter.cs` | REQ-W1, REQ-W2 |
| 2.16 | Implement retry/reconnection logic in `IpcBridge`: if Python TCP client disconnects, accept new connections with BepInEx log warnings. | 2.1 | Reconnection loop in `IpcBridge.cs` | REQ-S3 |
| 2.17 | Create Python IPC client (`ipc_client.py`) using standard `socket` library with length-prefixed JSON framing matching the C# side. | 2.1 | `src/agent/ipc_client.py` | REQ-U3 |
| 2.18 | Write a Python integration test script that: connects, receives one state message (verifying door/passive/faction fields), sends a `MOVE_HERO` command, sends an `OPEN_DOOR` command (with hero in correct room), and asserts success responses. | 2.2, 2.4, 2.5, 2.17 | `tests/test_ipc_integration.py` | REQ-E2, REQ-U7 |
| 2.19 | Write a negative test: send `OPEN_DOOR` with hero NOT in source room; assert error response. | 2.5, 2.17 | Test case in `tests/test_ipc_integration.py` | REQ-W4 |
| 2.20 | Verify end-to-end: launch game with mod, run Python script, observe hero movement and door opening in-game. Document with screenshots/logs. | 2.18 | `docs/ipc-verification.md` | US-2, US-3 |

---

## Phase 3: State Graph Construction

> **Goal:** Build the Python-side environment wrapper that converts raw JSON state (with door edges, passives, merchants, etc.) into a structured NetworkX graph and exposes a Gymnasium-compatible interface.

| # | Task | Dependencies | Deliverable | Reqs Covered |
|---|------|--------------|-------------|--------------|
| 3.1 | Create Python project structure with `pyproject.toml`; declare dependencies (`gymnasium`, `networkx`, `numpy`, `pydantic`). No `pyzmq` needed — IPC uses stdlib `socket`. | — | `src/agent/pyproject.toml` | REQ-U5 |
| 3.2 | Implement `StateParser` class that deserializes the raw JSON state payload, validates against the schema, and produces typed Python dataclasses (matching the C# models including doors, passives, faction, merchants, recruits, dropped items). | 2.17, 3.1 | `src/agent/state_parser.py` | REQ-U3 |
| 3.3 | Implement `GraphBuilder` that converts the `rooms` array into a NetworkX `Graph` with node attributes (powered, auto_powered, has_crystal, modules, unit counts) and **edge attributes** (door open/closed status per connection). | 3.2 | `src/agent/graph_builder.py` | US-5 |
| 3.4 | Add graph utility functions: `shortest_path_to_crystal()`, `shortest_path_to_exit()`, `unpowered_neighbors()`, `room_centrality_scores()`, `bottleneck_rooms()`, `unopened_doors()`, `escape_path_rooms()`. | 3.3 | `src/agent/graph_utils.py` | US-5, US-10 |
| 3.5 | Define the `observation_space` as a `gymnasium.spaces.Dict` containing the graph adjacency matrix, door-state edge matrix, node feature matrix, hero feature vectors (including passives/faction), resource vector, merchant/recruit availability flags. | 3.3, 3.1 | Observation space definition in `dote_env.py` | US-4 |
| 3.6 | Define the `action_space` as `gymnasium.spaces.Dict` with discrete command type, target room, target entity, and item/module identifiers. | 3.1 | Action space definition in `dote_env.py` | US-4 |
| 3.7 | Implement `DotEEnv.__init__()`: create IPC client, define spaces, set initial state, load `GuidelinesConfig` from optional config file. | 2.17, 3.5, 3.6 | `src/agent/dote_env.py` | US-4, US-11 |
| 3.8 | Implement `DotEEnv.reset()`: send UNPAUSE command, wait for first state message, build initial observation. | 3.7 | `reset()` method | US-4 |
| 3.9 | Implement `DotEEnv.step(action)`: translate action to `ActionCommand` JSON, send via IPC, receive next state, compute reward, detect termination (crystal destroyed OR floor escaped). | 3.7, 3.2 | `step()` method | US-4, REQ-E3 |
| 3.10 | Implement `_compute_reward()` per the updated reward function (rooms explored, dust, minor HP loss penalty, crystal destroyed, modules built, mobs killed, floor escaped, hero died with heavy penalty). | 3.9 | Reward computation in `dote_env.py` | US-4 |
| 3.11 | Implement `DotEEnv.close()`: cleanly disconnect ZeroMQ sockets. | 3.7 | `close()` method | US-4 |
| 3.12 | Implement `GuidelinesConfig` loader: read from YAML/JSON config file; allow toggling each guideline on/off. | 3.1 | `src/agent/guidelines_config.py` | US-11, REQ-O4 |
| 3.13 | Write Pytest suite validating Gymnasium API conformance: `check_env()` from `gymnasium.utils.env_checker`. | 3.7–3.11 | `tests/test_dote_env.py` | US-4 |
| 3.14 | Write unit tests for `GraphBuilder` and `graph_utils` with mock room data including loops (all rooms explored, some doors still closed). | 3.3, 3.4 | `tests/test_graph.py` | US-5 |
| 3.15 | Write unit tests for `StateParser` covering merchants, recruits, dropped items, passives, and faction fields. | 3.2 | `tests/test_state_parser.py` | REQ-U3 |

---

## Phase 4: Heuristic Baseline Agent

> **Goal:** Build a finite-state machine controller that can autonomously play through Floor 1 without human intervention, implementing the full macro/micro/escape hierarchy with learning guidelines.

| # | Task | Dependencies | Deliverable | Reqs Covered |
|---|------|--------------|-------------|--------------|
| 4.1 | Implement `BaseAgent` abstract class with `select_action()`, `reset()`, and `GuidelinesConfig` integration. | 3.1, 3.12 | `src/agent/base_agent.py` | US-11 |
| 4.2 | Implement `HeuristicAgent` FSM skeleton with states: `EXPLORE`, `BUILD`, `DEFEND`, `RETREAT`, `ESCAPE`. Define transition conditions. | 4.1 | `src/agent/heuristic_agent.py` | US-6 |
| 4.3 | Implement `EXPLORE` state logic: identify nearest unexplored door (not room — doors can be closed even if room is explored); dispatch a hero to that room then issue `OPEN_DOOR` with that hero present. | 3.4, 4.2 | EXPLORE behavior in `heuristic_agent.py` | US-6, REQ-U7 |
| 4.4 | Implement `BUILD` state logic: after exploration, evaluate available slots and resources; prioritize Industry generators → Food → defensive modules. Queue module repairs for damaged modules. | 3.3, 4.2 | BUILD behavior in `heuristic_agent.py` | US-8 |
| 4.5 | Implement research decision logic: evaluate available research options and queue based on current needs. | 4.4 | Research logic in `heuristic_agent.py` | US-8 |
| 4.6 | Implement power allocation logic: use `room_centrality_scores()` and Dust budget to determine which rooms to power, prioritizing the crystal path. Respect auto-powered rooms. | 3.4, 4.4 | Power management in `heuristic_agent.py` | US-8 |
| 4.7 | Implement hero upgrade logic: level up heroes using food; prioritize Max O'Kane until Operate is unlocked (GL-4). After that, balance upgrades across the team. | 4.2, 3.2 | Upgrade logic in `heuristic_agent.py` | US-8, GL-4 |
| 4.8 | Implement merchant evaluation logic: when merchants are present, assess items against current hero equipment; buy if the item is a meaningful upgrade and dust allows. | 3.2, 4.2 | Merchant logic in `heuristic_agent.py` | US-9, REQ-E8 |
| 4.9 | Implement recruitment logic: when recruitable heroes are present and food allows, dispatch a hero to recruit. Evaluate recruit value based on passives and faction synergy. | 3.2, 4.2 | Recruit logic in `heuristic_agent.py` | US-9 |
| 4.10 | Implement equipment management: after acquiring items (merchant, drops), evaluate which hero benefits most based on slot availability and stat bonuses. Issue `EQUIP_ITEM` commands. | 3.2, 4.2 | Equipment logic in `heuristic_agent.py` | US-9 |
| 4.11 | Implement dust collection logic: when dropped dust is detected, dispatch the nearest available (non-operating) hero to collect it. | 3.2, 3.4, 4.2 | Dust collection in `heuristic_agent.py` | REQ-E7 |
| 4.12 | Implement operator placement logic: heroes with unlocked "Operate" passive are assigned to safe rooms with major modules; avoid moving them unless emergency. (GL-3) | 3.2, 4.2 | Operator logic in `heuristic_agent.py` | REQ-S5, GL-3 |
| 4.13 | Implement `DEFEND` state logic (micro-controller): on wave start, position non-operator heroes in bottleneck rooms to block enemy spawns. Reactively reposition heroes mid-wave if enemy distribution is lopsided (concentrated in one wing vs spread out). Heroes auto-target closest enemy (no focus-fire). | 3.4, 4.2 | DEFEND behavior in `heuristic_agent.py` | US-7, REQ-U6 |
| 4.14 | Implement `RETREAT` state logic: if any hero's HP < threshold (GL-1, default 30%), issue `MOVE_HERO` toward Crystal Room. Transition back to DEFEND when healed or wave ends. | 4.13 | RETREAT behavior in `heuristic_agent.py` | REQ-S2, GL-1 |
| 4.15 | Implement `ESCAPE` state logic — initiation: when no unopened doors remain (REQ-E6) or manually triggered, designate fastest hero as crystal carrier (GL-5). | 3.4, 4.2 | Escape initiation in `heuristic_agent.py` | US-10, REQ-E6, GL-5 |
| 4.16 | Implement `ESCAPE` state logic — power reorganization: recompute lighting to keep exit path powered; de-power dead-end rooms to maximize Dust coverage on the escape route. (GL-6) | 3.4, 4.15 | Power reorg in `heuristic_agent.py` | US-10, GL-6 |
| 4.17 | Implement `ESCAPE` state logic — hero roles: crystal carrier runs straight to exit; other heroes are assigned guard (escort), spawn-block (stand in room), or exit-wait roles. (REQ-S4) | 4.15, 4.16 | Escape roles in `heuristic_agent.py` | US-10, REQ-S4 |
| 4.18 | Implement FSM transition logic: determine current state based on `game_phase`, hero HP ratios, unexplored door count, and escape conditions. | 4.3–4.17 | State transitions in `heuristic_agent.py` | US-6 |
| 4.19 | Implement the main game loop runner (`run_agent.py`): instantiate `DotEEnv`, load `GuidelinesConfig`, create `HeuristicAgent`, loop `step()` until terminated. Support hero selection at game start (GL-2: Max + Gork). | 3.7, 4.2, 3.12 | `src/agent/run_agent.py` | US-6, GL-2 |
| 4.20 | Add logging and metrics collection: turns survived, rooms explored, doors opened, resources gathered, heroes lost, items equipped, merchants visited, per-floor outcome. | 4.19 | `src/agent/metrics.py` | — |
| 4.21 | Run 5 automated Floor 1 playthroughs; record success/failure; tune heuristic thresholds (power budget, retreat HP%, explore priority, operator placement). | 4.19, 4.20 | `docs/baseline-results.md` | Acceptance: 3/5 success |
| 4.22 | Write integration test: mock IPC with recorded state sequences (including merchants, recruits, escape scenario); assert agent produces valid action sequences without crashes. | 4.2, 3.13 | `tests/test_heuristic_agent.py` | US-6 |
| 4.23 | Write unit test for `GuidelinesConfig` toggle: disable all guidelines, verify agent still functions (may perform worse but doesn't crash). | 3.12, 4.2 | `tests/test_guidelines_toggle.py` | REQ-O4 |
| 4.24 | Implement sell logic: when interacting with merchants, evaluate owned items and sell unwanted ones for currency. | 4.8 | Sell logic in `heuristic_agent.py` | REQ-E8 |
| 4.25 | Implement pre-escape inventory management: before initiating escape, move valuable items from shared inventory to backpack (4 slots); equip or sell the rest. (GL-8) | 4.15, 4.10 | Inventory prep in `heuristic_agent.py` | REQ-S8, GL-8 |
| 4.26 | Implement artifact defense logic: track whether artifact-targeting mobs have appeared on the floor; macro-planner gates research on defensibility; micro-controller positions heroes to defend artifact during waves. (GL-7) | 4.6, 4.13 | Artifact defense in `heuristic_agent.py` | REQ-E9, GL-7 |
| 4.27 | Implement crystal-targeting mob detection: when crystal-targeting mobs are observed, shift defensive strategy to prioritize crystal room and adjacent rooms. | 4.13 | Crystal defense in `heuristic_agent.py` | REQ-E12 |
| 4.28 | Implement room item interaction logic: dispatch heroes to trigger free interactables (Chests, Banquets, Science/Industry machines); evaluate cost/benefit for risky interactables (Dust Factory, Cryo Capsule). | 4.3, 4.2 | Item interaction in `heuristic_agent.py` | REQ-E10, REQ-E11 |
| 4.29 | Implement toxic cloud avoidance: micro-controller avoids positioning heroes in rooms with active toxic clouds; macro-controller avoids assigning operators there. | 4.13 | Toxic avoidance in `heuristic_agent.py` | REQ-S7 |
| 4.30 | Implement EMP awareness: don't build modules in rooms currently under EMP; factor EMP history into module distribution decisions. | 4.4 | EMP awareness in `heuristic_agent.py` | REQ-S6 |

---

## Dependency Graph (Critical Path)

```
Phase 1:  1.1 → 1.2 → 1.4──┐
                1.3──────────┼→ 1.11 → 1.12
                1.5──────────┤
                1.6──────────┤
                1.7──────────┤
                1.8──────────┤
                1.9──────────┤
                1.10─────────┘

Phase 2:  1.11 ─→ 2.1 → 2.2 ──────→ 2.18 → 2.19 → 2.20
                    │  → 2.3 → 2.4──┤
                    │         → 2.5──┤
                    │         → 2.6──┤
                    │         → 2.7──┤
                    │         → 2.8──┤
                    │         → 2.9──┤
                    │         → 2.10─┤
                    │         → 2.11─┤
                    │         → 2.12─┤
                    │         → 2.13─┤
                    │         → 2.14─┤
                    │         → 2.15─┘
                    │  → 2.16
                    └──→ 2.17 ──────→ 2.18

Phase 3:  2.17 → 3.1 → 3.2 → 3.3 → 3.4 → 3.5─┐
                         │              3.6──────┼→ 3.7 → 3.8 → 3.9 → 3.10 → 3.13
                         │                       └→ 3.11
                         │              3.12─────→ 3.7
                         └→ 3.15
                  3.3 → 3.14

Phase 4:  3.7 ──→ 4.1 → 4.2 → 4.3──┐
          3.12─→ 4.1    │  → 4.4──┤
                         │  → 4.5──┤
                         │  → 4.6──┤
                         │  → 4.7──┤
                         │  → 4.8──┤
                         │  → 4.9──┤
                         │  → 4.10─┤
                         │  → 4.11─┤
                         │  → 4.12─┤
                         │  → 4.13 → 4.14─┤
                         │  → 4.15 → 4.16 → 4.17─┤
                         │                         ├→ 4.18 → 4.19 → 4.20 → 4.21
                         └→ 4.22
                         └→ 4.23
```

---

## Summary

| Phase | Tasks | Estimated Effort | Key Risk |
|-------|-------|------------------|----------|
| Phase 1 | 12 | 1–2 weeks | Reflection targets may be obfuscated; passive/faction fields may require deeper decompilation |
| Phase 2 | 20 | 2–3 weeks | TCP threading on Unity main thread; .NET 3.5 JSON serialization; many action handlers to validate |
| Phase 3 | 15 | 1–2 weeks | Observation space dimensionality; variable room/door count; door-edge vs node modeling |
| Phase 4 | 30 | 3–5 weeks | Escape orchestration complexity; heuristic tuning; operator vs explorer hero assignment conflicts; artifact defense decision-making |
| **Total** | **77** | **7–12 weeks** | — |

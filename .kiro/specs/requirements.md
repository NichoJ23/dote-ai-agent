# Requirements: Autonomous AI Agent for Dungeon of the ENDLESS

#[[file:master-plan.md]]

---

## 1. User Stories

### US-1: Game State Observation
**As** an AI agent developer,
**I want** the BepInEx mod to extract the full game state (rooms, heroes, mobs, resources, door states, merchants, recruitable heroes) from the Unity runtime each turn,
**So that** the Python agent can make informed decisions without relying on computer vision.

### US-2: Action Injection
**As** an AI agent developer,
**I want** to send action commands from Python that are executed inside the game via native method calls,
**So that** the agent can autonomously control heroes, build modules, manage doors, interact with merchants, and equip items.

### US-3: IPC Communication
**As** an AI agent developer,
**I want** a reliable, low-latency bidirectional communication channel between the C# mod and the Python process,
**So that** state observations and action commands are exchanged in real time without frame drops.

### US-4: Gymnasium Environment Wrapper
**As** an AI/ML researcher,
**I want** the game environment exposed as a standard `gymnasium.Env` interface with `reset()` and `step()` methods,
**So that** I can plug in any RL algorithm or custom controller without rewriting integration code.

### US-5: Room Graph Representation
**As** an AI agent developer,
**I want** the room topology converted into a NetworkX graph with node attributes (power state, auto-powered flag, units, modules, door open/closed per edge),
**So that** graph-based algorithms can reason about connectivity, bottlenecks, and pathfinding.

### US-6: Heuristic Baseline Play
**As** a game AI researcher,
**I want** a finite-state machine macro-planner that can autonomously complete Floor 1,
**So that** I have a working baseline to benchmark future learned policies against.

### US-7: Wave Defense Micro-Control
**As** an AI agent developer,
**I want** the micro-controller to handle real-time hero positioning and retreat logic during enemy waves,
**So that** heroes survive encounters and protect the Crystal. (Note: heroes auto-heal to full after each combat; avoiding hero death matters far more than avoiding damage.)

### US-8: Resource Management & Building
**As** an AI agent developer,
**I want** the macro-planner to allocate resources (Industry, Food, Science, Dust), build/repair modules, and queue research,
**So that** the agent maximizes room infrastructure and hero sustainability.

### US-9: Hero Interaction & Equipment
**As** an AI agent developer,
**I want** the macro-planner to send heroes to collect dropped dust, interact with merchants, recruit new heroes, and equip items optimally,
**So that** the agent takes full advantage of available resources and opportunities.

### US-10: Floor Escape Orchestration
**As** an AI agent developer,
**I want** the macro-planner to orchestrate a floor escape by designating the fastest hero as crystal carrier, reorganizing room power for path safety, and coordinating other heroes as guards,
**So that** the team reliably reaches the exit with the crystal intact.

### US-11: Learning Guidelines
**As** an AI agent developer,
**I want** the heuristic agent to follow configurable gameplay guidelines (hero selection, upgrade priority, operator placement, retreat thresholds),
**So that** early learning is guided toward sound strategies while remaining removable for later optimization.

---

## 2. EARS Requirements (Easy Approach to Requirements Syntax)

### 2.1 Ubiquitous Requirements

| ID | Requirement |
|----|-------------|
| REQ-U1 | The system **shall** extract game state exclusively via C# reflection and method hooks from `Assembly-CSharp.dll`. |
| REQ-U2 | The system **shall not** use computer vision, frame buffer processing, or pixel-based detection at any layer. |
| REQ-U3 | All IPC messages **shall** be serialized as UTF-8 JSON payloads, framed with a 4-byte big-endian length prefix over raw TCP sockets. |
| REQ-U4 | The C# mod **shall** target .NET Framework 3.5 (Unity 5.0.3 Mono runtime) and be loaded via BepInEx (sc2ad patched build). |
| REQ-U5 | The Python agent **shall** require Python 3.10 or higher. |
| REQ-U6 | Heroes **shall** automatically target the closest enemy in their current room; the agent **shall not** issue explicit focus-fire commands. |
| REQ-U7 | Opening a door **shall** require dispatching a hero to the door's source room to perform the interaction. |

### 2.2 Event-Driven Requirements

| ID | Trigger | Requirement |
|----|---------|-------------|
| REQ-E1 | **When** a new game turn begins or a phase transition occurs, | the State Extractor **shall** serialize the current game state and publish it on TCP port 5555 within 50ms. |
| REQ-E2 | **When** the Python agent sends an action command on port 5556, | the Action Injector **shall** parse and execute the command within the same game tick. |
| REQ-E3 | **When** the Crystal is destroyed, | the environment wrapper **shall** return `terminated=True` and a reward penalty of −100. |
| REQ-E4 | **When** a door is opened and enemies spawn, | the micro-controller **shall** transition to wave-defense mode and begin tactical hero positioning. |
| REQ-E5 | **When** all enemies in the current wave are defeated, | the micro-controller **shall** transition back to idle and yield control to the macro-planner. |
| REQ-E6 | **When** no unexplored doors remain on the floor, | the macro-planner **shall** automatically initiate the floor escape sequence. |
| REQ-E7 | **When** a monster drops dust in a room, | the macro-planner **shall** dispatch the nearest available hero to collect it. |
| REQ-E8 | **When** a merchant is present on the floor, | the macro-planner **shall** evaluate available items for purchase AND evaluate owned items for selling. |
| REQ-E9 | **When** an artifact-targeting mob type is detected on the floor, | the macro-planner **shall** assess whether research can be safely conducted and the micro-controller **shall** defend the artifact during waves. |
| REQ-E10 | **When** a room contains an interactable item (Chest, Banquet, Science/Industry machine), | the macro-planner **shall** dispatch a hero to trigger it. |
| REQ-E11 | **When** a room contains a risky interactable (Dust Factory, Cryo Capsule), | the macro-planner **shall** evaluate cost/benefit before triggering. |
| REQ-E12 | **When** crystal-targeting mobs are detected on the floor, | the macro-planner **shall** shift defensive strategy to prioritize crystal room protection. |

### 2.3 State-Driven Requirements

| ID | Condition | Requirement |
|----|-----------|-------------|
| REQ-S1 | **While** the game is in "tactical_pause" phase, | the macro-planner **shall** evaluate and issue build, repair, research, recruit, equip, and exploration commands. |
| REQ-S2 | **While** a hero's HP drops below 30% of max HP (guideline, removable), | the micro-controller **shall** issue a retreat command toward the Crystal Room. |
| REQ-S3 | **While** the TCP connection is not established, | the C# mod **shall** retry connection every 2 seconds and log warnings to the BepInEx console. |
| REQ-S4 | **While** a floor escape is in progress, | the crystal carrier **shall** move directly to the exit without stopping, and other heroes **shall** be assigned guard, spawn-block, or exit-wait roles. |
| REQ-S5 | **While** a hero has the "Operate" passive ability, | the macro-planner **shall** prefer placing that hero in a safe room operating a major module and avoid issuing move commands that cancel the operation. |
| REQ-S6 | **While** a room suffers an EMP effect, | the agent **shall** not build new modules in that room and **shall** note modules there are non-functional. |
| REQ-S7 | **While** a room has a toxic cloud active, | the micro-controller **shall** avoid positioning heroes there unless no alternative exists. |
| REQ-S8 | **While** there are items in the shared inventory before floor escape, | the macro-planner **shall** equip or move valuable items to the backpack (4 slots) since shared inventory is lost on floor exit. |

### 2.4 Unwanted-Behaviour Requirements

| ID | Condition | Requirement |
|----|-----------|-------------|
| REQ-W1 | **If** the Python process does not respond within 5 seconds, **then** the C# mod **shall** pause the game and log an error, preventing uncontrolled gameplay. |
| REQ-W2 | **If** a malformed action command is received, **then** the Action Injector **shall** discard the command and return an error response JSON with a descriptive message. |
| REQ-W3 | **If** the game state serialization encounters a null reference, **then** the extractor **shall** substitute a safe default value and flag the field in the payload metadata. |
| REQ-W4 | **If** the agent attempts to open a door with no hero in the source room, **then** the Action Injector **shall** reject the command and return an error indicating a hero must be present. |

### 2.5 Optional/Feature Requirements

| ID | Requirement |
|----|-------------|
| REQ-O1 | The system **should** support a configurable tick rate for state extraction (default: every phase transition). |
| REQ-O2 | The system **should** expose a debug dashboard endpoint that streams state JSON to a local web viewer. |
| REQ-O3 | The system **may** support recording game sessions as replay files (JSON Lines format) for offline training. |
| REQ-O4 | The learning guidelines (hero selection, retreat threshold, upgrade priority) **should** be externalized to a configuration file so they can be toggled or removed. |

---

## 3. Learning Guidelines (Phase 4 Heuristics — Removable)

These guidelines constrain the heuristic agent during early development. They may be relaxed or removed in later phases to allow the agent to discover optimal strategies independently.

| ID | Guideline | Rationale |
|----|-----------|-----------|
| GL-1 | Retreat any hero below 30% HP toward the Crystal Room. | Prevents hero death; a more advanced agent may factor remaining mobs, module support, etc. |
| GL-2 | At game start, select **Max O'Kane** and **Gork** as the initial hero pair. | Strong early-game synergy; Max gains Operate at level-up. |
| GL-3 | Heroes with an "Operate" passive should be stationed in a relatively safe room operating a major module; avoid issuing moves that cancel operation. | Operate bonuses are significant and fragile. |
| GL-4 | Prioritize upgrading Max O'Kane until he unlocks Operate. | Unlocking Operate early maximizes its floor-wide benefit. |
| GL-5 | During floor escape, assign crystal-carry to the fastest hero. | Minimizes exposure time during the dangerous escape run. |
| GL-6 | During floor escape, reorganize lighting to keep the path to exit powered; de-power dead-end rooms. | Reduces spawn density along the escape route. |
| GL-7 | Do not start research if artifact-targeting mobs have been observed on the current floor and the artifact room cannot be adequately defended. | Prevents wasted science on cancelled research. |
| GL-8 | Before initiating floor escape, move valuable unequipped items from shared inventory to backpack. | Shared inventory is lost on floor exit; backpack persists. |

---

## 4. Acceptance Criteria Summary

| Criterion | Validation Method |
|-----------|-------------------|
| State extraction covers all target classes (Dungeon, Room, Hero, Mob, Player resources) including door states, passives, and factions | Unit test asserting non-null fields in serialized JSON |
| Round-trip IPC latency < 100ms for state + action cycle | Stopwatch measurement over 100 consecutive turns |
| Hero door-open command requires hero presence in source room; rejected otherwise | Integration test with hero in wrong room |
| Gymnasium `step()` returns valid observation, reward, terminated, truncated, info tuple | Pytest conformance test against Gymnasium API |
| Macro-planner correctly dispatches heroes for dust collection, merchant interaction, and recruitment | Unit tests with mock state containing merchants/dust/recruits |
| Floor escape designates fastest hero as carrier and re-powers the exit path | Integration test with mock floor state |
| Heuristic agent completes Floor 1 without Crystal destruction in 3/5 runs | Automated playthrough with success rate metric |
| Learning guidelines can be toggled off via config without code changes | Config file test with guidelines disabled |

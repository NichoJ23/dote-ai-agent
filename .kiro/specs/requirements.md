# Requirements: Autonomous AI Agent for Dungeon of the ENDLESS

#[[file:master-plan.md]]

---

## 1. User Stories

### US-1: Game State Observation
**As** an AI agent developer,
**I want** the BepInEx mod to extract the full game state (rooms, heroes, mobs, resources) from the Unity runtime each turn,
**So that** the Python agent can make informed decisions without relying on computer vision.

### US-2: Action Injection
**As** an AI agent developer,
**I want** to send action commands from Python that are executed inside the game via native method calls,
**So that** the agent can autonomously control heroes, build modules, and manage doors.

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
**I want** the room topology converted into a NetworkX graph with node attributes (power state, units, modules),
**So that** graph-based algorithms can reason about connectivity, bottlenecks, and pathfinding.

### US-6: Heuristic Baseline Play
**As** a game AI researcher,
**I want** a finite-state machine macro-planner that can autonomously complete Floor 1,
**So that** I have a working baseline to benchmark future learned policies against.

### US-7: Wave Defense Micro-Control
**As** an AI agent developer,
**I want** the micro-controller to handle real-time hero positioning, focus-fire, and retreat logic during enemy waves,
**So that** heroes survive encounters and protect the Crystal.

### US-8: Resource Management
**As** an AI agent developer,
**I want** the macro-planner to allocate resources (Industry, Food, Science, Dust) based on current state and production rates,
**So that** the agent maximizes room infrastructure and hero sustainability.

---

## 2. EARS Requirements (Easy Approach to Requirements Syntax)

### 2.1 Ubiquitous Requirements

| ID | Requirement |
|----|-------------|
| REQ-U1 | The system **shall** extract game state exclusively via C# reflection and method hooks from `Assembly-CSharp.dll`. |
| REQ-U2 | The system **shall not** use computer vision, frame buffer processing, or pixel-based detection at any layer. |
| REQ-U3 | All IPC messages **shall** be serialized as UTF-8 JSON payloads. |
| REQ-U4 | The C# mod **shall** target .NET Framework 4.7.2 and be loaded via BepInEx 5.4 (Mono). |
| REQ-U5 | The Python agent **shall** require Python 3.10 or higher. |

### 2.2 Event-Driven Requirements

| ID | Trigger | Requirement |
|----|---------|-------------|
| REQ-E1 | **When** a new game turn begins or a phase transition occurs, | the State Extractor **shall** serialize the current game state and publish it on ZeroMQ port 5555 within 50ms. |
| REQ-E2 | **When** the Python agent sends an action command on port 5556, | the Action Injector **shall** parse and execute the command within the same game tick. |
| REQ-E3 | **When** the Crystal is destroyed, | the environment wrapper **shall** return `terminated=True` and a reward penalty of −100. |
| REQ-E4 | **When** a door is opened and enemies spawn, | the micro-controller **shall** transition to wave-defense mode and begin tactical hero management. |
| REQ-E5 | **When** all enemies in the current wave are defeated, | the micro-controller **shall** transition back to idle and yield control to the macro-planner. |

### 2.3 State-Driven Requirements

| ID | Condition | Requirement |
|----|-----------|-------------|
| REQ-S1 | **While** the game is in "tactical_pause" phase, | the macro-planner **shall** evaluate and issue build, power, and exploration commands. |
| REQ-S2 | **While** a hero's HP drops below 30% of max HP, | the micro-controller **shall** issue a retreat command toward the Crystal Room. |
| REQ-S3 | **While** the ZeroMQ connection is not established, | the C# mod **shall** retry connection every 2 seconds and log warnings to the BepInEx console. |

### 2.4 Unwanted-Behaviour Requirements

| ID | Condition | Requirement |
|----|-----------|-------------|
| REQ-W1 | **If** the Python process does not respond within 5 seconds, **then** the C# mod **shall** pause the game and log an error, preventing uncontrolled gameplay. |
| REQ-W2 | **If** a malformed action command is received, **then** the Action Injector **shall** discard the command and return an error response JSON with a descriptive message. |
| REQ-W3 | **If** the game state serialization encounters a null reference, **then** the extractor **shall** substitute a safe default value and flag the field in the payload metadata. |

### 2.5 Optional/Feature Requirements

| ID | Requirement |
|----|-------------|
| REQ-O1 | The system **should** support a configurable tick rate for state extraction (default: every phase transition). |
| REQ-O2 | The system **should** expose a debug dashboard endpoint that streams state JSON to a local web viewer. |
| REQ-O3 | The system **may** support recording game sessions as replay files (JSON Lines format) for offline training. |

---

## 3. Acceptance Criteria Summary

| Criterion | Validation Method |
|-----------|-------------------|
| State extraction covers all target classes (Dungeon, Room, Hero, Mob, Player resources) | Unit test asserting non-null fields in serialized JSON |
| Round-trip IPC latency < 100ms for state + action cycle | Stopwatch measurement over 100 consecutive turns |
| Hero movement command from Python results in observable hero position change in-game | Integration test with mock game state |
| Gymnasium `step()` returns valid observation, reward, terminated, truncated, info tuple | Pytest conformance test against Gymnasium API |
| Heuristic agent completes Floor 1 without Crystal destruction in 3/5 runs | Automated playthrough with success rate metric |

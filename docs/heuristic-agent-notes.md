# Heuristic Agent Development Notes

## Current State (as of this session closing)

The heuristic agent can successfully:
- Start a new game via IPC
- Play through floor 1 (open doors, build modules, fight, research, buy from merchants)
- Initiate escape sequence (depower, repower escape path, send Gork to exit, Max picks up crystal, moves to exit, plugs crystal)
- Transition to floor 2 via NEXT_FLOOR command

Branch: `heuristic-agent` on GitHub (NichoJ23/dote-ai-agent)

## Architecture

### Python Side
- `src/agent/heuristic_agent.py` — FSM controller with 10-step macro decision tree
- `src/agent/run_agent.py` — Game loop runner with CLI, file logging, hero arrival/item pickup waits
- `src/agent/base_agent.py` — Abstract base class for agents
- `src/agent/metrics.py` — FloorMetrics + RunMetrics tracking
- `src/agent/state_parser.py` — Pydantic models matching the C# wire format
- `src/agent/graph_builder.py` / `graph_utils.py` — NetworkX graph for pathfinding

### C# Mod Side
- `src/mod/Plugin.cs` — Main Unity plugin, periodic state push (1s), post-action state push, 30s timeout, 2x timeScale
- `src/mod/Hooks/DungeonHook.cs` — Room indexing uses `OpeningIndex + 1` for stable IDs (game shuffles room array during waves)
- `src/mod/StateManager.cs` — Extracts full state including research costs, recruit costs, time_scale
- `src/mod/Actions/` — All action handlers (MOVE_HERO, OPEN_DOOR, BUILD_MODULE, etc.)

### Key Action Commands
- `OPEN_DOOR` — params: hero_name, from_room_index, target_room_index (-1 for any door from that room)
- `MOVE_HERO` — params: hero_name, target_room_index
- `BUILD_MODULE` — params: room_index, module_name, slot_type
- `POWER_ROOM` / `UNPOWER_ROOM` — params: room_index
- `PICK_UP_CRYSTAL` — params: hero_name (hero must be in crystal room)
- `PLUG_CRYSTAL_EXIT` — params: hero_name (hero must be in exit room carrying crystal)
- `NEXT_FLOOR` — no params (call after IsLevelOver, skips dialogue)
- `RESEARCH` — params: blueprint_name (needs artifact on floor, no hero-in-room requirement)
- `BUY_FROM_MERCHANT` — params: hero_name, item_name, merchant_room_index
- `RECRUIT_HERO` — params: recruiter_hero_name, recruit_name

### Module Blueprint IDs (confirmed at runtime)
- Industry Generator: `MajorModule_Major0002_LVL1`
- Prisoner Prod (minor turret): `MinorModule_Minor0004_LVL1`
- Pattern: `MajorModule_Major####_LVL#` / `MinorModule_Minor####_LVL#`

### Room Indexing
- Crystal/start room has `OpeningIndex = -1` in the game, stored as index `0` (OpeningIndex + 1)
- First opened room = index `1`, second = index `2`, etc.
- The game shuffles `dungeon.OpenedRooms` during wave spawning — NEVER use list position
- `GetRoomByOpeningIndex(roomIndex)` does reverse lookup: `targetOpeningIndex = roomIndex - 1`
- Room index `-1` is the sentinel for "not found / unopened"

### State Push Behavior
- Mod pushes state every 1 second (periodic)
- Mod pushes state after every successful action
- Mod pushes state on turn change or phase change (Strategy ↔ Action)

## Macro-Planner Decision Tree (10 steps)
1. Open door from crystal room (if any)
2. Power closest unpowered rooms (excess dust = total - powered*10)
3. Build 1 industry generator on newest room (once per floor)
4. Build prisoner prods in room 1 (fill all minor slots)
5. Research most expensive affordable blueprint (needs artifact on floor)
6. Collect dropped items (send hero, wait for pickup)
7. Recruit heroes (if food allows, uses actual recruit_cost_food)
8. Buy cheapest merchant item (dispatch Gork > Max to merchant room)
8.5. Equip items from inventory (Max first, then Gork)
9. Position Gork in room 1 (skip if Gork is only hero alive)
10. Open any remaining door (use Max, fall back to any hero if Max dead)

## Escape Sequence
1. Depower all non-auto rooms NOT on escape path
2. Power escape path rooms
3. Send Gork to exit room
4. Move Max to crystal room
5. PICK_UP_CRYSTAL
6. Move Max to exit room
7. PLUG_CRYSTAL_EXIT (plugs crystal on exit slot)
8. State shows `PluggedOnExitSlot` → floor complete
9. Wait 3s → NEXT_FLOOR → next dungeon loads

## Micro-Controller (Action Phase)
- DEFEND: Send all heroes to room 1 (fortified with prisoner prods)
- RETREAT: Heroes below 50% HP go to room 1. If room 1 has mobs, fall back to crystal room.
- No `_moves_issued_this_turn` check during DEFEND/RETREAT/ESCAPE — heroes move freely hop by hop
- `_wait_for_hero_arrival` blocks until hero physically arrives before issuing next command

## Problems Encountered (Critical for RL Agent Design)

### 1. Hero Movement is NOT Instant
Heroes walk between rooms over real time. MOVE_HERO returns OK immediately but the hero takes seconds to arrive. Any action requiring the hero to be in a specific room MUST wait for arrival first.
- **Solution**: `_wait_for_hero_arrival` polls state every 2s until `hero.room_index == target`
- **RL implication**: Movement actions have delayed effects. The RL agent needs to either: (a) use a step-per-action design with built-in waits, or (b) understand that sequential actions take variable time.

### 2. "Hero is not usable" During Door Opening Animation
After OPEN_DOOR, the hero is briefly "not usable" (playing the door-open animation, entering new room). Any command sent during this ~2s window fails.
- **Solution**: Retry with back-off until hero becomes usable again. The periodic state push eventually shows the hero in the new room.
- **RL implication**: Some actions have cooldowns. The RL agent will see failed actions that later succeed.

### 3. Room Indices Get Shuffled
The game shuffles `dungeon.OpenedRooms` in-place during wave spawning. Using list index as room ID breaks everything.
- **Solution**: Use `Room.OpeningIndex` (assigned once when discovered, never changes). Mod does `OpeningIndex + 1` as the stable room ID.
- **RL implication**: Room IDs in the observation space are stable across turns/phases.

### 4. State Staleness Between Actions
The mod pushes state after each action, but if you fire multiple actions instantly, later ones operate on stale state.
- **Solution**: After MOVE_HERO, call `_wait_for_hero_arrival` to get fresh state before next action. For instant actions (BUILD, POWER), the post-action state push is immediate.
- **RL implication**: The RL environment's `step()` should always wait for fresh state after executing an action.

### 5. Crystal State Confusion
`crystal_state == "Unplugged"` means BOTH "hero is carrying it" and "crystal destroyed". You must check `any(h.has_crystal for h in heroes)` to distinguish.
- **Solution**: `is_game_over` checks Unplugged + no hero carrying it.
- **RL implication**: The game-over detection logic must account for the crystal being in transit.

### 6. Item Pickup Timing
Heroes auto-collect items when entering a room, but it takes a few seconds. The state may not immediately reflect the pickup.
- **Solution**: Fixed wait of `4.0 / time_scale` seconds after hero arrives at a room with items.
- **RL implication**: Moving to a room with items is a multi-step process (move + wait). The reward for collecting shouldn't fire until items actually disappear from state.

### 7. Research Requires Artifact
Research can only be initiated if an artifact exists on the floor. The artifact state is `has_artifact: bool` on room data. Artifact "busy" state (already researching) is only learned via failed action.
- **RL implication**: The observation space should include artifact_room_index and is_researching.

### 8. Action Timeouts
The mod pauses the game if no action is received within 30 seconds during Action phase. This prevents the game from running uncontrolled while the agent processes.
- **RL implication**: The RL agent must respond within 30s or the game pauses. Not an issue for automated step() calls.

### 9. Time Scale
`Time.timeScale = 2f` speeds up game 2x. Item pickup wait uses `4.0 / time_scale`. The mod reports `time_scale` in the state payload.
- **RL implication**: Training could use higher timeScale (4x, 8x) for faster iteration. Need to ensure IPC timing still works.

### 10. Floor Transition
After escaping, the game shows a lift/dialogue sequence. `NEXT_FLOOR` command skips it and calls `StartNextLevelSinglePlayerGame()`. Need a 3s wait before sending it (game needs time to set up the panel).
- **RL implication**: Floor transitions are a separate "meta-action" outside the normal step loop.

## Uncommitted Changes
None — all work pushed to `heuristic-agent` branch on GitHub (NichoJ23/dote-ai-agent).

## Recent Session Changes (hero busy-flag system + game speed)

### Hero Busy-Flag System
Replaced the old blocking wait pattern (`_wait_for_hero_arrival`, `_wait_for_item_pickup`) with a non-blocking busy-flag system that allows concurrent hero actions:

- `_hero_busy` dict maps hero_name → `{"action": "move"|"repair"|"awaiting_pickup", "target_room": int}`
- Heroes marked busy are excluded from `_get_available_heroes()` — the other hero gets tasks
- `_update_busy_flags(state)` clears flags when heroes arrive at target room
- When arriving at a room with items, transitions to `awaiting_pickup` — clears only when items gone AND `is_gathering_item=false`
- Multi-hop moves: busy flag target set to final destination, `_continue_multi_hop_moves()` issues next hops automatically
- WAIT sentinel returned when coordinated actions (open door, pick up crystal) need all heroes ready
- All busy flags cleared when combat starts (heroes move freely during Action phase)

### Item Pickup Fix
- Root cause: game uses `base.Invoke("AcquireItem", itemGatheringDuration)` — delayed acquisition. Moving hero during this window calls `CancelItemGathering()`.
- Fix: exposed `hero.gatheringItem != null` as `is_gathering_item` in state (via reflection). Agent won't clear `awaiting_pickup` until both items are gone AND `is_gathering_item=false`.

### Game Speed (Time.timeScale)
- `Time.timeScale = 2f` enforced every frame in `Update()` (game resets it on unpause/transitions)
- State push interval: `1.0/timeScale` during Strategy, `0.5/timeScale` during Action
- Drain loop capped at 2s wall-clock to prevent blocking at high push rates

### Escape Sequence
- Escape initiation moved to step 9.5 in decision tree (after item collection, merchant, positioning)
- Won't initiate escape while any hero is busy
- Floor transition: waits for `floor > current_floor` in state (not just rooms > 0)
- `DungeonHook.ExtractState()` re-fetches dungeon singleton each call for floor transitions

### Combat Healing
- `_try_heal_in_combat()` heals most wounded hero (below 30% HP) using up to half available food
- Runs at top of both `_handle_defend` and `_handle_retreat`

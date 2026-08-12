# IPC Verification: Phase 2 End-to-End Results

## Summary

Phase 2 establishes two-way TCP communication between the BepInEx mod (C#) and the Python AI agent. All 20 tasks are verified and working in-game.

## Architecture

```
Game Process (Unity Mono)          Python Agent
┌─────────────────────┐            ┌─────────────────┐
│  BepInEx Plugin     │            │  IpcClient      │
│  ┌───────────────┐  │  TCP 5555  │  (ipc_client.py)│
│  │ IpcBridge     │──┼──(state)──>│                 │
│  │               │<─┼─(actions)──│                 │
│  │ ActionRouter  │  │  TCP 5556  │                 │
│  └───────────────┘  │            └─────────────────┘
└─────────────────────┘
```

- **Port 5555**: State push (mod → Python). Sends full GameStatePayload as JSON on turn/phase change or new connection.
- **Port 5556**: Action request/response (Python → mod → Python). Python sends ActionCommand, mod replies with ActionResult.
- **Framing**: 4-byte big-endian length prefix + UTF-8 JSON payload.

## Verified Capabilities

### State Extraction (Port 5555)
All game state fields verified in integration test output:
- Turn, floor, game phase, crystal state
- Resources (food, industry, science, dust, per-turn rates, power cost)
- Rooms (power, auto-power, adjacency, modules, unit counts, EMP, artifacts)
- Closed doors (room1, room2, is_opening)
- Heroes (name, faction, room, HP, level, active/passive skills, equipment, operating/crystal status)
- Mobs (type, room, HP, target type)
- Merchants (room, currency, item inventory with costs)
- Recruitable heroes (name, faction, room, passives, HP)
- Dropped items (type, name, room, dust amount)
- Inventory (backpack + shared, with name/rarity/category)
- Researchable blueprints (currently available research options)

### Action Handlers (Port 5556)

| Command | Handler | Verified |
|---------|---------|----------|
| MOVE_HERO | MoveHeroHandler | Hero walks to target room |
| OPEN_DOOR | OpenDoorHandler | Hero walks to door, triggers full room reveal + mob spawn |
| BUILD_MODULE | BuildModuleHandler | Module built in room, auto-powers if needed |
| REPAIR_MODULE | RepairModuleHandler | Moves repair-capable hero to room (auto-repair) |
| POWER_ROOM | PowerRoomHandler | Room powers via TogglePower (finds power path) |
| UNPOWER_ROOM | UnpowerRoomHandler | Room unpowers (rejects auto-powered/start rooms) |
| RECRUIT_HERO | RecruitHeroHandler | Instant recruitment, food deducted |
| BUY_FROM_MERCHANT | BuyFromMerchantHandler | Item purchased via merchant RPC |
| EQUIP_ITEM | EquipItemHandler | Item equipped from inventory to best slot |
| UNEQUIP_ITEM | UnequipItemHandler | Item removed from slot to inventory |
| COLLECT_ITEM | CollectItemHandler | Hero moves to item room (auto-collect) |
| PICK_UP_CRYSTAL | PickUpCrystalHandler | Hero walks to crystal, unplugs it |
| LEVEL_UP_HERO | LevelUpHeroHandler | Hero levels up, verifies level changed |
| HEAL_HERO | HealHeroHandler | Hero healed, food deducted |
| RESEARCH | ResearchHandler | Blueprint researched at artifact |

### Error Handling
- Malformed JSON → `{success: false, error: "Malformed JSON..."}`
- Unknown command → `{success: false, error: "Unknown command: ..."}`
- Failed preconditions → `{success: false, error: "<specific reason>"}`
- Python timeout (5s during Action phase) → game pauses via SetGamePause
- Agent responds → game resumes automatically

### Reconnection
- Client disconnect detected proactively (Poll + Peek on both ports)
- New connections accepted immediately after disconnect
- State pushed to new client on connect (no wait for turn change)
- Works in both directions: game first or script first

## Test Scripts

| Script | Tests |
|--------|-------|
| `scripts/test_ipc_receive.py` | State receive + field validation |
| `scripts/test_action_routing.py` | Unknown command, malformed JSON, missing fields |
| `scripts/test_move_hero.py` | Valid move, invalid hero, invalid room |
| `scripts/test_open_door.py` | REQ-W4 validation, valid door open |
| `scripts/test_build_module.py` | Build with real blueprint, invalid room, repair validation |
| `scripts/test_power_room.py` | Power/unpower, auto-power rejection |
| `scripts/test_recruit_hero.py` | Same-room validation, valid recruitment |
| `scripts/test_buy_from_merchant.py` | Room validation, valid purchase |
| `scripts/test_equip_item.py` | Equip from inventory, unequip, invalid item |
| `scripts/test_unequip_item.py` | Valid unequip |
| `scripts/test_collect_item.py` | Move to item room |
| `scripts/test_pick_up_crystal.py` | Crystal room validation, crystal pickup |
| `scripts/test_levelup_heal.py` | Level up with verification, heal |
| `scripts/test_research.py` | Blueprint validation, artifact presence |
| `scripts/test_timeout_pause.py` | 5s timeout → pause, action → resume |
| `scripts/test_reconnection.py` | Disconnect/reconnect both ports |
| `scripts/test_ipc_client.py` | IpcClient class: connect, send, receive, context manager |
| `tests/test_ipc_integration.py` | Full round-trip: state + MOVE_HERO + OPEN_DOOR |

## Key Implementation Notes

1. **Blueprint names** follow pattern `MajorModule_Major####_LVL#` / `MinorModule_Minor####_LVL#`. Available options exposed via `researchable_blueprints` in state.
2. **Merchant purchases** must use the merchant's RPC path (`SendRPCToServer`), not `dungeon.RequestBuyItem()` directly.
3. **Door opening** must use `hero.MoveToDoor()` for full room reveal. `Door.OpenByHeroOrMob()` is too low-level.
4. **Items are auto-collected** when a hero stands in the room — no explicit pickup interaction needed.
5. **Repair is automatic** when a hero with the Repair passive enters a room with damaged modules.
6. **Game pause** uses `IGameControlService.SetGamePause()`, not `Time.timeScale`.
7. **Dead connection detection** requires active Poll+Peek probing since TCP doesn't notify of remote close.

## Python IPC Client

`src/agent/ipc_client.py` provides:
- `IpcClient.connect()` / `disconnect()` with retry
- `receive_state(timeout)` — blocks for next state
- `send_action(command, params)` — sends command, waits for result  
- `wait_for_state(condition, timeout)` — loops until condition met
- Context manager support (`with IpcClient() as client:`)

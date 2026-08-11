# Project Steering & Constraints

## Local Paths
- **Game install:** `C:\Program Files (x86)\Steam\steamapps\common\Dungeon of the Endless\`
- **Decompiled source:** `C:\Users\nicho\Documents\Programming\Kiro\Assembly-CSharp\`
- **Build command:** `& "C:\Program Files\dotnet\dotnet.exe" build` (run from `src/mod/`)

## Environment & Tech Stack
- **C# Mod:** .NET Framework 3.5 / Unity 5.0.3 Mono, BepInEx (sc2ad patched build for DotE), raw TCP sockets.
- **Python Agent:** Python 3.10+, `gymnasium`, `networkx`, `stable-baselines3`.
- **IPC:** Length-prefixed JSON over raw TCP sockets (port 5555 state, port 5556 actions). No ZeroMQ/NetMQ (incompatible with game's .NET 3.5 Mono runtime).

## Architecture Rules
- Do NOT use computer vision or frame buffer processing.
- All game states MUST be extracted directly via C# reflection/hooks from `Assembly-CSharp.dll` and sent as JSON over TCP port 5555.
- All actions MUST be received over TCP port 5556 and executed via native method calls.
- C# code MUST target .NET 3.5 — no async/await, no null-conditional operators (`?.`), no string interpolation (`$""`), no LINQ extensions beyond what's available in System.Core 3.5.

## Coding Standards
- C# code must be organized into decoupled manager hooks (`DungeonHook`, `HeroHook`).
- Python code must adhere to standard Gymnasium `Env` API conventions (`reset()`, `step()`).
- C# serialization must use a .NET 3.5-compatible JSON library (e.g., MiniJSON, SimpleJSON, or manual serialization).

## Testing Practice
- Write a test script after every task is completed, before moving to the next task.
- Test scripts go in `scripts/` (for in-game smoke tests) or `tests/` (for unit/integration tests).
- Name tests clearly to indicate which task they validate (e.g., `test_ipc_receive.py` for 2.1+2.2).
- This enables per-task debugging: if a test fails, we know exactly which code introduced the issue.

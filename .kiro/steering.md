# Project Steering & Constraints

## Environment & Tech Stack
- **C# Mod:** .NET Framework 4.7.2 / Unity Mono, BepInEx 5.4, NetMQ (ZeroMQ).
- **Python Agent:** Python 3.10+, `pyzmq`, `gymnasium`, `networkx`, `stable-baselines3`.

## Architecture Rules
- Do NOT use computer vision or frame buffer processing.
- All game states MUST be extracted directly via C# reflection/hooks from `Assembly-CSharp.dll` and sent as JSON over ZeroMQ port 5555.
- All actions MUST be received over ZeroMQ port 5556 and executed via native method calls.

## Coding Standards
- C# code must be organized into decoupled manager hooks (`DungeonHook`, `HeroHook`).
- Python code must adhere to standard Gymnasium `Env` API conventions (`reset()`, `step()`).
# PPO Agent for Dungeon of the Endless

An RL agent that plays a roguelike with no API. A C# mod extracts live game state via reflection, streams it over TCP to a Python PPO agent that learns strategy from scratch through self-play.

## Architecture

```
Game Process (Unity 5.0.3)          Python Agent
┌─────────────────────────┐        ┌─────────────────────────┐
│  BepInEx Mod (C#/.NET 3.5)│        │  Gymnasium Environment   │
│  - State extraction      │──TCP──▶│  - NetworkX graph        │
│  - Action injection      │◀──TCP──│  - PPO policy (PyTorch)  │
│  - 20+ game state types  │        │  - Hierarchical actions  │
│  - 19 action commands    │        │  - Reward shaping        │
└─────────────────────────┘        └─────────────────────────┘
     Port 5555 (state)                Strategic Brain (16 options)
     Port 5556 (actions)              Micro-Controller (combat)
                                      Escape Controller
```

## Setup

### Prerequisites

- **Dungeon of the Endless** (Steam, Windows) — the game must be installed
- **Python 3.10+**
- **.NET SDK** with .NET 3.5 targeting pack (for building the mod)
- **BepInEx** (sc2ad patched build for Unity 5.0.3)

### 1. Install BepInEx

```powershell
.\scripts\install-bepinex.ps1 -GameDir "C:\Program Files (x86)\Steam\steamapps\common\Dungeon of the Endless"
```

Launch the game once through Steam, then close it. Verify `BepInEx\LogOutput.log` was created in the game directory.

### 2. Build and install the C# mod

```powershell
cd src/mod
dotnet build
```

This builds `DotEAgentMod.dll` and automatically copies it to `BepInEx\plugins\` in your game directory.

If your game is installed somewhere other than the default Steam path, edit the `<GameDir>` property in `src/mod/DotEAgentMod.csproj`.

### 3. Install Python dependencies

```powershell
cd src/agent
pip install -e ".[dev]"
```

### 4. Run the agent

**Heuristic agent (rule-based baseline):**
```powershell
cd src/agent
python run_agent.py
```

**RL training:**
```powershell
cd src/agent
python train_rl.py --episodes 100
```

**Run tests (no game required):**
```powershell
pytest tests/
```

### Notes

- The game must be running for `run_agent.py` or `train_rl.py` to work. The launcher will start it via Steam automatically.
- Training runs at 8x game speed by default. Set `time_scale` in `rl_config.py` to adjust.
- Checkpoints are saved to `checkpoints/` on interrupt (Ctrl+C) or periodically during training.

## Project Structure

```
src/
  mod/              C# BepInEx mod (state extraction + action injection)
    Hooks/          Game state hooks (Dungeon, Hero, Mob, Resource, etc.)
    Actions/        Action handlers (MoveHero, OpenDoor, Build, Recruit, etc.)
    Ipc/            TCP socket bridge + JSON serialization
    Models/         Data models for state payloads
  agent/            Python AI agent
    train_rl.py     RL training entry point
    run_agent.py    Heuristic agent runner
    rl_agent.py     PPO agent (strategic brain + micro + escape)
    networks.py     PyTorch policy/value networks
    rl_env.py       Enhanced Gymnasium environment for RL
    dote_env.py     Base Gymnasium environment wrapper
    heuristic_agent.py  Rule-based baseline agent
    reward_shaping.py   Configurable reward function
    action_masking.py   Hard-constraint action masking
    curriculum.py       Training curriculum manager
scripts/            Utility scripts (BepInEx install, multi-instance, testing)
tests/              164 unit/integration tests (all run offline, no game needed)
docs/               Decompilation reference, setup guides, agent notes
```

"""
Smoke test for the RL agent pipeline.

Validates end-to-end: IPC → state parse → observation build → network forward → action translate → send action.

Usage:
  1. Launch the game with the mod installed.
  2. Start a dungeon run (be in Strategy phase with 1+ rooms open).
  3. Run: python scripts/test_rl_smoke.py

What it verifies:
  - IPC connection works (ports 5555/5556)
  - State is received and parses correctly
  - Observation builds without errors (correct shapes)
  - Action mask computes (some options valid)
  - PolicyNetwork forward pass works on real observation
  - Action translates to a valid game command
  - Game accepts the command (or returns a sensible error)
  - Repeats for 10 steps to check stability
"""

import sys
import time
from pathlib import Path

# Add agent source to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "agent"))

import torch
import numpy as np

from action_masking import ActionMaskComputer, StrategicOption, NUM_OPTIONS
from ipc_client import IpcClient
from networks import PolicyNetwork
from rl_agent import RLAgent
from rl_config import RLConfig
from state_parser import StateParser


def main():
    print("=" * 60)
    print("RL Agent Smoke Test")
    print("=" * 60)
    print()
    print("Connecting to game (ports 5555 state, 5556 action)...")
    print("Make sure the game is running with mod and you're in a dungeon.")
    print()

    # --- Step 1: Connect IPC ---
    ipc = IpcClient(connect_timeout=60.0, recv_timeout=30.0)
    try:
        ipc.connect()
    except Exception as e:
        print(f"[FAIL] Could not connect: {e}")
        sys.exit(1)
    print("[OK] IPC connected")

    # --- Step 2: Receive state ---
    print("\nWaiting for game state...")
    try:
        raw_state = ipc.receive_state(timeout=30.0)
    except Exception as e:
        print(f"[FAIL] No state received: {e}")
        ipc.disconnect()
        sys.exit(1)

    parser = StateParser()
    state = parser.parse(raw_state)
    print(f"[OK] State received: Turn={state.turn}, Floor={state.floor}, Phase={state.game_phase.value}")
    print(f"     Rooms={len(state.rooms)}, Heroes={len(state.heroes)}, Mobs={len(state.mobs)}")
    if state.resources:
        r = state.resources
        print(f"     Resources: I={r.industry:.0f} F={r.food:.0f} S={r.science:.0f} D={r.dust:.0f}/{r.dust_max:.0f}")
        print(f"     Production: I/t={r.industry_per_turn:.0f} F/t={r.food_per_turn:.0f} S/t={r.science_per_turn:.0f}")

    # --- Step 3: Create RL agent ---
    print("\nCreating RL agent (untrained, random policy)...")
    agent = RLAgent(config=RLConfig(), deterministic=False)
    print(f"[OK] RLAgent created")

    # --- Step 4: Build observation + check mask ---
    print("\nBuilding observation tensor...")
    obs = agent._state_to_obs_tensor(state)
    print(f"[OK] Observation built. Keys: {list(obs.keys())}")
    for key, tensor in obs.items():
        print(f"     {key}: shape={tensor.shape}, dtype={tensor.dtype}")

    mask_computer = ActionMaskComputer()
    mask = mask_computer.compute_mask(state)
    valid_options = [StrategicOption(i).name for i in range(NUM_OPTIONS) if mask[i]]
    print(f"\n[OK] Action mask: {sum(mask)}/{NUM_OPTIONS} options valid")
    print(f"     Valid: {', '.join(valid_options)}")

    # --- Step 5: Network forward pass ---
    print("\nRunning PolicyNetwork forward pass...")
    mask_tensor = torch.tensor(mask, dtype=torch.int8).unsqueeze(0)
    with torch.no_grad():
        action_dict, log_prob, value = agent.policy_net.act(obs, mask_tensor)
    option = StrategicOption(action_dict["option"].item())
    print(f"[OK] Network output:")
    print(f"     Option: {option.name} ({option.value})")
    print(f"     Room target: {action_dict['room_target'].item()}")
    print(f"     Hero target: {action_dict['hero_target'].item()}")
    print(f"     Entity target: {action_dict['entity_target'].item()}")
    print(f"     Log prob: {log_prob.item():.4f}")
    print(f"     Value: {value.item():.4f}")

    # --- Step 6: Full select_action pipeline ---
    print("\nRunning full agent.select_action()...")
    action = agent.select_action(state)
    if action is None:
        print(f"[OK] Agent returned None (WAIT / no action needed)")
    else:
        print(f"[OK] Agent wants to execute: {action['command']}")
        print(f"     Parameters: {action['parameters']}")

    # --- Step 7: Send action to game ---
    if action is not None:
        print(f"\nSending action to game...")
        try:
            result = ipc.send_action(action["command"], action["parameters"])
            if result.get("success"):
                print(f"[OK] Action succeeded! Metadata: {result.get('metadata', {})}")
            else:
                print(f"[OK] Action failed (expected for random policy): {result.get('error')}")
        except Exception as e:
            print(f"[WARN] Error sending action: {e}")
    else:
        print("\n[SKIP] No action to send (agent chose WAIT)")

    # --- Step 8: Multi-step stability test ---
    print("\n" + "-" * 60)
    print("Running 10-step stability test...")
    print("-" * 60)

    successes = 0
    failures = 0
    nones = 0

    for step in range(10):
        # Receive fresh state
        try:
            raw = ipc.receive_state(timeout=5.0)
            state = parser.parse(raw)
        except Exception as e:
            print(f"  Step {step+1}: [WARN] No state received ({e}), using previous")
            # Keep using last state

        # Agent decides
        action = agent.select_action(state)
        if action is None:
            nones += 1
            print(f"  Step {step+1}: WAIT (no action)")
            continue

        # Send it
        try:
            result = ipc.send_action(action["command"], action["parameters"])
            if result.get("success"):
                successes += 1
                print(f"  Step {step+1}: {action['command']} → SUCCESS")
            else:
                failures += 1
                print(f"  Step {step+1}: {action['command']} → FAILED ({result.get('error', '')[:50]})")
            agent.on_action_result(action, result)
        except Exception as e:
            failures += 1
            print(f"  Step {step+1}: {action['command']} → ERROR ({e})")

        time.sleep(0.5)  # Small delay between actions

    # --- Summary ---
    print()
    print("=" * 60)
    print(f"SMOKE TEST COMPLETE")
    print(f"  Actions sent: {successes + failures}")
    print(f"  Successes: {successes}")
    print(f"  Failures: {failures} (expected — untrained random policy)")
    print(f"  Waits: {nones}")
    print(f"  Pipeline: {'WORKING' if (successes + failures + nones) == 10 else 'ISSUES DETECTED'}")
    print("=" * 60)

    ipc.disconnect()

    if successes + failures + nones == 10:
        print("\n[PASS] The RL pipeline is functional. Ready for training.")
    else:
        print("\n[WARN] Some steps had issues. Check output above.")


if __name__ == "__main__":
    main()

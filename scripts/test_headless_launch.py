"""
Test script: Launch Dungeon of the ENDLESS with optimized settings for training.

Since -batchmode -nographics crashes Unity 5.0.3, we use the next best approach:
  1. Small window (64x64 pixels) — minimizes GPU rendering overhead
  2. Training mode in the mod — disables VSync, shadows, particles, audio, etc.

Before running: set training_mode=true in BepInEx/plugins/dote_training.cfg

Usage:
    python test_headless_launch.py [--exe-path "C:/path/to/DungeonoftheEndless.exe"]
    python test_headless_launch.py --headless  # Test headless (known to crash, for reference)
"""

from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src" / "agent"))

from game_launcher import GameLauncher


def test_headless(exe_path: str | None, mode: str = "headless") -> None:
    headless = mode == "headless"

    print(f"=" * 60)
    if headless:
        print(f"  Testing HEADLESS (-batchmode -nographics) — known to crash")
    else:
        print(f"  Testing TRAINING MODE (mod handles optimizations)")
    print(f"=" * 60)
    print()

    launcher = GameLauncher(
        game_path=exe_path,
        use_steam=True,  # Use Steam protocol to avoid Steamworks init issues
        headless=headless,
        connect_timeout=90.0,  # Give it extra time in case startup is slower
        recv_timeout=30.0,
    )

    try:
        # Step 1: Launch and connect
        print("[1/5] Launching game and connecting IPC...")
        t0 = time.time()
        launcher.launch_and_connect()
        connect_time = time.time() - t0
        print(f"  -> Connected in {connect_time:.1f}s")
        print()

        # Step 2: Query menu state
        print("[2/4] Querying menu state...")
        try:
            menu = launcher.query_menu_state(retries=10, retry_delay=5.0)
            print(f"  -> in_dungeon: {menu.in_dungeon}")
            print(f"  -> has_save: {menu.has_save}")
            print(f"  -> available_heroes: {len(menu.available_heroes)} ({menu.available_heroes[:3]}...)")
            print(f"  -> available_ships: {menu.available_ships}")
            print()
        except Exception as e:
            print(f"  -> FAILED: {e}")
            print("  This likely means the game UI didn't fully initialize.")
            return

        # Step 3: Start a new game
        print("[3/4] Starting new game (Pod, Easy, Max + Gork)...")
        try:
            result = launcher.start_new_game(
                heroes=["Hero_H0001", "Hero_H0003"],
                ship="Pod",
                difficulty="easy",
                retries=10,
                retry_delay=5.0,
            )
            print(f"  -> Result: {result}")
            print()
        except Exception as e:
            print(f"  -> FAILED: {e}")
            print("  Game may crash when trying to load dungeon without rendering.")
            return

        # Step 4: Wait for dungeon state
        print("[4/4] Waiting for dungeon state...")
        try:
            state = launcher.wait_for_dungeon(timeout=90.0)
            print(f"  -> Got state! Turn: {state.get('turn')}, "
                  f"Rooms: {len(state.get('rooms', []))}, "
                  f"Phase: {state.get('game_phase')}")
            print()
            print("=" * 60)
            print("  SUCCESS! Headless mode works!")
            print(f"  Mode: {'batchmode+nographics' if headless else '64x64 window'}")
            print("  The game runs without GPU rendering.")
            print("  This is ideal for RL training parallelization.")
            print("=" * 60)
        except TimeoutError:
            print("  -> TIMEOUT: Dungeon never loaded.")
            print("  The game might be stuck on a loading screen that needs rendering.")
            print("  Try --small-window mode as a fallback.")

    except RuntimeError as e:
        print(f"\n  FAILED: {e}")
        print()
        if headless:
            print("  Headless mode didn't work. Try running with --small-window instead:")
            print(f"    python {sys.argv[0]} --small-window")
    except KeyboardInterrupt:
        print("\n  Interrupted by user.")
    finally:
        if launcher._process and launcher._process.poll() is None:
            print("\n  NOTE: Game process is still running.")
            print("  You may need to kill it manually (Task Manager or taskkill).")
            answer = input("  Kill the game process now? [y/N] ").strip().lower()
            if answer == "y":
                launcher._process.terminate()
                print("  Terminated.")
        launcher.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Test headless/minimal-window game launch")
    parser.add_argument("--exe-path", type=str,
                        default=r"C:\Program Files (x86)\Steam\steamapps\common\Dungeon of the Endless\DungeonoftheEndless.exe",
                        help="Path to DungeonoftheEndless.exe")
    parser.add_argument("--headless", action="store_true",
                        help="Test headless mode (known to crash Unity 5.0.3)")
    args = parser.parse_args()

    mode = "headless" if args.headless else "training"
    test_headless(args.exe_path, mode=mode)


if __name__ == "__main__":
    main()

# manual_test_phase35.py — Test game launcher and menu commands
# Run with the game already open on the main menu, OR let it launch via Steam.
#
# Usage:
#   python manual_test_phase35.py              # Connect to already-running game
#   python manual_test_phase35.py --launch     # Launch game via Steam first
#   python manual_test_phase35.py --new-game   # Start a new game after querying menu

import sys
sys.path.insert(0, "src/agent")

from game_launcher import GameLauncher

do_launch = "--launch" in sys.argv
do_new_game = "--new-game" in sys.argv

launcher = GameLauncher(use_steam=True, connect_timeout=60.0)

if do_launch:
    print("Launching game and connecting...")
    launcher.launch_and_connect()
else:
    print("Connecting to already-running game...")
    launcher.launch_and_connect()

print("\n--- Querying menu state ---")
menu = launcher.query_menu_state()
print(f"  In dungeon: {menu.in_dungeon}")
print(f"  Has save: {menu.has_save}")
print(f"  Available heroes ({len(menu.available_heroes)}):")
for h in menu.available_heroes:
    unlocked = " [UNLOCKED]" if h in menu.selectable_heroes else ""
    print(f"    {h}{unlocked}")
print(f"  Available ships ({len(menu.available_ships)}):")
for s in menu.available_ships:
    print(f"    {s}")

if menu.in_dungeon:
    print("\n--- Already in dungeon, receiving state ---")
    state = launcher.wait_for_dungeon(timeout=10.0)
    print(f"  Got state: Turn {state['turn']}, {len(state['rooms'])} rooms")
elif do_new_game:
    if menu.has_save:
        print("\n--- Continuing saved game ---")
        launcher.continue_game()
    else:
        # Find Max and Gork by looking for config names
        # (you'll see the actual names in the available_heroes list above)
        print("\n--- Starting new game ---")
        # Use first two unlocked heroes if available, otherwise first two available
        heroes_to_pick = menu.selectable_heroes[:2] if menu.selectable_heroes else menu.available_heroes[:2]
        ship_to_pick = menu.available_ships[0] if menu.available_ships else None
        print(f"  Heroes: {heroes_to_pick}")
        print(f"  Ship: {ship_to_pick}")
        launcher.start_new_game(heroes=heroes_to_pick, ship=ship_to_pick, difficulty="normal")

    print("\n--- Waiting for dungeon to load ---")
    state = launcher.wait_for_dungeon(timeout=90.0)
    print(f"  Dungeon loaded! Turn {state['turn']}, {len(state['rooms'])} rooms")
else:
    print("\n(Run with --new-game to start a game, or just use this to see available heroes/ships)")

launcher.disconnect()
print("\nDone!")

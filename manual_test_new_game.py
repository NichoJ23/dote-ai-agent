# manual_test_new_game.py — Test starting a fresh game with Max + Gork on Pod (Easy)
# Run with the game open on the main menu.
# WARNING: This will overwrite any existing save!

import sys
sys.path.insert(0, "src/agent")

from game_launcher import GameLauncher
from state_parser import StateParser

print("=== Phase 3.5 New Game Test ===")
print("Settings: Pod, Easy, Max O'Kane + Gork")
print()

launcher = GameLauncher(connect_timeout=60.0)

print("Connecting to game...")
launcher.launch_and_connect()
print("Connected!")

print("\nQuerying menu state...")
menu = launcher.query_menu_state()
print(f"  In dungeon: {menu.in_dungeon}")
print(f"  Has save: {menu.has_save}")

if menu.in_dungeon:
    print("\nAlready in a dungeon. Close the game and restart on the main menu to test new game.")
    launcher.disconnect()
    sys.exit(0)

print("\nStarting new game...")
print("  Ship: Pod")
print("  Difficulty: Easy")
print("  Heroes: Hero_H0001 (Max O'Kane), Hero_H0003 (Gork)")
result = launcher.start_new_game(
    heroes=["Hero_H0001", "Hero_H0003"],
    ship="Pod",
    difficulty="easy",
)
print(f"  Result: {result}")

print("\nWaiting for dungeon to load...")
raw_state = launcher.wait_for_dungeon(timeout=90.0)

# Parse and display
parser = StateParser()
state = parser.parse(raw_state)
print(f"\n=== Dungeon Loaded! ===")
print(f"  Turn: {state.turn}, Floor: {state.floor}")
print(f"  Phase: {state.game_phase.value}")
print(f"  Rooms: {len(state.rooms)}")
print(f"  Heroes:")
for h in state.heroes:
    print(f"    {h.name} [{h.faction}] Room {h.room_index} HP={h.hp:.0f}/{h.max_hp:.0f}")

launcher.disconnect()
print("\nTest complete!")

"""
Smoke test for tasks 2.1 + 2.2: IPC Bridge + JSON Serializer.

Usage:
  1. Run this script FIRST (it blocks waiting for the mod to connect):
       python scripts/test_ipc_receive.py
  2. Launch Dungeon of the ENDLESS with the mod installed.
  3. Start a dungeon run. Once a turn ticks, this script will print the
     full game state JSON and validate its structure.

What it verifies:
  - TCP connection on port 5555 succeeds
  - 4-byte big-endian length-prefix framing works
  - Payload is valid JSON
  - Top-level keys match expected schema
  - Nested structures (rooms, heroes, etc.) are present and typed correctly
"""

import socket
import struct
import json
import sys


EXPECTED_TOP_KEYS = {
    "turn", "floor", "game_phase", "crystal_state",
    "exit_room_index", "start_room_index",
    "resources", "rooms", "closed_doors",
    "heroes", "mobs", "merchants",
    "recruitable_heroes", "dropped_items",
    "backpack_items", "shared_inventory_items",
}


def recv_exact(sock, n):
    """Receive exactly n bytes from socket."""
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Connection closed before receiving all data")
        data += chunk
    return data


def receive_message(sock):
    """Read one length-prefixed message from the socket."""
    raw_len = recv_exact(sock, 4)
    msg_len = struct.unpack(">I", raw_len)[0]
    print(f"[OK] Received length prefix: {msg_len} bytes")

    payload = recv_exact(sock, msg_len)
    return payload.decode("utf-8")


def validate_state(state):
    """Validate the game state structure."""
    errors = []

    # Check top-level keys
    missing = EXPECTED_TOP_KEYS - set(state.keys())
    extra = set(state.keys()) - EXPECTED_TOP_KEYS
    if missing:
        errors.append(f"Missing top-level keys: {missing}")
    if extra:
        print(f"[INFO] Extra top-level keys (not an error): {extra}")

    # Type checks
    if not isinstance(state.get("turn"), int):
        errors.append(f"'turn' should be int, got {type(state.get('turn'))}")
    if not isinstance(state.get("floor"), int):
        errors.append(f"'floor' should be int, got {type(state.get('floor'))}")
    if not isinstance(state.get("game_phase"), str):
        errors.append(f"'game_phase' should be str, got {type(state.get('game_phase'))}")
    if not isinstance(state.get("rooms"), list):
        errors.append(f"'rooms' should be list, got {type(state.get('rooms'))}")
    if not isinstance(state.get("heroes"), list):
        errors.append(f"'heroes' should be list, got {type(state.get('heroes'))}")
    if not isinstance(state.get("mobs"), list):
        errors.append(f"'mobs' should be list, got {type(state.get('mobs'))}")

    # Validate rooms have expected fields
    rooms = state.get("rooms", [])
    if len(rooms) > 0:
        room = rooms[0]
        room_keys = {"index", "is_powered", "is_auto_powered", "adjacent_room_indices"}
        missing_room = room_keys - set(room.keys())
        if missing_room:
            errors.append(f"First room missing keys: {missing_room}")

    # Validate heroes have expected fields
    heroes = state.get("heroes", [])
    if len(heroes) > 0:
        hero = heroes[0]
        hero_keys = {"name", "faction", "room_index", "hp", "max_hp", "level", "active_skills", "passive_skills", "equipment"}
        missing_hero = hero_keys - set(hero.keys())
        if missing_hero:
            errors.append(f"First hero missing keys: {missing_hero}")

    # Validate resources
    resources = state.get("resources")
    if resources is not None:
        res_keys = {"industry", "food", "science", "dust", "dust_max"}
        missing_res = res_keys - set(resources.keys())
        if missing_res:
            errors.append(f"Resources missing keys: {missing_res}")

    return errors


def main():
    import time

    print("=" * 60)
    print("IPC Smoke Test (Tasks 2.1 + 2.2)")
    print("Connecting to localhost:5555 (state port)...")
    print("=" * 60)
    print()
    print("Waiting for mod to start... (launch the game now)")
    print("Will retry every 2 seconds for up to 5 minutes.")
    print()

    sock = None
    timeout_seconds = 300  # 5 minutes
    start_time = time.time()

    while time.time() - start_time < timeout_seconds:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(("127.0.0.1", 5555))
            break
        except (ConnectionRefusedError, OSError, socket.timeout):
            sock.close()
            sock = None
            elapsed = int(time.time() - start_time)
            print(f"  ...retrying ({elapsed}s elapsed)", end="\r")
            time.sleep(2)

    if sock is None:
        print()
        print("[FAIL] Timed out after 5 minutes. Is the game running with the mod?")
        sys.exit(1)

    print("[OK] Connected to state port 5555!")
    print("Waiting for first state message (start a dungeon run)...")
    print("You have up to 5 minutes to get through menus and into a game.")
    print()

    sock.settimeout(300)  # 5 minutes to get through menus and start a run

    try:
        raw_json = receive_message(sock)
    except socket.timeout:
        print("[FAIL] Timed out waiting for state message. Did you start a dungeon run?")
        sock.close()
        sys.exit(1)

    # Parse JSON
    try:
        state = json.loads(raw_json)
        print("[OK] Valid JSON received")
    except json.JSONDecodeError as e:
        print(f"[FAIL] Invalid JSON: {e}")
        print(f"Raw (first 500 chars): {raw_json[:500]}")
        sock.close()
        sys.exit(1)

    # Validate structure
    errors = validate_state(state)

    # Print summary
    print()
    print("-" * 60)
    print("STATE SUMMARY:")
    print(f"  Turn: {state.get('turn')}")
    print(f"  Floor: {state.get('floor')}")
    print(f"  Phase: {state.get('game_phase')}")
    print(f"  Crystal: {state.get('crystal_state')}")
    print(f"  Rooms: {len(state.get('rooms', []))}")
    print(f"  Heroes: {len(state.get('heroes', []))}")
    print(f"  Mobs: {len(state.get('mobs', []))}")
    print(f"  Merchants: {len(state.get('merchants', []))}")
    print(f"  Recruits: {len(state.get('recruitable_heroes', []))}")
    print(f"  Dropped Items: {len(state.get('dropped_items', []))}")
    print("-" * 60)

    if errors:
        print()
        print(f"[FAIL] {len(errors)} validation error(s):")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print()
        print("[PASS] All validations passed!")

    # Print full JSON for inspection
    print()
    print("Full state JSON (pretty-printed):")
    print(json.dumps(state, indent=2))

    sock.close()


if __name__ == "__main__":
    main()

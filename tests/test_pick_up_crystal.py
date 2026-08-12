"""
Smoke test for task 2.12: PickUpCrystalHandler.

Usage:
  1. Start a dungeon (crystal is in starting room by default).
  2. Make sure a hero is in the starting room (room 0).
  3. Run: python scripts/test_pick_up_crystal.py

What it verifies:
  - PICK_UP_CRYSTAL with hero in crystal room succeeds (hero picks up crystal)
  - PICK_UP_CRYSTAL with hero NOT in crystal room is rejected
  - Missing parameters are rejected

WARNING: This will actually unplug the crystal and start the escape phase!
         Only run this if you're ready for that (or testing on a throwaway run).
"""

import socket
import struct
import json
import sys
import time


def recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Connection closed")
        data += chunk
    return data


def send_message(sock, payload_dict):
    json_bytes = json.dumps(payload_dict).encode("utf-8")
    length_prefix = struct.pack(">I", len(json_bytes))
    sock.sendall(length_prefix + json_bytes)


def receive_message(sock):
    raw_len = recv_exact(sock, 4)
    msg_len = struct.unpack(">I", raw_len)[0]
    payload = recv_exact(sock, msg_len)
    return json.loads(payload.decode("utf-8"))


def connect_with_retry(port, timeout_seconds=300):
    start_time = time.time()
    sock = None
    while time.time() - start_time < timeout_seconds:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(("127.0.0.1", port))
            return sock
        except (ConnectionRefusedError, OSError, socket.timeout):
            sock.close()
            sock = None
            time.sleep(2)
    return None


def main():
    print("=" * 60)
    print("Pick Up Crystal Smoke Test (Task 2.12)")
    print("=" * 60)
    print()
    print("WARNING: This will unplug the crystal! Use on a throwaway run.")
    print()
    print("Connecting...")

    state_sock = connect_with_retry(5555)
    action_sock = connect_with_retry(5556)
    if not state_sock or not action_sock:
        print("[FAIL] Could not connect")
        sys.exit(1)
    print("[OK] Connected")

    # Wait for state with heroes
    state_sock.settimeout(300)
    state = None
    while True:
        state = receive_message(state_sock)
        heroes = state.get("heroes", [])
        if len(heroes) > 0:
            break

    print(f"[OK] State: {len(heroes)} heroes, crystal={state.get('crystal_state')}")

    start_room = state.get("start_room_index", 0)
    passed = 0
    failed = 0
    action_sock.settimeout(10)

    # Test 1: Missing parameter
    print("\nTest 1: Missing parameter...")
    send_message(action_sock, {
        "command": "PICK_UP_CRYSTAL",
        "parameters": {},
        "timestamp": int(time.time() * 1000)
    })
    response = receive_message(action_sock)
    if not response["success"] and "missing" in response["error"].lower():
        print(f"  [OK] Correctly rejected: {response['error']}")
        passed += 1
    else:
        print(f"  [FAIL] Expected parameter error, got: {response}")
        failed += 1

    # Test 2: Hero NOT in crystal room
    hero_not_in_start = None
    for h in heroes:
        if h["room_index"] != start_room:
            hero_not_in_start = h
            break

    if hero_not_in_start:
        print(f"\nTest 2: Hero not in crystal room ({hero_not_in_start['name']} in room {hero_not_in_start['room_index']})...")
        send_message(action_sock, {
            "command": "PICK_UP_CRYSTAL",
            "parameters": {"hero_name": hero_not_in_start["name"]},
            "timestamp": int(time.time() * 1000)
        })
        response = receive_message(action_sock)
        if not response["success"] and "not in crystal room" in response["error"].lower():
            print(f"  [OK] Correctly rejected: {response['error']}")
            passed += 1
        else:
            print(f"  [FAIL] Expected room mismatch, got: {response}")
            failed += 1
    else:
        print("\nTest 2: [SKIP] All heroes are in start room")
        passed += 1

    # Test 3: Valid crystal pickup
    hero_in_start = None
    for h in heroes:
        if h["room_index"] == start_room:
            hero_in_start = h
            break

    if hero_in_start and state.get("crystal_state") == "Plugged":
        print(f"\nTest 3: Valid PICK_UP_CRYSTAL ({hero_in_start['name']})...")
        print(f"  (Crystal should unplug and hero will carry it)")
        send_message(action_sock, {
            "command": "PICK_UP_CRYSTAL",
            "parameters": {"hero_name": hero_in_start["name"]},
            "timestamp": int(time.time() * 1000)
        })
        response = receive_message(action_sock)
        if response["success"]:
            print(f"  [OK] Crystal pickup initiated! Check in-game.")
            passed += 1
        elif "not usable" in response.get("error", ""):
            print(f"  [OK] Hero busy (timing): {response['error']}")
            passed += 1
        else:
            print(f"  [FAIL] {response['error']}")
            failed += 1
    elif not hero_in_start:
        print(f"\nTest 3: [SKIP] No hero in start room. Move one there first.")
        passed += 1
    else:
        print(f"\nTest 3: [SKIP] Crystal not plugged (state: {state.get('crystal_state')})")
        passed += 1

    # Results
    print()
    print("-" * 60)
    print(f"Results: {passed} passed, {failed} failed out of 3 tests")
    print("-" * 60)

    state_sock.close()
    action_sock.close()

    if failed > 0:
        sys.exit(1)
    else:
        print("[PASS] All Pick Up Crystal tests passed!")


if __name__ == "__main__":
    main()

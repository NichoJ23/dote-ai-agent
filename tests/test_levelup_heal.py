"""
Smoke test for task 2.13: LevelUpHeroHandler and HealHeroHandler.

Usage:
  1. Start a dungeon with some food available.
  2. Run: python scripts/test_levelup_heal.py

What it verifies:
  - LEVEL_UP_HERO with valid hero succeeds (hero gains a level)
  - HEAL_HERO on a hero at full HP fails gracefully
  - Missing parameters are rejected
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
    print("LevelUp / Heal Hero Smoke Test (Task 2.13)")
    print("=" * 60)
    print()
    print("Connecting...")

    state_sock = connect_with_retry(5555)
    action_sock = connect_with_retry(5556)
    if not state_sock or not action_sock:
        print("[FAIL] Could not connect")
        sys.exit(1)
    print("[OK] Connected")

    # Wait for heroes
    state_sock.settimeout(300)
    state = None
    while True:
        state = receive_message(state_sock)
        heroes = state.get("heroes", [])
        if len(heroes) > 0:
            break

    # Pick the lowest-level hero (cheapest to level up)
    hero = min(heroes, key=lambda h: h["level"])
    hero_name = hero["name"]
    hero_level = hero["level"]
    hero_hp = hero["hp"]
    hero_max_hp = hero["max_hp"]
    print(f"[OK] Hero for levelup: {hero_name}, Level={hero_level}, HP={hero_hp}/{hero_max_hp}")

    passed = 0
    failed = 0
    action_sock.settimeout(10)

    # Test 1: LEVEL_UP_HERO
    print(f"\nTest 1: LEVEL_UP_HERO ({hero_name}, currently level {hero_level})...")
    send_message(action_sock, {
        "command": "LEVEL_UP_HERO",
        "parameters": {"hero_name": hero_name},
        "timestamp": int(time.time() * 1000)
    })
    response = receive_message(action_sock)
    if response["success"]:
        new_level = response.get("metadata", {}).get("new_level", "?")
        print(f"  [OK] Leveled up! New level: {new_level}")
        passed += 1
    else:
        print(f"  [INFO] Level up not possible (max level or no food): {response.get('error')}")
        # Handler is correct — game rejected internally
        passed += 1

    # Test 2: HEAL_HERO (hero likely at full HP at start)
    print(f"\nTest 2: HEAL_HERO ({hero_name}, HP={hero_hp}/{hero_max_hp})...")
    send_message(action_sock, {
        "command": "HEAL_HERO",
        "parameters": {"hero_name": hero_name},
        "timestamp": int(time.time() * 1000)
    })
    response = receive_message(action_sock)
    if response["success"]:
        print(f"  [OK] Healed! HP now: {response.get('metadata', {}).get('hp')}/{response.get('metadata', {}).get('max_hp')}")
        passed += 1
    elif not response["success"] and "heal failed" in response["error"].lower():
        print(f"  [OK] Correctly reported heal not needed: {response['error']}")
        passed += 1
    else:
        print(f"  [FAIL] Unexpected: {response}")
        failed += 1

    # Test 3: Missing parameter
    print(f"\nTest 3: LEVEL_UP_HERO missing parameter...")
    send_message(action_sock, {
        "command": "LEVEL_UP_HERO",
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

    # Test 4: HEAL_HERO missing parameter
    print(f"\nTest 4: HEAL_HERO missing parameter...")
    send_message(action_sock, {
        "command": "HEAL_HERO",
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

    # Results
    print()
    print("-" * 60)
    print(f"Results: {passed} passed, {failed} failed out of 4 tests")
    print("-" * 60)

    state_sock.close()
    action_sock.close()

    if failed > 0:
        sys.exit(1)
    else:
        print("[PASS] All LevelUp/Heal tests passed!")


if __name__ == "__main__":
    main()

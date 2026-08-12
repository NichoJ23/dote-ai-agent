"""
Quick test for task 2.11: CollectItemHandler.

Since items are auto-collected when a hero enters the room, this handler
just moves the hero. This test validates the command is routed correctly.

Usage:
  1. Have a dungeon with 2+ rooms open.
  2. Run: python scripts/test_collect_item.py
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
    print("Collect Item Quick Test (Task 2.11)")
    print("-" * 40)

    state_sock = connect_with_retry(5555)
    action_sock = connect_with_retry(5556)
    if not state_sock or not action_sock:
        print("[FAIL] Could not connect")
        sys.exit(1)

    state_sock.settimeout(300)
    state = None
    while True:
        state = receive_message(state_sock)
        heroes = state.get("heroes", [])
        rooms = state.get("rooms", [])
        if len(heroes) > 0 and len(rooms) >= 2:
            break

    hero = heroes[0]
    hero_name = hero["name"]
    hero_room = hero["room_index"]
    target_room = 1 if hero_room == 0 else 0

    passed = 0
    failed = 0
    action_sock.settimeout(10)

    # Test 1: Valid COLLECT_ITEM (moves hero to target room)
    print(f"\nTest 1: COLLECT_ITEM ({hero_name} -> room {target_room})...")
    send_message(action_sock, {
        "command": "COLLECT_ITEM",
        "parameters": {"hero_name": hero_name, "room_index": target_room},
        "timestamp": int(time.time() * 1000)
    })
    response = receive_message(action_sock)
    if response["success"]:
        print(f"  [OK] Hero dispatched to room {target_room}")
        passed += 1
    elif "not usable" in response.get("error", ""):
        print(f"  [OK] Hero busy (timing): {response['error']}")
        passed += 1
    else:
        print(f"  [FAIL] {response['error']}")
        failed += 1

    # Test 2: Invalid room
    print(f"\nTest 2: COLLECT_ITEM with invalid room...")
    send_message(action_sock, {
        "command": "COLLECT_ITEM",
        "parameters": {"hero_name": hero_name, "room_index": 9999},
        "timestamp": int(time.time() * 1000)
    })
    response = receive_message(action_sock)
    if not response["success"] and "invalid" in response["error"].lower():
        print(f"  [OK] Correctly rejected: {response['error']}")
        passed += 1
    else:
        print(f"  [FAIL] Expected rejection, got: {response}")
        failed += 1

    # Test 3: Missing parameters
    print(f"\nTest 3: COLLECT_ITEM missing parameters...")
    send_message(action_sock, {
        "command": "COLLECT_ITEM",
        "parameters": {},
        "timestamp": int(time.time() * 1000)
    })
    response = receive_message(action_sock)
    if not response["success"] and "missing" in response["error"].lower():
        print(f"  [OK] Correctly rejected: {response['error']}")
        passed += 1
    else:
        print(f"  [FAIL] Expected rejection, got: {response}")
        failed += 1

    print(f"\nResults: {passed}/3 passed")
    state_sock.close()
    action_sock.close()

    if failed > 0:
        sys.exit(1)
    else:
        print("[PASS] All Collect Item tests passed!")


if __name__ == "__main__":
    main()

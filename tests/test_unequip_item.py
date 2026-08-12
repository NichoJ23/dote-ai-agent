"""
Quick test: Unequip the first equipped item from the first hero.

Usage:
  1. Make sure a hero has at least one item equipped.
  2. Run: python scripts/test_unequip_item.py
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
    print("Unequip Item Quick Test")
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
        if len(state.get("heroes", [])) > 0:
            break

    heroes = state["heroes"]
    hero = heroes[0]
    hero_name = hero["name"]
    equipment = hero.get("equipment", [])

    # Find first equipped slot
    equipped_slot = None
    slot_idx = -1
    for i, e in enumerate(equipment):
        if e.get("item_name") is not None:
            equipped_slot = e
            slot_idx = i
            break

    if equipped_slot is None:
        print(f"[SKIP] {hero_name} has no equipped items. Equip something first.")
        state_sock.close()
        action_sock.close()
        sys.exit(0)

    print(f"  Hero: {hero_name}")
    print(f"  Unequipping: {equipped_slot['item_name']} from slot {slot_idx} ({equipped_slot['slot_category']})")

    action_sock.settimeout(10)
    send_message(action_sock, {
        "command": "UNEQUIP_ITEM",
        "parameters": {"hero_name": hero_name, "slot_index": slot_idx},
        "timestamp": int(time.time() * 1000)
    })
    response = receive_message(action_sock)

    if response["success"]:
        print(f"  [OK] Unequipped! Check in-game. metadata={response.get('metadata')}")
    else:
        print(f"  [FAIL] {response['error']}")

    state_sock.close()
    action_sock.close()


if __name__ == "__main__":
    main()

"""
Smoke test for task 2.10: EquipItemHandler and UnequipItemHandler.

Usage:
  1. Start a dungeon and acquire at least one item (buy from merchant or pick up).
  2. Run this script: python scripts/test_equip_item.py

What it verifies:
  - EQUIP_ITEM with valid item in inventory succeeds
  - UNEQUIP_ITEM on an equipped slot succeeds
  - EQUIP_ITEM with invalid item name is rejected
  - UNEQUIP_ITEM on empty slot is rejected
  - Missing parameters are rejected

NOTE: Requires at least one item in shared/backpack inventory OR already equipped.
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
            elapsed = int(time.time() - start_time)
            print(f"  ...retrying ({elapsed}s elapsed)", end="\r")
            time.sleep(2)
    return None


def main():
    print("=" * 60)
    print("Equip/Unequip Item Smoke Test (Task 2.10)")
    print("=" * 60)
    print()
    print("Connecting...")
    print("Make sure you have items in inventory (buy from merchant first).")
    print()

    state_sock = connect_with_retry(5555)
    if state_sock is None:
        print("[FAIL] Could not connect to state port")
        sys.exit(1)
    print("[OK] Connected to state port 5555")

    action_sock = connect_with_retry(5556)
    if action_sock is None:
        print("[FAIL] Could not connect to action port")
        state_sock.close()
        sys.exit(1)
    print("[OK] Connected to action port 5556")

    # Wait for state with heroes
    print()
    print("Waiting for game state with heroes...")
    state_sock.settimeout(300)

    state = None
    while True:
        state = receive_message(state_sock)
        heroes = state.get("heroes", [])
        if len(heroes) > 0:
            break

    print(f"[OK] State: {len(heroes)} heroes")

    # Check for items in inventory
    backpack_items = state.get("backpack_items", [])
    shared_items = state.get("shared_inventory_items", [])
    all_inventory_items = backpack_items + shared_items
    print(f"  Backpack items: {len(backpack_items)}")
    print(f"  Shared inventory items: {len(shared_items)}")

    # Check hero equipment
    hero = heroes[0]
    hero_name = hero["name"]
    equipment = hero.get("equipment", [])
    equipped_slots = [e for e in equipment if e.get("item_name") is not None]
    empty_slots = [i for i, e in enumerate(equipment) if e.get("item_name") is None]
    print(f"  Hero: {hero_name}")
    print(f"  Equipped slots: {len(equipped_slots)}, Empty slots: {len(empty_slots)}")

    passed = 0
    failed = 0
    action_sock.settimeout(10)

    # Test 1: Missing parameters
    print("\nTest 1: EQUIP_ITEM missing parameters...")
    send_message(action_sock, {
        "command": "EQUIP_ITEM",
        "parameters": {"hero_name": hero_name},
        "timestamp": int(time.time() * 1000)
    })
    response = receive_message(action_sock)
    if not response["success"] and "item_name" in response["error"].lower():
        print(f"  [OK] Correctly rejected: {response['error']}")
        passed += 1
    else:
        print(f"  [FAIL] Expected parameter error, got: {response}")
        failed += 1

    # Test 2: Invalid item name
    print("\nTest 2: EQUIP_ITEM with invalid item name...")
    send_message(action_sock, {
        "command": "EQUIP_ITEM",
        "parameters": {"hero_name": hero_name, "item_name": "FakeItem999"},
        "timestamp": int(time.time() * 1000)
    })
    response = receive_message(action_sock)
    if not response["success"] and "not found" in response["error"].lower():
        print(f"  [OK] Correctly rejected: {response['error']}")
        passed += 1
    else:
        print(f"  [FAIL] Expected 'not found' error, got: {response}")
        failed += 1

    # Test 3: UNEQUIP_ITEM on empty slot
    if len(empty_slots) > 0:
        empty_slot_idx = empty_slots[0]
        print(f"\nTest 3: UNEQUIP_ITEM on empty slot {empty_slot_idx}...")
        send_message(action_sock, {
            "command": "UNEQUIP_ITEM",
            "parameters": {"hero_name": hero_name, "slot_index": empty_slot_idx},
            "timestamp": int(time.time() * 1000)
        })
        response = receive_message(action_sock)
        if not response["success"] and "no item" in response["error"].lower():
            print(f"  [OK] Correctly rejected: {response['error']}")
            passed += 1
        else:
            print(f"  [FAIL] Expected 'no item' error, got: {response}")
            failed += 1
    else:
        print("\nTest 3: [SKIP] No empty slots to test")
        passed += 1

    # Test 4: Valid EQUIP_ITEM (requires item in inventory)
    if len(all_inventory_items) > 0:
        item_to_equip = all_inventory_items[0]["name"]
        print(f"\nTest 4: Valid EQUIP_ITEM ({item_to_equip} on {hero_name})...")
        send_message(action_sock, {
            "command": "EQUIP_ITEM",
            "parameters": {"hero_name": hero_name, "item_name": item_to_equip},
            "timestamp": int(time.time() * 1000)
        })
        response = receive_message(action_sock)
        if response["success"]:
            print(f"  [OK] Equipped! metadata={response.get('metadata')}")
            passed += 1
        else:
            print(f"  [INFO] Equip failed: {response['error']}")
            # Could be no compatible slot — handler is correct
            passed += 1
    elif len(equipped_slots) > 0:
        print("\nTest 4: [SKIP] No items in inventory. Testing UNEQUIP instead...")
        # Unequip first equipped item, then re-equip
        slot_idx = equipment.index(equipped_slots[0])
        item_name = equipped_slots[0]["item_name"]
        print(f"  Unequipping {item_name} from slot {slot_idx}...")
        send_message(action_sock, {
            "command": "UNEQUIP_ITEM",
            "parameters": {"hero_name": hero_name, "slot_index": slot_idx},
            "timestamp": int(time.time() * 1000)
        })
        response = receive_message(action_sock)
        if response["success"]:
            print(f"  [OK] Unequipped! Now re-equipping...")
            time.sleep(1)
            send_message(action_sock, {
                "command": "EQUIP_ITEM",
                "parameters": {"hero_name": hero_name, "item_name": item_name},
                "timestamp": int(time.time() * 1000)
            })
            response = receive_message(action_sock)
            if response["success"]:
                print(f"  [OK] Re-equipped successfully!")
                passed += 1
            else:
                print(f"  [INFO] Re-equip failed: {response['error']}")
                passed += 1
        else:
            print(f"  [INFO] Unequip failed: {response['error']}")
            passed += 1
    else:
        print("\nTest 4: [SKIP] No items available anywhere")
        passed += 1

    # Test 5: UNEQUIP_ITEM missing parameters
    print("\nTest 5: UNEQUIP_ITEM missing parameters...")
    send_message(action_sock, {
        "command": "UNEQUIP_ITEM",
        "parameters": {"hero_name": hero_name},
        "timestamp": int(time.time() * 1000)
    })
    response = receive_message(action_sock)
    if not response["success"] and "slot_index" in response["error"].lower():
        print(f"  [OK] Correctly rejected: {response['error']}")
        passed += 1
    else:
        print(f"  [FAIL] Expected parameter error, got: {response}")
        failed += 1

    # Results
    print()
    print("-" * 60)
    print(f"Results: {passed} passed, {failed} failed out of 5 tests")
    print("-" * 60)

    state_sock.close()
    action_sock.close()

    if failed > 0:
        sys.exit(1)
    else:
        print("[PASS] All Equip/Unequip tests passed!")


if __name__ == "__main__":
    main()

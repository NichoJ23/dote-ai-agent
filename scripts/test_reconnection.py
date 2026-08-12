"""
Test for task 2.16: Client disconnect and reconnect while game is running.

Usage:
  1. Start a dungeon (any state is fine).
  2. Run: python scripts/test_reconnection.py

What it verifies:
  - Connect to state port, receive state, then disconnect abruptly
  - Reconnect to state port, receive state again (mod re-accepts)
  - Same test for action port: connect, send command, disconnect, reconnect, send again
  - Game doesn't crash during any of this
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


def connect_with_retry(port, timeout_seconds=30):
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
            time.sleep(1)
    return None


def main():
    print("=" * 60)
    print("Reconnection Test (Task 2.16)")
    print("=" * 60)
    print()

    passed = 0
    failed = 0

    # --- STATE PORT RECONNECTION ---

    # Test 1: Connect, receive state, disconnect
    print("Test 1: Connect to state port, receive state, disconnect...")
    sock = connect_with_retry(5555)
    if sock is None:
        print("  [FAIL] Could not connect to port 5555")
        sys.exit(1)

    sock.settimeout(30)
    state = receive_message(sock)
    print(f"  Received state: Turn={state['turn']}, Phase={state['game_phase']}")
    
    # Abruptly close (simulating crash/disconnect)
    sock.close()
    print("  Disconnected abruptly.")
    passed += 1

    # Wait a moment for mod to detect disconnect
    time.sleep(3)

    # Test 2: Reconnect and receive state again
    print("\nTest 2: Reconnect to state port, receive state again...")
    sock = connect_with_retry(5555, timeout_seconds=15)
    if sock is None:
        print("  [FAIL] Could not reconnect to port 5555")
        failed += 1
    else:
        sock.settimeout(30)
        try:
            state = receive_message(sock)
            print(f"  [OK] Received state after reconnect: Turn={state['turn']}, Phase={state['game_phase']}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] Could not receive state: {e}")
            failed += 1
        sock.close()

    time.sleep(2)

    # --- ACTION PORT RECONNECTION ---

    # Test 3: Connect to action port, send command, disconnect
    print("\nTest 3: Connect to action port, send command, disconnect...")
    action_sock = connect_with_retry(5556)
    if action_sock is None:
        print("  [FAIL] Could not connect to port 5556")
        failed += 1
    else:
        action_sock.settimeout(10)
        send_message(action_sock, {
            "command": "MOVE_HERO",
            "parameters": {"hero_name": "FakeHero", "target_room_index": 0},
            "timestamp": int(time.time() * 1000)
        })
        response = receive_message(action_sock)
        print(f"  Got response: success={response['success']}, error={response.get('error', '')}")
        
        # Abruptly disconnect
        action_sock.close()
        print("  Disconnected abruptly.")
        passed += 1

    time.sleep(3)

    # Test 4: Reconnect to action port, send another command
    print("\nTest 4: Reconnect to action port, send command again...")
    action_sock = connect_with_retry(5556, timeout_seconds=15)
    if action_sock is None:
        print("  [FAIL] Could not reconnect to port 5556")
        failed += 1
    else:
        action_sock.settimeout(10)
        send_message(action_sock, {
            "command": "MOVE_HERO",
            "parameters": {"hero_name": "FakeHero2", "target_room_index": 0},
            "timestamp": int(time.time() * 1000)
        })
        try:
            response = receive_message(action_sock)
            print(f"  [OK] Got response after reconnect: success={response['success']}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] Could not get response: {e}")
            failed += 1
        action_sock.close()

    # Results
    print()
    print("-" * 60)
    print(f"Results: {passed} passed, {failed} failed out of 4 tests")
    print("-" * 60)

    if failed > 0:
        sys.exit(1)
    else:
        print("[PASS] All reconnection tests passed!")


if __name__ == "__main__":
    main()

"""
Smoke test for task 2.3: Action Polling + Routing via port 5556.

Usage:
  1. Run this script: python scripts/test_action_routing.py
  2. Launch the game with the mod installed.
  3. Start a dungeon run (so the mod binds and starts processing).

What it verifies:
  - TCP connection on port 5556 succeeds
  - Sending a length-prefixed JSON action command works
  - Mod responds with a length-prefixed JSON ActionResult
  - Unknown commands return success=false with appropriate error
  - Malformed JSON returns success=false with parse error
"""

import socket
import struct
import json
import sys
import time


def recv_exact(sock, n):
    """Receive exactly n bytes from socket."""
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Connection closed before receiving all data")
        data += chunk
    return data


def send_message(sock, payload_dict):
    """Send a length-prefixed JSON message."""
    json_bytes = json.dumps(payload_dict).encode("utf-8")
    length_prefix = struct.pack(">I", len(json_bytes))
    sock.sendall(length_prefix + json_bytes)


def receive_message(sock):
    """Read one length-prefixed JSON message."""
    raw_len = recv_exact(sock, 4)
    msg_len = struct.unpack(">I", raw_len)[0]
    payload = recv_exact(sock, msg_len)
    return json.loads(payload.decode("utf-8"))


def test_unknown_command(sock):
    """Send a valid JSON command that has no handler registered."""
    print("Test 1: Unknown command...")
    send_message(sock, {
        "command": "NONEXISTENT_COMMAND",
        "parameters": {},
        "timestamp": 12345
    })
    response = receive_message(sock)
    
    assert response["success"] == False, f"Expected success=false, got {response['success']}"
    assert "Unknown command" in response["error"], f"Expected 'Unknown command' in error, got: {response['error']}"
    print(f"  [OK] Got expected error: {response['error']}")
    return True


def test_malformed_json(sock):
    """Send invalid JSON and verify error response."""
    print("Test 2: Malformed JSON...")
    # Send raw garbage as the payload
    garbage = b"{{not valid json at all"
    length_prefix = struct.pack(">I", len(garbage))
    sock.sendall(length_prefix + garbage)

    response = receive_message(sock)
    
    assert response["success"] == False, f"Expected success=false, got {response['success']}"
    assert response["error"] is not None, "Expected an error message"
    print(f"  [OK] Got expected error: {response['error']}")
    return True


def test_missing_command_field(sock):
    """Send JSON without the 'command' field."""
    print("Test 3: Missing 'command' field...")
    send_message(sock, {
        "parameters": {"hero_id": "test"},
        "timestamp": 99999
    })
    response = receive_message(sock)
    
    assert response["success"] == False, f"Expected success=false, got {response['success']}"
    print(f"  [OK] Got expected error: {response['error']}")
    return True


def main():
    print("=" * 60)
    print("Action Routing Smoke Test (Task 2.3)")
    print("Connecting to localhost:5556 (action port)...")
    print("=" * 60)
    print()
    print("Waiting for mod to start... (launch the game now)")
    print("Will retry every 2 seconds for up to 5 minutes.")
    print()

    sock = None
    timeout_seconds = 300
    start_time = time.time()

    while time.time() - start_time < timeout_seconds:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(("127.0.0.1", 5556))
            break
        except (ConnectionRefusedError, OSError, socket.timeout):
            sock.close()
            sock = None
            elapsed = int(time.time() - start_time)
            print(f"  ...retrying ({elapsed}s elapsed)", end="\r")
            time.sleep(2)

    if sock is None:
        print()
        print("[FAIL] Timed out. Is the game running with the mod?")
        sys.exit(1)

    print("[OK] Connected to action port 5556!")
    print()
    print("Waiting a few seconds for mod to fully initialize...")
    sock.settimeout(30)
    time.sleep(3)

    passed = 0
    failed = 0

    tests = [test_unknown_command, test_malformed_json, test_missing_command_field]

    for test_fn in tests:
        try:
            if test_fn(sock):
                passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            failed += 1
        except Exception as e:
            print(f"  [FAIL] Exception: {e}")
            failed += 1

    print()
    print("-" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    print("-" * 60)

    sock.close()

    if failed > 0:
        sys.exit(1)
    else:
        print("[PASS] All action routing tests passed!")


if __name__ == "__main__":
    main()

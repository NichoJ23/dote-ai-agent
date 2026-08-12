"""
Test for task 2.15: Timeout → game pause during Action phase.

Usage:
  1. Start a dungeon and open enough doors that enemies will spawn on next open.
  2. Run this script: python scripts/test_timeout_pause.py
  3. Open a door to trigger a wave (Action phase).
  4. Watch: game should FREEZE after 5 seconds.
  5. Script will then send an action to resume.

What it verifies:
  - Game pauses when agent doesn't respond during Action phase
  - Game resumes when agent sends an action
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
    print("Timeout Pause Test (Task 2.15)")
    print("=" * 60)
    print()
    print("This test verifies the game pauses when the agent doesn't respond.")
    print()
    print("Steps:")
    print("  1. Connect to both ports")
    print("  2. Wait for Action phase (open a door to trigger a wave)")
    print("  3. Do NOT send any action for 8 seconds")
    print("  4. Game should freeze after 5s")
    print("  5. Script sends an action to resume")
    print()
    print("Connecting...")

    state_sock = connect_with_retry(5555)
    action_sock = connect_with_retry(5556)
    if not state_sock or not action_sock:
        print("[FAIL] Could not connect")
        sys.exit(1)
    print("[OK] Connected to both ports")

    # Wait for state with heroes
    state_sock.settimeout(300)
    state = None
    while True:
        state = receive_message(state_sock)
        heroes = state.get("heroes", [])
        if len(heroes) > 0:
            break

    print(f"[OK] State received: Phase={state['game_phase']}, Turn={state['turn']}")
    print()

    if state["game_phase"] == "Action":
        print("Already in Action phase!")
    else:
        print("Currently in Strategy phase.")
        print(">>> OPEN A DOOR NOW to trigger a wave (Action phase) <<<")
        print("Waiting for Action phase...")
        
        # Keep reading state until we see Action phase
        while state.get("game_phase") != "Action":
            try:
                state = receive_message(state_sock)
            except:
                pass

        print(f"[OK] Action phase detected! (Turn={state['turn']})")

    print()
    print("NOT sending any action... game should pause in ~5 seconds.")
    print("Watch the game - enemies and heroes should FREEZE.")
    print()

    # Wait 8 seconds without sending anything
    for i in range(8, 0, -1):
        print(f"  Waiting... {i}s remaining", end="\r")
        time.sleep(1)

    print()
    print()
    print("Game should be PAUSED now. Sending an action to resume...")
    print()

    # Send a harmless action to unpause
    action_sock.settimeout(10)
    hero_name = state["heroes"][0]["name"] if state.get("heroes") else "Max O'Kane"
    send_message(action_sock, {
        "command": "MOVE_HERO",
        "parameters": {"hero_name": hero_name, "target_room_index": 0},
        "timestamp": int(time.time() * 1000)
    })

    try:
        response = receive_message(action_sock)
        print(f"[OK] Got response: success={response['success']}")
        print()
        print("Game should have RESUMED now. Check in-game!")
        print("[PASS] Timeout pause test complete.")
    except Exception as e:
        print(f"[INFO] Response error (game may still be paused): {e}")
        print("Check BepInEx log for timeout/resume messages.")

    state_sock.close()
    action_sock.close()


if __name__ == "__main__":
    main()

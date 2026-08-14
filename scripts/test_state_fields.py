"""
Quick in-game test: connect to the mod, receive one state, and print
hero stats + buildable blueprints to verify the new fields are coming through.

Usage:
  1. Launch the game with the mod loaded
  2. Start a dungeon run
  3. Run: python scripts/test_state_fields.py
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


def receive_message(sock):
    raw_len = recv_exact(sock, 4)
    msg_len = struct.unpack(">I", raw_len)[0]
    payload = recv_exact(sock, msg_len)
    return json.loads(payload.decode("utf-8"))


def main():
    print("Connecting to state port 5555...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30)
    try:
        sock.connect(("127.0.0.1", 5555))
    except (ConnectionRefusedError, socket.timeout):
        print("FAILED: Could not connect. Is the game running with the mod?")
        sys.exit(1)

    print("Connected! Waiting for state...\n")
    state = receive_message(sock)
    sock.close()

    # --- Hero Stats ---
    print("=" * 60)
    print("HERO STATS")
    print("=" * 60)
    heroes = state.get("heroes", [])
    if not heroes:
        print("  (no heroes in state)")
    for h in heroes:
        print(f"\n  {h['name']} (Lvl {h['level']}, {h['faction']})")
        print(f"    HP:       {h['hp']:.0f} / {h['max_hp']:.0f}")
        print(f"    Attack:   {h.get('attack', '???')}")
        print(f"    Defense:  {h.get('defense', '???')}")
        print(f"    Speed:    {h.get('speed', '???')}")
        print(f"    Wit:      {h.get('wit', '???')}")
        print(f"    AtkCD:    {h.get('attack_cooldown', '???')}")
        print(f"    Room:     {h['room_index']}")
        equip = h.get("equipment", [])
        if equip:
            print(f"    Equip:    {', '.join(e.get('item_name') or '(empty)' for e in equip)}")

    # --- Buildable Blueprints ---
    print("\n" + "=" * 60)
    print("BUILDABLE BLUEPRINTS (unlocked modules)")
    print("=" * 60)
    blueprints = state.get("buildable_blueprints", [])
    if not blueprints:
        print("  (none — field missing or empty)")
    else:
        # Group by category
        by_cat = {}
        for bp in blueprints:
            cat = bp.get("category", "Unknown")
            by_cat.setdefault(cat, []).append(bp)

        for cat, bps in sorted(by_cat.items()):
            print(f"\n  [{cat}]")
            for bp in bps:
                print(f"    {bp['name']}  (module: {bp.get('module_name')}, "
                      f"lvl {bp.get('level')}, cost: {bp.get('industry_cost'):.0f} industry)")

    # --- Researchable Blueprints (existing) ---
    print("\n" + "=" * 60)
    print("RESEARCHABLE BLUEPRINTS (available to research)")
    print("=" * 60)
    research = state.get("researchable_blueprints", [])
    if not research:
        print("  (none available)")
    else:
        for bp in research:
            print(f"    {bp['name']}  (cost: {bp.get('science_cost', 0):.0f} science)")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()

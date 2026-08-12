# manual_test_phase3.py — run with game + mod active
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "agent"))

from ipc_client import IpcClient
from state_parser import StateParser
from graph_builder import GraphBuilder
import graph_utils

client = IpcClient(connect_timeout=30.0)
print("Connecting to game...")
client.connect()
print("Connected. Waiting for state...")

raw = client.receive_state(timeout=60.0)
print(f"Received raw state with {len(raw)} top-level keys: {list(raw.keys())}")

parser = StateParser()
try:
    state = parser.parse(raw)
    print(f"\nParsed OK!")
    print(f"  Turn: {state.turn}, Floor: {state.floor}, Phase: {state.game_phase.value}")
    print(f"  Crystal: {state.crystal_state}")
    print(f"  Rooms: {len(state.rooms)}, Heroes: {len(state.heroes)}, Mobs: {len(state.mobs)}")
    print(f"  Closed Doors: {len(state.closed_doors)}")
    print(f"  Merchants: {len(state.merchants)}, Recruits: {len(state.recruitable_heroes)}")
    print(f"  Dropped items: {len(state.dropped_items)}")
    print(f"  Backpack: {len(state.backpack_items)}, Shared inv: {len(state.shared_inventory_items)}")
    print(f"  Researchable: {state.researchable_blueprints}")
    if state.resources:
        r = state.resources
        print(f"  Resources: I={r.industry:.0f} F={r.food:.0f} S={r.science:.0f} D={r.dust:.0f}/{r.dust_max:.0f}")
    else:
        print("  Resources: None (not yet available)")
    print(f"\n  Heroes:")
    for h in state.heroes:
        print(f"    {h.name} (Lv{h.level}) [{h.faction}] Room {h.room_index} HP={h.hp:.0f}/{h.max_hp:.0f} Op={h.is_operating}")
except Exception as e:
    print(f"\nPARSE FAILED: {e}")
    print("\nTrying lenient parse...")
    try:
        state = parser.parse_lenient(raw)
        print(f"Lenient parse OK — some fields may have used defaults")
    except Exception as e2:
        print(f"Lenient parse also failed: {e2}")
        client.disconnect()
        sys.exit(1)

# Build graph
graph = GraphBuilder().build(state)
print(f"\nGraph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
closed = graph_utils.unopened_doors(graph)
print(f"  Closed doors: {closed}")
start = state.start_room_index
print(f"  Reachable from start (room {start}): {graph_utils.reachable_rooms(graph, start)}")
print(f"  Bottlenecks: {graph_utils.bottleneck_rooms(graph)}")
path = graph_utils.escape_path_rooms(graph)
print(f"  Escape path: {path if path else 'no open path to exit yet'}")

client.disconnect()
print("\nDone — all Phase 3 components working with live data!")

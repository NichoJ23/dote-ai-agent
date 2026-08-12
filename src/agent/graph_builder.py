"""
GraphBuilder: Converts parsed game state rooms into a NetworkX graph.

Rooms become nodes with attributes (powered, auto_powered, modules, unit counts, EMP, etc.).
Edges represent adjacency between rooms, with door open/closed status.

The mod sends:
- rooms[].adjacent_room_indices: all neighboring rooms (edges always exist)
- closed_doors[]: list of {room1_index, room2_index} for doors that are STILL CLOSED

So: an edge is "open" if it exists in adjacency but is NOT in closed_doors.
"""

from __future__ import annotations

import networkx as nx

from state_parser import ClosedDoor, GameStatePayload, RoomState


class GraphBuilder:
    """
    Builds a NetworkX undirected Graph from a GameStatePayload.

    Nodes: room indices with attributes.
    Edges: adjacency connections with is_open status (True = door opened, False = still closed).

    Usage:
        builder = GraphBuilder()
        graph = builder.build(state)
        # graph.nodes[0]["is_powered"] -> True
        # graph.edges[0, 1]["is_open"] -> True
    """

    def build(self, state: GameStatePayload) -> nx.Graph:
        """
        Build the room graph from a full game state payload.

        Args:
            state: Validated GameStatePayload from StateParser.

        Returns:
            NetworkX Graph with room nodes and adjacency edges.
        """
        graph = nx.Graph()

        # Build set of closed doors for O(1) lookup
        closed_set = self._build_closed_set(state.closed_doors)

        # Add nodes (rooms)
        for room in state.rooms:
            graph.add_node(
                room.index,
                is_powered=room.is_powered,
                is_auto_powered=room.is_auto_powered,
                is_exit_room=room.is_exit_room,
                is_start_room=room.is_start_room,
                is_fully_opened=room.is_fully_opened,
                depth=room.depth,
                suffers_emp=room.suffers_emp,
                emp_turns_remaining=room.emp_turns_remaining,
                dust_loot_amount=room.dust_loot_amount,
                has_artifact=room.has_artifact,
                has_stele=room.has_stele,
                major_module_name=room.major_module_name,
                minor_module_names=list(room.minor_module_names),
                minor_slot_count=room.minor_slot_count,
                hero_count=room.hero_count,
                mob_count=room.mob_count,
                npc_count=room.npc_count,
            )

        # Add edges from adjacency lists
        for room in state.rooms:
            for adj_idx in room.adjacent_room_indices:
                if not graph.has_edge(room.index, adj_idx):
                    # Check if this door is closed
                    edge_key = frozenset((room.index, adj_idx))
                    is_open = edge_key not in closed_set
                    graph.add_edge(room.index, adj_idx, is_open=is_open)

        return graph

    def build_from_rooms(
        self, rooms: list[RoomState], closed_doors: list[ClosedDoor] | None = None
    ) -> nx.Graph:
        """
        Build a graph from just rooms and optionally closed doors.
        Useful for testing or when you only have partial state.
        """
        graph = nx.Graph()
        closed_set = self._build_closed_set(closed_doors or [])

        for room in rooms:
            graph.add_node(
                room.index,
                is_powered=room.is_powered,
                is_auto_powered=room.is_auto_powered,
                is_exit_room=room.is_exit_room,
                is_start_room=room.is_start_room,
                is_fully_opened=room.is_fully_opened,
                depth=room.depth,
                suffers_emp=room.suffers_emp,
                emp_turns_remaining=room.emp_turns_remaining,
                dust_loot_amount=room.dust_loot_amount,
                has_artifact=room.has_artifact,
                has_stele=room.has_stele,
                major_module_name=room.major_module_name,
                minor_module_names=list(room.minor_module_names),
                minor_slot_count=room.minor_slot_count,
                hero_count=room.hero_count,
                mob_count=room.mob_count,
                npc_count=room.npc_count,
            )

        for room in rooms:
            for adj_idx in room.adjacent_room_indices:
                if not graph.has_edge(room.index, adj_idx):
                    edge_key = frozenset((room.index, adj_idx))
                    is_open = edge_key not in closed_set
                    graph.add_edge(room.index, adj_idx, is_open=is_open)

        return graph

    @staticmethod
    def _build_closed_set(closed_doors: list[ClosedDoor]) -> set[frozenset]:
        """Build a set of frozenset pairs for O(1) closed-door lookup."""
        return {frozenset((d.room1_index, d.room2_index)) for d in closed_doors}

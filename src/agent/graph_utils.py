"""
Graph utility functions for strategic reasoning over the room topology.

All functions operate on a NetworkX Graph produced by GraphBuilder.
They support the macro-planner (pathfinding, power decisions, exploration targets)
and escape-planner (exit path, bottleneck detection).
"""

from __future__ import annotations

import networkx as nx


def shortest_path_to_crystal(graph: nx.Graph, from_room: int) -> list[int]:
    """
    Find the shortest path from a room to the crystal room (start room).

    Only traverses edges where is_open=True (can't walk through closed doors).

    Args:
        graph: Room graph from GraphBuilder.
        from_room: Starting room index.

    Returns:
        List of room indices from from_room to crystal room (inclusive).
        Empty list if no path exists through open doors.
    """
    crystal_room = _find_room_with_attr(graph, "is_start_room", True)
    if crystal_room is None:
        return []
    return _shortest_path_open_doors(graph, from_room, crystal_room)


def shortest_path_to_exit(graph: nx.Graph, from_room: int) -> list[int]:
    """
    Find the shortest path from a room to the exit room.

    Only traverses edges where is_open=True.

    Args:
        graph: Room graph from GraphBuilder.
        from_room: Starting room index.

    Returns:
        List of room indices from from_room to exit room (inclusive).
        Empty list if no path exists through open doors.
    """
    exit_room = _find_room_with_attr(graph, "is_exit_room", True)
    if exit_room is None:
        return []
    return _shortest_path_open_doors(graph, from_room, exit_room)


def unpowered_neighbors(graph: nx.Graph, room_index: int) -> list[int]:
    """
    Get all neighbors of a room that are unpowered and reachable (door open).

    Useful for identifying rooms that could benefit from powering.

    Args:
        graph: Room graph from GraphBuilder.
        room_index: The room to check neighbors of.

    Returns:
        List of neighbor room indices that are unpowered and connected by open doors.
    """
    result = []
    for neighbor in graph.neighbors(room_index):
        edge_data = graph.edges[room_index, neighbor]
        if edge_data.get("is_open", False) and not graph.nodes[neighbor].get("is_powered", False):
            result.append(neighbor)
    return result


def room_centrality_scores(graph: nx.Graph) -> dict[int, float]:
    """
    Compute betweenness centrality for all rooms considering only open doors.

    Rooms with high centrality are bottlenecks — critical for defense and powering.

    Args:
        graph: Room graph from GraphBuilder.

    Returns:
        Dict mapping room_index -> centrality score (0.0 to 1.0).
    """
    open_subgraph = _open_door_subgraph(graph)
    if len(open_subgraph.nodes) == 0:
        return {}
    return nx.betweenness_centrality(open_subgraph)


def bottleneck_rooms(graph: nx.Graph, top_n: int = 3) -> list[int]:
    """
    Identify the top-N bottleneck rooms by betweenness centrality.

    These are the rooms where enemies are most likely to pass through,
    making them ideal for defensive module placement and hero positioning.

    Args:
        graph: Room graph from GraphBuilder.
        top_n: Number of top bottleneck rooms to return.

    Returns:
        List of room indices sorted by centrality (highest first).
    """
    scores = room_centrality_scores(graph)
    if not scores:
        return []
    sorted_rooms = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [room_index for room_index, _ in sorted_rooms[:top_n]]


def unopened_doors(graph: nx.Graph) -> list[tuple[int, int]]:
    """
    Find all edges (door connections) that are still closed.

    These represent exploration targets — doors the agent can open
    to discover new rooms or complete connectivity.

    Args:
        graph: Room graph from GraphBuilder.

    Returns:
        List of (room_a, room_b) tuples where the door is closed.
    """
    closed = []
    for u, v, data in graph.edges(data=True):
        if not data.get("is_open", False):
            closed.append((u, v))
    return closed


def escape_path_rooms(graph: nx.Graph, crystal_room: int | None = None) -> list[int]:
    """
    Compute the set of rooms along the shortest path from crystal to exit.

    These rooms should be powered during escape to minimize enemy spawns.
    Only considers open doors.

    Args:
        graph: Room graph from GraphBuilder.
        crystal_room: Override crystal room index. If None, auto-detects (start room).

    Returns:
        List of room indices on the escape path (inclusive of start and end).
        Empty list if no path exists.
    """
    if crystal_room is None:
        crystal_room = _find_room_with_attr(graph, "is_start_room", True)
    if crystal_room is None:
        return []

    exit_room = _find_room_with_attr(graph, "is_exit_room", True)
    if exit_room is None:
        return []

    return _shortest_path_open_doors(graph, crystal_room, exit_room)


def reachable_rooms(graph: nx.Graph, from_room: int) -> set[int]:
    """
    Get all rooms reachable from a starting room via open doors.

    Args:
        graph: Room graph from GraphBuilder.
        from_room: Starting room index.

    Returns:
        Set of room indices reachable through open doors (includes from_room).
    """
    open_subgraph = _open_door_subgraph(graph)
    if from_room not in open_subgraph:
        return {from_room}
    return set(nx.node_connected_component(open_subgraph, from_room))


def rooms_with_mobs(graph: nx.Graph) -> list[int]:
    """Get all room indices that currently have mobs."""
    return [n for n, d in graph.nodes(data=True) if d.get("mob_count", 0) > 0]


def emp_affected_rooms(graph: nx.Graph) -> list[int]:
    """Get all room indices currently suffering from EMP."""
    return [n for n, d in graph.nodes(data=True) if d.get("suffers_emp", False)]


# --- Private helpers ---


def _find_room_with_attr(graph: nx.Graph, attr: str, value) -> int | None:
    """Find the first room with a given attribute value."""
    for node, data in graph.nodes(data=True):
        if data.get(attr) == value:
            return node
    return None


def _open_door_subgraph(graph: nx.Graph) -> nx.Graph:
    """Create a subgraph containing only edges where is_open=True."""
    open_edges = [(u, v) for u, v, d in graph.edges(data=True) if d.get("is_open", False)]
    subgraph = graph.edge_subgraph(open_edges).copy() if open_edges else nx.Graph()
    # Add isolated nodes (rooms with no open doors to them)
    for node in graph.nodes:
        if node not in subgraph:
            subgraph.add_node(node, **graph.nodes[node])
    return subgraph


def _shortest_path_open_doors(graph: nx.Graph, source: int, target: int) -> list[int]:
    """Find shortest path using only open doors."""
    open_subgraph = _open_door_subgraph(graph)
    try:
        return nx.shortest_path(open_subgraph, source, target)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []

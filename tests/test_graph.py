"""
Unit tests for GraphBuilder and graph_utils.

Tests the actual wire format: rooms use 'index', adjacency via 'adjacent_room_indices',
closed doors as separate list, 'is_start_room' for crystal.
"""

import sys
from pathlib import Path

import networkx as nx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "agent"))

from graph_builder import GraphBuilder
from graph_utils import (
    bottleneck_rooms,
    emp_affected_rooms,
    escape_path_rooms,
    reachable_rooms,
    room_centrality_scores,
    rooms_with_mobs,
    shortest_path_to_crystal,
    shortest_path_to_exit,
    unopened_doors,
    unpowered_neighbors,
)
from state_parser import StateParser


# --- Fixtures ---


def _make_linear_state(n_rooms=4):
    """Linear chain: 0--1--2--3, all doors open, room 0 is start (crystal), room n-1 is exit."""
    rooms = []
    for i in range(n_rooms):
        adj = []
        if i > 0:
            adj.append(i - 1)
        if i < n_rooms - 1:
            adj.append(i + 1)
        rooms.append({
            "index": i,
            "is_powered": i == 0,
            "is_auto_powered": i == 0,
            "is_exit_room": i == n_rooms - 1,
            "is_start_room": i == 0,
            "is_fully_opened": True,
            "depth": i,
            "suffers_emp": False,
            "emp_turns_remaining": 0,
            "dust_loot_amount": 0,
            "has_artifact": False,
            "has_stele": False,
            "adjacent_room_indices": adj,
            "major_module_name": "IndGen" if i == 0 else None,
            "minor_module_names": [],
            "minor_slot_count": 2,
            "hero_count": 1 if i == 0 else 0,
            "mob_count": 1 if i == 2 else 0,
            "npc_count": 0,
        })
    return {
        "turn": 1,
        "floor": 1,
        "game_phase": "Strategy",
        "crystal_state": "Plugged",
        "exit_room_index": n_rooms - 1,
        "start_room_index": 0,
        "resources": {"industry": 10, "food": 10, "science": 5, "dust": 5, "dust_max": 10,
                      "industry_per_turn": 3, "food_per_turn": 2, "science_per_turn": 1,
                      "dust_per_turn": 0, "room_power_cost": 1, "powered_room_count": 1},
        "rooms": rooms,
        "closed_doors": [],  # All open
        "heroes": [{"name": "Hero1", "room_index": 0, "hp": 100, "max_hp": 100, "level": 1}],
        "mobs": [{"type": "Zed", "room_index": 2, "hp": 30, "max_hp": 50, "target_type": "AntiHeroMob"}],
        "merchants": [],
        "recruitable_heroes": [],
        "dropped_items": [],
        "backpack_items": [],
        "shared_inventory_items": [],
        "researchable_blueprints": [],
    }


def _make_loop_state():
    """
    Room graph with a loop and closed doors:
        0(start) --open-- 1 --open-- 2
        |                             |
        +-------closed--- 3(exit) ---closed---+

    Adjacency: 0:[1,3], 1:[0,2], 2:[1,3], 3:[0,2]
    Closed: 0-3, 2-3
    """
    rooms = [
        {"index": 0, "is_powered": True, "is_auto_powered": True, "is_exit_room": False, "is_start_room": True,
         "is_fully_opened": True, "depth": 0, "suffers_emp": False, "emp_turns_remaining": 0,
         "dust_loot_amount": 0, "has_artifact": False, "has_stele": False,
         "adjacent_room_indices": [1, 3], "major_module_name": None, "minor_module_names": [],
         "minor_slot_count": 2, "hero_count": 1, "mob_count": 0, "npc_count": 0},
        {"index": 1, "is_powered": True, "is_auto_powered": False, "is_exit_room": False, "is_start_room": False,
         "is_fully_opened": True, "depth": 1, "suffers_emp": True, "emp_turns_remaining": 1,
         "dust_loot_amount": 0, "has_artifact": False, "has_stele": False,
         "adjacent_room_indices": [0, 2], "major_module_name": None, "minor_module_names": [],
         "minor_slot_count": 2, "hero_count": 0, "mob_count": 2, "npc_count": 0},
        {"index": 2, "is_powered": False, "is_auto_powered": False, "is_exit_room": False, "is_start_room": False,
         "is_fully_opened": True, "depth": 2, "suffers_emp": False, "emp_turns_remaining": 0,
         "dust_loot_amount": 0, "has_artifact": False, "has_stele": False,
         "adjacent_room_indices": [1, 3], "major_module_name": None, "minor_module_names": [],
         "minor_slot_count": 2, "hero_count": 1, "mob_count": 0, "npc_count": 0},
        {"index": 3, "is_powered": False, "is_auto_powered": False, "is_exit_room": True, "is_start_room": False,
         "is_fully_opened": False, "depth": 3, "suffers_emp": False, "emp_turns_remaining": 0,
         "dust_loot_amount": 0, "has_artifact": False, "has_stele": False,
         "adjacent_room_indices": [0, 2], "major_module_name": None, "minor_module_names": [],
         "minor_slot_count": 2, "hero_count": 0, "mob_count": 0, "npc_count": 0},
    ]
    return {
        "turn": 5,
        "floor": 1,
        "game_phase": "Strategy",
        "crystal_state": "Plugged",
        "exit_room_index": 3,
        "start_room_index": 0,
        "resources": {"industry": 20, "food": 15, "science": 8, "dust": 7, "dust_max": 12,
                      "industry_per_turn": 4, "food_per_turn": 2, "science_per_turn": 1,
                      "dust_per_turn": 0, "room_power_cost": 1, "powered_room_count": 2},
        "rooms": rooms,
        "closed_doors": [
            {"room1_index": 0, "room2_index": 3, "is_opening": False},
            {"room1_index": 2, "room2_index": 3, "is_opening": False},
        ],
        "heroes": [
            {"name": "Max", "room_index": 0, "hp": 200, "max_hp": 250, "level": 2},
            {"name": "Gork", "room_index": 2, "hp": 150, "max_hp": 150, "level": 1},
        ],
        "mobs": [
            {"type": "Silic", "room_index": 1, "hp": 40, "max_hp": 60, "target_type": "AntiHeroMob"},
            {"type": "Silic", "room_index": 1, "hp": 35, "max_hp": 60, "target_type": "AntiHeroMob"},
        ],
        "merchants": [],
        "recruitable_heroes": [],
        "dropped_items": [],
        "backpack_items": [],
        "shared_inventory_items": [],
        "researchable_blueprints": [],
    }


# --- GraphBuilder Tests ---


class TestGraphBuilder:
    def test_node_count(self):
        state = StateParser().parse(_make_linear_state(4))
        graph = GraphBuilder().build(state)
        assert len(graph.nodes) == 4

    def test_edge_count_linear(self):
        state = StateParser().parse(_make_linear_state(4))
        graph = GraphBuilder().build(state)
        assert len(graph.edges) == 3

    def test_node_attributes(self):
        state = StateParser().parse(_make_linear_state(4))
        graph = GraphBuilder().build(state)
        assert graph.nodes[0]["is_powered"] is True
        assert graph.nodes[0]["is_auto_powered"] is True
        assert graph.nodes[0]["is_start_room"] is True
        assert graph.nodes[3]["is_exit_room"] is True

    def test_all_doors_open(self):
        state = StateParser().parse(_make_linear_state(4))
        graph = GraphBuilder().build(state)
        for u, v, d in graph.edges(data=True):
            assert d["is_open"] is True

    def test_closed_doors_marked(self):
        state = StateParser().parse(_make_loop_state())
        graph = GraphBuilder().build(state)
        assert graph.edges[0, 3]["is_open"] is False
        assert graph.edges[2, 3]["is_open"] is False
        assert graph.edges[0, 1]["is_open"] is True
        assert graph.edges[1, 2]["is_open"] is True

    def test_hero_count(self):
        state = StateParser().parse(_make_linear_state(4))
        graph = GraphBuilder().build(state)
        assert graph.nodes[0]["hero_count"] == 1
        assert graph.nodes[1]["hero_count"] == 0

    def test_mob_count(self):
        state = StateParser().parse(_make_linear_state(4))
        graph = GraphBuilder().build(state)
        assert graph.nodes[2]["mob_count"] == 1

    def test_loop_graph_edges(self):
        state = StateParser().parse(_make_loop_state())
        graph = GraphBuilder().build(state)
        assert len(graph.nodes) == 4
        # Edges: 0-1, 0-3, 1-2, 2-3 = 4
        assert len(graph.edges) == 4

    def test_module_attributes(self):
        state = StateParser().parse(_make_linear_state(4))
        graph = GraphBuilder().build(state)
        assert graph.nodes[0]["major_module_name"] == "IndGen"
        assert graph.nodes[1]["major_module_name"] is None

    def test_emp_attribute(self):
        state = StateParser().parse(_make_loop_state())
        graph = GraphBuilder().build(state)
        assert graph.nodes[1]["suffers_emp"] is True
        assert graph.nodes[0]["suffers_emp"] is False


# --- Graph Utils Tests ---


class TestShortestPathToCrystal:
    def test_direct_path(self):
        state = StateParser().parse(_make_linear_state(4))
        graph = GraphBuilder().build(state)
        path = shortest_path_to_crystal(graph, 2)
        assert path == [2, 1, 0]

    def test_from_crystal_room(self):
        state = StateParser().parse(_make_linear_state(4))
        graph = GraphBuilder().build(state)
        path = shortest_path_to_crystal(graph, 0)
        assert path == [0]

    def test_unreachable_through_closed(self):
        state = StateParser().parse(_make_loop_state())
        graph = GraphBuilder().build(state)
        # Room 3 has only closed doors
        path = shortest_path_to_crystal(graph, 3)
        assert path == []


class TestShortestPathToExit:
    def test_linear_path(self):
        state = StateParser().parse(_make_linear_state(4))
        graph = GraphBuilder().build(state)
        path = shortest_path_to_exit(graph, 0)
        assert path == [0, 1, 2, 3]

    def test_unreachable_exit(self):
        state = StateParser().parse(_make_loop_state())
        graph = GraphBuilder().build(state)
        path = shortest_path_to_exit(graph, 0)
        assert path == []


class TestUnpoweredNeighbors:
    def test_finds_unpowered(self):
        state = StateParser().parse(_make_linear_state(4))
        graph = GraphBuilder().build(state)
        result = unpowered_neighbors(graph, 0)
        assert 1 in result

    def test_ignores_powered(self):
        state = StateParser().parse(_make_loop_state())
        graph = GraphBuilder().build(state)
        # Room 1's open neighbors: 0 (powered), 2 (unpowered)
        result = unpowered_neighbors(graph, 1)
        assert 2 in result
        assert 0 not in result

    def test_ignores_closed_doors(self):
        state = StateParser().parse(_make_loop_state())
        graph = GraphBuilder().build(state)
        # Room 0's neighbors: 1 (open), 3 (closed)
        result = unpowered_neighbors(graph, 0)
        assert 3 not in result


class TestCentrality:
    def test_linear_middle_most_central(self):
        state = StateParser().parse(_make_linear_state(5))
        graph = GraphBuilder().build(state)
        scores = room_centrality_scores(graph)
        assert scores[2] >= scores[0]
        assert scores[2] >= scores[4]

    def test_bottleneck_top_n(self):
        state = StateParser().parse(_make_linear_state(5))
        graph = GraphBuilder().build(state)
        result = bottleneck_rooms(graph, top_n=2)
        assert len(result) == 2
        assert result[0] == 2

    def test_empty_graph(self):
        graph = nx.Graph()
        assert room_centrality_scores(graph) == {}
        assert bottleneck_rooms(graph) == []


class TestUnopenedDoors:
    def test_all_open(self):
        state = StateParser().parse(_make_linear_state(3))
        graph = GraphBuilder().build(state)
        assert unopened_doors(graph) == []

    def test_finds_closed(self):
        state = StateParser().parse(_make_loop_state())
        graph = GraphBuilder().build(state)
        closed = unopened_doors(graph)
        assert len(closed) == 2
        closed_set = {frozenset(e) for e in closed}
        assert frozenset({0, 3}) in closed_set
        assert frozenset({2, 3}) in closed_set


class TestEscapePathRooms:
    def test_linear(self):
        state = StateParser().parse(_make_linear_state(4))
        graph = GraphBuilder().build(state)
        path = escape_path_rooms(graph)
        assert path == [0, 1, 2, 3]

    def test_no_path(self):
        state = StateParser().parse(_make_loop_state())
        graph = GraphBuilder().build(state)
        assert escape_path_rooms(graph) == []


class TestReachableRooms:
    def test_all_connected(self):
        state = StateParser().parse(_make_linear_state(4))
        graph = GraphBuilder().build(state)
        assert reachable_rooms(graph, 0) == {0, 1, 2, 3}

    def test_isolated(self):
        state = StateParser().parse(_make_loop_state())
        graph = GraphBuilder().build(state)
        assert reachable_rooms(graph, 3) == {3}

    def test_partial(self):
        state = StateParser().parse(_make_loop_state())
        graph = GraphBuilder().build(state)
        assert reachable_rooms(graph, 0) == {0, 1, 2}


class TestAdditionalUtils:
    def test_rooms_with_mobs(self):
        state = StateParser().parse(_make_loop_state())
        graph = GraphBuilder().build(state)
        assert rooms_with_mobs(graph) == [1]

    def test_emp_affected_rooms(self):
        state = StateParser().parse(_make_loop_state())
        graph = GraphBuilder().build(state)
        assert emp_affected_rooms(graph) == [1]

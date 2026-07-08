"""Pure Python PD-code mid-simplification prototype.

This module is the cleaned-up Python counterpart of the C++ implementation.
It exposes both a Python API and a command-line interface using the same
PD-code input style as the project executable and `cppkh`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, Iterable, List, Optional, Sequence, Set, Tuple


PDCode = List[Tuple[int, int, int, int]]
BLOCKED_WEIGHT = 10_000


@dataclass(frozen=True, order=True)
class Endpoint:
    crossing: int
    strand: int

    @property
    def key(self) -> int:
        return self.crossing * 4 + self.strand

    @staticmethod
    def from_key(key: int) -> "Endpoint":
        return Endpoint(key // 4, key % 4)


@dataclass
class GreenCrossing:
    from_face: int
    to_face: int
    strand_level: str

    def to_json(self) -> Dict[str, object]:
        return {
            "from_face": self.from_face,
            "to_face": self.to_face,
            "strand_level": self.strand_level,
        }


@dataclass
class ComponentSummary:
    crossing_indices: List[int]


@dataclass
class ComponentAnalysis:
    components: List[ComponentSummary] = field(default_factory=list)
    crossingless_components: int = 0

    @property
    def components_with_crossings(self) -> int:
        return len(self.components)

    @property
    def total_components(self) -> int:
        return self.components_with_crossings + self.crossingless_components

    def to_json(self) -> Dict[str, int]:
        return {
            "components_with_crossings": self.components_with_crossings,
            "crossingless_components": self.crossingless_components,
            "total_components": self.total_components,
        }


@dataclass
class SimplificationResult:
    found: bool = False
    direction: str = "left"
    red_path: List[Endpoint] = field(default_factory=list)
    green_path: List[int] = field(default_factory=list)
    green_crossings: List[GreenCrossing] = field(default_factory=list)
    tested_red_paths: int = 0
    tested_green_paths: int = 0

    def to_json(
        self,
        input_components: Optional[ComponentAnalysis] = None,
        after_removal_components: Optional[ComponentAnalysis] = None,
        pd_simplification: Optional[PDSimplificationResult] = None,
        search_components: Optional[ComponentAnalysis] = None,
        label: Optional[str] = None,
    ) -> Dict[str, object]:
        data: Dict[str, object] = {}
        if label is not None:
            data["label"] = label
        data["simplification_found"] = self.found
        if input_components is not None:
            data["input_components"] = input_components.to_json()
        if after_removal_components is not None:
            data["after_removal_components"] = after_removal_components.to_json()
        if pd_simplification is not None and search_components is not None:
            data["pd_simplification"] = pd_simplification.to_json()
            data["search_components"] = search_components.to_json()
        data["tested_red_paths"] = self.tested_red_paths
        data["tested_green_paths"] = self.tested_green_paths
        if self.found:
            data["direction"] = self.direction
            data["red_path"] = [
                {"crossing": endpoint.crossing, "strand": endpoint.strand}
                for endpoint in self.red_path
            ]
            data["green_path"] = list(self.green_path)
            data["green_crossings"] = [
                crossing.to_json() for crossing in self.green_crossings
            ]
        return data


@dataclass
class PDSimplificationResult:
    code: PDCode
    crossingless_components: int = 0
    reidemeister_i_moves: int = 0
    nugatory_crossing_moves: int = 0

    def to_json(self) -> Dict[str, object]:
        return {
            "enabled": True,
            "reidemeister_i_moves": self.reidemeister_i_moves,
            "nugatory_crossing_moves": self.nugatory_crossing_moves,
            "output_crossings": len(self.code),
        }


@dataclass
class PDJob:
    label: str
    code: PDCode = field(default_factory=list)
    implied_crossingless_components: int = 0
    error: str = ""


def endpoint_key(endpoint: Endpoint) -> int:
    return endpoint.key


def endpoint_from_key(key: int) -> Endpoint:
    return Endpoint.from_key(key)


def face_pair_key(a: int, b: int) -> Tuple[int, int]:
    return (a, b) if a <= b else (b, a)


def parse_pd_code(text: str) -> PDCode:
    numbers = [int(token) for token in re.findall(r"-?\d+", text)]
    if not numbers:
        return []
    if len(numbers) % 4 != 0:
        raise ValueError("The input must contain a multiple of four integers")
    return [
        (numbers[i], numbers[i + 1], numbers[i + 2], numbers[i + 3])
        for i in range(0, len(numbers), 4)
    ]


def format_pd_code(code: PDCode) -> str:
    parts = ["X[{},{},{},{}]".format(*crossing) for crossing in code]
    return "PD[" + ",".join(parts) + "]"


def compact_text(text: str) -> str:
    return "".join(ch for ch in text if not ch.isspace())


def denotes_crossingless_unknot(text: str) -> bool:
    compact = compact_text(text)
    return compact in {"PD[]", "[]"}


def trim(text: str) -> str:
    return text.strip(" \t\r\n")


class Diagram:
    def __init__(self, code: PDCode):
        self.code = list(code)
        self.adjacent: List[List[Endpoint]] = [
            [Endpoint(-1, -1) for _ in range(4)] for _ in self.code
        ]
        self.directions: List[List[List[bool]]] = [
            [[False for _ in range(4)] for _ in range(4)] for _ in self.code
        ]
        self.signs: List[int] = [0 for _ in self.code]
        self._build_adjacency()
        starts = self._component_starts_from_pd()
        self._orient_crossings(starts)

    def opposite(self, endpoint: Endpoint) -> Endpoint:
        return self.adjacent[endpoint.crossing][endpoint.strand]

    def next(self, endpoint: Endpoint) -> Endpoint:
        return self.adjacent[endpoint.crossing][(endpoint.strand + 2) % 4]

    def next_corner(self, endpoint: Endpoint) -> Endpoint:
        return self.adjacent[endpoint.crossing][(endpoint.strand + 1) % 4]

    @staticmethod
    def rotate_endpoint(endpoint: Endpoint, offset: int) -> Endpoint:
        return Endpoint(endpoint.crossing, (endpoint.strand + offset) % 4)

    def crossing_entries(self) -> List[Endpoint]:
        entries: List[Endpoint] = []
        for crossing, sign in enumerate(self.signs):
            if sign == -1:
                entries.extend([Endpoint(crossing, 0), Endpoint(crossing, 1)])
            elif sign == 1:
                entries.extend([Endpoint(crossing, 0), Endpoint(crossing, 3)])
            else:
                raise RuntimeError("Crossing was not oriented")
        return entries

    def _build_adjacency(self) -> None:
        gluings: Dict[int, List[Endpoint]] = {}
        for crossing, labels in enumerate(self.code):
            for strand, label in enumerate(labels):
                gluings.setdefault(label, []).append(Endpoint(crossing, strand))
        for label, endpoints in gluings.items():
            if len(endpoints) != 2:
                raise ValueError(
                    f"PD label {label} appears {len(endpoints)} times; "
                    "each label must appear exactly twice"
                )
            first, second = endpoints
            self.adjacent[first.crossing][first.strand] = second
            self.adjacent[second.crossing][second.strand] = first

    def _component_starts_from_pd(self) -> List[Endpoint]:
        labels: Set[int] = set()
        gluings: Dict[int, List[Endpoint]] = {}
        for crossing, crossing_labels in enumerate(self.code):
            for strand, label in enumerate(crossing_labels):
                labels.add(label)
                gluings.setdefault(label, []).append(Endpoint(crossing, strand))

        starts: List[Endpoint] = []
        while labels:
            minimum = min(labels)
            labels.remove(minimum)
            first, second = gluings[minimum]
            if first.crossing == second.crossing:
                other_labels = set(self.code[first.crossing]) - {minimum}
                if not other_labels:
                    raise ValueError("A PD self-loop crossing must have another label")
                next_label = min(other_labels)
                direction = Endpoint(
                    first.crossing, self.code[first.crossing].index(next_label)
                )
            else:
                j1 = (first.strand + 2) % 4
                j2 = (second.strand + 2) % 4
                l1 = self.code[first.crossing][j1]
                l2 = self.code[second.crossing][j2]
                if l1 < l2:
                    next_label = l1
                    direction = Endpoint(first.crossing, j1)
                elif l2 < l1:
                    next_label = l2
                    direction = Endpoint(second.crossing, j2)
                else:
                    next_label = l1
                    if self.code[second.crossing][0] == l1 or self.code[first.crossing][0] == minimum:
                        direction = Endpoint(first.crossing, j1)
                    else:
                        direction = Endpoint(second.crossing, j2)
            starts.append(direction)
            while next_label != minimum:
                if next_label not in labels:
                    raise ValueError("PD component traversal encountered a repeated label")
                labels.remove(next_label)
                next_gluing = gluings[next_label]
                if next_gluing[0] == direction:
                    other = next_gluing[1]
                elif next_gluing[1] == direction:
                    other = next_gluing[0]
                else:
                    raise ValueError("PD component traversal lost its current endpoint")
                direction = Endpoint(other.crossing, (other.strand + 2) % 4)
                next_label = self.code[direction.crossing][direction.strand]
        return starts

    def _make_tail(self, crossing: int, strand: int) -> None:
        head = (strand + 2) % 4
        if self.directions[crossing][head][strand]:
            raise ValueError("The same crossing strand was oriented twice")
        self.directions[crossing][strand][head] = True

    def _orient_crossings(self, starts: List[Endpoint]) -> None:
        remaining = {Endpoint(crossing, strand).key for crossing in range(len(self.code)) for strand in range(4)}
        starts = list(starts)
        while remaining:
            if starts:
                start = starts.pop()
            else:
                start = endpoint_from_key(min(remaining))
            current = start
            while True:
                other = self.adjacent[current.crossing][current.strand]
                self._make_tail(other.crossing, other.strand)
                remaining.discard(current.key)
                remaining.discard(other.key)
                current = Endpoint(other.crossing, (other.strand + 2) % 4)
                if current == start:
                    break
        for crossing in range(len(self.code)):
            self._orient_crossing(crossing)

    def _orient_crossing(self, crossing: int) -> None:
        if self.directions[crossing][2][0]:
            self._rotate_crossing_180(crossing)
        if self.directions[crossing][3][1]:
            self.signs[crossing] = 1
        elif self.directions[crossing][1][3]:
            self.signs[crossing] = -1
        else:
            raise ValueError("Could not determine crossing sign from PD orientation")

    def _rotate_crossing_180(self, crossing: int) -> None:
        old_adjacent = list(self.adjacent[crossing])
        old_directions = [row[:] for row in self.directions[crossing]]
        self.directions[crossing] = [[False for _ in range(4)] for _ in range(4)]

        for i in range(4):
            other = old_adjacent[(i + 2) % 4]
            if other.crossing != crossing:
                self.adjacent[other.crossing][other.strand] = Endpoint(crossing, i)
                self.adjacent[crossing][i] = other
            else:
                self.adjacent[crossing][i] = Endpoint(crossing, (other.strand - 2) % 4)

        for a in range(4):
            for b in range(4):
                if old_directions[a][b]:
                    self.directions[crossing][(a + 2) % 4][(b + 2) % 4] = True


@dataclass
class GraphEdge:
    u: int
    v: int
    interface_u: int
    interface_v: int
    weight: int = 1

    def interface_for_face(self, face: int) -> int:
        if face == self.u:
            return self.interface_u
        if face == self.v:
            return self.interface_v
        raise RuntimeError("Face is not incident to the requested dual edge")


class DualGraph:
    def __init__(self, diagram: Diagram):
        self.edge_to_face: List[int] = []
        self.face_assignment_order: List[int] = []
        self.faces: List[List[int]] = []
        self.edges: List[GraphEdge] = []
        self.adjacency: List[List[int]] = []
        self.edge_by_faces: Dict[Tuple[int, int], int] = {}
        self._build_faces(diagram)
        self._build_edges(diagram)

    def edge_index(self, a: int, b: int) -> Optional[int]:
        return self.edge_by_faces.get(face_pair_key(a, b))

    def edge(self, a: int, b: int) -> Optional[GraphEdge]:
        index = self.edge_index(a, b)
        if index is None:
            return None
        return self.edges[index]

    def _build_faces(self, diagram: Diagram) -> None:
        endpoint_count = len(diagram.code) * 4
        self.edge_to_face = [-1 for _ in range(endpoint_count)]
        present = [True for _ in range(endpoint_count)]
        remaining = endpoint_count

        while remaining > 0:
            first_key = next(key for key in range(endpoint_count - 1, -1, -1) if present[key])
            face_index = len(self.faces)
            face: List[int] = []
            first = endpoint_from_key(first_key)
            current = first
            present[first_key] = False
            remaining -= 1
            self.edge_to_face[first_key] = face_index
            self.face_assignment_order.append(first_key)
            face.append(first_key)

            while True:
                nxt = diagram.next_corner(current)
                if nxt == first:
                    self.faces.append(face)
                    break
                next_key = nxt.key
                self.edge_to_face[next_key] = face_index
                self.face_assignment_order.append(next_key)
                if present[next_key]:
                    present[next_key] = False
                    remaining -= 1
                face.append(next_key)
                current = nxt

    def _build_edges(self, diagram: Diagram) -> None:
        self.adjacency = [[] for _ in self.faces]
        for key in self.face_assignment_order:
            endpoint = endpoint_from_key(key)
            opposite = diagram.opposite(endpoint)
            opposite_key = opposite.key
            face = self.edge_to_face[key]
            neighbor = self.edge_to_face[opposite_key]
            if face >= neighbor:
                continue
            pair_key = face_pair_key(face, neighbor)
            found = self.edge_by_faces.get(pair_key)
            if found is None:
                edge = GraphEdge(face, neighbor, key, opposite_key)
                edge_index = len(self.edges)
                self.edge_by_faces[pair_key] = edge_index
                self.edges.append(edge)
                self.adjacency[face].append(edge_index)
                self.adjacency[neighbor].append(edge_index)
            else:
                edge = self.edges[found]
                if edge.u == face:
                    edge.interface_u = key
                    edge.interface_v = opposite_key
                else:
                    edge.interface_u = opposite_key
                    edge.interface_v = key


def possible_red_lines(diagram: Diagram) -> List[List[Endpoint]]:
    long_lines: List[List[Endpoint]] = []
    entries = diagram.crossing_entries()
    while entries:
        red_line: List[Endpoint] = []
        endpoint = entries.pop()
        red_line.append(endpoint)
        crossings = {endpoint.crossing}
        while True:
            endpoint = diagram.next(endpoint)
            red_line.append(endpoint)
            if endpoint.crossing in crossings:
                break
            crossings.add(endpoint.crossing)
        long_lines.append(red_line)

    candidates: List[List[Endpoint]] = []
    for line in long_lines:
        if len(line) < 3:
            continue
        for i in range(len(line) - 2):
            candidates.append(line[: len(line) - i])
    return candidates


def component_summaries(diagram: Diagram) -> List[ComponentSummary]:
    remaining = {endpoint.key for endpoint in diagram.crossing_entries()}
    summaries: List[ComponentSummary] = []
    while remaining:
        start = endpoint_from_key(max(remaining))
        current = start
        crossings: Set[int] = set()
        while True:
            remaining.discard(current.key)
            crossings.add(current.crossing)
            current = diagram.next(current)
            if current == start:
                break
        summaries.append(ComponentSummary(sorted(crossings)))
    return summaries


def analyze_components(code: PDCode, known_crossingless_components: int = 0) -> ComponentAnalysis:
    analysis = ComponentAnalysis(crossingless_components=known_crossingless_components)
    if not code:
        return analysis
    analysis.components = component_summaries(Diagram(code))
    return analysis


def analyze_components_after_removing_crossings(
    code: PDCode,
    removed_crossings: Sequence[int],
    known_crossingless_components: int = 0,
) -> ComponentAnalysis:
    removed = set(removed_crossings)
    for crossing in removed:
        if crossing < 0 or crossing >= len(code):
            raise ValueError(f"Removed crossing index {crossing} is out of range")
    original = analyze_components(code, known_crossingless_components)
    reduced = ComponentAnalysis(crossingless_components=original.crossingless_components)
    for component in original.components:
        remaining = [crossing for crossing in component.crossing_indices if crossing not in removed]
        if remaining:
            reduced.components.append(ComponentSummary(remaining))
        else:
            reduced.crossingless_components += 1
    return reduced


def unique_label_count(crossing: Sequence[int]) -> int:
    return len(set(crossing))


def value_set(code: PDCode) -> List[int]:
    return sorted({label for crossing in code for label in crossing})


def replace_label(code: PDCode, old_label: int, new_label: int) -> PDCode:
    if old_label == new_label:
        return [tuple(crossing) for crossing in code]
    return [
        tuple(new_label if label == old_label else label for label in crossing)  # type: ignore[misc]
        for crossing in code
    ]


def add_vector_edge(graph: Dict[int, List[int]], a: int, b: int) -> None:
    graph.setdefault(a, [])
    graph.setdefault(b, [])
    if b not in graph[a]:
        graph[a].append(b)
    if a not in graph[b]:
        graph[b].append(a)


def pd_adjacency_vector(code: PDCode) -> Dict[int, List[int]]:
    graph: Dict[int, List[int]] = {}
    for crossing in code:
        add_vector_edge(graph, crossing[0], crossing[2])
        add_vector_edge(graph, crossing[1], crossing[3])
    return graph


def renumber_r1_order(code: PDCode) -> PDCode:
    if not code:
        return []
    graph = pd_adjacency_vector(code)
    visit_order: List[int] = []
    for value in value_set(code):
        if value in visit_order:
            continue
        if value not in graph:
            raise ValueError("Invalid PD graph during R1 renumbering")
        visit_order.append(value)
        while True:
            current = visit_order[-1]
            advanced = False
            for nxt in sorted(graph[current]):
                if nxt not in visit_order:
                    visit_order.append(nxt)
                    advanced = True
                    break
            if not advanced:
                break
    new_label = {value: index for index, value in enumerate(visit_order)}
    return [tuple(new_label[label] for label in crossing) for crossing in code]  # type: ignore[misc]


def erase_r1_moves(
    code: PDCode,
    crossingless_components: int,
) -> Tuple[PDCode, int, int]:
    if code:
        Diagram(code)
    result = [tuple(crossing) for crossing in code]
    moves = 0
    while True:
        changed = False
        for index, crossing in enumerate(result):
            if unique_label_count(crossing) > 3:
                continue
            after_removal = analyze_components_after_removing_crossings(
                result,
                [index],
                crossingless_components,
            )
            result.pop(index)
            singles = [
                label for label in crossing if list(crossing).count(label) == 1
            ]
            if len(singles) == 2:
                result = replace_label(result, singles[0], singles[1])
            crossingless_components = after_removal.crossingless_components
            moves += 1
            changed = True
            break
        if not changed:
            break
    return renumber_r1_order(result), crossingless_components, moves


def add_set_edge(graph: Dict[int, Set[int]], a: int, b: int) -> None:
    graph.setdefault(a, set()).add(b)
    graph.setdefault(b, set()).add(a)


def graph_component_count(code: PDCode) -> int:
    graph: Dict[int, Set[int]] = {}
    for crossing_index, crossing in enumerate(code):
        crossing_node = -crossing_index - 1
        for label in crossing:
            add_set_edge(graph, label, crossing_node)
    visited: Set[int] = set()
    count = 0
    for start in graph:
        if start in visited:
            continue
        count += 1
        stack = [start]
        visited.add(start)
        while stack:
            node = stack.pop()
            for nxt in graph.get(node, set()):
                if nxt not in visited:
                    visited.add(nxt)
                    stack.append(nxt)
    return count


def is_nugatory_crossing(code: PDCode, index: int) -> bool:
    if unique_label_count(code[index]) != 4:
        raise ValueError("Nugatory check requires an R1-free PD code")
    without = list(code)
    without.pop(index)
    return graph_component_count(without) > graph_component_count(code)


def find_nugatory_crossing(code: PDCode) -> int:
    for index in range(len(code)):
        if is_nugatory_crossing(code, index):
            return index
    return -1


def add_pre_next_edge(previous: Dict[int, int], nxt: Dict[int, int], a: int, b: int) -> None:
    if abs(a - b) == 1:
        previous_value, next_value = (a, b) if a < b else (b, a)
    else:
        previous_value, next_value = (b, a) if a < b else (a, b)
    previous[next_value] = previous_value
    nxt[previous_value] = next_value


def pre_next_maps(code: PDCode) -> Tuple[Dict[int, int], Dict[int, int]]:
    if code:
        Diagram(code)
    previous: Dict[int, int] = {}
    nxt: Dict[int, int] = {}
    for crossing in code:
        if unique_label_count(crossing) > 2:
            add_pre_next_edge(previous, nxt, crossing[0], crossing[2])
            add_pre_next_edge(previous, nxt, crossing[1], crossing[3])
        else:
            values = sorted(set(crossing))
            if len(values) != 2:
                raise ValueError("Invalid two-value crossing in pre/next maps")
            previous[values[0]] = values[1]
            nxt[values[0]] = values[1]
            previous[values[1]] = values[0]
            nxt[values[1]] = values[0]

    for label in value_set(code):
        if label not in previous:
            if label not in nxt:
                raise ValueError("Broken PD pre/next map")
            previous[label] = nxt[label]
        if label not in nxt:
            nxt[label] = previous[label]
    return previous, nxt


def renumber_full_dfs(code: PDCode) -> PDCode:
    if not code:
        return []
    graph: Dict[int, Set[int]] = {}
    for crossing in code:
        add_set_edge(graph, crossing[0], crossing[2])
        add_set_edge(graph, crossing[1], crossing[3])

    visited: Set[int] = set()
    new_label: Dict[int, int] = {}
    for start in value_set(code):
        if start in visited:
            continue
        stack = [start]
        while stack:
            value = stack.pop()
            if value in visited:
                continue
            if value not in graph:
                raise ValueError("Invalid PD graph during renumbering")
            new_label[value] = len(visited)
            visited.add(value)
            for nxt in sorted(graph[value], reverse=True):
                if nxt not in visited:
                    stack.append(nxt)
    if len(new_label) != len(value_set(code)):
        raise ValueError("PD renumbering failed")
    return [tuple(new_label[label] for label in crossing) for crossing in code]  # type: ignore[misc]


def erase_one_nugatory_crossing(
    code: PDCode,
    index: int,
    crossingless_components: int,
) -> Tuple[PDCode, int]:
    if unique_label_count(code[index]) != 4:
        raise ValueError("Nugatory erase requires an R1-free PD code")

    crossing = code[index]
    ax, bx, cx, dx = crossing
    _, nxt = pre_next_maps(code)
    loop = [ax]
    guard = len(value_set(code)) + 1
    while True:
        if loop[-1] not in nxt:
            raise ValueError("Broken loop while erasing nugatory crossing")
        next_label = nxt[loop[-1]]
        loop.append(next_label)
        if next_label == ax:
            loop.pop()
            break
        if len(loop) > guard:
            raise ValueError("Failed to close PD loop while erasing nugatory crossing")

    loop_set = set(loop)
    if not {ax, bx, cx, dx}.issubset(loop_set):
        raise ValueError("Nugatory crossing arcs are not in one component")

    after_removal = analyze_components_after_removing_crossings(
        code,
        [index],
        crossingless_components,
    )
    result = list(code)
    result.pop(index)
    result = replace_label(result, ax, cx)
    result = replace_label(result, dx, bx)
    return renumber_full_dfs(result), after_removal.crossingless_components


def simplify_pd_code(
    code: PDCode,
    known_crossingless_components: int = 0,
) -> PDSimplificationResult:
    result = PDSimplificationResult(
        code=[tuple(crossing) for crossing in code],
        crossingless_components=known_crossingless_components,
    )
    result.code, result.crossingless_components, result.reidemeister_i_moves = erase_r1_moves(
        result.code,
        result.crossingless_components,
    )
    while True:
        index = find_nugatory_crossing(result.code)
        if index < 0:
            break
        result.code, result.crossingless_components = erase_one_nugatory_crossing(
            result.code,
            index,
            result.crossingless_components,
        )
        result.nugatory_crossing_moves += 1
    return result


def reset_weights(graph: DualGraph) -> None:
    for edge in graph.edges:
        edge.weight = 1


def collect_simple_paths(
    graph: DualGraph,
    source: int,
    target: int,
    cutoff: int,
    max_paths: int,
) -> List[List[int]]:
    if (
        source == target
        or source < 0
        or target < 0
        or source >= len(graph.faces)
        or target >= len(graph.faces)
        or cutoff <= 0
    ):
        return []

    paths: List[List[int]] = []
    visited = [False for _ in graph.faces]
    current_path = [source]
    visited[source] = True

    def dfs(current: int) -> None:
        if len(current_path) - 1 >= cutoff:
            return
        for edge_index in graph.adjacency[current]:
            edge = graph.edges[edge_index]
            nxt = edge.v if edge.u == current else edge.u
            if visited[nxt]:
                continue
            current_path.append(nxt)
            visited[nxt] = True
            if nxt == target:
                path_weight = 0
                for i in range(len(current_path) - 1):
                    path_edge = graph.edge(current_path[i], current_path[i + 1])
                    if path_edge is None:
                        raise RuntimeError("Missing dual edge while weighing a path")
                    path_weight += path_edge.weight
                    if path_weight >= cutoff:
                        break
                if path_weight < cutoff:
                    paths.append(list(current_path))
                if max_paths != -1 and len(paths) > max_paths:
                    visited[nxt] = False
                    current_path.pop()
                    return
            else:
                dfs(nxt)
                if max_paths != -1 and len(paths) > max_paths:
                    visited[nxt] = False
                    current_path.pop()
                    return
            visited[nxt] = False
            current_path.pop()

    dfs(source)
    return paths


def opposite_level(level: str) -> str:
    return "over" if level == "under" else "under"


def do_check(
    diagram: Diagram,
    graph: DualGraph,
    red_path: List[Endpoint],
    green_path: List[int],
    direction: str,
    result: SimplificationResult,
) -> bool:
    green_left_cross: List[int] = []
    for i in range(len(green_path) - 1):
        f1 = green_path[i]
        f2 = green_path[i + 1]
        edge = graph.edge(f1, f2)
        if edge is None:
            return False
        face_for_interface = f1 if direction == "right" else f2
        green_left_cross.append(edge.interface_for_face(face_for_interface))

    red_boundary_crossings: Set[int] = set()
    to_check: Deque[int] = deque()
    queued: Set[int] = set()
    check_result: Dict[int, str] = {}

    def enqueue(key: int) -> None:
        if key not in queued:
            queued.add(key)
            to_check.append(key)

    def erase_queued(key: int) -> None:
        if key in queued:
            queued.remove(key)
            try:
                to_check.remove(key)
            except ValueError:
                pass

    for red_endpoint in red_path[:-1]:
        red_boundary_crossings.add(red_endpoint.crossing)
        offset = 3 if direction == "right" else 1
        cross_strand = Diagram.rotate_endpoint(red_endpoint, offset)
        key = cross_strand.key
        enqueue(key)
        check_result[key] = "under" if cross_strand.strand % 2 == 0 else "over"

    green_index = {face: index for index, face in enumerate(green_path)}
    green_crossings: List[GreenCrossing] = []
    good_path = True

    while to_check and good_path:
        start_key = to_check.pop()
        queued.discard(start_key)
        cross_strand = endpoint_from_key(start_key)

        while True:
            cross_key = cross_strand.key
            current_level = check_result[cross_key]
            opposite = diagram.opposite(cross_strand)
            opposite_key = opposite.key
            opposite_result = check_result.get(opposite_key)
            if opposite_result is not None and opposite_result != current_level:
                good_path = False
                break

            if cross_key in green_left_cross:
                f1 = graph.edge_to_face[cross_key]
                f2 = graph.edge_to_face[opposite_key]
                if f1 not in green_index or f2 not in green_index:
                    good_path = False
                    break
                forward = green_index[f1] < green_index[f2]
                green_crossings.append(
                    GreenCrossing(
                        from_face=f1 if forward else f2,
                        to_face=f2 if forward else f1,
                        strand_level=opposite_level(current_level),
                    )
                )
                break

            check_result[opposite_key] = current_level
            erase_queued(opposite_key)
            if opposite.crossing in red_boundary_crossings:
                break

            cross_strand = opposite
            side1 = Diagram.rotate_endpoint(cross_strand, 1)
            side2 = Diagram.rotate_endpoint(cross_strand, 3)
            side1_key = side1.key
            side2_key = side2.key

            if cross_strand.strand % 2 == 1 and current_level == "under":
                if check_result.get(side1_key) == "over" or check_result.get(side2_key) == "over":
                    good_path = False
                    break
                if side1_key not in check_result:
                    check_result[side1_key] = "under"
                    enqueue(side1_key)
                if side2_key not in check_result:
                    check_result[side2_key] = "under"
                    enqueue(side2_key)

            if cross_strand.strand % 2 == 0 and current_level == "over":
                if check_result.get(side1_key) == "under" or check_result.get(side2_key) == "under":
                    good_path = False
                    break
                if side1_key not in check_result:
                    check_result[side1_key] = "over"
                    enqueue(side1_key)
                if side2_key not in check_result:
                    check_result[side2_key] = "over"
                    enqueue(side2_key)

            across = Diagram.rotate_endpoint(cross_strand, 2)
            check_result[across.key] = current_level
            cross_strand = across

    if not good_path:
        return False
    result.found = True
    result.direction = direction
    result.red_path = list(red_path)
    result.green_path = list(green_path)
    result.green_crossings = green_crossings
    return True


def find_simplification(code: PDCode, max_paths: int = 100) -> SimplificationResult:
    result = SimplificationResult()
    diagram = Diagram(code)
    graph = DualGraph(diagram)
    red_lines = possible_red_lines(diagram)

    for red_path in red_lines:
        result.tested_red_paths += 1
        reset_weights(graph)
        start = red_path[0]
        end = red_path[-1]
        sources = [
            graph.edge_to_face[start.key],
            graph.edge_to_face[diagram.opposite(start).key],
        ]
        destinations = [
            graph.edge_to_face[end.key],
            graph.edge_to_face[diagram.opposite(end).key],
        ]

        for endpoint in red_path[1:-1]:
            right_region = graph.edge_to_face[endpoint.key]
            left_region = graph.edge_to_face[diagram.opposite(endpoint).key]
            edge = graph.edge(right_region, left_region)
            if edge is not None:
                edge.weight = BLOCKED_WEIGHT

        paths: List[List[int]] = []
        cutoff = len(red_path) - 1
        for source in sources:
            for destination in destinations:
                found = collect_simple_paths(graph, source, destination, cutoff, max_paths)
                paths.extend(found)
                if max_paths != -1 and len(paths) > max_paths:
                    break

        for green_path in paths:
            result.tested_green_paths += 1
            if len(green_path) >= len(red_path):
                continue
            if do_check(diagram, graph, red_path, green_path, "left", result):
                return result
            if do_check(diagram, graph, red_path, green_path, "right", result):
                return result

    return result


def label_for_block(text: str, block_start: int, label_prefix: str, index: int) -> str:
    line_start = text.rfind("\n", 0, block_start)
    line_start = 0 if line_start == -1 else line_start + 1
    before_block = text[line_start:block_start]
    colon = before_block.find(":")
    if colon != -1:
        line_label = trim(before_block[:colon])
        if line_label:
            return f"{label_prefix}:{line_label}"
    return label_prefix if index == 0 else f"{label_prefix}#{index + 1}"


def parse_pd_document(text: str, label_prefix: str = "input") -> List[PDJob]:
    jobs: List[PDJob] = []
    pos = 0
    index = 0
    while True:
        start = text.find("PD[", pos)
        if start == -1:
            break
        depth = 0
        end = -1
        for i in range(start + 2, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end == -1:
            jobs.append(
                PDJob(
                    label=f"{label_prefix}#{index + 1}",
                    error="Unterminated PD[...] block",
                )
            )
            break
        block = text[start : end + 1]
        job = PDJob(label=label_for_block(text, start, label_prefix, index))
        try:
            job.code = parse_pd_code(block)
            job.implied_crossingless_components = 1 if denotes_crossingless_unknot(block) else 0
        except Exception as exc:
            job.error = str(exc)
        jobs.append(job)
        index += 1
        pos = end + 1

    if jobs:
        return jobs

    for line in text.splitlines():
        cleaned = trim(line)
        if not cleaned or cleaned.startswith("#"):
            continue
        payload = cleaned
        label = label_prefix
        if ":" in cleaned:
            line_label, payload = cleaned.split(":", 1)
            line_label = trim(line_label)
            payload = trim(payload)
            if line_label:
                label = f"{label}:{line_label}"
        elif jobs:
            label = f"{label}#{len(jobs) + 1}"
        if not any(ch.isdigit() for ch in payload) and not denotes_crossingless_unknot(payload):
            continue
        job = PDJob(label=label)
        try:
            job.code = parse_pd_code(payload)
            job.implied_crossingless_components = 1 if denotes_crossingless_unknot(payload) else 0
        except Exception as exc:
            job.error = str(exc)
        jobs.append(job)
    return jobs


def read_pd_file(path: str) -> List[PDJob]:
    text = Path(path).read_text(encoding="utf-8")
    jobs = parse_pd_document(text, path)
    if len(jobs) == 1:
        jobs[0].label = path
    return jobs


def list_input_files(directory: str) -> List[str]:
    paths = []
    for entry in Path(directory).iterdir():
        if entry.is_file() and entry.suffix.lower() in {".pd", ".txt"}:
            paths.append(str(entry))
    return sorted(paths)


def run_job(
    job: PDJob,
    max_paths: int = 100,
    known_crossingless_components: int = 0,
    removed_crossings: Optional[Sequence[int]] = None,
    simplify_pd: bool = True,
) -> Tuple[
    SimplificationResult,
    ComponentAnalysis,
    Optional[ComponentAnalysis],
    Optional[PDSimplificationResult],
    Optional[ComponentAnalysis],
]:
    if job.error:
        raise ValueError(job.error)
    crossingless = known_crossingless_components + job.implied_crossingless_components
    input_components = analyze_components(job.code, crossingless)
    after_removal = None
    if removed_crossings is not None:
        after_removal = analyze_components_after_removing_crossings(
            job.code, removed_crossings, crossingless
        )
    pd_simplification = None
    search_components = None
    search_code = job.code
    if simplify_pd:
        pd_simplification = simplify_pd_code(job.code, crossingless)
        search_code = pd_simplification.code
        search_components = analyze_components(
            search_code,
            pd_simplification.crossingless_components,
        )
    return (
        find_simplification(search_code, max_paths),
        input_components,
        after_removal,
        pd_simplification,
        search_components,
    )


def print_text_result(
    result: SimplificationResult,
    input_components: ComponentAnalysis,
    after_removal_components: Optional[ComponentAnalysis] = None,
    pd_simplification: Optional[PDSimplificationResult] = None,
    search_components: Optional[ComponentAnalysis] = None,
) -> None:
    print(f"simplification_found: {'yes' if result.found else 'no'}")
    print(f"input_components_with_crossings: {input_components.components_with_crossings}")
    print(f"input_crossingless_components: {input_components.crossingless_components}")
    print(f"input_total_components: {input_components.total_components}")
    if after_removal_components is not None:
        print(
            "after_removal_components_with_crossings: "
            f"{after_removal_components.components_with_crossings}"
        )
        print(
            "after_removal_crossingless_components: "
            f"{after_removal_components.crossingless_components}"
        )
        print(f"after_removal_total_components: {after_removal_components.total_components}")
    if pd_simplification is not None and search_components is not None:
        print("pd_simplification_enabled: yes")
        print(
            "pd_simplification_reidemeister_i_moves: "
            f"{pd_simplification.reidemeister_i_moves}"
        )
        print(
            "pd_simplification_nugatory_crossing_moves: "
            f"{pd_simplification.nugatory_crossing_moves}"
        )
        print(f"pd_simplification_output_crossings: {len(pd_simplification.code)}")
        print(
            "search_components_with_crossings: "
            f"{search_components.components_with_crossings}"
        )
        print(f"search_crossingless_components: {search_components.crossingless_components}")
        print(f"search_total_components: {search_components.total_components}")
    print(f"tested_red_paths: {result.tested_red_paths}")
    print(f"tested_green_paths: {result.tested_green_paths}")
    if not result.found:
        return
    red = ", ".join(f"({e.crossing}, {e.strand})" for e in result.red_path)
    green_crossings = ", ".join(
        f"({c.from_face}, {c.to_face}, {c.strand_level})"
        for c in result.green_crossings
    )
    print(f"direction: {result.direction}")
    print(f"red_path: [{red}]")
    print(f"green_path: {result.green_path}")
    print(f"green_crossings: [{green_crossings}]")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find a mid-simplification witness in PD code."
    )
    parser.add_argument("inputs", nargs="*", help="PD strings, files, or directories")
    parser.add_argument("--pd-code", "-c", action="append", help="literal PD[...] string")
    parser.add_argument("--pd-file", "-f", action="append", help="read one PD input file")
    parser.add_argument("--pd-dir", "-d", action="append", help="read every .txt/.pd file in a directory")
    parser.add_argument("--input", "-i", action="append", help="alias for --pd-file")
    parser.add_argument("--json", action="store_true", help="print JSON output")
    parser.add_argument("--simplify-pd", dest="simplify_pd", action="store_true", default=True,
                        help="enable R1 then nugatory PD pre-simplification")
    parser.add_argument("--no-simplify-pd", "--raw-pd", dest="simplify_pd", action="store_false",
                        help="disable PD pre-simplification")
    parser.add_argument("--max-paths", type=int, default=100, help="green path cap, or -1 for unlimited")
    parser.add_argument(
        "--known-crossingless-components",
        type=int,
        default=0,
        help="components already missing from the PD code",
    )
    parser.add_argument(
        "--remove-crossings",
        help="comma-separated zero-based crossing indices for deletion accounting",
    )
    return parser


def collect_jobs(args: argparse.Namespace) -> List[PDJob]:
    jobs: List[PDJob] = []
    files: List[str] = []

    for literal in args.pd_code or []:
        jobs.extend(parse_pd_document(literal, "command-line"))
    for path in args.pd_file or []:
        files.append(path)
    for path in args.input or []:
        files.append(path)
    for directory in args.pd_dir or []:
        files.extend(list_input_files(directory))

    for item in args.inputs:
        path = Path(item)
        if path.is_dir():
            files.extend(list_input_files(str(path)))
        elif path.is_file():
            files.append(str(path))
        else:
            jobs.extend(parse_pd_document(item, "command-line"))

    if not files and not jobs:
        files.append("PD.txt")

    for path in files:
        jobs.extend(read_pd_file(path))
    if not jobs:
        raise ValueError("No PD code found")
    return jobs


def parse_removed_crossings(text: Optional[str]) -> Optional[List[int]]:
    if text is None:
        return None
    return [int(token) for token in re.findall(r"-?\d+", text)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    jobs = collect_jobs(args)
    removed_crossings = parse_removed_crossings(args.remove_crossings)
    show_labels = len(jobs) > 1
    all_found = True
    had_error = False

    if args.json:
        payload = []
        for job in jobs:
            try:
                (
                    result,
                    input_components,
                    after_removal,
                    pd_simplification,
                    search_components,
                ) = run_job(
                    job,
                    max_paths=args.max_paths,
                    known_crossingless_components=args.known_crossingless_components,
                    removed_crossings=removed_crossings,
                    simplify_pd=args.simplify_pd,
                )
                all_found = all_found and result.found
                payload.append(
                    result.to_json(
                        input_components=input_components,
                        after_removal_components=after_removal,
                        pd_simplification=pd_simplification,
                        search_components=search_components,
                        label=job.label if show_labels else None,
                    )
                )
            except Exception as exc:
                all_found = False
                had_error = True
                item: Dict[str, object] = {"error": str(exc)}
                if show_labels:
                    item["label"] = job.label
                payload.append(item)
        print(json.dumps(payload if show_labels else payload[0], indent=2))
    else:
        for index, job in enumerate(jobs):
            if show_labels:
                print(f"{job.label}:")
            try:
                (
                    result,
                    input_components,
                    after_removal,
                    pd_simplification,
                    search_components,
                ) = run_job(
                    job,
                    max_paths=args.max_paths,
                    known_crossingless_components=args.known_crossingless_components,
                    removed_crossings=removed_crossings,
                    simplify_pd=args.simplify_pd,
                )
                all_found = all_found and result.found
                print_text_result(
                    result,
                    input_components,
                    after_removal,
                    pd_simplification,
                    search_components,
                )
            except Exception as exc:
                all_found = False
                had_error = True
                print(f"error: {exc}")
            if show_labels and index + 1 < len(jobs):
                print()
    if had_error:
        return 2
    return 0 if all_found else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)

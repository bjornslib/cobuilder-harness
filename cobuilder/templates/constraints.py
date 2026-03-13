"""Static constraint validators for template-generated DOT pipelines.

These checks run at instantiation time (before the pipeline is executed)
to catch structural violations early.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cobuilder.templates.manifest import (
        Manifest,
        PathConstraint,
        TopologyConstraint,
    )

logger = logging.getLogger(__name__)


def validate_static_constraints(
    dot_content: str, manifest: "Manifest"
) -> list[str]:
    """Run all static constraint checks on a rendered DOT string.

    Args:
        dot_content: The rendered DOT pipeline content.
        manifest: Parsed template manifest with constraints.

    Returns:
        List of error strings. Empty means all constraints passed.
    """
    errors: list[str] = []

    # Parse DOT into lightweight structure for analysis
    nodes, edges = _parse_dot_lightweight(dot_content)

    for pc in manifest.path_constraints:
        errors.extend(_check_path_constraint(pc, nodes, edges))

    for tc in manifest.topology_constraints:
        errors.extend(_check_topology_constraint(tc, nodes, edges))

    return errors


# ---------------------------------------------------------------------------
# Lightweight DOT parser (just enough for constraint checking)
# ---------------------------------------------------------------------------


def _parse_dot_lightweight(
    dot_content: str,
) -> tuple[dict[str, dict[str, str]], list[tuple[str, str]]]:
    """Extract nodes (with shape/handler attrs) and edges from DOT content.

    Returns:
        (nodes_dict, edges_list) where:
        - nodes_dict maps node_id -> {shape, handler, ...}
        - edges_list is [(source_id, target_id), ...]
    """
    nodes: dict[str, dict[str, str]] = {}
    edges: list[tuple[str, str]] = []

    # Remove comments
    content = re.sub(r"//[^\n]*", "", dot_content)
    content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)

    # Extract node definitions: node_id [attrs]
    node_pattern = re.compile(
        r'(\w+)\s*\[([^\]]*)\]', re.MULTILINE
    )
    for match in node_pattern.finditer(content):
        node_id = match.group(1)
        attrs_str = match.group(2)
        if node_id in ("node", "edge", "graph", "digraph", "subgraph"):
            continue  # Skip global defaults
        attrs = _parse_attrs(attrs_str)
        if attrs:  # Only add if it has attributes (not just edge labels)
            nodes[node_id] = attrs

    # Extract edges: source -> target
    edge_pattern = re.compile(r'(\w+)\s*->\s*(\w+)')
    for match in edge_pattern.finditer(content):
        src, dst = match.group(1), match.group(2)
        edges.append((src, dst))

    return nodes, edges


def _parse_attrs(attrs_str: str) -> dict[str, str]:
    """Parse DOT attribute string into a dict."""
    attrs: dict[str, str] = {}
    # Match key=value or key="value" patterns
    pattern = re.compile(r'(\w+)\s*=\s*(?:"([^"]*?)"|(\S+))')
    for match in pattern.finditer(attrs_str):
        key = match.group(1)
        value = match.group(2) if match.group(2) is not None else match.group(3)
        attrs[key] = value
    return attrs


# ---------------------------------------------------------------------------
# Path constraint checker
# ---------------------------------------------------------------------------


def _check_path_constraint(
    constraint: "PathConstraint",
    nodes: dict[str, dict[str, str]],
    edges: list[tuple[str, str]],
) -> list[str]:
    """Check that all paths from source-shape nodes to target-shape nodes
    pass through required intermediate shapes.

    Uses DFS to enumerate all paths from each source node to each target node.
    """
    errors: list[str] = []

    # Build adjacency
    adj: dict[str, list[str]] = defaultdict(list)
    for src, dst in edges:
        adj[src].append(dst)

    # Find source and target nodes
    source_nodes = [
        nid for nid, attrs in nodes.items()
        if attrs.get("shape", "") == constraint.from_shape
    ]
    target_nodes = set(
        nid for nid, attrs in nodes.items()
        if attrs.get("shape", "") in constraint.before_reaching
    )
    required_shapes = set(constraint.must_pass_through)

    for source_id in source_nodes:
        # DFS to find all paths from source to any target
        violations = _dfs_check_paths(
            source_id, target_nodes, required_shapes, nodes, adj
        )
        errors.extend(violations)

    return errors


def _dfs_check_paths(
    start: str,
    targets: set[str],
    required_shapes: set[str],
    nodes: dict[str, dict[str, str]],
    adj: dict[str, list[str]],
) -> list[str]:
    """DFS from start to any target, checking that required shapes appear on every path."""
    errors: list[str] = []

    # Stack: (current_node, visited_set, shapes_seen)
    stack: list[tuple[str, set[str], set[str]]] = [
        (start, {start}, {nodes.get(start, {}).get("shape", "")})
    ]

    while stack:
        current, visited, shapes_seen = stack.pop()

        for neighbor in adj.get(current, []):
            if neighbor in visited:
                continue  # Avoid cycles

            neighbor_shape = nodes.get(neighbor, {}).get("shape", "")
            new_shapes = shapes_seen | {neighbor_shape}

            if neighbor in targets:
                # Check if all required shapes were seen on this path
                missing = required_shapes - new_shapes
                if missing:
                    errors.append(
                        f"Path from '{start}' to '{neighbor}' does not pass through "
                        f"required shape(s): {sorted(missing)}"
                    )
            else:
                stack.append((neighbor, visited | {neighbor}, new_shapes))

    return errors


# ---------------------------------------------------------------------------
# Topology constraint checker
# ---------------------------------------------------------------------------


def _check_topology_constraint(
    constraint: "TopologyConstraint",
    nodes: dict[str, dict[str, str]],
    edges: list[tuple[str, str]],
) -> list[str]:
    """Check that every node matching the constraint has a downstream node
    of the required shape within max_hops.
    """
    errors: list[str] = []

    # Build adjacency
    adj: dict[str, list[str]] = defaultdict(list)
    for src, dst in edges:
        adj[src].append(dst)

    # Find nodes that must have a downstream match
    source_nodes = [
        nid for nid, attrs in nodes.items()
        if attrs.get("shape", "") == constraint.every_node_shape
        and (
            constraint.every_node_handler is None
            or attrs.get("handler", "") == constraint.every_node_handler
        )
    ]

    target_shape = constraint.must_have_downstream_shape
    max_hops = constraint.max_hops

    for source_id in source_nodes:
        if not _bfs_find_shape(source_id, target_shape, adj, nodes, max_hops):
            errors.append(
                f"Node '{source_id}' (shape={constraint.every_node_shape}) "
                f"has no downstream '{target_shape}' node within {max_hops} hops"
            )

    return errors


def _bfs_find_shape(
    start: str,
    target_shape: str,
    adj: dict[str, list[str]],
    nodes: dict[str, dict[str, str]],
    max_hops: int,
) -> bool:
    """BFS from start to find any node with target_shape within max_hops."""
    visited: set[str] = {start}
    frontier: list[str] = [start]
    depth = 0

    while frontier and depth < max_hops:
        next_frontier: list[str] = []
        for node_id in frontier:
            for neighbor in adj.get(node_id, []):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                if nodes.get(neighbor, {}).get("shape", "") == target_shape:
                    return True
                next_frontier.append(neighbor)
        frontier = next_frontier
        depth += 1

    return False

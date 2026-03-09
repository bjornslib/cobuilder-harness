#!/usr/bin/env python3
"""Attractor DOT Pipeline Validator.

Validates pipeline DOT files against the schema rules defined in schema.md.
Reports errors (fatal) and warnings (advisory).

Usage:
    python3 validator.py <file.dot> [--output json] [--strict]
    python3 validator.py --help

Validation Rules (from schema.md section 11):
    1.  Exactly one Mdiamond (start) node
    2.  Exactly one Msquare (exit) node
    3.  All nodes reachable from start
    4.  No orphan nodes
    5.  Every codergen node has at least one hexagon (AT) peer downstream
    6.  Diamond nodes have exactly 2 outbound edges (pass/fail)
    7.  Status values are valid enum members
    8.  Required attributes per handler type present
    9.  No unguarded cycles (only via diamond fail-edges)
    10. promise_id exists on graph if any node has promise_ac
    11. Edge conditions use valid syntax (pass, fail, partial)
    12. Full cluster topology check: every codergen node must have downstream wait.system3 and wait.human nodes
    13. wait.human nodes must follow wait.system3 or research nodes
"""

import argparse
import json
import sys
from typing import Any

from .parser import parse_file


# --- Constants ---

VALID_STATUSES = {"pending", "active", "impl_complete", "validated", "failed"}

VALID_HANDLERS = {
    "start",
    "exit",
    "codergen",
    "tool",
    "wait.human",
    "wait.system3",
    "conditional",
    "parallel",
    "research",
    "acceptance-test-writer",
}

HANDLER_SHAPE_MAP = {
    "start": "Mdiamond",
    "exit": "Msquare",
    "codergen": "box",
    "tool": "box",
    "wait.human": "hexagon",
    "wait.system3": "hexagon",
    "conditional": "diamond",
    "parallel": "parallelogram",
    "research": "tab",
    "acceptance-test-writer": "component",
}

VALID_CONDITIONS = {"pass", "fail", "partial"}

# Required attributes per handler type
REQUIRED_ATTRS: dict[str, list[str]] = {
    "start": ["label", "handler"],
    "exit": ["label", "handler"],
    "codergen": ["label", "handler", "bead_id", "worker_type", "sd_path"],
    "tool": ["label", "handler", "command"],
    "wait.human": ["label", "handler", "gate", "mode"],
    "wait.system3": ["label", "handler", "gate_type"],
    "conditional": ["label", "handler"],
    "parallel": ["label", "handler"],
    "research": ["label", "handler", "downstream_node", "solution_design"],
    "acceptance-test-writer": ["label", "handler", "prd_ref"],
}

# Recommended attributes per handler type — absence emits warnings (not errors).
# These are needed for Runner context and PRD traceability.
WARNING_ATTRS: dict[str, list[str]] = {
    "codergen": ["prd_ref", "acceptance"],
    "research": ["research_queries"],
}

VALID_WORKER_TYPES = {
    "frontend-dev-expert",
    "backend-solutions-engineer",
    "tdd-test-engineer",
    "solution-architect",
    "solution-design-architect",
    "validation-test-agent",
    "ux-designer",
}

VALID_GATE_TYPES = {"technical", "business", "e2e", "manual"}

VALID_MODES = {"technical", "business"}


class Issue:
    """A validation issue (error or warning)."""

    def __init__(self, level: str, rule: int, message: str, node: str = ""):
        self.level = level  # "error" or "warning"
        self.rule = rule    # Rule number from schema
        self.message = message
        self.node = node    # Node ID if applicable

    def to_dict(self) -> dict:
        d = {"level": self.level, "rule": self.rule, "message": self.message}
        if self.node:
            d["node"] = self.node
        return d

    def __str__(self) -> str:
        prefix = "ERROR" if self.level == "error" else "WARN "
        node_str = f" [{self.node}]" if self.node else ""
        return f"  {prefix} (rule {self.rule:2d}){node_str}: {self.message}"


def validate(data: dict[str, Any], strict: bool = False) -> list[Issue]:
    """Validate a parsed DOT pipeline against schema rules.

    Args:
        data: Output from parser.parse_file() or parser.parse_dot().
        strict: If True, treat warnings as errors.

    Returns:
        List of Issue objects.
    """
    issues: list[Issue] = []
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    graph_attrs = data.get("graph_attrs", {})

    # Build lookup structures
    node_map: dict[str, dict] = {}
    for n in nodes:
        node_map[n["id"]] = n["attrs"]

    # Build adjacency lists
    adj: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    reverse_adj: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    edge_by_src: dict[str, list[dict]] = {n["id"]: [] for n in nodes}

    for e in edges:
        src, dst = e["src"], e["dst"]
        if src in adj:
            adj[src].append(dst)
        if dst in reverse_adj:
            reverse_adj[dst].append(src)
        if src in edge_by_src:
            edge_by_src[src].append(e)

    # --- Rule 1: Exactly one Mdiamond (start) node ---
    start_nodes = [
        n["id"] for n in nodes if n["attrs"].get("shape") == "Mdiamond"
    ]
    if len(start_nodes) == 0:
        issues.append(Issue("error", 1, "No start node (shape=Mdiamond) found"))
    elif len(start_nodes) > 1:
        issues.append(
            Issue("error", 1, f"Multiple start nodes found: {start_nodes}")
        )

    # --- Rule 2: Exactly one Msquare (exit) node ---
    exit_nodes = [
        n["id"] for n in nodes if n["attrs"].get("shape") == "Msquare"
    ]
    if len(exit_nodes) == 0:
        issues.append(Issue("error", 2, "No exit node (shape=Msquare) found"))
    elif len(exit_nodes) > 1:
        issues.append(
            Issue("error", 2, f"Multiple exit nodes found: {exit_nodes}")
        )

    # --- Rule 3 & 4: All nodes reachable from start; no orphans ---
    if start_nodes:
        reachable = _bfs(start_nodes[0], adj)
        for n in nodes:
            if n["id"] not in reachable:
                issues.append(
                    Issue(
                        "error",
                        3,
                        f"Node not reachable from start",
                        n["id"],
                    )
                )

    # Check for orphans (nodes with no edges at all)
    all_edge_nodes = set()
    for e in edges:
        all_edge_nodes.add(e["src"])
        all_edge_nodes.add(e["dst"])
    for n in nodes:
        nid = n["id"]
        if nid not in all_edge_nodes and len(nodes) > 1:
            issues.append(Issue("error", 4, "Orphan node (no edges)", nid))

    # --- Rule 5: Every codergen node has at least one hexagon descendant ---
    codergen_nodes = [
        n["id"] for n in nodes if n["attrs"].get("handler") == "codergen"
    ]
    hexagon_nodes = set(
        n["id"] for n in nodes if n["attrs"].get("handler") == "wait.human"
    )
    for cg in codergen_nodes:
        # BFS from this codergen node to find any hexagon descendant
        descendants = _bfs(cg, adj)
        descendants.discard(cg)  # remove self
        has_hex = any(d in hexagon_nodes for d in descendants)
        if not has_hex:
            level = "error" if strict else "warning"
            issues.append(
                Issue(
                    level,
                    5,
                    "codergen node has no validation gate (hexagon) downstream",
                    cg,
                )
            )

    # --- Rule 6: Diamond nodes have exactly 2 outbound edges (pass/fail) ---
    diamond_nodes = [
        n["id"]
        for n in nodes
        if n["attrs"].get("shape") == "diamond"
        or n["attrs"].get("handler") == "conditional"
    ]
    for dn in diamond_nodes:
        out_edges = edge_by_src.get(dn, [])
        if len(out_edges) != 2:
            issues.append(
                Issue(
                    "error",
                    6,
                    f"Diamond node must have exactly 2 outbound edges, has {len(out_edges)}",
                    dn,
                )
            )
        else:
            conditions = {e["attrs"].get("condition", "") for e in out_edges}
            if "pass" not in conditions:
                issues.append(
                    Issue("error", 6, "Diamond missing 'pass' outbound edge", dn)
                )
            if "fail" not in conditions:
                issues.append(
                    Issue("error", 6, "Diamond missing 'fail' outbound edge", dn)
                )

    # --- Rule 7: Status values are valid enum members ---
    for n in nodes:
        status = n["attrs"].get("status", "pending")
        if status and status not in VALID_STATUSES:
            issues.append(
                Issue(
                    "error",
                    7,
                    f"Invalid status '{status}', must be one of {sorted(VALID_STATUSES)}",
                    n["id"],
                )
            )

    # --- Rule 8: Required attributes per handler type ---
    for n in nodes:
        handler = n["attrs"].get("handler", "")
        if handler not in VALID_HANDLERS:
            issues.append(
                Issue(
                    "error",
                    8,
                    f"Unknown handler '{handler}', must be one of {sorted(VALID_HANDLERS)}",
                    n["id"],
                )
            )
            continue
        required = REQUIRED_ATTRS.get(handler, [])
        for attr in required:
            if not n["attrs"].get(attr):
                issues.append(
                    Issue(
                        "error",
                        8,
                        f"Missing required attribute '{attr}' for handler={handler}",
                        n["id"],
                    )
                )

        # Check for recommended attributes — emit warnings (backward compatible)
        warnings_list = WARNING_ATTRS.get(handler, [])
        for attr in warnings_list:
            if attr not in n["attrs"]:
                issues.append(
                    Issue(
                        "warning",
                        8,
                        f"codergen node '{n['id']}' missing recommended attribute '{attr}' (needed for Runner context)",
                        n["id"],
                    )
                )

        # Extra validations per handler
        if handler == "codergen":
            wt = n["attrs"].get("worker_type", "")
            if wt and wt not in VALID_WORKER_TYPES:
                issues.append(
                    Issue(
                        "error",  # Changed from "warning" to "error" as per AC-5.3
                        8,
                        f"Unknown worker_type '{wt}', expected one of {sorted(VALID_WORKER_TYPES)}",
                        n["id"],
                    )
                )

            # Validate that sd_path is present for codergen nodes (AC-5.1)
            sd_path = n["attrs"].get("sd_path", "")
            if not sd_path:
                issues.append(
                    Issue(
                        "error",  # Hard error for missing sd_path
                        8,
                        "Missing required attribute 'sd_path' for handler=codergen",
                        n["id"],
                    )
                )
        elif handler == "wait.human":
            gate = n["attrs"].get("gate", "")
            if gate and gate not in VALID_GATE_TYPES:
                issues.append(
                    Issue(
                        "warning",
                        8,
                        f"Unknown gate type '{gate}', expected one of {sorted(VALID_GATE_TYPES)}",
                        n["id"],
                    )
                )
            mode = n["attrs"].get("mode", "")
            if mode and mode not in VALID_MODES:
                issues.append(
                    Issue(
                        "warning",
                        8,
                        f"Unknown mode '{mode}', expected one of {sorted(VALID_MODES)}",
                        n["id"],
                    )
                )
        elif handler == "wait.system3":
            gate_type = n["attrs"].get("gate_type", "")
            if not gate_type:
                issues.append(
                    Issue(
                        "error",
                        8,
                        "Missing required attribute 'gate_type' for handler=wait.system3",
                        n["id"],
                    )
                )
            elif gate_type not in {"unit", "e2e", "contract"}:
                issues.append(
                    Issue(
                        "error",
                        8,
                        f"Invalid gate_type '{gate_type}' for handler=wait.system3, must be one of unit, e2e, contract",
                        n["id"],
                    )
                )

    # --- Rule 9: No unguarded cycles ---
    # Cycles are only allowed via diamond fail-edges (retry paths)
    _check_cycles(nodes, edges, adj, diamond_nodes, issues)

    # --- Rule 10: promise_id on graph if any node has promise_ac ---
    promise_id = graph_attrs.get("promise_id", "")
    nodes_with_pac = [
        n["id"] for n in nodes if n["attrs"].get("promise_ac")
    ]
    if nodes_with_pac and not promise_id:
        issues.append(
            Issue(
                "warning",
                10,
                f"Nodes {nodes_with_pac} reference promise_ac but graph has no promise_id set",
            )
        )

    # --- Rule 11: Edge conditions use valid syntax ---
    for e in edges:
        cond = e["attrs"].get("condition", "")
        if cond and cond not in VALID_CONDITIONS:
            issues.append(
                Issue(
                    "warning",
                    11,
                    f"Non-standard edge condition '{cond}' on {e['src']}->{e['dst']}, "
                    f"expected one of {sorted(VALID_CONDITIONS)}",
                )
            )

    # --- Handler/shape consistency (schema rule 10 in the doc) ---
    for n in nodes:
        handler = n["attrs"].get("handler", "")
        shape = n["attrs"].get("shape", "")
        if handler in HANDLER_SHAPE_MAP and shape:
            expected = HANDLER_SHAPE_MAP[handler]
            if shape != expected:
                issues.append(
                    Issue(
                        "error",
                        8,
                        f"Shape '{shape}' does not match handler '{handler}' (expected '{expected}')",
                        n["id"],
                    )
                )

    # --- Rule 12: Cluster topology check (AC-5.2) ---
    _check_cluster_topology(nodes, edges, adj, reverse_adj, issues, node_map)

    return issues


def _check_cluster_topology(
    nodes: list[dict],
    edges: list[dict],
    adj: dict[str, list[str]],
    reverse_adj: dict[str, list[str]],
    issues: list[Issue],
    node_map: dict[str, dict],   # <-- This parameter was missing and caused NameError
) -> None:
    """Check full cluster topology: acceptance-test-writer -> research -> refine -> codergen -> wait.system3 -> wait.human"""

    # Build mapping from handler to node IDs
    handler_to_nodes: dict[str, list[str]] = {}
    for n in nodes:
        handler = n["attrs"].get("handler", "")
        if handler not in handler_to_nodes:
            handler_to_nodes[handler] = []
        handler_to_nodes[handler].append(n["id"])

    # Check each codergen node has the full cluster topology leading to it
    codergen_nodes = handler_to_nodes.get("codergen", [])

    for cg_node in codergen_nodes:
        # Find all upstream nodes that should be in the cluster
        upstream_acceptance = []  # acceptance-test-writer nodes that reach this codergen
        upstream_research = []    # research nodes that reach this codergen
        upstream_refine = []      # refine nodes that reach this codergen

        # Find all acceptance-test-writer nodes that can reach this codergen
        for accept_node in handler_to_nodes.get("acceptance-test-writer", []):
            if _can_reach(accept_node, cg_node, adj):
                upstream_acceptance.append(accept_node)

        # Find all research nodes that can reach this codergen
        for research_node in handler_to_nodes.get("research", []):
            if _can_reach(research_node, cg_node, adj):
                upstream_research.append(research_node)

        # Find all refine nodes that can reach this codergen
        for refine_node in handler_to_nodes.get("refine", []):
            if _can_reach(refine_node, cg_node, adj):
                upstream_refine.append(refine_node)

        # According to schema rule, every codergen node should have the full cluster:
        # acceptance-test-writer -> research -> refine -> codergen -> wait.system3 -> wait.human
        # But this might not be true for all codergen nodes - only for certain epic clusters
        # For now, we'll validate the presence of downstream wait.system3 and wait.human
        descendants = _bfs(cg_node, adj)
        has_wait_system3 = any(n_id in descendants for n_id in handler_to_nodes.get("wait.system3", []))
        has_wait_human = any(n_id in descendants for n_id in handler_to_nodes.get("wait.human", []))

        # If we have a codergen node, it should eventually lead to wait.system3 and wait.human
        if not has_wait_system3:
            issues.append(
                Issue(
                    "error",  # Changed to error as per AC-5.2 requirement
                    12,
                    f"codergen node '{cg_node}' must have a downstream wait.system3 node in the cluster",
                    cg_node,
                )
            )

        if not has_wait_human:
            issues.append(
                Issue(
                    "error",  # Changed to error as per AC-5.2 requirement
                    12,
                    f"codergen node '{cg_node}' must have a downstream wait.human node in the cluster",
                    cg_node,
                )
            )

    # Rule V-15: warn codergen without upstream acceptance-test-writer node
    for cg_node in codergen_nodes:
        predecessors_all = _bfs_reverse(cg_node, reverse_adj)
        has_at_writer = any(
            node_map.get(p, {}).get("handler") == "acceptance-test-writer"
            for p in predecessors_all
        )
        if not has_at_writer:
            issues.append(Issue(
                "warning", 15,  # V-15: Warning for codergen without upstream AT writer
                f"codergen node '{cg_node}' has no upstream acceptance-test-writer node (V-15)",
                cg_node,
            ))

    # Rule V-16: warn when skills_required references missing skill dir
    for n in nodes:
        handler = n["attrs"].get("handler", "")
        if handler == "codergen":
            worker_type = n["attrs"].get("worker_type", "").strip()
            if worker_type:
                # Check for agent file to get skills_required
                import os
                import yaml
                from pathlib import Path

                agent_path = Path(f".claude/agents/{worker_type}.md")
                if agent_path.exists():
                    try:
                        content = agent_path.read_text()
                        # Parse YAML frontmatter
                        if content.startswith("---"):
                            # Find the end of the YAML frontmatter
                            lines = content.split('\n')
                            if len(lines) > 1 and lines[0] == "---":
                                # Find the closing ---
                                for i in range(1, len(lines)):
                                    if lines[i] == "---" and i > 0:
                                        fm_content = '\n'.join(lines[1:i])
                                        try:
                                            fm = yaml.safe_load(fm_content)
                                            if fm and isinstance(fm, dict) and "skills_required" in fm:
                                                for skill in fm.get("skills_required", []):
                                                    skill_dir = Path(f".claude/skills/{skill}")
                                                    if not skill_dir.exists():
                                                        issues.append(Issue(
                                                            "warning", 16,  # V-16: Warning for missing skill directory
                                                            f"Agent '{worker_type}' requires skill '{skill}' but .claude/skills/{skill}/ not found (V-16)",
                                                            n["id"],
                                                        ))
                                        except yaml.YAMLError:
                                            pass  # Skip invalid YAML
                                        break
                    except Exception:
                        pass  # Don't fail validation on agent file parse errors

    # Validate that wait.human nodes follow wait.system3 or research (AC-5.4)
    wait_human_nodes = handler_to_nodes.get("wait.human", [])
    wait_system3_nodes = handler_to_nodes.get("wait.system3", [])
    research_nodes = handler_to_nodes.get("research", [])

    for wh_node in wait_human_nodes:
        # Check if this wait.human node has a direct predecessor that is wait.system3 or research
        predecessors = reverse_adj.get(wh_node, [])
        has_valid_predecessor = any(
            pred in wait_system3_nodes or pred in research_nodes or
            node_map.get(pred, {}).get("handler") in ["wait.system3", "research"]
            for pred in predecessors
        )

        if not has_valid_predecessor:
            issues.append(
                Issue(
                    "error",  # AC-5.4: wait.human must follow wait.system3 or research
                    13,
                    f"wait.human node '{wh_node}' must follow wait.system3 or research node",
                    wh_node,
                )
            )


def _can_reach(start: str, target: str, adj: dict[str, list[str]]) -> bool:
    """Check if target is reachable from start using BFS."""
    if start == target:
        return True

    visited = set()
    queue = [start]

    while queue:
        node = queue.pop(0)
        if node == target:
            return True
        if node in visited:
            continue
        visited.add(node)

        for neighbor in adj.get(node, []):
            if neighbor not in visited:
                queue.append(neighbor)

    return False


def _bfs(start: str, adj: dict[str, list[str]]) -> set[str]:
    """Breadth-first search from start node, return all reachable nodes."""
    visited: set[str] = set()
    queue = [start]
    while queue:
        node = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        for neighbor in adj.get(node, []):
            if neighbor not in visited:
                queue.append(neighbor)
    return visited


def _bfs_reverse(start: str, reverse_adj: dict[str, list[str]]) -> set[str]:
    """Breadth-first search backwards from start node, return all predecessor nodes."""
    visited: set[str] = set()
    queue = [start]
    while queue:
        node = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        for predecessor in reverse_adj.get(node, []):
            if predecessor not in visited:
                queue.append(predecessor)
    return visited


def _check_cycles(
    nodes: list[dict],
    edges: list[dict],
    adj: dict[str, list[str]],
    diamond_nodes: list[str],
    issues: list[Issue],
) -> None:
    """Detect cycles. Only cycles via diamond fail-edges are allowed."""
    # Build a set of "allowed back edges" (diamond fail edges)
    allowed_back: set[tuple[str, str]] = set()
    for e in edges:
        if (
            e["src"] in diamond_nodes
            and e["attrs"].get("condition") == "fail"
        ):
            allowed_back.add((e["src"], e["dst"]))

    # Build adj without allowed back edges and check for cycles
    filtered_adj: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for e in edges:
        pair = (e["src"], e["dst"])
        if pair not in allowed_back:
            if e["src"] in filtered_adj:
                filtered_adj[e["src"]].append(e["dst"])

    # DFS cycle detection on filtered graph
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n["id"]: WHITE for n in nodes}
    reported_cycles: set[str] = set()

    def dfs(node: str, path: list[str]) -> None:
        color[node] = GRAY
        path.append(node)
        for neighbor in filtered_adj.get(node, []):
            if color.get(neighbor) == GRAY:
                # Found a cycle — report it if not already reported
                if neighbor in set(path):
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycle_key = " -> ".join(cycle)
                    if cycle_key not in reported_cycles:
                        reported_cycles.add(cycle_key)
                        issues.append(
                            Issue(
                                "error",
                                9,
                                f"Unguarded cycle detected: {cycle_key}",
                            )
                        )
            elif color.get(neighbor) == WHITE:
                dfs(neighbor, path)
        path.pop()
        color[node] = BLACK

    for n in nodes:
        if color[n["id"]] == WHITE:
            dfs(n["id"], [])


def validate_file(filepath: str, strict: bool = False) -> list[Issue]:
    """Parse and validate a DOT file."""
    data = parse_file(filepath)
    return validate(data, strict=strict)


def main() -> None:
    """CLI entry point."""
    ap = argparse.ArgumentParser(
        description="Validate Attractor DOT pipeline files against schema rules."
    )
    ap.add_argument("file", help="Path to .dot file")
    ap.add_argument(
        "--output",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors",
    )
    args = ap.parse_args()

    try:
        issues = validate_file(args.file, strict=args.strict)
    except FileNotFoundError:
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]

    if args.output == "json":
        result = {
            "valid": len(errors) == 0,
            "errors": [i.to_dict() for i in errors],
            "warnings": [i.to_dict() for i in warnings],
            "summary": f"{len(errors)} errors, {len(warnings)} warnings",
        }
        print(json.dumps(result, indent=2))
    else:
        if not issues:
            print(f"VALID: {args.file} passes all validation rules.")
        else:
            if errors:
                print(f"\nErrors ({len(errors)}):")
                for e in errors:
                    print(str(e))
            if warnings:
                print(f"\nWarnings ({len(warnings)}):")
                for w in warnings:
                    print(str(w))
            print(f"\nSummary: {len(errors)} errors, {len(warnings)} warnings")
            if errors:
                print("INVALID: Pipeline has structural errors.")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

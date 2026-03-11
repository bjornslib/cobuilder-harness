#!/usr/bin/env python3
"""Attractor DOT Pipeline Edge Operations.

CRUD operations for edges in Attractor DOT pipeline files.

Usage:
    python3 edge_ops.py <file.dot> list [--output json]
    python3 edge_ops.py <file.dot> add <src> <dst> [--label <label>] [--condition pass|fail|partial] [--set key=value ...] [--dry-run]
    python3 edge_ops.py <file.dot> remove <src> <dst> [--condition pass|fail|partial] [--label <label>] [--dry-run]
    python3 edge_ops.py --help
"""

import argparse
import contextlib
import datetime
import fcntl
import json
import os
import re
import sys

from cobuilder.attractor.parser import parse_dot, parse_file


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_CONDITIONS = {"pass", "fail", "partial"}

_OPS_LOG_SUFFIX = ".ops.jsonl"


# ---------------------------------------------------------------------------
# File-level helpers (locking and logging)
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _dot_file_lock(dot_file: str):
    """Acquire an exclusive file lock on *dot_file* to prevent concurrent writes.

    Creates a companion `<dot_file>.lock` file and removes it on exit.
    """
    lock_path = dot_file + ".lock"
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
        try:
            os.unlink(lock_path)
        except OSError:
            pass


def _append_ops_jsonl(dot_file: str, entry: dict) -> None:
    """Append *entry* as a single JSON line to the ops log alongside *dot_file*."""
    log_path = dot_file + _OPS_LOG_SUFFIX
    with open(log_path, "a") as fh:
        fh.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# DOT edge manipulation helpers
# ---------------------------------------------------------------------------


def _find_edge_block(
    content: str,
    src: str,
    dst: str,
    condition: str = "",
    label: str = "",
) -> tuple[int, int]:
    """Find the span of an edge definition in the DOT content.

    When *condition* or *label* are given they are used to disambiguate
    between multiple edges that share the same src -> dst pair.

    Returns (start, end) byte positions of the full edge statement
    (including leading whitespace and trailing newline), or (-1, -1)
    if no matching edge is found.
    """
    # Match "src -> dst" at the start of a (possibly indented) line
    edge_re = re.compile(
        r"([ \t]*)\b" + re.escape(src) + r"\b[ \t]*->[ \t]*\b" + re.escape(dst) + r"\b[ \t]*",
        re.MULTILINE,
    )

    for m in edge_re.finditer(content):
        # Record where the (indented) line starts — walk back to '\n' boundary
        line_start = m.start()
        while line_start > 0 and content[line_start - 1] != "\n":
            line_start -= 1

        pos = m.end()

        # Skip whitespace between 'dst' and the optional attribute block
        while pos < len(content) and content[pos] in " \t":
            pos += 1

        # Parse optional attribute block [...]
        if pos < len(content) and content[pos] == "[":
            depth = 0
            while pos < len(content):
                ch = content[pos]
                if ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        pos += 1
                        break
                elif ch == '"':
                    pos += 1
                    while pos < len(content) and content[pos] != '"':
                        if content[pos] == "\\":
                            pos += 1
                        pos += 1
                pos += 1

        # Skip optional whitespace then semicolon
        while pos < len(content) and content[pos] in " \t":
            pos += 1
        if pos < len(content) and content[pos] == ";":
            pos += 1

        # Skip trailing whitespace then newline
        while pos < len(content) and content[pos] in " \t":
            pos += 1
        if pos < len(content) and content[pos] == "\n":
            pos += 1

        edge_text = content[line_start:pos]

        # Apply optional filters
        if condition:
            has_cond = (
                f'condition="{condition}"' in edge_text
                or f"condition={condition}" in edge_text
            )
            if not has_cond:
                continue

        if label:
            has_label = (
                f'label="{label}"' in edge_text
                or f"label={label}" in edge_text
            )
            if not has_label:
                continue

        return line_start, pos

    return -1, -1


def _build_edge_statement(
    src: str,
    dst: str,
    label: str = "",
    condition: str = "",
    extra_attrs: dict[str, str] | None = None,
) -> str:
    """Build a DOT edge statement string.

    If no attributes are provided, emits a simple ``src -> dst;`` line.
    Otherwise emits a multi-attribute block.
    """
    attrs: dict[str, str] = {}
    if label:
        attrs["label"] = label
    if condition:
        attrs["condition"] = condition
    if extra_attrs:
        attrs.update(extra_attrs)

    if not attrs:
        return f"    {src} -> {dst};"

    attr_lines = [f"        {k}=\"{v}\"" for k, v in attrs.items()]
    inner = "\n".join(attr_lines)
    return f"    {src} -> {dst} [\n{inner}\n    ];"


def _insert_before_closing_brace(content: str, block: str) -> str:
    """Insert *block* text before the final closing `}` of the digraph."""
    pos = content.rfind("}")
    if pos == -1:
        raise ValueError("Cannot find closing '}' in DOT content")
    return content[:pos] + block + "\n" + content[pos:]


def _would_create_unguarded_cycle(content: str, src: str, dst: str) -> bool:
    """Return True if adding the edge src -> dst would introduce an unguarded cycle.

    Unguarded cycles are forbidden by schema rule 9.  The only permitted
    back-edges are those from ``conditional`` (diamond) nodes carrying
    ``condition=fail`` — these represent retry paths and are intentional.

    Args:
        content: Current DOT file content.
        src:     Proposed edge source node ID.
        dst:     Proposed edge destination node ID.

    Returns:
        True if the proposed edge would create an unguarded cycle.
    """
    data = parse_dot(content)
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    # Determine diamond (conditional) nodes — these may legitimately form cycles
    diamond_nodes: set[str] = {
        n["id"]
        for n in nodes
        if n["attrs"].get("handler") == "conditional"
        or n["attrs"].get("shape") == "diamond"
    }

    # Collect "allowed back-edges" (diamond fail edges that are already in the graph)
    allowed_back: set[tuple[str, str]] = set()
    for e in edges:
        if (
            e["src"] in diamond_nodes
            and e["attrs"].get("condition") == "fail"
        ):
            allowed_back.add((e["src"], e["dst"]))

    # Build adjacency list for the filtered graph (no allowed back-edges)
    # Include all current edges plus the proposed new one.
    adj: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for e in edges:
        pair = (e["src"], e["dst"])
        if pair not in allowed_back and e["src"] in adj:
            adj[e["src"]].append(e["dst"])

    # Add the proposed edge (unless it is itself an allowed back-edge)
    proposed = (src, dst)
    if proposed not in allowed_back and src in adj:
        # Avoid duplicate entries if the same edge already exists
        if dst not in adj[src]:
            adj[src].append(dst)

    # DFS cycle detection on the filtered graph
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n["id"]: WHITE for n in nodes}
    # Handle src/dst that might not be in the current node list
    if src not in color:
        color[src] = WHITE
    if dst not in color:
        color[dst] = WHITE

    def _dfs(node: str) -> bool:
        color[node] = GRAY
        for neighbor in adj.get(node, []):
            state = color.get(neighbor, WHITE)
            if state == GRAY:
                return True  # Back-edge found → cycle
            if state == WHITE and _dfs(neighbor):
                return True
        color[node] = BLACK
        return False

    for n in nodes:
        if color[n["id"]] == WHITE:
            if _dfs(n["id"]):
                return True
    return False


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def list_edges(content: str, output: str = "text") -> None:
    """List all edges in the pipeline."""
    data = parse_dot(content)
    edges = data.get("edges", [])

    if output == "json":
        print(json.dumps(edges, indent=2))
        return

    if not edges:
        print("No edges found.")
        return

    print(f"{'src':<30} {'dst':<30} {'label':<25} {'condition'}")
    print("-" * 95)
    for edge in edges:
        src = edge["src"]
        dst = edge["dst"]
        label = edge["attrs"].get("label", "")[:24]
        condition = edge["attrs"].get("condition", "")
        print(f"{src:<30} {dst:<30} {label:<25} {condition}")

    print(f"\nTotal: {len(edges)} edge(s)")


def add_edge(
    content: str,
    src: str,
    dst: str,
    label: str = "",
    condition: str = "",
    extra_attrs: dict[str, str] | None = None,
    allow_cycle: bool = False,
) -> str:
    """Add a new edge to the DOT content.

    Args:
        content:     DOT file content string.
        src:         Source node ID.
        dst:         Destination node ID.
        label:       Optional edge label.
        condition:   Optional condition value (pass/fail/partial).
        extra_attrs: Additional key=value attributes.
        allow_cycle: If True, skip unguarded cycle detection and allow the edge
                     even if it would form a cycle. Use with caution; only for
                     deliberate non-standard back-edges.

    Returns:
        Updated DOT content string.

    Raises:
        ValueError: If src or dst nodes don't exist, condition is invalid,
                    the edge is a self-loop, or it would create an unguarded cycle.
    """
    # Self-loop check — always rejected regardless of allow_cycle
    if src == dst:
        raise ValueError(
            f"Self-loop detected: edge '{src} -> {dst}' connects a node to itself. "
            f"Self-loops are not permitted in pipeline graphs."
        )

    # Validate condition
    if condition and condition not in VALID_CONDITIONS:
        raise ValueError(
            f"Invalid condition '{condition}'. Valid conditions: {sorted(VALID_CONDITIONS)}"
        )

    # Validate nodes exist
    data = parse_dot(content)
    node_ids = {n["id"] for n in data.get("nodes", [])}
    if src not in node_ids:
        raise ValueError(f"Source node '{src}' not found in pipeline")
    if dst not in node_ids:
        raise ValueError(f"Destination node '{dst}' not found in pipeline")

    # Cycle detection (schema rule 9): reject unguarded cycles unless suppressed.
    # A fail-edge from a conditional/diamond node is intrinsically allowed.
    if not allow_cycle:
        is_allowed_back_edge = (
            condition == "fail"
            and any(
                n["id"] == src
                and (
                    n["attrs"].get("handler") == "conditional"
                    or n["attrs"].get("shape") == "diamond"
                )
                for n in data.get("nodes", [])
            )
        )
        if not is_allowed_back_edge and _would_create_unguarded_cycle(content, src, dst):
            raise ValueError(
                f"Adding edge '{src} -> {dst}' would create an unguarded cycle "
                f"(schema rule 9). Only conditional/diamond fail-edges may form cycles. "
                f"Use --allow-cycle to override."
            )

    statement = _build_edge_statement(src, dst, label=label, condition=condition, extra_attrs=extra_attrs)
    return _insert_before_closing_brace(content, "\n" + statement)


def remove_edge(
    content: str,
    src: str,
    dst: str,
    condition: str = "",
    label: str = "",
) -> tuple[str, int]:
    """Remove edge(s) matching src -> dst from the DOT content.

    If *condition* or *label* are provided, only edges matching those
    filters are removed. Otherwise ALL edges between src and dst are removed.

    Args:
        content:   DOT file content string.
        src:       Source node ID.
        dst:       Destination node ID.
        condition: Optional condition filter (pass/fail/partial).
        label:     Optional label filter.

    Returns:
        (updated_content, count_removed)

    Raises:
        ValueError: If no matching edge is found.
    """
    count = 0

    while True:
        start, end = _find_edge_block(content, src, dst, condition=condition, label=label)
        if start == -1:
            break
        content = content[:start] + content[end:]
        count += 1

    if count == 0:
        filter_desc = ""
        if condition:
            filter_desc += f" with condition='{condition}'"
        if label:
            filter_desc += f" with label='{label}'"
        raise ValueError(
            f"No edge '{src} -> {dst}'{filter_desc} found in pipeline"
        )

    # Clean up excess blank lines
    content = re.sub(r"\n{3,}", "\n\n", content)

    return content, count


def _parse_set_args(set_args: list[str]) -> dict[str, str]:
    """Parse a list of 'key=value' strings into a dict."""
    result: dict[str, str] = {}
    for item in set_args:
        if "=" not in item:
            raise ValueError(f"Invalid --set format '{item}': expected key=value")
        key, _, value = item.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"Empty key in --set '{item}'")
        result[key] = value
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point."""
    ap = argparse.ArgumentParser(
        description="CRUD operations for edges in Attractor DOT pipeline files."
    )
    ap.add_argument("file", help="Path to .dot file")

    subparsers = ap.add_subparsers(dest="command", help="operation")

    # --- list ---
    list_p = subparsers.add_parser("list", help="List all edges")
    list_p.add_argument(
        "--output",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )

    # --- add ---
    add_p = subparsers.add_parser("add", help="Add a new edge")
    add_p.add_argument("src", help="Source node ID")
    add_p.add_argument("dst", help="Destination node ID")
    add_p.add_argument("--label", default="", help="Edge label (optional)")
    add_p.add_argument(
        "--condition",
        default="",
        choices=["", *sorted(VALID_CONDITIONS)],
        help="Edge condition (pass/fail/partial, optional)",
    )
    add_p.add_argument(
        "--set",
        action="append",
        dest="set_attrs",
        metavar="key=value",
        default=[],
        help="Additional edge attribute(s) as key=value (repeatable)",
    )
    add_p.add_argument(
        "--allow-cycle",
        action="store_true",
        dest="allow_cycle",
        help="Skip unguarded cycle detection for this edge (use with caution)",
    )
    add_p.add_argument("--dry-run", action="store_true", help="Preview without writing")
    add_p.add_argument(
        "--output",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )

    # --- remove ---
    remove_p = subparsers.add_parser("remove", help="Remove edge(s)")
    remove_p.add_argument("src", help="Source node ID")
    remove_p.add_argument("dst", help="Destination node ID")
    remove_p.add_argument(
        "--condition",
        default="",
        choices=["", *sorted(VALID_CONDITIONS)],
        help="Filter by condition (optional; removes all edges when omitted)",
    )
    remove_p.add_argument("--label", default="", help="Filter by label (optional)")
    remove_p.add_argument("--dry-run", action="store_true", help="Preview without writing")
    remove_p.add_argument(
        "--output",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )

    args = ap.parse_args()

    if args.command is None:
        ap.print_help()
        sys.exit(1)

    # Load DOT file
    try:
        with open(args.file, "r") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    output = getattr(args, "output", "text")
    dry_run = getattr(args, "dry_run", False)

    # --- Dispatch ---

    if args.command == "list":
        list_edges(content, output=output)

    elif args.command == "add":
        try:
            extra_attrs = _parse_set_args(args.set_attrs)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        try:
            updated = add_edge(
                content,
                args.src,
                args.dst,
                label=args.label,
                condition=args.condition,
                extra_attrs=extra_attrs if extra_attrs else None,
                allow_cycle=getattr(args, "allow_cycle", False),
            )
        except ValueError as e:
            if output == "json":
                print(json.dumps({"success": False, "error": str(e)}, indent=2))
            else:
                print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        desc = f"{args.src} -> {args.dst}"
        if args.condition:
            desc += f" [{args.condition}]"

        if dry_run:
            if output == "json":
                print(json.dumps({
                    "success": True,
                    "dry_run": True,
                    "src": args.src,
                    "dst": args.dst,
                    "condition": args.condition,
                    "label": args.label,
                }, indent=2))
            else:
                print(f"DRY RUN: would add edge '{desc}'")
                print("(no changes written)")
        else:
            with _dot_file_lock(args.file):
                with open(args.file, "w") as f:
                    f.write(updated)

                timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
                _append_ops_jsonl(
                    args.file,
                    {
                        "timestamp": timestamp,
                        "file": args.file,
                        "command": "edge add",
                        "src": args.src,
                        "dst": args.dst,
                        "label": args.label,
                        "condition": args.condition,
                    },
                )

            if output == "json":
                print(json.dumps({
                    "success": True,
                    "src": args.src,
                    "dst": args.dst,
                    "condition": args.condition,
                    "label": args.label,
                    "file": args.file,
                }, indent=2))
            else:
                print(f"Edge added: {desc}")
                print(f"Updated: {args.file}")

    elif args.command == "remove":
        try:
            updated, count = remove_edge(
                content,
                args.src,
                args.dst,
                condition=args.condition,
                label=args.label,
            )
        except ValueError as e:
            if output == "json":
                print(json.dumps({"success": False, "error": str(e)}, indent=2))
            else:
                print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        desc = f"{args.src} -> {args.dst}"
        if args.condition:
            desc += f" [condition={args.condition}]"

        if dry_run:
            if output == "json":
                print(json.dumps({
                    "success": True,
                    "dry_run": True,
                    "src": args.src,
                    "dst": args.dst,
                    "count": count,
                }, indent=2))
            else:
                print(f"DRY RUN: would remove {count} edge(s) matching '{desc}'")
                print("(no changes written)")
        else:
            with _dot_file_lock(args.file):
                with open(args.file, "w") as f:
                    f.write(updated)

                timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
                _append_ops_jsonl(
                    args.file,
                    {
                        "timestamp": timestamp,
                        "file": args.file,
                        "command": "edge remove",
                        "src": args.src,
                        "dst": args.dst,
                        "condition": args.condition,
                        "label": args.label,
                        "count": count,
                    },
                )

            if output == "json":
                print(json.dumps({
                    "success": True,
                    "src": args.src,
                    "dst": args.dst,
                    "count": count,
                    "file": args.file,
                }, indent=2))
            else:
                print(f"Edge(s) removed: {count} matching '{desc}'")
                print(f"Updated: {args.file}")

    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

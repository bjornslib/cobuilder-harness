#!/usr/bin/env python3
"""Attractor DOT Pipeline Node Operations.

CRUD operations for nodes in Attractor DOT pipeline files.

Usage:
    python3 node_ops.py <file.dot> list [--output json]
    python3 node_ops.py <file.dot> add <node_id> --handler <handler> --label <label> [--set key=value ...] [--dry-run]
    python3 node_ops.py <file.dot> remove <node_id> [--dry-run]
    python3 node_ops.py <file.dot> modify <node_id> --set key=value [--set key=value ...] [--dry-run]
    python3 node_ops.py --help
"""

import argparse
import contextlib
import datetime
import fcntl
import json
import os
import re
import sys

from cobuilder.engine.dispatch_parser import parse_dot, parse_file
from cobuilder.engine.validator import VALID_HANDLERS, HANDLER_SHAPE_MAP, VALID_STATUSES


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STATUS_COLORS: dict[str, str] = {
    "pending": "lightyellow",
    "active": "lightblue",
    "impl_complete": "lightsalmon",
    "validated": "lightgreen",
    "failed": "lightcoral",
}

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
# DOT manipulation helpers
# ---------------------------------------------------------------------------


def _find_node_block(content: str, node_id: str) -> tuple[int, int]:
    """Find the start and end positions of a node's definition block.

    Returns (start, end) positions, or (-1, -1) if not found.
    """
    pattern = re.compile(
        r"(?<!\w)(" + re.escape(node_id) + r")\s*\[",
        re.MULTILINE,
    )

    for m in pattern.finditer(content):
        # Verify this isn't an edge (no -> before it on the same line)
        before = content[: m.start()].rstrip()
        if before.endswith("->"):
            continue

        bracket_start = content.index("[", m.start())
        depth = 0
        pos = bracket_start
        while pos < len(content):
            if content[pos] == "[":
                depth += 1
            elif content[pos] == "]":
                depth -= 1
                if depth == 0:
                    end = pos + 1
                    if end < len(content) and content[end] == ";":
                        end += 1
                    return m.start(), end
            elif content[pos] == '"':
                pos += 1
                while pos < len(content) and content[pos] != '"':
                    if content[pos] == "\\":
                        pos += 1
                    pos += 1
            pos += 1

    return -1, -1


def _update_node_attr(content: str, node_id: str, attr: str, value: str) -> str:
    """Update a single attribute within a node's block."""
    start, end = _find_node_block(content, node_id)
    if start == -1:
        raise ValueError(f"Cannot find node block for '{node_id}'")

    block = content[start:end]

    # Try to replace existing quoted attribute: attr="old_value"
    attr_pattern = re.compile(r"(" + re.escape(attr) + r")\s*=\s*\"[^\"]*\"")
    m = attr_pattern.search(block)
    if m:
        new_block = block[: m.start()] + f'{attr}="{value}"' + block[m.end() :]
        return content[:start] + new_block + content[end:]

    # Try unquoted: attr=value
    attr_pattern_unquoted = re.compile(r"(" + re.escape(attr) + r")\s*=\s*(\S+)")
    m = attr_pattern_unquoted.search(block)
    if m:
        new_block = block[: m.start()] + f'{attr}="{value}"' + block[m.end() :]
        return content[:start] + new_block + content[end:]

    # Attribute not found — add it
    return _add_node_attr(content, node_id, attr, value)


def _add_node_attr(content: str, node_id: str, attr: str, value: str) -> str:
    """Add a new attribute to a node's block."""
    start, end = _find_node_block(content, node_id)
    if start == -1:
        raise ValueError(f"Cannot find node block for '{node_id}'")

    block = content[start:end]

    bracket_pos = block.rfind("]")
    if bracket_pos == -1:
        raise ValueError(f"Malformed node block for '{node_id}'")

    new_attr = f'\n        {attr}="{value}"'
    new_block = block[:bracket_pos] + new_attr + "\n    " + block[bracket_pos:]
    return content[:start] + new_block + content[end:]


def _remove_node_edges(content: str, node_id: str) -> tuple[str, list[str]]:
    """Remove all edge statements referencing *node_id* as src or dst.

    Returns (updated_content, list_of_removed_edge_descriptions).
    """
    removed: list[str] = []

    # Pattern matches edge lines: whitespace node -> node [attrs]; newline
    # Handles both single-line and multi-line edge blocks.
    # We scan for "node_id ->" and "-> node_id" patterns.
    edge_pattern = re.compile(
        r"[ \t]*\b" + re.escape(node_id) + r"\b[ \t]*->[ \t]*\w+[ \t]*(?:\[[^\]]*\])?[ \t]*;?[ \t]*\n?",
        re.DOTALL,
    )
    reverse_pattern = re.compile(
        r"[ \t]*\w+[ \t]*->[ \t]*\b" + re.escape(node_id) + r"\b[ \t]*(?:\[[^\]]*\])?[ \t]*;?[ \t]*\n?",
        re.DOTALL,
    )

    for pat in (edge_pattern, reverse_pattern):
        for m in pat.finditer(content):
            removed.append(m.group(0).strip())

    # Remove all matches (iterate backwards to preserve positions)
    for pat in (edge_pattern, reverse_pattern):
        content = pat.sub("", content)

    # Clean up double blank lines
    content = re.sub(r"\n{3,}", "\n\n", content)

    return content, removed


def _build_node_block(node_id: str, attrs: dict[str, str]) -> str:
    """Build a DOT node block string from a node_id and attribute dict."""
    lines = [f"    {node_id} ["]
    for key, value in attrs.items():
        # Values that don't need quoting: fillcolor names, bare keywords
        # We quote everything for consistency
        lines.append(f'        {key}="{value}"')
    lines.append("    ];")
    return "\n".join(lines)


def _insert_before_closing_brace(content: str, block: str) -> str:
    """Insert *block* text before the final closing `}` of the digraph."""
    pos = content.rfind("}")
    if pos == -1:
        raise ValueError("Cannot find closing '}' in DOT content")
    return content[:pos] + block + "\n" + content[pos:]


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def list_nodes(content: str, output: str = "text") -> None:
    """List all nodes in the pipeline."""
    data = parse_dot(content)
    nodes = data.get("nodes", [])

    if output == "json":
        print(json.dumps(nodes, indent=2))
        return

    if not nodes:
        print("No nodes found.")
        return

    print(f"{'ID':<35} {'handler':<20} {'status':<15} {'label'}")
    print("-" * 90)
    for node in nodes:
        nid = node["id"]
        handler = node["attrs"].get("handler", "?")
        status = node["attrs"].get("status", "pending")
        label = node["attrs"].get("label", "").replace("\\n", " ")[:40]
        print(f"{nid:<35} {handler:<20} {status:<15} {label}")

    print(f"\nTotal: {len(nodes)} node(s)")


def add_node(
    content: str,
    node_id: str,
    handler: str,
    label: str,
    status: str = "pending",
    extra_attrs: dict[str, str] | None = None,
    auto_pair_at: bool = True,
) -> str:
    """Add a new node to the DOT content.

    Args:
        content:      DOT file content string.
        node_id:      Identifier for the new node (must be unique).
        handler:      Handler type (must be in VALID_HANDLERS).
        label:        Display label for the node.
        status:       Initial status (default: pending).
        extra_attrs:  Additional key=value attributes to set on the node.
        auto_pair_at: If True (default) and handler is 'codergen', automatically
                      add a paired wait.human (AT gate) node named ``{node_id}_at``
                      and a directed edge from the codergen node to it.
                      Satisfies schema rule 5 (every codergen needs an AT peer).
                      Pass False (or use ``--no-at-pair`` on the CLI) to suppress.

    Returns:
        Updated DOT content string.

    Raises:
        ValueError: If node_id already exists, handler is invalid, or status is invalid.
    """
    if handler not in VALID_HANDLERS:
        raise ValueError(
            f"Unknown handler '{handler}'. Valid handlers: {sorted(VALID_HANDLERS)}"
        )
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'. Valid statuses: {sorted(VALID_STATUSES)}"
        )

    # Check node_id doesn't already exist
    existing_start, _ = _find_node_block(content, node_id)
    if existing_start != -1:
        raise ValueError(f"Node '{node_id}' already exists in the pipeline")

    # Infer shape from handler
    shape = HANDLER_SHAPE_MAP.get(handler, "box")
    fillcolor = STATUS_COLORS.get(status, "lightyellow")

    # Build attributes in standard order
    attrs: dict[str, str] = {}
    attrs["shape"] = shape
    attrs["label"] = label.replace('"', '\\"')
    attrs["handler"] = handler
    attrs["status"] = status
    attrs["style"] = "filled"
    attrs["fillcolor"] = fillcolor

    # Merge any extra attributes (may override defaults)
    if extra_attrs:
        attrs.update(extra_attrs)

    block = _build_node_block(node_id, attrs)
    content = _insert_before_closing_brace(content, "\n" + block)

    # AT auto-pairing: add a wait.human validation gate for codergen nodes
    if auto_pair_at and handler == "codergen":
        at_node_id = f"{node_id}_at"
        at_label = f"Validate: {label}".replace('"', '\\"')
        at_attrs: dict[str, str] = {
            "shape": HANDLER_SHAPE_MAP.get("wait.human", "hexagon"),
            "label": at_label,
            "handler": "wait.human",
            "status": "pending",
            "style": "filled",
            "fillcolor": STATUS_COLORS.get("pending", "lightyellow"),
            "gate": "technical",
            "mode": "technical",
        }
        at_block = _build_node_block(at_node_id, at_attrs)
        content = _insert_before_closing_brace(content, "\n" + at_block)
        # Add directed edge: codergen node -> AT node
        edge_stmt = f"\n    {node_id} -> {at_node_id};"
        content = _insert_before_closing_brace(content, edge_stmt)

    return content


def remove_node(
    content: str,
    node_id: str,
    remove_edges: bool = True,
) -> tuple[str, list[str]]:
    """Remove a node from the DOT content.

    Args:
        content:      DOT file content string.
        node_id:      Node ID to remove.
        remove_edges: If True, also remove edges referencing this node (default: True).

    Returns:
        (updated_content, removed_edge_descriptions)

    Raises:
        ValueError: If the node is not found.
    """
    start, end = _find_node_block(content, node_id)
    if start == -1:
        raise ValueError(f"Node '{node_id}' not found in pipeline")

    # Remove the node block.
    # Also remove the preceding newline if possible (to avoid blank lines).
    remove_start = start
    # Walk back to eat leading whitespace/newline on the same "block"
    while remove_start > 0 and content[remove_start - 1] in " \t":
        remove_start -= 1
    if remove_start > 0 and content[remove_start - 1] == "\n":
        remove_start -= 1

    updated = content[:remove_start] + content[end:]

    removed_edges: list[str] = []
    if remove_edges:
        updated, removed_edges = _remove_node_edges(updated, node_id)

    return updated, removed_edges


def modify_node(
    content: str,
    node_id: str,
    attr_updates: dict[str, str],
) -> str:
    """Modify attributes of an existing node.

    Args:
        content:      DOT file content string.
        node_id:      Node ID to modify.
        attr_updates: Dict of {attr: value} pairs to apply.

    Returns:
        Updated DOT content string.

    Raises:
        ValueError: If the node is not found or an invalid value is supplied.
    """
    # Validate node exists
    start, _ = _find_node_block(content, node_id)
    if start == -1:
        raise ValueError(f"Node '{node_id}' not found in pipeline")

    # Validate status if being updated
    if "status" in attr_updates:
        new_status = attr_updates["status"]
        if new_status not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{new_status}'. Valid statuses: {sorted(VALID_STATUSES)}"
            )
        # Sync fillcolor when status changes
        if "fillcolor" not in attr_updates:
            attr_updates["fillcolor"] = STATUS_COLORS.get(new_status, "lightyellow")

    # Validate handler if being updated
    if "handler" in attr_updates:
        new_handler = attr_updates["handler"]
        if new_handler not in VALID_HANDLERS:
            raise ValueError(
                f"Unknown handler '{new_handler}'. Valid handlers: {sorted(VALID_HANDLERS)}"
            )
        # Sync shape when handler changes (unless shape is also explicitly set)
        if "shape" not in attr_updates:
            attr_updates["shape"] = HANDLER_SHAPE_MAP.get(new_handler, "box")

    updated = content
    for attr, value in attr_updates.items():
        updated = _update_node_attr(updated, node_id, attr, value)

    return updated


def _parse_set_args(set_args: list[str]) -> dict[str, str]:
    """Parse a list of 'key=value' strings into a dict.

    Raises:
        ValueError: If any string is not in 'key=value' format.
    """
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
        description="CRUD operations for nodes in Attractor DOT pipeline files."
    )
    ap.add_argument("file", help="Path to .dot file")

    subparsers = ap.add_subparsers(dest="command", help="operation")

    # --- list ---
    list_p = subparsers.add_parser("list", help="List all nodes")
    list_p.add_argument(
        "--output",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )

    # --- add ---
    add_p = subparsers.add_parser("add", help="Add a new node")
    add_p.add_argument("node_id", help="Node identifier (unique)")
    add_p.add_argument(
        "--handler",
        required=True,
        choices=sorted(VALID_HANDLERS),
        help="Handler type (determines shape)",
    )
    add_p.add_argument("--label", required=True, help="Display label for the node")
    add_p.add_argument(
        "--status",
        default="pending",
        choices=sorted(VALID_STATUSES),
        help="Initial status (default: pending)",
    )
    add_p.add_argument(
        "--set",
        action="append",
        dest="set_attrs",
        metavar="key=value",
        default=[],
        help="Additional attribute(s) to set (repeatable)",
    )
    add_p.add_argument(
        "--no-at-pair",
        action="store_true",
        dest="no_at_pair",
        help="Suppress automatic AT gate pairing for codergen nodes (default: pair is created)",
    )
    add_p.add_argument("--dry-run", action="store_true", help="Preview without writing")
    add_p.add_argument(
        "--output",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )

    # --- remove ---
    remove_p = subparsers.add_parser("remove", help="Remove a node")
    remove_p.add_argument("node_id", help="Node ID to remove")
    remove_p.add_argument(
        "--keep-edges",
        action="store_true",
        help="Do not remove edges referencing this node",
    )
    remove_p.add_argument("--dry-run", action="store_true", help="Preview without writing")
    remove_p.add_argument(
        "--output",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )

    # --- modify ---
    modify_p = subparsers.add_parser("modify", help="Modify node attributes")
    modify_p.add_argument("node_id", help="Node ID to modify")
    modify_p.add_argument(
        "--set",
        action="append",
        dest="set_attrs",
        metavar="key=value",
        required=True,
        help="Attribute(s) to update as key=value (repeatable)",
    )
    modify_p.add_argument("--dry-run", action="store_true", help="Preview without writing")
    modify_p.add_argument(
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
        list_nodes(content, output=output)

    elif args.command == "add":
        # Parse extra --set attrs
        try:
            extra_attrs = _parse_set_args(args.set_attrs)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        try:
            updated = add_node(
                content,
                args.node_id,
                handler=args.handler,
                label=args.label,
                status=args.status,
                extra_attrs=extra_attrs if extra_attrs else None,
                auto_pair_at=not getattr(args, "no_at_pair", False),
            )
        except ValueError as e:
            if output == "json":
                print(json.dumps({"success": False, "error": str(e)}, indent=2))
            else:
                print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        auto_pair_at = not getattr(args, "no_at_pair", False)
        at_node_id = f"{args.node_id}_at" if (auto_pair_at and args.handler == "codergen") else None

        if dry_run:
            if output == "json":
                result: dict = {"success": True, "dry_run": True, "node_id": args.node_id}
                if at_node_id:
                    result["at_node_id"] = at_node_id
                print(json.dumps(result, indent=2))
            else:
                print(f"DRY RUN: would add node '{args.node_id}' (handler={args.handler})")
                if at_node_id:
                    print(f"  Also would add AT gate node '{at_node_id}' (handler=wait.human)")
                    print(f"  Also would add edge: {args.node_id} -> {at_node_id}")
                print("(no changes written)")
        else:
            with _dot_file_lock(args.file):
                with open(args.file, "w") as f:
                    f.write(updated)

                timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
                log_entry: dict = {
                    "timestamp": timestamp,
                    "file": args.file,
                    "command": "node add",
                    "node_id": args.node_id,
                    "handler": args.handler,
                    "label": args.label,
                    "status": args.status,
                }
                if at_node_id:
                    log_entry["at_node_id"] = at_node_id
                    log_entry["auto_pair_at"] = True
                _append_ops_jsonl(args.file, log_entry)

            if output == "json":
                result = {"success": True, "node_id": args.node_id, "file": args.file}
                if at_node_id:
                    result["at_node_id"] = at_node_id
                print(json.dumps(result, indent=2))
            else:
                print(f"Node added: {args.node_id}")
                if at_node_id:
                    print(f"  AT gate node added: {at_node_id}")
                    print(f"  Edge added: {args.node_id} -> {at_node_id}")
                print(f"Updated: {args.file}")

    elif args.command == "remove":
        remove_edges = not args.keep_edges
        try:
            updated, removed_edges = remove_node(content, args.node_id, remove_edges=remove_edges)
        except ValueError as e:
            if output == "json":
                print(json.dumps({"success": False, "error": str(e)}, indent=2))
            else:
                print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        if dry_run:
            if output == "json":
                print(json.dumps({
                    "success": True,
                    "dry_run": True,
                    "node_id": args.node_id,
                    "edges_removed": len(removed_edges),
                }, indent=2))
            else:
                print(f"DRY RUN: would remove node '{args.node_id}'")
                if removed_edges:
                    print(f"  Would also remove {len(removed_edges)} edge(s)")
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
                        "command": "node remove",
                        "node_id": args.node_id,
                        "edges_removed": len(removed_edges),
                    },
                )

            if output == "json":
                print(json.dumps({
                    "success": True,
                    "node_id": args.node_id,
                    "edges_removed": len(removed_edges),
                    "file": args.file,
                }, indent=2))
            else:
                print(f"Node removed: {args.node_id}")
                if removed_edges:
                    print(f"  Also removed {len(removed_edges)} edge(s) referencing this node")
                print(f"Updated: {args.file}")

    elif args.command == "modify":
        try:
            attr_updates = _parse_set_args(args.set_attrs)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        try:
            updated = modify_node(content, args.node_id, attr_updates)
        except ValueError as e:
            if output == "json":
                print(json.dumps({"success": False, "error": str(e)}, indent=2))
            else:
                print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        if dry_run:
            if output == "json":
                print(json.dumps({
                    "success": True,
                    "dry_run": True,
                    "node_id": args.node_id,
                    "updates": attr_updates,
                }, indent=2))
            else:
                print(f"DRY RUN: would modify node '{args.node_id}'")
                for k, v in attr_updates.items():
                    print(f"  {k} = \"{v}\"")
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
                        "command": "node modify",
                        "node_id": args.node_id,
                        "updates": attr_updates,
                    },
                )

            if output == "json":
                print(json.dumps({
                    "success": True,
                    "node_id": args.node_id,
                    "updates": attr_updates,
                    "file": args.file,
                }, indent=2))
            else:
                print(f"Node modified: {args.node_id}")
                for k, v in attr_updates.items():
                    print(f"  {k} = \"{v}\"")
                print(f"Updated: {args.file}")

    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

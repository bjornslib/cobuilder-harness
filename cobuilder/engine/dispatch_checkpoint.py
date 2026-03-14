#!/usr/bin/env python3
"""Attractor DOT Pipeline Checkpoint Manager.

Save and restore pipeline state to/from JSON checkpoints.

Usage:
    python3 checkpoint.py save <file.dot> [--output=<path>]
    python3 checkpoint.py restore <checkpoint.json> [--output=<file.dot>]
    python3 checkpoint.py --help
"""

import argparse
import datetime
import json
import os
import re
import sys

from cobuilder.engine.dispatch_parser import parse_file, parse_dot


def save_checkpoint(dot_path: str, output_path: str = "") -> dict:
    """Save the current pipeline state to a JSON checkpoint.

    The checkpoint includes:
        - graph metadata (name, prd_ref, promise_id)
        - all node statuses with timestamps
        - all edge definitions
        - original DOT content hash for integrity
        - timestamp of checkpoint creation
    """
    with open(dot_path, "r") as f:
        dot_content = f.read()

    data = parse_dot(dot_content)
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Build node state map
    nodes_state = []
    for node in data["nodes"]:
        attrs = node["attrs"]
        nodes_state.append({
            "id": node["id"],
            "handler": attrs.get("handler", ""),
            "status": attrs.get("status", "pending"),
            "shape": attrs.get("shape", ""),
            "label": attrs.get("label", "").replace("\n", " "),
            "bead_id": attrs.get("bead_id", ""),
            "worker_type": attrs.get("worker_type", ""),
            "promise_ac": attrs.get("promise_ac", ""),
            # Preserve all custom attributes
            "all_attrs": attrs,
        })

    # Build edge list
    edges_state = []
    for edge in data["edges"]:
        edges_state.append({
            "src": edge["src"],
            "dst": edge["dst"],
            "attrs": edge["attrs"],
        })

    checkpoint = {
        "version": "1.0.0",
        "created_at": timestamp,
        "source_file": os.path.abspath(dot_path),
        "graph_name": data["graph_name"],
        "graph_attrs": data["graph_attrs"],
        "defaults": data["defaults"],
        "nodes": nodes_state,
        "edges": edges_state,
        "content_hash": _simple_hash(dot_content),
    }

    if not output_path:
        # Default: same directory as DOT file, with timestamp
        base = os.path.splitext(os.path.basename(dot_path))[0]
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = os.path.join(
            os.path.dirname(dot_path) or ".",
            f"{base}-checkpoint-{ts}.json",
        )

    with open(output_path, "w") as f:
        json.dump(checkpoint, f, indent=2)

    return {"checkpoint_path": output_path, "checkpoint": checkpoint}


def restore_checkpoint(checkpoint_path: str, output_path: str = "") -> str:
    """Restore a pipeline from a JSON checkpoint to DOT format.

    Reconstructs a valid DOT file from the checkpoint data.

    Returns the output file path.
    """
    with open(checkpoint_path, "r") as f:
        checkpoint = json.load(f)

    if not output_path:
        # Default: derive from source file path
        source = checkpoint.get("source_file", "restored-pipeline.dot")
        base = os.path.splitext(os.path.basename(source))[0]
        output_path = os.path.join(
            os.path.dirname(checkpoint_path) or ".",
            f"{base}-restored.dot",
        )

    dot_content = _reconstruct_dot(checkpoint)

    with open(output_path, "w") as f:
        f.write(dot_content)

    return output_path


def _reconstruct_dot(checkpoint: dict) -> str:
    """Reconstruct a DOT file from checkpoint data."""
    lines = []

    graph_name = checkpoint.get("graph_name", "restored")
    lines.append(f'digraph "{graph_name}" {{')

    # Graph attributes
    graph_attrs = checkpoint.get("graph_attrs", {})
    if graph_attrs:
        lines.append("    graph [")
        for key, val in graph_attrs.items():
            lines.append(f'        {key}="{val}"')
        lines.append("    ];")
        lines.append("")

    # Default node/edge attributes
    defaults = checkpoint.get("defaults", {})
    node_defaults = defaults.get("node", {})
    edge_defaults = defaults.get("edge", {})

    if node_defaults:
        attrs_str = " ".join(f'{k}="{v}"' for k, v in node_defaults.items())
        lines.append(f"    node [{attrs_str}];")
    if edge_defaults:
        attrs_str = " ".join(f'{k}="{v}"' for k, v in edge_defaults.items())
        lines.append(f"    edge [{attrs_str}];")

    if node_defaults or edge_defaults:
        lines.append("")

    # Nodes
    for node in checkpoint.get("nodes", []):
        node_id = node["id"]
        attrs = node.get("all_attrs", {})

        # Build attribute list
        attr_lines = []
        for key, val in attrs.items():
            # Quote values that contain spaces or special chars, or always quote
            attr_lines.append(f'        {key}="{val}"')

        lines.append(f"    {node_id} [")
        lines.append("\n".join(attr_lines))
        lines.append("    ];")
        lines.append("")

    # Edges
    for edge in checkpoint.get("edges", []):
        src = edge["src"]
        dst = edge["dst"]
        attrs = edge.get("attrs", {})
        if attrs:
            attr_parts = []
            for key, val in attrs.items():
                attr_parts.append(f'{key}="{val}"')
            attrs_str = " ".join(attr_parts)
            lines.append(f"    {src} -> {dst} [{attrs_str}];")
        else:
            lines.append(f"    {src} -> {dst};")

    lines.append("}")
    lines.append("")

    return "\n".join(lines)


def _simple_hash(content: str) -> str:
    """Simple hash of content for integrity checking (stdlib only)."""
    import hashlib
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def main() -> None:
    """CLI entry point."""
    ap = argparse.ArgumentParser(
        description="Save and restore Attractor DOT pipeline checkpoints."
    )
    sub = ap.add_subparsers(dest="command", help="Checkpoint command")
    sub.required = True

    # save subcommand
    save_p = sub.add_parser("save", help="Save pipeline state to JSON checkpoint")
    save_p.add_argument("file", help="Path to .dot file")
    save_p.add_argument(
        "--output",
        default="",
        help="Output path for checkpoint JSON (default: auto-generated)",
    )

    # restore subcommand
    restore_p = sub.add_parser(
        "restore", help="Restore pipeline from JSON checkpoint"
    )
    restore_p.add_argument("file", help="Path to checkpoint .json file")
    restore_p.add_argument(
        "--output",
        default="",
        help="Output path for restored .dot file (default: auto-generated)",
    )

    args = ap.parse_args()

    if args.command == "save":
        try:
            result = save_checkpoint(args.file, args.output)
            print(f"Checkpoint saved: {result['checkpoint_path']}")
            cp = result["checkpoint"]
            print(f"  Graph: {cp['graph_name']}")
            print(f"  Nodes: {len(cp['nodes'])}")
            print(f"  Edges: {len(cp['edges'])}")
            print(f"  Hash:  {cp['content_hash']}")
        except FileNotFoundError:
            print(f"Error: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "restore":
        try:
            output = restore_checkpoint(args.file, args.output)
            print(f"Pipeline restored: {output}")
        except FileNotFoundError:
            print(f"Error: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in {args.file}: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()

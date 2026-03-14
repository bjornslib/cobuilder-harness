#!/usr/bin/env python3
"""Attractor DOT Pipeline Annotator.

Takes an existing pipeline.dot and cross-references with beads data to:
- Update bead_id attributes on nodes by matching task titles/descriptions
- Update status attributes from beads status
- Add missing acceptance criteria from beads

Usage:
    python3 annotate.py pipeline.dot [--output annotated.dot]
    python3 annotate.py pipeline.dot --beads-json beads.json
    python3 annotate.py --help
"""

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any

# Ensure sibling imports work

from cobuilder.engine.dispatch_parser import parse_dot


# Beads status -> DOT node status
BEADS_STATUS_MAP: dict[str, str] = {
    "open": "pending",
    "in_progress": "active",
    "impl_complete": "impl_complete",
    "closed": "validated",
    "blocked": "pending",
}

# DOT status -> fillcolor
STATUS_COLORS: dict[str, str] = {
    "pending": "lightyellow",
    "active": "lightblue",
    "impl_complete": "lightsalmon",
    "validated": "lightgreen",
    "failed": "lightcoral",
}


def get_beads_data(beads_json: str = "") -> list[dict]:
    """Get beads data from JSON file or bd list --json."""
    if beads_json:
        with open(beads_json, "r") as f:
            return json.load(f)

    try:
        result = subprocess.run(
            ["bd", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass

    return []


def normalize_text(text: str) -> str:
    """Normalize text for fuzzy matching."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def match_node_to_bead(
    node_attrs: dict[str, str], beads: list[dict]
) -> dict | None:
    """Match a pipeline node to a bead by title similarity.

    Matching strategies (in order of priority):
    1. Exact bead_id match (if node already has bead_id)
    2. Title word overlap scoring
    """
    # Strategy 1: Existing bead_id
    existing_id = node_attrs.get("bead_id", "")
    if existing_id and not existing_id.startswith("AT-") and existing_id != "UNASSIGNED":
        for bead in beads:
            if bead["id"] == existing_id:
                return bead

    # Strategy 2: Title word overlap
    node_label = normalize_text(node_attrs.get("label", "").replace("\\n", " "))
    if not node_label:
        return None

    node_words = set(node_label.split())
    # Remove only true linguistic stopwords (not domain verbs)
    stopwords = {
        "the", "a", "an", "and", "or", "for", "in", "to", "of", "with",
        "is", "are", "was", "were", "be", "been", "being", "it", "its",
    }
    node_words -= stopwords

    if not node_words:
        return None

    best_match: dict | None = None
    best_score = 0.0

    for bead in beads:
        bead_title = normalize_text(bead.get("title", ""))
        bead_desc = normalize_text(bead.get("description", ""))
        bead_text = f"{bead_title} {bead_desc}"
        bead_words = set(bead_text.split()) - stopwords

        if not bead_words:
            continue

        # Jaccard-like overlap scoring
        overlap = node_words & bead_words
        if not overlap:
            continue

        score = len(overlap) / min(len(node_words), len(bead_words))

        if score > best_score:
            best_score = score
            best_match = bead

    # Require at least 30% overlap
    if best_score >= 0.3:
        return best_match

    return None


def find_node_block(content: str, node_id: str) -> tuple[int, int]:
    """Find start and end positions of a node's definition block.

    Returns (start, end) or (-1, -1) if not found.
    """
    pattern = re.compile(
        r"(?<!\w)" + re.escape(node_id) + r"\s*\[",
        re.MULTILINE,
    )

    for m in pattern.finditer(content):
        # Skip if part of an edge
        before = content[: m.start()].rstrip()
        if before.endswith("->"):
            continue

        # Find matching ]
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


def update_node_attr(content: str, node_id: str, attr: str, value: str) -> str:
    """Update or add an attribute within a node's block."""
    start, end = find_node_block(content, node_id)
    if start == -1:
        return content  # Node not found; skip silently

    block = content[start:end]

    # Try to replace existing quoted attribute
    attr_pattern = re.compile(
        r'(' + re.escape(attr) + r')\s*=\s*"[^"]*"'
    )
    m = attr_pattern.search(block)
    if m:
        new_block = block[: m.start()] + f'{attr}="{value}"' + block[m.end() :]
        return content[:start] + new_block + content[end:]

    # Try unquoted attribute
    attr_pattern_unquoted = re.compile(
        r'(' + re.escape(attr) + r')\s*=\s*(\S+)'
    )
    m = attr_pattern_unquoted.search(block)
    if m:
        new_block = block[: m.start()] + f'{attr}="{value}"' + block[m.end() :]
        return content[:start] + new_block + content[end:]

    # Attribute not found - add it before closing bracket
    bracket_pos = block.rfind("]")
    if bracket_pos == -1:
        return content

    new_attr = f'\n        {attr}="{value}"'
    new_block = block[:bracket_pos] + new_attr + "\n    " + block[bracket_pos:]
    return content[:start] + new_block + content[end:]


def annotate_pipeline(
    dot_content: str, beads: list[dict], verbose: bool = False
) -> tuple[str, list[dict]]:
    """Annotate a pipeline DOT with beads data.

    Returns (updated_dot_content, list_of_changes).
    """
    data = parse_dot(dot_content)
    changes: list[dict] = []
    updated = dot_content

    for node in data.get("nodes", []):
        node_id = node["id"]
        attrs = node["attrs"]
        handler = attrs.get("handler", "")

        # Only annotate codergen nodes
        if handler != "codergen":
            continue

        matched_bead = match_node_to_bead(attrs, beads)
        if not matched_bead:
            if verbose:
                print(
                    f"  No match: {node_id} (label={attrs.get('label', '?')})",
                    file=sys.stderr,
                )
            continue

        bead_id = matched_bead["id"]
        beads_status = matched_bead.get("status", "open")
        dot_status = BEADS_STATUS_MAP.get(beads_status, "pending")
        fillcolor = STATUS_COLORS.get(dot_status, "lightyellow")

        change = {
            "node_id": node_id,
            "bead_id": bead_id,
            "bead_title": matched_bead.get("title", ""),
            "old_bead_id": attrs.get("bead_id", ""),
            "old_status": attrs.get("status", "pending"),
            "new_status": dot_status,
        }

        # Update bead_id
        if attrs.get("bead_id") != bead_id:
            updated = update_node_attr(updated, node_id, "bead_id", bead_id)
            change["updated_bead_id"] = True
        else:
            change["updated_bead_id"] = False

        # Update status from beads
        if attrs.get("status") != dot_status:
            updated = update_node_attr(updated, node_id, "status", dot_status)
            updated = update_node_attr(updated, node_id, "fillcolor", fillcolor)
            change["updated_status"] = True
        else:
            change["updated_status"] = False

        # Update acceptance criteria if bead has them and node doesn't
        bead_ac = matched_bead.get("acceptance_criteria", "")
        if bead_ac and not attrs.get("acceptance"):
            safe_ac = bead_ac[:120].replace('"', '\\"').replace("\n", " ")
            updated = update_node_attr(updated, node_id, "acceptance", safe_ac)
            change["added_acceptance"] = True
        else:
            change["added_acceptance"] = False

        changes.append(change)

    return updated, changes


def main() -> None:
    """CLI entry point."""
    ap = argparse.ArgumentParser(
        description="Annotate Attractor pipeline.dot with beads data."
    )
    ap.add_argument("file", help="Path to pipeline .dot file")
    ap.add_argument(
        "--output",
        help="Output file path (default: overwrite input file)",
    )
    ap.add_argument(
        "--beads-json",
        help="Path to JSON file with beads data (default: runs bd list --json)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output changes as JSON",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing",
    )
    ap.add_argument(
        "--verbose",
        action="store_true",
        help="Show unmatched nodes",
    )
    args = ap.parse_args()

    # Read input DOT
    try:
        with open(args.file, "r") as f:
            dot_content = f.read()
    except FileNotFoundError:
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    # Get beads data
    beads = get_beads_data(args.beads_json or "")
    if not beads:
        print("Error: No beads data available.", file=sys.stderr)
        print(
            "Provide --beads-json <file> or ensure 'bd list --json' works.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Annotate
    updated, changes = annotate_pipeline(dot_content, beads, verbose=args.verbose)

    # Report changes
    if args.json_output:
        result = {
            "file": args.file,
            "total_changes": len(changes),
            "bead_id_updates": sum(1 for c in changes if c.get("updated_bead_id")),
            "status_updates": sum(1 for c in changes if c.get("updated_status")),
            "acceptance_adds": sum(1 for c in changes if c.get("added_acceptance")),
            "changes": changes,
        }
        print(json.dumps(result, indent=2))
    else:
        if not changes:
            print("No changes: no nodes could be matched to beads.")
        else:
            print(f"Annotated {len(changes)} node(s):")
            for c in changes:
                updates = []
                if c.get("updated_bead_id"):
                    updates.append(f"bead_id: {c['old_bead_id']} -> {c['bead_id']}")
                if c.get("updated_status"):
                    updates.append(f"status: {c['old_status']} -> {c['new_status']}")
                if c.get("added_acceptance"):
                    updates.append("acceptance: added")
                if updates:
                    print(f"  {c['node_id']}: {'; '.join(updates)}")
                else:
                    print(f"  {c['node_id']}: already up to date")

    # Write output
    if not args.dry_run and changes:
        output_path = args.output or args.file
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(updated)
        if not args.json_output:
            print(f"\nWritten: {output_path}")
    elif args.dry_run and not args.json_output:
        print("\n(dry-run: no changes written)")


if __name__ == "__main__":
    main()

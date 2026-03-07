#!/usr/bin/env python3
"""Attractor DOT Pipeline Parser.

Parses DOT files into an internal JSON representation using only Python stdlib.
Uses regex-based parsing since we control the DOT format (schema.md).

Usage:
    python3 parser.py <file.dot> [--output json]
    python3 parser.py --help
"""

import argparse
import json
import re
import sys
from typing import Any


def parse_dot(content: str) -> dict[str, Any]:
    """Parse a DOT file string into a structured dictionary.

    Returns a dict with keys:
        - graph_name: str
        - graph_attrs: dict of graph-level attributes
        - nodes: list of node dicts (id, attrs)
        - edges: list of edge dicts (src, dst, attrs)
        - defaults: dict of default node/edge attributes

    The attribute parser is generic: any key=value pair in a node or graph
    block will be extracted, including the following schema-defined attributes:

    Graph-level attributes:
        prd_ref     (str) -- PRD identifier e.g. "PRD-AUTH-001"
        promise_id  (str) -- Completion promise ID
        label       (str) -- Human-readable pipeline label

    Node attributes (codergen handler):
        prd_ref          (str) -- PRD identifier for this task (recommended)
        prd_section      (str) -- Specific section within the PRD
        solution_design  (str) -- Path to solution design document
        target_dir       (str) -- Working directory for the orchestrator/worker
        acceptance       (str) -- Acceptance criteria (recommended)
        bead_id          (str) -- Beads issue ID (required)
        worker_type      (str) -- Specialist agent type (required)
        promise_ac       (str) -- Completion promise acceptance criterion ref
    """
    result: dict[str, Any] = {
        "graph_name": "",
        "graph_attrs": {},
        "nodes": [],
        "edges": [],
        "defaults": {"node": {}, "edge": {}},
    }

    # Strip comments (// ...) but preserve strings containing //
    lines = content.split("\n")
    cleaned_lines = []
    for line in lines:
        # Remove line comments that aren't inside quotes
        cleaned = _strip_line_comment(line)
        cleaned_lines.append(cleaned)
    content_clean = "\n".join(cleaned_lines)

    # Extract graph name
    m = re.search(r'digraph\s+"([^"]+)"', content_clean)
    if not m:
        m = re.search(r"digraph\s+(\w+)", content_clean)
    if m:
        result["graph_name"] = m.group(1)

    # Extract graph-level attributes: graph [ ... ];
    _parse_graph_attrs(content_clean, result)

    # Extract default node/edge attributes: node [ ... ]; edge [ ... ];
    _parse_defaults(content_clean, result)

    # Extract node definitions and edges
    _parse_nodes_and_edges(content_clean, result)

    return result


def _strip_line_comment(line: str) -> str:
    """Strip // comments from a line, respecting quoted strings."""
    in_quote = False
    i = 0
    while i < len(line):
        if line[i] == '"' and (i == 0 or line[i - 1] != "\\"):
            in_quote = not in_quote
        elif not in_quote and i + 1 < len(line) and line[i : i + 2] == "//":
            return line[:i]
        i += 1
    return line


def _parse_attr_block(text: str) -> dict[str, str]:
    """Parse a DOT attribute block [...] into a dict.

    Handles multiline values, quoted strings with escaped characters,
    and unquoted values.
    """
    attrs: dict[str, str] = {}
    # Remove surrounding brackets if present
    text = text.strip()
    if text.startswith("["):
        text = text[1:]
    if text.endswith("]"):
        text = text[:-1]
    if text.endswith("];"):
        text = text[:-2]

    # Match key=value pairs where value can be quoted or unquoted
    # Pattern: key = "value" or key = value
    pos = 0
    while pos < len(text):
        # Skip whitespace and separators
        while pos < len(text) and text[pos] in " \t\n\r,;":
            pos += 1
        if pos >= len(text):
            break

        # Read key
        key_match = re.match(r"(\w+)\s*=\s*", text[pos:])
        if not key_match:
            pos += 1
            continue

        key = key_match.group(1)
        pos += key_match.end()

        # Read value
        if pos < len(text) and text[pos] == '"':
            # Quoted value - find matching close quote
            pos += 1  # skip opening quote
            value_chars = []
            while pos < len(text):
                if text[pos] == "\\" and pos + 1 < len(text):
                    next_ch = text[pos + 1]
                    if next_ch == '"':
                        # Escaped quote inside string
                        value_chars.append('"')
                    elif next_ch == "\\":
                        value_chars.append("\\")
                    else:
                        # Preserve DOT escape sequences like \n, \l, \r
                        value_chars.append("\\")
                        value_chars.append(next_ch)
                    pos += 2
                elif text[pos] == '"':
                    pos += 1  # skip closing quote
                    break
                else:
                    value_chars.append(text[pos])
                    pos += 1
            attrs[key] = "".join(value_chars)
        else:
            # Unquoted value - read until whitespace, comma, semicolon, or bracket
            val_match = re.match(r"([^\s,;\]]+)", text[pos:])
            if val_match:
                attrs[key] = val_match.group(1)
                pos += val_match.end()
            else:
                pos += 1

    return attrs


def _parse_graph_attrs(content: str, result: dict) -> None:
    """Extract graph-level attributes from 'graph [...]' blocks."""
    # Match graph [ ... ] blocks (potentially multiline)
    pattern = re.compile(r"\bgraph\s*\[([^\]]*)\]", re.DOTALL)
    for m in pattern.finditer(content):
        attrs = _parse_attr_block(m.group(1))
        result["graph_attrs"].update(attrs)


def _parse_defaults(content: str, result: dict) -> None:
    """Extract default node/edge attribute blocks."""
    # node [...]; or edge [...];
    for kind in ("node", "edge"):
        pattern = re.compile(
            r"(?<!\w)" + kind + r"\s*\[([^\]]*)\]", re.DOTALL
        )
        for m in pattern.finditer(content):
            # Check this isn't inside a graph block
            before = content[: m.start()].rstrip()
            if before.endswith("graph") or before.endswith("//"):
                continue
            attrs = _parse_attr_block(m.group(1))
            result["defaults"][kind].update(attrs)


def _find_body(content: str) -> str:
    """Find the body of the digraph (between the first { and last })."""
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1:
        return ""
    return content[start + 1 : end]


def _parse_nodes_and_edges(content: str, result: dict) -> None:
    """Parse node definitions and edges from the graph body."""
    body = _find_body(content)
    if not body:
        return

    seen_node_ids: set[str] = set()

    # We need to find all statements in the body.
    # Statements are separated by ; or newlines.
    # We need to handle multiline attribute blocks.

    # Strategy: find all "word [...]" node definitions and "word -> word [...]" edges
    # using a character-by-character approach to properly handle brackets.

    # First, collect all edge definitions (src -> dst [...])
    # Edge pattern can span multiple lines due to attributes
    edge_pattern = re.compile(
        r"(\w+)\s*->\s*(\w+)\s*(?:\[([^\]]*)\])?\s*;?",
        re.DOTALL,
    )
    edge_pairs: set[tuple[str, str, str]] = set()
    for m in edge_pattern.finditer(body):
        src = m.group(1)
        dst = m.group(2)
        attr_text = m.group(3) or ""
        attrs = _parse_attr_block(attr_text) if attr_text.strip() else {}
        edge_key = (src, dst, json.dumps(attrs, sort_keys=True))
        if edge_key not in edge_pairs:
            edge_pairs.add(edge_key)
            result["edges"].append({"src": src, "dst": dst, "attrs": attrs})

    # Find all node definitions: identifier [ ... ]
    # But NOT graph/node/edge/subgraph/digraph defaults
    # And NOT parts of edge definitions (handled above)
    reserved = {"graph", "node", "edge", "subgraph", "digraph"}

    # Find node blocks: identifier [ multiline attrs ]
    # Use a stateful approach to handle nested brackets
    node_pattern = re.compile(r"(\w+)\s*\[", re.DOTALL)
    for m in node_pattern.finditer(body):
        node_id = m.group(1)
        if node_id in reserved:
            continue

        # Check if this match is inside a quoted string by counting
        # unescaped quotes before the match position. Odd count = inside string.
        preceding = body[: m.start()]
        quote_count = 0
        i = 0
        while i < len(preceding):
            if preceding[i] == "\\" and i + 1 < len(preceding) and preceding[i + 1] == '"':
                i += 2  # skip escaped quote
                continue
            if preceding[i] == '"':
                quote_count += 1
            i += 1
        if quote_count % 2 == 1:
            continue  # inside a quoted string — skip this match

        # Check if this is part of an edge definition
        before = preceding.rstrip()
        if before.endswith("->"):
            continue

        # Find the matching closing bracket
        bracket_start = m.end() - 1  # position of [
        bracket_depth = 0
        pos = bracket_start
        while pos < len(body):
            if body[pos] == "[":
                bracket_depth += 1
            elif body[pos] == "]":
                bracket_depth -= 1
                if bracket_depth == 0:
                    break
            elif body[pos] == '"':
                # Skip quoted strings
                pos += 1
                while pos < len(body) and body[pos] != '"':
                    if body[pos] == "\\":
                        pos += 1
                    pos += 1
            pos += 1

        if bracket_depth != 0:
            continue

        attr_text = body[bracket_start + 1 : pos]
        attrs = _parse_attr_block(attr_text)

        if node_id not in seen_node_ids:
            seen_node_ids.add(node_id)
            result["nodes"].append({"id": node_id, "attrs": attrs})


def parse_file(filepath: str) -> dict[str, Any]:
    """Parse a DOT file from disk."""
    with open(filepath, "r") as f:
        content = f.read()
    return parse_dot(content)


def main() -> None:
    """CLI entry point."""
    ap = argparse.ArgumentParser(
        description="Parse Attractor DOT pipeline files into structured data."
    )
    ap.add_argument("file", help="Path to .dot file")
    ap.add_argument(
        "--output",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )
    ap.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indent level (default: 2)",
    )
    args = ap.parse_args()

    try:
        data = parse_file(args.file)
    except FileNotFoundError:
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error parsing {args.file}: {e}", file=sys.stderr)
        sys.exit(1)

    if args.output == "json":
        print(json.dumps(data, indent=args.indent))
    else:
        print(f"Graph: {data['graph_name']}")
        print(f"Graph attributes: {data['graph_attrs']}")
        print(f"\nNodes ({len(data['nodes'])}):")
        for node in data["nodes"]:
            handler = node["attrs"].get("handler", "?")
            status = node["attrs"].get("status", "pending")
            label = node["attrs"].get("label", node["id"]).replace("\n", " ")
            print(f"  {node['id']:30s}  handler={handler:15s}  status={status:15s}  label={label}")
        print(f"\nEdges ({len(data['edges'])}):")
        for edge in data["edges"]:
            label = edge["attrs"].get("label", "")
            cond = edge["attrs"].get("condition", "")
            extra = f"  label={label}" if label else ""
            extra += f"  condition={cond}" if cond else ""
            print(f"  {edge['src']} -> {edge['dst']}{extra}")


if __name__ == "__main__":
    main()

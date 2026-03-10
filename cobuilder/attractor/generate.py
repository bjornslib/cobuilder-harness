#!/usr/bin/env python3
"""Attractor DOT Pipeline Generator.

Generates an Attractor-compatible pipeline.dot from beads task data.
For each task bead: creates a codergen node with bead_id, worker_type, status,
paired AT hexagon nodes (technical + business validation), and conditional
diamonds. Includes start (Mdiamond) and finish (Msquare) nodes.

Usage:
    python3 generate.py --prd PRD-S3-ATTRACTOR-001 [--output pipeline.dot]
    python3 generate.py --prd PRD-S3-ATTRACTOR-001 --beads-json <file.json>
    python3 generate.py --help

Input:
    Beads data is read from `bd list --json` by default.
    Alternatively, provide a JSON file via --beads-json.

Output:
    Valid Attractor DOT to stdout or to --output file.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any


# --- Worker type inference ---

# Keyword-based heuristics for inferring worker_type from task title/description
WORKER_TYPE_KEYWORDS: dict[str, list[str]] = {
    "frontend-dev-expert": [
        "frontend", "ui", "ux", "react", "next.js", "nextjs", "component",
        "page", "form", "layout", "css", "tailwind", "zustand", "login ui",
        "dashboard", "widget",
    ],
    "backend-solutions-engineer": [
        "backend", "api", "endpoint", "database", "supabase", "fastapi",
        "python", "server", "auth", "jwt", "pydantic", "model", "schema",
        "migrate", "cli", "script", "export", "generate", "annotate",
        "wire", "integrate", "modify", "navigation", "orchestrat",
    ],
    "tdd-test-engineer": [
        "test", "e2e", "playwright", "pytest", "jest", "spec",
        "integration test", "unit test", "validation test",
    ],
    "solution-architect": [
        "design", "architecture", "document", "prd", "adr", "schema",
        "design document", "specification",
    ],
}

# Status mapping: beads status -> DOT node status
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


def infer_worker_type(title: str, description: str = "", design: str = "") -> str:
    """Infer worker_type from task title, description, and design fields.

    Uses keyword matching with priority ordering. Falls back to
    backend-solutions-engineer for ambiguous cases.
    """
    text = f"{title} {description} {design}".lower()

    scores: dict[str, int] = {wt: 0 for wt in WORKER_TYPE_KEYWORDS}
    for worker_type, keywords in WORKER_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[worker_type] += 1

    # Return highest scoring, with tie-breaking preference
    max_score = max(scores.values())
    if max_score == 0:
        return "backend-solutions-engineer"

    # Priority order for tie-breaking
    priority = [
        "solution-architect",
        "tdd-test-engineer",
        "frontend-dev-expert",
        "backend-solutions-engineer",
    ]
    for wt in priority:
        if scores[wt] == max_score:
            return wt

    return "backend-solutions-engineer"


def map_beads_status(beads_status: str) -> str:
    """Map beads status to DOT node status."""
    return BEADS_STATUS_MAP.get(beads_status, "pending")


def sanitize_node_id(text: str) -> str:
    """Convert a title or ID into a valid DOT node identifier."""
    # Remove common prefixes
    text = re.sub(r"^(claude-harness-setup-|TASK-|task-)", "", text)
    # Keep alphanumeric and underscores
    text = re.sub(r"[^a-zA-Z0-9_]", "_", text)
    # Collapse multiple underscores
    text = re.sub(r"_+", "_", text)
    # Remove leading/trailing underscores
    text = text.strip("_")
    # Ensure it starts with a letter
    if text and text[0].isdigit():
        text = "n_" + text
    return text.lower() if text else "unnamed"


def truncate_label(text: str, max_len: int = 40) -> str:
    """Truncate a label for DOT display, adding line breaks."""
    # Clean up the text
    text = text.replace('"', '\\"')
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        if len(current_line) + len(word) + 1 > max_len:
            if current_line:
                lines.append(current_line)
            current_line = word
        else:
            current_line = f"{current_line} {word}" if current_line else word
    if current_line:
        lines.append(current_line)
    return "\\n".join(lines[:3])  # Max 3 lines


def escape_dot_string(text: str) -> str:
    """Escape a string for use in DOT attribute values."""
    return text.replace('"', '\\"').replace("\n", "\\n")


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


def filter_beads_for_prd(beads: list[dict], prd_ref: str) -> list[dict]:
    """Filter beads relevant to a PRD.

    Includes tasks that:
    - Have the PRD reference in their title or description
    - Are children of an epic that references the PRD
    - Are task type (not epics themselves, unless they have actionable work)
    """
    prd_lower = prd_ref.lower()

    # Find the epic bead for this PRD
    epic_ids = set()
    for bead in beads:
        title = bead.get("title", "").lower()
        if prd_lower in title and bead.get("issue_type") == "epic":
            epic_ids.add(bead["id"])

    # Find all tasks that are children of the epic
    task_beads = []
    for bead in beads:
        if bead.get("issue_type") == "epic":
            continue

        # Check if it's a child of a matching epic
        is_child = False
        for dep in bead.get("dependencies", []):
            if dep.get("type") == "parent-child" and dep.get("depends_on_id") in epic_ids:
                is_child = True
                break

        # Check if title/description references PRD
        text = f"{bead.get('title', '')} {bead.get('description', '')}".lower()
        references_prd = prd_lower in text

        if is_child or references_prd:
            task_beads.append(bead)

    return task_beads


def generate_pipeline_dot(
    prd_ref: str,
    beads: list[dict],
    label: str = "",
    promise_id: str = "",
    target_dir: str = "",
) -> str:
    """Generate an Attractor-compatible DOT pipeline from beads data.

    Args:
        prd_ref: PRD reference identifier (e.g., PRD-S3-ATTRACTOR-001)
        beads: List of bead dicts from bd list --json
        label: Human-readable initiative label (defaults to prd_ref)
        promise_id: Completion promise ID (empty = to be populated later)
        target_dir: Target implementation repo directory (stored as graph attr)

    Returns:
        Valid DOT string.
    """
    if not label:
        label = f"Initiative: {prd_ref}"

    lines: list[str] = []

    # --- Graph envelope ---
    lines.append(f'digraph "{prd_ref}" {{')
    lines.append("    graph [")
    lines.append(f'        label="{escape_dot_string(label)}"')
    lines.append('        labelloc="t"')
    lines.append("        fontsize=16")
    lines.append('        rankdir="TB"')
    lines.append(f'        prd_ref="{prd_ref}"')
    lines.append(f'        promise_id="{promise_id}"')
    if target_dir:
        lines.append(f'        target_dir="{target_dir}"')
    lines.append("    ];")
    lines.append("")
    lines.append('    node [fontname="Helvetica" fontsize=11];')
    lines.append('    edge [fontname="Helvetica" fontsize=9];')
    lines.append("")

    # --- Stage 1: PARSE (start node) ---
    lines.append("    // ===== STAGE 1: PARSE =====")
    lines.append("")
    lines.append("    start [")
    lines.append(f'        shape=Mdiamond')
    lines.append(f'        label="PARSE\\n{prd_ref}"')
    lines.append('        handler="start"')
    lines.append('        status="validated"')
    lines.append("        style=filled")
    lines.append("        fillcolor=lightgreen")
    lines.append("    ];")
    lines.append("")

    # --- Stage 2: VALIDATE (tool node) ---
    lines.append("    // ===== STAGE 2: VALIDATE =====")
    lines.append("")
    lines.append("    validate_graph [")
    lines.append("        shape=box")
    lines.append('        label="Validate Graph\\nStructure"')
    lines.append('        handler="tool"')
    lines.append('        command="attractor validate pipeline.dot"')
    lines.append('        status="pending"')
    lines.append("        style=filled")
    lines.append("        fillcolor=lightyellow")
    lines.append("    ];")
    lines.append("")
    lines.append('    start -> validate_graph [label="parse complete"];')
    lines.append("")

    # --- Stage 3: INITIALIZE (tool node) ---
    slug = re.sub(r"[^a-z0-9]+", "-", prd_ref.lower()).strip("-")
    lines.append("    // ===== STAGE 3: INITIALIZE =====")
    lines.append("")
    lines.append("    init_env [")
    lines.append("        shape=box")
    lines.append('        label="Initialize\\nEnvironment"')
    lines.append('        handler="tool"')
    lines.append(f'        command="launchorchestrator {slug}"')
    lines.append('        status="pending"')
    lines.append("        style=filled")
    lines.append("        fillcolor=lightyellow")
    lines.append("    ];")
    lines.append("")
    lines.append('    validate_graph -> init_env [label="graph valid"];')
    lines.append("")

    # --- Stage 4: EXECUTE ---
    lines.append("    // ===== STAGE 4: EXECUTE =====")
    lines.append("")

    if not beads:
        # No beads: create a placeholder codergen node
        lines.append("    // No beads found - placeholder task")
        lines.append("    impl_placeholder [")
        lines.append("        shape=box")
        lines.append('        label="Placeholder\\nTask"')
        lines.append('        handler="codergen"')
        lines.append('        bead_id="UNASSIGNED"')
        lines.append('        worker_type="backend-solutions-engineer"')
        lines.append('        status="pending"')
        lines.append("        style=filled")
        lines.append("        fillcolor=lightyellow")
        lines.append("    ];")
        lines.append("")
        lines.append('    init_env -> impl_placeholder [label="env ready"];')
        lines.append('    impl_placeholder -> finalize [label="done"];')
        lines.append("")
    else:
        # Generate task nodes from beads
        task_nodes: list[dict[str, str]] = []  # {node_id, bead_id, ...}
        ac_counter = 0

        for bead in beads:
            bead_id = bead["id"]
            title = bead.get("title", "Untitled")
            description = bead.get("description", "")
            design = bead.get("design", "")
            acceptance = bead.get("acceptance_criteria", "")
            beads_status = bead.get("status", "open")

            node_id = f"impl_{sanitize_node_id(title)}"
            # Ensure uniqueness
            existing_ids = {t["node_id"] for t in task_nodes}
            if node_id in existing_ids:
                node_id = f"{node_id}_{sanitize_node_id(bead_id)}"

            worker_type = infer_worker_type(title, description, design)
            dot_status = map_beads_status(beads_status)
            fillcolor = STATUS_COLORS.get(dot_status, "lightyellow")
            ac_counter += 1
            promise_ac = f"AC-{ac_counter}"

            task_nodes.append({
                "node_id": node_id,
                "bead_id": bead_id,
                "title": title,
                "worker_type": worker_type,
                "status": dot_status,
                "fillcolor": fillcolor,
                "acceptance": acceptance,
                "promise_ac": promise_ac,
            })

        # Determine if we use parallel execution (2+ tasks)
        use_parallel = len(task_nodes) > 1

        if use_parallel:
            lines.append("    // --- Parallel fan-out ---")
            lines.append("")
            lines.append("    parallel_start [")
            lines.append("        shape=parallelogram")
            task_labels = [truncate_label(t["title"], 20) for t in task_nodes[:3]]
            par_label = "Parallel:\\n" + " + ".join(task_labels)
            if len(task_nodes) > 3:
                par_label += f" +{len(task_nodes) - 3} more"
            lines.append(f'        label="{par_label}"')
            lines.append('        handler="parallel"')
            lines.append('        status="pending"')
            lines.append("        style=filled")
            lines.append("        fillcolor=lightyellow")
            lines.append("    ];")
            lines.append("")
            lines.append('    init_env -> parallel_start [label="env ready"];')
            lines.append("")

        # Generate each task's nodes: impl -> tech_validation -> biz_validation -> decision
        for i, task in enumerate(task_nodes):
            nid = task["node_id"]
            bid = task["bead_id"]
            label = truncate_label(task["title"])

            lines.append(f"    // --- Task: {task['title'][:60]} ---")
            lines.append("")

            # Implementation (codergen) node
            lines.append(f"    {nid} [")
            lines.append("        shape=box")
            lines.append(f'        label="{label}"')
            lines.append('        handler="codergen"')
            lines.append(f'        bead_id="{bid}"')
            lines.append(f'        worker_type="{task["worker_type"]}"')
            if task["acceptance"]:
                lines.append(f'        acceptance="{escape_dot_string(task["acceptance"][:120])}"')
            lines.append(f'        promise_ac="{task["promise_ac"]}"')
            lines.append(f'        prd_ref="{prd_ref}"')
            lines.append(f'        status="{task["status"]}"')
            lines.append("        style=filled")
            lines.append(f'        fillcolor={task["fillcolor"]}')
            lines.append("    ];")
            lines.append("")

            # Connect from parallel_start or init_env
            if use_parallel:
                lines.append(f"    parallel_start -> {nid} [color=blue style=bold];")
            elif i == 0:
                lines.append(f'    init_env -> {nid} [label="env ready"];')
            lines.append("")

            # Technical validation hexagon
            val_tech_id = f"validate_{sanitize_node_id(task['title'])}_tech"
            lines.append(f"    {val_tech_id} [")
            lines.append("        shape=hexagon")
            short_title = truncate_label(task["title"], 15)
            lines.append(f'        label="{short_title}\\nTechnical\\nValidation"')
            lines.append('        handler="wait.human"')
            lines.append('        gate="technical"')
            lines.append('        mode="technical"')
            lines.append(f'        bead_id="AT-{sanitize_node_id(bid)}-TECH"')
            lines.append(f'        promise_ac="{task["promise_ac"]}"')
            lines.append('        status="pending"')
            lines.append("        style=filled")
            lines.append("        fillcolor=lightyellow")
            lines.append("    ];")
            lines.append("")
            lines.append(f'    {nid} -> {val_tech_id} [label="impl_complete"];')
            lines.append("")

            # Business validation hexagon
            val_biz_id = f"validate_{sanitize_node_id(task['title'])}_biz"
            lines.append(f"    {val_biz_id} [")
            lines.append("        shape=hexagon")
            lines.append(f'        label="{short_title}\\nBusiness\\nValidation"')
            lines.append('        handler="wait.human"')
            lines.append('        gate="business"')
            lines.append('        mode="business"')
            lines.append(f'        bead_id="AT-{sanitize_node_id(bid)}-BIZ"')
            lines.append(f'        promise_ac="{task["promise_ac"]}"')
            lines.append('        status="pending"')
            lines.append("        style=filled")
            lines.append("        fillcolor=lightyellow")
            lines.append("    ];")
            lines.append("")
            lines.append(f'    {val_tech_id} -> {val_biz_id} [label="tech pass"];')
            lines.append("")

            # Conditional diamond
            decision_id = f"decision_{sanitize_node_id(task['title'])}"
            lines.append(f"    {decision_id} [")
            lines.append("        shape=diamond")
            lines.append(f'        label="{short_title}\\nResult?"')
            lines.append('        handler="conditional"')
            lines.append("    ];")
            lines.append("")
            lines.append(f"    {val_biz_id} -> {decision_id};")
            lines.append("")

            # Pass edge -> join or finalize
            if use_parallel:
                lines.append(f"    {decision_id} -> join_validation [")
                lines.append('        label="pass"')
                lines.append('        condition="pass"')
                lines.append("        color=green")
                lines.append("    ];")
            # (sequential pass edge wired below)

            # Fail edge -> retry
            lines.append(f"    {decision_id} -> {nid} [")
            lines.append('        label="fail\\nretry"')
            lines.append('        condition="fail"')
            lines.append("        color=red")
            lines.append("        style=dashed")
            lines.append("    ];")
            lines.append("")

            # Store decision_id for sequential wiring
            task["decision_id"] = decision_id

        if use_parallel:
            # Parallel fan-in
            lines.append("    // --- Parallel fan-in ---")
            lines.append("")
            lines.append("    join_validation [")
            lines.append("        shape=parallelogram")
            lines.append('        label="Join:\\nAll Streams\\nValidated"')
            lines.append('        handler="parallel"')
            lines.append('        status="pending"')
            lines.append("        style=filled")
            lines.append("        fillcolor=lightyellow")
            lines.append("    ];")
            lines.append("")
            lines.append('    join_validation -> finalize [label="all pass" style=bold];')
            lines.append("")
        else:
            # Sequential: last decision -> finalize
            if task_nodes:
                last_decision = task_nodes[-1]["decision_id"]
                lines.append(f"    {last_decision} -> finalize [")
                lines.append('        label="pass"')
                lines.append('        condition="pass"')
                lines.append("        color=green")
                lines.append("    ];")
                lines.append("")

            # Sequential: chain tasks if more than one
            for i in range(len(task_nodes) - 1):
                src_decision = task_nodes[i]["decision_id"]
                dst_impl = task_nodes[i + 1]["node_id"]
                lines.append(f"    {src_decision} -> {dst_impl} [")
                lines.append('        label="pass"')
                lines.append('        condition="pass"')
                lines.append("        color=green")
                lines.append("    ];")
                lines.append("")

    # --- Stage 5: FINALIZE ---
    lines.append("    // ===== STAGE 5: FINALIZE =====")
    lines.append("")
    lines.append("    finalize [")
    lines.append("        shape=Msquare")
    lines.append('        label="FINALIZE\\nTriple Gate\\ncs-verify"')
    lines.append('        handler="exit"')
    lines.append(f'        promise_id="{promise_id}"')
    if beads:
        lines.append(f'        promise_ac="AC-{len(beads)}"')
    lines.append('        status="pending"')
    lines.append("        style=filled")
    lines.append("        fillcolor=lightyellow")
    lines.append("    ];")

    lines.append("}")
    lines.append("")

    return "\n".join(lines)


def generate_scaffold_dot(
    prd_ref: str = "PRD-SCAFFOLD",
    label: str = "",
    promise_id: str = "",
    target_dir: str = "",
) -> str:
    """Generate a minimal scaffold DOT pipeline with only standard structural nodes.

    Produces start -> validate_graph -> init_env -> finalize with no task
    nodes.  Intended as a starting skeleton to which nodes and edges can be
    added incrementally with the ``node`` and ``edge`` sub-commands.

    Args:
        prd_ref:    PRD reference identifier (default: 'PRD-SCAFFOLD').
        label:      Human-readable initiative label (default: derived from prd_ref).
        promise_id: Completion promise ID (default: empty).
        target_dir: Target implementation repo directory (stored as graph attr).

    Returns:
        Valid DOT string.
    """
    if not label:
        label = f"Initiative: {prd_ref}"

    slug = re.sub(r"[^a-z0-9]+", "-", prd_ref.lower()).strip("-")

    lines: list[str] = []

    lines.append(f'digraph "{prd_ref}" {{')
    lines.append("    graph [")
    lines.append(f'        label="{escape_dot_string(label)}"')
    lines.append('        labelloc="t"')
    lines.append("        fontsize=16")
    lines.append('        rankdir="TB"')
    lines.append(f'        prd_ref="{prd_ref}"')
    lines.append(f'        promise_id="{promise_id}"')
    if target_dir:
        lines.append(f'        target_dir="{target_dir}"')
    lines.append("    ];")
    lines.append("")
    lines.append('    node [fontname="Helvetica" fontsize=11];')
    lines.append('    edge [fontname="Helvetica" fontsize=9];')
    lines.append("")

    # Stage 1: PARSE
    lines.append("    // ===== STAGE 1: PARSE =====")
    lines.append("")
    lines.append("    start [")
    lines.append("        shape=Mdiamond")
    lines.append(f'        label="PARSE\\n{prd_ref}"')
    lines.append('        handler="start"')
    lines.append('        status="validated"')
    lines.append("        style=filled")
    lines.append("        fillcolor=lightgreen")
    lines.append("    ];")
    lines.append("")

    # Stage 2: VALIDATE
    lines.append("    // ===== STAGE 2: VALIDATE =====")
    lines.append("")
    lines.append("    validate_graph [")
    lines.append("        shape=box")
    lines.append('        label="Validate Graph\\nStructure"')
    lines.append('        handler="tool"')
    lines.append('        command="attractor validate pipeline.dot"')
    lines.append('        status="pending"')
    lines.append("        style=filled")
    lines.append("        fillcolor=lightyellow")
    lines.append("    ];")
    lines.append("")
    lines.append('    start -> validate_graph [label="parse complete"];')
    lines.append("")

    # Stage 3: INITIALIZE
    lines.append("    // ===== STAGE 3: INITIALIZE =====")
    lines.append("")
    lines.append("    init_env [")
    lines.append("        shape=box")
    lines.append('        label="Initialize\\nEnvironment"')
    lines.append('        handler="tool"')
    lines.append(f'        command="launchorchestrator {slug}"')
    lines.append('        status="pending"')
    lines.append("        style=filled")
    lines.append("        fillcolor=lightyellow")
    lines.append("    ];")
    lines.append("")
    lines.append('    validate_graph -> init_env [label="graph valid"];')
    lines.append("")

    # Stage 5: FINALIZE (Stage 4 EXECUTE left empty for manual population)
    lines.append("    // ===== STAGE 5: FINALIZE =====")
    lines.append("    // Stage 4 EXECUTE: add task nodes with 'cli.py node <file> add ...'")
    lines.append("")
    lines.append("    finalize [")
    lines.append("        shape=Msquare")
    lines.append('        label="FINALIZE\\nTriple Gate\\ncs-verify"')
    lines.append('        handler="exit"')
    lines.append(f'        promise_id="{promise_id}"')
    lines.append('        status="pending"')
    lines.append("        style=filled")
    lines.append("        fillcolor=lightyellow")
    lines.append("    ];")
    lines.append("")
    lines.append('    init_env -> finalize [label="ready"];')
    lines.append("")

    lines.append("}")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    """CLI entry point."""
    ap = argparse.ArgumentParser(
        description="Generate Attractor-compatible pipeline.dot from beads task data."
    )
    ap.add_argument(
        "--prd",
        default="",
        help="PRD reference identifier (e.g., PRD-S3-ATTRACTOR-001). Required unless --scaffold.",
    )
    ap.add_argument(
        "--scaffold",
        action="store_true",
        help=(
            "Generate a minimal skeleton pipeline with only structural nodes "
            "(start, validate_graph, init_env, finalize). No beads data required."
        ),
    )
    ap.add_argument(
        "--output",
        help="Output file path (default: stdout)",
    )
    ap.add_argument(
        "--beads-json",
        help="Path to JSON file with beads data (default: runs bd list --json)",
    )
    ap.add_argument(
        "--label",
        help="Human-readable initiative label (default: derived from PRD ref)",
    )
    ap.add_argument(
        "--promise-id",
        default="",
        help="Completion promise ID (default: empty, populated by init-promise)",
    )
    ap.add_argument(
        "--target-dir",
        default="",
        dest="target_dir",
        help="Target implementation repo directory (stored as graph attr in DOT)",
    )
    ap.add_argument(
        "--filter-prd",
        action="store_true",
        default=True,
        help="Filter beads to only those related to the PRD (default: true)",
    )
    ap.add_argument(
        "--no-filter",
        action="store_true",
        help="Include all beads without filtering",
    )
    args = ap.parse_args()

    # --- Scaffold mode: bypass beads entirely ---
    if args.scaffold:
        prd_ref = args.prd or "PRD-SCAFFOLD"
        dot = generate_scaffold_dot(
            prd_ref=prd_ref,
            label=args.label or "",
            promise_id=args.promise_id,
            target_dir=args.target_dir,
        )
        if args.output:
            out_dir = os.path.dirname(os.path.abspath(args.output))
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            with open(args.output, "w") as f:
                f.write(dot)
            print(f"Scaffold generated: {args.output}", file=sys.stderr)
            print(f"PRD: {prd_ref}", file=sys.stderr)
        else:
            print(dot)
        return

    # --- Full generation mode ---
    if not args.prd:
        ap.error("--prd is required unless --scaffold is specified")

    # Get beads data
    beads = get_beads_data(args.beads_json or "")

    if not beads:
        print(
            "Warning: No beads data available. Generating pipeline with placeholder.",
            file=sys.stderr,
        )

    # Filter beads for PRD
    if beads and not args.no_filter:
        filtered = filter_beads_for_prd(beads, args.prd)
        if filtered:
            beads = filtered
        else:
            print(
                f"Warning: No beads matched PRD '{args.prd}'. "
                f"Using all {len(beads)} beads.",
                file=sys.stderr,
            )

    # Filter out epics (only tasks)
    beads = [b for b in beads if b.get("issue_type") != "epic"]

    # Generate DOT
    dot = generate_pipeline_dot(
        prd_ref=args.prd,
        beads=beads,
        label=args.label or "",
        promise_id=args.promise_id,
        target_dir=args.target_dir,
    )

    # Output
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w") as f:
            f.write(dot)
        print(f"Generated: {args.output}", file=sys.stderr)
        print(f"Tasks: {len(beads)}", file=sys.stderr)
        print(f"PRD: {args.prd}", file=sys.stderr)
    else:
        print(dot)


if __name__ == "__main__":
    main()

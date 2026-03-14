#!/usr/bin/env python3
"""Attractor Pipeline Lifecycle Dashboard.

Produces a combined progress view for an Attractor .dot pipeline, showing:
  - Pipeline stage (Definition / Implementation / Validation / Finalized)
  - Node status distribution (pending / active / impl_complete / validated / failed)
  - Per-node detail table with worker assignment and time in current state
  - Completion promise progress (N/M acceptance criteria met)
  - Estimated completion (based on average node duration when checkpoint available)

Usage:
    python3 dashboard.py <file.dot> [--output json] [--checkpoint <path>]
    python3 dashboard.py --help
"""

import argparse
import datetime
import json
import os
import sys

# Ensure sibling imports work

from cobuilder.engine.dispatch_parser import parse_file


# ---------------------------------------------------------------------------
# Stage determination
# ---------------------------------------------------------------------------

# Status sets for stage classification
_ACTIVE_STATUSES = {"active", "impl_complete", "failed"}
_VALIDATED_STATUS = "validated"
_FINALIZE_HANDLERS = {"finalize"}
_FINALIZE_SHAPES = {"Msquare"}
_CODERGEN_HANDLERS = {"codergen"}
_VALIDATION_HANDLERS = {"wait.human"}
_DECISION_HANDLERS = {"conditional"}
_START_HANDLERS = {"start"}

STAGES = ["Definition", "Implementation", "Validation", "Finalized"]


def determine_pipeline_stage(nodes: list[dict]) -> str:
    """Determine the overall pipeline lifecycle stage.

    Stage logic (in priority order):
    - FINALIZED: all hexagon (wait.human) nodes are validated, OR the
      finalize (Msquare) node is validated.
    - VALIDATION: at least one hexagon node is active or validated,
      or all codergen nodes are impl_complete/validated.
    - IMPLEMENTATION: at least one codergen node is active or impl_complete.
    - DEFINITION: all nodes are pending (only start may be validated).
    """
    codergen_nodes = []
    hexagon_nodes = []
    finalize_nodes = []

    for node in nodes:
        attrs = node["attrs"]
        handler = attrs.get("handler", "")
        shape = attrs.get("shape", "")
        if handler in _CODERGEN_HANDLERS:
            codergen_nodes.append(attrs)
        elif handler in _VALIDATION_HANDLERS:
            hexagon_nodes.append(attrs)
        elif handler in _FINALIZE_HANDLERS or shape in _FINALIZE_SHAPES:
            finalize_nodes.append(attrs)

    # Check FINALIZED
    if finalize_nodes:
        if any(a.get("status", "pending") == _VALIDATED_STATUS for a in finalize_nodes):
            return "Finalized"
    if hexagon_nodes and all(
        a.get("status", "pending") == _VALIDATED_STATUS for a in hexagon_nodes
    ):
        return "Finalized"

    # Check VALIDATION
    if hexagon_nodes:
        hexagon_statuses = {a.get("status", "pending") for a in hexagon_nodes}
        if _ACTIVE_STATUSES & hexagon_statuses or _VALIDATED_STATUS in hexagon_statuses:
            return "Validation"
    if codergen_nodes and all(
        a.get("status", "pending") in ("impl_complete", "validated")
        for a in codergen_nodes
    ):
        if codergen_nodes:
            return "Validation"

    # Check IMPLEMENTATION
    if codergen_nodes:
        codergen_statuses = {a.get("status", "pending") for a in codergen_nodes}
        if _ACTIVE_STATUSES & codergen_statuses:
            return "Implementation"

    return "Definition"


# ---------------------------------------------------------------------------
# Status distribution
# ---------------------------------------------------------------------------

def compute_status_distribution(nodes: list[dict]) -> dict[str, int]:
    """Count nodes by their status value."""
    counts: dict[str, int] = {}
    for node in nodes:
        status = node["attrs"].get("status", "pending")
        counts[status] = counts.get(status, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Promise progress
# ---------------------------------------------------------------------------

def compute_promise_progress(nodes: list[dict]) -> dict:
    """Compute completion promise progress from hexagon (wait.human) nodes.

    Returns:
        {
            "validated": N,
            "total": M,
            "percentage": float,
            "status_label": "N/M",
        }
    """
    hexagons = [
        n for n in nodes if n["attrs"].get("handler") == "wait.human"
    ]
    total = len(hexagons)
    validated = sum(
        1 for n in hexagons if n["attrs"].get("status", "pending") == "validated"
    )
    pct = (validated / total * 100) if total > 0 else 0.0
    return {
        "validated": validated,
        "total": total,
        "percentage": round(pct, 1),
        "status_label": f"{validated}/{total}",
    }


# ---------------------------------------------------------------------------
# Time-in-state estimation from checkpoint
# ---------------------------------------------------------------------------

def load_checkpoint(checkpoint_path: str) -> dict:
    """Load a checkpoint JSON file, returning empty dict on failure."""
    if not checkpoint_path or not os.path.exists(checkpoint_path):
        return {}
    try:
        with open(checkpoint_path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _build_state_durations(checkpoint: dict) -> dict[str, float]:
    """Compute average validated-node duration from checkpoint history.

    Returns a mapping {node_id: duration_seconds} where available.
    """
    # Checkpoint saves timestamp per save; we don't have per-transition
    # timestamps in the DOT format. Return empty — durations are N/A unless
    # richer data becomes available.
    return {}


def compute_estimated_completion(
    nodes: list[dict], checkpoint: dict
) -> str:
    """Estimate completion time based on average validated-node duration.

    Without per-transition timestamps this is N/A. If checkpoint includes
    a "completed_at" and "started_at" we could compute it, but for now
    return a human-readable placeholder.
    """
    # Future: use checkpoint history deltas across saves
    if not checkpoint:
        return "N/A (no checkpoint data)"

    # Count pending / active nodes
    pending_count = sum(
        1 for n in nodes
        if n["attrs"].get("status", "pending") in ("pending", "active")
    )
    if pending_count == 0:
        return "Complete"

    return f"N/A ({pending_count} nodes remaining)"


# ---------------------------------------------------------------------------
# Node detail table
# ---------------------------------------------------------------------------

def build_node_table(nodes: list[dict]) -> list[dict]:
    """Build a per-node detail table for dashboard display."""
    rows = []
    for node in nodes:
        attrs = node["attrs"]
        rows.append({
            "node_id": node["id"],
            "handler": attrs.get("handler", ""),
            "status": attrs.get("status", "pending"),
            "worker_type": attrs.get("worker_type", ""),
            "bead_id": attrs.get("bead_id", ""),
            "label": attrs.get("label", "").replace("\\n", " ").replace("\n", " "),
        })
    return rows


def format_node_table(rows: list[dict]) -> str:
    """Format node rows into an aligned text table."""
    if not rows:
        return "(no nodes)"

    headers = {
        "node_id": "Node ID",
        "handler": "Handler",
        "status": "Status",
        "worker_type": "Worker Type",
        "bead_id": "Bead ID",
        "label": "Label",
    }
    cols = ["node_id", "handler", "status", "worker_type", "bead_id", "label"]

    widths: dict[str, int] = {}
    for col in cols:
        widths[col] = max(
            len(headers[col]),
            max((len(str(row.get(col, ""))) for row in rows), default=0),
        )

    header_line = "  ".join(headers[col].ljust(widths[col]) for col in cols)
    sep_line = "  ".join("-" * widths[col] for col in cols)
    data_lines = [
        "  ".join(str(row.get(col, "")).ljust(widths[col]) for col in cols)
        for row in rows
    ]
    return "\n".join([header_line, sep_line] + data_lines)


# ---------------------------------------------------------------------------
# High-level dashboard computation
# ---------------------------------------------------------------------------

def compute_dashboard(data: dict, checkpoint: dict = None) -> dict:
    """Compute the full dashboard data from parsed DOT data.

    Returns a dict suitable for JSON serialisation or text rendering.
    """
    checkpoint = checkpoint or {}
    nodes = data.get("nodes", [])
    graph_attrs = data.get("graph_attrs", {})

    stage = determine_pipeline_stage(nodes)
    status_dist = compute_status_distribution(nodes)
    promise_progress = compute_promise_progress(nodes)
    estimated_completion = compute_estimated_completion(nodes, checkpoint)
    node_table = build_node_table(nodes)

    # Summary worker-type distribution
    worker_counts: dict[str, int] = {}
    for node in nodes:
        wt = node["attrs"].get("worker_type", "")
        if wt:
            worker_counts[wt] = worker_counts.get(wt, 0) + 1

    return {
        "graph_name": data.get("graph_name", ""),
        "prd_ref": graph_attrs.get("prd_ref", ""),
        "pipeline_stage": stage,
        "status_distribution": status_dist,
        "total_nodes": len(nodes),
        "promise_progress": promise_progress,
        "estimated_completion": estimated_completion,
        "worker_type_distribution": worker_counts,
        "nodes": node_table,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------

_STATUS_SYMBOLS = {
    "pending": "○",
    "active": "►",
    "impl_complete": "◑",
    "validated": "✓",
    "failed": "✗",
}

_STAGE_BANNER = {
    "Definition": "DEFINITION  (Stage 1 — building .dot from PRD)",
    "Implementation": "IMPLEMENTATION  (Stage 2 — orchestrators executing nodes)",
    "Validation": "VALIDATION  (Stage 3 — guardian scoring against acceptance criteria)",
    "Finalized": "FINALIZED  ✓  (All nodes validated — pipeline complete)",
}


def render_dashboard(dashboard: dict) -> str:
    """Render the dashboard as a human-readable string."""
    lines: list[str] = []

    graph = dashboard["graph_name"] or "unknown"
    prd = dashboard["prd_ref"] or ""
    stage = dashboard["pipeline_stage"]
    generated = dashboard["generated_at"]

    # ---- Header ----
    lines.append("=" * 70)
    lines.append(f"  ATTRACTOR PIPELINE DASHBOARD")
    lines.append(f"  Pipeline : {graph}")
    if prd:
        lines.append(f"  PRD      : {prd}")
    lines.append(f"  Generated: {generated}")
    lines.append("=" * 70)
    lines.append("")

    # ---- Pipeline Stage ----
    lines.append(f"STAGE: {_STAGE_BANNER.get(stage, stage)}")
    lines.append("")

    # ---- Status Distribution ----
    dist = dashboard["status_distribution"]
    total = dashboard["total_nodes"]
    lines.append(f"NODE STATUS DISTRIBUTION  (total: {total})")
    lines.append("-" * 40)
    all_statuses = ["pending", "active", "impl_complete", "validated", "failed"]
    for s in all_statuses:
        count = dist.get(s, 0)
        sym = _STATUS_SYMBOLS.get(s, " ")
        bar_width = int(count / total * 20) if total > 0 else 0
        bar = "█" * bar_width
        lines.append(f"  {sym} {s:<15s}  {count:>3d}  {bar}")
    # Any non-standard statuses
    for s, count in sorted(dist.items()):
        if s not in all_statuses:
            lines.append(f"  ? {s:<15s}  {count:>3d}")
    lines.append("")

    # ---- Promise Progress ----
    prog = dashboard["promise_progress"]
    lines.append(
        f"COMPLETION PROMISE  ({prog['status_label']} validation gates met"
        f"  —  {prog['percentage']}%)"
    )
    if prog["total"] > 0:
        filled = int(prog["percentage"] / 100 * 30)
        bar = "█" * filled + "░" * (30 - filled)
        lines.append(f"  [{bar}] {prog['percentage']}%")
    lines.append("")

    # ---- Worker Type Distribution ----
    wt_dist = dashboard.get("worker_type_distribution", {})
    if wt_dist:
        lines.append("WORKER TYPE DISTRIBUTION")
        lines.append("-" * 40)
        for wt, count in sorted(wt_dist.items()):
            lines.append(f"  {wt:<35s}  {count:>3d} nodes")
        lines.append("")

    # ---- Estimated Completion ----
    lines.append(f"ESTIMATED COMPLETION: {dashboard['estimated_completion']}")
    lines.append("")

    # ---- Node Detail Table ----
    lines.append("NODE DETAIL")
    lines.append("-" * 70)
    lines.append(format_node_table(dashboard["nodes"]))
    lines.append("")
    lines.append("=" * 70)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point."""
    ap = argparse.ArgumentParser(
        description="Display unified lifecycle dashboard for an Attractor .dot pipeline."
    )
    ap.add_argument("file", help="Path to pipeline .dot file")
    ap.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format: text (default) or json",
    )
    ap.add_argument(
        "--checkpoint",
        default="",
        metavar="PATH",
        help="Optional path to checkpoint .json for time-in-state estimates",
    )
    args = ap.parse_args()

    # Parse DOT file
    try:
        data = parse_file(args.file)
    except FileNotFoundError:
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error parsing {args.file}: {e}", file=sys.stderr)
        sys.exit(1)

    # Load optional checkpoint
    checkpoint = load_checkpoint(args.checkpoint)

    # Compute dashboard
    dashboard = compute_dashboard(data, checkpoint)

    # Render
    if args.output == "json":
        print(json.dumps(dashboard, indent=2))
    else:
        print(render_dashboard(dashboard))


if __name__ == "__main__":
    main()

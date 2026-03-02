#!/usr/bin/env python3
"""Attractor DOT Pipeline Generator — RepoMap-native edition.

Generates an Attractor-compatible pipeline.dot from RepoMap baseline data
(F2.1/F2.2/F2.4/F2.6) or from beads task data (legacy fallback).

Usage:
    # RepoMap-native mode (preferred):
    python3 generate.py --prd PRD-S3-ATTRACTOR-001 --repo-name myrepo
    # Legacy beads-only mode:
    python3 generate.py --prd PRD-S3-ATTRACTOR-001 [--beads-json file.json]
    python3 generate.py --scaffold [--prd PRD-...]
    python3 generate.py --help

Input:
    Beads data is read from `bd list --json` by default for cross-referencing.
    RepoMap baseline is read from .repomap/baselines/{repo_name}/baseline.json.

Output:
    Valid Attractor DOT to stdout or to --output file.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import anthropic

import cobuilder.bridge as bridge

logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# F2.1 — ensure_baseline
# ---------------------------------------------------------------------------


def ensure_baseline(repo_name: str, project_root: str | Path) -> Path:
    """Ensure a baseline exists for repo_name, auto-initializing if missing.

    Checks if ``.repomap/baselines/{repo_name}/baseline.json`` exists inside
    *project_root*.  If the file is absent, logs a progress message, calls
    ``bridge.init_repo()`` followed by ``bridge.sync_baseline()`` to create it.

    Args:
        repo_name: Short identifier for the repository (e.g. ``"myrepo"``).
        project_root: Root of the project that owns ``.repomap/``.

    Returns:
        :class:`pathlib.Path` pointing to the baseline.json file.
    """
    project_root = Path(project_root)
    baseline_path = project_root / ".repomap" / "baselines" / repo_name / "baseline.json"

    if not baseline_path.exists():
        print(
            f"Running repomap init for {repo_name}... (~2-3 min)",
            file=sys.stderr,
        )
        logger.info("Auto-initialising baseline for '%s'", repo_name)
        bridge.init_repo(repo_name, project_root, project_root=project_root, force=True)
        bridge.sync_baseline(repo_name, project_root=project_root)

    return baseline_path


# ---------------------------------------------------------------------------
# F2.2 — collect_repomap_nodes
# ---------------------------------------------------------------------------


def collect_repomap_nodes(repo_name: str, project_root: str | Path) -> list[dict]:
    """Load baseline.json and extract node dicts for MODIFIED/NEW nodes.

    Reads the RPGGraph JSON serialized by :class:`~cobuilder.repomap.serena.baseline.BaselineManager`
    from ``.repomap/baselines/{repo_name}/baseline.json``.  Filters to nodes
    whose ``delta_status`` (stored in ``node.metadata``) is ``"MODIFIED"`` or
    ``"NEW"``.  If no nodes have a ``delta_status``, all nodes are returned
    (useful for a fresh/uncompared baseline).

    Args:
        repo_name: Short identifier for the repository.
        project_root: Root of the project that owns ``.repomap/``.

    Returns:
        List of dicts with keys:
        ``node_id``, ``title``, ``file_path``, ``delta_status``,
        ``module``, ``interfaces``.
    """
    baseline_path = ensure_baseline(repo_name, project_root)

    json_str = baseline_path.read_text(encoding="utf-8")
    data = json.loads(json_str)

    result: list[dict] = []
    for node_id, node_data in data.get("nodes", {}).items():
        metadata: dict[str, Any] = node_data.get("metadata") or {}
        delta_status: str = metadata.get("delta_status", "")

        # Module: top-level folder segment from folder_path
        folder_path: str = node_data.get("folder_path") or ""
        module = folder_path.split("/")[0] if folder_path else ""

        # Interfaces: prefer metadata list, fall back to interface_type enum value
        raw_interfaces = metadata.get("interfaces")
        if raw_interfaces and isinstance(raw_interfaces, list):
            interfaces: list[str] = [str(i) for i in raw_interfaces]
        else:
            interface_type = node_data.get("interface_type")
            interfaces = [str(interface_type)] if interface_type else []

        result.append({
            "node_id": node_id,
            "title": node_data.get("name") or "",
            "file_path": node_data.get("file_path") or "",
            "delta_status": delta_status,
            "module": module,
            "interfaces": interfaces,
        })

    # Filter to changed nodes; fall back to all if none are delta-tagged
    filtered = [n for n in result if n["delta_status"] in ("MODIFIED", "NEW")]
    return filtered if filtered else result


# ---------------------------------------------------------------------------
# F2.3 — filter_nodes_by_sd_relevance
# ---------------------------------------------------------------------------


def filter_nodes_by_sd_relevance(
    nodes: list[dict],
    sd_content: str,
    model: str = "claude-haiku-4-5-20251001",
    batch_size: int = 300,
) -> list[dict]:
    """Filter repomap nodes to those relevant to the Solution Design using LLM.

    Processes nodes in batches and uses an LLM to identify which nodes would
    be created or modified when implementing the solution described in the SD.

    On failure, returns an EMPTY list — callers must handle the empty case.
    The previous behavior of returning all nodes on failure caused downstream
    bottlenecks (2900+ nodes hitting LLM enrichment).

    Args:
        nodes: List of node dicts from :func:`collect_repomap_nodes`.
        sd_content: Full text of the Solution Design document.
        model: Claude model to use (defaults to claude-haiku for speed/cost).
        batch_size: Maximum number of nodes per LLM batch call.

    Returns:
        Filtered list of nodes relevant to the SD, or empty list on failure.
    """
    if not nodes:
        return nodes
    if not sd_content.strip():
        logger.warning("filter_nodes_by_sd_relevance: no SD content provided, skipping filter")
        return nodes

    # ── Phase A: Fast keyword pre-filter ──────────────────────────────
    # Extract file paths mentioned in the SD (Section 6: File Scope)
    # and filter nodes to those whose file_path contains any SD-mentioned path segment.
    # This reduces 2900+ nodes to ~50-100 before sending to LLM.
    sd_lower = sd_content.lower()
    # Extract likely file paths from SD: patterns like `word/word.ext` or `word/word/word.ext`
    # Include bracket patterns like [task_id] common in Next.js dynamic routes
    path_fragments = set()
    segment = r"[\w\-\[\].]+"  # Allow brackets and dots in path segments
    for m in re.finditer(
        rf"{segment}/{segment}(?:/{segment})*\.(?:tsx?|jsx?|py|css|json|yaml|md)",
        sd_content,
    ):
        # Take the last 2-3 path segments as a matching key
        parts = m.group().split("/")
        path_fragments.add("/".join(parts[-2:]))  # e.g. "[task_id]/page.tsx"
        if len(parts) >= 3:
            path_fragments.add("/".join(parts[-3:]))  # e.g. "verify-check/[task_id]/page.tsx"

    import sys
    print(f"[DEBUG] path_fragments ({len(path_fragments)}): {sorted(path_fragments)[:10]}", file=sys.stderr)

    if path_fragments:
        pre_filtered = [
            n for n in nodes
            if any(frag in (n.get("file_path") or "") for frag in path_fragments)
        ]
        print(f"[DEBUG] pre_filtered: {len(pre_filtered)} from {len(nodes)}", file=sys.stderr)
        if pre_filtered:
            logger.info(
                "filter_nodes_by_sd_relevance: keyword pre-filter %d → %d nodes (fragments: %s)",
                len(nodes), len(pre_filtered), list(path_fragments)[:10],
            )
            nodes = pre_filtered
        else:
            logger.info(
                "filter_nodes_by_sd_relevance: keyword pre-filter matched 0 nodes from %d; "
                "falling through to LLM filter on all nodes",
                len(nodes),
            )

    # ── Phase B: LLM relevance filter ─────────────────────────────────
    # If pre-filter already reduced to a small set (<= 50), skip LLM and return directly
    if path_fragments and len(nodes) <= 50:
        logger.info(
            "filter_nodes_by_sd_relevance: pre-filter yielded %d nodes (<= 50), skipping LLM phase",
            len(nodes),
        )
        return nodes

    # Truncate SD to avoid excessive token usage; first ~4000 chars contain the key context
    sd_excerpt = sd_content[:4000]

    try:
        client = anthropic.Anthropic()
        relevant: list[dict] = []

        num_batches = (len(nodes) + batch_size - 1) // batch_size
        for batch_idx in range(num_batches):
            batch_start = batch_idx * batch_size
            batch = nodes[batch_start : batch_start + batch_size]

            # Build compact node listing — one line per node
            node_lines = "\n".join(
                f"{i}: {(node.get('title') or '')[:60]} | {(node.get('file_path') or '')[:80]}"
                for i, node in enumerate(batch)
            )

            prompt = (
                f"## Solution Design (excerpt)\n{sd_excerpt}\n\n"
                f"## Candidate Code Nodes (batch {batch_idx + 1}/{num_batches})\n"
                f"Format per line: INDEX: title | file_path\n"
                f"{node_lines}\n\n"
                f"## Task\n"
                f"Select ONLY the nodes that will need to be CREATED or MODIFIED "
                f"to implement the solution described above.\n"
                f"Return a JSON array of INDEX integers only. Example: [0, 3, 7]\n"
                f"Return ONLY the JSON array, nothing else.\n"
                f"If no nodes in this batch are relevant, return: []"
            )

            msg = client.messages.create(
                model=model,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            response_text = msg.content[0].text.strip()

            # Strip markdown code fences if present (```json ... ``` or ``` ... ```)
            cleaned = re.sub(r"^```(?:json)?\s*\n?", "", response_text)
            cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()

            # Extract JSON array from response — allow negative indices too
            match = re.search(r"\[[\d,\s\-]*\]", cleaned)
            if not match:
                logger.warning(
                    "filter_nodes_by_sd_relevance: could not parse batch %d response: %r",
                    batch_idx,
                    response_text[:200],
                )
                continue

            indexes = json.loads(match.group())
            for idx in indexes:
                if isinstance(idx, int) and 0 <= idx < len(batch):
                    relevant.append(batch[idx])

        if not relevant:
            logger.warning(
                "filter_nodes_by_sd_relevance: LLM returned no relevant nodes "
                "from %d candidates; returning EMPTY list (not all nodes)",
                len(nodes),
            )
            return []

        logger.info(
            "filter_nodes_by_sd_relevance: %d → %d nodes after SD relevance filter",
            len(nodes),
            len(relevant),
        )
        return relevant

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "filter_nodes_by_sd_relevance failed (%s); returning EMPTY list",
            exc,
        )
        return []


# ---------------------------------------------------------------------------
# F2.4 — cross_reference_beads
# ---------------------------------------------------------------------------


def cross_reference_beads(repomap_nodes: list[dict], prd_ref: str) -> list[dict]:
    """Match repomap nodes with beads for priority/ID enrichment.

    Runs ``bd list --json`` to obtain all beads.  For each *repomap_node*,
    tries to find a matching bead using two heuristics:

    1. **Word-overlap**: lowercase token intersection ≥ 50% of the smaller set
       (between node title and bead title).
    2. **Path mention**: the node's ``file_path`` appears literally in the bead
       description.

    Matched nodes gain ``bead_id`` and ``priority`` keys.
    Unmatched nodes get ``bead_id=None`` and ``priority=None``.

    Args:
        repomap_nodes: List of node dicts from :func:`collect_repomap_nodes`.
        prd_ref: PRD reference string (reserved for future server-side filtering).

    Returns:
        Enriched copy of *repomap_nodes* with ``bead_id`` and ``priority`` added.
    """
    beads = get_beads_data()

    enriched: list[dict] = []
    for node in repomap_nodes:
        node = dict(node)  # shallow copy — do not mutate caller's list

        node_words = set(re.sub(r"[^a-z0-9 ]", " ", (node.get("title") or "").lower()).split())
        node_file = (node.get("file_path") or "").lower()

        best_bead: dict | None = None
        best_overlap = 0.0

        for bead in beads:
            bead_words = set(
                re.sub(r"[^a-z0-9 ]", " ", (bead.get("title") or "").lower()).split()
            )
            bead_desc = (bead.get("description") or "").lower()

            # Word-overlap ratio relative to the smaller token set
            common = node_words & bead_words
            smaller = min(len(node_words), len(bead_words))
            overlap = len(common) / smaller if smaller > 0 else 0.0

            file_match = bool(node_file and node_file in bead_desc)

            if overlap >= 0.5 or file_match:
                if overlap > best_overlap or (file_match and best_bead is None):
                    best_bead = bead
                    best_overlap = overlap

        if best_bead is not None:
            node["bead_id"] = best_bead["id"]
            node["priority"] = best_bead.get("priority")
        else:
            node["bead_id"] = None
            node["priority"] = None

        enriched.append(node)

    return enriched


# ---------------------------------------------------------------------------
# Utility helpers (unchanged from original)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# F2.6 — generate_pipeline_dot (RepoMap-native signature)
# ---------------------------------------------------------------------------


def generate_pipeline_dot(
    prd_ref: str,
    nodes: list[dict],
    label: str = "",
    promise_id: str = "",
    target_dir: str = "",
    solution_design: str = "",
) -> str:
    """Generate an Attractor-compatible DOT pipeline from enriched RepoMap nodes.

    Replaces the legacy beads-based signature.  Each entry in *nodes* is a
    dict produced by :func:`collect_repomap_nodes` (optionally enriched by
    :func:`cross_reference_beads`).

    Additional DOT attributes rendered on codergen nodes (when present in the
    node dict):

    - ``file_path``       — primary source file
    - ``delta_status``    — ``MODIFIED`` / ``NEW``
    - ``interfaces``      — comma-joined interface names
    - ``change_summary``  — brief description of the change
    - ``worker_type``     — specialist agent type
    - ``solution_design`` — path to the solution design document (graph-level)

    The overall pipeline structure (scaffold stages, validation hexagons,
    conditional diamonds, finalize node) is preserved.

    Args:
        prd_ref: PRD reference identifier (e.g. ``PRD-S3-ATTRACTOR-001``).
        nodes: List of enriched RepoMap node dicts.
        label: Human-readable initiative label (defaults to *prd_ref*).
        promise_id: Completion promise ID (empty = populated by init-promise).
        target_dir: Target implementation repo directory (stored as graph attr).
        solution_design: Path to the solution design document.

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
    if solution_design:
        lines.append(f'        solution_design="{escape_dot_string(solution_design)}"')
    lines.append("    ];")
    lines.append("")
    lines.append('    node [fontname="Helvetica" fontsize=11];')
    lines.append('    edge [fontname="Helvetica" fontsize=9];')
    lines.append("")

    # --- Stage 1: PARSE (start node) ---
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

    if not nodes:
        # No nodes: create a placeholder codergen node
        lines.append("    // No nodes found - placeholder task")
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
        # Generate task nodes from enriched RepoMap nodes
        task_nodes: list[dict[str, Any]] = []
        ac_counter = 0

        for node in nodes:
            node_id_raw = node.get("node_id", "")
            title = node.get("title", "Untitled")

            # Stable DOT identifier derived from title (or fallback to module-derived suffix)
            dot_node_id = f"impl_{sanitize_node_id(title)}"
            existing_ids = {t["dot_node_id"] for t in task_nodes}
            if dot_node_id in existing_ids:
                module_raw = node.get("module", "") or node.get("folder_path", "") or node_id_raw[-6:]
                module_slug = sanitize_node_id(module_raw.split("/")[0])
                dot_node_id = f"impl_{sanitize_node_id(title)}_{module_slug}"
                if dot_node_id in existing_ids:
                    counter = sum(1 for nid in existing_ids if nid.startswith(f"impl_{sanitize_node_id(title)}"))
                    dot_node_id = f"impl_{sanitize_node_id(title)}_{module_slug}_{counter}"

            # Determine worker_type: prefer explicit field, else infer from title
            worker_type = node.get("worker_type") or infer_worker_type(title)

            bead_id = node.get("bead_id") or "UNASSIGNED"
            dot_status = "pending"
            fillcolor = STATUS_COLORS.get(dot_status, "lightyellow")

            ac_counter += 1
            promise_ac = f"AC-{ac_counter}"

            task_nodes.append({
                "dot_node_id": dot_node_id,
                "node_id": node_id_raw,
                "bead_id": bead_id,
                "title": title,
                "worker_type": worker_type,
                "status": dot_status,
                "fillcolor": fillcolor,
                "promise_ac": promise_ac,
                # Enriched RepoMap fields
                "file_path": node.get("file_path") or "",
                "delta_status": node.get("delta_status") or "",
                "interfaces": node.get("interfaces") or [],
                "change_summary": node.get("change_summary") or "",
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
            nid = task["dot_node_id"]
            bid = task["bead_id"]
            node_label = truncate_label(task["title"])

            lines.append(f"    // --- Task: {task['title'][:60]} ---")
            lines.append("")

            # Implementation (codergen) node
            lines.append(f"    {nid} [")
            lines.append("        shape=box")
            lines.append(f'        label="{node_label}"')
            lines.append('        handler="codergen"')
            lines.append(f'        bead_id="{bid}"')
            lines.append(f'        worker_type="{task["worker_type"]}"')
            lines.append(f'        promise_ac="{task["promise_ac"]}"')
            lines.append(f'        prd_ref="{prd_ref}"')
            lines.append(f'        status="{task["status"]}"')

            # F2.6 enriched attributes — only emit when non-empty
            if task["file_path"]:
                lines.append(f'        file_path="{escape_dot_string(task["file_path"])}"')
            if task["delta_status"]:
                lines.append(f'        delta_status="{task["delta_status"]}"')
            if task["interfaces"]:
                ifaces_str = escape_dot_string(", ".join(task["interfaces"]))
                lines.append(f'        interfaces="{ifaces_str}"')
            if task["change_summary"]:
                lines.append(
                    f'        change_summary="{escape_dot_string(task["change_summary"][:120])}"'
                )
            feature_id = task.get("feature_id", "")
            if solution_design:
                sd_ref = f"{solution_design}#{feature_id}" if feature_id else solution_design
                lines.append(f'        solution_design="{escape_dot_string(sd_ref)}"')

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
                dst_impl = task_nodes[i + 1]["dot_node_id"]
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
    if nodes:
        lines.append(f'        promise_ac="AC-{len(nodes)}"')
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
        description=(
            "Generate Attractor-compatible pipeline.dot from RepoMap baseline "
            "data (F2.x) or beads task data (legacy)."
        )
    )
    ap.add_argument(
        "--prd",
        default="",
        help="PRD reference identifier (e.g., PRD-S3-ATTRACTOR-001). Required unless --scaffold.",
    )
    ap.add_argument(
        "--repo-name",
        default="",
        dest="repo_name",
        help=(
            "Repository name for RepoMap-native mode.  "
            "If provided, nodes are collected from .repomap/baselines/<repo-name>/baseline.json "
            "and cross-referenced with beads.  "
            "If absent, legacy beads-only mode is used."
        ),
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
        "--solution-design",
        default="",
        dest="solution_design",
        help="Path to solution design document (stored as graph/node attr in DOT)",
    )
    ap.add_argument(
        "--filter-prd",
        action="store_true",
        default=True,
        help="Filter beads to only those related to the PRD (default: true, legacy mode only)",
    )
    ap.add_argument(
        "--no-filter",
        action="store_true",
        help="Include all beads without filtering (legacy mode only)",
    )
    ap.add_argument(
        "--project-root",
        default=".",
        dest="project_root",
        help="Project root directory containing .repomap/ (default: .)",
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

    # --- RepoMap-native mode (F2.x) ---
    if args.repo_name:
        project_root = Path(args.project_root)
        repomap_nodes = collect_repomap_nodes(args.repo_name, project_root)
        nodes = cross_reference_beads(repomap_nodes, args.prd)

        dot = generate_pipeline_dot(
            prd_ref=args.prd,
            nodes=nodes,
            label=args.label or "",
            promise_id=args.promise_id,
            target_dir=args.target_dir,
            solution_design=args.solution_design,
        )

        if args.output:
            os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
            with open(args.output, "w") as f:
                f.write(dot)
            print(f"Generated: {args.output}", file=sys.stderr)
            print(f"RepoMap nodes: {len(nodes)}", file=sys.stderr)
            print(f"PRD: {args.prd}", file=sys.stderr)
        else:
            print(dot)
        return

    # --- Legacy beads-only mode ---
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

    # Convert beads to the RepoMap node format expected by generate_pipeline_dot
    nodes = []
    for bead in beads:
        title = bead.get("title", "Untitled")
        description = bead.get("description", "")
        design = bead.get("design", "")
        worker_type = infer_worker_type(title, description, design)
        nodes.append({
            "node_id": bead["id"],
            "title": title,
            "file_path": "",
            "delta_status": "",
            "module": "",
            "interfaces": [],
            "change_summary": description[:120] if description else "",
            "worker_type": worker_type,
            "bead_id": bead["id"],
            "priority": bead.get("priority"),
        })

    dot = generate_pipeline_dot(
        prd_ref=args.prd,
        nodes=nodes,
        label=args.label or "",
        promise_id=args.promise_id,
        target_dir=args.target_dir,
        solution_design=args.solution_design,
    )

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w") as f:
            f.write(dot)
        print(f"Generated: {args.output}", file=sys.stderr)
        print(f"Tasks: {len(nodes)}", file=sys.stderr)
        print(f"PRD: {args.prd}", file=sys.stderr)
    else:
        print(dot)


if __name__ == "__main__":
    main()

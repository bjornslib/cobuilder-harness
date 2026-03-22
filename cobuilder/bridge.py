"""CoBuilder Bridge — RepoMap ↔ Pipeline adapter.

Provides high-level operations that connect the repomap subsystem (codebase
scanning, baseline management) with the central .repomap/ storage and the
pipeline subsystem.

Public API
----------
- :func:`init_repo`            — Initialise a repo in .repomap/config.yaml
- :func:`sync_baseline`        — Walk codebase and save a new baseline
- :func:`get_repomap_context`  — Return a string summary for LLM injection
- :func:`refresh_baseline`     — Rotate baseline → baseline.prev, write new

These functions are consumed by the CLI subcommands wired in F1.7.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from cobuilder.repomap.models.graph import RPGGraph
from cobuilder.repomap.serena.baseline import BaselineManager
from cobuilder.repomap.serena.walker import CodebaseWalker
from cobuilder.repomap.serena.session import FileBasedCodebaseAnalyzer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoped refresh debounce state (module-level, process-scoped)
# ---------------------------------------------------------------------------

_REFRESH_DEBOUNCE_SECONDS = 30.0
_last_refresh_times: dict[str, float] = {}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPOMAP_DIR = ".repomap"
CONFIG_FILE = "config.yaml"
CONFIG_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _repomap_dir(project_root: Path) -> Path:
    """Return the .repomap/ directory path inside *project_root*."""
    return project_root / REPOMAP_DIR


def _load_config(repomap_dir: Path) -> dict[str, Any]:
    """Load .repomap/config.yaml, returning empty config if missing."""
    config_path = repomap_dir / CONFIG_FILE
    if not config_path.exists():
        return {"version": CONFIG_VERSION, "repos": []}
    with config_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if "repos" not in data:
        data["repos"] = []
    return data


def _save_config(repomap_dir: Path, config: dict[str, Any]) -> None:
    """Persist *config* to .repomap/config.yaml."""
    config_path = repomap_dir / CONFIG_FILE
    repomap_dir.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as fh:
        yaml.dump(config, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _find_repo_entry(repos: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Return the config entry for *name*, or None if not registered."""
    for entry in repos:
        if entry.get("name") == name:
            return entry
    return None


def _baseline_dir(repomap_dir: Path, repo_name: str) -> Path:
    """Return the baselines/<repo_name>/ directory."""
    return repomap_dir / "baselines" / repo_name


def _manifest_path(repomap_dir: Path, repo_name: str) -> Path:
    """Return the manifests/<repo_name>.manifest.yaml path."""
    return repomap_dir / "manifests" / f"{repo_name}.manifest.yaml"


def _graph_hash(graph: RPGGraph) -> str:
    """Compute a SHA-256 fingerprint of the graph JSON."""
    # to_json() returns a deterministic JSON string
    raw = graph.to_json(indent=0).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()[:16]


def _walk_codebase(target_dir: Path) -> RPGGraph:
    """Walk *target_dir* and return an RPGGraph baseline."""
    analyzer = FileBasedCodebaseAnalyzer()
    analyzer.activate(target_dir)
    walker = CodebaseWalker(analyzer=analyzer)
    graph = walker.walk(project_root=target_dir)
    return graph


def _write_manifest(
    repomap_dir: Path,
    repo_name: str,
    graph: RPGGraph,
    target_dir: Path,
) -> None:
    """Write a human-readable YAML manifest for *repo_name*."""
    manifest_path = _manifest_path(repomap_dir, repo_name)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    node_count = len(graph.nodes)
    # Count file-level (COMPONENT) nodes
    from cobuilder.repomap.models.enums import NodeLevel

    file_count = sum(
        1 for n in graph.nodes.values() if n.level == NodeLevel.COMPONENT
    )
    function_count = sum(
        1 for n in graph.nodes.values() if n.level == NodeLevel.FEATURE
    )

    # Top modules: group COMPONENT nodes by folder_path
    module_counts: dict[str, int] = {}
    for node in graph.nodes.values():
        if node.level == NodeLevel.COMPONENT and node.folder_path:
            # Use top-level folder as module name
            parts = node.folder_path.split("/")
            module_name = parts[0] if parts else node.folder_path
            module_counts[module_name] = module_counts.get(module_name, 0) + 1

    top_modules = [
        {"name": mod, "files": cnt, "delta": "existing"}
        for mod, cnt in sorted(module_counts.items(), key=lambda x: -x[1])[:10]
    ]

    manifest = {
        "repository": repo_name,
        "snapshot_date": datetime.now(timezone.utc).isoformat(),
        "total_nodes": node_count,
        "total_files": file_count,
        "total_functions": function_count,
        "top_modules": top_modules,
        "target_dir": str(target_dir.resolve()),
    }

    with manifest_path.open("w", encoding="utf-8") as fh:
        yaml.dump(manifest, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)

    logger.info("Wrote manifest: %s", manifest_path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init_repo(
    name: str,
    target_dir: Path | str,
    *,
    project_root: Path | str = Path("."),
    force: bool = False,
) -> dict[str, Any]:
    """Register a repository in .repomap/config.yaml without scanning.

    Creates the baseline directory for *name* and adds an entry to config.yaml.
    If *name* is already registered, raises ``ValueError`` unless *force=True*.

    Args:
        name: Short identifier for the repository (e.g. ``"my-project"``).
        target_dir: Absolute path to the repository root to track.
        project_root: Root of the project that owns .repomap/ (default: cwd).
        force: If True, update an existing entry instead of raising.

    Returns:
        The config entry dict that was written.

    Raises:
        ValueError: If *name* is already registered and *force=False*.
        FileNotFoundError: If *target_dir* does not exist.
    """
    target_dir = Path(target_dir).resolve()
    project_root = Path(project_root).resolve()
    repomap_dir = _repomap_dir(project_root)

    if not target_dir.exists():
        raise FileNotFoundError(f"target_dir does not exist: {target_dir}")

    config = _load_config(repomap_dir)
    existing = _find_repo_entry(config["repos"], name)

    if existing and not force:
        raise ValueError(
            f"Repository '{name}' is already registered. "
            "Use force=True to update."
        )

    entry: dict[str, Any] = {
        "name": name,
        "path": str(target_dir),
        "last_synced": None,
        "baseline_hash": None,
        "node_count": 0,
        "file_count": 0,
    }

    if existing:
        # Update in-place
        existing.update(entry)
    else:
        config["repos"].append(entry)

    # Create baseline directory
    baseline_dir = _baseline_dir(repomap_dir, name)
    baseline_dir.mkdir(parents=True, exist_ok=True)

    _save_config(repomap_dir, config)
    logger.info("Initialised repo '%s' at %s", name, target_dir)
    return entry


def sync_baseline(
    name: str,
    *,
    project_root: Path | str = Path("."),
) -> dict[str, Any]:
    """Walk the registered repository and save a new baseline.

    The previous baseline (if any) is first rotated to ``baseline.prev.json``.
    Config metadata (last_synced, baseline_hash, node_count, file_count) is
    updated in config.yaml, and a manifest YAML is written/updated.

    Args:
        name: Repository name (must already be registered via :func:`init_repo`).
        project_root: Root of the project that owns .repomap/.

    Returns:
        Updated config entry dict.

    Raises:
        KeyError: If *name* is not registered.
    """
    project_root = Path(project_root).resolve()
    repomap_dir = _repomap_dir(project_root)
    config = _load_config(repomap_dir)

    entry = _find_repo_entry(config["repos"], name)
    if entry is None:
        raise KeyError(
            f"Repository '{name}' is not registered. "
            "Call init_repo() first."
        )

    target_dir = Path(entry["path"])
    if not target_dir.exists():
        raise FileNotFoundError(
            f"Repository path no longer exists: {target_dir}"
        )

    logger.info("Walking codebase: %s", target_dir)
    graph = _walk_codebase(target_dir)

    # Rotate baseline if exists
    baseline_dir = _baseline_dir(repomap_dir, name)
    baseline_dir.mkdir(parents=True, exist_ok=True)
    current = baseline_dir / "baseline.json"
    prev = baseline_dir / "baseline.prev.json"

    if current.exists():
        current.rename(prev)
        logger.debug("Rotated baseline → baseline.prev.json")

    # Save new baseline
    manager = BaselineManager()
    manager.save(
        graph,
        current,
        target_dir,
        extra_metadata={"repo_name": name},
    )

    # Update config
    graph_hash = _graph_hash(graph)
    node_count = len(graph.nodes)
    from cobuilder.repomap.models.enums import NodeLevel as _NodeLevel

    file_count = sum(
        1 for n in graph.nodes.values() if n.level == _NodeLevel.COMPONENT
    )

    entry.update(
        {
            "last_synced": datetime.now(timezone.utc).isoformat(),
            "baseline_hash": graph_hash,
            "node_count": node_count,
            "file_count": file_count,
        }
    )
    _save_config(repomap_dir, config)

    # Write manifest
    _write_manifest(repomap_dir, name, graph, target_dir)

    logger.info(
        "Synced '%s': %d nodes, %d files, hash=%s",
        name,
        node_count,
        file_count,
        graph_hash,
    )
    return entry


def get_repomap_context(
    name: str,
    *,
    project_root: Path | str = Path("."),
    max_modules: int = 10,
    prd_keywords: list[str] | None = None,
    sd_file_references: list[str] | None = None,
    format: str = "yaml",
) -> str:
    """Return a repomap context string suitable for LLM injection.

    Supports two output formats:

    - ``"yaml"`` *(default)*: Returns a structured YAML document with
      repository stats, relevant modules (filtered by *prd_keywords* and
      *sd_file_references*), a dependency graph, and protected files.
    - ``"text"``: Returns the original plain-text format (backward-compatible).

    Args:
        name: Repository name.
        project_root: Root of the project that owns .repomap/.
        max_modules: Maximum number of top modules to include.
        prd_keywords: Optional keyword list for relevance filtering (yaml mode).
        sd_file_references: Optional list of file paths from the SD (yaml mode).
        format: Output format — ``"yaml"`` or ``"text"``.

    Returns:
        A formatted string (YAML or plain text).

    Raises:
        KeyError: If *name* is not registered.
        FileNotFoundError: If no manifest exists (sync first).
        ValueError: If *format* is not ``"yaml"`` or ``"text"``.
    """
    if format not in ("yaml", "text"):
        raise ValueError(f"format must be 'yaml' or 'text', got '{format}'")

    project_root = Path(project_root).resolve()
    repomap_dir = _repomap_dir(project_root)
    config = _load_config(repomap_dir)

    entry = _find_repo_entry(config["repos"], name)
    if entry is None:
        raise KeyError(f"Repository '{name}' is not registered.")

    manifest_path = _manifest_path(repomap_dir, name)
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"No manifest found for '{name}'. Run sync_baseline() first."
        )

    with manifest_path.open("r", encoding="utf-8") as fh:
        manifest = yaml.safe_load(fh) or {}

    # ------------------------------------------------------------------ text
    if format == "text":
        lines: list[str] = [
            f"## Codebase: {name}",
            f"Path: {entry.get('path', 'unknown')}",
            f"Last synced: {entry.get('last_synced', 'never')}",
            f"Total nodes: {manifest.get('total_nodes', 0)}",
            f"Files: {manifest.get('total_files', 0)}",
            f"Functions: {manifest.get('total_functions', 0)}",
            "",
            "### Top Modules",
        ]
        top_modules = manifest.get("top_modules", [])[:max_modules]
        for mod in top_modules:
            mod_name = mod.get("name", "?")
            files = mod.get("files", 0)
            delta = mod.get("delta", "existing")
            lines.append(f"  - {mod_name}: {files} files [{delta}]")
        if not top_modules:
            lines.append("  (no modules — run sync_baseline first)")
        return "\n".join(lines)

    # ------------------------------------------------------------------ yaml
    # Try to load the baseline for richer module/dependency data.
    baseline_path = _baseline_dir(repomap_dir, name) / "baseline.json"
    relevant_modules: list[dict] = []
    dependency_graph: list[dict] = []
    protected_files: list[dict] = []

    if baseline_path.exists() and (prd_keywords or sd_file_references):
        from cobuilder.repomap.context_filter import filter_relevant_modules

        relevant_modules = filter_relevant_modules(
            baseline_path=baseline_path,
            prd_keywords=prd_keywords or [],
            sd_file_references=sd_file_references or [],
            max_results=max_modules,
        )
    else:
        # Fall back to manifest top_modules with minimal structure
        top_modules = manifest.get("top_modules", [])[:max_modules]
        for mod in top_modules:
            relevant_modules.append(
                {
                    "name": mod.get("name", "?"),
                    "delta": mod.get("delta", "existing"),
                    "files": mod.get("files", 0),
                    "summary": None,
                    "key_interfaces": [],
                }
            )

    # Build dependency graph from relevant module names (baseline required)
    if baseline_path.exists() and relevant_modules:
        from cobuilder.repomap.context_filter import extract_dependency_graph

        relevant_names = [m["name"] for m in relevant_modules]
        dependency_graph = extract_dependency_graph(baseline_path, relevant_names)

    # Build structured YAML document
    doc: dict = {
        "repository": name,
        "snapshot_date": entry.get("last_synced") or manifest.get("snapshot_date", ""),
        "total_nodes": manifest.get("total_nodes", 0),
        "total_files": manifest.get("total_files", 0),
        "total_functions": manifest.get("total_functions", 0),
        "modules_relevant_to_epic": relevant_modules or None,
        "dependency_graph": dependency_graph or None,
        "protected_files": protected_files or None,
    }
    # Remove None-valued top-level keys for cleaner output
    doc = {k: v for k, v in doc.items() if v is not None}

    return yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)


def scoped_refresh(
    name: str,
    scope: list[str],
    *,
    project_root: Path | str = Path("."),
) -> dict[str, Any]:
    """Re-scan only the specified files/folders and merge into the existing baseline.

    Unlike :func:`sync_baseline` which re-scans the entire repository, this
    function restricts the walk to the paths listed in *scope*.

    A 30-second debounce window is enforced per repo name. If called again
    within that window the function returns immediately with
    ``{"skipped": True, ...}``.

    Args:
        name: Repository name (must already be registered via
            :func:`init_repo`).
        scope: List of file or folder paths to re-scan. Paths may be
            absolute or relative to the repository root.
        project_root: Root of the project that owns ``.repomap/``.

    Returns:
        Dict with keys:

        - ``refreshed_nodes`` (int) — number of nodes in the scoped graph
        - ``duration_seconds`` (float) — wall-clock time of the scan
        - ``baseline_hash`` (str) — SHA-256 fingerprint of merged baseline
        - ``skipped`` (bool) — True if the call was debounced

    Raises:
        KeyError: If *name* is not registered.
        FileNotFoundError: If the repository path no longer exists.
    """
    # ------------------------------------------------------------------
    # Debounce guard
    # ------------------------------------------------------------------
    now = time.monotonic()
    if now - _last_refresh_times.get(name, 0.0) < _REFRESH_DEBOUNCE_SECONDS:
        logger.debug("scoped_refresh debounced for '%s'", name)
        return {
            "skipped": True,
            "refreshed_nodes": 0,
            "duration_seconds": 0.0,
            "baseline_hash": "",
        }
    _last_refresh_times[name] = now

    # ------------------------------------------------------------------
    # Load repo config
    # ------------------------------------------------------------------
    project_root = Path(project_root).resolve()
    repomap_dir = _repomap_dir(project_root)
    config = _load_config(repomap_dir)

    entry = _find_repo_entry(config["repos"], name)
    if entry is None:
        raise KeyError(
            f"Repository '{name}' is not registered. "
            "Call init_repo() first."
        )

    target_dir = Path(entry["path"])
    if not target_dir.exists():
        raise FileNotFoundError(
            f"Repository path no longer exists: {target_dir}"
        )

    # ------------------------------------------------------------------
    # Resolve scope paths relative to target_dir
    # ------------------------------------------------------------------
    resolved_scope: list[Path] = []
    for raw in scope:
        p = Path(raw)
        if not p.is_absolute():
            p = (target_dir / p).resolve()
        else:
            p = p.resolve()
        resolved_scope.append(p)

    # ------------------------------------------------------------------
    # Scoped walk
    # ------------------------------------------------------------------
    t0 = time.monotonic()
    analyzer = FileBasedCodebaseAnalyzer()
    analyzer.activate(target_dir)
    walker = CodebaseWalker(analyzer=analyzer)
    scoped_graph = walker.walk_paths(
        paths=[str(p) for p in resolved_scope],
        project_root=target_dir,
    )
    elapsed = time.monotonic() - t0

    # ------------------------------------------------------------------
    # Merge + save
    # ------------------------------------------------------------------
    manager = BaselineManager()
    save_result = manager.scoped_save(
        repo_name=name,
        scoped=scoped_graph,
        project_root=target_dir,
        repomap_dir=repomap_dir,
    )

    # ------------------------------------------------------------------
    # Update config.yaml with new last_synced + hash
    # ------------------------------------------------------------------
    entry.update(
        {
            "last_synced": datetime.now(timezone.utc).isoformat(),
            "baseline_hash": save_result["baseline_hash"],
            "node_count": save_result["node_count"],
            "file_count": save_result["file_count"],
        }
    )
    _save_config(repomap_dir, config)

    logger.info(
        "scoped_refresh '%s': %d nodes refreshed in %.2fs, hash=%s",
        name,
        len(scoped_graph.nodes),
        elapsed,
        save_result["baseline_hash"],
    )

    return {
        "skipped": False,
        "refreshed_nodes": len(scoped_graph.nodes),
        "duration_seconds": elapsed,
        "baseline_hash": save_result["baseline_hash"],
    }


def refresh_baseline(
    name: str,
    *,
    project_root: Path | str = Path("."),
) -> dict[str, Any]:
    """Convenience alias for :func:`sync_baseline`.

    Rotates baseline → baseline.prev.json and writes a fresh scan.
    Identical to ``sync_baseline()`` — provided as a descriptive alias
    for callers who think in terms of "refresh".

    Args:
        name: Repository name.
        project_root: Root of the project that owns .repomap/.

    Returns:
        Updated config entry dict.
    """
    return sync_baseline(name, project_root=project_root)

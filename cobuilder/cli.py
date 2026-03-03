"""CoBuilder CLI — command groups for repomap, pipeline, and agents."""

import sys
import json
import datetime
from pathlib import Path
from typing import Optional, List

import typer

from cobuilder.repomap.cli.commands import app as repomap_app

app = typer.Typer(name="cobuilder", help="CoBuilder: unified codebase intelligence")

pipeline_app = typer.Typer(help="Pipeline commands")
agents_app = typer.Typer(help="Agent orchestration commands")

app.add_typer(repomap_app, name="repomap")
app.add_typer(pipeline_app, name="pipeline")
app.add_typer(agents_app, name="agents")


@pipeline_app.command("create")
def pipeline_create(
    sd: str = typer.Option(..., "--sd", help="Path to Solution Design file"),
    repo: str = typer.Option(..., "--repo", help="Repository name (registered in .repomap/)"),
    output: str = typer.Option("", "--output", help="Output .dot file path (default: stdout)"),
    prd: str = typer.Option("", "--prd", help="PRD reference (e.g. PRD-COBUILDER-001)"),
    target_dir: str = typer.Option("", "--target-dir", help="Implementation repo root"),
    skip_enrichment: bool = typer.Option(False, "--skip-enrichment", help="Skip LLM enrichment"),
    skip_taskmaster: bool = typer.Option(False, "--skip-taskmaster", help="Skip TaskMaster parse"),
    dot_pipeline: str = typer.Option("", "--dot-pipeline", help="Path to existing .dot pipeline file for context injection"),
) -> None:
    """Create an Attractor DOT pipeline from a Solution Design + RepoMap baseline."""
    from cobuilder.pipeline.generate import ensure_baseline, collect_repomap_nodes, filter_nodes_by_sd_relevance, cross_reference_beads, generate_pipeline_dot
    from cobuilder.pipeline.enrichers import EnrichmentPipeline
    from cobuilder.pipeline.taskmaster_bridge import run_taskmaster_parse
    from cobuilder.pipeline.sd_enricher import write_all_enrichments

    project_root = Path(target_dir) if target_dir else Path(".")
    sd_path = Path(sd)

    # Step 1+2: Ensure baseline, collect nodes
    typer.echo(f"[1/7] Checking RepoMap baseline for '{repo}'...")
    ensure_baseline(repo, project_root)

    typer.echo("[2/7] Collecting RepoMap nodes...")
    nodes = collect_repomap_nodes(repo, project_root)
    typer.echo(f"      Found {len(nodes)} MODIFIED/NEW nodes")

    # Step 2.5: SD relevance filter
    sd_content = sd_path.read_text() if sd_path.exists() else ""
    typer.echo(f"[2.5/7] Filtering nodes by SD relevance ({len(nodes)} candidates)...")
    nodes = filter_nodes_by_sd_relevance(nodes, sd_content)
    typer.echo(f"        Retained {len(nodes)} SD-relevant nodes")
    if not nodes:
        typer.echo("        ⚠ SD filter returned 0 nodes — pipeline will contain only TaskMaster-derived nodes")

    # Step 3: TaskMaster parse
    taskmaster_tasks = {}
    if not skip_taskmaster:
        typer.echo("[3/7] Running TaskMaster parse...")
        # Fetch RepoMap context for enriched task decomposition
        repomap_ctx = ""
        try:
            from cobuilder.bridge import get_repomap_context
            repomap_ctx = get_repomap_context(repo, project_root=project_root)
            typer.echo("      RepoMap context injected into TaskMaster input")
        except (KeyError, FileNotFoundError):
            typer.echo("      (RepoMap context unavailable — run 'cobuilder repomap sync' first)")
        taskmaster_tasks = run_taskmaster_parse(
            str(sd_path.resolve()),
            str(project_root.resolve()),
            repomap_context=repomap_ctx,
            dot_pipeline_path=dot_pipeline,
        )
        if dot_pipeline:
            typer.echo(f"      DOT pipeline context injected: {dot_pipeline}")
    else:
        typer.echo("[3/7] Skipping TaskMaster parse (--skip-taskmaster)")

    # Step 4: Beads cross-reference
    typer.echo("[4/7] Cross-referencing with beads...")
    nodes = cross_reference_beads(nodes, prd)

    # Step 5: LLM enrichment
    if not skip_enrichment:
        typer.echo("[5/7] Running LLM enrichment pipeline (5 enrichers)...")
        pipeline = EnrichmentPipeline()
        nodes = pipeline.enrich(nodes, {}, sd_content)
        worker_types = {}
        for n in nodes:
            wt = n.get("worker_type", "unknown")
            worker_types[wt] = worker_types.get(wt, 0) + 1
        typer.echo(f"      Worker type distribution: {worker_types}")
    else:
        typer.echo("[5/7] Skipping LLM enrichment (--skip-enrichment)")

    # Step 6: DOT rendering
    typer.echo("[6/7] Rendering DOT pipeline...")
    dot = generate_pipeline_dot(
        prd_ref=prd or f"PRD-{repo.upper()}",
        nodes=nodes,
        solution_design=sd,
        target_dir=target_dir,
    )

    # Step 7: SD v2 enrichment
    typer.echo("[7/7] Writing SD v2 enrichment blocks...")
    count = write_all_enrichments(str(sd_path), nodes, taskmaster_tasks)
    typer.echo(f"      Wrote {count} enrichment blocks to {sd}")

    # Output DOT
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(dot)
        typer.echo(f"Pipeline written to: {output}")
    else:
        typer.echo(dot)


# ---------------------------------------------------------------------------
# Node operations
# ---------------------------------------------------------------------------


@pipeline_app.command("node-list")
def pipeline_node_list(
    file: str = typer.Argument(..., help="Path to .dot file"),
    output: str = typer.Option("text", "--output", help="Output format: text or json"),
) -> None:
    """List all nodes in a pipeline."""
    from cobuilder.pipeline.node_ops import list_nodes

    try:
        content = Path(file).read_text()
    except FileNotFoundError:
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)

    list_nodes(content, output=output)


@pipeline_app.command("node-add")
def pipeline_node_add(
    file: str = typer.Argument(..., help="Path to .dot file"),
    node_id: str = typer.Argument(..., help="Node identifier (unique)"),
    handler: str = typer.Option(..., "--handler", help="Handler type (determines shape)"),
    label: str = typer.Option(..., "--label", help="Display label for the node"),
    status: str = typer.Option("pending", "--status", help="Initial status (default: pending)"),
    set_attrs: Optional[List[str]] = typer.Option(None, "--set", help="Additional attribute(s) as key=value (repeatable)"),
    no_at_pair: bool = typer.Option(False, "--no-at-pair", help="Suppress automatic AT gate pairing for codergen nodes"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
    output: str = typer.Option("text", "--output", help="Output format: text or json"),
) -> None:
    """Add a new node to a pipeline."""
    from cobuilder.pipeline.node_ops import add_node, _parse_set_args, _dot_file_lock, _append_ops_jsonl

    try:
        content = Path(file).read_text()
    except FileNotFoundError:
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)

    extra_attrs = {}
    if set_attrs:
        try:
            extra_attrs = _parse_set_args(list(set_attrs))
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

    try:
        updated = add_node(
            content,
            node_id,
            handler=handler,
            label=label,
            status=status,
            extra_attrs=extra_attrs if extra_attrs else None,
            auto_pair_at=not no_at_pair,
        )
    except ValueError as e:
        if output == "json":
            typer.echo(json.dumps({"success": False, "error": str(e)}, indent=2))
        else:
            typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    at_node_id = f"{node_id}_at" if (not no_at_pair and handler == "codergen") else None

    if dry_run:
        if output == "json":
            result: dict = {"success": True, "dry_run": True, "node_id": node_id}
            if at_node_id:
                result["at_node_id"] = at_node_id
            typer.echo(json.dumps(result, indent=2))
        else:
            typer.echo(f"DRY RUN: would add node '{node_id}' (handler={handler})")
            if at_node_id:
                typer.echo(f"  Also would add AT gate node '{at_node_id}' (handler=wait.human)")
                typer.echo(f"  Also would add edge: {node_id} -> {at_node_id}")
            typer.echo("(no changes written)")
    else:
        with _dot_file_lock(file):
            Path(file).write_text(updated)

            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            log_entry: dict = {
                "timestamp": timestamp,
                "file": file,
                "command": "node add",
                "node_id": node_id,
                "handler": handler,
                "label": label,
                "status": status,
            }
            if at_node_id:
                log_entry["at_node_id"] = at_node_id
                log_entry["auto_pair_at"] = True
            _append_ops_jsonl(file, log_entry)

        if output == "json":
            result = {"success": True, "node_id": node_id, "file": file}
            if at_node_id:
                result["at_node_id"] = at_node_id
            typer.echo(json.dumps(result, indent=2))
        else:
            typer.echo(f"Node added: {node_id}")
            if at_node_id:
                typer.echo(f"  AT gate node added: {at_node_id}")
                typer.echo(f"  Edge added: {node_id} -> {at_node_id}")
            typer.echo(f"Updated: {file}")


@pipeline_app.command("node-remove")
def pipeline_node_remove(
    file: str = typer.Argument(..., help="Path to .dot file"),
    node_id: str = typer.Argument(..., help="Node ID to remove"),
    keep_edges: bool = typer.Option(False, "--keep-edges", help="Do not remove edges referencing this node"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
    output: str = typer.Option("text", "--output", help="Output format: text or json"),
) -> None:
    """Remove a node from a pipeline."""
    from cobuilder.pipeline.node_ops import remove_node, _dot_file_lock, _append_ops_jsonl

    try:
        content = Path(file).read_text()
    except FileNotFoundError:
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)

    remove_edges = not keep_edges
    try:
        updated, removed_edges = remove_node(content, node_id, remove_edges=remove_edges)
    except ValueError as e:
        if output == "json":
            typer.echo(json.dumps({"success": False, "error": str(e)}, indent=2))
        else:
            typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    if dry_run:
        if output == "json":
            typer.echo(json.dumps({
                "success": True,
                "dry_run": True,
                "node_id": node_id,
                "edges_removed": len(removed_edges),
            }, indent=2))
        else:
            typer.echo(f"DRY RUN: would remove node '{node_id}'")
            if removed_edges:
                typer.echo(f"  Would also remove {len(removed_edges)} edge(s)")
            typer.echo("(no changes written)")
    else:
        with _dot_file_lock(file):
            Path(file).write_text(updated)

            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            _append_ops_jsonl(
                file,
                {
                    "timestamp": timestamp,
                    "file": file,
                    "command": "node remove",
                    "node_id": node_id,
                    "edges_removed": len(removed_edges),
                },
            )

        if output == "json":
            typer.echo(json.dumps({
                "success": True,
                "node_id": node_id,
                "edges_removed": len(removed_edges),
                "file": file,
            }, indent=2))
        else:
            typer.echo(f"Node removed: {node_id}")
            if removed_edges:
                typer.echo(f"  Also removed {len(removed_edges)} edge(s) referencing this node")
            typer.echo(f"Updated: {file}")


@pipeline_app.command("node-modify")
def pipeline_node_modify(
    file: str = typer.Argument(..., help="Path to .dot file"),
    node_id: str = typer.Argument(..., help="Node ID to modify"),
    set_attrs: List[str] = typer.Option(..., "--set", help="Attribute(s) to update as key=value (repeatable)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
    output: str = typer.Option("text", "--output", help="Output format: text or json"),
) -> None:
    """Modify attributes of an existing node."""
    from cobuilder.pipeline.node_ops import modify_node, _parse_set_args, _dot_file_lock, _append_ops_jsonl

    try:
        content = Path(file).read_text()
    except FileNotFoundError:
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)

    try:
        attr_updates = _parse_set_args(list(set_attrs))
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    try:
        updated = modify_node(content, node_id, attr_updates)
    except ValueError as e:
        if output == "json":
            typer.echo(json.dumps({"success": False, "error": str(e)}, indent=2))
        else:
            typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    if dry_run:
        if output == "json":
            typer.echo(json.dumps({
                "success": True,
                "dry_run": True,
                "node_id": node_id,
                "updates": attr_updates,
            }, indent=2))
        else:
            typer.echo(f"DRY RUN: would modify node '{node_id}'")
            for k, v in attr_updates.items():
                typer.echo(f'  {k} = "{v}"')
            typer.echo("(no changes written)")
    else:
        with _dot_file_lock(file):
            Path(file).write_text(updated)

            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            _append_ops_jsonl(
                file,
                {
                    "timestamp": timestamp,
                    "file": file,
                    "command": "node modify",
                    "node_id": node_id,
                    "updates": attr_updates,
                },
            )

        if output == "json":
            typer.echo(json.dumps({
                "success": True,
                "node_id": node_id,
                "updates": attr_updates,
                "file": file,
            }, indent=2))
        else:
            typer.echo(f"Node modified: {node_id}")
            for k, v in attr_updates.items():
                typer.echo(f'  {k} = "{v}"')
            typer.echo(f"Updated: {file}")


# ---------------------------------------------------------------------------
# Edge operations
# ---------------------------------------------------------------------------


@pipeline_app.command("edge-list")
def pipeline_edge_list(
    file: str = typer.Argument(..., help="Path to .dot file"),
    output: str = typer.Option("text", "--output", help="Output format: text or json"),
) -> None:
    """List all edges in a pipeline."""
    from cobuilder.pipeline.edge_ops import list_edges

    try:
        content = Path(file).read_text()
    except FileNotFoundError:
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)

    list_edges(content, output=output)


@pipeline_app.command("edge-add")
def pipeline_edge_add(
    file: str = typer.Argument(..., help="Path to .dot file"),
    src: str = typer.Argument(..., help="Source node ID"),
    dst: str = typer.Argument(..., help="Destination node ID"),
    label: str = typer.Option("", "--label", help="Edge label (optional)"),
    condition: str = typer.Option("", "--condition", help="Edge condition: pass, fail, or partial (optional)"),
    set_attrs: Optional[List[str]] = typer.Option(None, "--set", help="Additional edge attribute(s) as key=value (repeatable)"),
    allow_cycle: bool = typer.Option(False, "--allow-cycle", help="Skip unguarded cycle detection for this edge"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
    output: str = typer.Option("text", "--output", help="Output format: text or json"),
) -> None:
    """Add a new edge to a pipeline."""
    from cobuilder.pipeline.edge_ops import add_edge, _parse_set_args, _dot_file_lock, _append_ops_jsonl

    try:
        content = Path(file).read_text()
    except FileNotFoundError:
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)

    extra_attrs = {}
    if set_attrs:
        try:
            extra_attrs = _parse_set_args(list(set_attrs))
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

    try:
        updated = add_edge(
            content,
            src,
            dst,
            label=label,
            condition=condition,
            extra_attrs=extra_attrs if extra_attrs else None,
            allow_cycle=allow_cycle,
        )
    except ValueError as e:
        if output == "json":
            typer.echo(json.dumps({"success": False, "error": str(e)}, indent=2))
        else:
            typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    desc = f"{src} -> {dst}"
    if condition:
        desc += f" [{condition}]"

    if dry_run:
        if output == "json":
            typer.echo(json.dumps({
                "success": True,
                "dry_run": True,
                "src": src,
                "dst": dst,
                "condition": condition,
                "label": label,
            }, indent=2))
        else:
            typer.echo(f"DRY RUN: would add edge '{desc}'")
            typer.echo("(no changes written)")
    else:
        with _dot_file_lock(file):
            Path(file).write_text(updated)

            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            _append_ops_jsonl(
                file,
                {
                    "timestamp": timestamp,
                    "file": file,
                    "command": "edge add",
                    "src": src,
                    "dst": dst,
                    "label": label,
                    "condition": condition,
                },
            )

        if output == "json":
            typer.echo(json.dumps({
                "success": True,
                "src": src,
                "dst": dst,
                "condition": condition,
                "label": label,
                "file": file,
            }, indent=2))
        else:
            typer.echo(f"Edge added: {desc}")
            typer.echo(f"Updated: {file}")


@pipeline_app.command("edge-remove")
def pipeline_edge_remove(
    file: str = typer.Argument(..., help="Path to .dot file"),
    src: str = typer.Argument(..., help="Source node ID"),
    dst: str = typer.Argument(..., help="Destination node ID"),
    condition: str = typer.Option("", "--condition", help="Filter by condition (optional; removes all edges when omitted)"),
    label: str = typer.Option("", "--label", help="Filter by label (optional)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
    output: str = typer.Option("text", "--output", help="Output format: text or json"),
) -> None:
    """Remove edge(s) from a pipeline."""
    from cobuilder.pipeline.edge_ops import remove_edge, _dot_file_lock, _append_ops_jsonl

    try:
        content = Path(file).read_text()
    except FileNotFoundError:
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)

    try:
        updated, count = remove_edge(content, src, dst, condition=condition, label=label)
    except ValueError as e:
        if output == "json":
            typer.echo(json.dumps({"success": False, "error": str(e)}, indent=2))
        else:
            typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    desc = f"{src} -> {dst}"
    if condition:
        desc += f" [condition={condition}]"

    if dry_run:
        if output == "json":
            typer.echo(json.dumps({
                "success": True,
                "dry_run": True,
                "src": src,
                "dst": dst,
                "count": count,
            }, indent=2))
        else:
            typer.echo(f"DRY RUN: would remove {count} edge(s) matching '{desc}'")
            typer.echo("(no changes written)")
    else:
        with _dot_file_lock(file):
            Path(file).write_text(updated)

            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            _append_ops_jsonl(
                file,
                {
                    "timestamp": timestamp,
                    "file": file,
                    "command": "edge remove",
                    "src": src,
                    "dst": dst,
                    "condition": condition,
                    "label": label,
                    "count": count,
                },
            )

        if output == "json":
            typer.echo(json.dumps({
                "success": True,
                "src": src,
                "dst": dst,
                "count": count,
                "file": file,
            }, indent=2))
        else:
            typer.echo(f"Edge(s) removed: {count} matching '{desc}'")
            typer.echo(f"Updated: {file}")


# ---------------------------------------------------------------------------
# Checkpoint operations
# ---------------------------------------------------------------------------


@pipeline_app.command("checkpoint-save")
def pipeline_checkpoint_save(
    file: str = typer.Argument(..., help="Path to .dot file"),
    output: str = typer.Option("", "--output", help="Output path for checkpoint JSON (default: auto-generated)"),
) -> None:
    """Save pipeline state to a JSON checkpoint."""
    from cobuilder.pipeline.checkpoint import save_checkpoint

    try:
        result = save_checkpoint(file, output)
        typer.echo(f"Checkpoint saved: {result['checkpoint_path']}")
        cp = result["checkpoint"]
        typer.echo(f"  Graph: {cp['graph_name']}")
        typer.echo(f"  Nodes: {len(cp['nodes'])}")
        typer.echo(f"  Edges: {len(cp['edges'])}")
        typer.echo(f"  Hash:  {cp['content_hash']}")
    except FileNotFoundError:
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@pipeline_app.command("checkpoint-restore")
def pipeline_checkpoint_restore(
    file: str = typer.Argument(..., help="Path to checkpoint .json file"),
    output: str = typer.Option("", "--output", help="Output path for restored .dot file (default: auto-generated)"),
) -> None:
    """Restore a pipeline from a JSON checkpoint."""
    from cobuilder.pipeline.checkpoint import restore_checkpoint

    try:
        out_path = restore_checkpoint(file, output)
        typer.echo(f"Pipeline restored: {out_path}")
    except FileNotFoundError:
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)
    except json.JSONDecodeError as e:
        typer.echo(f"Error: Invalid JSON in {file}: {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@pipeline_app.command("dashboard")
def pipeline_dashboard(
    file: str = typer.Argument(..., help="Path to pipeline .dot file"),
    output: str = typer.Option("text", "--output", help="Output format: text or json"),
    checkpoint: str = typer.Option("", "--checkpoint", metavar="PATH", help="Optional path to checkpoint .json for time-in-state estimates"),
) -> None:
    """Display unified lifecycle dashboard for a pipeline."""
    from cobuilder.pipeline.dashboard import parse_file, load_checkpoint, compute_dashboard, render_dashboard

    try:
        data = parse_file(file)
    except FileNotFoundError:
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error parsing {file}: {e}", err=True)
        raise typer.Exit(1)

    checkpoint_data = load_checkpoint(checkpoint)
    dashboard = compute_dashboard(data, checkpoint_data)

    if output == "json":
        typer.echo(json.dumps(dashboard, indent=2))
    else:
        typer.echo(render_dashboard(dashboard))


# ---------------------------------------------------------------------------
# Init promise
# ---------------------------------------------------------------------------


@pipeline_app.command("init-promise")
def pipeline_init_promise(
    file: str = typer.Argument(..., help="Path to pipeline .dot file"),
    json_output: bool = typer.Option(False, "--json", help="Output structured JSON instead of shell commands"),
    execute: bool = typer.Option(False, "--execute", help="Execute the initialization commands"),
) -> None:
    """Generate cs-promise initialization commands from pipeline.dot."""
    from cobuilder.pipeline.init_promise import parse_file, extract_promise_info, generate_shell_commands, generate_json_output

    try:
        data = parse_file(file)
    except FileNotFoundError:
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error parsing {file}: {e}", err=True)
        raise typer.Exit(1)

    info = extract_promise_info(data)

    if not info["codergen_nodes"]:
        typer.echo(
            "Warning: No codergen nodes found in pipeline. "
            "Promise will have no task-derived ACs.",
            err=True,
        )

    if json_output:
        result = generate_json_output(info)
        typer.echo(json.dumps(result, indent=2))
    else:
        commands = generate_shell_commands(info)
        output_text = "\n".join(commands)
        typer.echo(output_text)

        if execute:
            import re
            import subprocess
            typer.echo("\n# --- Executing initialization commands ---", err=True)

            slug = re.sub(r"[^a-z0-9]+", "-", info["prd_ref"].lower()).strip("-")

            typer.echo(f"Executing: cs-init --initiative {slug}", err=True)
            result_proc = subprocess.run(
                ["cs-init", "--initiative", slug],
                capture_output=True,
                text=True,
            )
            if result_proc.returncode != 0:
                typer.echo(f"cs-init failed: {result_proc.stderr}", err=True)
                raise typer.Exit(1)
            if result_proc.stdout.strip():
                typer.echo(f"cs-init output: {result_proc.stdout.strip()}", err=True)

            label = info["graph_label"] or info["prd_ref"]
            create_cmd = ["cs-promise", "--create", label]
            for cg in info["codergen_nodes"]:
                ac_desc = cg.get("acceptance") or cg.get("label", "")
                if ac_desc:
                    create_cmd.extend(["--ac", ac_desc])
            create_cmd.extend(["--ac", "All pipeline nodes validated (triple-gate verification)"])

            typer.echo("Executing: cs-promise --create ...", err=True)
            result_proc = subprocess.run(
                create_cmd,
                capture_output=True,
                text=True,
            )
            if result_proc.returncode != 0:
                typer.echo(f"cs-promise --create failed: {result_proc.stderr}", err=True)
                raise typer.Exit(1)
            typer.echo(f"cs-promise output: {result_proc.stdout.strip()}", err=True)

            typer.echo("\nInitialization complete.", err=True)
            typer.echo("Run the validation gate commands as tasks complete.", err=True)


# ---------------------------------------------------------------------------
# Annotate
# ---------------------------------------------------------------------------


@pipeline_app.command("annotate")
def pipeline_annotate(
    file: str = typer.Argument(..., help="Path to pipeline .dot file"),
    output: Optional[str] = typer.Option(None, "--output", help="Output file path (default: overwrite input file)"),
    beads_json: Optional[str] = typer.Option(None, "--beads-json", help="Path to JSON file with beads data (default: runs bd list --json)"),
    json_output: bool = typer.Option(False, "--json", help="Output changes as JSON"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change without writing"),
    verbose: bool = typer.Option(False, "--verbose", help="Show unmatched nodes"),
) -> None:
    """Annotate pipeline.dot with beads data (status, bead_id, acceptance criteria)."""
    from cobuilder.pipeline.annotate import get_beads_data, annotate_pipeline
    import os

    try:
        with open(file, "r") as f:
            dot_content = f.read()
    except FileNotFoundError:
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)

    beads = get_beads_data(beads_json or "")
    if not beads:
        typer.echo("Error: No beads data available.", err=True)
        typer.echo(
            "Provide --beads-json <file> or ensure 'bd list --json' works.",
            err=True,
        )
        raise typer.Exit(1)

    updated, changes = annotate_pipeline(dot_content, beads, verbose=verbose)

    if json_output:
        result = {
            "file": file,
            "total_changes": len(changes),
            "bead_id_updates": sum(1 for c in changes if c.get("updated_bead_id")),
            "status_updates": sum(1 for c in changes if c.get("updated_status")),
            "acceptance_adds": sum(1 for c in changes if c.get("added_acceptance")),
            "changes": changes,
        }
        typer.echo(json.dumps(result, indent=2))
    else:
        if not changes:
            typer.echo("No changes: no nodes could be matched to beads.")
        else:
            typer.echo(f"Annotated {len(changes)} node(s):")
            for c in changes:
                updates = []
                if c.get("updated_bead_id"):
                    updates.append(f"bead_id: {c['old_bead_id']} -> {c['bead_id']}")
                if c.get("updated_status"):
                    updates.append(f"status: {c['old_status']} -> {c['new_status']}")
                if c.get("added_acceptance"):
                    updates.append("acceptance: added")
                if updates:
                    typer.echo(f"  {c['node_id']}: {'; '.join(updates)}")
                else:
                    typer.echo(f"  {c['node_id']}: already up to date")

    if not dry_run and changes:
        output_path = output or file
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(updated)
        if not json_output:
            typer.echo(f"\nWritten: {output_path}")
    elif dry_run and not json_output:
        typer.echo("\n(dry-run: no changes written)")


# ---------------------------------------------------------------------------
# Transition
# ---------------------------------------------------------------------------


@pipeline_app.command("transition")
def pipeline_transition(
    file: str = typer.Argument(..., help="Path to .dot file"),
    node: str = typer.Argument(..., help="Node ID to transition"),
    new_status: str = typer.Argument(..., help="Target status (pending, active, impl_complete, validated, failed)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
    force: bool = typer.Option(False, "--force", help="Skip finalize gate check (use with caution)"),
) -> None:
    """Apply a status transition to a pipeline node."""
    from cobuilder.pipeline.transition import (
        apply_transition,
        check_finalize_gate,
        _dot_file_lock,
        _append_transition_jsonl,
        _write_finalize_signal,
    )
    from cobuilder.pipeline.parser import parse_file as _parse_file

    try:
        content = Path(file).read_text()
    except FileNotFoundError:
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)

    # Pre-fetch node attrs for signal file writing
    try:
        pre_data = _parse_file(file)
    except Exception as e:
        typer.echo(f"Error parsing {file}: {e}", err=True)
        raise typer.Exit(1)

    pre_node_attrs: dict = {}
    for n in pre_data.get("nodes", []):
        if n["id"] == node:
            pre_node_attrs = n["attrs"]
            break

    try:
        updated, log_msg = apply_transition(content, node, new_status)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    if dry_run:
        typer.echo(f"DRY RUN: {log_msg}")
        typer.echo("(no changes written)")
    else:
        with _dot_file_lock(file):
            Path(file).write_text(updated)

            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            _append_transition_jsonl(
                file,
                {
                    "timestamp": timestamp,
                    "file": file,
                    "command": "transition",
                    "node_id": node,
                    "new_status": new_status,
                    "log": log_msg,
                },
            )

            sig = _write_finalize_signal(file, node, new_status, pre_node_attrs)

        typer.echo(f"Transition applied: {log_msg}")
        typer.echo(f"Updated: {file}")
        if sig:
            typer.echo(f"Signal written: {sig}")


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@pipeline_app.command("status")
def pipeline_status(
    file: str = typer.Argument(..., help="Path to .dot file"),
    filter_status: str = typer.Option("", "--filter", help="Filter by status (e.g. active, pending)"),
    deps_met: bool = typer.Option(False, "--deps-met", help="Only show nodes whose upstream deps are all validated"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    summary: bool = typer.Option(False, "--summary", help="Show only status summary counts"),
) -> None:
    """Display node status table for a pipeline."""
    from cobuilder.pipeline.status import get_status_table, format_table, status_summary
    from cobuilder.pipeline.parser import parse_file as _parse_file

    try:
        data = _parse_file(file)
    except FileNotFoundError:
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error parsing {file}: {e}", err=True)
        raise typer.Exit(1)

    all_rows = get_status_table(data)
    display_rows = get_status_table(data, filter_status=filter_status, deps_met=deps_met)
    counts = status_summary(all_rows)

    if json_output:
        result: dict = {
            "graph_name": data.get("graph_name", ""),
            "prd_ref": data.get("graph_attrs", {}).get("prd_ref", ""),
            "total_nodes": len(all_rows),
            "summary": counts,
        }
        if deps_met:
            result["deps_met_filter"] = True
        if not summary:
            result["nodes"] = display_rows
        typer.echo(json.dumps(result, indent=2))
    else:
        graph_name = data.get("graph_name", "unknown")
        prd = data.get("graph_attrs", {}).get("prd_ref", "")
        typer.echo(f"Pipeline: {graph_name}")
        if prd:
            typer.echo(f"PRD: {prd}")
        typer.echo(f"Total nodes: {len(all_rows)}")
        typer.echo("")

        if summary:
            typer.echo("Status summary:")
            for s, c in sorted(counts.items()):
                typer.echo(f"  {s:20s}  {c}")
        else:
            active_filters = []
            if filter_status:
                active_filters.append(f"status={filter_status}")
            if deps_met:
                active_filters.append("deps-met (all predecessors validated)")
            if active_filters:
                typer.echo(f"Filter: {', '.join(active_filters)}")
                typer.echo("")
            typer.echo(format_table(display_rows))
            typer.echo("")
            typer.echo("Summary: " + ", ".join(f"{s}={c}" for s, c in sorted(counts.items())))


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


@pipeline_app.command("validate")
def pipeline_validate(
    file: str = typer.Argument(..., help="Path to .dot file"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Validate a pipeline DOT file against schema rules."""
    from cobuilder.pipeline.validator import validate_file

    try:
        issues = validate_file(file)
    except FileNotFoundError:
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]

    if json_output:
        result = {
            "valid": len(errors) == 0,
            "errors": [i.to_dict() for i in errors],
            "warnings": [i.to_dict() for i in warnings],
            "summary": f"{len(errors)} errors, {len(warnings)} warnings",
        }
        typer.echo(json.dumps(result, indent=2))
    else:
        if not issues:
            typer.echo(f"VALID: {file} passes all validation rules.")
        else:
            if errors:
                typer.echo(f"\nErrors ({len(errors)}):")
                for e in errors:
                    typer.echo(str(e))
            if warnings:
                typer.echo(f"\nWarnings ({len(warnings)}):")
                for w in warnings:
                    typer.echo(str(w))
            typer.echo(f"\nSummary: {len(errors)} errors, {len(warnings)} warnings")
            if errors:
                typer.echo("INVALID: Pipeline has structural errors.")

    if errors:
        raise typer.Exit(1)


@pipeline_app.command("run")
def pipeline_run(
    file: str = typer.Argument(..., help="Path to .dot pipeline file to execute"),
    resume: Optional[str] = typer.Option(
        None,
        "--resume",
        help="Resume from an existing run directory (path to the run-<timestamp> dir)",
    ),
    pipelines_dir: Optional[str] = typer.Option(
        None,
        "--pipelines-dir",
        help="Parent directory for run directories (default: .claude/attractor/pipelines/)",
    ),
    max_visits: int = typer.Option(
        10,
        "--max-visits",
        help="Maximum number of times any single node may be visited (loop guard)",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit the final EngineCheckpoint as JSON on stdout",
    ),
    skip_validation: bool = typer.Option(
        False,
        "--skip-validation",
        help="Skip pre-execution pipeline validation",
    ),
) -> None:
    """Execute a DOT pipeline from start node to exit node.

    Runs the Attractor pipeline engine against FILE, executing each node's
    handler in graph order.  Checkpoints are saved atomically after every node
    so that ``--resume`` can pick up where a crashed run left off.

    Examples:

    \\b
        # Fresh run
        cobuilder pipeline run .claude/attractor/pipelines/my-pipeline.dot

        # Resume a crashed run
        cobuilder pipeline run .claude/attractor/pipelines/my-pipeline.dot \\
            --resume .claude/attractor/pipelines/my-pipeline-run-20260228T120000Z

        # Emit checkpoint JSON for scripting
        cobuilder pipeline run my-pipeline.dot --json
    """
    import asyncio

    from cobuilder.engine.checkpoint import CheckpointGraphMismatchError
    from cobuilder.engine.exceptions import (
        CheckpointVersionError,
        HandlerError,
        LoopDetectedError,
        NoEdgeError,
        ValidationError,
    )
    from cobuilder.engine.parser import ParseError
    from cobuilder.engine.runner import EngineRunner

    if not Path(file).exists():
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)

    runner = EngineRunner(
        dot_path=file,
        run_dir=resume,
        pipelines_dir=pipelines_dir,
        max_node_visits=max_visits,
        skip_validation=skip_validation,
    )

    try:
        checkpoint = asyncio.run(runner.run())
    except ValidationError as exc:
        typer.echo(f"Validation error: {exc}", err=True)
        raise typer.Exit(2)
    except ParseError as exc:
        typer.echo(f"Parse error: {exc}", err=True)
        raise typer.Exit(2)
    except CheckpointVersionError as exc:
        typer.echo(f"Checkpoint version mismatch: {exc}", err=True)
        raise typer.Exit(3)
    except CheckpointGraphMismatchError as exc:
        typer.echo(f"Pipeline DOT changed since checkpoint: {exc}", err=True)
        raise typer.Exit(3)
    except LoopDetectedError as exc:
        typer.echo(f"Loop detected: {exc}", err=True)
        raise typer.Exit(4)
    except NoEdgeError as exc:
        typer.echo(f"No edge: {exc}", err=True)
        raise typer.Exit(5)
    except HandlerError as exc:
        typer.echo(f"Handler error: {exc}", err=True)
        raise typer.Exit(6)
    except NotImplementedError as exc:
        typer.echo(f"Not implemented: {exc}", err=True)
        raise typer.Exit(7)
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)

    if json_output:
        typer.echo(checkpoint.model_dump_json(indent=2))
    else:
        completed = len(checkpoint.completed_nodes)
        typer.echo(
            f"Pipeline '{checkpoint.pipeline_id}' complete — "
            f"{completed} node(s) executed.  "
            f"Run dir: {checkpoint.run_dir}"
        )

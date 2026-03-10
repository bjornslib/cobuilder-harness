#!/usr/bin/env python3
"""Attractor DOT Pipeline Promise Initializer.

Reads a pipeline.dot and generates cs-promise initialization commands.
For each hexagon (validation) node: outputs a cs-promise --meet prerequisite.
For the graph's promise_id: outputs cs-init and cs-promise --create commands.

Usage:
    python3 init_promise.py pipeline.dot
    python3 init_promise.py pipeline.dot --execute
    python3 init_promise.py pipeline.dot --json
    python3 init_promise.py --help

Output (default):
    Shell commands to stdout that can be piped to bash:
        python3 init_promise.py pipeline.dot | bash
"""

import argparse
import json
import os
import re
import sys
from typing import Any

# Ensure sibling imports work

from cobuilder.attractor.parser import parse_dot, parse_file

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def extract_promise_info(data: dict[str, Any]) -> dict[str, Any]:
    """Extract promise-related information from parsed DOT data.

    Returns a dict with:
        - prd_ref: PRD reference from graph
        - graph_label: initiative label
        - promise_id: existing promise_id (may be empty)
        - acceptance_criteria: list of {ac_id, description, gate, mode, bead_id}
        - codergen_nodes: list of implementation nodes with promise_ac refs
    """
    graph_attrs = data.get("graph_attrs", {})
    nodes = data.get("nodes", [])

    info: dict[str, Any] = {
        "prd_ref": graph_attrs.get("prd_ref", ""),
        "graph_label": graph_attrs.get("label", "").replace("\\n", " "),
        "promise_id": graph_attrs.get("promise_id", ""),
        "acceptance_criteria": [],
        "codergen_nodes": [],
    }

    # Collect unique promise_ac values from codergen nodes
    seen_acs: set[str] = set()

    for node in nodes:
        attrs = node["attrs"]
        handler = attrs.get("handler", "")
        promise_ac = attrs.get("promise_ac", "")

        if handler == "codergen" and promise_ac:
            info["codergen_nodes"].append({
                "node_id": node["id"],
                "bead_id": attrs.get("bead_id", ""),
                "label": attrs.get("label", "").replace("\\n", " "),
                "worker_type": attrs.get("worker_type", ""),
                "acceptance": attrs.get("acceptance", ""),
                "promise_ac": promise_ac,
            })
            if promise_ac not in seen_acs:
                seen_acs.add(promise_ac)

    # Collect validation gates (hexagons) grouped by promise_ac
    for node in nodes:
        attrs = node["attrs"]
        handler = attrs.get("handler", "")

        if handler == "wait.human":
            gate = attrs.get("gate", "")
            mode = attrs.get("mode", "")
            bead_id = attrs.get("bead_id", "")
            promise_ac = attrs.get("promise_ac", "")

            info["acceptance_criteria"].append({
                "node_id": node["id"],
                "gate": gate,
                "mode": mode,
                "bead_id": bead_id,
                "promise_ac": promise_ac,
                "label": attrs.get("label", "").replace("\\n", " "),
            })

    return info


def generate_shell_commands(info: dict[str, Any]) -> list[str]:
    """Generate shell commands for promise initialization.

    Returns a list of shell command strings.
    """
    commands: list[str] = []
    prd_ref = info["prd_ref"]
    label = info["graph_label"] or prd_ref

    # Step 1: Initialize session
    slug = re.sub(r"[^a-z0-9]+", "-", prd_ref.lower()).strip("-")
    commands.append(f"# === Attractor Pipeline Promise Initialization ===")
    commands.append(f"# PRD: {prd_ref}")
    commands.append(f"# Generated from pipeline.dot")
    commands.append(f"#")
    commands.append(f"")
    commands.append(f"# Step 1: Initialize session")
    commands.append(f'eval "$(cs-init --initiative {slug})"')
    commands.append(f"")

    # Step 2: Create promise with ACs derived from codergen nodes
    # Each unique promise_ac becomes an AC on the promise
    ac_descriptions: list[str] = []
    seen_acs: dict[str, str] = {}

    for cg in info["codergen_nodes"]:
        pac = cg["promise_ac"]
        if pac in seen_acs:
            continue
        desc = cg.get("acceptance") or cg.get("label", f"Task {pac}")
        # Clean up for shell
        desc = desc.replace('"', '\\"').replace("'", "'\\''")
        ac_descriptions.append(desc)
        seen_acs[pac] = desc

    # Add a final AC for graph-level validation
    ac_descriptions.append("All pipeline nodes validated (triple-gate verification)")

    commands.append(f"# Step 2: Create promise with acceptance criteria")
    safe_label = label.replace('"', '\\"')
    create_cmd = f'cs-promise --create "{safe_label}"'
    for ac_desc in ac_descriptions:
        create_cmd += f' \\\n    --ac "{ac_desc}"'
    commands.append(create_cmd)
    commands.append(f"")

    # Step 3: Capture promise ID
    commands.append(f"# Step 3: Capture the promise ID")
    commands.append(f"# (cs-promise --create outputs the promise ID; capture it)")
    commands.append(f'PROMISE_ID=$(cs-promise --mine --json 2>/dev/null | python3 -c "')
    commands.append(f"import json, sys")
    commands.append(f"data = json.load(sys.stdin)")
    commands.append(f"if data: print(data[-1].get('id', ''))")
    commands.append(f'")')
    commands.append(f"")

    # Step 4: Start the promise
    commands.append(f"# Step 4: Start the promise")
    commands.append(f'cs-promise --start "$PROMISE_ID"')
    commands.append(f"")

    # Step 5: Output promise meeting commands for each validation gate
    commands.append(f"# Step 5: Validation gate commands (run as tasks complete)")
    commands.append(f"# These are templates - execute them as each task is validated:")
    commands.append(f"")

    for i, cg in enumerate(info["codergen_nodes"], 1):
        pac = cg["promise_ac"]
        task_label = cg.get("label", f"Task {i}")
        bead_id = cg.get("bead_id", "")
        safe_label = task_label.replace('"', '\\"')

        commands.append(f"# --- {pac}: {safe_label} ---")
        commands.append(
            f'# cs-promise --meet "$PROMISE_ID" --ac-id {pac} \\'
        )
        commands.append(
            f'#     --evidence "{safe_label} validated (bead: {bead_id})" --type test'
        )
        commands.append(f"")

    # Step 6: Final verification command
    commands.append(f"# Step 6: Final triple-gate verification (after all tasks validated)")
    commands.append(f'# cs-verify --promise "$PROMISE_ID" --type e2e \\')
    commands.append(f'#     --proof "All ACs met with evidence for {prd_ref}"')
    commands.append(f"")

    return commands


def generate_json_output(info: dict[str, Any]) -> dict:
    """Generate structured JSON output for programmatic consumption."""
    return {
        "prd_ref": info["prd_ref"],
        "graph_label": info["graph_label"],
        "existing_promise_id": info["promise_id"],
        "codergen_count": len(info["codergen_nodes"]),
        "validation_gate_count": len(info["acceptance_criteria"]),
        "acceptance_criteria": [
            {
                "ac_id": cg["promise_ac"],
                "description": cg.get("acceptance") or cg.get("label", ""),
                "bead_id": cg.get("bead_id", ""),
                "worker_type": cg.get("worker_type", ""),
            }
            for cg in info["codergen_nodes"]
        ],
        "validation_gates": [
            {
                "node_id": ac["node_id"],
                "gate": ac["gate"],
                "mode": ac["mode"],
                "bead_id": ac["bead_id"],
                "promise_ac": ac["promise_ac"],
            }
            for ac in info["acceptance_criteria"]
        ],
    }


def main() -> None:
    """CLI entry point."""
    ap = argparse.ArgumentParser(
        description="Generate cs-promise initialization commands from pipeline.dot."
    )
    ap.add_argument("file", help="Path to pipeline .dot file")
    ap.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output structured JSON instead of shell commands",
    )
    ap.add_argument(
        "--execute",
        action="store_true",
        help="Execute the initialization commands (cs-init + cs-promise --create + --start)",
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

    # Extract promise info
    info = extract_promise_info(data)

    if not info["codergen_nodes"]:
        print(
            "Warning: No codergen nodes found in pipeline. "
            "Promise will have no task-derived ACs.",
            file=sys.stderr,
        )

    # Output
    if args.json_output:
        result = generate_json_output(info)
        print(json.dumps(result, indent=2))
    else:
        commands = generate_shell_commands(info)
        output = "\n".join(commands)
        print(output)

        if args.execute:
            print("\n# --- Executing initialization commands ---", file=sys.stderr)
            import subprocess
            from pathlib import Path

            # Resolve cs-* script paths: prefer absolute path, fall back to PATH
            def _cs_bin(name: str) -> str:
                """Return absolute path to a cs-* script if it exists, else bare name."""
                # Try relative to this script's location (../completion-state/)
                candidate = Path(SCRIPT_DIR).parent / "completion-state" / name
                if candidate.exists():
                    return str(candidate)
                # Try CLAUDE_PROJECT_DIR
                proj = os.environ.get("CLAUDE_PROJECT_DIR", "")
                if proj:
                    candidate = Path(proj) / ".claude" / "scripts" / "completion-state" / name
                    if candidate.exists():
                        return str(candidate)
                return name  # fallback to PATH

            # Only execute the safe initialization commands (not the templates)
            slug = re.sub(r"[^a-z0-9]+", "-", info["prd_ref"].lower()).strip("-")

            # cs-init
            print(f"Executing: cs-init --initiative {slug}", file=sys.stderr)
            result = subprocess.run(
                [_cs_bin("cs-init"), "--initiative", slug],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(f"cs-init failed: {result.stderr}", file=sys.stderr)
                sys.exit(1)
            if result.stdout.strip():
                # eval the output for environment setup
                print(f"cs-init output: {result.stdout.strip()}", file=sys.stderr)

            # cs-promise --create
            label = info["graph_label"] or info["prd_ref"]
            create_cmd = [_cs_bin("cs-promise"), "--create", label]
            for cg in info["codergen_nodes"]:
                ac_desc = cg.get("acceptance") or cg.get("label", "")
                if ac_desc:
                    create_cmd.extend(["--ac", ac_desc])
            create_cmd.extend(["--ac", "All pipeline nodes validated (triple-gate verification)"])

            print(f"Executing: cs-promise --create ...", file=sys.stderr)
            result = subprocess.run(
                create_cmd,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(f"cs-promise --create failed: {result.stderr}", file=sys.stderr)
                sys.exit(1)
            print(f"cs-promise output: {result.stdout.strip()}", file=sys.stderr)

            print("\nInitialization complete.", file=sys.stderr)
            print(
                "Run the validation gate commands as tasks complete.",
                file=sys.stderr,
            )


if __name__ == "__main__":
    main()

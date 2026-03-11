#!/usr/bin/env python3
"""Attractor CLI — Main entry point for pipeline management tools.

Dispatches subcommands for parsing, validating, querying status,
transitioning states, checkpointing, generating, annotating,
initializing completion promises, and displaying lifecycle dashboards
for Attractor DOT pipelines.

Usage:
    python3 cli.py parse <file.dot> [--output json]
    python3 cli.py validate <file.dot> [--output json] [--strict]
    python3 cli.py status <file.dot> [--json] [--filter=<status>] [--summary]
    python3 cli.py transition <file.dot> <node_id> <new_status> [--dry-run]
    python3 cli.py checkpoint save <file.dot> [--output=<path>]
    python3 cli.py checkpoint restore <checkpoint.json> [--output=<file.dot>]
    python3 cli.py generate --prd <PRD-REF> [--output pipeline.dot] [--scaffold]
    python3 cli.py annotate <file.dot> [--output annotated.dot]
    python3 cli.py init-promise <file.dot> [--json]
    python3 cli.py dashboard <file.dot> [--output json] [--checkpoint <path>]
    python3 cli.py node <file.dot> list|add|remove|modify [...]
    python3 cli.py edge <file.dot> list|add|remove [...]
    python3 cli.py lint [--verbose] [--json] [--fix]
    python3 cli.py gardener [--execute] [--report] [--json]
    python3 cli.py install-hooks
    python3 cli.py run <file.dot> [--execute] [--channel <name>] [--json]
    python3 cli.py guardian status|list|verify-chain|audit [...]
    python3 cli.py agents list|show|mark-crashed|mark-terminated [...]
    python3 cli.py merge-queue list|enqueue|process [...]
    python3 cli.py --help
"""

import os
import subprocess
import sys

# Package directory (used for resolving adjacent script paths)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Doc-gardener scripts live in the sibling doc-gardener/ directory
DOC_GARDENER_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "doc-gardener")
# .claude/ directory is the parent of scripts/
CLAUDE_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))


def main() -> None:
    """Dispatch to the appropriate subcommand."""
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        print()
        print("Subcommands:")
        print("  parse         Parse a DOT file into structured data")
        print("  validate      Validate a DOT file against schema rules")
        print("  status        Display node status table")
        print("  transition    Advance a node's status")
        print("  checkpoint    Save/restore pipeline state")
        print("  generate      Generate pipeline.dot from beads task data (--scaffold for skeleton)")
        print("  annotate      Cross-reference pipeline.dot with beads")
        print("  init-promise  Generate cs-promise commands from pipeline.dot")
        print("  dashboard     Show unified lifecycle dashboard (stage, progress, nodes)")
        print("  node          CRUD operations for nodes (list/add/remove/modify)")
        print("  edge          CRUD operations for edges (list/add/remove)")
        print("  lint          Lint .claude/ documentation (delegates to doc-gardener)")
        print("  gardener      Run doc-gardener remediation (delegates to doc-gardener)")
        print("  install-hooks Install pre-push git hook for doc-gardener")
        print("  run           Run the production pipeline runner agent")
        print("  guardian      System 3 read-only monitor for pipeline runner state")
        print("  agents        Inspect and manage agent identity records")
        print("  merge-queue   Manage the sequential merge queue (list/enqueue/process)")
        print()
        print("Run 'cli.py <command> --help' for subcommand details.")
        sys.exit(0)

    command = sys.argv[1]
    # Remove the subcommand from argv so sub-modules see correct args
    sys.argv = [sys.argv[0]] + sys.argv[2:]

    if command == "parse":
        from cobuilder.attractor.parser import main as parser_main
        parser_main()
    elif command == "validate":
        from cobuilder.attractor.validator import main as validator_main
        validator_main()
    elif command == "status":
        from cobuilder.attractor.status import main as status_main
        status_main()
    elif command == "transition":
        from cobuilder.attractor.transition import main as transition_main
        transition_main()
    elif command == "checkpoint":
        from cobuilder.attractor.checkpoint import main as checkpoint_main
        checkpoint_main()
    elif command == "generate":
        from cobuilder.attractor.generate import main as generate_main
        generate_main()
    elif command == "annotate":
        from cobuilder.attractor.annotate import main as annotate_main
        annotate_main()
    elif command in ("init-promise", "init_promise"):
        from cobuilder.attractor.init_promise import main as init_promise_main
        init_promise_main()
    elif command == "dashboard":
        from cobuilder.attractor.dashboard import main as dashboard_main
        dashboard_main()
    elif command == "node":
        from cobuilder.attractor.node_ops import main as node_ops_main
        node_ops_main()
    elif command == "edge":
        from cobuilder.attractor.edge_ops import main as edge_ops_main
        edge_ops_main()
    elif command == "lint":
        lint_script = os.path.join(DOC_GARDENER_DIR, "lint.py")
        result = subprocess.run(
            [sys.executable, lint_script] + sys.argv[1:],
        )
        sys.exit(result.returncode)
    elif command == "gardener":
        gardener_script = os.path.join(DOC_GARDENER_DIR, "gardener.py")
        result = subprocess.run(
            [sys.executable, gardener_script] + sys.argv[1:],
        )
        sys.exit(result.returncode)
    elif command in ("install-hooks", "install_hooks"):
        _install_hooks()
    elif command == "run":
        from cobuilder.attractor.pipeline_runner import main as pipeline_runner_main
        pipeline_runner_main()
    elif command == "guardian":
        from cobuilder.attractor.guardian_hooks import main as guardian_main
        guardian_main()
    elif command == "agents":
        from cobuilder.attractor.agents_cmd import main as agents_main
        agents_main()
    elif command in ("merge-queue", "merge_queue"):
        from cobuilder.attractor.merge_queue_cmd import main as merge_queue_main
        merge_queue_main()
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print("Run 'cli.py --help' for available commands.", file=sys.stderr)
        sys.exit(1)


def _install_hooks() -> None:
    """Install doc-gardener pre-push hook into the git hooks directory."""
    import stat

    force = "--force" in sys.argv
    # Strip --force from argv so it doesn't confuse downstream code
    sys.argv = [a for a in sys.argv if a != "--force"]

    # Resolve project root from script location (works regardless of caller's CWD).
    # CLAUDE_DIR = .claude/, so its parent is the project root.
    project_root = os.path.dirname(CLAUDE_DIR)

    # Find the git common dir (works in worktrees too)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
            cwd=project_root,  # Use project root, not caller's CWD
        )
        git_common_dir = result.stdout.strip()
    except subprocess.CalledProcessError:
        print("Error: Not inside a git repository.", file=sys.stderr)
        sys.exit(1)

    # Make git_common_dir absolute (git may return relative path like "../.git")
    if not os.path.isabs(git_common_dir):
        git_common_dir = os.path.normpath(os.path.join(project_root, git_common_dir))

    hooks_dir = os.path.join(git_common_dir, "hooks")
    os.makedirs(hooks_dir, exist_ok=True)

    hook_source = os.path.join(CLAUDE_DIR, "hooks", "doc-gardener-pre-push.sh")
    hook_dest = os.path.join(hooks_dir, "pre-push")

    if not os.path.exists(hook_source):
        print(f"Error: Hook source not found: {hook_source}", file=sys.stderr)
        sys.exit(1)

    # Make the source script executable
    current_mode = os.stat(hook_source).st_mode
    os.chmod(hook_source, current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Check for existing hook — do not silently overwrite (R1.4 / AC-3)
    if os.path.lexists(hook_dest):
        if os.path.islink(hook_dest):
            existing_target = os.path.realpath(hook_dest)
            expected_target = os.path.realpath(hook_source)
            if existing_target == expected_target:
                print("Pre-push hook already installed (up to date).")
                return
            # Different symlink target — safe to replace
            print(f"Updating pre-push hook symlink (was -> {os.readlink(hook_dest)})")
            os.remove(hook_dest)
        else:
            # Regular file — refuse to overwrite without --force
            if not force:
                print(
                    "Warning: A pre-push hook already exists and is not a symlink:",
                    file=sys.stderr,
                )
                print(f"  {hook_dest}", file=sys.stderr)
                print(
                    "Use 'cli.py install-hooks --force' to replace it.",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"Replacing existing pre-push hook (--force)")
            os.remove(hook_dest)

    # Create symlink: hooks/pre-push -> (canonical path to source)
    # Use realpath() instead of abspath() so symlinks are resolved to the
    # main working tree.  This keeps the hook functional even after a
    # worktree is removed (abspath would resolve to the worktree CWD).
    source_real = os.path.realpath(hook_source)
    os.symlink(source_real, hook_dest)

    print(f"Installed pre-push hook:")
    print(f"  {hook_dest} -> {source_real}")


if __name__ == "__main__":
    main()

"""merge_queue_cmd.py — CLI subcommand for merge queue management.

Provides:
    merge-queue list                    - show current queue state
    merge-queue enqueue <node> <branch> - add to queue
    merge-queue process                 - process next entry

Usage (via cli.py):
    python3 cli.py merge-queue list
    python3 cli.py merge-queue enqueue impl_auth feature/impl_auth --repo-root /path/to/repo
    python3 cli.py merge-queue process
"""

from __future__ import annotations

import json
import os
import sys


import cobuilder.attractor.merge_queue as merge_queue


_USAGE = """\
Usage:
  merge-queue list                                      Show current queue state
  merge-queue enqueue <node_id> <branch> --repo-root <path>  Add entry to queue
  merge-queue process                                   Process next entry in queue
"""


def _cmd_list() -> None:
    """Show current merge queue state."""
    state = merge_queue._read_queue()
    print(json.dumps(state, indent=2))


def _cmd_enqueue(node_id: str, branch: str, repo_root: str) -> None:
    """Add an entry to the merge queue."""
    try:
        entry = merge_queue.enqueue(node_id=node_id, branch=branch, repo_root=repo_root)
        print(json.dumps({"status": "ok", "entry": entry}))
        sys.exit(0)
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}), file=sys.stderr)
        sys.exit(1)


def _cmd_process() -> None:
    """Process the next entry in the merge queue."""
    try:
        result = merge_queue.process_next()
        print(json.dumps(result))
        if result.get("success"):
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}), file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """Dispatch merge-queue subcommand."""
    argv = sys.argv[1:]  # cli.py already stripped the 'merge-queue' token

    if not argv or argv[0] in ("-h", "--help"):
        print(_USAGE)
        sys.exit(0)

    sub = argv[0]
    rest = argv[1:]

    if sub == "list":
        _cmd_list()

    elif sub == "enqueue":
        if len(rest) < 2:
            print("Usage: merge-queue enqueue <node_id> <branch> --repo-root <path>", file=sys.stderr)
            sys.exit(1)
        node_id = rest[0]
        branch = rest[1]
        repo_root = None
        if "--repo-root" in rest:
            idx = rest.index("--repo-root")
            if idx + 1 < len(rest):
                repo_root = rest[idx + 1]
        if repo_root is None:
            print("Error: --repo-root is required for enqueue", file=sys.stderr)
            sys.exit(1)
        _cmd_enqueue(node_id, branch, repo_root)

    elif sub == "process":
        _cmd_process()

    else:
        print(f"Unknown merge-queue subcommand: {sub}", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

"""agents_cmd.py — CLI subcommand for inspecting and managing agent identities.

Provides:
    agents list                          - table of all agent identities
    agents show <role> <name>            - full JSON for one agent
    agents mark-crashed <role> <name>    - force-mark an agent as crashed
    agents mark-terminated <role> <name> - force-mark an agent as terminated

Usage (via cli.py):
    python3 cli.py agents list
    python3 cli.py agents show orchestrator impl_auth
    python3 cli.py agents mark-crashed runner impl_auth
    python3 cli.py agents mark-terminated orchestrator impl_auth
"""

from __future__ import annotations

import json
import os
import sys

# Ensure attractor package is importable regardless of invocation CWD.

import cobuilder.attractor.identity_registry as identity_registry


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------

def _cmd_list(as_json: bool = False, stale_only: int | None = None) -> None:
    """Print a table of all agent identities."""
    agents = identity_registry.list_all()

    if stale_only is not None:
        import time
        from datetime import datetime
        cutoff = time.time() - stale_only

        def _ts(agent: dict) -> float:
            hb = agent.get("last_heartbeat")
            if not hb:
                return 0.0
            try:
                return datetime.fromisoformat(hb.replace("Z", "+00:00")).timestamp()
            except Exception:
                return 0.0

        agents = [a for a in agents if _ts(a) < cutoff]

    if as_json:
        print(json.dumps(agents))
        return

    if not agents:
        print("No agent identities found.")
        return

    # Header
    header = f"{'ROLE':<16} {'NAME':<24} {'STATUS':<12} {'LAST HEARTBEAT':<22} {'AGENT ID'}"
    print(header)
    print("-" * len(header))

    for agent in sorted(agents, key=lambda a: a.get("created_at", "")):
        role = agent.get("role", "?")[:16]
        name = agent.get("name", "?")[:24]
        status = agent.get("status", "?")[:12]
        heartbeat = (agent.get("last_heartbeat") or "")[:22]
        agent_id = agent.get("agent_id", "")
        print(f"{role:<16} {name:<24} {status:<12} {heartbeat:<22} {agent_id}")


def _cmd_show(role: str, name: str) -> None:
    """Print full JSON for a single agent identity."""
    data = identity_registry.read_identity(role, name)
    if data is None:
        print(f"No identity found for {role}/{name}.", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(data, indent=2))


def _cmd_mark_crashed(role: str, name: str) -> None:
    """Force-mark an agent as crashed."""
    try:
        data = identity_registry.mark_crashed(role, name)
        print(f"Marked {role}/{name} as crashed.")
        print(f"  crashed_at: {data['crashed_at']}")
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


def _cmd_mark_terminated(role: str, name: str) -> None:
    """Force-mark an agent as terminated."""
    try:
        data = identity_registry.mark_terminated(role, name)
        print(f"Marked {role}/{name} as terminated.")
        print(f"  terminated_at: {data['terminated_at']}")
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

_USAGE = """\
Usage:
  agents list [--json] [--stale-only <N>]  List all agent identities (table or JSON)
  agents show <role> <name>                 Show full JSON for one agent
  agents mark-crashed <role> <name>         Mark agent as crashed
  agents mark-terminated <role> <name>      Mark agent as terminated
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Dispatch agents subcommand."""
    argv = sys.argv[1:]  # cli.py already stripped the 'agents' token

    if not argv or argv[0] in ("-h", "--help"):
        print(_USAGE)
        sys.exit(0)

    sub = argv[0]
    rest = argv[1:]

    if sub == "list":
        import argparse as _ap
        lp = _ap.ArgumentParser()
        lp.add_argument("--json", action="store_true", dest="as_json")
        lp.add_argument("--stale-only", type=int, dest="stale_only")
        largs = lp.parse_args(rest)
        _cmd_list(as_json=largs.as_json, stale_only=largs.stale_only)

    elif sub == "show":
        if len(rest) < 2:
            print("Usage: agents show <role> <name>", file=sys.stderr)
            sys.exit(1)
        _cmd_show(rest[0], rest[1])

    elif sub in ("mark-crashed", "mark_crashed"):
        if len(rest) < 2:
            print("Usage: agents mark-crashed <role> <name>", file=sys.stderr)
            sys.exit(1)
        _cmd_mark_crashed(rest[0], rest[1])

    elif sub in ("mark-terminated", "mark_terminated"):
        if len(rest) < 2:
            print("Usage: agents mark-terminated <role> <name>", file=sys.stderr)
            sys.exit(1)
        _cmd_mark_terminated(rest[0], rest[1])

    else:
        print(f"Unknown agents subcommand: {sub}", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

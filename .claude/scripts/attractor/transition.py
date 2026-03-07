#!/usr/bin/env python3
"""Attractor DOT Pipeline State Transition.

Advance a node's status through the defined lifecycle:
    pending -> active -> impl_complete -> validated
                                       -> failed -> active (retry)

Hexagon (validation gate) nodes use a shorter path:
    pending -> active -> validated (pass)
                      -> failed   (fail)

Usage:
    python3 transition.py <file.dot> <node_id> <new_status> [--dry-run]
    python3 transition.py --help
"""

import argparse
import contextlib
import datetime
import fcntl
import json
import os
import re
import sys

from parser import parse_file


# --- Valid transitions ---
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"active"},
    "active": {"impl_complete", "validated", "failed"},  # hexagons go active→validated/failed directly
    "impl_complete": {"validated", "failed", "active"},  # active for retry after fail
    "failed": {"active"},
    "validated": {"accepted"},  # validated -> accepted (pipeline runner final step)
    "accepted": set(),  # terminal
}

# Status -> fillcolor mapping from schema
STATUS_COLORS: dict[str, str] = {
    "pending": "lightyellow",
    "active": "lightblue",
    "impl_complete": "lightsalmon",
    "validated": "lightgreen",
    "failed": "lightcoral",
    "accepted": "palegreen",
}


# ---------------------------------------------------------------------------
# File-level helpers: locking, JSONL logging, finalize signal files
# ---------------------------------------------------------------------------

_SIGNALS_DIR_NAME = "signals"
_TRANSITIONS_LOG_SUFFIX = ".transitions.jsonl"


@contextlib.contextmanager
def _dot_file_lock(dot_file: str):
    """Acquire an exclusive file lock on *dot_file* to prevent concurrent writes.

    Creates a companion `<dot_file>.lock` file for the duration of the
    critical section and removes it on exit (AC-4).
    """
    lock_path = dot_file + ".lock"
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
        try:
            os.unlink(lock_path)
        except OSError:
            pass


def _append_transition_jsonl(dot_file: str, entry: dict) -> None:
    """Append *entry* as a single JSON line to the transitions log alongside *dot_file*."""
    log_path = dot_file + _TRANSITIONS_LOG_SUFFIX
    with open(log_path, "a") as fh:
        fh.write(json.dumps(entry) + "\n")


def _write_finalize_signal(
    dot_file: str, node_id: str, new_status: str, node_attrs: dict, session_id: str = ""
) -> str | None:
    """Write a signal file when a finalize/exit node reaches 'active' or 'validated' (AC-3).

    Signal files are placed in a ``signals/`` directory adjacent to *dot_file*.
    If *session_id* is provided it is included in the signal payload so that
    the receiving session can filter signals by origin.

    Returns the signal file path if written, else None.
    """
    node_shape = node_attrs.get("shape", "")
    node_handler = node_attrs.get("handler", "")
    is_finalize = node_shape == "Msquare" or node_handler == "exit"
    if not is_finalize or new_status not in ("active", "validated"):
        return None

    dot_dir = os.path.dirname(os.path.abspath(dot_file))
    signals_dir = os.path.join(dot_dir, _SIGNALS_DIR_NAME)
    os.makedirs(signals_dir, exist_ok=True)

    dot_basename = os.path.splitext(os.path.basename(dot_file))[0]
    signal_name = f"{dot_basename}-{node_id}-{new_status}.signal"
    signal_path = os.path.join(signals_dir, signal_name)
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    payload: dict = {
        "timestamp": timestamp,
        "node_id": node_id,
        "status": new_status,
        "dot_file": dot_file,
    }
    if session_id:
        payload["session_id"] = session_id
    with open(signal_path, "w") as fh:
        fh.write(json.dumps(payload))
    return signal_path


def check_transition(current: str, target: str) -> tuple[bool, str]:
    """Check if a status transition is valid.

    Returns (is_valid, reason).
    """
    if current not in VALID_TRANSITIONS:
        return False, f"Unknown current status '{current}'"
    if target not in VALID_TRANSITIONS and target not in {
        s for ss in VALID_TRANSITIONS.values() for s in ss
    }:
        return False, f"Unknown target status '{target}'"
    if target in VALID_TRANSITIONS.get(current, set()):
        return True, f"{current} -> {target}"
    return False, (
        f"Illegal transition: {current} -> {target}. "
        f"Valid transitions from '{current}': {sorted(VALID_TRANSITIONS.get(current, set()))}"
    )


def apply_transition(
    dot_content: str, node_id: str, new_status: str
) -> tuple[str, str]:
    """Apply a status transition to a DOT file string.

    Finds the node definition and updates its status attribute.
    Also updates fillcolor to match the new status.

    For finalize nodes (shape=Msquare or handler=exit), enforces the finalize
    gate: all hexagon (wait.human) nodes must be 'validated' before the
    finalize node can be activated.

    Returns (updated_content, log_message).
    """
    # First parse to validate the node exists and get current status
    from parser import parse_dot

    data = parse_dot(dot_content)
    node = None
    for n in data["nodes"]:
        if n["id"] == node_id:
            node = n
            break

    if node is None:
        raise ValueError(f"Node '{node_id}' not found in pipeline")

    current_status = node["attrs"].get("status", "pending")
    valid, reason = check_transition(current_status, new_status)
    if not valid:
        raise ValueError(reason)

    # --- Finalize gate check (R4.7) ---
    # Block activation of finalize nodes (Msquare / handler=exit) unless ALL
    # hexagon nodes in the graph are already 'validated'.
    if new_status == "active":
        node_shape = node["attrs"].get("shape", "")
        node_handler = node["attrs"].get("handler", "")
        if node_shape == "Msquare" or node_handler == "exit":
            gate_ok, blocked = check_finalize_gate(dot_content)
            if not gate_ok:
                raise ValueError(
                    f"Finalize gate blocked: the following hexagon validation "
                    f"nodes are not yet validated: {blocked}. "
                    "All hexagon nodes must reach 'validated' before the "
                    "finalize node can be activated."
                )

    # Update the status attribute in the DOT content
    updated = _update_node_attr(dot_content, node_id, "status", new_status)

    # Update fillcolor to match new status
    new_color = STATUS_COLORS.get(new_status, "")
    if new_color:
        updated = _update_node_attr(updated, node_id, "fillcolor", new_color)
        # Ensure style=filled is present
        if "style" not in node["attrs"]:
            updated = _add_node_attr(updated, node_id, "style", "filled")

    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    log_msg = f"[{timestamp}] {node_id}: {current_status} -> {new_status}"

    return updated, log_msg


# ---------------------------------------------------------------------------
# Graph-inspection helpers (used by cascade functions)
# ---------------------------------------------------------------------------


def _get_node(dot_content: str, node_id: str) -> dict | None:
    """Return the parsed node dict for node_id, or None if not found."""
    from parser import parse_dot

    data = parse_dot(dot_content)
    for node in data["nodes"]:
        if node["id"] == node_id:
            return node
    return None


def find_activation_targets(dot_content: str, codergen_id: str) -> list[str]:
    """Find hexagon nodes that should be activated when a codergen node
    reaches impl_complete.

    Follows edges whose label contains 'impl_complete' and whose destination
    has shape=hexagon.

    Returns a list of hexagon node IDs.
    """
    from parser import parse_dot

    data = parse_dot(dot_content)
    # Build a quick shape lookup
    shape_of: dict[str, str] = {
        n["id"]: n["attrs"].get("shape", "") for n in data["nodes"]
    }
    targets = []
    for edge in data["edges"]:
        if edge["src"] != codergen_id:
            continue
        label = edge["attrs"].get("label", "")
        if "impl_complete" in label and shape_of.get(edge["dst"]) == "hexagon":
            targets.append(edge["dst"])
    return targets


def find_decision_diamond(dot_content: str, hexagon_id: str) -> str | None:
    """Find the decision diamond (handler=conditional) immediately downstream
    of a hexagon node.

    Returns the diamond node ID, or None if not found.
    """
    from parser import parse_dot

    data = parse_dot(dot_content)
    handler_of: dict[str, str] = {
        n["id"]: n["attrs"].get("handler", "") for n in data["nodes"]
    }
    for edge in data["edges"]:
        if edge["src"] == hexagon_id:
            dst = edge["dst"]
            if handler_of.get(dst) == "conditional":
                return dst
    return None


def route_from_diamond(
    dot_content: str, diamond_id: str, condition: str
) -> list[str]:
    """Find destination node IDs from a decision diamond for a given condition.

    Args:
        dot_content: DOT file content.
        diamond_id:  ID of the diamond (conditional) node.
        condition:   'pass' or 'fail'.

    Returns a list of destination node IDs whose edge has condition==condition.
    """
    from parser import parse_dot

    data = parse_dot(dot_content)
    destinations = []
    for edge in data["edges"]:
        if edge["src"] == diamond_id and edge["attrs"].get("condition") == condition:
            destinations.append(edge["dst"])
    return destinations


def check_finalize_gate(dot_content: str) -> tuple[bool, list[str]]:
    """Check whether all hexagon (validation gate) nodes are 'validated'.

    This is the finalize gate guard (R4.7): the finalize node may only be
    activated when every hexagon node in the pipeline has reached 'validated'.

    Returns:
        (all_validated: bool, not_validated: list[str])
        all_validated is True when every hexagon node is 'validated'.
        not_validated lists the IDs of hexagon nodes that are NOT yet
        'validated'.
    """
    from parser import parse_dot

    data = parse_dot(dot_content)
    not_validated: list[str] = []
    for node in data["nodes"]:
        if node["attrs"].get("shape") == "hexagon":
            status = node["attrs"].get("status", "pending")
            if status != "validated":
                not_validated.append(node["id"])
    return len(not_validated) == 0, not_validated


# ---------------------------------------------------------------------------
# Cascade operations (Epic 4: R4.1, R4.5)
# ---------------------------------------------------------------------------


def activate_hexagon_cascade(
    dot_content: str, codergen_id: str
) -> tuple[str, list[str]]:
    """Activate hexagon validation gates downstream of a codergen node that
    has just reached impl_complete (R4.1).

    For each edge from codergen_id whose label contains 'impl_complete' and
    whose destination has shape=hexagon, transitions that hexagon from
    whatever status it currently holds to 'active'.

    Returns:
        (updated_content, activated_ids)
        updated_content: DOT string with all cascade transitions applied.
        activated_ids:   List of hexagon node IDs that were activated.
    """
    targets = find_activation_targets(dot_content, codergen_id)
    content = dot_content
    activated: list[str] = []
    for hexagon_id in targets:
        try:
            content, _log = apply_transition(content, hexagon_id, "active")
            activated.append(hexagon_id)
        except ValueError:
            # Already active or in a non-pending state — skip silently
            pass
    return content, activated


def route_decision_cascade(
    dot_content: str, hexagon_id: str, result: str
) -> tuple[str, list[str]]:
    """Route through a decision diamond after a hexagon validation completes.

    Implements R4.5:
      - result='pass': finds the diamond immediately downstream of hexagon_id,
        then activates all pass-side destinations.  If a destination is a
        finalize node (shape=Msquare or handler=exit) the finalize gate is
        enforced automatically by apply_transition.
      - result='fail': finds the fail-side destinations (usually the paired
        codergen node), transitions them back to 'active' for retry.  If the
        codergen is currently 'impl_complete', it is first moved to 'failed'
        and then to 'active'.

    Args:
        dot_content: DOT file content.
        hexagon_id:  ID of the hexagon node whose validation just concluded.
        result:      'pass' or 'fail'.

    Returns:
        (updated_content, affected_ids)
        updated_content: DOT string with all cascade transitions applied.
        affected_ids:    List of node IDs that were modified.
    """
    from parser import parse_dot

    if result not in ("pass", "fail"):
        raise ValueError(f"result must be 'pass' or 'fail', got '{result}'")

    diamond_id = find_decision_diamond(dot_content, hexagon_id)
    if diamond_id is None:
        return dot_content, []

    destinations = route_from_diamond(dot_content, diamond_id, result)
    content = dot_content
    affected: list[str] = []

    for dst_id in destinations:
        node = _get_node(content, dst_id)
        if node is None:
            continue

        dst_shape = node["attrs"].get("shape", "")
        dst_handler = node["attrs"].get("handler", "")
        current_status = node["attrs"].get("status", "pending")

        if result == "pass":
            # Activate the next stage node.
            # apply_transition enforces the finalize gate for Msquare/exit
            # nodes automatically.
            try:
                content, _log = apply_transition(content, dst_id, "active")
                affected.append(dst_id)
            except ValueError as exc:
                # Re-raise finalize gate errors so callers are aware
                raise ValueError(
                    f"Cannot advance to '{dst_id}' on pass: {exc}"
                ) from exc

        else:  # result == "fail"
            # Reset codergen (or other retry targets) to 'active'.
            # If it's currently 'impl_complete', step through 'failed' first
            # so the audit trail is preserved.
            if current_status == "impl_complete":
                content, _log = apply_transition(content, dst_id, "failed")
                current_status = "failed"
            if current_status in ("failed", "pending"):
                try:
                    content, _log = apply_transition(content, dst_id, "active")
                    affected.append(dst_id)
                except ValueError:
                    pass  # Already active or invalid — skip
            # If already 'active', nothing to do

    return content, affected


def _find_node_block(content: str, node_id: str) -> tuple[int, int]:
    """Find the start and end positions of a node's definition block.

    Returns (start, end) positions, or (-1, -1) if not found.
    """
    # Look for patterns like: node_id [ ... ] or node_id [...];
    # Must handle multiline blocks
    pattern = re.compile(
        r"(?<!\w)(" + re.escape(node_id) + r")\s*\[",
        re.MULTILINE,
    )

    for m in pattern.finditer(content):
        # Verify this isn't an edge (no -> before it)
        before = content[: m.start()].rstrip()
        if before.endswith("->"):
            continue

        # Find matching ]
        bracket_start = content.index("[", m.start())
        depth = 0
        pos = bracket_start
        while pos < len(content):
            if content[pos] == "[":
                depth += 1
            elif content[pos] == "]":
                depth -= 1
                if depth == 0:
                    # Include trailing semicolon if present
                    end = pos + 1
                    if end < len(content) and content[end] == ";":
                        end += 1
                    return m.start(), end
            elif content[pos] == '"':
                pos += 1
                while pos < len(content) and content[pos] != '"':
                    if content[pos] == "\\":
                        pos += 1
                    pos += 1
            pos += 1

    return -1, -1


def _update_node_attr(content: str, node_id: str, attr: str, value: str) -> str:
    """Update a single attribute within a node's block."""
    start, end = _find_node_block(content, node_id)
    if start == -1:
        raise ValueError(f"Cannot find node block for '{node_id}'")

    block = content[start:end]

    # Try to replace existing attribute
    # Match: attr="old_value" or attr=old_value
    attr_pattern = re.compile(
        r'(' + re.escape(attr) + r')\s*=\s*"[^"]*"'
    )
    m = attr_pattern.search(block)
    if m:
        new_block = block[: m.start()] + f'{attr}="{value}"' + block[m.end() :]
        return content[:start] + new_block + content[end:]

    # Try unquoted: attr=value
    attr_pattern_unquoted = re.compile(
        r'(' + re.escape(attr) + r')\s*=\s*(\S+)'
    )
    m = attr_pattern_unquoted.search(block)
    if m:
        new_block = block[: m.start()] + f'{attr}="{value}"' + block[m.end() :]
        return content[:start] + new_block + content[end:]

    # Attribute not found — add it
    return _add_node_attr(content, node_id, attr, value)


def _add_node_attr(content: str, node_id: str, attr: str, value: str) -> str:
    """Add a new attribute to a node's block."""
    start, end = _find_node_block(content, node_id)
    if start == -1:
        raise ValueError(f"Cannot find node block for '{node_id}'")

    block = content[start:end]

    # Find the closing bracket and insert before it
    bracket_pos = block.rfind("]")
    if bracket_pos == -1:
        raise ValueError(f"Malformed node block for '{node_id}'")

    # Determine indentation from existing attributes
    new_attr = f'\n        {attr}="{value}"'
    new_block = block[:bracket_pos] + new_attr + "\n    " + block[bracket_pos:]
    return content[:start] + new_block + content[end:]


_SUBCOMMANDS = {"transition", "activate-hexagon", "route-decision", "check-finalize-gate"}


def main() -> None:
    """CLI entry point."""
    # --- Legacy-mode detection (MUST happen before argparse is built) ---
    # Old callers use: transition.py <file> <node_id> <status> [--dry-run] [--output …]
    # New callers use: transition.py <file> <sub-command> …
    # Detect legacy mode by checking whether sys.argv[2] (if present) is a known
    # sub-command name.  If not, route directly to _cmd_transition with a minimal
    # parser so argparse never tries to interpret node_id as a sub-command.
    _argv = sys.argv[1:]  # drop script name
    if len(_argv) >= 3 and _argv[1] not in _SUBCOMMANDS:
        # Legacy positional: file node_id new_status [--dry-run] [--output …]
        leg = argparse.ArgumentParser(
            description="Transition a node's status in an Attractor DOT pipeline."
        )
        leg.add_argument("file")
        leg.add_argument("node_id")
        leg.add_argument(
            "new_status",
            choices=["pending", "active", "impl_complete", "validated", "failed", "accepted"],
        )
        leg.add_argument("--dry-run", action="store_true")
        leg.add_argument("--output", choices=["json", "text"], default="text")
        leg.add_argument(
            "--session-id",
            default="",
            dest="session_id",
            help="Session ID embedded in finalize signal files (AC-3)",
        )
        largs = leg.parse_args(_argv)
        try:
            with open(largs.file, "r") as f:
                content = f.read()
        except FileNotFoundError:
            print(f"Error: File not found: {largs.file}", file=sys.stderr)
            sys.exit(1)
        _cmd_transition(largs, content)
        return

    ap = argparse.ArgumentParser(
        description="Transition a node's status in an Attractor DOT pipeline."
    )
    ap.add_argument("file", help="Path to .dot file")

    subparsers = ap.add_subparsers(dest="command", help="sub-command")

    # --- default transition sub-command (also the implicit default) ---
    trans_p = subparsers.add_parser(
        "transition",
        help="Apply a status transition to a node (default command).",
    )
    trans_p.add_argument("node_id", help="Node ID to transition")
    trans_p.add_argument(
        "new_status",
        choices=["pending", "active", "impl_complete", "validated", "failed", "accepted"],
        help="Target status",
    )
    trans_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing",
    )
    trans_p.add_argument(
        "--output",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )
    trans_p.add_argument(
        "--session-id",
        default="",
        dest="session_id",
        help="Session ID embedded in finalize signal files (AC-3)",
    )

    # --- activate-hexagon sub-command (R4.1 cascade) ---
    ah_p = subparsers.add_parser(
        "activate-hexagon",
        help=(
            "Activate hexagon validation gates downstream of a codergen node "
            "that has just reached impl_complete (R4.1 cascade)."
        ),
    )
    ah_p.add_argument("node_id", help="Codergen node ID that reached impl_complete")
    ah_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing",
    )
    ah_p.add_argument(
        "--output",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )
    ah_p.add_argument(
        "--session-id",
        default="",
        dest="session_id",
        help="Session ID embedded in finalize signal files (AC-3)",
    )

    # --- route-decision sub-command (R4.5 cascade) ---
    rd_p = subparsers.add_parser(
        "route-decision",
        help=(
            "Route through a decision diamond after hexagon validation "
            "(R4.5 cascade). 'pass' activates the next stage; 'fail' resets "
            "the codergen for retry."
        ),
    )
    rd_p.add_argument("node_id", help="Hexagon node ID whose validation concluded")
    rd_p.add_argument(
        "result",
        choices=["pass", "fail"],
        help="Validation result: 'pass' or 'fail'",
    )
    rd_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing",
    )
    rd_p.add_argument(
        "--output",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )
    rd_p.add_argument(
        "--session-id",
        default="",
        dest="session_id",
        help="Session ID embedded in finalize signal files (AC-3)",
    )

    # --- check-finalize-gate sub-command (R4.7) ---
    fg_p = subparsers.add_parser(
        "check-finalize-gate",
        help=(
            "Check whether the finalize gate is open (all hexagons validated). "
            "Exits with code 0 if open, 1 if blocked."
        ),
    )
    fg_p.add_argument(
        "--output",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )

    args = ap.parse_args()

    if args.command is None:
        ap.print_help()
        sys.exit(1)

    # --- load file ---
    try:
        with open(args.file, "r") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    # -------------------------------------------------------------------
    # Dispatch sub-commands
    # -------------------------------------------------------------------

    if args.command == "transition":
        _cmd_transition(args, content)

    elif args.command == "activate-hexagon":
        _cmd_activate_hexagon(args, content)

    elif args.command == "route-decision":
        _cmd_route_decision(args, content)

    elif args.command == "check-finalize-gate":
        _cmd_check_finalize_gate(args, content)

    else:
        ap.print_help()
        sys.exit(1)


# ---------------------------------------------------------------------------
# Sub-command handlers
# ---------------------------------------------------------------------------


def _cmd_transition(args: argparse.Namespace, content: str) -> None:
    """Handle the 'transition' sub-command (or legacy positional mode)."""
    dry_run: bool = getattr(args, "dry_run", False)
    output: str = getattr(args, "output", "text")
    session_id: str = getattr(args, "session_id", "")

    # Fetch node attrs before transition for AC-3 signal check
    from parser import parse_dot as _parse_dot

    _pre_data = _parse_dot(content)
    _pre_node_attrs: dict = {}
    for _n in _pre_data["nodes"]:
        if _n["id"] == args.node_id:
            _pre_node_attrs = _n["attrs"]
            break

    try:
        updated, log_msg = apply_transition(content, args.node_id, args.new_status)
    except ValueError as e:
        if output == "json":
            print(json.dumps({"success": False, "error": str(e)}, indent=2))
        else:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if dry_run:
        if output == "json":
            print(json.dumps({"success": True, "dry_run": True, "log": log_msg}, indent=2))
        else:
            print(f"DRY RUN: {log_msg}")
            print("(no changes written)")
    else:
        with _dot_file_lock(args.file):  # AC-4: exclusive lock during write
            with open(args.file, "w") as f:
                f.write(updated)

            # JSONL transition log
            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            _append_transition_jsonl(
                args.file,
                {
                    "timestamp": timestamp,
                    "file": args.file,
                    "command": "transition",
                    "node_id": args.node_id,
                    "new_status": args.new_status,
                    "log": log_msg,
                },
            )

            # AC-3: finalize signal file
            _sig = _write_finalize_signal(
                args.file, args.node_id, args.new_status, _pre_node_attrs,
                session_id=session_id,
            )

        if output == "json":
            result = {"success": True, "log": log_msg, "file": args.file}
            if _sig:
                result["signal_file"] = _sig
            print(json.dumps(result, indent=2))
        else:
            print(f"Transition applied: {log_msg}")
            print(f"Updated: {args.file}")
            if _sig:
                print(f"Signal written: {_sig}")


def _cmd_activate_hexagon(args: argparse.Namespace, content: str) -> None:
    """Handle the 'activate-hexagon' sub-command (R4.1 cascade)."""
    dry_run: bool = getattr(args, "dry_run", False)
    output: str = getattr(args, "output", "text")

    try:
        updated, activated = activate_hexagon_cascade(content, args.node_id)
    except ValueError as e:
        if output == "json":
            print(json.dumps({"success": False, "error": str(e)}, indent=2))
        else:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not activated:
        msg = f"No hexagon nodes found downstream of '{args.node_id}' via impl_complete edge."
        if output == "json":
            print(json.dumps({"success": True, "activated": [], "note": msg}, indent=2))
        else:
            print(msg)
        return

    if dry_run:
        if output == "json":
            print(json.dumps({"success": True, "dry_run": True, "activated": activated}, indent=2))
        else:
            print(f"DRY RUN: would activate hexagons: {activated}")
            print("(no changes written)")
    else:
        with _dot_file_lock(args.file):  # AC-4: exclusive lock during write
            with open(args.file, "w") as f:
                f.write(updated)

            # JSONL transition log
            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            _append_transition_jsonl(
                args.file,
                {
                    "timestamp": timestamp,
                    "file": args.file,
                    "command": "activate-hexagon",
                    "node_id": args.node_id,
                    "activated": activated,
                },
            )

        if output == "json":
            print(json.dumps({"success": True, "activated": activated, "file": args.file}, indent=2))
        else:
            for hid in activated:
                print(f"Hexagon activated: {hid}")
            print(f"Updated: {args.file}")


def _cmd_route_decision(args: argparse.Namespace, content: str) -> None:
    """Handle the 'route-decision' sub-command (R4.5 cascade)."""
    dry_run: bool = getattr(args, "dry_run", False)
    output: str = getattr(args, "output", "text")

    try:
        updated, affected = route_decision_cascade(content, args.node_id, args.result)
    except ValueError as e:
        if output == "json":
            print(json.dumps({"success": False, "error": str(e)}, indent=2))
        else:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not affected:
        msg = (
            f"No nodes affected by '{args.result}' routing from hexagon '{args.node_id}'. "
            "Check that a decision diamond exists downstream with matching condition edges."
        )
        if output == "json":
            print(json.dumps({"success": True, "affected": [], "note": msg}, indent=2))
        else:
            print(msg)
        return

    if dry_run:
        if output == "json":
            print(json.dumps({"success": True, "dry_run": True, "result": args.result, "affected": affected}, indent=2))
        else:
            print(f"DRY RUN: '{args.result}' routing would affect: {affected}")
            print("(no changes written)")
    else:
        with _dot_file_lock(args.file):  # AC-4: exclusive lock during write
            with open(args.file, "w") as f:
                f.write(updated)

            # JSONL transition log
            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            _append_transition_jsonl(
                args.file,
                {
                    "timestamp": timestamp,
                    "file": args.file,
                    "command": "route-decision",
                    "node_id": args.node_id,
                    "result": args.result,
                    "affected": affected,
                },
            )

        if output == "json":
            print(json.dumps({"success": True, "result": args.result, "affected": affected, "file": args.file}, indent=2))
        else:
            for nid in affected:
                print(f"Node updated: {nid}")
            print(f"Updated: {args.file}")


def _cmd_check_finalize_gate(args: argparse.Namespace, content: str) -> None:
    """Handle the 'check-finalize-gate' sub-command (R4.7)."""
    output: str = getattr(args, "output", "text")

    gate_ok, blocked = check_finalize_gate(content)

    if output == "json":
        print(
            json.dumps(
                {
                    "gate_open": gate_ok,
                    "blocked_hexagons": blocked,
                },
                indent=2,
            )
        )
    else:
        if gate_ok:
            print("Finalize gate: OPEN — all hexagon nodes are validated.")
        else:
            print("Finalize gate: BLOCKED")
            print(f"  Not yet validated: {blocked}")

    sys.exit(0 if gate_ok else 1)


if __name__ == "__main__":
    main()

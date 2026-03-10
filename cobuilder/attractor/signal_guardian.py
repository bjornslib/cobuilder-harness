"""signal_guardian.py — Write signal to Guardian (from Runner).

Usage:
    python signal_guardian.py <SIGNAL_TYPE> --node <node_id>
        [--evidence <path>] [--question <text>] [--options <json>]
        [--commit <hash>] [--summary <text>] [--reason <text>]
        [--last-output <text>] [--duration <seconds>]
        [--target {guardian,terminal}]

Output (stdout, JSON):
    {"status": "ok", "signal_file": "<path>", "signal_type": "<type>"}

On error:
    {"status": "error", "message": "<error>"}
    exits with code 1
"""

from __future__ import annotations

import argparse
import json
import sys
import os

# Ensure the attractor package directory is on sys.path

from cobuilder.attractor.signal_protocol import write_signal  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="signal_guardian.py",
        description="Write a signal to Guardian from Runner.",
    )
    parser.add_argument(
        "signal_type",
        metavar="SIGNAL_TYPE",
        help="Signal type (e.g., NEEDS_REVIEW, STUCK, COMPLETE)",
    )
    parser.add_argument("--node", required=True, help="Node identifier")
    parser.add_argument("--evidence", default=None, help="Path to evidence file/dir")
    parser.add_argument("--question", default=None, help="Question for Guardian")
    parser.add_argument(
        "--options",
        default=None,
        help="JSON-encoded options dict (e.g., '{\"a\": 1}')",
    )
    parser.add_argument("--commit", default=None, help="Git commit hash")
    parser.add_argument("--summary", default=None, help="Summary text")
    parser.add_argument("--reason", default=None, help="Reason text")
    parser.add_argument("--last-output", default=None, dest="last_output",
                        help="Last output text from orchestrator")
    parser.add_argument("--duration", default=None, type=float,
                        help="Duration in seconds")
    parser.add_argument("--target", default="guardian", choices=["guardian", "terminal"],
                        help="Signal target (default: guardian)")

    args = parser.parse_args()

    payload: dict = {"node_id": args.node}
    if args.evidence is not None:
        payload["evidence_path"] = args.evidence
    if args.question is not None:
        payload["question"] = args.question
    if args.options is not None:
        try:
            payload["options"] = json.loads(args.options)
        except json.JSONDecodeError as exc:
            print(json.dumps({"status": "error", "message": f"Invalid --options JSON: {exc}"}))
            sys.exit(1)
    if args.commit is not None:
        payload["commit_hash"] = args.commit
    if args.summary is not None:
        payload["summary"] = args.summary
    if args.reason is not None:
        payload["reason"] = args.reason
    if args.last_output is not None:
        payload["last_output"] = args.last_output
    if args.duration is not None:
        payload["duration_seconds"] = args.duration

    try:
        signal_file = write_signal(
            source="runner",
            target=args.target,
            signal_type=args.signal_type,
            payload=payload,
        )
        print(json.dumps({
            "status": "ok",
            "signal_file": signal_file,
            "signal_type": args.signal_type,
        }))
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

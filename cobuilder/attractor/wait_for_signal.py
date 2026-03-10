"""wait_for_signal.py — Block until a signal for a target layer appears.

Usage:
    python wait_for_signal.py --target <layer> [--timeout <seconds>] [--poll <seconds>]

Output (stdout, JSON):
    The signal JSON dict parsed from the signal file.

On timeout or error:
    {"status": "error", "message": "<error>"}
    exits with code 1
"""

from __future__ import annotations

import argparse
import json
import sys
import os


from cobuilder.attractor.signal_protocol import wait_for_signal  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="wait_for_signal.py",
        description="Block until a signal for a target layer appears.",
    )
    parser.add_argument("--target", required=True, help="Target layer to wait for")
    parser.add_argument(
        "--timeout", type=float, default=300.0, help="Timeout in seconds (default: 300)"
    )
    parser.add_argument(
        "--poll", type=float, default=5.0, help="Poll interval in seconds (default: 5)"
    )

    args = parser.parse_args()

    try:
        signal_data = wait_for_signal(
            target_layer=args.target,
            timeout=args.timeout,
            poll_interval=args.poll,
        )
        print(json.dumps(signal_data))
    except TimeoutError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        sys.exit(1)
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

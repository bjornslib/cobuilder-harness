"""read_signal.py — Parse and print a signal file.

Usage:
    python read_signal.py <signal_file_path>

Output (stdout, JSON):
    The signal JSON dict parsed from the signal file.

On error:
    {"status": "error", "message": "<error>"}
    exits with code 1
"""

from __future__ import annotations

import argparse
import json
import sys
import os


from cobuilder.engine.signal_protocol import read_signal  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="read_signal.py",
        description="Parse and print a signal file as JSON.",
    )
    parser.add_argument("signal_file", metavar="signal_file_path",
                        help="Path to the signal JSON file")

    args = parser.parse_args()

    try:
        data = read_signal(args.signal_file)
        print(json.dumps(data))
    except FileNotFoundError:
        print(json.dumps({
            "status": "error",
            "message": f"Signal file not found: {args.signal_file}",
        }))
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(json.dumps({
            "status": "error",
            "message": f"Invalid JSON in signal file: {exc}",
        }))
        sys.exit(1)
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

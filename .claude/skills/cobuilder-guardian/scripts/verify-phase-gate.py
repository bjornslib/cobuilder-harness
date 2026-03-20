#!/usr/bin/env python3
"""Verify guardian phase gates before proceeding to the next phase.

Usage:
    python3 verify-phase-gate.py --prd PRD-XXX-001 --gate G1
    python3 verify-phase-gate.py --prd PRD-XXX-001 --gate G0
    python3 verify-phase-gate.py --prd PRD-XXX-001 --gate G2

Gates:
    G0: Phase 0 → Phase 1 (PRD exists, pipeline created)
    G1: Phase 1 → Phase 2 (acceptance tests exist with .feature files)
    G2: Phase 2/3 → Phase 4 (implementation complete)

Exit codes:
    0 = gate passes
    1 = gate fails (missing prerequisites)
    2 = invalid arguments
"""

import argparse
import glob
import os
import sys


def find_project_root():
    """Walk up from CWD to find a directory with .claude/ or acceptance-tests/."""
    cwd = os.getcwd()
    for d in [cwd] + [os.path.dirname(cwd)] * 5:
        if os.path.isdir(os.path.join(d, "acceptance-tests")) or os.path.isdir(
            os.path.join(d, ".claude")
        ):
            return d
        d = os.path.dirname(d)
    return cwd


def check_g0(prd_id: str, root: str) -> tuple[bool, list[str]]:
    """Gate G0: Phase 0 → Phase 1. PRD exists and pipeline created."""
    issues = []

    # Check PRD exists (either new or legacy location)
    prd_patterns = [
        os.path.join(root, f"docs/prds/{prd_id}.md"),
        os.path.join(root, f"docs/specs/business/{prd_id}.md"),
    ]
    prd_found = any(os.path.isfile(p) for p in prd_patterns)
    if not prd_found:
        # Also try glob for partial matches
        for pattern in [f"docs/prds/{prd_id}*.md", f"docs/specs/business/{prd_id}*.md"]:
            if glob.glob(os.path.join(root, pattern)):
                prd_found = True
                break
    if not prd_found:
        issues.append(f"PRD file not found for {prd_id} in docs/prds/ or docs/specs/business/")

    # Check pipeline exists
    pipeline_patterns = glob.glob(os.path.join(root, ".pipelines/pipelines/*.dot"))
    if not pipeline_patterns:
        issues.append("No pipeline DOT file found in .pipelines/pipelines/")

    return len(issues) == 0, issues


def check_g1(prd_id: str, root: str) -> tuple[bool, list[str]]:
    """Gate G1: Phase 1 → Phase 2. Acceptance tests exist."""
    issues = []
    at_dir = os.path.join(root, f"acceptance-tests/{prd_id}")

    if not os.path.isdir(at_dir):
        issues.append(
            f"Acceptance test directory not found: acceptance-tests/{prd_id}/\n"
            f"  Run Phase 1 first: Skill(\"acceptance-test-writer\") with {prd_id}"
        )
        return False, issues

    feature_files = glob.glob(os.path.join(at_dir, "*.feature"))
    if not feature_files:
        issues.append(
            f"No .feature files in acceptance-tests/{prd_id}/\n"
            f"  Directory exists but is empty. Run Phase 1 to create Gherkin tests."
        )
        return False, issues

    manifest = os.path.join(at_dir, "manifest.yaml")
    if not os.path.isfile(manifest):
        issues.append(
            f"manifest.yaml missing in acceptance-tests/{prd_id}/\n"
            f"  Run: scripts/generate-manifest.sh {prd_id}"
        )
        # This is a warning, not a blocker
        print(f"WARNING: {issues[-1]}", file=sys.stderr)
        issues.pop()  # Remove from blocking issues

    return len(issues) == 0, issues


def check_g2(prd_id: str, root: str) -> tuple[bool, list[str]]:
    """Gate G2: Phase 2/3 → Phase 4. Implementation signals completion."""
    issues = []

    # Check for signal files indicating completion
    signal_dirs = glob.glob(os.path.join(root, ".pipelines/pipelines/signals/*/"))
    if not signal_dirs:
        issues.append("No signal directories found — pipeline may not have started")

    return len(issues) == 0, issues


def main():
    parser = argparse.ArgumentParser(description="Verify guardian phase gates")
    parser.add_argument("--prd", required=True, help="PRD identifier (e.g., PRD-AUTH-001)")
    parser.add_argument("--gate", required=True, choices=["G0", "G1", "G2"], help="Gate to check")
    parser.add_argument("--root", help="Project root directory (auto-detected if not specified)")
    args = parser.parse_args()

    root = args.root or find_project_root()
    gate_checks = {"G0": check_g0, "G1": check_g1, "G2": check_g2}

    passed, issues = gate_checks[args.gate](args.prd, root)

    if passed:
        print(f"PASS: Gate {args.gate} for {args.prd}")
        sys.exit(0)
    else:
        print(f"FAIL: Gate {args.gate} for {args.prd}", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

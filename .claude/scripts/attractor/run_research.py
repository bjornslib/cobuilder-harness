#!/usr/bin/env python3
"""Research Node Agent — validates implementation approach against current docs.

Runs BEFORE codergen nodes to ensure the Solution Design document contains
current API patterns and framework best practices. Uses Context7 and Perplexity
via the Claude Code SDK (Haiku model) to research, then updates the SD directly.

Usage:
    python3 run_research.py --node <node_id> --prd <prd_ref> \
        --solution-design <path> --target-dir <path> \
        [--frameworks <comma-separated>] [--model haiku] \
        [--max-turns 15] [--dry-run]

Output (stdout JSON):
    {"status": "ok", "node": "<id>", "evidence_path": "<path>",
     "sd_updated": true, "sd_path": "<path>", "summary": "..."}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Load environment variables from .claude/attractor/.env
try:
    from dispatch_worker import load_attractor_env
    os.environ.update(load_attractor_env())
except ImportError:
    # If dispatch_worker is not available in this context, that's OK
    pass

def _get_default_model():
    """Get the default model from environment or fallback to hardcoded value."""
    return os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")


DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
DEFAULT_MAX_TURNS = 15


def build_research_prompt(
    node_id: str,
    prd_ref: str,
    sd_path: str,
    frameworks: list[str],
    evidence_dir: str,
    prd_path: str | None = None,
) -> str:
    """Build the prompt that instructs Haiku to research and update the SD.

    Args:
        node_id: Pipeline node identifier.
        prd_ref: PRD reference (e.g. "PRD-AUTH-001").
        sd_path: Absolute path to the Solution Design document.
        frameworks: List of frameworks/libraries to validate.
        evidence_dir: Directory to write research evidence JSON.
        prd_path: Optional absolute path to the PRD document for additional context.

    Returns:
        Formatted research prompt string.
    """
    frameworks_section = ""
    if frameworks:
        fw_list = "\n".join(f"  - {fw}" for fw in frameworks)
        frameworks_section = f"""
## Frameworks to Research
{fw_list}

For each framework above:
1. Call mcp__context7__resolve-library-id with the framework name to find the library ID
2. Call mcp__context7__query-docs with the resolved library ID and relevant topics (API patterns, migration guides, breaking changes)
3. Call mcp__perplexity__perplexity_ask to cross-validate: "What are the current best practices and latest API patterns for <framework> as of 2026?"
4. If the research reveals multiple viable approaches or conflicting best practices,
   use mcp__perplexity__perplexity_reason to analyze tradeoffs:
   "Given these approaches for <framework feature>: [A] vs [B], analyze the tradeoffs
   considering performance, maintainability, and current ecosystem support as of 2026"

These MCP tools are directly available — you do NOT need to use ToolSearch to discover them.
"""

    prd_section = ""
    if prd_path:
        prd_section = f"""
2. Read the PRD document at {prd_path} to understand the full context, requirements, and acceptance criteria that the SD must satisfy
"""
        sd_step = "3"
    else:
        sd_step = "2"

    return f"""\
You are a Research Agent validating implementation patterns before coding begins.

## Your Task
- Node ID: {node_id}
- PRD Reference: {prd_ref}
- Solution Design: {sd_path}
{f'- PRD Document: {prd_path}' if prd_path else ''}

## Instructions

1. Read the Solution Design document at {sd_path}
{prd_section}
{frameworks_section}
## Update the Solution Design

After researching, update the SD file using the Edit tool:
- Correct any outdated API references
- Update code examples to current versions
- Add annotations like "Validated via Context7/Perplexity on {datetime.now(timezone.utc).strftime('%Y-%m-%d')}" where you make changes
- Do NOT rewrite the entire document — only update sections with outdated patterns

## Write Evidence

After updating (or confirming the SD is current), write a JSON evidence file to:
{evidence_dir}/research-findings.json

The JSON must have this exact structure:
{{
  "node_id": "{node_id}",
  "downstream_codergen": "<the codergen node this research feeds into>",
  "timestamp": "<ISO 8601 timestamp>",
  "sd_path": "{sd_path}",
  "sd_updated": <true if you made changes, false if SD was already current>,
  "frameworks_queried": {json.dumps(frameworks)},
  "findings": [
    {{
      "framework": "<name>",
      "source": "context7 or perplexity",
      "current_version": "<latest version found>",
      "summary": "<what you found>",
      "sd_sections_updated": ["<section names you changed>"]
    }}
  ],
  "sd_changes_summary": "<one-line summary of all changes made>",
  "gotchas": ["<any important warnings for downstream implementers>"]
}}

If the SD file does not exist at the specified path, report status=error.
If research tools are unavailable, still write evidence with what you could determine from the SD alone.

## Hindsight Reflection (Final Step)

After writing evidence, use Hindsight to persist learnings in the target repo's memory bank.

The Hindsight MCP tools (mcp__hindsight__reflect, mcp__hindsight__retain, mcp__hindsight__recall) are directly available.

1. **Recall** relevant research patterns — Before reflecting, surface prior learnings:
   Call mcp__hindsight__recall with a query like:
   "Research findings for {frameworks}, API pattern validations, Context7/Perplexity results for {prd_ref}"
   This surfaces any prior research agent learnings for these frameworks, helping you
   avoid re-discovering known gotchas and build on previous sessions' work.
2. **Reflect** — Formulate your own query based on what you actually discovered during
   research. Your query should capture the most useful question a future research agent
   would need answered about these frameworks in this project's context. Consider:
   - Breaking changes or migration gotchas you uncovered
   - Patterns that were outdated vs. confirmed current
   - Interactions between frameworks that surprised you
   Call mcp__hindsight__reflect with your crafted query and budget="mid".
3. **Retain** — Synthesize a concise memory from your findings. Focus on what would
   save a future agent the most time: version-specific gotchas, deprecated patterns
   you corrected, and any discrepancies between the SD's assumptions and current reality.
   Call mcp__hindsight__retain with:
   - content: Your synthesized memory (not a copy of the evidence JSON — distill it)
   - context: "research-gate"
   - Include metadata: {{"node_id": "{node_id}", "prd_ref": "{prd_ref}", "frameworks": {json.dumps(frameworks)}}}

This ensures future research cycles benefit from what you learned today.

Begin by reading the Solution Design document.
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="run_research.py",
        description="Research Node Agent: validates approach against current documentation.",
    )
    parser.add_argument("--node", required=True, help="Pipeline node ID")
    parser.add_argument("--prd", required=True, help="PRD reference")
    parser.add_argument("--solution-design", required=True, dest="solution_design",
                        help="Path to Solution Design document")
    parser.add_argument("--target-dir", required=True, dest="target_dir",
                        help="Target implementation directory")
    parser.add_argument("--prd-path", default="", dest="prd_path",
                        help="Path to PRD document for additional context")
    parser.add_argument("--frameworks", default="",
                        help="Comma-separated list of frameworks to research")
    parser.add_argument("--model", default=_get_default_model(),
                        help="Claude model (default: claude-haiku-4-5-20251001 or ANTHROPIC_MODEL env var)")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS,
                        dest="max_turns",
                        help=f"Max SDK turns (default: {DEFAULT_MAX_TURNS})")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="Output the prompt without running SDK")
    return parser.parse_args(argv)


async def _run_research(prompt: str, options: object) -> dict:
    """Run the research agent via claude_code_sdk and return parsed result."""
    from claude_code_sdk import query, ResultMessage

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            return {
                "is_error": message.is_error,
                "num_turns": message.num_turns,
                "cost_usd": message.total_cost_usd,
            }
    return {"is_error": True, "num_turns": 0, "cost_usd": 0}


def main(argv: list[str] | None = None) -> None:
    """Entry point: build prompt, run SDK, output result JSON."""
    args = parse_args(argv)

    # Parse frameworks
    frameworks = [f.strip() for f in args.frameworks.split(",") if f.strip()] if args.frameworks else []

    # Resolve paths
    sd_path = os.path.abspath(args.solution_design)
    target_dir = os.path.abspath(args.target_dir)
    prd_path = os.path.abspath(args.prd_path) if args.prd_path else None
    evidence_dir = os.path.join(target_dir, ".claude", "evidence", args.node)
    os.makedirs(evidence_dir, exist_ok=True)

    prompt = build_research_prompt(
        node_id=args.node,
        prd_ref=args.prd,
        sd_path=sd_path,
        frameworks=frameworks,
        evidence_dir=evidence_dir,
        prd_path=prd_path,
    )

    # Dry-run: output prompt and exit
    if args.dry_run:
        result = {
            "dry_run": True,
            "node": args.node,
            "prd": args.prd,
            "prd_path": prd_path,
            "sd_path": sd_path,
            "frameworks": frameworks,
            "model": args.model,
            "max_turns": args.max_turns,
            "evidence_dir": evidence_dir,
            "prompt_length": len(prompt),
            "prompt": prompt,
        }
        print(json.dumps(result, indent=2))
        sys.exit(0)

    # Build SDK options
    from claude_code_sdk import ClaudeCodeOptions

    options = ClaudeCodeOptions(
        allowed_tools=[
            "Bash", "Read", "Edit", "Write", "ToolSearch",
            # MCP: research tools (Context7 for docs, Perplexity for cross-validation)
            "mcp__context7__resolve-library-id",
            "mcp__context7__query-docs",
            "mcp__perplexity__perplexity_ask",
            "mcp__perplexity__perplexity_reason",
            "mcp__perplexity__perplexity_research",
            # MCP: memory persistence (Hindsight for cross-session learnings)
            "mcp__hindsight__reflect",
            "mcp__hindsight__retain",
            "mcp__hindsight__recall",
        ],
        system_prompt="You are a research agent that validates implementation patterns against current documentation.",
        cwd=target_dir,
        model=args.model,
        max_turns=args.max_turns,
        env={"CLAUDECODE": ""},
    )

    # Run the agent
    try:
        sdk_result = asyncio.run(_run_research(prompt, options))
    except Exception as exc:
        error_result = {
            "status": "error",
            "node": args.node,
            "error": str(exc),
        }
        print(json.dumps(error_result, indent=2))
        sys.exit(1)

    # Check if evidence was written
    evidence_path = os.path.join(evidence_dir, "research-findings.json")
    sd_updated = False
    summary = "Research completed but no evidence file found"

    if os.path.exists(evidence_path):
        try:
            with open(evidence_path) as f:
                evidence = json.load(f)
            sd_updated = evidence.get("sd_updated", False)
            summary = evidence.get("sd_changes_summary", "No changes summary provided")
        except (json.JSONDecodeError, OSError):
            summary = "Evidence file exists but could not be parsed"

    output = {
        "status": "error" if sdk_result.get("is_error") else "ok",
        "node": args.node,
        "evidence_path": evidence_path,
        "sd_updated": sd_updated,
        "sd_path": sd_path,
        "summary": summary,
        "cost_usd": sdk_result.get("cost_usd", 0),
        "num_turns": sdk_result.get("num_turns", 0),
    }
    print(json.dumps(output, indent=2))
    sys.exit(0 if output["status"] == "ok" else 1)


if __name__ == "__main__":
    main()

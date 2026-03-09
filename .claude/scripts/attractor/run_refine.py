#!/usr/bin/env python3
"""Refine Node Agent — rewrites SD with validated research findings.

Runs AFTER research nodes to transform inline research annotations into
production-quality Solution Design content. Uses Sonnet to read the research
evidence JSON, reflect via Hindsight, then rewrite the SD sections properly.

Usage:
    python3 run_refine.py --node <node_id> --prd <prd_ref> \
        --solution-design <path> --target-dir <path> \
        --evidence-path <path> \
        [--model claude-sonnet-4-6] [--max-turns 20] [--dry-run]

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
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")


DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
DEFAULT_MAX_TURNS = 20


def build_refine_prompt(
    node_id: str,
    prd_ref: str,
    sd_path: str,
    evidence_path: str,
    evidence_dir: str,
    prd_path: str | None = None,
) -> str:
    """Build the prompt that instructs Sonnet to refine the SD using research evidence.

    Args:
        node_id: Pipeline node identifier.
        prd_ref: PRD reference (e.g. "PRD-AUTH-001").
        sd_path: Absolute path to the Solution Design document.
        evidence_path: Absolute path to the upstream research evidence JSON.
        evidence_dir: Directory to write refine evidence JSON.
        prd_path: Optional absolute path to the PRD document for additional context.

    Returns:
        Formatted refine prompt string.
    """
    prd_section = ""
    if prd_path:
        prd_section = f"""
3. Read the PRD document at {prd_path} to understand the full requirements context
"""

    return f"""\
You are a Refine Agent that incorporates validated research findings into a Solution Design document.

## Your Task
- Node ID: {node_id}
- PRD Reference: {prd_ref}
- Solution Design: {sd_path}
- Research Evidence: {evidence_path}
{f'- PRD Document: {prd_path}' if prd_path else ''}

## Instructions

### Phase 1: Gather Context

1. Read the research evidence JSON at {evidence_path}
   - This contains findings from the upstream research agent: frameworks queried, versions found,
     SD sections updated, gotchas, and a changes summary
   - Pay special attention to the `findings` array and `gotchas` list

2. Read the Solution Design document at {sd_path}
   - The SD currently contains inline research annotations like:
     - `// Validated via Context7/Perplexity on YYYY-MM-DD`
     - `Note (YYYY-MM-DD Validation): ...`
     - Comments starting with research tool names
   - These are useful notes but NOT production-quality SD content
{prd_section}

### Phase 2: Reflect via Hindsight (MANDATORY — before making changes)

Before editing the SD, you MUST use Hindsight to reflect on what you've read. This ensures
you make informed, context-aware decisions about how to restructure the SD.

The Hindsight MCP tools (mcp__hindsight__reflect, mcp__hindsight__retain, mcp__hindsight__recall)
are directly available — you do NOT need ToolSearch.

1. **Reflect on the SD structure and research findings together**:
   Call mcp__hindsight__reflect with a query like:
   "Given the research findings for {prd_ref} — specifically the framework versions,
   API pattern changes, and gotchas discovered — what is the best way to restructure
   the Solution Design to incorporate these findings as first-class content?
   What patterns exist for clean SD organization in this project?"
   Use budget="high" for thorough reasoning.

2. **Recall relevant project patterns**:
   Call mcp__hindsight__recall with a query like:
   "Solution Design document patterns, SD restructuring conventions, research-to-SD integration"
   This surfaces any prior refine agent learnings or SD conventions.

Use the reflect and recall results to guide your editing decisions in Phase 3.

### Phase 3: Rewrite the Solution Design

If research findings present conflicting approaches or you need to make a judgment
call about which pattern to recommend in the SD, you may use
mcp__perplexity__perplexity_reason to reason through the tradeoffs before deciding.

For each research finding, determine the appropriate action:

- **Inline fix**: Small corrections (e.g., updated import path, version number)
  → Edit the specific line/section directly

- **Structural rewrite**: The finding reveals the approach needs rethinking
  → Rewrite the affected section with the finding as first-class content

- **New section**: The finding adds information not covered in the SD
  → Add a new section (e.g., "Implementation Notes", "Migration Considerations")

**Critical rules:**
- Remove ALL inline research annotations:
  - Lines matching `// Validated via Context7/Perplexity on ...`
  - Lines matching `// Note (YYYY-MM-DD Validation): ...`
  - Any comment that starts with tool names like `// Context7:`, `// Perplexity:`
  - Markdown blockquotes starting with `> Note (YYYY-MM-DD Validation):`
- Research findings should become NATURAL parts of the SD, not annotations
- Preserve the document's existing structure and voice
- If a finding confirms existing content is correct, remove the annotation but keep the content

### Phase 4: Write Evidence

After updating the SD, write a JSON evidence file to:
{evidence_dir}/refine-findings.json

The JSON must have this exact structure:
{{
  "node_id": "{node_id}",
  "timestamp": "<ISO 8601 timestamp>",
  "sd_path": "{sd_path}",
  "sd_updated": <true if you made changes, false if SD needed no changes>,
  "research_evidence_path": "{evidence_path}",
  "sections_rewritten": ["<section headings you rewrote entirely>"],
  "sections_patched": ["<section headings where you made inline fixes>"],
  "sections_added": ["<new section headings you added>"],
  "annotations_removed": <integer count of research annotations removed>,
  "refinement_summary": "<one-line summary of all changes made>",
  "remaining_concerns": ["<any issues you could not resolve>"]
}}

### Phase 5: Persist Learnings to Hindsight (Final Step)

1. **Retain** — Synthesize a concise memory from your refinement work. Focus on:
   - Which SD patterns worked well vs. needed restructuring
   - How research annotations were best integrated (inline fix vs. rewrite vs. new section)
   - Any gotchas about the document structure or project conventions
   Call mcp__hindsight__retain with:
   - content: Your synthesized memory (distilled insights, not a copy of evidence)
   - context: "refine-gate"
   - Include metadata: {{"node_id": "{node_id}", "prd_ref": "{prd_ref}"}}

2. **Reflect** — Final validation of your changes:
   Call mcp__hindsight__reflect with budget="mid" and a query about whether your
   changes are consistent with the project's SD conventions and the PRD requirements.

If the SD file does not exist at the specified path, report status=error in the evidence JSON.
If the research evidence file does not exist, report status=error.

Begin by reading the research evidence JSON.
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="run_refine.py",
        description="Refine Node Agent: rewrites SD with validated research findings.",
    )
    parser.add_argument("--node", required=True, help="Pipeline node ID")
    parser.add_argument("--prd", required=True, help="PRD reference")
    parser.add_argument("--solution-design", required=True, dest="solution_design",
                        help="Path to Solution Design document")
    parser.add_argument("--target-dir", required=True, dest="target_dir",
                        help="Target implementation directory")
    parser.add_argument("--evidence-path", required=True, dest="evidence_path",
                        help="Path to upstream research evidence JSON")
    parser.add_argument("--prd-path", default="", dest="prd_path",
                        help="Path to PRD document for additional context")
    parser.add_argument("--model", default=_get_default_model(),
                        help="Claude model (default: claude-sonnet-4-6 or ANTHROPIC_MODEL env var)")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS,
                        dest="max_turns",
                        help=f"Max SDK turns (default: {DEFAULT_MAX_TURNS})")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="Output the prompt without running SDK")
    return parser.parse_args(argv)


async def _run_refine(prompt: str, options: object) -> dict:
    """Run the refine agent via claude_code_sdk and return parsed result."""
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

    # Resolve paths
    sd_path = os.path.abspath(args.solution_design)
    target_dir = os.path.abspath(args.target_dir)
    evidence_path = os.path.abspath(args.evidence_path)
    prd_path = os.path.abspath(args.prd_path) if args.prd_path else None
    evidence_dir = os.path.join(target_dir, ".claude", "evidence", args.node)
    os.makedirs(evidence_dir, exist_ok=True)

    prompt = build_refine_prompt(
        node_id=args.node,
        prd_ref=args.prd,
        sd_path=sd_path,
        evidence_path=evidence_path,
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
            "evidence_path": evidence_path,
            "model": args.model,
            "max_turns": args.max_turns,
            "evidence_dir": evidence_dir,
            "prompt_length": len(prompt),
            "prompt": prompt,
        }
        print(json.dumps(result, indent=2))
        sys.exit(0)

    # Build SDK options — refine agent has restricted tools (no research tools)
    from claude_code_sdk import ClaudeCodeOptions

    options = ClaudeCodeOptions(
        allowed_tools=[
            "Read", "Edit", "Write",
            # LSP: type info, go-to-definition, diagnostics (for validating code references in SD)
            "LSP",
            # MCP: memory persistence (Hindsight for reflection and cross-session learnings)
            "mcp__hindsight__reflect",
            "mcp__hindsight__retain",
            "mcp__hindsight__recall",
            # MCP: reasoning tool for resolving conflicting research findings
            "mcp__perplexity__perplexity_reason",
            # MCP: Serena — navigate code to verify claims in Solution Design (read-only navigation)
            "mcp__serena__activate_project",
            "mcp__serena__check_onboarding_performed",
            "mcp__serena__find_symbol",
            "mcp__serena__search_for_pattern",
            "mcp__serena__get_symbols_overview",
            "mcp__serena__find_referencing_symbols",
            "mcp__serena__find_file",
        ],
        system_prompt="You are a refine agent that incorporates validated research findings into Solution Design documents.",
        cwd=target_dir,
        model=args.model,
        max_turns=args.max_turns,
        env={"CLAUDECODE": ""},
    )

    # Run the agent
    try:
        sdk_result = asyncio.run(_run_refine(prompt, options))
    except Exception as exc:
        error_result = {
            "status": "error",
            "node": args.node,
            "error": str(exc),
        }
        print(json.dumps(error_result, indent=2))
        sys.exit(1)

    # Check if evidence was written
    refine_evidence_path = os.path.join(evidence_dir, "refine-findings.json")
    sd_updated = False
    summary = "Refinement completed but no evidence file found"

    if os.path.exists(refine_evidence_path):
        try:
            with open(refine_evidence_path) as f:
                evidence = json.load(f)
            sd_updated = evidence.get("sd_updated", False)
            summary = evidence.get("refinement_summary", "No summary provided")
        except (json.JSONDecodeError, OSError):
            summary = "Evidence file exists but could not be parsed"

    output = {
        "status": "error" if sdk_result.get("is_error") else "ok",
        "node": args.node,
        "evidence_path": refine_evidence_path,
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

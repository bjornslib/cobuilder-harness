#!/usr/bin/env python3
"""guardian.py — Pilot Agent + Terminal Bridge (Layers 0 & 1).

Merged from guardian_agent.py (Layer 1) and launch_guardian.py (Layer 0).

Provides the interactive terminal (ccsystem3 / Layer 0) with the ability to
launch one or more headless Pilot agents (Layer 1) via the claude_code_sdk,
monitor them for terminal-targeted signals, and handle escalations or
completion events.

Architecture:
    guardian.py (Layer 0/1 — launch bridge + Pilot agent process)
        │
        ├── parse_args()                → CLI argument parsing (--dot | --multi)
        ├── build_system_prompt()       → pipeline execution instructions for Claude
        ├── build_initial_prompt()      → first user message with pipeline context
        ├── build_options()             → ClaudeCodeOptions (Bash only, max_turns, model)
        ├── launch_guardian()           → Single Pilot launch via Agent SDK query()
        ├── launch_multiple_guardians() → Parallel launch via asyncio.gather
        ├── monitor_guardian()          → Health-check loop watching terminal signals
        ├── handle_escalation()         → Format + forward Pilot escalation to user
        └── handle_pipeline_complete()  → Finalize and summarise a completed pipeline

CLAUDECODE environment note:
    The Pilot may be launched from inside a Claude Code session. To avoid
    nested-session conflicts, the environment is cleaned by stripping
    CLAUDECODE, CLAUDE_SESSION_ID, and CLAUDE_OUTPUT_STYLE, and setting
    PIPELINE_SIGNAL_DIR and PROJECT_TARGET_DIR for worker context.

Usage:
    # Single guardian
    python guardian.py \\
        --dot <path_to_pipeline.dot> \\
        --pipeline-id <id> \\
        [--project-root <path>] \\
        [--model <model_id>] \\
        [--max-turns <n>] \\
        [--signal-timeout <seconds>] \\
        [--max-retries <n>] \\
        [--signals-dir <path>] \\
        [--dry-run]

    # Parallel launch from JSON config
    python guardian.py --multi <configs.json>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Ensure this file's directory is importable regardless of invocation CWD.

import cobuilder.engine.identity_registry as identity_registry
from cobuilder.engine.dispatch_worker import load_engine_env

# Import signal_protocol at module level so tests can patch
# ``guardian.wait_for_signal`` directly via unittest.mock.patch.
from cobuilder.engine.signal_protocol import wait_for_signal  # noqa: E402

# Import merge_queue so it is available in the Pilot process for signal handling
try:
    import cobuilder.engine.merge_queue as merge_queue  # noqa: F401  (imported for side-effects / availability)
except ImportError:
    pass  # merge_queue not available in test-only environments

# ---------------------------------------------------------------------------
# Logfire instrumentation (required)
# ---------------------------------------------------------------------------
import logfire

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

# Gracefully handle missing Logfire project credentials:

# ---------------------------------------------------------------------------
# Pilot allowed_tools (Epic 3: Expand Tools)
# ---------------------------------------------------------------------------
# Pilot is a coordinator, not implementer — NO Write/Edit/MultiEdit.
# It needs: Bash (commands), Read/Glob/Grep (investigation), ToolSearch/Skill/LSP
# (deferred MCP loading), Serena (code nav for validation), Hindsight (learning).
_GUARDIAN_TOOLS: list[str] = [
    # Base tools
    "Bash", "Read", "Glob", "Grep", "ToolSearch", "Skill", "LSP",
    # Serena: code navigation for validation inspection
    "mcp__serena__activate_project",
    "mcp__serena__check_onboarding_performed",
    "mcp__serena__find_symbol",
    "mcp__serena__search_for_pattern",
    "mcp__serena__get_symbols_overview",
    "mcp__serena__find_referencing_symbols",
    "mcp__serena__find_file",
    # Hindsight: learning storage
    "mcp__hindsight__retain",
    "mcp__hindsight__recall",
    "mcp__hindsight__reflect",
]
# When running in an impl repo without .logfire/, logfire.configure()
# triggers an interactive prompt that crashes non-interactive contexts.
_send_to_logfire_env = os.environ.get("LOGFIRE_SEND_TO_LOGFIRE", "").lower()
if _send_to_logfire_env == "false":
    _logfire_enabled = False
elif _send_to_logfire_env == "true":
    _logfire_enabled = True
else:
    _logfire_enabled = (
        Path(".logfire").is_dir()
        or bool(os.environ.get("LOGFIRE_TOKEN"))
    )

logfire.configure(
    service_name="cobuilder-guardian",
    send_to_logfire=_logfire_enabled,
    inspect_arguments=False,
    scrubbing=False,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_TURNS = 200          # more turns than runner; Pilot runs longer
DEFAULT_SIGNAL_TIMEOUT = 600     # 10 minutes per wait cycle
DEFAULT_MAX_RETRIES = 3          # max retries per node before escalating
DEFAULT_MONITOR_TIMEOUT = 3600   # 1 hour total monitor timeout
DEFAULT_MODEL = "claude-sonnet-4-6"  # default Claude model for Pilot


# ---------------------------------------------------------------------------
# Public helper functions (importable for testing)
# ---------------------------------------------------------------------------


def build_system_prompt(
    dot_path: str,
    pipeline_id: str,
    scripts_dir: str,
    signal_timeout: float,
    max_retries: int,
    target_dir: str = "",
    max_cycles: int = 3,
) -> str:
    """Return the system prompt that instructs the Pilot agent how to run the pipeline.

    Args:
        dot_path: Absolute path to the pipeline DOT file.
        pipeline_id: Unique pipeline identifier string.
        scripts_dir: Absolute path to the attractor scripts directory.
        signal_timeout: Seconds to wait per signal wait cycle.
        max_retries: Maximum retries allowed per node before escalation.
        target_dir: Target implementation repo directory.
        max_cycles: Maximum full research→validate cycles before forced exit (default: 3).

    Returns:
        Formatted system prompt string.
    """
    target_dir_line = f"- Target directory: {target_dir}"
    target_dir_flag = f" --target-dir {target_dir}"
    return f"""\
You are the Pilot agent (Layer 1) in a 4-layer pipeline execution system.

Your role: Drive pipeline execution autonomously by reading the DOT graph, spawning
Runners for each codergen node, handling signals, and transitioning node statuses.

## Your Assignment
- Pipeline DOT: {dot_path}
- Pipeline ID: {pipeline_id}
- Scripts directory: {scripts_dir}
- Signal timeout: {signal_timeout}s per wait cycle
- Max retries per node: {max_retries}
{target_dir_line}

## Tools Available (via Bash — use python3 to invoke)
All scripts are in {scripts_dir}:

### Attractor CLI (pipeline management)
- python3 {scripts_dir}/cli.py status {dot_path} --filter=pending --deps-met --json    # Find ready nodes
- python3 {scripts_dir}/cli.py status {dot_path} --json                                  # Full status
- python3 {scripts_dir}/cli.py parse {dot_path} --output json                            # Full graph
- python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> <new_status>  # Advance status
- python3 {scripts_dir}/cli.py checkpoint save {dot_path}                                # Save checkpoint

### Signal Tools
- python3 {scripts_dir}/wait_for_signal.py --target guardian --timeout {signal_timeout}  # Wait for runner
- python3 {scripts_dir}/read_signal.py <signal_path>                                      # Read signal
- python3 {scripts_dir}/respond_to_runner.py VALIDATION_PASSED --node <id>               # Approve
- python3 {scripts_dir}/respond_to_runner.py VALIDATION_FAILED --node <id> --feedback <text>  # Reject
- python3 {scripts_dir}/respond_to_runner.py INPUT_RESPONSE --node <id> --response <text>     # Decide
- python3 {scripts_dir}/respond_to_runner.py GUIDANCE --node <id> --message <text>            # Guide
- python3 {scripts_dir}/respond_to_runner.py KILL_ORCHESTRATOR --node <id> --reason <text>    # Abort
- python3 {scripts_dir}/escalate_to_terminal.py --pipeline {pipeline_id} --issue <text>   # Escalate

### Pipeline Runner Launch
- python3 {scripts_dir}/pipeline_runner.py --dot-file {dot_path} &   # Launch runner in BACKGROUND
- python3 {scripts_dir}/cli.py status {dot_path} --json              # Check runner progress

CRITICAL: Always run pipeline_runner.py with & (background). If you run it in the foreground,
you will DEADLOCK when the runner hits a gate node — it will wait for your GATE_RESPONSE signal,
but you'll be blocked waiting for it to exit.

### Gate Handling
When a node with handler=wait.cobuilder or wait.human becomes active, the runner is blocked
waiting for you to validate or approve.

For wait.cobuilder gates:
1. Read the codergen node's acceptance criteria from the DOT
2. Verify the work was done (check files exist, run tests via Bash)
3. If PASS: transition the gate to validated
   python3 {scripts_dir}/cli.py transition {dot_path} <gate_node> validated
4. If FAIL: transition the codergen node back to pending for retry
   python3 {scripts_dir}/cli.py transition {dot_path} <codergen_node> pending

For wait.human gates:
1. Check if you can validate autonomously (technical criteria)
2. If autonomous: transition to validated
3. If human needed: escalate to Terminal

### Pipeline Graph Modification (Node/Edge CRUD)
When you need to modify the pipeline structure (e.g., inject a refinement node after failure,
add a parallel research branch, or restructure after validation failure):

Node operations:
- python3 {scripts_dir}/cli.py node {dot_path} add <node_id> --handler codergen --label "Fix: <description>" --set sd_path=<path> --set worker_type=backend-solutions-engineer --set llm_profile=alibaba-glm5 --set prompt="<task>" --set acceptance="<criteria>" --set prd_ref=<prd> --set bead_id=<id>
- python3 {scripts_dir}/cli.py node {dot_path} add <node_id> --handler research --label "Research: <topic>" --set llm_profile=anthropic-fast
- python3 {scripts_dir}/cli.py node {dot_path} add <node_id> --handler refine --label "Refine: <topic>" --set sd_path=<path>
- python3 {scripts_dir}/cli.py node {dot_path} modify <node_id> --set prompt="<updated_prompt>" --set acceptance="<updated_criteria>"
- python3 {scripts_dir}/cli.py node {dot_path} remove <node_id>
- python3 {scripts_dir}/cli.py node {dot_path} list

Edge operations:
- python3 {scripts_dir}/cli.py edge {dot_path} add <from_node> <to_node> --label "<description>"
- python3 {scripts_dir}/cli.py edge {dot_path} remove <from_node> <to_node>
- python3 {scripts_dir}/cli.py edge {dot_path} list

Common patterns:
1. Inject fix-it node after validation failure:
   python3 {scripts_dir}/cli.py node {dot_path} add fix_<id> --handler codergen --label "Fix: <gap>" --set sd_path=<path> --set worker_type=backend-solutions-engineer
   python3 {scripts_dir}/cli.py edge {dot_path} add <failed_node> fix_<id> --label "fix required"
   python3 {scripts_dir}/cli.py edge {dot_path} add fix_<id> <next_gate> --label "re-validate"

2. Add research branch for unknown domain:
   python3 {scripts_dir}/cli.py node {dot_path} add research_<topic> --handler research --label "Research: <topic>"
   python3 {scripts_dir}/cli.py edge {dot_path} add <predecessor> research_<topic> --label "investigate"
   python3 {scripts_dir}/cli.py edge {dot_path} add research_<topic> <successor> --label "findings ready"

3. Restructure after repeated failure (replace node):
   python3 {scripts_dir}/cli.py node {dot_path} remove <old_node>
   python3 {scripts_dir}/cli.py node {dot_path} add <new_node> --handler codergen --label "<new approach>" --set sd_path=<path>
   (re-wire edges from predecessor/successor)

IMPORTANT: After ANY graph modification, always:
   python3 {scripts_dir}/cli.py validate {dot_path}
   python3 {scripts_dir}/cli.py checkpoint save {dot_path}

### Signal Handler Types
When reading signals via wait_for_signal.py, you may encounter these signal types from runners:
- NEEDS_REVIEW: Worker completed but requires Pilot review before validation
- NEEDS_INPUT: Worker is blocked and requires human input to proceed
- VIOLATION: Policy or constraint violation detected during execution
- ORCHESTRATOR_STUCK: The orchestrator has stalled and cannot make progress
- ORCHESTRATOR_CRASHED: The orchestrator process terminated unexpectedly
- NODE_COMPLETE: A node has finished execution and is ready for transition

### Response Types (via respond_to_runner.py)
- VALIDATION_PASSED: Approve the work and transition node to validated
- VALIDATION_FAILED: Reject the work with feedback, retry or escalate
- INPUT_RESPONSE: Provide the requested input to unblock the worker
- GUIDANCE: Send guidance to help the worker without approval/rejection
- KILL_ORCHESTRATOR: Terminate the runner process for the specified node

## Pipeline Execution Flow

### Phase 1: Initialize
1. Parse the DOT file:
   python3 {scripts_dir}/cli.py parse {dot_path} --output json
2. Validate the pipeline:
   python3 {scripts_dir}/cli.py validate {dot_path} --output json
3. Get current status:
   python3 {scripts_dir}/cli.py status {dot_path} --json

### Phase 2a: Dispatch Research Nodes (BEFORE codergen)
4a. Find ready research nodes:
    python3 {scripts_dir}/cli.py status {dot_path} --filter=pending --deps-met --json
    Filter output for nodes with handler="research".
4b. For each ready research node:
   a. Transition to active:
      python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> active
   b. Save checkpoint:
      python3 {scripts_dir}/cli.py checkpoint save {dot_path}
   c. Run research agent (synchronous — completes in seconds):
      python3 {scripts_dir}/run_research.py --node <node_id> --prd <prd_ref> \
          --solution-design <solution_design_attr> --target-dir {target_dir} \
          --frameworks <research_queries_attr> \
          --prd-path <prd_path_attr if present>
   d. Parse the JSON output from stdout
   e. If status=ok and sd_updated=true:
      - The SD has been updated with validated patterns
      - Transition research node to validated:
        python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> validated
      - Save checkpoint
      - Log: "Research validated N frameworks, updated SD at <sd_path>"
   f. If status=ok and sd_updated=false:
      - SD was already current — no changes needed
      - Transition research node to validated:
        python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> validated
      - Save checkpoint
   g. If status=error:
      - Transition to failed:
        python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> failed
      - Escalate: python3 {scripts_dir}/escalate_to_terminal.py --pipeline {pipeline_id} --issue "Research failed for <node_id>: <error>"

Research nodes are dispatched BEFORE codergen nodes. The downstream codergen node's dependency
on the research node is enforced by DOT edges — it won't appear in --deps-met until research
is validated.

### Phase 2a.5: Dispatch Refine Nodes (AFTER research, BEFORE codergen)
4c. Find ready refine nodes:
    python3 {scripts_dir}/cli.py status {dot_path} --filter=pending --deps-met --json
    Filter output for nodes with handler="refine".
4d. For each ready refine node:
   a. Transition to active:
      python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> active
   b. Save checkpoint:
      python3 {scripts_dir}/cli.py checkpoint save {dot_path}
   c. Run refine agent (synchronous — uses Sonnet, takes ~30-60s):
      python3 {scripts_dir}/run_refine.py --node <node_id> --prd <prd_ref> \
          --solution-design <solution_design_attr> --target-dir {target_dir} \
          --evidence-path <evidence_path_attr> \
          --prd-path <prd_path_attr if present>
   d. Parse the JSON output from stdout
   e. If status=ok and sd_updated=true:
      - The SD has been rewritten with research findings as first-class content
      - All inline research annotations have been removed
      - Transition refine node to validated:
        python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> validated
      - Save checkpoint
      - Log: "Refine completed: rewrote N sections, patched M sections, removed K annotations"
   f. If status=ok and sd_updated=false:
      - SD needed no refinement beyond what research already did
      - Transition refine node to validated:
        python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> validated
      - Save checkpoint
   g. If status=error:
      - Transition to failed:
        python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> failed
      - Escalate: python3 {scripts_dir}/escalate_to_terminal.py --pipeline {pipeline_id} --issue "Refine failed for <node_id>: <error>"

Refine nodes run AFTER research and BEFORE codergen. They transform inline research
annotations into production-quality SD content. The downstream codergen node's dependency
on the refine node is enforced by DOT edges — it won't appear in --deps-met until refine
is validated.

### Phase 2: Launch Pipeline Runner (Background)
4. Launch the pipeline runner in the BACKGROUND:
   python3 {scripts_dir}/pipeline_runner.py --dot-file {dot_path} &
   RUNNER_PID=$!
   echo "Pipeline runner launched with PID: $RUNNER_PID"

   CRITICAL: Always use & (background). Foreground execution will DEADLOCK at gate nodes.

5. Poll the runner process and handle gates:
   ```bash
   while ps -p $RUNNER_PID > /dev/null 2>&1; do
       # Check for gate signals (runner is blocked waiting for you)
       ls {scripts_dir}/../signals/*GATE*.signal 2>/dev/null

       # Check node statuses for progress
       python3 {scripts_dir}/cli.py status {dot_path} --json

       sleep 30
   done
   ```

6. When the runner hits a gate node (wait.cobuilder or wait.human):
   a. Read the gate signal file to identify which node is blocked
   b. For wait.cobuilder gates:
      - Read the upstream codergen node's acceptance criteria
      - Verify the work (check files, run tests)
      - If PASS: python3 {scripts_dir}/cli.py transition {dot_path} <gate_node> validated
      - If FAIL: python3 {scripts_dir}/cli.py transition {dot_path} <codergen_node> pending
   c. For wait.human gates:
      - If you can validate autonomously: transition to validated
      - If human input needed: escalate to Terminal

### Phase 3: Handle Runner Completion
7. When the runner PID exits, check the final status:
   python3 {scripts_dir}/cli.py status {dot_path} --json

8. Handle based on final state:

   ALL NODES validated:
   - Pipeline completed successfully
   - Save final checkpoint: python3 {scripts_dir}/cli.py checkpoint save {dot_path}
   - Signal completion: python3 {scripts_dir}/escalate_to_terminal.py --pipeline {pipeline_id} --issue "PIPELINE_COMPLETE"

   ANY NODE failed:
   - Check retry count for the failed node
   - If retries remain: transition back to pending and re-launch runner
     python3 {scripts_dir}/cli.py transition {dot_path} <node_id> pending
     python3 {scripts_dir}/pipeline_runner.py --dot-file {dot_path} &
   - If max retries exceeded: escalate
     python3 {scripts_dir}/escalate_to_terminal.py --pipeline {pipeline_id} --issue "Node <node_id> failed after {max_retries} retries"

   RUNNER CRASHED (no status update):
   - Check stderr logs for diagnostics
   - Retry or escalate as appropriate

9. Pipeline complete when all non-start/exit nodes are validated.

## Retry Tracking
Track retries per node in memory (dict). When a node exceeds {max_retries} retries, do not
spawn again — escalate to Terminal with full context.

## Hook Phase Tracking
Update pipeline phase at lifecycle transitions:

When beginning validation of a pipeline node:
```bash
python3 {scripts_dir}/hook_manager.py update-phase guardian {pipeline_id} validating
```

After successful merge of a node:
```bash
python3 {scripts_dir}/hook_manager.py update-phase guardian {pipeline_id} merged
```

## Merge Queue Integration
The merge queue handles sequential merging of completed nodes. Use these commands:

Check for pending merges:
```bash
python3 {scripts_dir}/merge_queue.py process_next --pipeline {pipeline_id}
```

Signal merge completion:
```bash
python3 {scripts_dir}/merge_queue.py write_signal MERGE_COMPLETE --node <node_id>
```

Signal merge failure:
```bash
python3 {scripts_dir}/merge_queue.py write_signal MERGE_FAILED --node <node_id> --reason <reason>
```

## Identity Scanning
Before dispatching workers, scan for identity conflicts in the DOT graph.
Ensure all nodes have unique identifiers and no duplicate handler assignments.

## Failure Context for Retry Loops
When a validation fails and you need to loop back to research:
1. Write a failure summary BEFORE transitioning back:
   ```bash
   cat >> state/${{INITIATIVE_ID}}-failures.md << 'EOF'
   ## Cycle N Failure Summary
   - Node: <node_id>
   - Reason: <why it failed>
   - Attempted: <what was tried>
   - Root cause: <analysis>
   EOF
   ```
2. Use APPEND (`>>`) not overwrite (`>`) — each cycle adds context
3. The RESEARCH node will read this file on its next run to focus investigation

## Cycle Tracking and Bounds Enforcement
Track the number of full research→validate cycles in a state file:

Before each loop-back to RESEARCH:
1. Read current cycle count:
   ```bash
   CYCLES=$(cat state/{pipeline_id}-cycle-count.txt 2>/dev/null || echo 0)
   ```
2. Increment:
   ```bash
   echo $((CYCLES + 1)) > state/{pipeline_id}-cycle-count.txt
   ```
3. Check against max_cycles ({max_cycles}):
   ```bash
   if [ $((CYCLES + 1)) -ge {max_cycles} ]; then
       # Max cycles reached — transition to CLOSE with exhaustion reason
       python3 {scripts_dir}/cli.py transition {dot_path} close active
       python3 {scripts_dir}/cli.py transition {dot_path} close validated
       echo "Max cycles ({max_cycles}) exhausted. Closing pipeline."
       exit 0
   fi
   ```
4. Only loop back if cycles remain

The max_cycles value is {max_cycles} (from pipeline manifest or default).

### Template Instantiation (For PLAN Nodes)
When a PLAN node needs to generate a child implementation pipeline:

1. Read the refined BS:
   cat state/{pipeline_id}-refined.md

2. Break into implementation tasks (each task = one codergen node)

3. Instantiate a template:
   python3 -c "
   from cobuilder.templates.instantiator import instantiate_template
   instantiate_template('sequential-validated', {{
       'initiative_id': '{pipeline_id}-impl',
       'tasks': [...],
       'target_dir': '{target_dir}',
       'cobuilder_root': '{{cobuilder_root}}',
   }}, output_path='.pipelines/pipelines/{pipeline_id}-impl.dot')
   "

   OR create a DOT file manually using node/edge CRUD:
   python3 {scripts_dir}/cli.py node <dot_path> add impl_task_1 --handler codergen ...

4. Write the plan file:
   cat > state/{pipeline_id}-plan.json << 'EOF'
   {{
       "dot_path": ".pipelines/pipelines/{pipeline_id}-impl.dot",
       "template": "sequential-validated",
       "task_count": N,
       "tasks": [{{"id": "task_1", "description": "..."}}]
   }}
   EOF

5. The EXECUTE node will read this plan and implement each task.

## Important Rules
- NEVER use Edit or Write tools — you are a coordinator, not an implementer
- NEVER guess at node status — always read from the DOT file via CLI
- ALWAYS checkpoint after every status transition
- When in doubt about a validation decision, err on the side of VALIDATION_FAILED with specific feedback
- Escalate to Terminal (Layer 0) only when you cannot resolve without human input
"""


def build_initial_prompt(
    dot_path: str,
    pipeline_id: str,
    scripts_dir: str,
    target_dir: str = "",
) -> str:
    """Return the first user message sent to Claude to start the pipeline execution loop.

    Args:
        dot_path: Absolute path to the pipeline DOT file.
        pipeline_id: Unique pipeline identifier string.
        scripts_dir: Absolute path to the attractor scripts directory.
        target_dir: Target implementation repo directory.

    Returns:
        Formatted initial prompt string.
    """
    target_dir_line = f"Target directory: {target_dir}\n" if target_dir else ""
    return (
        f"You are the Pilot for pipeline '{pipeline_id}'.\n\n"
        f"Pipeline DOT file: {dot_path}\n"
        f"Scripts directory: {scripts_dir}\n"
        f"{target_dir_line}\n"
        f"Begin by:\n"
        f"1. Parsing the pipeline to understand the full graph\n"
        f"2. Validating the pipeline structure\n"
        f"3. Getting current node statuses\n\n"
        f"Then proceed with Phase 2 (dispatch ready nodes) of the execution flow.\n\n"
        f"If the pipeline is already partially complete (some nodes are already validated),\n"
        f"skip those nodes and continue from the current state.\n"
    )


# ---------------------------------------------------------------------------
# Pilot Stop Hook Factory
# ---------------------------------------------------------------------------


def _create_guardian_stop_hook(dot_path: str, pipeline_id: str) -> dict:
    """Create a Stop hook that checks pipeline completion instead of promises/hindsight.

    The Pilot should continue driving the pipeline until all nodes reach terminal
    states (validated, accepted, or failed). This hook blocks exit if non-terminal
    nodes (pending, active, impl_complete) remain, with a safety valve after 3 blocks.

    Args:
        dot_path: Absolute path to the pipeline DOT file.
        pipeline_id: Unique pipeline identifier string.

    Returns:
        Dict suitable for ClaudeCodeOptions.hooks parameter:
        {"Stop": [HookMatcher(hooks=[callback])]}
    """
    _block_count = 0
    _MAX_BLOCKS = 3  # Safety valve — allow exit after this many blocks

    async def _check_pipeline(hook_input: dict, event_name: str | None, context: Any) -> Any:
        """Stop hook: block exit if pipeline has non-terminal nodes."""
        nonlocal _block_count
        import subprocess

        try:
            result = subprocess.run(
                ["python3", "cobuilder/engine/cli.py", "status", dot_path, "--json", "--summary"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                import json
                status = json.loads(result.stdout)
                summary = status.get("summary", {})
                # Non-terminal states that require continued work
                non_terminal = (
                    summary.get("pending", 0)
                    + summary.get("active", 0)
                    + summary.get("impl_complete", 0)
                )
                if non_terminal == 0:
                    return {}  # All nodes terminal — allow exit

                _block_count += 1
                if _block_count > _MAX_BLOCKS:
                    return {}  # Safety valve — allow exit

                return {
                    "decision": "block",
                    "systemMessage": (
                        f"PIPELINE STOP GATE ({_block_count}/{_MAX_BLOCKS}): "
                        f"Pipeline '{pipeline_id}' has {non_terminal} non-terminal nodes.\n\n"
                        f"Continue driving the pipeline to completion. Check node statuses with:\n"
                        f"  python3 cobuilder/engine/cli.py status {dot_path}\n\n"
                        f"Dispatch any ready nodes, handle gates, and monitor for completion."
                    ),
                }
        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
            logfire.warning("[guardian-stop-hook] Status check failed: %s", e)
            # On error, allow exit — don't block indefinitely

        return {}  # Default: allow exit

    try:
        from claude_code_sdk.types import HookMatcher
        return {"Stop": [HookMatcher(hooks=[_check_pipeline])]}
    except ImportError:
        logfire.warning("[hooks] claude_code_sdk.types not available — guardian stop hook disabled")
        return {}


def build_options(
    system_prompt: str,
    cwd: str,
    model: str,
    max_turns: int,
    hooks: dict | None = None,
    signals_dir: str | None = None,
    target_dir: str | None = None,
) -> Any:
    """Construct a ClaudeCodeOptions instance for the Pilot agent.

    The Pilot is a coordinator (not implementer) — it gets read/investigation
    tools (Bash, Read, Glob, Grep, ToolSearch, Skill, LSP) plus Serena and Hindsight
    for code navigation and learning storage. It does NOT get Write/Edit/MultiEdit.

    Args:
        system_prompt: Pipeline execution instructions for Claude.
        cwd: Working directory for the agent (project root).
        model: Claude model identifier.
        max_turns: Maximum turns before the SDK stops the conversation.
        hooks: Optional hooks dict for Stop hook configuration.
        signals_dir: Path to signals directory (set as PIPELINE_SIGNAL_DIR).
        target_dir: Target implementation repo directory (set as PROJECT_TARGET_DIR).

    Returns:
        Configured ClaudeCodeOptions instance.
    """
    with logfire.span("guardian.build_options", model=model):
        from claude_code_sdk import ClaudeCodeOptions

        # Build clean environment: strip session identifiers and set pipeline context.
        # This matches the pattern in pipeline_runner.py:1513-1516.
        clean_env = {
            k: v for k, v in os.environ.items()
            if k not in ("CLAUDECODE", "CLAUDE_SESSION_ID", "CLAUDE_OUTPUT_STYLE")
        }
        if signals_dir:
            clean_env["PIPELINE_SIGNAL_DIR"] = str(signals_dir)
        if target_dir:
            clean_env["PROJECT_TARGET_DIR"] = str(target_dir)

        options_kwargs = {
            "allowed_tools": _GUARDIAN_TOOLS,
            "permission_mode": "bypassPermissions",
            "system_prompt": system_prompt,
            "cwd": cwd,
            "model": model,
            "max_turns": max_turns,
            "env": clean_env,
        }
        if hooks:
            options_kwargs["hooks"] = hooks

        return ClaudeCodeOptions(**options_kwargs)


def resolve_scripts_dir() -> str:
    """Return the absolute path to the attractor scripts directory.

    Resolution order:
    1. The directory containing this file (guardian.py is inside attractor/).
    2. Falls back to current working directory if for some reason _THIS_DIR is unavailable.

    Returns:
        Absolute path string.
    """
    return _THIS_DIR


def build_env_config(
    signals_dir: str | None = None,
    target_dir: str | None = None,
) -> dict[str, str]:
    """Return environment overrides for the Pilot agent.

    Strips session identifiers (CLAUDECODE, CLAUDE_SESSION_ID, CLAUDE_OUTPUT_STYLE)
    and sets pipeline context variables (PIPELINE_SIGNAL_DIR, PROJECT_TARGET_DIR).

    Note: ClaudeCodeOptions.env only adds/overrides keys, it cannot delete.
    This function provides the clean environment dict that should be passed
    directly to the options.

    Args:
        signals_dir: Path to signals directory (set as PIPELINE_SIGNAL_DIR).
        target_dir: Target implementation repo directory (set as PROJECT_TARGET_DIR).

    Returns:
        Dict of cleaned env vars with pipeline context set.
    """
    clean_env = {
        k: v for k, v in os.environ.items()
        if k not in ("CLAUDECODE", "CLAUDE_SESSION_ID", "CLAUDE_OUTPUT_STYLE")
    }
    if signals_dir:
        clean_env["PIPELINE_SIGNAL_DIR"] = str(signals_dir)
    if target_dir:
        clean_env["PROJECT_TARGET_DIR"] = str(target_dir)
    return clean_env


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for guardian.py.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Parsed namespace.
    """
    parser = argparse.ArgumentParser(
        prog="guardian.py",
        description=(
            "Pilot Agent launcher (Layers 0/1): launch Pilot agents and "
            "monitor pipeline execution via claude_code_sdk."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python guardian.py --dot /path/to/pipeline.dot --pipeline-id my-pipeline

  python guardian.py --dot /path/to/pipeline.dot --pipeline-id my-pipeline \\
      --project-root /my/project --max-turns 300 --signal-timeout 300 --dry-run

  python guardian.py --multi /path/to/configs.json
        """,
    )

    # Mutually exclusive groups: single-launch vs multi-launch vs lifecycle
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dot", dest="dot",
                       help="Path to pipeline .dot file (single Pilot mode)")
    group.add_argument("--multi", dest="multi",
                       help="Path to JSON file containing a list of pipeline configs")
    group.add_argument("--lifecycle", dest="lifecycle",
                       help="Path to PRD — auto-instantiates lifecycle pipeline and launches")

    parser.add_argument("--pipeline-id", dest="pipeline_id", default=None,
                        help="Unique pipeline identifier (required with --dot)")
    parser.add_argument("--project-root", default=None, dest="project_root",
                        help="Working directory for the agent (default: cwd)")
    parser.add_argument("--target-dir", default=None, dest="target_dir",
                        help="Target implementation repo directory (overrides DOT graph attr)")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS,
                        dest="max_turns",
                        help=f"Max SDK turns (default: {DEFAULT_MAX_TURNS})")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Claude model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--signals-dir", default=None, dest="signals_dir",
                        help="Override signals directory path")
    parser.add_argument("--signal-timeout", type=float, default=DEFAULT_SIGNAL_TIMEOUT,
                        dest="signal_timeout",
                        help=f"Seconds to wait per signal wait cycle (default: {DEFAULT_SIGNAL_TIMEOUT})")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES,
                        dest="max_retries",
                        help=f"Max retries per node before escalating (default: {DEFAULT_MAX_RETRIES})")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="Log configuration without invoking the SDK (for testing)")

    ns = parser.parse_args(argv)

    # Validate --dot requires --pipeline-id
    if ns.dot is not None and ns.pipeline_id is None:
        parser.error("--pipeline-id is required when using --dot")

    return ns


# ---------------------------------------------------------------------------
# Async agent runner
# ---------------------------------------------------------------------------


async def _run_agent(initial_prompt: str, options: Any) -> None:
    """Stream messages from the claude_code_sdk ClaudeSDKClient and log them.

    Each SDK message type is logged to Logfire as a structured event so that
    tool calls, assistant text, tool results, and session completion are all
    visible in the Logfire dashboard.

    Uses ClaudeSDKClient pattern (connect() then query()) to enable Stop hooks.

    Args:
        initial_prompt: The first user message to send to Claude.
        options: Configured ClaudeCodeOptions instance.
    """
    import time as _time

    from claude_code_sdk import (
        ClaudeSDKClient,
        AssistantMessage,
        UserMessage,
        ResultMessage,
        TextBlock,
        ThinkingBlock,
        ToolUseBlock,
        ToolResultBlock,
    )

    turn_count = 0
    tool_call_count = 0
    start_time = _time.time()

    with logfire.span("guardian.run_agent") as agent_span:
        async with ClaudeSDKClient(options=options) as client:
            await client.connect()
            await client.query(initial_prompt)
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    turn_count += 1
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            text_preview = block.text[:300] if block.text else ""
                            logfire.info(
                                "guardian.assistant_text",
                                turn=turn_count,
                                text_length=len(block.text) if block.text else 0,
                                text_preview=text_preview,
                            )
                            print(f"[Pilot] {block.text}", flush=True)

                        elif isinstance(block, ToolUseBlock):
                            tool_call_count += 1
                            input_preview = json.dumps(block.input)[:500]
                            logfire.info(
                                "guardian.tool_use",
                                tool_name=block.name,
                                tool_use_id=block.id,
                                tool_input_preview=input_preview,
                                turn=turn_count,
                                tool_call_number=tool_call_count,
                            )
                            print(f"[Pilot tool] {block.name}: {input_preview[:200]}", flush=True)

                        elif isinstance(block, ThinkingBlock):
                            logfire.info(
                                "guardian.thinking",
                                turn=turn_count,
                                thinking_length=len(block.thinking) if block.thinking else 0,
                                thinking_preview=(block.thinking or "")[:200],
                            )

                elif isinstance(message, UserMessage):
                    # UserMessage carries tool results back from tool execution
                    if isinstance(message.content, list):
                        for block in message.content:
                            if isinstance(block, ToolResultBlock):
                                content_preview = ""
                                content_length = 0
                                if isinstance(block.content, str):
                                    content_preview = block.content[:500]
                                    content_length = len(block.content)
                                elif isinstance(block.content, list):
                                    content_preview = json.dumps(block.content)[:500]
                                    content_length = len(json.dumps(block.content))
                                logfire.info(
                                    "guardian.tool_result",
                                    tool_use_id=block.tool_use_id,
                                    is_error=block.is_error or False,
                                    content_length=content_length,
                                    content_preview=content_preview,
                                    turn=turn_count,
                                )

                elif isinstance(message, ResultMessage):
                    elapsed = _time.time() - start_time
                    logfire.info(
                        "guardian.result",
                        session_id=message.session_id,
                        is_error=message.is_error,
                        num_turns=message.num_turns,
                        duration_ms=message.duration_ms,
                        duration_api_ms=message.duration_api_ms,
                        total_cost_usd=message.total_cost_usd,
                        usage=message.usage,
                        result_preview=(message.result or "")[:300],
                        wall_time_seconds=round(elapsed, 2),
                        total_tool_calls=tool_call_count,
                    )
                    print(f"[Pilot done] turns={message.num_turns} cost=${message.total_cost_usd} tools={tool_call_count}", flush=True)


# ---------------------------------------------------------------------------
# Core public API (launch/monitor functions)
# ---------------------------------------------------------------------------


async def _launch_guardian_async(
    dot_path: str,
    project_root: str,
    pipeline_id: str,
    *,
    model: str = "claude-sonnet-4-6",
    max_turns: int = DEFAULT_MAX_TURNS,
    signal_timeout: float = DEFAULT_SIGNAL_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    signals_dir: Optional[str] = None,
    dry_run: bool = False,
    target_dir: str = "",
) -> dict[str, Any]:
    """Async implementation of launch_guardian().

    Args:
        dot_path: Absolute path to the pipeline DOT file.
        project_root: Working directory for the agent.
        pipeline_id: Unique pipeline identifier string.
        model: Claude model identifier.
        max_turns: Maximum SDK turns.
        signal_timeout: Seconds to wait per signal wait cycle.
        max_retries: Maximum retries per node before escalation.
        signals_dir: Override signals directory path.
        dry_run: If True, return config dict without invoking SDK.
        target_dir: Target implementation repo directory.

    Returns:
        Dict with status and pipeline metadata.
    """
    scripts_dir = resolve_scripts_dir()

    with logfire.span("guardian.launch_guardian_async", pipeline_id=pipeline_id):
        system_prompt = build_system_prompt(
            dot_path=dot_path,
            pipeline_id=pipeline_id,
            scripts_dir=scripts_dir,
            signal_timeout=signal_timeout,
            max_retries=max_retries,
            target_dir=target_dir,
        )

        initial_prompt = build_initial_prompt(
            dot_path=dot_path,
            pipeline_id=pipeline_id,
            scripts_dir=scripts_dir,
            target_dir=target_dir,
        )

        config: dict[str, Any] = {
            "dry_run": dry_run,
            "dot_path": dot_path,
            "pipeline_id": pipeline_id,
            "model": model,
            "max_turns": max_turns,
            "signal_timeout": signal_timeout,
            "max_retries": max_retries,
            "project_root": project_root,
            "signals_dir": signals_dir,
            "scripts_dir": scripts_dir,
            "target_dir": target_dir,
            "system_prompt_length": len(system_prompt),
            "initial_prompt_length": len(initial_prompt),
        }

        if dry_run:
            return config

        # Create the Pilot stop hook that checks pipeline completion
        hooks = _create_guardian_stop_hook(dot_path, pipeline_id)

        options = build_options(
            system_prompt=system_prompt,
            cwd=project_root,
            model=model,
            max_turns=max_turns,
            hooks=hooks,
            signals_dir=signals_dir,
            target_dir=target_dir,
        )

    try:
        await _run_agent(initial_prompt, options)
        return {
            "status": "ok",
            "pipeline_id": pipeline_id,
            "dot_path": dot_path,
        }
    except Exception as exc:
        return {
            "status": "error",
            "pipeline_id": pipeline_id,
            "dot_path": dot_path,
            "error": str(exc),
        }


def launch_guardian(
    dot_path: str,
    project_root: str,
    pipeline_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Launch a single Pilot agent via the Agent SDK.

    Constructs ClaudeCodeOptions with allowed_tools=["Bash"] and
    env={"CLAUDECODE": ""}, then streams the SDK conversation until
    the Pilot completes or errors.

    Args:
        dot_path: Path to the pipeline .dot file.
        project_root: Working directory for the agent.
        pipeline_id: Unique pipeline identifier string.
        **kwargs: Optional overrides — model, max_turns, signal_timeout,
                  max_retries, signals_dir, dry_run.

    Returns:
        Dict with ``status`` ("ok" | "error"), ``pipeline_id``, ``dot_path``,
        and optionally ``error`` on failure.  In dry_run mode returns the
        full config dict with ``dry_run: True``.
    """
    dot_path = os.path.abspath(dot_path)
    return asyncio.run(
        _launch_guardian_async(
            dot_path=dot_path,
            project_root=project_root,
            pipeline_id=pipeline_id,
            **kwargs,
        )
    )


async def _launch_multiple_async(
    pipeline_configs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Async implementation of launch_multiple_guardians().

    Args:
        pipeline_configs: List of config dicts, each with at minimum
            dot_path, project_root, pipeline_id.

    Returns:
        List of result dicts, one per config.
    """
    tasks = [
        _launch_guardian_async(
            dot_path=os.path.abspath(cfg["dot_path"]),
            project_root=cfg.get("project_root", os.getcwd()),
            pipeline_id=cfg["pipeline_id"],
            model=cfg.get("model", "claude-sonnet-4-6"),
            max_turns=cfg.get("max_turns", DEFAULT_MAX_TURNS),
            signal_timeout=cfg.get("signal_timeout", DEFAULT_SIGNAL_TIMEOUT),
            max_retries=cfg.get("max_retries", DEFAULT_MAX_RETRIES),
            signals_dir=cfg.get("signals_dir"),
            dry_run=cfg.get("dry_run", False),
            target_dir=cfg.get("target_dir", ""),
        )
        for cfg in pipeline_configs
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Normalise exceptions to error dicts so callers receive a uniform type.
    output: list[dict[str, Any]] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            cfg = pipeline_configs[i]
            output.append({
                "status": "error",
                "pipeline_id": cfg.get("pipeline_id", "unknown"),
                "dot_path": cfg.get("dot_path", "unknown"),
                "error": str(result),
            })
        else:
            output.append(result)  # type: ignore[arg-type]

    return output


def launch_multiple_guardians(
    pipeline_configs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Launch multiple Pilot agents concurrently.

    Uses asyncio.gather with return_exceptions=True so an individual
    failure does not abort the remaining launches.

    Args:
        pipeline_configs: List of config dicts, each with:
            - dot_path (str, required)
            - project_root (str, required)
            - pipeline_id (str, required)
            - model, max_turns, signal_timeout, max_retries,
              signals_dir, dry_run (all optional)

    Returns:
        List of result dicts (one per config).  Any individual failure
        is represented as ``{"status": "error", ...}`` rather than
        raising an exception.
    """
    return asyncio.run(_launch_multiple_async(pipeline_configs))


def monitor_guardian(
    guardian_process: Any,
    dot_path: str,
    signals_dir: Optional[str] = None,
    *,
    timeout: float = DEFAULT_MONITOR_TIMEOUT,
    poll_interval: float = 5.0,
) -> dict[str, Any]:
    """Watch for terminal-targeted signals from a running Pilot.

    Polls the signals directory for signals with target="terminal" until
    either a PIPELINE_COMPLETE or terminal-escalation signal arrives, or
    the timeout is reached.

    Args:
        guardian_process: The guardian process handle (may be None for
            signal-only monitoring).  Currently unused but reserved for
            future process health checks.
        dot_path: Absolute path to the pipeline DOT file (used for
            metadata in returned dicts).
        signals_dir: Override the default signals directory.
        timeout: Maximum seconds to wait for a terminal signal.
        poll_interval: Seconds between directory polls.

    Returns:
        Dict with ``status`` ("complete" | "escalation" | "timeout") and
        the received ``signal_data`` (if any).
    """
    try:
        signal_data = wait_for_signal(
            target_layer="terminal",
            timeout=timeout,
            signals_dir=signals_dir,
            poll_interval=poll_interval,
        )
    except TimeoutError:
        return {
            "status": "timeout",
            "dot_path": dot_path,
            "signal_data": None,
        }
    except Exception as exc:
        return {
            "status": "error",
            "dot_path": dot_path,
            "error": str(exc),
            "signal_data": None,
        }

    signal_type = signal_data.get("signal_type", "")

    if "PIPELINE_COMPLETE" in signal_type or (
        signal_data.get("payload", {}).get("issue", "").startswith("PIPELINE_COMPLETE")
    ):
        return handle_pipeline_complete(signal_data, dot_path)

    if "VALIDATION_COMPLETE" in signal_type:
        return handle_validation_complete(signal_data, dot_path)

    # Any other terminal-targeted signal is treated as an escalation.
    return handle_escalation(signal_data)


def handle_validation_complete(
    signal_data: dict[str, Any],
    dot_path: str,
) -> dict[str, Any]:
    """Handle VALIDATION_COMPLETE signal from a Runner via terminal.

    Args:
        signal_data: Parsed signal dict from the Runner.
        dot_path: Absolute path to the pipeline DOT file.

    Returns:
        Dict with validation complete details.
    """
    payload = signal_data.get("payload", {})
    return {
        "status": "validation_complete",
        "node_id": payload.get("node_id", "unknown"),
        "pipeline_id": payload.get("pipeline_id", ""),
        "dot_path": dot_path,
        "summary": payload.get("summary", ""),
        "timestamp": signal_data.get("timestamp"),
        "source": signal_data.get("source"),
        "raw": signal_data,
    }


def handle_escalation(signal_data: dict[str, Any]) -> dict[str, Any]:
    """Forward a Pilot escalation signal to the terminal user.

    Reads the escalation signal payload and formats it for terminal
    display as a JSON dict.

    Args:
        signal_data: Parsed signal dict with fields source, target,
            signal_type, timestamp, payload.

    Returns:
        Dict with escalation details formatted for terminal display:
        ``{"status": "escalation", "signal_type": ..., "pipeline_id": ...,
           "issue": ..., "options": ..., "timestamp": ..., "raw": ...}``
    """
    payload = signal_data.get("payload", {})

    result: dict[str, Any] = {
        "status": "escalation",
        "signal_type": signal_data.get("signal_type", "ESCALATE"),
        "pipeline_id": payload.get("pipeline_id", "unknown"),
        "issue": payload.get("issue", "No issue description provided"),
        "options": payload.get("options"),
        "timestamp": signal_data.get("timestamp"),
        "source": signal_data.get("source"),
        "raw": signal_data,
    }

    return result


def handle_pipeline_complete(
    signal_data: dict[str, Any],
    dot_path: str,
) -> dict[str, Any]:
    """Finalise a pipeline after receiving PIPELINE_COMPLETE signal.

    Reads the PIPELINE_COMPLETE signal payload and produces a completion
    summary with node statuses.

    Args:
        signal_data: Parsed signal dict from the Pilot.
        dot_path: Absolute path to the pipeline DOT file.

    Returns:
        Dict with completion summary:
        ``{"status": "complete", "pipeline_id": ..., "dot_path": ...,
           "node_statuses": ..., "timestamp": ..., "raw": ...}``
    """
    payload = signal_data.get("payload", {})

    # Extract node statuses from payload if available (Pilot may include them).
    node_statuses = payload.get("node_statuses", {})

    # Parse issue string to extract structured data if node_statuses not present.
    issue = payload.get("issue", "")
    if not node_statuses and issue:
        node_statuses = {"summary": issue}

    result: dict[str, Any] = {
        "status": "complete",
        "pipeline_id": payload.get("pipeline_id", "unknown"),
        "dot_path": dot_path,
        "node_statuses": node_statuses,
        "issue": issue,
        "timestamp": signal_data.get("timestamp"),
        "source": signal_data.get("source"),
        "raw": signal_data,
    }

    return result


# ---------------------------------------------------------------------------
# Lifecycle launcher
# ---------------------------------------------------------------------------


def launch_lifecycle(
    prd_path: str,
    initiative_id: str | None = None,
    target_dir: str | None = None,
    max_cycles: int = 3,
    model: str = DEFAULT_MODEL,
    max_turns: int = DEFAULT_MAX_TURNS,
    dry_run: bool = False,
) -> dict | None:
    """Launch a self-driving lifecycle pipeline from a PRD path.

    Steps:
    1. Derive initiative_id from PRD filename if not provided
    2. Create placeholder state files for sd_path validation
    3. Instantiate cobuilder-lifecycle template
    4. Validate rendered DOT
    5. Launch Pilot on the pipeline (or return config if dry_run)

    Args:
        prd_path: Path to the PRD markdown file (e.g. PRD-AUTH-001.md).
        initiative_id: Optional override for the initiative identifier.
            Defaults to the PRD stem with 'PRD-' prefix stripped.
        target_dir: Target implementation repo directory. Defaults to cwd.
        max_cycles: Maximum full research→validate cycles before forced exit.
        model: Claude model to use for the Pilot.
        max_turns: Maximum SDK turns.
        dry_run: If True, return config dict without launching the Pilot.

    Returns:
        Result dict from launch_guardian(), or a dry-run config dict.
    """
    import subprocess

    # 1. Derive initiative_id
    if initiative_id is None:
        stem = Path(prd_path).stem  # e.g. PRD-AUTH-001
        initiative_id = stem.replace("PRD-", "", 1)

    # 2. Resolve paths
    project_root = os.getcwd()
    cobuilder_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if target_dir is None:
        target_dir = project_root

    # 3. Create placeholder state files
    state_dir = Path(target_dir) / "state"
    state_dir.mkdir(exist_ok=True)
    for suffix in ["-research.json", "-refined.md"]:
        placeholder = state_dir / f"{initiative_id}{suffix}"
        if not placeholder.exists():
            placeholder.write_text(
                f"# Placeholder — will be populated by pipeline\n"
            )

    # 4. Instantiate template
    from cobuilder.templates.instantiator import instantiate_template
    dot_output = Path(".pipelines/pipelines") / f"lifecycle-{initiative_id}.dot"
    dot_output.parent.mkdir(parents=True, exist_ok=True)

    instantiate_template(
        "cobuilder-lifecycle",
        {
            "initiative_id": initiative_id,
            "business_spec_path": str(Path(prd_path).resolve()),
            "target_dir": target_dir,
            "cobuilder_root": cobuilder_root,
            "max_cycles": max_cycles,
            "require_human_before_launch": True,
        },
        output_path=str(dot_output),
        validate=False,  # Validate via cli.py below
    )

    # 5. Validate
    result = subprocess.run(
        ["python3", "cobuilder/engine/cli.py", "validate", str(dot_output)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise ValueError(
            f"Pipeline validation failed:\n{result.stderr or result.stdout}"
        )

    # 6. Launch or dry-run
    dot_path = str(dot_output.resolve())
    pipeline_id = f"lifecycle-{initiative_id}"

    if dry_run:
        return {
            "dry_run": True,
            "initiative_id": initiative_id,
            "prd_path": prd_path,
            "dot_path": dot_path,
            "pipeline_id": pipeline_id,
            "model": model,
            "max_turns": max_turns,
            "max_cycles": max_cycles,
        }

    # Launch Pilot (reuse existing launch_guardian logic)
    return launch_guardian(
        dot_path=dot_path,
        project_root=project_root,
        pipeline_id=pipeline_id,
        model=model,
        max_turns=max_turns,
        target_dir=target_dir,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Parse arguments and launch one or multiple Pilot agents."""
    # Load attractor-specific API credentials before any SDK call.
    # claude_code_sdk.query() reads ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL from
    # os.environ, so this must happen before argparse or SDK initialisation.
    os.environ.update(load_engine_env())

    args = parse_args(argv)

    # -----------------------------------------------------------------------
    # Multi-launch mode: --multi <configs.json>
    # -----------------------------------------------------------------------
    if args.multi is not None:
        multi_path = os.path.abspath(args.multi)
        try:
            with open(multi_path, encoding="utf-8") as fh:
                configs = json.load(fh)
        except FileNotFoundError:
            print(json.dumps({
                "status": "error",
                "message": f"Config file not found: {multi_path}",
            }))
            sys.exit(1)
        except json.JSONDecodeError as exc:
            print(json.dumps({
                "status": "error",
                "message": f"Invalid JSON in {multi_path}: {exc}",
            }))
            sys.exit(1)

        if not isinstance(configs, list):
            print(json.dumps({
                "status": "error",
                "message": "--multi JSON file must contain a list of config dicts",
            }))
            sys.exit(1)

        # Propagate top-level dry_run flag to all configs that don't set it.
        if args.dry_run:
            for cfg in configs:
                cfg.setdefault("dry_run", True)

        results = launch_multiple_guardians(configs)
        print(json.dumps(results, indent=2))
        return

    # -----------------------------------------------------------------------
    # Lifecycle mode: --lifecycle <prd_path>
    # -----------------------------------------------------------------------
    if args.lifecycle is not None:
        result = launch_lifecycle(
            prd_path=args.lifecycle,
            initiative_id=args.pipeline_id,  # optional override
            target_dir=args.target_dir,
            max_cycles=3,
            model=args.model,
            max_turns=args.max_turns,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            print(json.dumps(result, indent=2))
        return

    # -----------------------------------------------------------------------
    # Single Pilot mode: --dot + --pipeline-id
    # -----------------------------------------------------------------------
    dot_path = os.path.abspath(args.dot)
    cwd = args.project_root or os.getcwd()
    scripts_dir = resolve_scripts_dir()

    # Read target_dir from DOT graph_attrs (CLI arg overrides DOT value).
    graph_target_dir = ""
    if os.path.exists(dot_path):
        from cobuilder.engine.dispatch_parser import parse_dot  # noqa: PLC0415 (lazy import — intentional)
        with open(dot_path, encoding="utf-8") as _fh:
            dot_data = parse_dot(_fh.read())
        graph_target_dir = dot_data.get("graph_attrs", {}).get("target_dir", "")
    target_dir = args.target_dir or graph_target_dir
    if not target_dir:
        print(json.dumps({
            "status": "error",
            "message": "target_dir is required: set in DOT graph attrs or pass --target-dir",
        }))
        sys.exit(1)

    with logfire.span("guardian.main", pipeline_id=args.pipeline_id):
        system_prompt = build_system_prompt(
            dot_path=dot_path,
            pipeline_id=args.pipeline_id,
            scripts_dir=scripts_dir,
            signal_timeout=args.signal_timeout,
            max_retries=args.max_retries,
            target_dir=target_dir,
        )

        initial_prompt = build_initial_prompt(
            dot_path=dot_path,
            pipeline_id=args.pipeline_id,
            scripts_dir=scripts_dir,
            target_dir=target_dir,
        )

    # Dry-run: log config and exit without calling the SDK.
    if args.dry_run:
        config: dict[str, Any] = {
            "dry_run": True,
            "dot_path": dot_path,
            "pipeline_id": args.pipeline_id,
            "model": args.model,
            "max_turns": args.max_turns,
            "signal_timeout": args.signal_timeout,
            "max_retries": args.max_retries,
            "project_root": cwd,
            "signals_dir": args.signals_dir,
            "target_dir": target_dir,
            "scripts_dir": scripts_dir,
            "system_prompt_length": len(system_prompt),
            "initial_prompt_length": len(initial_prompt),
        }
        print(json.dumps(config, indent=2))
        sys.exit(0)

    # Register Layer 0/1 (Pilot) identity before starting the agent loop.
    identity_registry.create_identity(
        role="launch",
        name="guardian",
        session_id="launch-guardian",
        worktree=os.getcwd(),
    )

    # Live run: launch the Pilot agent with retry loop.
    # If the Pilot SDK session crashes or times out, retry up to max_retries times.
    guardian_retries = args.max_retries
    attempt = 0
    while True:
        attempt += 1
        print(f"[Layer 0] Launching Pilot (attempt {attempt}/{guardian_retries + 1})", flush=True)
        result = launch_guardian(
            dot_path=dot_path,
            project_root=cwd,
            pipeline_id=args.pipeline_id,
            model=args.model,
            max_turns=args.max_turns,
            signal_timeout=args.signal_timeout,
            max_retries=args.max_retries,
            signals_dir=args.signals_dir,
            target_dir=target_dir,
        )
        print(json.dumps(result, indent=2))

        status = result.get("status", "error")
        if status == "ok":
            break  # Pilot completed successfully

        # Check if we should retry
        if attempt > guardian_retries:
            print(f"[Layer 0] Pilot failed after {attempt} attempts. Giving up.", file=sys.stderr, flush=True)
            sys.exit(1)

        # Retry on timeout or error (Pilot SDK crash)
        print(f"[Layer 0] Pilot returned status={status}. Retrying in 5s...", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()

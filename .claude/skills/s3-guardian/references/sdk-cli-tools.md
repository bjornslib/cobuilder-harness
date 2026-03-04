# SDK Mode CLI Reference

Complete argparse reference for all 15 SDK mode scripts. Organized by layer.

Scripts live at `.claude/scripts/attractor/` in the implementation repo.

---

## Layer 0 — Terminal Entry Points

### `launch_guardian.py`

Terminal-to-Guardian bridge. Launches Guardian agent(s) and monitors pipeline execution.

```
usage: launch_guardian.py [-h] (--dot DOT | --multi MULTI)
                          [--pipeline-id PIPELINE_ID]
                          [--project-root PROJECT_ROOT]
                          [--max-turns MAX_TURNS] [--model MODEL]
                          [--signals-dir SIGNALS_DIR]
                          [--signal-timeout SIGNAL_TIMEOUT]
                          [--max-retries MAX_RETRIES] [--dry-run]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--dot DOT` | One of --dot/--multi | — | Path to pipeline .dot file (single guardian mode) |
| `--multi MULTI` | One of --dot/--multi | — | Path to JSON file with list of pipeline configs |
| `--pipeline-id ID` | With --dot | — | Unique pipeline identifier |
| `--project-root PATH` | No | cwd | Working directory for the agent |
| `--max-turns N` | No | 200 | Max SDK turns |
| `--model MODEL` | No | claude-sonnet-4-6 | Claude model to use |
| `--signals-dir DIR` | No | `.claude/attractor/signals/` | Override signals directory |
| `--signal-timeout SECS` | No | 600 | Seconds to wait per signal wait cycle |
| `--max-retries N` | No | 3 | Max retries per node before escalating |
| `--dry-run` | No | false | Log configuration without invoking SDK |

**Output (stdout JSON)**:
```json
{
    "status": "complete|error",
    "pipeline_id": "PRD-AUTH-001",
    "nodes_validated": 5,
    "nodes_failed": 0,
    "duration_seconds": 1234
}
```

**Multi-pipeline JSON format** (for `--multi`):
```json
[
    {"dot_path": "auth.dot", "project_root": "/impl", "pipeline_id": "PRD-AUTH-001"},
    {"dot_path": "dash.dot", "project_root": "/impl", "pipeline_id": "PRD-DASH-002"}
]
```

---

## Layer 1 — Headless Guardian

### `guardian_agent.py`

Pipeline execution engine. Drives the 4-phase loop: read DOT, spawn runners, process signals, transition nodes.

```
usage: guardian_agent.py [-h] --dot DOT --pipeline-id PIPELINE_ID
                         [--project-root PROJECT_ROOT] [--max-turns MAX_TURNS]
                         [--model MODEL] [--signals-dir SIGNALS_DIR]
                         [--signal-timeout SIGNAL_TIMEOUT]
                         [--max-retries MAX_RETRIES] [--dry-run]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--dot DOT` | Yes | — | Path to pipeline .dot file |
| `--pipeline-id ID` | Yes | — | Unique pipeline identifier |
| `--project-root PATH` | No | cwd | Working directory |
| `--max-turns N` | No | 200 | Max SDK turns |
| `--model MODEL` | No | claude-sonnet-4-6 | Claude model |
| `--signals-dir DIR` | No | auto | Override signals directory |
| `--signal-timeout SECS` | No | 600 | Signal wait timeout |
| `--max-retries N` | No | 3 | Max retries per node |
| `--dry-run` | No | false | Log config only |

**Execution Flow (4 phases)**:
1. Read DOT pipeline, identify pending nodes with met dependencies
2. For each ready codergen node, call `spawn_runner.py`
3. Wait for runner signals via `wait_for_signal.py --target guardian`
4. Process signal: validate work, transition DOT node, checkpoint

**System Prompt**: Constructed dynamically with pipeline context, node list, and available tools.

### `spawn_runner.py`

Launches a Runner subprocess for a specific pipeline node.

```
usage: spawn_runner.py [-h] --node NODE --prd PRD
                       [--solution-design SOLUTION_DESIGN]
                       [--acceptance ACCEPTANCE] [--target-dir TARGET_DIR]
                       [--bead-id BEAD_ID]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--node NODE` | Yes | — | Pipeline node identifier |
| `--prd PRD` | Yes | — | PRD reference (e.g., PRD-AUTH-001) |
| `--solution-design PATH` | No | — | Path to solution design doc |
| `--acceptance TEXT` | No | — | Acceptance criteria text |
| `--target-dir PATH` | No | cwd | Working directory for runner |
| `--bead-id ID` | No | — | Beads issue/task identifier |

**State file**: Written to `.claude/attractor/runner-state-{node}.json`

### `respond_to_runner.py`

Guardian writes a response signal for the Runner to read.

```
usage: respond_to_runner.py [-h] --node NODE [--feedback FEEDBACK]
                            [--response RESPONSE] [--reason REASON]
                            [--new-status NEW_STATUS] [--message MESSAGE]
                            SIGNAL_TYPE
```

| Arg/Flag | Required | Description |
|----------|----------|-------------|
| `SIGNAL_TYPE` (positional) | Yes | Signal type to send |
| `--node NODE` | Yes | Node identifier |
| `--feedback TEXT` | No | Feedback text |
| `--response TEXT` | No | Response text |
| `--reason TEXT` | No | Reason for decision |
| `--new-status STATUS` | No | New status to assign |
| `--message TEXT` | No | Additional message |

**Valid SIGNAL_TYPEs** (Guardian to Runner):
- `VALIDATION_PASSED` — Work approved, node transitions to validated
- `VALIDATION_FAILED` — Work rejected, node may retry
- `INPUT_RESPONSE` — Answer to Runner's question
- `KILL_ORCHESTRATOR` — Stop the orchestrator for this node
- `GUIDANCE` — Advice for the Runner without changing node state

### `escalate_to_terminal.py`

Guardian escalates to Terminal (Layer 0) for both pipeline completion and blocking issues.

```
usage: escalate_to_terminal.py [-h] --pipeline PIPELINE --issue ISSUE
                               [--options OPTIONS]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--pipeline ID` | Yes | — | Pipeline identifier |
| `--issue TEXT` | Yes | — | Description of the issue (or "PIPELINE_COMPLETE: ...") |
| `--options JSON` | No | — | JSON-encoded options for the user (e.g., `'["retry", "skip"]'`) |

---

## Layer 2 — Runner

### `runner_agent.py`

Orchestrator monitor. Spawns orchestrator (headless by default, legacy tmux for debugging), monitors progress via signal files, and signals Guardian at decision points.

```
usage: runner_agent.py [-h] --node NODE --prd PRD --session SESSION
                       [--dot-file DOT_FILE]
                       [--solution-design SOLUTION_DESIGN]
                       [--acceptance ACCEPTANCE] [--target-dir TARGET_DIR]
                       [--bead-id BEAD_ID] [--check-interval CHECK_INTERVAL]
                       [--stuck-threshold STUCK_THRESHOLD]
                       [--max-turns MAX_TURNS] [--model MODEL]
                       [--signals-dir SIGNALS_DIR] [--dry-run]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--node NODE` | Yes | — | Pipeline node identifier |
| `--prd PRD` | Yes | — | PRD reference |
| `--session SESSION` | Yes | — | Session name for orchestrator (Legacy: tmux session name; headless: used for state file naming) |
| `--dot-file PATH` | No | — | Path to pipeline .dot file |
| `--solution-design PATH` | No | — | Path to solution design doc |
| `--acceptance TEXT` | No | — | Acceptance criteria text |
| `--target-dir PATH` | No | cwd | Working directory |
| `--bead-id ID` | No | — | Beads issue identifier |
| `--check-interval SECS` | No | 30 | Seconds between polling cycles |
| `--stuck-threshold SECS` | No | 300 | Seconds of no progress → ORCHESTRATOR_STUCK |
| `--max-turns N` | No | 100 | Max SDK turns |
| `--model MODEL` | No | claude-sonnet-4-6 | Claude model |
| `--signals-dir DIR` | No | auto | Override signals directory |
| `--dry-run` | No | false | Log config only |

**Monitoring loop**: Every `check-interval` seconds, checks signal files and process health → LLM interpretation → decide: continue monitoring, signal Guardian, or escalate. (Legacy: captures tmux output instead of signal files when in tmux mode.)

### `signal_guardian.py`

Runner writes a signal to Guardian.

```
usage: signal_guardian.py [-h] --node NODE [--evidence EVIDENCE]
                          [--question QUESTION] [--options OPTIONS]
                          [--commit COMMIT] [--summary SUMMARY]
                          [--reason REASON] [--last-output LAST_OUTPUT]
                          [--duration DURATION]
                          SIGNAL_TYPE
```

| Arg/Flag | Required | Description |
|----------|----------|-------------|
| `SIGNAL_TYPE` (positional) | Yes | Signal type to send |
| `--node NODE` | Yes | Node identifier |
| `--evidence PATH` | No | Path to evidence file/dir |
| `--question TEXT` | No | Question for Guardian |
| `--options JSON` | No | JSON-encoded options dict |
| `--commit HASH` | No | Git commit hash |
| `--summary TEXT` | No | Summary text |
| `--reason TEXT` | No | Reason text |
| `--last-output TEXT` | No | Last output from orchestrator |
| `--duration SECS` | No | Duration in seconds |

**Valid SIGNAL_TYPEs** (Runner to Guardian):
- `NEEDS_REVIEW` — Node work complete, ready for validation
- `NEEDS_INPUT` — Runner has a question for Guardian
- `VIOLATION` — Detected a protocol violation
- `ORCHESTRATOR_STUCK` — No progress for `stuck-threshold` seconds
- `ORCHESTRATOR_CRASHED` — Orchestrator process died (headless: subprocess exited unexpectedly; legacy tmux: session terminated)
- `NODE_COMPLETE` — Node implementation finished

### `wait_for_guardian.py`

Runner blocks until Guardian responds with a signal for this node.

```
usage: wait_for_guardian.py [-h] --node NODE [--timeout TIMEOUT]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--node NODE` | Yes | — | Node identifier (filters signals to this node) |
| `--timeout SECS` | No | 300 | Timeout in seconds |

**Note**: Filters for signals with `target: "runner"` AND matching node ID.

### `spawn_orchestrator.py`

Launches Claude Code as orchestrator. Headless mode (default) runs `claude -p` as a subprocess; legacy tmux mode creates an interactive terminal session for debugging.

```
usage: spawn_orchestrator.py [-h] --node NODE --prd PRD [--worktree WORKTREE]
                             [--session-name SESSION_NAME] [--prompt PROMPT]
                             [--mode {headless,tmux}]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--node NODE` | Yes | — | Node identifier |
| `--prd PRD` | Yes | — | PRD reference |
| `--worktree PATH` | No | — | Working directory path |
| `--session-name NAME` | No | `orch-{node}` | Session name (headless: state file naming; legacy tmux: session name) |
| `--prompt TEXT` | No | — | Initial prompt (headless: passed as `-p` argument; legacy tmux: sent after launch) |
| `--mode MODE` | No | `headless` | Dispatch mode: `headless` (subprocess, default) or `tmux` (interactive, debugging only) |

### `capture_output.py` *(Legacy: tmux debugging only)*

Captures recent output from a tmux session pane. Only used in legacy tmux mode for debugging; headless mode uses signal files instead.

```
usage: capture_output.py [-h] --session SESSION [--lines LINES] [--pane PANE]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--session NAME` | Yes | — | tmux session name |
| `--lines N` | No | 100 | Number of lines to capture |
| `--pane ID` | No | first pane | Pane identifier |

### `check_orchestrator_alive.py` *(Legacy: tmux debugging only)*

Checks if a tmux session exists (exit code 0 = alive, 1 = dead). Only used in legacy tmux mode; headless mode checks process liveness via PID.

```
usage: check_orchestrator_alive.py [-h] --session SESSION
```

| Flag | Required | Description |
|------|----------|-------------|
| `--session NAME` | Yes | tmux session name to check |

### `send_to_orchestrator.py` *(Legacy: tmux debugging only)*

Sends text to a tmux session via `send-keys`. Only used in legacy tmux mode; headless mode communicates via signal files (`respond_to_runner.py`).

```
usage: send_to_orchestrator.py [-h] --session SESSION --message MESSAGE
```

| Flag | Required | Description |
|------|----------|-------------|
| `--session NAME` | Yes | tmux session name |
| `--message TEXT` | Yes | Text to send |

---

## Signal Protocol

### `signal_protocol.py` (Library — No CLI)

Shared library used by all signal-writing/reading scripts. Not invoked directly.

**Key functions**:
- `write_signal(source, target, signal_type, payload, signals_dir)` — Creates signal JSON file
- `read_signal(path)` — Parses signal JSON file
- `find_signals(target, signals_dir)` — Finds signals for a target layer
- `move_to_processed(path)` — Moves consumed signal to `processed/` subdirectory

**File naming convention**: `{timestamp}-{source}-{target}-{signal_type}.json`

**Signal JSON schema**:
```json
{
    "source": "runner|guardian|terminal",
    "target": "runner|guardian|terminal",
    "signal_type": "NEEDS_REVIEW|VALIDATION_PASSED|...",
    "timestamp": "20260224T120000Z",
    "payload": { "node_id": "...", "...": "..." }
}
```

**Directory**: `.claude/attractor/signals/` (or `$ATTRACTOR_SIGNALS_DIR`)

### `wait_for_signal.py`

Blocks until a signal for a target layer appears.

```
usage: wait_for_signal.py [-h] --target TARGET [--timeout TIMEOUT] [--poll POLL]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--target TARGET` | Yes | — | Target layer to wait for (e.g., "guardian", "runner", "terminal") |
| `--timeout SECS` | No | 300 | Timeout in seconds |
| `--poll SECS` | No | 5 | Poll interval in seconds |

**Behavior**: Polls `signals_dir` for files matching `*-{target}-*.json`. Returns first match as JSON to stdout. Exits with code 1 on timeout.

### `read_signal.py`

Parses and prints a signal file.

```
usage: read_signal.py [-h] signal_file_path
```

| Arg | Required | Description |
|-----|----------|-------------|
| `signal_file_path` (positional) | Yes | Path to the signal JSON file |

**Output**: Pretty-printed JSON to stdout.

---

## Signal Routing Table

### Source → Target Matrix

| Source | Target | Signal Types | Written By | Read By |
|--------|--------|-------------|------------|---------|
| Runner | Guardian | `NEEDS_REVIEW`, `NEEDS_INPUT`, `VIOLATION`, `ORCHESTRATOR_STUCK`, `ORCHESTRATOR_CRASHED`, `NODE_COMPLETE` | `signal_guardian.py` | `wait_for_signal.py --target guardian` |
| Guardian | Runner | `VALIDATION_PASSED`, `VALIDATION_FAILED`, `INPUT_RESPONSE`, `KILL_ORCHESTRATOR`, `GUIDANCE` | `respond_to_runner.py` | `wait_for_guardian.py --node {id}` |
| Guardian | Terminal | `PIPELINE_COMPLETE`, `ESCALATION`, `GUARDIAN_ERROR` | `escalate_to_terminal.py` | `wait_for_signal.py --target terminal` |

### Signal File Location

All signals live in `.claude/attractor/signals/` (flat directory).

**Glob patterns for finding signals**:
- All signals FOR terminal: `*-terminal-*.json`
- All signals FROM runner: `*-runner-*.json`
- All signals FOR a specific node: requires reading JSON payload (no filename filtering)
- Processed (consumed): `processed/` subdirectory

---

## Pipeline Runner (Anthropic API Alternative)

### `pipeline_runner.py`

Production Pipeline Runner — analyzes and executes Attractor DOT pipelines using LLM tool-use.

```
usage: pipeline_runner.py [-h] [--execute]
                          [--channel {stdout,native_teams}]
                          [--verbose] [--json]
                          [--max-iterations MAX_ITERATIONS]
                          [--session-id SESSION_ID] [--mb-target MB_TARGET]
                          [--team-name TEAM_NAME]
                          pipeline
```

| Arg/Flag | Required | Default | Description |
|----------|----------|---------|-------------|
| `pipeline` (positional) | Yes | — | Path to .dot pipeline file |
| `--execute` | No | false (plan-only) | Execute actions (spawn orchestrators, run validation) |
| `--channel CHAN` | No | stdout | Communication channel: `stdout`, `native_teams` |
| `--verbose`, `-v` | No | false | Print tool call details to stderr |
| `--json` | No | false | Output raw RunnerPlan JSON |
| `--max-iterations N` | No | 20 | Maximum tool-use iterations |
| `--session-id ID` | No | — | Session ID for state persistence |
| `--team-name NAME` | No | — | Native teams team name (for `native_teams` channel) |

**RunnerPlan JSON schema** (output with `--json`):
```json
{
    "pipeline_path": "path/to/pipeline.dot",
    "total_nodes": 8,
    "ready_nodes": ["impl_auth", "impl_db"],
    "actions": [
        {"type": "spawn_orchestrator", "node": "impl_auth", "reason": "..."},
        {"type": "dispatch_validation", "node": "validate_auth", "reason": "..."}
    ],
    "summary": "2 nodes ready for execution"
}
```

**Channel adapters**:
- `stdout` — Print actions to console (default, for plan-only mode)
- `native_teams` — Send via Agent Teams messaging

### `poc_test_scenarios.py`

Run POC test scenarios for the Pipeline Runner agent.

```
usage: poc_test_scenarios.py [-h] [--scenario [N ...]] [--verbose] [--json] [--list]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--scenario N [N ...]` | No | all | Scenario IDs to run |
| `--verbose`, `-v` | No | false | Print tool call details |
| `--json` | No | false | Output results as JSON |
| `--list` | No | false | List available scenarios without running |

**Available scenarios**:

| ID | Name | Description |
|----|------|-------------|
| 1 | Fresh Pipeline | All nodes pending. Should propose spawn_orchestrator for first ready node. |
| 2 | Mid-Execution | First node validated. Should propose spawn for second ready node. |
| 3 | Validation Needed | Node at impl_complete. Should propose dispatch_validation. |
| 4 | Pipeline Complete | All nodes validated. Should propose signal_finalize. |
| 5 | Stuck Pipeline | Node failed multiple times. Should propose signal_stuck. |
| 6 | Parallel Pipeline | Multiple independent ready nodes. Should propose spawn for each. |

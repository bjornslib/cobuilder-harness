---
title: "SD-COBUILDER-CONSOLIDATION-002: Subsystem Decomposition and Interface Contracts"
status: active
type: reference
last_verified: 2026-03-09
grade: authoritative
---

# SD-COBUILDER-CONSOLIDATION-002: Subsystem Decomposition and Interface Contracts

**Reasoning mode**: Systematic Decomposition — focuses on module boundaries, interface contracts, and dependency ordering rather than file-move logistics.

**Companion document**: SD-COBUILDER-CONSOLIDATION-001 covers the *what* (file moves, naming, runtime state migration). This document covers the *how*: formal subsystem ownership, interface signatures, data contracts, dependency graph, and per-subsystem risk.

**Related PRD**: PRD-HARNESS-UPGRADE-001

---

## 1. Executive Summary

The harness has seven distinct subsystems doing coherent work but with blurred ownership boundaries. The structural problem is not that two codebases exist — it is that the same *responsibility* is encoded in two places with diverging state (specifically: state machine transitions, signal directory resolution, and the pipeline runner contract).

This document defines eight subsystems with non-overlapping responsibilities, specifies their public interfaces, identifies the three critical divergence points that must be resolved before any file moves, and provides a dependency-ordered migration sequence that eliminates the risk of simultaneous-breakage.

**Hindsight findings surfaced before this design**:
- Signal Directory Resolution pattern (priority-order fallback) is validated and must be preserved
- `CLAUDECODE` env var unset in child processes is mandatory (breaking omission risk)
- Stepwise migration strongly preferred over big-bang rewrite (user opinion, high confidence)
- Namespace shadowing is a real risk: avoid putting both `attractor/` and `cobuilder/` on sys.path simultaneously
- ZeroRepo `__main__.py` gap: any new sub-package must have `__main__.py` if it registers a console script

---

## 2. Subsystem Map

```
┌──────────────────────────────────────────────────────────────────────────┐
│  S1: Claude Code Config (.claude/ native)                               │
│  Reads: S5 (agent definitions)                                           │
│  Writes: Nothing at runtime                                              │
├──────────────────────────────────────────────────────────────────────────┤
│  S2: Pipeline DOT Layer (cobuilder/pipeline/)   ← ZERO-DEPENDENCY CORE  │
│  Reads: DOT files on disk                                                │
│  Writes: DOT files (transition), signal files, checkpoint JSONs          │
├──────────────────────────────────────────────────────────────────────────┤
│  S3: Pipeline Generation (cobuilder/pipeline/generate.py + enrichers)   │
│  Reads: SD markdown, RepoMap baseline (S6), beads data                  │
│  Writes: DOT files                                                       │
├──────────────────────────────────────────────────────────────────────────┤
│  S4a: Python Runner (attractor/pipeline_runner.py → cobuilder/attractor/)│
│  Reads: DOT files via S2, signals via S2                                 │
│  Writes: DOT states via S2, checkpoints via S2, signals via S2           │
│  Dispatches: Workers via S5                                              │
├──────────────────────────────────────────────────────────────────────────┤
│  S4b: Engine Runner (cobuilder/engine/)                                  │
│  Reads: DOT files via S2 (parser)                                        │
│  Writes: Run dir artifacts, events via event bus                         │
│  Dispatches: Handlers (codergen via S5)                                  │
├──────────────────────────────────────────────────────────────────────────┤
│  S5: Worker Dispatch (cobuilder/pipeline/dispatch.py — NEW)              │
│  Reads: Agent definitions from S1, SD files, tool allowlists            │
│  Writes: Signal evidence files via S2                                    │
│  Dispatches: claude_code_sdk workers                                     │
├──────────────────────────────────────────────────────────────────────────┤
│  S6: RepoMap / ZeroRepo (cobuilder/repomap/)                            │
│  Reads: Codebase files, .repomap/ baselines                             │
│  Writes: .repomap/ baselines, ontology, vector store                    │
├──────────────────────────────────────────────────────────────────────────┤
│  S7: Runtime State (var/cobuilder/ directory convention)                 │
│  Not a Python module — a filesystem layout contract                      │
└──────────────────────────────────────────────────────────────────────────┘

Dependency edges (A → B means A depends on B):
  S3 → S6 (repomap context)
  S3 → S2 (write DOT output)
  S4a → S2 (read/write DOT and signals)
  S4a → S5 (dispatch workers)
  S4b → S2 (DOT parsing only)
  S4b → S5 (codergen handler dispatch)
  S5 → S1 (read agent definitions)
  S5 → S2 (write signal evidence)
  CLI → S2, S3, S4a, S4b, S6 (entry point for all)
```

---

## 3. Critical Divergence Points

Three divergences exist between attractor and cobuilder/pipeline that **must be resolved before any file consolidation**. Resolving them in the wrong order creates transient breakage in running pipelines.

### D1: `VALID_TRANSITIONS` State Machine Mismatch

| Module | VALID_TRANSITIONS content |
|--------|--------------------------|
| `attractor/transition.py` | `validated → accepted` (accepted is terminal), `failed → {active, pending}` |
| `cobuilder/pipeline/transition.py` | No `accepted` state. `failed → {active}` only |

**Impact**: Any pipeline with nodes in `accepted` status will raise `InvalidTransitionError` if loaded by the cobuilder version. Any pipeline that relies on gate nodes resetting to `pending` on runner restart will fail with the attractor version.

**Resolution** (must happen first, in D-Order Step 0):

Canonical transitions after reconciliation:
```python
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending":      {"active"},
    "active":       {"impl_complete", "validated", "failed"},
    "impl_complete":{"validated", "failed", "active"},   # active = retry
    "failed":       {"active", "pending"},               # pending: gate nodes reset on runner restart
    "validated":    {"accepted"},
    "accepted":     set(),                               # terminal
}
```

The `failed → pending` transition is used by `pipeline_runner.py` to reset gate nodes on runner restart. It is essential for resilient pipeline recovery and must be present in the canonical version.

**Regression test** (add to `cobuilder/pipeline/tests/test_transition.py`):
```python
def test_accepted_is_terminal():
    """accepted state must have no valid successors."""
    assert VALID_TRANSITIONS["accepted"] == set()

def test_gate_reset_path():
    """failed → pending must be valid for gate node recovery."""
    assert "pending" in VALID_TRANSITIONS["failed"]

def test_all_existing_dot_states():
    """All status values found in existing DOT files must be valid keys."""
    for status in ["pending", "active", "impl_complete", "validated", "accepted", "failed"]:
        assert status in VALID_TRANSITIONS
```

### D2: Signal Directory Resolution Difference

| Module | Step 3 default (git-root path) |
|--------|-------------------------------|
| `attractor/signal_protocol.py` | `{git_root}/.claude/attractor/signals/` |
| `cobuilder/pipeline/signal_protocol.py` | `{git_root}/.claude/attractor/signals/` (same — but does not define `COBUILDER_STATE_ROOT` env var) |

The divergence is not in the current path but in the *extension point*: `attractor/signal_protocol.py` checks `ATTRACTOR_SIGNALS_DIR` env var; `cobuilder/pipeline/signal_protocol.py` does not define a canonical env var name.

**Resolution** (D-Order Step 0, same commit as D1):

Define in `cobuilder/settings.py`:
```python
COBUILDER_STATE_ROOT: Path = Path(
    os.getenv("COBUILDER_STATE_ROOT", str(Path.cwd() / "var" / "cobuilder"))
)
```

Update `cobuilder/pipeline/signal_protocol.py` resolution order:
```python
def resolve_signals_dir(
    signals_dir: str | None = None,
    dot_path: str | None = None,
) -> Path:
    """Resolve signal directory using priority-order fallback.

    Priority order:
    1. Explicit signals_dir parameter
    2. ATTRACTOR_SIGNALS_DIR environment variable (backward compat)
    3. COBUILDER_STATE_ROOT/signals/ environment variable
    4. {dot_file_parent}/signals/ (DOT-scoped)
    5. {git_root}/var/cobuilder/signals/ (project-local default)
    6. ~/.cobuilder/signals/ (home fallback)
    """
```

### D3: Three Pipeline Runner Implementations with No Clear Owner

Three runners exist with overlapping names and no documentation clarifying which to use:

| Runner | Location | Dispatch | LLM? | Status |
|--------|----------|---------|------|--------|
| Python state machine | `attractor/pipeline_runner.py` | AgentSDK | No | ACTIVE — use this |
| Async engine | `cobuilder/engine/runner.py` | Handlers (codergen via SDK) | No | ACTIVE — use for observability |
| LLM-based agent | `cobuilder/orchestration/pipeline_runner.py` | Anthropic API tools | Yes (33 turns) | SUPERSEDED — delete |

**Resolution** (D-Order Step 1, after D1 and D2):

Document the selection rule clearly:

```
Use attractor/pipeline_runner.py when:
  - Running a DOT pipeline end-to-end (codergen nodes, research nodes, gate nodes)
  - You need headless AgentSDK dispatch
  - You need checkpoint/resume semantics
  - Cost is a concern ($0 graph traversal)

Use cobuilder/engine/runner.py when:
  - You need full middleware observability (Logfire, token counting, audit)
  - You need the handler extensibility model
  - You are building tooling ON TOP of pipeline execution
  - Testing individual handler types

cobuilder/orchestration/pipeline_runner.py: DELETE (see Phase 2)
```

This rule is added as a docstring to `cobuilder/__init__.py` and to the CLI help text.

---

## 4. Interface Specifications

### 4.1 S2 Public Interface (Pipeline DOT Layer)

All of `cobuilder/pipeline/` functions that cross subsystem boundaries:

```python
# Parser
def parse_dot(content: str) -> dict[str, Any]: ...
def parse_file(path: str | Path) -> dict[str, Any]: ...

# Transitions
VALID_TRANSITIONS: dict[str, set[str]]
def apply_transition(
    dot_path: str | Path,
    node_id: str,
    new_status: str,
    dry_run: bool = False,
    reason: str = "",
) -> bool: ...

# Signals
def resolve_signals_dir(
    signals_dir: str | None = None,
    dot_path: str | None = None,
) -> Path: ...
def write_signal(
    signals_dir: Path,
    source: str,
    target: str,
    signal_type: str,
    payload: dict,
) -> Path: ...
def read_signals(signals_dir: Path) -> list[dict]: ...
def consume_signal(signal_path: Path) -> dict: ...  # atomic rename to processed/

# Checkpoints
def save_checkpoint(dot_path: str | Path, stage: str = "progress") -> Path: ...
def restore_checkpoint(dot_path: str | Path) -> dict | None: ...

# Node/Edge operations (used by CLI and runner)
def add_node(dot_path, node_id, attrs) -> None: ...
def modify_node(dot_path, node_id, updates) -> None: ...
def remove_node(dot_path, node_id) -> None: ...
def list_nodes(dot_path) -> list[dict]: ...
def add_edge(dot_path, src, dst, attrs) -> None: ...
def remove_edge(dot_path, src, dst) -> None: ...
def list_edges(dot_path) -> list[dict]: ...

# Status
def get_status_table(dot_path) -> dict: ...
def status_summary(dot_path) -> dict: ...  # {"total": N, "pending": N, ...}
```

**Invariants enforced by S2**:
- All DOT file writes go through file locking (`_dot_file_lock` context manager)
- Transitions validate against `VALID_TRANSITIONS` before writing
- Signal writes use atomic rename (`tmp → final`)
- `parse_file` is the only function allowed to read DOT files (no caller parses raw DOT independently)

### 4.2 S4a Public Interface (Python Runner)

```python
# cobuilder/attractor/pipeline_runner.py (after move)
class PipelineRunnerState:
    """Main state machine for DOT pipeline execution."""
    def __init__(
        self,
        dot_path: str,
        resume: bool = False,
        signals_dir: str | None = None,
        target_dir: str | None = None,
    ) -> None: ...

    def run(self) -> bool:
        """Run pipeline to completion. Returns True if all nodes accepted.""" ...

# Entry point (for direct invocation as subprocess):
def main() -> None: ...
```

**Invariants enforced by S4a**:
- S4a is the sole writer of DOT node statuses during a pipeline run
- S4a never calls LLM APIs directly; all LLM work is delegated to workers via S5
- S4a reads signals but never writes signal files for worker nodes (workers write their own signals)
- S4a DOES write signal evidence for gate/tool nodes it executes directly
- `CLAUDECODE` env var must be unset before any AgentSDK dispatch (S5 contract)

### 4.3 S5 Public Interface (Worker Dispatch)

This is a **new module** (`cobuilder/pipeline/dispatch.py`) consolidating functions currently spread across `attractor/dispatch_worker.py` and the private methods of `attractor/pipeline_runner.py`.

```python
# cobuilder/pipeline/dispatch.py

def compute_sd_hash(sd_content: str) -> str:
    """SHA256 of SD content, first 16 chars. Tamper detection."""

def load_agent_definition(
    worker_type: str,
    agents_dir: Path | None = None,
) -> AgentDefinition | None:
    """Load .claude/agents/{worker_type}.md and parse frontmatter.
    Returns None if agent definition not found."""

@dataclass
class AgentDefinition:
    skills_required: list[str]
    model: str
    max_turns: int
    system_prompt: str  # content after frontmatter

def build_worker_prompt(
    node: dict,
    pipeline_data: dict,
    sd_content: str,
    agent_def: AgentDefinition | None = None,
    predecessor_files: list[str] | None = None,
) -> str:
    """Build the task prompt injected into the worker's initial message."""

def build_system_prompt(
    worker_type: str,
    agent_def: AgentDefinition | None = None,
    tool_allowlist: list[str] | None = None,
) -> str:
    """Build the system prompt for the AgentSDK worker subprocess."""

async def dispatch_agent_sdk(
    node_id: str,
    worker_type: str,
    prompt: str,
    system_prompt: str,
    signals_dir: Path,
    max_turns: int = 50,
) -> None:
    """Dispatch a worker via claude_code_sdk.query(). Non-blocking — writes
    signal file when done. CLAUDECODE env var is unset in child process."""

def create_signal_evidence(
    node_id: str,
    status: str,
    sd_content: str = "",
    sd_path: str = "",
) -> dict:
    """Create signal evidence dict with sd_hash for tamper detection."""
```

**Critical invariant** (Hindsight: CLAUDECODE Env Var pattern):
```python
# Inside dispatch_agent_sdk, before sdk query:
import os
env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
# Pass env to sdk process — prevents nested session conflicts
```

**Tool allowlist** (Hindsight: allowlist > deny-list):
```python
DEFAULT_TOOL_ALLOWLIST = [
    "Bash", "Read", "Write", "Edit", "Glob", "Grep", "MultiEdit",
    "Task",  # for worker subagents
]
```

### 4.4 Signal Protocol Data Contract

This is the load-bearing contract between S4a (runner), S5 (dispatch), and validation agents:

```json
// Worker result signal — written by worker to {signals_dir}/{node_id}.json
{
  "status": "success" | "failed",
  "files_changed": ["path/to/file.py"],
  "message": "Human-readable summary",
  "sd_hash": "16-char-sha256",    // from compute_sd_hash()
  "node": "node_id",              // for routing
  "timestamp": "ISO-8601"
}

// Validation result signal — written by validation agent to {signals_dir}/{node_id}-validation.json
{
  "result": "pass" | "fail" | "requeue",
  "reason": "Human-readable explanation",
  "requeue_target": "node_id",    // only when result == "requeue"
  "guidance": "Instruction for requeued node"
}
```

**Runner response to signals** (mechanical, no LLM):
```
worker signal: "success"   → transition node: impl_complete → validated → accepted
worker signal: "failed"    → transition node: active → failed
validation signal: "pass"  → transition node: validated → accepted
validation signal: "fail"  → transition node: impl_complete → failed
validation signal: "requeue" → transition node: impl_complete → failed,
                               transition requeue_target node: {status} → pending
```

### 4.5 S7 Runtime State Layout Contract

```
var/cobuilder/                          # Root: set via COBUILDER_STATE_ROOT
├── pipelines/                          # Active DOT files
│   └── {pipeline-name}.dot
├── signals/                            # Signal files for active runs
│   ├── {pipeline-id}/                  # Scoped per pipeline run
│   │   ├── {node_id}.json             # Worker result
│   │   ├── {node_id}-validation.json  # Validation result
│   │   └── processed/                 # Consumed signals (moved here atomically)
│   └── processed/
├── checkpoints/                        # Pipeline state snapshots
│   └── {pipeline-name}-{stage}.json
├── runner-state/                       # Runner PID and state files
│   └── {node_id}-{timestamp}.json     # {"pid": N, "node": "...", "started_at": "..."}
├── runs/                               # Engine run directories (S4b)
│   └── {run-id}/
│       ├── checkpoint.json
│       ├── events.jsonl
│       └── nodes/{node_id}/outcome.json
├── evidence/                           # Validation evidence artifacts
└── progress/                           # Session progress logs
```

**Directory creation**: Each subsystem creates its subdirectory on first use:
```python
# cobuilder/settings.py
def ensure_state_dirs(root: Path | None = None) -> None:
    r = root or DEFAULT_STATE_ROOT
    for sub in ["pipelines", "signals", "checkpoints", "runner-state", "runs", "evidence", "progress"]:
        (r / sub).mkdir(parents=True, exist_ok=True)
```

---

## 5. Dependency-Ordered Migration Sequence

The key insight: **D1 (transition reconciliation) must happen before any file moves**. If a pipeline runner using the old `cobuilder/pipeline/transition.py` processes a DOT file that has `accepted` nodes, it raises an error. This breakage must be fixed while both codebases still exist, before consolidation.

```
D-Order Step 0: Resolve divergences (no file moves)
    a. Add `accepted` state + `failed → pending` to cobuilder/pipeline/transition.py
    b. Add COBUILDER_STATE_ROOT to cobuilder/settings.py
    c. Update signal_protocol.py resolution order
    d. Document runner selection rule in cobuilder/__init__.py
    GATE: pytest cobuilder/pipeline/tests/ + pytest .claude/scripts/attractor/tests/ BOTH pass

D-Order Step 1: Delete dead code (attractor/ only)
    a. Delete 13 confirmed-dead attractor files (Hindsight: 2026-03-04 cleanup list)
    b. Delete/update tests referencing deleted files
    GATE: pytest .claude/scripts/attractor/tests/ passes (green on reduced set)

D-Order Step 2: Delete superseded cobuilder/orchestration/ runner
    a. Update 2 optional import sites in engine/ (audit.py, codergen.py)
    b. Delete cobuilder/orchestration/{pipeline_runner,spawn_orchestrator,runner_hooks,runner_models,runner_tools}.py
    c. Retain cobuilder/orchestration/adapters/
    GATE: pytest cobuilder/ passes

D-Order Step 3: Create cobuilder/pipeline/dispatch.py (new module)
    a. Extract build_worker_prompt(), build_system_prompt(), dispatch_agent_sdk(),
       compute_sd_hash(), create_signal_evidence(), load_agent_definition()
       from attractor/pipeline_runner.py and attractor/dispatch_worker.py
    b. Write unit tests for dispatch.py
    c. Update attractor/pipeline_runner.py to import from cobuilder.pipeline.dispatch
    GATE: pytest cobuilder/pipeline/tests/test_dispatch.py passes;
          attractor/pipeline_runner.py still runs (smoke test)

D-Order Step 4: Move attractor support modules into cobuilder/pipeline/ (deduplication)
    a. For each duplicate (signal_protocol, transition, parser, validator, checkpoint):
       - Overwrite cobuilder/pipeline/ version with attractor canonical version
       - Replace attractor/ copy with a shim: `from cobuilder.pipeline.X import *`
    b. Move non-duplicate attractor modules that belong in pipeline/:
       annotate.py, status.py, generate.py, dashboard.py, init_promise.py,
       node_ops.py, edge_ops.py
    c. Update attractor/*.py imports: bare `from parser import ...` → `from cobuilder.pipeline.parser import ...`
    GATE: pytest cobuilder/pipeline/tests/ passes;
          pytest .claude/scripts/attractor/tests/ passes (via shims)

D-Order Step 5: Move attractor engine into cobuilder/attractor/
    a. Create cobuilder/attractor/__init__.py, __main__.py
    b. Copy (then delete) Group A files
    c. Rename runner.py → session_runner.py
    d. Remove sys.path.insert bootstrapping from all moved files
    e. Update pyproject.toml: add `attractor` console script entry point
    f. Run full test suite
    g. Delete .claude/scripts/attractor/ after all tests pass
    GATE: `attractor --help` works; pytest cobuilder/ passes

D-Order Step 6: Runtime state migration (var/)
    a. Create var/cobuilder/ structure
    b. Update signal_protocol.py step 3 to var/cobuilder/signals/
    c. Update runner-state directory constant in session_runner.py
    d. Run migration script: move .claude/attractor/pipelines/ → var/cobuilder/pipelines/
    e. Add var/ to .gitignore
    f. Test with a dry-run pipeline: verify signals go to var/cobuilder/signals/
    GATE: `cobuilder pipeline run --dot-file var/cobuilder/pipelines/example.dot --dry-run` works;
          no files written under .claude/ during dry run

D-Order Step 7: CLI unification
    a. Extend cobuilder/cli.py pipeline subcommands to cover attractor CLI surface
    b. `attractor` entry point delegates to cobuilder.attractor.cli:main
    c. Verify all 14 attractor subcommands accessible via both `attractor X` and `cobuilder pipeline X`
    GATE: CLI compatibility test matrix passes
```

The key property of this ordering: **each step is independently revertible**. Steps 0-2 touch different files. Step 3 adds a new file (no breakage possible). Step 4 uses shims (backward compat preserved). Step 5 does a copy-then-delete (can revert by deleting copy). Steps 6-7 are additive.

---

## 6. Subsystem-Level Risk Assessment

### S2: Pipeline DOT Layer — Risk: MEDIUM

**Risk vector**: The `VALID_TRANSITIONS` divergence (D1). Any code that loads a DOT file with `accepted` nodes and uses the unpatched `cobuilder/pipeline/transition.py` will raise an error.

**Detection**: Add a smoke test before Step 0:
```bash
python -c "
from cobuilder.pipeline.transition import VALID_TRANSITIONS
assert 'accepted' in VALID_TRANSITIONS, 'D1 not yet resolved'
print('VALID_TRANSITIONS OK')
"
```

**Mitigation**: D-Order Step 0a resolves this before any other work. The change is a 4-line diff. High confidence, low effort.

**Rollback**: The transition change is self-contained. Rolling back is a 4-line diff reversal.

### S4a: Python Runner — Risk: HIGH

**Risk vector**: The import path surgery in D-Order Step 5 changes 20+ files simultaneously. Any missed import causes an `ImportError` at runtime, silently breaking pipelines.

**Detection**: After Step 5, run the import smoke test:
```bash
python -c "
from cobuilder.attractor.pipeline_runner import PipelineRunnerState, main
from cobuilder.attractor.guardian import main as guardian_main
from cobuilder.attractor.dispatch_worker import compute_sd_hash
print('All attractor imports OK')
"
```

**Mitigation**: Use Serena MCP `find_referencing_symbols` to find all import sites before making changes. The copy-then-delete strategy means the old imports continue to work until the copy is verified.

**Specific fragility**: The `sys.path.insert(0, _THIS_DIR)` bootstrap in each attractor file currently makes the module self-contained. After the move into a package, this bootstrap becomes harmful (it adds the wrong directory to sys.path). Every file must have these 3 lines removed:
```python
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
```

**Rollback**: The original `.claude/scripts/attractor/` directory is preserved until Step 5's gate test passes. If anything breaks, delete the `cobuilder/attractor/` copy and revert to the original location.

### S5: Worker Dispatch — Risk: LOW-MEDIUM

**Risk vector**: Extracting `dispatch_agent_sdk()` from the 1,669-line `pipeline_runner.py` into a standalone module requires preserving the async context correctly.

**Critical invariant to preserve** (Hindsight: CLAUDECODE Env Var pattern):
```python
env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
```
This unset must be in the extracted function. Missing it causes nested session conflicts that silently fail.

**Detection**: Add a dedicated test:
```python
def test_claudecode_unset_in_dispatch(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    captured_env = {}
    async def mock_query(prompt, options):
        captured_env.update(os.environ)
        return []
    # ... call dispatch_agent_sdk with mock ...
    assert "CLAUDECODE" not in captured_env
```

**Mitigation**: D-Order Step 3 is isolated (new file only). The original `pipeline_runner.py` is updated to import from the new module rather than deleted. Any regression is immediately visible in the existing test suite.

### S6: RepoMap — Risk: NONE

No changes to `cobuilder/repomap/`. The 149 modules are stable and have their own test suite.

### S7: Runtime State Migration — Risk: MEDIUM (for active pipelines)

**Risk vector**: Moving `.claude/attractor/pipelines/` to `var/cobuilder/pipelines/` while a pipeline is actively running. The runner holds open file handles to the DOT file and the runner-state directory. Moving files mid-run causes `FileNotFoundError`.

**Mitigation**: Step 6 includes a pre-migration check:
```python
# tools/preflight_state_migration.py
import json
from pathlib import Path

state_dir = Path(".claude/attractor/runner-state")
active = [f for f in state_dir.glob("*.json") if json.loads(f.read_text()).get("status") == "active"]
if active:
    print(f"BLOCKED: {len(active)} active runners. Wait for them to complete.")
    sys.exit(1)
print("OK: No active runners. Safe to migrate.")
```

**Rollback**: Signal paths fall back through the resolution order. If `var/cobuilder/signals/` is not found, the runner falls back to `.claude/attractor/signals/`. So even a partially-migrated state is recoverable by moving files back manually.

---

## 7. Interface Contract Stability Guarantees

The following interfaces are **stable** (will not change in phases 0-7 above):

1. `cobuilder/pipeline/parser.py`: `parse_dot()` and `parse_file()` signatures — callers in attractor, engine, and CLI all depend on these
2. `cobuilder/pipeline/signal_protocol.py`: `write_signal()` and `read_signals()` — the signal contract is the coordination backbone
3. `cobuilder/pipeline/transition.py`: `apply_transition()` and `VALID_TRANSITIONS` — after D1 resolution, this is frozen
4. `cobuilder/pipeline/checkpoint.py`: `save_checkpoint()` and `restore_checkpoint()` — format must not change without migration

The following are **internal** (may change during migration, callers are within the same subsystem):

1. `pipeline_runner.py` private methods (`_dispatch_node`, `_build_worker_prompt`, etc.) — these become public S5 functions in Step 3
2. `cobuilder/engine/` internal handler methods — no external callers
3. `cobuilder/repomap/` internal modules — no external callers outside `cobuilder/bridge.py`

---

## 8. Package Structure After Full Migration

```
cobuilder/
├── __init__.py          # Public: EngineRunner, PipelineRunnerState, pipeline/* imports
├── __main__.py          # python -m cobuilder entry point (EXISTS, keep)
├── cli.py               # Unified typer CLI
├── bridge.py            # RepoMap ↔ Pipeline adapter (UNCHANGED)
├── settings.py          # NEW: DEFAULT_STATE_ROOT, ensure_state_dirs()
│
├── attractor/           # NEW — production pipeline engine (from .claude/scripts/attractor/)
│   ├── __init__.py
│   ├── __main__.py      # python -m cobuilder.attractor
│   ├── pipeline_runner.py     # Pure-Python AgentSDK state machine
│   ├── guardian.py            # System 3 SDK agent (boundary: guardian dissolves per E7; retained for tmux orchestration)
│   ├── session_runner.py      # RENAMED from runner.py — SDK monitoring agent
│   ├── spawn_orchestrator.py  # Worktree + tmux session bootstrap
│   ├── run_research.py
│   ├── run_refine.py
│   ├── dispatch_worker.py     # Shim: imports from cobuilder.pipeline.dispatch
│   ├── merge_queue.py
│   ├── anti_gaming.py
│   ├── hook_manager.py
│   ├── identity_registry.py   # (also exists in cobuilder/orchestration/ — merge)
│   ├── runner_guardian.py
│   ├── gchat_adapter.py
│   ├── channel_bridge.py
│   ├── channel_adapter.py
│   ├── agents_cmd.py
│   ├── cli.py                 # 14-subcommand attractor CLI
│   └── tests/                 # 17 test files (2 deleted, 17 remain)
│
├── pipeline/            # DOT layer + generation (EXPANDED from current state)
│   ├── __init__.py
│   ├── parser.py              # CANONICAL (attractor version)
│   ├── transition.py          # CANONICAL (reconciled)
│   ├── validator.py           # CANONICAL (attractor version)
│   ├── checkpoint.py          # CANONICAL (attractor version)
│   ├── signal_protocol.py     # CANONICAL (updated resolution order)
│   ├── dispatch.py            # NEW — consolidated AgentSDK dispatch (S5)
│   ├── node_ops.py            # MOVED from attractor
│   ├── edge_ops.py            # MOVED from attractor
│   ├── annotate.py            # MOVED from attractor
│   ├── status.py              # MOVED from attractor
│   ├── generate.py            # MOVED from attractor (imports bridge.py)
│   ├── dashboard.py           # MOVED from attractor
│   ├── init_promise.py        # MOVED from attractor
│   ├── dot_context.py         # EXISTS in cobuilder/pipeline/
│   ├── sd_enricher.py         # EXISTS in cobuilder/pipeline/
│   ├── taskmaster_bridge.py   # EXISTS in cobuilder/pipeline/
│   ├── enrichers/
│   └── tests/
│
├── engine/              # Async engine with middleware (UNCHANGED internally)
│   └── ...
│
├── orchestration/       # Scoped down — only adapters remain
│   ├── __init__.py
│   └── adapters/
│       ├── base.py
│       ├── native_teams.py
│       └── stdout.py
│
└── repomap/             # ZeroRepo — UNCHANGED
    └── ...
```

**pyproject.toml additions**:
```toml
[project.scripts]
cobuilder = "cobuilder.__main__:main"
zerorepo = "cobuilder.repomap.cli.app:app"
attractor = "cobuilder.attractor.cli:main"   # NEW

[project.optional-dependencies]
attractor = [
    "watchdog>=4.0",
    "claude-code-sdk>=0.1",
    "pyyaml>=6.0",
]
```

---

## 9. Acceptance Criteria

Each D-Order Step has its own gate test (defined in Section 5). Overall completion criteria:

| Criterion | Verification |
|-----------|-------------|
| S2 has zero duplicate implementations | `grep -r "def parse_dot" cobuilder/ --include="*.py"` returns exactly one result |
| `accepted` state in VALID_TRANSITIONS | `python -c "from cobuilder.pipeline.transition import VALID_TRANSITIONS; assert 'accepted' in VALID_TRANSITIONS"` |
| `failed → pending` in VALID_TRANSITIONS | `python -c "from cobuilder.pipeline.transition import VALID_TRANSITIONS; assert 'pending' in VALID_TRANSITIONS['failed']"` |
| S5 dispatch module exists | `from cobuilder.pipeline.dispatch import dispatch_agent_sdk` succeeds |
| CLAUDECODE unset in dispatch | Unit test `test_claudecode_unset_in_dispatch` passes |
| `attractor` CLI entry point works | `attractor --help` prints help text |
| No runtime state in .claude/ after run | `ls .claude/attractor/signals/` is empty (or dir removed) after test pipeline run |
| `.claude/scripts/attractor/` removed | `test ! -d .claude/scripts/attractor/` exits 0 |
| `cobuilder/orchestration/pipeline_runner.py` removed | `test ! -f cobuilder/orchestration/pipeline_runner.py` exits 0 |
| Full test suite passes | `pytest cobuilder/ .claude/tests/ -q` exits 0 |
| No sys.path.insert in cobuilder/attractor/ | `grep -r "sys.path.insert" cobuilder/attractor/` returns nothing |

---

## 10. Handoff Summary for Orchestrator

**Recommended agent assignments per D-Order step**:

| Step | Agent | Why |
|------|-------|-----|
| 0: Transition reconciliation | `backend-solutions-engineer` | Python data structure edit + test authoring |
| 1: Dead code deletion | `backend-solutions-engineer` | File deletions + test updates |
| 2: Delete orchestration runner | `backend-solutions-engineer` | Import site surgery in engine/ |
| 3: Create dispatch.py | `backend-solutions-engineer` | New module extraction + unit tests — `tdd-test-engineer` for test coverage |
| 4: Deduplication via shims | `backend-solutions-engineer` with Serena MCP for import tracking |
| 5: Move attractor into package | `backend-solutions-engineer` — HIGH CARE step. Run tests after every 3-5 file moves, not all at once |
| 6: State migration | `backend-solutions-engineer` — run only when no active pipelines |
| 7: CLI unification | `backend-solutions-engineer` + `tdd-test-engineer` for CLI compat tests |

**Minimum viable outcome** (if full migration takes too long): Complete Steps 0-3 only. This resolves all three divergences, eliminates the LLM-based runner, creates the clean dispatch module, and leaves the system in a stable intermediate state where:
- `cobuilder/pipeline/` is the canonical module set
- `attractor/` scripts import from `cobuilder.pipeline.*`
- The AgentSDK dispatch is a tested, documented module
- No runtime state moves have occurred (lower risk, lower reward)

Steps 4-7 can then be completed in a subsequent initiative.

**Security action required immediately** (outside this SD): `private.pem` in the repo root is a live private key committed to version control. Rotate the key and rewrite git history with `git filter-repo --path private.pem --invert-paths` before any new PRs land on `main`.

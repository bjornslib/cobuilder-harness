---
title: "SD-HARNESS-UPGRADE-001 Epic 6: Dispatch Worker Enhancements (SDK Mode)"
status: complete
type: solution-design
last_verified: 2026-03-07T00:00:00.000Z
grade: authoritative
---
# SD-HARNESS-UPGRADE-001 Epic 6: Dispatch Worker Enhancements (SDK Mode)

## 1. Problem Statement

The E2E analysis (2026-03-06) identified three critical issues with worker dispatch:

1. **Issue 1 (CRITICAL)**: Workers inherit the full MCP server list, triggering interactive permission dialogs on the host. The beads MCP server caused 5+ wasted turns.
2. **Issue 2 (MEDIUM)**: Workers use incorrect Write/Edit tool parameter formats. Six turns wasted on retries. (Addressed by E7.1 — tool examples extracted to reference file.)
3. **Issue 3 (HIGH)**: Workers receive `solution_design: null` because `sd_path` is not wired from DOT node attributes to the worker prompt. Workers spend 10+ turns searching for non-existent files.

Additionally, the runner needs signal coordination and skill injection for E7.2.

## 2. Design

### 2.1 MCP Permission Bypass

Use `permission_mode="bypassPermissions"` in `ClaudeCodeOptions`:

```python
options = ClaudeCodeOptions(
    permission_mode="bypassPermissions",
    # ... other options
)
```

Workers KEEP access to MCP tools (they may need Perplexity for research, Context7 for docs, etc.) but skip interactive permission dialogs. This is the correct approach — removing MCP entirely (`mcp_servers={}`) was too aggressive.

### 2.2 SD Content Wiring

In `build_worker_initial_prompt()`:
```python
def build_worker_initial_prompt(node_state: dict, sd_content: str | None = None) -> str:
    sd_path = node_state.get("sd_path")
    if sd_path and not sd_content:
        sd_content = Path(sd_path).read_text()

    prompt = f"""
## Task: {node_state['label']}

## Solution Design
Read: {sd_path}

## Acceptance Criteria
{node_state.get('acceptance', 'No acceptance criteria specified.')}

## Directive
The SD describes the intended approach and the AC defines success criteria.
Use your judgment on implementation details.
"""
    return prompt
```

Note: E7.1 restructures this further — this fix ensures `sd_path` is wired at all.

### 2.3 Skill Injection

Read `skills_required` from agent definition (E4) and inject into initial prompt:

```python
def inject_skills(agent_def: dict) -> str:
    skills = agent_def.get("skills_required", [])
    if not skills:
        return ""
    lines = ["## Skills (load before implementation)"]
    for skill in skills:
        lines.append(f'Skill("{skill}")')
    return "\n".join(lines)
```

### 2.4 ATTRACTOR_SIGNAL_DIR Environment Variable

```python
env = os.environ.copy()
env["ATTRACTOR_SIGNAL_DIR"] = str(Path(dot_file).parent / "signals")
```

Workers write signal files to `$ATTRACTOR_SIGNAL_DIR/{node_id}.json`. The Python runner (E7.2) polls this same directory.

### 2.5 CONCERNS_FILE Environment Variable

```python
env["CONCERNS_FILE"] = str(Path(signal_dir) / "concerns.jsonl")
```

Workers append concerns during execution. The validation agent at `wait.system3` gates reads these during technical validation (dispatched by pipeline_runner.py).

### 2.6 SD Hash Verification

```python
import hashlib

def compute_sd_hash(sd_content: str) -> str:
    return hashlib.sha256(sd_content.encode()).hexdigest()[:16]

# In signal evidence
signal = {
    "node": node_id,
    "status": "success",
    "sd_hash": compute_sd_hash(sd_content),
    "sd_path": sd_path,
}
```

The `wait.system3` gate can verify the hash matches the expected frozen SD version.

### 2.7 AgentSDK Dispatch (All Modes)

All dispatch paths use `claude_code_sdk` (`_run_agent()`) with proper sub-agent types, skills, and instructions. No headless CLI (`claude -p`) or tmux dispatch. This aligns with the E7 architecture: `System 3 → pipeline_runner.py → Workers (AgentSDK)`.

The `wait.system3` gate dispatches a `validation-test-agent` (with `--mode=pipeline-gate` and `acceptance-test-runner` skill) as an AgentSDK worker. The validation agent writes a signal file with `result: pass|fail|requeue` — the runner applies the transition mechanically.

## 3. Files Changed

| File | Change |
| --- | --- |
| `dispatch_worker.py` | bypassPermissions, ATTRACTOR_SIGNAL_DIR, CONCERNS_FILE, skill injection, SD hash |
| `runner.py` | Pass `sd_path` to dispatch functions |

## 4. Testing

- Unit test: `ClaudeCodeOptions` includes `permission_mode="bypassPermissions"`
- Unit test: SD content resolved from `sd_path` attribute
- Unit test: skill invocations injected from agent definition
- Unit test: signal evidence includes `sd_hash`
- Unit test: ATTRACTOR_SIGNAL_DIR and CONCERNS_FILE set in worker environment
- E2E test: re-run simple-pipeline.dot — 0 permission dialogs, worker receives SD content

## 5. Acceptance Criteria

- AC-6.1: Workers run without MCP permission dialogs (`permission_mode="bypassPermissions"`)
- AC-6.2: Workers receive real SD content in their initial prompt (not null)
- AC-6.3: Skill invocations injected into worker initial prompt from `skills_required`
- AC-6.4: `ATTRACTOR_SIGNAL_DIR` env var set for worker subprocesses
- AC-6.5: Signal evidence includes `sd_hash` field (SHA256 of frozen SD content)

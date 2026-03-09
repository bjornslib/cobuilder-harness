---
title: "SD-HARNESS-UPGRADE-001: E4-E6 Post-Pipeline Gap Remediation"
status: complete
type: solution-design
last_verified: 2026-03-07
grade: authoritative
---

# SD: E4-E6 Gap Remediation

Post-pipeline independent verification of E4-E6 identified 8 gaps across validator.py (E5) and pipeline_runner.py (E6). This SD specifies exact fixes.

## 1. E5 Gaps: validator.py

### GAP-5.3: VALID_WORKER_TYPES incomplete

**File**: `.claude/scripts/attractor/validator.py:94-99`

**Problem**: `VALID_WORKER_TYPES` has 4 types. The agent registry (`.claude/agents/`) has 6+.

**Current**:
```python
VALID_WORKER_TYPES = {
    "frontend-dev-expert",
    "backend-solutions-engineer",
    "tdd-test-engineer",
    "solution-architect",
}
```

**Fix**: Add missing types:
```python
VALID_WORKER_TYPES = {
    "frontend-dev-expert",
    "backend-solutions-engineer",
    "tdd-test-engineer",
    "solution-architect",
    "solution-design-architect",
    "validation-test-agent",
    "ux-designer",
}
```

**Acceptance**: `cobuilder pipeline validate` accepts DOT files with any of the 7 worker types without error.

---

### GAP-5.4: `node_map` NameError in `_check_cluster_topology()`

**File**: `.claude/scripts/attractor/validator.py:582`

**Problem**: Line 582 references `node_map.get(pred, {}).get("handler")` but `node_map` is defined in `validate()` (line 143), not passed to `_check_cluster_topology()`.

**Fix**: Either (a) pass `node_map` as a parameter, or (b) build a local lookup inside `_check_cluster_topology()`.

Option (a) — minimal diff:
```python
def _check_cluster_topology(
    nodes: list[dict],
    edges: list[dict],
    adj: dict[str, list[str]],
    reverse_adj: dict[str, list[str]],
    issues: list[Issue],
    node_map: dict[str, dict],   # <-- ADD
) -> None:
```

And update the call site at line 482:
```python
_check_cluster_topology(nodes, edges, adj, reverse_adj, issues, node_map)
```

**Acceptance**: `python3 validator.py <any.dot>` no longer raises `NameError: name 'node_map' is not defined` when wait.human nodes exist.

---

### GAP-5.5: Missing V-15 (acceptance-test-writer topology rule)

**File**: `.claude/scripts/attractor/validator.py` — new rule needed

**Problem**: SD-E5 specifies Rule V-15: warn when a codergen cluster has no acceptance-test-writer node. Not implemented.

**Fix**: Add after the cluster topology check:
```python
# Rule V-15: acceptance-test-writer warning
for cg_node in codergen_nodes:
    predecessors_all = _bfs_reverse(cg_node, reverse_adj)
    has_at_writer = any(
        node_map.get(p, {}).get("handler") == "acceptance-test-writer"
        for p in predecessors_all
    )
    if not has_at_writer:
        issues.append(Issue(
            "warning", 15,
            f"codergen node '{cg_node}' has no upstream acceptance-test-writer node",
            cg_node,
        ))
```

**Note**: This is a WARNING, not an error — many valid pipelines omit AT writers (e.g., fix pipelines).

**Acceptance**: Validator emits warning for codergen nodes without upstream AT writer; no error on pipelines that lack AT writers.

---

### GAP-5.6: Missing V-16 (skills_required validation)

**File**: `.claude/scripts/attractor/validator.py` — new rule needed

**Problem**: SD-E5 specifies Rule V-16: warn when an agent's `skills_required` references a non-existent skill directory. Not implemented.

**Fix**: Add after worker_type validation:
```python
# Rule V-16: skills_required validation
import yaml
from pathlib import Path

for n in nodes:
    wt = n["attrs"].get("worker_type", "")
    if not wt:
        continue
    agent_path = Path(f".claude/agents/{wt}.md")
    if not agent_path.exists():
        continue  # Missing agent already caught by worker_type check
    try:
        content = agent_path.read_text()
        # Parse YAML frontmatter
        if content.startswith("---"):
            fm_end = content.index("---", 3)
            fm = yaml.safe_load(content[3:fm_end])
            for skill in fm.get("skills_required", []):
                skill_dir = Path(f".claude/skills/{skill}")
                if not skill_dir.exists():
                    issues.append(Issue(
                        "warning", 16,
                        f"Agent '{wt}' requires skill '{skill}' but .claude/skills/{skill}/ not found",
                        n["id"],
                    ))
    except Exception:
        pass  # Don't fail validation on agent file parse errors
```

**Acceptance**: Validator warns when a skill directory referenced in `skills_required` doesn't exist.

---

## 2. E6 Gaps: pipeline_runner.py SDK Dispatch

### GAP-6.1: Missing ATTRACTOR_SIGNAL_DIR env var

**File**: `.claude/scripts/attractor/pipeline_runner.py:786-797` (`_dispatch_via_sdk`)

**Problem**: SD-E6 AC-6.4 requires `ATTRACTOR_SIGNAL_DIR` env var set for worker subprocesses. The SDK dispatch builds `clean_env` from `os.environ` but never sets `ATTRACTOR_SIGNAL_DIR`.

**Fix**: Add to `clean_env` before passing to `ClaudeCodeOptions`:
```python
clean_env["ATTRACTOR_SIGNAL_DIR"] = str(self.signal_dir)
```

**Acceptance**: Worker subprocess has `ATTRACTOR_SIGNAL_DIR` in its environment pointing to the signal directory.

---

### GAP-6.2: No skill injection from agent definitions

**File**: `.claude/scripts/attractor/pipeline_runner.py:730-775` (`_dispatch_agent_sdk`)

**Problem**: SD-E6 AC-6.3 requires skill invocations injected into worker prompt from `skills_required`. `dispatch_worker.py` does this via `load_agent_definition()` but `pipeline_runner.py`'s SDK path doesn't call it.

**Fix**: In `_build_worker_prompt()` or `_dispatch_agent_sdk()`, load the agent definition and inject skill invocations:
```python
from dispatch_worker import load_agent_definition

agent_def = load_agent_definition(worker_type)
if agent_def and agent_def.get("skills_required"):
    skills_block = "\n".join(
        f'Skill("{s}")' for s in agent_def["skills_required"]
    )
    prompt += f"\n\n## Required Skills\nInvoke these skills before starting:\n{skills_block}\n"
```

**Acceptance**: Workers dispatched via SDK receive skill invocation instructions matching their agent definition's `skills_required`.

---

### GAP-6.3: No sd_hash in signal evidence

**File**: `.claude/scripts/attractor/pipeline_runner.py` (signal write paths)

**Problem**: SD-E6 AC-6.5 requires signal evidence to include `sd_hash` field (SHA256 of frozen SD content). The runner reads `sd_path` from the DOT node but never computes or includes the hash.

**Fix**: Use `compute_sd_hash()` from `dispatch_worker.py`:
```python
from dispatch_worker import compute_sd_hash

# In _write_node_signal or _dispatch_agent_sdk:
sd_path = node_attrs.get("sd_path", "")
sd_hash = compute_sd_hash(sd_path) if sd_path else ""
signal_data["sd_hash"] = sd_hash
```

**Acceptance**: Signal files written by the runner include `sd_hash` field with SHA256 of the SD file content.

---

## 3. Pipeline DOT for Gap Fixes

A new pipeline DOT will be created at `.claude/attractor/pipelines/PRD-HARNESS-UPGRADE-E4E6-GAPS.dot` with:

```
start -> impl_e5_gaps -> verify_e5_gaps -> impl_e6_gaps -> verify_e6_gaps -> finalize
```

- `impl_e5_gaps`: codergen worker fixes GAPs 5.3, 5.4, 5.5, 5.6 in validator.py
- `verify_e5_gaps`: tool node runs validator on a test DOT with all worker types + wait.human
- `impl_e6_gaps`: codergen worker fixes GAPs 6.1, 6.2, 6.3 in pipeline_runner.py
- `verify_e6_gaps`: tool node checks env var injection, skill loading, sd_hash in code

E6 depends on E5 because `pipeline_runner.py` imports from `dispatch_worker.py` (which E5 doesn't touch) but the validator fixes should land first so the pipeline itself validates cleanly.

## 4. Files Changed

| File | Changes |
|------|---------|
| `.claude/scripts/attractor/validator.py` | GAP-5.3 (worker types), GAP-5.4 (node_map param), GAP-5.5 (V-15 rule), GAP-5.6 (V-16 rule) |
| `.claude/scripts/attractor/pipeline_runner.py` | GAP-6.1 (ATTRACTOR_SIGNAL_DIR), GAP-6.2 (skill injection), GAP-6.3 (sd_hash) |

## 5. Testing

- Unit: Each gap fix has its own acceptance criterion above
- Integration: Run `cobuilder pipeline validate` on the E4-E6 pipeline DOT — should pass with no errors
- E2E: Run the gap-fix pipeline itself through `pipeline_runner.py` — validates the runner fixes itself

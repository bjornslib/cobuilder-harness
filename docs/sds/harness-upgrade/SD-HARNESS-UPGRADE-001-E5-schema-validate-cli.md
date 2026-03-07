---
title: "SD-HARNESS-UPGRADE-001 Epic 5: Attractor Schema + Validate CLI Extension"
status: active
type: solution-design
last_verified: 2026-03-07
grade: authoritative
---

# SD-HARNESS-UPGRADE-001 Epic 5: Attractor Schema + Validate CLI Extension

## 1. Problem Statement

`cobuilder pipeline validate` currently checks basic graph structure (single start, reachable nodes, valid edges) but does not enforce:
- The mandatory `wait.system3 -> wait.human` gate pair after codergen clusters
- `worker_type` values against a known registry
- Required attributes on specific handler types (e.g., `sd_path` on codergen)
- Epic-level clustering validation

The E2E analysis (Issue 3) showed workers receiving `solution_design: null` because `sd_path` was not a required attribute.

## 2. Design

### 2.1 New Schema Attributes

| Attribute | Type | Required On | Default | Description |
|-----------|------|-------------|---------|-------------|
| `sd_path` | path | codergen | (none — mandatory) | Path to Solution Design file |
| `solution_design_hash` | string | codergen (auto-set) | (computed) | SHA256 of frozen SD content at dispatch time |
| `epic_id` | string | all (recommended) | (none) | Epic identifier for cluster validation |
| `gate_type` | enum | wait.system3 | "e2e" | "unit", "e2e", or "contract" |
| `contract_ref` | path | wait.system3 (optional) | (none) | Path to PRD Contract |
| `summary_ref` | path | wait.system3, wait.human | (none — mandatory on these types) | Path for summary write/read |
| `worker_type` | enum | codergen (optional) | (none) | Agent type from registry |

### 2.2 New Validation Rules

Added to `cobuilder pipeline validate`:

**Rule V-10: sd_path required on codergen nodes**
```python
for node in pipeline.nodes_by_handler("codergen"):
    if not node.attrs.get("sd_path"):
        errors.append(f"{node.id}: codergen node missing required 'sd_path' attribute")
```

**Rule V-11: Epic-level E2E gate check**
```python
for epic_id in pipeline.unique_epic_ids():
    codergen_nodes = pipeline.nodes_by_epic(epic_id, handler="codergen")
    gate_nodes = pipeline.nodes_by_epic(epic_id, handler="wait.system3")
    human_nodes = pipeline.nodes_by_epic(epic_id, handler="wait.human")
    if codergen_nodes and not gate_nodes:
        errors.append(f"Epic {epic_id}: has codergen nodes but no wait.system3 gate")
    if gate_nodes and not human_nodes:
        errors.append(f"Epic {epic_id}: has wait.system3 gate but no wait.human review")
```

**Rule V-12: worker_type registry check**
```python
KNOWN_WORKER_TYPES = {
    "frontend-dev-expert", "backend-solutions-engineer", "tdd-test-engineer",
    "solution-architect", "validation-test-agent", "ux-designer"
}
for node in pipeline.nodes_with_attr("worker_type"):
    if node.attrs["worker_type"] not in KNOWN_WORKER_TYPES:
        errors.append(f"{node.id}: unknown worker_type '{node.attrs['worker_type']}'")
```

**Rule V-13: wait.human topology**
```python
for node in pipeline.nodes_by_handler("wait.human"):
    predecessors = pipeline.predecessors(node)
    valid_pred_handlers = {"wait.system3", "research"}
    if not any(p.handler in valid_pred_handlers for p in predecessors):
        errors.append(f"{node.id}: wait.human must follow wait.system3 or research")
```

**Rule V-14: summary_ref required on gate nodes**
```python
for node in pipeline.nodes_by_handler("wait.system3", "wait.human"):
    if not node.attrs.get("summary_ref"):
        errors.append(f"{node.id}: gate node missing required 'summary_ref' attribute")
```

**Rule V-15: acceptance-test-writer at start of codergen cluster**
```python
for epic_id in pipeline.unique_epic_ids():
    codergen_nodes = pipeline.nodes_by_epic(epic_id, handler="codergen")
    at_writer_nodes = pipeline.nodes_by_epic(epic_id, handler="acceptance-test-writer")
    if codergen_nodes and not at_writer_nodes:
        warnings.append(f"Epic {epic_id}: has codergen but no acceptance-test-writer node")
```

**Rule V-16: skills_required references valid skill directories**
```python
for node in pipeline.nodes_with_attr("worker_type"):
    agent_path = Path(f".claude/agents/{node.attrs['worker_type']}.md")
    if agent_path.exists():
        skills = parse_frontmatter(agent_path).get("skills_required", [])
        for skill in skills:
            skill_dir = Path(f".claude/skills/{skill}")
            if not skill_dir.exists():
                warnings.append(f"{node.id}: agent '{node.attrs['worker_type']}' requires skill '{skill}' but .claude/skills/{skill}/ not found")
```

### 2.3 Runner Mode Flag

`runner.py` gains `--mode=python` flag:
```bash
python3 runner.py --dot-file pipeline.dot --mode=python  # Use pipeline_runner.py
python3 runner.py --dot-file pipeline.dot --mode=sdk     # Use existing SDK runner
python3 runner.py --dot-file pipeline.dot --mode=llm     # Use existing LLM guardian (default, for now)
```

After E7 validation period, `--mode=python` becomes the default.

## 3. Files Changed

| File | Change |
|------|--------|
| `agent-schema.md` | New attributes table, handler definitions |
| `validator.py` (or `cobuilder/pipeline/validation/`) | Rules V-10 through V-14 |
| `runner.py` | `--mode` flag with python/sdk/llm options |
| Test files | Unit tests for each new validation rule |

## 4. Testing

- Unit test per validation rule (V-10 through V-16) with passing and failing DOT samples
- Integration test: `cobuilder pipeline validate` on existing pipelines — expect warnings for missing new attributes
- Backward compatibility: existing valid pipelines should not produce errors for optional new attributes

## 5. Acceptance Criteria

- AC-5.1: `sd_path` mandatory on codergen nodes; validate rejects nodes without it
- AC-5.2: Epic-level E2E gate check implemented (V-11) and tested
- AC-5.3: `worker_type` registry check (V-12) rejects unknown agent types
- AC-5.4: `wait.human` topology (V-13) enforced — must follow `wait.system3` or `research`
- AC-5.5: `--mode=python` flag accepted by runner.py (dispatch to E7.2's PipelineRunner)
- AC-5.6: Acceptance-test-writer topology rule (V-15) warns when codergen cluster lacks AT writer
- AC-5.7: Skills validation (V-16) warns when agent's `skills_required` references non-existent skill directory

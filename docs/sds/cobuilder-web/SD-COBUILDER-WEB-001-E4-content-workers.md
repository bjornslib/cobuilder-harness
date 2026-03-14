---
title: "SD-COBUILDER-WEB-001 Epic 4: AgentSDK Content Workers"
status: active
type: solution-design
last_verified: 2026-03-12
grade: authoritative
prd_ref: PRD-COBUILDER-WEB-001
epic: E4
---

# SD-COBUILDER-WEB-001 Epic 4: AgentSDK Content Workers

**PRD**: PRD-COBUILDER-WEB-001
**Epic**: E4 (Phase 3: Content Workers + Process Management)
**Date**: 2026-03-12

---

## 1. Problem Statement

The CoBuilder Web initiative lifecycle requires three categories of content-authoring work before implementation begins: PRD drafting, Solution Design authoring, and blind acceptance test generation. Today these are performed by the S3 Guardian or manually by the operator, introducing three concrete problems:

1. **Guardian scope creep**: The Guardian currently drives PRD creation, SD creation, AND validation. This violates the separation of concerns defined in PRD-COBUILDER-WEB-001 Section 5.2 where the Guardian should own only acceptance tests + monitoring + validation, not content creation.

2. **No output path enforcement**: When a worker writes a document, the destination path is embedded in the worker's LLM reasoning. LLMs hallucinate paths (wrong directory, wrong naming convention, relative when absolute is needed). The web server has no mechanism to verify that the worker actually produced the expected artifact at the expected location.

3. **Missing PRD-writer agent**: `solution-design-architect` and `acceptance-test-writer` preambles exist in the runner, but there is no `prd-writer` agent definition. The runner cannot dispatch a worker to draft PRDs from a brief.

This SD delivers three things: (a) a new `prd-writer` agent definition, (b) `output_path` support in the runner's prompt construction so workers are told exactly where to write, and (c) a post-completion output verification protocol that the web server uses to confirm file creation before transitioning nodes.

---

## 2. Technical Architecture

### 2.1 Dispatch Flow

The existing pipeline runner dispatches content workers identically to implementation workers. The `worker_type` DOT attribute selects the agent definition; the `handler` attribute selects the tool/MCP permission set. Content workers use `handler="codergen"` because they need Write/Edit tools to create documents.

```
Web Server                    Pipeline Runner                     AgentSDK Worker
    |                              |                                    |
    |  Creates DOT with:           |                                    |
    |    worker_type="prd-writer"  |                                    |
    |    output_path="docs/..."    |                                    |
    |    handler="codergen"        |                                    |
    |                              |                                    |
    |  Launches runner ---------> |                                    |
    |                              | _build_worker_prompt() injects:    |
    |                              |   - output_path as absolute path   |
    |                              |   - role preamble from agent .md   |
    |                              |   - signal protocol instructions   |
    |                              |                                    |
    |                              | _dispatch_via_sdk() ------------> |
    |                              |                                    | Reads system_prompt
    |                              |                                    | from prd-writer.md
    |                              |                                    |
    |                              |                                    | Writes PRD to
    |                              |                                    | output_path using
    |                              |                                    | Write() tool
    |                              |                                    |
    |                              |                                    | Writes signal file
    |                              | <-- signal: success/failed ------  |
    |                              |                                    |
    |                              | Reads signal, checks output_path   |
    |                              | exists on disk                     |
    |                              |                                    |
    |                              | If file exists:                    |
    |                              |   transition -> impl_complete      |
    |                              | If file MISSING:                   |
    |                              |   transition -> failed             |
    |                              |   reason: "output file not created"|
    |                              |                                    |
    | <-- SSE event: node status   |                                    |
```

### 2.2 Agent Definition Structure

Agent definitions live at `.claude/agents/{worker_type}.md`. The frontmatter provides metadata; the body provides the system prompt. The runner loads both via `_build_system_prompt(worker_type)`, which:

1. Reads `worker-tool-reference.md` (tool usage guide, always prepended)
2. Reads `{worker_type}.md` (role-specific instructions)
3. Strips YAML frontmatter from both
4. Concatenates: tool reference + separator + role prompt

```python
# From pipeline_runner.py _build_system_prompt():
system_prompt = f"{tool_ref}\n\n---\n\n{role_content}"
```

The task prompt (per-node) is built by `_build_worker_prompt()` and includes the node's `output_path`, acceptance criteria, solution design content, and signal protocol instructions.

### 2.3 Key Design Decision: output_path in Prompt, Not Tool Restriction

The worker is TOLD the output path via the task prompt. We do NOT attempt to intercept Write() calls or restrict Write() to a specific path. Reasons:

- The SDK `allowed_tools` mechanism is a flat allow/deny list with no path-scoping capability
- Workers may need to Write() the signal file (different path) in addition to the output file
- Post-completion verification is a cheaper, more reliable check than pre-emption

The output_path is injected as an absolute path in the prompt. The worker is instructed to use it verbatim.

---

## 3. Agent Definitions

### 3.1 New Agent: `prd-writer`

**File**: `.claude/agents/prd-writer.md`

```markdown
---
name: prd-writer
description: >
  Use this agent to draft Product Requirement Documents (PRDs) from an initiative
  brief. Writes a structured PRD following the project template to the output_path
  specified in the task prompt. Does NOT create Solution Designs, acceptance tests,
  or implementation code.
model: sonnet
color: blue
title: "PRD Writer"
status: active
skills_required: []
---

You are a PRD Writer. Your sole job is to produce a complete, actionable Product
Requirement Document at the exact file path given in the task prompt.

## Output Rules

1. **Write to the EXACT output_path** specified in the task prompt. Do NOT choose
   your own path. Do NOT write to a different directory.
2. Use `Write(file_path="<output_path>")` since this is a NEW file.
3. If the parent directory does not exist, create it first:
   `Bash(command="mkdir -p <parent_dir>", description="Create output directory")`

## PRD Template

Every PRD you produce MUST include these sections in order:

```yaml
---
prd_id: <PRD_ID from task>
title: "<Initiative Title>"
status: draft
created: <today's date YYYY-MM-DD>
last_verified: <today's date YYYY-MM-DD>
grade: draft
---
```

### Required Sections

1. **Executive Summary** (2-3 paragraphs)
   - What problem does this solve?
   - What is the proposed solution at a high level?
   - Why now?

2. **Problem Statement**
   - Numbered problems (P1, P2, ...) with concrete impact descriptions
   - Each problem should be independently verifiable

3. **Goals & Success Criteria**
   - Table format: ID | Goal | Success Metric
   - Goals must be measurable (not aspirational)

4. **User Stories**
   - Format: "As a [role], I want to [action] so that [outcome]"
   - 3-8 user stories covering the core workflow

5. **Architecture** (high-level only)
   - Component diagram (text-based)
   - Separation of concerns table
   - Key technical decisions with rationale

6. **Technical Decisions**
   - TD-N format with Decision, Rationale, Trade-off subsections
   - At least 3 key decisions

7. **Epics**
   - Phased breakdown (Phase 1: Foundation, Phase 2: Core, etc.)
   - Each epic: scope bullet list + acceptance criteria checklist
   - Explicit dependencies between epics

8. **Risks & Mitigations**
   - Table format: Risk | Likelihood | Impact | Mitigation

9. **Non-Goals** (explicit exclusions)

## Research Protocol

Before writing, investigate the codebase to understand conventions:

1. Read 1-2 existing PRDs from `docs/prds/` to match the project's style
2. Use Grep/Glob to understand the project structure relevant to the initiative
3. If the initiative brief references specific technologies, verify current patterns
   in the codebase

## Quality Checklist (Self-Verify Before Signal)

Before writing your completion signal, verify:
- [ ] File exists at the exact output_path
- [ ] Frontmatter includes prd_id, title, status
- [ ] All 9 required sections are present
- [ ] Acceptance criteria are checkboxes (not prose)
- [ ] Epics have explicit scope and acceptance criteria
- [ ] No placeholder text like "TBD" or "TODO"
```

### 3.2 Existing Agent: `solution-design-architect`

**File**: `.claude/agents/solution-design-architect.md` (already exists)

**Verification Checklist** (what must be confirmed before E4 closes):

| Check | Status | Notes |
|-------|--------|-------|
| Agent file exists at `.claude/agents/solution-design-architect.md` | Exists | Verified in codebase |
| Frontmatter has `name: solution-design-architect` | Present | Line 2 |
| `model: sonnet` specified | Present | Line 4 |
| `skills_required: [research-first]` | Present | Line 8 |
| Body instructs research-first + Hindsight reflect | Present | Steps 1-2 in Mandatory Startup Sequence |
| Output Location section says `docs/prds/SD-*.md` | Present but NEEDS UPDATE | Currently writes to `docs/prds/`; content workers need to honor `output_path` from task prompt instead |

**Required Change**: The `solution-design-architect` agent body says "Save all documents to `docs/prds/`". When dispatched by the runner with an `output_path` attribute, the agent must write to the specified path instead. Add an override clause:

```
## Output Path Override

If the task prompt specifies an `output_path`, write to THAT path instead of the
default `docs/prds/` location. The web server controls file placement; respect its
path assignment.
```

### 3.3 Existing Preamble: `acceptance-test-writer`

**Runner preamble**: Already defined in `PipelineRunner.HANDLER_PREAMBLES["acceptance-test-writer"]` (line 2103 of `pipeline_runner.py`).

**No agent definition file exists**. The runner falls back to the generic prompt: "You are a specialist agent (acceptance-test-writer). Implement features directly using the provided tools."

**Required**: Either create `.claude/agents/acceptance-test-writer.md` with blind Gherkin test writing instructions, OR verify that the existing preamble + generic fallback produces acceptable output. The preamble currently says:

> You create Gherkin acceptance test scenarios from PRD acceptance criteria. Write .feature files with Given/When/Then. Tests should be blind (not peek at implementation).

This is sufficient for the content worker role. The worker does not need `output_path` because acceptance tests write to `acceptance-tests/{prd_ref}/` by convention (the PRD ref is already in the task prompt). No change needed for E4.

---

## 4. Output Verification Protocol

### 4.1 When Verification Runs

Output verification runs in the runner AFTER a worker's signal file is read and BEFORE the node transitions to `impl_complete`. It applies only to nodes that have an `output_path` attribute.

### 4.2 Verification Logic

```python
# Pseudocode — to be added to PipelineRunner._process_signal()

def _verify_output_path(self, node_id: str, node_attrs: dict, signal: dict) -> tuple[bool, str]:
    """Verify that a content worker produced its expected output file.

    Args:
        node_id: The pipeline node identifier.
        node_attrs: DOT node attributes dict.
        signal: Parsed signal file contents.

    Returns:
        (passed, reason) tuple. passed=True if file exists or no output_path
        attribute is defined. reason is empty on success, descriptive on failure.
    """
    output_path = node_attrs.get("output_path", "")
    if not output_path:
        # No output_path attribute — skip verification (normal codergen node)
        return True, ""

    # Resolve relative paths against repo root (output_path in DOT is relative)
    if not os.path.isabs(output_path):
        repo_root = self._get_repo_root()
        abs_output = os.path.join(repo_root, output_path)
    else:
        abs_output = output_path

    # Also check target_dir (worktree) if different from repo root
    target_dir = self._get_target_dir()
    alt_output = os.path.join(target_dir, output_path) if not os.path.isabs(output_path) else ""

    if os.path.exists(abs_output):
        return True, ""
    if alt_output and os.path.exists(alt_output):
        return True, ""

    # File not found at any candidate location
    return False, (
        f"Output file not created by worker. "
        f"Expected at: {abs_output}"
        f"{f' or {alt_output}' if alt_output else ''}. "
        f"Worker signal reported: {signal.get('status', 'unknown')}. "
        f"Worker message: {signal.get('message', '(none)')[:200]}"
    )
```

### 4.3 Integration Point in `_process_signal()`

The existing `_process_signal()` method reads the signal file and transitions the node. The output verification inserts between signal read and transition:

```python
# Current flow:
#   1. Read signal file
#   2. If status == "success": transition node to impl_complete
#   3. If status == "failed": transition node to failed

# New flow:
#   1. Read signal file
#   2. If status == "success":
#      a. Run _verify_output_path(node_id, node_attrs, signal)
#      b. If verification passed: transition node to impl_complete
#      c. If verification FAILED: transition node to failed with verification reason
#   3. If status == "failed": transition node to failed (unchanged)
```

### 4.4 Failure Handling

When output verification fails, the runner:

1. Transitions the node to `failed` with a descriptive reason
2. Writes the failure reason to `{signal_dir}/{node_id}.verification.json` for debugging
3. The web server detects the `failed` status via DOT file re-read or SSE event
4. The web server can offer "Retry" (re-queue the node to `pending`) or "Skip" (advance past the node)

The runner does NOT automatically retry content workers. The failure might indicate a systemic issue (wrong template, missing directory permissions) that would produce the same result on retry.

### 4.5 output_path in Worker Prompt

The `_build_worker_prompt()` method must inject `output_path` into the task prompt so the worker knows where to write. Add this to the prompt construction:

```python
# In _build_worker_prompt(), after the acceptance criteria block:

output_path = attrs.get("output_path", "")
if output_path:
    # Resolve to absolute path for the worker
    if not os.path.isabs(output_path):
        abs_output = os.path.join(self._get_target_dir(), output_path)
    else:
        abs_output = output_path
    lines.append(
        f"\n## Output Path — MANDATORY\n"
        f"You MUST write your output to this EXACT path:\n"
        f"```\n{abs_output}\n```\n"
        f"Create parent directories if they don't exist:\n"
        f'```\nBash(command="mkdir -p {os.path.dirname(abs_output)}", '
        f'description="Create output directory")\n```\n'
        f"Then write the document:\n"
        f'```\nWrite(file_path="{abs_output}", content="<your document>")\n```\n'
        f"Do NOT write to any other path. The web server will verify this file exists."
    )
```

---

## 5. Files Changed

### New Files

| File | Purpose |
|------|---------|
| `.claude/agents/prd-writer.md` | PRD writer agent definition (system prompt + frontmatter) |

### Modified Files

| File | Change | Scope |
|------|--------|-------|
| `cobuilder/attractor/pipeline_runner.py` | Add `output_path` injection to `_build_worker_prompt()` | ~15 lines in prompt construction |
| `cobuilder/attractor/pipeline_runner.py` | Add `_verify_output_path()` method | ~30 lines new method |
| `cobuilder/attractor/pipeline_runner.py` | Call `_verify_output_path()` in signal processing flow | ~10 lines in `_process_signal()` |
| `.claude/agents/solution-design-architect.md` | Add "Output Path Override" section | ~5 lines appended to existing body |

### Unchanged Files (Confirmed Working)

| File | Reason No Change Needed |
|------|------------------------|
| `.claude/agents/worker-tool-reference.md` | Already documents Write/Edit/Read tools; content workers use the same tool set |
| `cobuilder/attractor/dispatch_worker.py` | `load_agent_definition()` already parses any agent `.md` file by `worker_type` name |
| `cobuilder/attractor/signal_protocol.py` | Signal format unchanged; content workers use the same `{status, files_changed, message}` schema |
| `cobuilder/attractor/parser.py` | DOT parser already extracts arbitrary node attributes including `output_path` |
| `cobuilder/attractor/transition.py` | Transition rules (`pending->active->impl_complete->validated`) unchanged |

---

## 6. Implementation Priority

| Priority | Task | Rationale |
|----------|------|-----------|
| P0 | Create `.claude/agents/prd-writer.md` | Blocking: no PRD writing possible without this agent definition |
| P0 | Add `output_path` injection to `_build_worker_prompt()` | Blocking: workers won't know where to write without this |
| P1 | Add `_verify_output_path()` method to `PipelineRunner` | Safety net: catches output failures before web server proceeds |
| P1 | Wire verification into `_process_signal()` | Integration of P1 verification into existing flow |
| P2 | Update `solution-design-architect.md` with output path override | Defensive: current behavior writes to `docs/prds/` which conflicts with `docs/sds/` output_path values |
| P3 | Manual verification: dispatch `acceptance-test-writer` with PRD ref, confirm Gherkin output | Confidence check; no code change expected |

---

## 7. Acceptance Criteria

### AC-1: PRD Writer Agent Produces Valid PRD

- [ ] `.claude/agents/prd-writer.md` exists with valid frontmatter (`name: prd-writer`, `model: sonnet`, `status: active`)
- [ ] Runner dispatches `prd-writer` worker when DOT node has `worker_type="prd-writer"`
- [ ] Worker writes PRD file to the exact `output_path` specified in the DOT node
- [ ] PRD content includes all 9 required sections (Executive Summary through Non-Goals)
- [ ] PRD frontmatter includes `prd_id`, `title`, `status` fields

### AC-2: Solution Design Architect Honors output_path

- [ ] `solution-design-architect.md` body includes output path override clause
- [ ] When dispatched with `output_path="docs/sds/foo/SD-FOO-001.md"`, worker writes to that path (not `docs/prds/`)
- [ ] Existing behavior (no `output_path` attribute) still writes to `docs/prds/` default

### AC-3: Output Verification Catches Missing Files

- [ ] Runner calls `_verify_output_path()` after signal read for nodes with `output_path` attribute
- [ ] Node transitions to `impl_complete` when output file exists at expected path
- [ ] Node transitions to `failed` with descriptive reason when output file is missing
- [ ] Nodes WITHOUT `output_path` attribute skip verification (backward compatible)
- [ ] Verification checks both repo root and target_dir (worktree) as candidate paths

### AC-4: output_path Injected Into Worker Prompt

- [ ] `_build_worker_prompt()` includes `## Output Path` section when node has `output_path` attribute
- [ ] Output path is resolved to absolute path before injection
- [ ] Prompt includes `mkdir -p` instruction for parent directory creation
- [ ] Prompt includes explicit `Write(file_path="...")` example with the resolved path

### AC-5: Acceptance Test Writer Dispatches Successfully

- [ ] Runner dispatches `acceptance-test-writer` for nodes with that `worker_type`
- [ ] Worker produces `.feature` files in `acceptance-tests/{prd_ref}/` directory
- [ ] No `output_path` verification needed (convention-based output, not web-server-specified)

---

## 8. Risks

### R1: LLM Writes to Wrong Path (Likelihood: Medium, Impact: Medium)

**Description**: Despite being told the exact output_path, the LLM ignores the instruction and writes to a different location (e.g., the default `docs/prds/` path baked into the agent definition, or a path it constructs from the PRD ID).

**Mitigation**:
- Output verification protocol catches this at the runner level (Section 4)
- The prompt repeats the path three times: once in the `## Output Path` section, once in the `mkdir -p` example, once in the `Write()` example
- The `prd-writer` agent definition explicitly states "Do NOT choose your own path"
- `solution-design-architect` gets an override clause that says "If output_path is specified, use it instead of default"

**Residual risk**: If the worker writes to a wrong path AND writes a success signal, the verification catches it. If the worker writes to the correct path but with wrong content, that is not caught by file-existence checks (content quality is a separate concern for the Guardian/validation agent).

### R2: Content Quality Drift (Likelihood: Medium, Impact: Low)

**Description**: The LLM produces a PRD that technically follows the template structure but contains shallow, generic content that doesn't address the actual initiative requirements.

**Mitigation**:
- The PRD goes through a `wait.human` review gate immediately after creation (Section 5.1 of PRD)
- The prd-writer agent instructs research of existing PRDs for style matching
- Sonnet model (not Haiku) used for content workers to ensure reasoning depth
- The human reviewer can Reject, which requeues the writer with guidance

**Residual risk**: Acceptable. Human review is the designed quality gate for content artifacts.

### R3: Template Drift Between Agent Definition and Project Conventions (Likelihood: Low, Impact: Medium)

**Description**: The PRD template hardcoded in `prd-writer.md` diverges from the template used in existing PRDs as the project evolves. New PRDs follow the agent's template while old PRDs follow a different structure.

**Mitigation**:
- The agent instructions say "Read 1-2 existing PRDs from `docs/prds/` to match the project's style" as a mandatory research step
- The template in the agent definition is a MINIMUM structure, not a rigid format
- Agent definition files are version-controlled and reviewed alongside PRD convention changes

### R4: Directory Creation Race with Worktree (Likelihood: Low, Impact: Low)

**Description**: The worker tries to `mkdir -p` the output directory before the worktree has been fully initialized, resulting in the directory being created in the main checkout instead of the worktree.

**Mitigation**:
- `_build_worker_prompt()` resolves `output_path` against `self._get_target_dir()`, which returns the worktree path (from DOT graph `worktree_path` attribute)
- The worktree is created by Epic 0 (WorktreeManager) before the runner starts dispatching
- The worker's `cwd` is set to the worktree via `ClaudeCodeOptions(cwd=self._get_target_dir())`
- Even if the worker uses a relative path accidentally, `cwd` ensures it lands in the worktree

### R5: Concurrent Content Workers Clobber Each Other (Likelihood: Low, Impact: Low)

**Description**: Two SD writer nodes are dispatched in parallel (e.g., `write_sd_backend` and `write_sd_frontend`) and both try to create directories or write files that conflict.

**Mitigation**:
- Each SD writer has a unique `output_path` (different file names, potentially different directories)
- `mkdir -p` is idempotent (safe for parallel invocation on shared parent directories)
- Workers operate in the same worktree but write to different files
- The runner's `ThreadPoolExecutor` handles parallel dispatch; file writes are to distinct paths

---

## 9. DOT Node Examples

### PRD Writer Node

```dot
write_prd [
    shape=box
    handler="codergen"
    worker_type="prd-writer"
    label="Write PRD"
    output_path="docs/prds/dashboard-audit-trail/PRD-DASHBOARD-AUDIT-001.md"
    status="pending"
];
```

### SD Writer Node

```dot
write_sd_backend [
    shape=box
    handler="codergen"
    worker_type="solution-design-architect"
    label="Write SD: Backend"
    prd_ref="docs/prds/dashboard-audit-trail/PRD-DASHBOARD-AUDIT-001.md"
    output_path="docs/sds/dashboard-audit-trail/SD-DASHBOARD-AUDIT-001.md"
    epic="E1"
    status="pending"
];
```

### Acceptance Test Writer Node

```dot
write_tests [
    shape=box
    handler="codergen"
    worker_type="acceptance-test-writer"
    label="Write Blind Acceptance Tests"
    prd_ref="PRD-DASHBOARD-AUDIT-001"
    status="pending"
];
```

Note: `write_tests` has no `output_path` attribute because acceptance tests follow the convention `acceptance-tests/{prd_ref}/` and the writer determines the filenames.

---

## 10. ClaudeCodeOptions Configuration

Content workers use the standard `codergen` handler tools. No handler-specific tool additions are needed.

```python
# Effective ClaudeCodeOptions for a prd-writer dispatch:
options = claude_code_sdk.ClaudeCodeOptions(
    system_prompt=self._build_system_prompt("prd-writer"),
    # system_prompt = worker-tool-reference.md + prd-writer.md (frontmatter stripped)
    allowed_tools=[
        # Base tools (all handlers)
        "Bash", "Read", "Write", "Edit", "Glob", "Grep", "MultiEdit",
        "TodoWrite", "WebFetch", "WebSearch",
        "ToolSearch",  # Loads deferred MCP tool schemas
        "Skill",       # Native skill invocation
        "LSP",         # Type info, definitions
        # Serena tools (codergen handler default)
        "mcp__serena__activate_project",
        "mcp__serena__check_onboarding_performed",
        "mcp__serena__find_symbol",
        "mcp__serena__find_referencing_symbols",
        "mcp__serena__get_symbols_overview",
        "mcp__serena__search_for_pattern",
        "mcp__serena__replace_symbol_body",
        "mcp__serena__insert_after_symbol",
        "mcp__serena__insert_before_symbol",
        "mcp__serena__rename_symbol",
        "mcp__serena__list_dir",
        "mcp__serena__find_file",
        # Hindsight tools (codergen handler default)
        "mcp__hindsight__recall",
        "mcp__hindsight__retain",
        "mcp__hindsight__reflect",
    ],
    permission_mode="bypassPermissions",
    model="claude-sonnet-4-5-20251001",  # Content workers use Sonnet for quality
    cwd="/path/to/worktree",             # Set by _get_target_dir() from DOT worktree_path
    env={
        # Clean env without CLAUDECODE (prevents nested session detection)
        "ATTRACTOR_SIGNAL_DIR": "/path/to/signals/",
        # ... inherited env minus CLAUDECODE
    },
)
```

**Model note**: Content workers SHOULD use Sonnet (not Haiku). PRD/SD authoring requires synthesis and judgment that Haiku cannot reliably deliver. The worker model is controlled by `ANTHROPIC_MODEL` env var or `PIPELINE_WORKER_MODEL`, defaulting to Haiku. For E4, either:
- Set `PIPELINE_WORKER_MODEL=claude-sonnet-4-5-20251001` for the runner process, OR
- Add a `model` attribute to DOT nodes and have the runner read it (future enhancement, not in E4 scope)

The agent definition frontmatter specifies `model: sonnet`, but the runner currently ignores frontmatter model preferences and uses the environment variable. This is a known gap; for E4, the environment variable approach is sufficient.

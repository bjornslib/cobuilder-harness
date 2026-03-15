---
title: "SD-HARNESS-UPGRADE-001 Epic 4: Sub-Agent Registry + Skill Injection"
status: archived
type: reference
last_verified: 2026-03-07
grade: authoritative
---
# SD-HARNESS-UPGRADE-001 Epic 4: Sub-Agent Registry + Skill Injection

## 1. Problem Statement

The DOT pipeline schema supports a `worker_type` attribute on codergen nodes, but:
- Only 3 of 6 agent types have `.claude/agents/*.md` definition files
- `dispatch_worker.py` doesn't load agent definitions based on `worker_type`
- `cobuilder pipeline validate` doesn't check if `worker_type` values correspond to real agent definitions
- **Most critically**: the rich `.claude/skills/` library is not injected into worker prompts. Workers operate without domain-specific skills like `react-best-practices`, `research-first`, or `acceptance-test-writer`

## 2. Design

### 2.1 Agent Registry

All agent types must have a definition file at `.claude/agents/{agent-type}.md`:

| Agent Type | File | Status |
| --- | --- | --- |
| `frontend-dev-expert` | `.claude/agents/frontend-dev-expert.md` | Exists |
| `backend-solutions-engineer` | `.claude/agents/backend-solutions-engineer.md` | Exists |
| `tdd-test-engineer` | `.claude/agents/tdd-test-engineer.md` | Exists |
| `solution-architect` | `.claude/agents/solution-architect.md` | Verify/Create |
| `validation-test-agent` | `.claude/agents/validation-test-agent.md` | Verify/Create |
| `ux-designer` | `.claude/agents/ux-designer.md` | Verify/Create |

### 2.2 Agent Definition Format with Skill Injection

Each `.claude/agents/{type}.md` follows a standard format with `skills_required`:

```markdown
---
agent_type: frontend-dev-expert
title: "Frontend Development Expert"
model: sonnet
skills_required: [react-best-practices, frontend-design]
tools_allowed: [Read, Write, Edit, Grep, Glob, Bash]
---

# Frontend Development Expert

## Role
You are a frontend implementation specialist...

## Capabilities
- React/Next.js component development
- State management (Zustand, Redux)
- CSS/Tailwind styling
- Performance optimization

## Skills Loading (MANDATORY FIRST ACTION)
Before any implementation, load your required skills:
- Skill("react-best-practices")
- Skill("frontend-design")
These provide current patterns and anti-patterns for your domain.

## Output Format
...
```

### 2.3 Skill Injection in Dispatch

`dispatch_worker.py` enhanced to:
1. Read `worker_type` from DOT node attributes
2. Resolve to `.claude/agents/{worker_type}.md`
3. Parse frontmatter to extract `skills_required`
4. Inject skill invocations into the worker's initial prompt:
```
   ## Skills (load before implementation)
   Skill("react-best-practices")
   Skill("frontend-design")
```
5. Inject agent definition content as system prompt
6. If agent file not found: raise `AgentDefinitionNotFoundError` (hard error)

### 2.4 Skill-to-Agent Mapping

| Agent Type | Skills Required | Rationale |
| --- | --- | --- |
| `frontend-dev-expert` | `react-best-practices`, `frontend-design` | Current React/Next.js patterns |
| `backend-solutions-engineer` | (domain-specific, e.g., `dspy-development`) | Backend framework guidance |
| `tdd-test-engineer` | `test-driven-development`, `acceptance-test-runner` | Testing methodology |
| `solution-architect` | `research-first` | Architecture research patterns |
| `validation-test-agent` | `acceptance-test-runner` | Technical validation at pipeline gates (--mode=pipeline-gate) and PRD E2E validation (--mode=e2e) |
| `ux-designer` | `website-ux-audit`, `website-ux-design-concepts`, `frontend-design` | UX patterns |

### 2.5 Schema Extension

`agent-schema.md` updated with `worker_type` enum:
```
worker_type: enum [
    "frontend-dev-expert",
    "backend-solutions-engineer",
    "tdd-test-engineer",
    "solution-architect",
    "validation-test-agent",
    "ux-designer"
]
```

## 3. Files Changed

| File | Change |
| --- | --- |
| `.claude/agents/solution-architect.md` | Verify exists, update to standard format with `skills_required` |
| `.claude/agents/validation-test-agent.md` | Verify exists, update to standard format with `skills_required` |
| `.claude/agents/ux-designer.md` | Verify exists, update to standard format with `skills_required` |
| `.claude/agents/frontend-dev-expert.md` | Add `skills_required` to frontmatter |
| `.claude/agents/backend-solutions-engineer.md` | Add `skills_required` to frontmatter |
| `.claude/agents/tdd-test-engineer.md` | Add `skills_required` to frontmatter |
| `agent-schema.md` | `worker_type` enum with all 6 values |
| `dispatch_worker.py` | Load agent definition, parse `skills_required`, inject Skill() into prompt |

## 4. Testing

- Unit test: `dispatch_worker.py` resolves each `worker_type` to the correct `.md` file
- Unit test: `skills_required` parsed from frontmatter correctly
- Unit test: missing `worker_type` file raises `AgentDefinitionNotFoundError`
- Unit test: skill invocations injected into initial prompt
- Integration test: SDK worker receives agent definition as system prompt + skill invocations in initial prompt
- Validation test: `cobuilder pipeline validate` rejects unknown `worker_type` values
- Validation test: `skills_required` references verified against `.claude/skills/` directory

## 5. Acceptance Criteria

- AC-4.1: All 6 agent types have `.claude/agents/*.md` definition files with `skills_required` in frontmatter
- AC-4.2: `agent-schema.md` `worker_type` enum includes all 6 types with descriptions
- AC-4.3: `dispatch_worker.py` loads agent definition and injects `Skill()` invocations from `skills_required`
- AC-4.4: Missing agent definition is a hard error (not silent fallback to generic prompt)

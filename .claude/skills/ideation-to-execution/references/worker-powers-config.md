---
title: "Worker Powers Configuration"
status: active
type: reference
---

# Configuring Superpowers for Pipeline Workers

When generating TDD pipeline DOT files, codergen nodes can be configured to grant workers access to superpowers skills. This reference documents how to set up worker powers in pipeline templates and DOT files.

---

## DOT Node Attributes for Powers

Add `worker_powers` attribute to codergen nodes to specify which superpowers the worker should load:

```dot
impl_feature_auth [
    shape=box
    label="Auth Feature\nTDD Implementation"
    handler="codergen"
    worker_type="backend-solutions-engineer"
    worker_powers="tdd,systematic-debugging,verification"
    status="pending"
];
```

### Available Power Sets

| Power Key | Skills Loaded | Use Case |
|-----------|--------------|----------|
| `tdd` | test-driven-development, verification-before-completion | Standard TDD implementation |
| `systematic-debugging` | systematic-debugging, root-cause-tracing | Troubleshooting failures |
| `verification` | verification-before-completion | Pre-completion validation |
| `brainstorming` | brainstorming | Unclear approach decisions |
| `all` | All worker superpowers | Full power mode |

---

## Worker Prompt Injection

When the pipeline runner dispatches a codergen worker, it reads `worker_powers` and appends skill invocation instructions to the worker prompt:

```
## Available Superpowers

Load these skills as needed during your work:

- Skill("worker-superpowers") — TDD workflow, systematic debugging, verification protocols
- When stuck on a bug: Skill("worker-superpowers") then follow systematic-debugging protocol
- Before marking complete: Skill("worker-superpowers") then follow verification-before-completion
- For TDD cycles: Follow the RED-GREEN-REFACTOR protocol from worker-superpowers skill
```

---

## TDD Pipeline Default Powers

The `tdd-validated` template automatically sets `worker_powers="tdd,systematic-debugging,verification"` on all codergen nodes. Workers in TDD pipelines always have access to:

1. **RED-GREEN-REFACTOR cycle** — Write failing test → implement → refactor
2. **Systematic debugging** — Root-cause analysis when tests fail unexpectedly
3. **Verification before completion** — Evidence-based completion checks

---

## Custom Power Configurations

For specialized workers, override the default power set:

```dot
// Frontend worker with brainstorming for UX decisions
impl_ui_dashboard [
    worker_type="frontend-dev-expert"
    worker_powers="tdd,brainstorming,verification"
];

// Backend worker with full debugging suite
impl_api_auth [
    worker_type="backend-solutions-engineer"
    worker_powers="all"
];
```

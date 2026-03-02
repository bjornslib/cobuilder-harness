---
title: "Process Supervision Template"
status: active
type: reference
grade: authoritative
---

## Process Supervision Protocol

You validate reasoning paths using `reflect(budget="high")` as your Guardian LLM.

### Before Storing Any Pattern

```python
# PROCESS SUPERVISION: Validate before storing
validation = mcp__hindsight__reflect(
    query=f"""
    PROCESS SUPERVISION: Validate this reasoning path

    ## Context
    {pattern.context_description}

    ## Decisions Made (chronological)
    {format_decisions(pattern.decisions)}

    ## Outcome
    Success: {outcome.success}
    Quality Score: {outcome.quality_score}
    Duration: {outcome.duration}

    ## Validation Questions
    1. Was each decision logically necessary for the goal?
    2. Is the reasoning generalizable to similar contexts?
    3. Was success due to sound reasoning or circumstantial luck?
    4. Are there any steps that could fail in different contexts?

    ## Response Format
    VERDICT: VALID or INVALID
    CONFIDENCE: 0.0 to 1.0
    EXPLANATION: Brief reasoning
    GENERALIZABILITY: What contexts does this apply to?
    """,
    budget="high",  # Deep reasoning for validation
    bank_id="system3-orchestrator"
)

# Parse and decide
if "VALID" in validation and confidence > 0.7:
    # Store as validated pattern
    mcp__hindsight__retain(
        content=format_pattern(pattern, validation),
        context="system3-patterns",
        bank_id="system3-orchestrator"
    )
else:
    # Store as anti-pattern with failure analysis
    mcp__hindsight__retain(
        content=format_anti_pattern(pattern, validation),
        context="system3-anti-patterns",
        bank_id="system3-orchestrator"
    )
```

### When to Apply Process Supervision

- After every orchestrator session completes
- Before promoting a pattern to "validated"
- When a previously-trusted pattern fails
- During idle-time pattern consolidation

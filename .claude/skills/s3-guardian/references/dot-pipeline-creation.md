---
title: "DOT Pipeline Creation Reference"
status: active
type: skill
last_verified: 2026-03-07
grade: authoritative
---

# DOT Pipeline Creation Reference

## Graph Structure Overview

DOT pipelines define the execution flow for orchestrator networks. Each pipeline consists of nodes connected by directed edges, where nodes represent tasks and edges represent dependencies/execution flow.

### Basic Graph Declaration

```dot
digraph PRD_HARNESS_UPGRADE_001 {
    // Global graph attributes
    rankdir=TB
    splines=ortho
    nodesep=1.0
    ranksep=1.5

    // Global node attributes
    node [shape=ellipse, style=filled, fillcolor=lightblue]

    // Global edge attributes
    edge [arrowhead=vee, color=gray]

    // Node definitions with attributes follow...
}
```

## Node Attributes by Handler Type

Each node must specify a `handler` attribute that determines how it executes. Here are all valid handler types with their required and optional attributes:

### `start` - Pipeline Entry Point

```dot
start_node [label="Start Pipeline"
          handler="start"
          shape=house
          fillcolor=green
          status=pending
          worker_type=start_worker
          prompt="Initialize pipeline execution"]
```

**Purpose**: Pipeline initialization and entry point
**Worker Type**: N/A (system handler)
**LLM Required**: No

### `codergen` - Code Implementation

```dot
implement_feature [label="Implement Feature"
                 handler="codergen"
                 shape=box
                 fillcolor=lightyellow
                 status=pending
                 worker_type=backend-solutions-engineer
                 llm=sonnet
                 file_path="src/main.py"
                 folder_path="src/"
                 prompt="Implement the core feature as specified in the SD"]
```

**Purpose**: Code generation and implementation tasks
**Worker Type**: Specified by `worker_type` attribute
**LLM Required**: Yes (specified by `llm` attribute)

### `research` - Framework/API Investigation

```dot
research_api [label="Research API"
            handler="research"
            shape=tab
            fillcolor=lightcyan
            status=pending
            worker_type=researcher
            llm=haiku
            prompt="Investigate latest patterns for framework X"]
```

**Purpose**: Pre-implementation research and validation
**Worker Type**: Haiku (cost-effective)
**LLM Required**: Yes

### `refine` - SD Rewriting with Findings

```dot
refine_sd [label="Refine Solution Design"
          handler="refine"
          shape=note
          fillcolor=lightgreen
          status=pending
          worker_type=refiner
          llm=sonnet
          prompt="Update SD with research findings"]
```

**Purpose**: Rewrite Solution Design with research findings
**Worker Type**: Sonnet (for quality refinement)
**LLM Required**: Yes

### `tool` - Shell Command Execution

```dot
run_tests [label="Run Tests"
         handler="tool"
         shape=invtriangle
         fillcolor=orange
         status=pending
         command="npm test"
         working_dir="./"
         timeout=300]
```

**Purpose**: Execute shell commands/tools
**Worker Type**: N/A (subprocess execution)
**LLM Required**: No

### `wait.system3` - Automated E2E Gate

```dot
e2e_gate [label="E2E Validation"
        handler="wait.system3"
        shape=doublecircle
        fillcolor=purple
        status=pending
        runner=python
        script="validate_e2e.py"
        timeout=3600]
```

**Purpose**: Automated validation gate (Python runner)
**Worker Type**: Python runner (subprocess)
**LLM Required**: No

### `wait.human` - Human Review Gate

```dot
human_review [label="Human Review"
            handler="wait.human"
            shape=hexagon
            fillcolor=red
            status=pending
            platform=gchat
            timeout=86400]
```

**Purpose**: Human approval/verification gate
**Worker Type**: N/A (external platform)
**LLM Required**: No

### `exit` - Pipeline Termination

```dot
pipeline_exit [label="Complete"
             handler="exit"
             shape=octagon
             fillcolor=darkgreen
             status=pending
             prompt="Pipeline completed successfully"]
```

**Purpose**: Pipeline termination point
**Worker Type**: N/A (system handler)
**LLM Required**: No

## Edge Labels and Flow Control

Edges connect nodes and determine execution flow:

```dot
// Sequential flow
start_node -> research_api [label="initiates"]

// Conditional flow
research_api -> refine_sd [label="success"]
research_api -> research_api_retry [label="retry"]

// Fan-out pattern
refine_sd -> task1 [label="branches"]
refine_sd -> task2 [label="branches"]

// Fan-in pattern
task1 -> merge_point [label="complete"]
task2 -> merge_point [label="complete"]
```

## Complete Minimal Example

```dot
digraph EXAMPLE_PIPELINE {
    rankdir=TB
    splines=ortho
    nodesep=1.0
    ranksep=1.5

    node [shape=ellipse, style=filled, fillcolor=lightblue]
    edge [arrowhead=vee, color=gray]

    // Pipeline structure
    start [label="Start Pipeline"
          handler="start"
          shape=house
          fillcolor=green
          status=pending]

    research [label="Research Framework"
             handler="research"
             shape=tab
             fillcolor=lightcyan
             status=pending
             worker_type=researcher
             llm=haiku
             prompt="Research best practices for React components"]

    refine [label="Refine Solution Design"
           handler="refine"
           shape=note
           fillcolor=lightgreen
           status=pending
           worker_type=refiner
           llm=sonnet
           prompt="Update SD with research findings"]

    implement [label="Implement Components"
              handler="codergen"
              shape=box
              fillcolor=lightyellow
              status=pending
              worker_type=frontend-dev-expert
              llm=sonnet
              file_path="src/components/"
              prompt="Implement React components per refined SD"]

    test [label="Run Tests"
         handler="tool"
         shape=invtriangle
         fillcolor=orange
         status=pending
         command="npm test"]

    validate [label="E2E Validation"
             handler="wait.system3"
             shape=doublecircle
             fillcolor=purple
             status=pending
             runner=python
             script="validate_components.py"]

    complete [label="Complete"
             handler="exit"
             shape=octagon
             fillcolor=darkgreen
             status=pending]

    // Execution flow
    start -> research [label="initiates"]
    research -> refine [label="success"]
    refine -> implement [label="ready"]
    implement -> test [label="built"]
    test -> validate [label="pass"]
    validate -> complete [label="validated"]
}
```

## Required vs Optional Node Attributes

### Required for All Nodes:
- `handler` - Specifies execution handler type
- `label` - Human-readable description
- `status` - Current execution status (pending, active, impl_complete, validated, failed)

### Handler-Specific Requirements:

| Handler | Required Attributes | Optional Attributes |
|---------|-------------------|-------------------|
| `start` | handler, label, status | worker_type, prompt |
| `codergen` | handler, label, status, worker_type, llm | file_path, folder_path, prompt |
| `research` | handler, label, status, worker_type, llm | prompt, file_path |
| `refine` | handler, label, status, worker_type, llm | prompt |
| `tool` | handler, label, status, command | working_dir, timeout |
| `wait.system3` | handler, label, status, runner, script | timeout |
| `wait.human` | handler, label, status, platform | timeout |
| `exit` | handler, label, status | prompt |

## Validation Checklist

Before running a DOT pipeline, verify:

1. **All nodes have required attributes**
2. **At least one `start` node exists**
3. **At least one `exit` node exists**
4. **All edges connect existing nodes**
5. **No circular dependencies exist**
6. **Node IDs are unique**
7. **Handler types are valid**

Use the validation command:
```bash
python .claude/scripts/attractor/cli.py validate --dot-file path/to/pipeline.dot
```

## Common Patterns

### Research→Refine→Codergen Chain
```dot
research -> refine [label="findings"]
refine -> implement [label="updated_sd"]
```

### Parallel Execution (Fan-out/fan-in)
```dot
split -> task_a [label="branch"]
split -> task_b [label="branch"]
task_a -> join [label="complete"]
task_b -> join [label="complete"]
```

### Retry Pattern
```dot
attempt -> success_handler [label="success"]
attempt -> attempt_retry [label="failure"]
attempt_retry -> success_handler [label="success"]
```

---

**Reference Version**: 1.0.0
**Parent Skill**: s3-guardian
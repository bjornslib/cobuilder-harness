---
title: "Solution Design: Template System and System 3 Meta-Pipeline"
status: draft
type: architecture
last_verified: 2026-03-12
grade: authoritative
---

# SD: Attractor Template System & System 3 Meta-Pipeline

**Author**: Solution Architect
**Date**: 2026-03-12
**Status**: Draft — awaiting review
**Scope**: Two interconnected capabilities:
1. Parameterized DOT templates with state transition constraints
2. Self-orchestrating System 3 lifecycle pipeline that spawns sub-pipelines

---

## Part 1: Attractor Template System

### 1.1 Problem Statement

Every pipeline is either hand-crafted DOT or generated from beads via `generate.py`. There is no reusable, parameterized topology library. This means:

- Repeated structural patterns (hub-spoke, sequential-with-retry, brainstorm-then-synthesize) are re-invented each time.
- The runner (`EngineRunner`) accepts any DOT file but has no way to enforce topology-level contracts — a template that says "this node MUST NOT transition directly to exit without passing through a validation gate" cannot be expressed.
- No way to say "give me a 3-worker parallel pipeline for PRD-X" without writing 200+ lines of DOT.

### 1.2 Design Goals

1. **Templates are DOT** — not a new language. Templates extend DOT with Jinja2-style parameter placeholders and a companion manifest that defines constraints.
2. **The runner enforces constraints** — state transition rules declared in the template are loaded at parse time and enforced during traversal.
3. **`generate.py` becomes a template instantiator** — existing generation logic migrates to populating templates rather than emitting raw DOT strings.
4. **Backward compatible** — any existing `.dot` file without a manifest runs exactly as today (no constraints enforced).

### 1.3 Template Format

A template is a **directory** (not a single file):

```
.pipelines/templates/
├── hub-spoke/
│   ├── template.dot.j2          # Jinja2-parameterized DOT
│   ├── manifest.yaml             # Parameters, constraints, metadata
│   └── README.md                 # Human description + example rendering
├── sequential-validated/
│   ├── template.dot.j2
│   ├── manifest.yaml
│   └── README.md
├── brainstorm-synthesize/
│   ├── template.dot.j2
│   ├── manifest.yaml
│   └── README.md
└── s3-lifecycle/                 # Part 2's template
    ├── template.dot.j2
    ├── manifest.yaml
    └── README.md
```

#### 1.3.1 `manifest.yaml` — Template Manifest

```yaml
# manifest.yaml for hub-spoke template
template:
  name: hub-spoke
  version: "1.0"
  description: "Central coordinator fans out to N parallel workers, joins, validates"
  topology: parallel          # linear | parallel | cyclic | meta
  min_nodes: 5                # Structural validation hint
  max_nodes: 50

# Parameters the user must supply at instantiation time
parameters:
  prd_ref:
    type: string
    required: true
    description: "PRD identifier (e.g., PRD-AUTH-001)"

  promise_id:
    type: string
    required: false
    default: ""

  workers:
    type: list
    required: true
    min_length: 1
    max_length: 10
    item_schema:
      type: object
      properties:
        label:
          type: string
          required: true
        worker_type:
          type: string
          required: true
          enum:
            - frontend-dev-expert
            - backend-solutions-engineer
            - tdd-test-engineer
            - solution-architect
        bead_id:
          type: string
          required: true
        acceptance:
          type: string
          required: true
        promise_ac:
          type: string
          required: false

  include_e2e:
    type: boolean
    default: true
    description: "Whether to append an E2E test node after the join gate"

# State transition constraints — the core new capability
constraints:
  # Global: every codergen node must pass through at least one validation gate
  # before reaching an exit node
  require_validation_before_exit:
    description: "No codergen node may reach exit without passing a validation gate"
    type: path_constraint
    rule:
      from_shape: box           # codergen nodes
      must_pass_through:
        - hexagon               # wait_human (validation gate)
      before_reaching:
        - Msquare               # exit node

  # Per-node: codergen nodes can only transition through these statuses
  codergen_transitions:
    description: "Allowed status transitions for implementation nodes"
    type: node_state_machine
    applies_to:
      shape: box
      handler: codergen
    states: [pending, active, impl_complete, validated, failed]
    transitions:
      - {from: pending,       to: active}
      - {from: active,        to: impl_complete}
      - {from: active,        to: failed}
      - {from: impl_complete, to: validated}
      - {from: impl_complete, to: failed}
      - {from: failed,        to: active}        # retry
    initial: pending
    terminal: [validated, failed]

  # Per-node: validation gates can only transition through these statuses
  validation_gate_transitions:
    description: "Allowed status transitions for validation gates"
    type: node_state_machine
    applies_to:
      shape: hexagon
      handler: wait_human
    states: [pending, active, passed, failed]
    transitions:
      - {from: pending, to: active}
      - {from: active,  to: passed}
      - {from: active,  to: failed}
      - {from: failed,  to: active}             # re-validate
    initial: pending
    terminal: [passed, failed]

  # Topology: parallel fan-out must have matching fan-in
  balanced_parallelism:
    description: "Every parallel fan-out must have a corresponding fan-in"
    type: topology_constraint
    rule:
      every_node:
        shape: component
        handler: parallel
      must_have_downstream:
        shape: tripleoctagon     # fan_in
        max_hops: 20

  # Loop safety: retry edges must have bounded visit counts
  bounded_retries:
    description: "Edges targeting already-visited nodes must be bounded"
    type: loop_constraint
    rule:
      max_per_node_visits: 4     # Overrides LoopPolicy.per_node_max
      max_pipeline_visits: 50
```

#### 1.3.2 `template.dot.j2` — Parameterized DOT

```dot
// Generated from template: hub-spoke v1.0
// PRD: {{ prd_ref }}

digraph "{{ prd_ref }}" {
    graph [
        label="Initiative: {{ prd_ref }}"
        labelloc="t"
        fontsize=16
        rankdir="TB"
        prd_ref="{{ prd_ref }}"
        promise_id="{{ promise_id }}"
        _template="hub-spoke"
        _template_version="1.0"
    ];

    node [fontname="Helvetica" fontsize=11];
    edge [fontname="Helvetica" fontsize=9];

    // STAGE 1: PARSE
    start [
        shape=Mdiamond
        label="PARSE\n{{ prd_ref }}"
        handler="start"
        status="pending"
        style=filled
        fillcolor=lightyellow
    ];

    // STAGE 2: VALIDATE
    validate_graph [
        shape=parallelogram
        label="Validate Graph"
        handler="tool"
        tool_command="attractor validate pipeline.dot"
        status="pending"
        style=filled
        fillcolor=lightyellow
    ];

    start -> validate_graph [label="parse complete"];

    // STAGE 3: INITIALIZE
    init_env [
        shape=parallelogram
        label="Initialize\nEnvironment"
        handler="tool"
        tool_command="launchorchestrator {{ prd_ref | slugify }}"
        status="pending"
        style=filled
        fillcolor=lightyellow
    ];

    validate_graph -> init_env [label="graph valid"];

    // STAGE 4: EXECUTE — Parallel fan-out
    {% if workers | length > 1 %}
    parallel_start [
        shape=component
        label="Parallel:\n{{ workers | length }} Workers"
        handler="parallel"
        status="pending"
        style=filled
        fillcolor=lightyellow
    ];

    init_env -> parallel_start [label="env ready"];
    {% endif %}

    {% for worker in workers %}
    // --- Worker {{ loop.index }}: {{ worker.label }} ---
    impl_{{ worker.bead_id | slugify }} [
        shape=box
        label="{{ worker.label }}"
        handler="codergen"
        bead_id="{{ worker.bead_id }}"
        worker_type="{{ worker.worker_type }}"
        acceptance="{{ worker.acceptance | truncate(120) }}"
        {% if worker.promise_ac %}promise_ac="{{ worker.promise_ac }}"{% endif %}
        prd_ref="{{ prd_ref }}"
        status="pending"
        style=filled
        fillcolor=lightyellow
    ];

    {% if workers | length > 1 %}
    parallel_start -> impl_{{ worker.bead_id | slugify }} [color=blue style=bold];
    {% else %}
    init_env -> impl_{{ worker.bead_id | slugify }} [label="env ready"];
    {% endif %}

    validate_{{ worker.bead_id | slugify }}_tech [
        shape=hexagon
        label="{{ worker.label }}\nTech Validation"
        handler="wait_human"
        gate="technical"
        mode="technical"
        bead_id="AT-{{ worker.bead_id }}-TECH"
        status="pending"
        style=filled
        fillcolor=lightyellow
    ];

    impl_{{ worker.bead_id | slugify }} -> validate_{{ worker.bead_id | slugify }}_tech
        [label="impl_complete"];

    validate_{{ worker.bead_id | slugify }}_biz [
        shape=hexagon
        label="{{ worker.label }}\nBiz Validation"
        handler="wait_human"
        gate="business"
        mode="business"
        bead_id="AT-{{ worker.bead_id }}-BIZ"
        status="pending"
        style=filled
        fillcolor=lightyellow
    ];

    validate_{{ worker.bead_id | slugify }}_tech -> validate_{{ worker.bead_id | slugify }}_biz
        [label="tech pass"];

    decision_{{ worker.bead_id | slugify }} [
        shape=diamond
        label="{{ worker.label }}\nResult?"
        handler="conditional"
    ];

    validate_{{ worker.bead_id | slugify }}_biz -> decision_{{ worker.bead_id | slugify }};

    decision_{{ worker.bead_id | slugify }} -> {% if workers | length > 1 %}join_validation{% elif include_e2e %}impl_e2e{% else %}finalize{% endif %} [
        label="pass"
        condition="$last_status = 'success'"
        color=green
    ];

    decision_{{ worker.bead_id | slugify }} -> impl_{{ worker.bead_id | slugify }} [
        label="fail\nretry"
        condition="$last_status = 'failure'"
        color=red
        style=dashed
    ];
    {% endfor %}

    {% if workers | length > 1 %}
    // --- Fan-in ---
    join_validation [
        shape=tripleoctagon
        label="Join:\nAll Validated"
        handler="fan_in"
        status="pending"
        style=filled
        fillcolor=lightyellow
    ];
    {% endif %}

    {% if include_e2e %}
    // --- E2E Integration ---
    impl_e2e [
        shape=box
        label="E2E Integration\nTests"
        handler="codergen"
        bead_id="E2E-{{ prd_ref }}"
        worker_type="tdd-test-engineer"
        acceptance="Full integration test suite passes"
        prd_ref="{{ prd_ref }}"
        status="pending"
        style=filled
        fillcolor=lightyellow
    ];

    {% if workers | length > 1 %}
    join_validation -> impl_e2e [label="all pass"];
    {% endif %}

    validate_e2e [
        shape=hexagon
        label="E2E\nValidation"
        handler="wait_human"
        gate="e2e"
        mode="business"
        status="pending"
        style=filled
        fillcolor=lightyellow
    ];

    impl_e2e -> validate_e2e [label="impl_complete"];

    decision_e2e [
        shape=diamond
        label="E2E\nResult?"
        handler="conditional"
    ];

    validate_e2e -> decision_e2e;
    decision_e2e -> finalize [
        label="pass"
        condition="$last_status = 'success'"
        color=green
    ];
    decision_e2e -> impl_e2e [
        label="fail\nretry"
        condition="$last_status = 'failure'"
        color=red
        style=dashed
    ];
    {% endif %}

    // STAGE 5: FINALIZE
    finalize [
        shape=Msquare
        label="FINALIZE\n{{ prd_ref }}"
        handler="exit"
        {% if promise_id %}promise_id="{{ promise_id }}"{% endif %}
        status="pending"
        style=filled
        fillcolor=lightyellow
    ];
}
```

### 1.4 Constraint Enforcement Architecture

Three constraint types, enforced at different times:

```
+-----------------------------------------------------------+
|                 CONSTRAINT ENFORCEMENT                     |
+--------------+--------------------+------------------------+
| When         | Constraint Type    | Enforced By            |
+--------------+--------------------+------------------------+
| Instantiate  | topology_constraint| TemplateInstantiator   |
| (generate)   | path_constraint    | (static graph analysis)|
|              | loop_constraint    |                        |
+--------------+--------------------+------------------------+
| Parse        | node_state_machine | EngineRunner.__init__  |
| (load DOT)   | (loaded into SM)   | (loads SMs from mfst)  |
+--------------+--------------------+------------------------+
| Execute      | node_state_machine | ConstraintMiddleware   |
| (per-node)   | (enforced live)    | (new middleware)       |
+--------------+--------------------+------------------------+
```

#### 1.4.1 Static Constraints (Instantiation-Time)

Checked when a template is instantiated into a concrete DOT file. These are structural graph properties that can be verified by analysis:

**`path_constraint`**: Uses DFS to verify that every path from a source shape to a target shape passes through required intermediate shapes.

**`topology_constraint`**: Verifies structural pairing (e.g., every `component` has a reachable `tripleoctagon`).

**`loop_constraint`**: Overrides `LoopPolicy` defaults for the generated pipeline. Written as graph-level attributes in the output DOT.

#### 1.4.2 Dynamic Constraints (Execution-Time) — Node State Machines

This is the core new runtime capability. Each constraint of type `node_state_machine` defines a finite state machine that governs a node's `status` field transitions.

**New module**: `cobuilder/engine/state_machine.py`

```python
@dataclass(frozen=True)
class NodeStateMachine:
    """Finite state machine governing allowed status transitions for a node.

    Loaded from manifest.yaml constraint definitions. Applied by
    ConstraintMiddleware before each handler execution.
    """
    name: str
    applies_to_shape: str
    applies_to_handler: str | None  # None = all handlers with matching shape
    states: frozenset[str]
    transitions: dict[str, set[str]]  # from_state -> {allowed_to_states}
    initial_state: str
    terminal_states: frozenset[str]

    def can_transition(self, from_state: str, to_state: str) -> bool:
        """Return True if the transition from_state -> to_state is allowed."""
        allowed = self.transitions.get(from_state, set())
        return to_state in allowed

    def validate_transition(
        self, node_id: str, from_state: str, to_state: str
    ) -> None:
        """Raise ConstraintViolation if the transition is disallowed."""
        if not self.can_transition(from_state, to_state):
            raise ConstraintViolation(
                node_id=node_id,
                machine=self.name,
                from_state=from_state,
                to_state=to_state,
                allowed=self.transitions.get(from_state, set()),
            )
```

**New middleware**: `cobuilder/engine/middleware/constraint.py`

```python
class ConstraintMiddleware:
    """Middleware that enforces node state machine constraints.

    Inserted into the middleware chain BEFORE the handler executes.
    Reads the node's current status, checks that the handler's
    expected outcome status is a valid transition.

    Position in chain:
        Logfire -> TokenCounting -> Retry -> Constraint -> Audit -> Handler
    """

    def __init__(self, machines: dict[str, NodeStateMachine]):
        self._machines = machines  # keyed by shape or shape:handler

    async def __call__(self, request, next_handler):
        # Find applicable state machine
        machine = self._resolve_machine(request.node)
        if machine is None:
            return await next_handler(request)

        current_status = request.node.status
        outcome = await next_handler(request)

        # Map OutcomeStatus to node status
        new_status = self._outcome_to_status(outcome, request.node)
        if new_status and new_status != current_status:
            machine.validate_transition(
                request.node.id, current_status, new_status
            )

        return outcome
```

#### 1.4.3 Manifest Resolution

When the runner loads a DOT file, it checks for template metadata:

1. Read `_template` and `_template_version` from graph attributes.
2. If present, locate `templates/{_template}/manifest.yaml`.
3. Parse `constraints` section and build `NodeStateMachine` instances.
4. Pass machines to `ConstraintMiddleware` in the middleware chain.
5. If no template metadata, no constraints enforced (backward compatible).

### 1.5 Template Instantiation CLI

```bash
# List available templates
attractor templates list

# Show template parameters
attractor templates show hub-spoke

# Instantiate with parameters from CLI
attractor templates create hub-spoke \
    --prd PRD-AUTH-001 \
    --param 'workers=[...]' \
    --output .pipelines/pipelines/PRD-AUTH-001.dot

# Instantiate from a params file (preferred for complex templates)
attractor templates create hub-spoke \
    --params-file params.yaml \
    --output .pipelines/pipelines/PRD-AUTH-001.dot

# Validate constraints on an already-instantiated DOT file
attractor validate --constraints .pipelines/pipelines/PRD-AUTH-001.dot
```

**`params.yaml` example**:
```yaml
prd_ref: PRD-AUTH-001
promise_id: promise-abc123
include_e2e: true
workers:
  - label: "Backend Auth API"
    worker_type: backend-solutions-engineer
    bead_id: TASK-10
    acceptance: "POST /auth/login returns JWT"
    promise_ac: AC-1
  - label: "Login UI"
    worker_type: frontend-dev-expert
    bead_id: TASK-11
    acceptance: "Login form with validation"
    promise_ac: AC-2
```

### 1.6 Initial Template Library

| Template | Topology | Use Case |
|----------|----------|----------|
| `sequential-validated` | linear | Single-task PRDs: implement, validate, finalize |
| `hub-spoke` | parallel | Multi-task PRDs: fan-out workers, fan-in validation, optional E2E |
| `brainstorm-synthesize` | cyclic | Research tasks: N parallel researchers, synthesizer, quality gate, loop or exit |
| `retry-escalate` | linear+retry | Single task with escalation: try worker A, if fail escalate to worker B |
| `s3-lifecycle` | cyclic | **Part 2**: System 3 meta-pipeline (see below) |

### 1.7 Migration Path for `generate.py`

The existing `generate.py` becomes a thin wrapper:

```python
def generate_pipeline_dot(prd_ref, beads, label, promise_id, target_dir):
    """Generate pipeline DOT — now delegates to template instantiation."""
    workers = [bead_to_worker_param(b) for b in beads]
    template_name = "hub-spoke" if len(workers) > 1 else "sequential-validated"

    return instantiate_template(
        template_name=template_name,
        params={
            "prd_ref": prd_ref,
            "promise_id": promise_id,
            "workers": workers,
            "include_e2e": len(workers) > 1,
        },
        output_path=target_dir / f"{prd_ref}.dot",
    )
```

### 1.8 Implementation Modules

| Module | Purpose |
|--------|---------|
| `cobuilder/templates/instantiator.py` | Jinja2 rendering + static constraint validation |
| `cobuilder/templates/manifest.py` | Manifest YAML parsing + parameter validation |
| `cobuilder/templates/constraints.py` | Static constraint checkers (path, topology, loop) |
| `cobuilder/engine/state_machine.py` | `NodeStateMachine` model |
| `cobuilder/engine/middleware/constraint.py` | `ConstraintMiddleware` for runtime enforcement |
| `cobuilder/engine/runner.py` | Modified to load manifest + wire constraint middleware |

---

## Part 2: System 3 Meta-Pipeline

### 2.1 Vision

A user defines business outcomes in a PRD. System 3 becomes a **self-driving pipeline** that:

1. **Researches** the problem space
2. **Refines** the PRD with discovered constraints
3. **Plans** by generating sub-pipelines (DOT files)
4. **Executes** by launching pipeline runners for each sub-pipeline
5. **Validates** outcomes against PRD acceptance criteria
6. **Deploys** if validated
7. **Evaluates** business goals and loops back if not met

The key insight: **System 3 itself runs as a DOT pipeline** — specifically, the `s3-lifecycle` template — and one of its nodes (`execute`) spawns child pipeline runners. This is pipelines-all-the-way-down.

### 2.2 Architecture

```
+-----------------------------------------------------------------------+
|  USER CLI                                                              |
|  $ attractor launch-s3 --prd PRD-AUTH-001.md                          |
|    -> Instantiates s3-lifecycle template                               |
|    -> Launches EngineRunner on the S3 DOT pipeline                     |
+----------------------------+------------------------------------------+
                             |
                             v
+-----------------------------------------------------------------------+
|  S3 LIFECYCLE PIPELINE (cyclic DOT graph)                              |
|                                                                        |
|  +----------+  +--------+  +------+  +---------+  +----------+        |
|  | RESEARCH |->| REFINE |->| PLAN |->| EXECUTE |->| VALIDATE |        |
|  | (tab)    |  | (box)  |  | (box)|  | (house) |  | (hexagon)|        |
|  +----------+  +--------+  +------+  +---------+  +----------+        |
|       ^                                                 |              |
|       |                                   +-------------+              |
|       |                                   v             v              |
|       |                             +--------+    +----------+         |
|       |                             | DEPLOY |    | EVALUATE |         |
|       |                             | (tool) |    | (diamond)|         |
|       |                             +--------+    +-----+----+         |
|       |                                                 |              |
|       |         <-- loop_restart=true <-----------------+              |
|       |         (goals not met: cycle back to RESEARCH)               |
|       |                                                 |              |
|       |                                                 v              |
|       |                                           +----------+         |
|       |                                           |   EXIT   |         |
|       |                                           | (Msquare)|         |
|       |                                           +----------+         |
|       +-----------------------------------------------------+         |
+-----------------------------------------------------------------------+
               |
               |  EXECUTE node (ManagerLoopHandler) spawns:
               v
+-----------------------------------------------------------------------+
|  CHILD PIPELINE RUNNER (hub-spoke DOT graph)                           |
|                                                                        |
|  S3's PLAN node wrote this DOT file.                                   |
|  S3's EXECUTE node launches EngineRunner on it.                        |
|  S3's EXECUTE node monitors via signal protocol.                       |
|                                                                        |
|  +-------+   +----------+   +----------+   +---------+                |
|  | START |-->| Worker 1 |-->| Worker 2 |-->| FINISH  |                |
|  +-------+   +-----+----+   +-----+----+   +---------+                |
|                     |               |                                  |
|                     v               v                                  |
|               Signal files     Signal files                            |
+---------------------+---------------+----------------------------------+
                      |               |
                      v               v
+-----------------------------------------------------------------------+
|  STREAM SUMMARIZER (cheap LLM sidecar)                                 |
|                                                                        |
|  Watches: streaming JSON from Claude Code workers                      |
|  Watches: signal files in signals/ directory                           |
|  Produces: .pipelines/state/{pipeline-id}-summary.md            |
|  Model: Haiku (or local LLM) — cost-efficient continuous summarization |
|                                                                        |
|  S3's EXECUTE node reads the summary after child pipeline completes.   |
+-----------------------------------------------------------------------+
```

### 2.3 The S3 Lifecycle Template

```yaml
# .pipelines/templates/s3-lifecycle/manifest.yaml
template:
  name: s3-lifecycle
  version: "1.0"
  description: >
    Self-driving System 3 lifecycle: research, refine, plan,
    execute, validate, deploy, evaluate, loop
  topology: cyclic

parameters:
  prd_ref:
    type: string
    required: true
  prd_path:
    type: string
    required: true
    description: "Path to the PRD markdown file"
  target_repo:
    type: string
    required: true
    description: "Path to the target repository"
  max_cycles:
    type: integer
    default: 3
    description: "Maximum full research-to-evaluate cycles before forced exit"
  execution_template:
    type: string
    default: "hub-spoke"
    description: "Template to use for child pipelines generated by PLAN"
  deploy_command:
    type: string
    required: false
    default: ""
    description: "Deployment command (empty = skip deploy)"

constraints:
  lifecycle_transitions:
    type: node_state_machine
    applies_to:
      shape: box
    states: [pending, active, completed, failed]
    transitions:
      - {from: pending, to: active}
      - {from: active,  to: completed}
      - {from: active,  to: failed}
      - {from: failed,  to: active}
    initial: pending
    terminal: [completed, failed]

  bounded_lifecycle:
    type: loop_constraint
    rule:
      max_per_node_visits: 3
      max_pipeline_visits: 31

  must_validate_before_deploy:
    type: path_constraint
    rule:
      from_shape: house          # execute (manager_loop)
      must_pass_through:
        - hexagon                # validate
      before_reaching:
        - parallelogram          # deploy (tool)
```

### 2.4 Node Behaviors in the S3 Lifecycle

| Node | Shape | Handler | Behavior |
|------|-------|---------|----------|
| **RESEARCH** | `tab` | `research` | Uses Perplexity/Brave to research the problem domain. Reads PRD, identifies unknowns, writes research findings to `state/{prd}-research.json`. |
| **REFINE** | `box` | `codergen` | LLM node (Opus) that reads research findings + original PRD, produces a refined PRD with constraints, updated acceptance criteria, and solution design notes. Writes to `state/{prd}-refined.md`. |
| **PLAN** | `box` | `codergen` | LLM node (Opus) that reads refined PRD + beads data, selects a template, fills parameters, and writes a child pipeline DOT file to `pipelines/{prd}-cycle-{N}.dot`. Also writes `state/{prd}-plan.json` with the params used. |
| **EXECUTE** | `house` | `manager_loop` | **Key node.** Spawns an `EngineRunner` subprocess on the child DOT file. Monitors via signal protocol. Launches the stream summarizer sidecar. Blocks until child pipeline completes or fails. Writes `state/{prd}-execution-result.json`. |
| **VALIDATE** | `hexagon` | `wait_human` | Runs acceptance tests against the PRD. Can be automated (validation-test-agent) or human-gated. Reads execution results + evidence files. Writes `state/{prd}-validation.json`. |
| **DEPLOY** | `parallelogram` | `tool` | Runs the deploy command if provided. Skipped (auto-pass) if `deploy_command` is empty. |
| **EVALUATE** | `diamond` | `conditional` | Reads validation results + business goals from PRD. Condition: if all acceptance criteria met, exit. If not, `loop_restart=true` back to RESEARCH with updated context about what failed. |

### 2.5 The EXECUTE Node: Spawning Child Pipelines

The `ManagerLoopHandler` (shape `house`) already exists for orchestrator supervision. For the S3 lifecycle, we extend it to support a new mode: `spawn_pipeline`.

```dot
execute [
    shape=house
    label="EXECUTE\nChild Pipeline"
    handler="manager_loop"
    mode="spawn_pipeline"
    pipeline_template="{{ execution_template }}"
    pipeline_params_file="state/{{ prd_ref }}-plan.json"
    signals_dir="signals/{{ prd_ref }}"
    summarizer="true"
    status="pending"
    style=filled
    fillcolor=lightyellow
];
```

**ManagerLoopHandler extension** (pseudo-code):

```python
async def execute(self, request: HandlerRequest) -> Outcome:
    if request.node.attrs.get("mode") == "spawn_pipeline":
        return await self._execute_child_pipeline(request)
    else:
        return await self._execute_supervisor_loop(request)

async def _execute_child_pipeline(self, request):
    # 1. Load the DOT file that PLAN node generated
    plan = json.loads(
        Path(request.node.attrs["pipeline_params_file"]).read_text()
    )
    dot_path = plan["dot_path"]

    # 2. Optionally launch stream summarizer sidecar
    summarizer = None
    if request.node.attrs.get("summarizer") == "true":
        summarizer = await self._launch_summarizer(
            dot_path, plan["prd_ref"]
        )

    # 3. Spawn child EngineRunner as subprocess
    child = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "cobuilder.engine.runner",
        "--dot", str(dot_path),
        "--signals-dir", request.node.attrs.get("signals_dir", ""),
    )

    # 4. Monitor via signal protocol (poll for RUNNER_EXITED signal)
    result = await self._monitor_child(child, request)

    # 5. Collect summarizer output
    summary = ""
    if summarizer:
        summary = await summarizer.get_summary()
        request.context.update({"execution_summary": summary})

    # 6. Return outcome based on child pipeline result
    if result["status"] == "completed":
        return Outcome(
            status=OutcomeStatus.SUCCESS,
            context_updates={
                "child_checkpoint": result["checkpoint_path"],
                "execution_summary": summary,
            },
        )
    else:
        return Outcome(
            status=OutcomeStatus.FAILURE,
            context_updates={
                "failure_reason": result.get("error", "unknown"),
            },
        )
```

### 2.6 Stream Summarizer Sidecar

A lightweight process that watches Claude Code streaming JSON output and signal files, producing rolling summaries for System 3 to consume.

**Module**: `cobuilder/sidecar/stream_summarizer.py`

```
+--------------------------------------------------------------+
|  STREAM SUMMARIZER                                            |
|                                                               |
|  Inputs:                                                      |
|  +-- Claude Code streaming JSON (stdout pipe or log file)     |
|  +-- Signal files (signal_protocol.py reader)                 |
|  +-- Checkpoint file (periodic reads)                         |
|                                                               |
|  Processing:                                                  |
|  +-- Accumulate events into rolling buffer (last 50 events)   |
|  +-- Every 60s OR on signal event: summarize with Haiku       |
|  +-- Write summary to state/{pipeline-id}-summary.md          |
|                                                               |
|  Outputs:                                                     |
|  +-- state/{pipeline-id}-summary.md  (human-readable)         |
|  +-- state/{pipeline-id}-summary.json (machine-readable)      |
|  +-- Returns final summary on completion                      |
|                                                               |
|  Cost model:                                                  |
|  +-- Haiku @ ~$0.25/1M input tokens                           |
|  +-- ~2K tokens per summarization call                        |
|  +-- ~30 calls per hour of pipeline execution                 |
|  +-- Total: ~$0.015/hour — negligible                         |
+--------------------------------------------------------------+
```

**Summary JSON format**:

```json
{
  "pipeline_id": "PRD-AUTH-001-cycle-1",
  "timestamp": "2026-03-12T14:30:00Z",
  "cycle": 1,
  "nodes_completed": 3,
  "nodes_total": 7,
  "nodes_failed": 0,
  "current_activity": "Backend worker implementing JWT auth endpoint",
  "key_events": [
    "Backend worker spawned at 14:22",
    "Frontend worker spawned at 14:22",
    "Backend: 47 files modified, tests passing",
    "Frontend: blocked on API schema"
  ],
  "blockers": ["Frontend waiting for backend API schema"],
  "estimated_progress_pct": 42,
  "tokens_used": 145000,
  "elapsed_seconds": 480
}
```

### 2.7 The PLAN Node: Generating Child Pipelines

The PLAN node is a `codergen` (LLM) node that uses Opus to:

1. Read the refined PRD (`state/{prd}-refined.md`)
2. Read beads data (`bd list --json --epic {prd}`)
3. Select the appropriate template based on task structure
4. Fill template parameters
5. Write the instantiated DOT file

**System prompt for PLAN node** (embedded in node attributes or referenced file):

```
You are a pipeline architect. Your job is to translate a PRD into an
executable Attractor DOT pipeline.

Available templates: {template_list}

Read the refined PRD and task list. Then:
1. Choose the best template for this work structure
2. Map each task to a worker parameter
3. Generate a params.yaml file
4. Call: attractor templates create {template} \
       --params-file params.yaml --output {output_path}
5. Write state/{prd}-plan.json with:
   {"dot_path": "...", "template": "...", "params": {...}}
```

### 2.8 The Evaluation Loop

The EVALUATE node (diamond/conditional) uses edge conditions to decide whether to loop:

```dot
evaluate [
    shape=diamond
    label="Goals\nMet?"
    handler="conditional"
];

// All goals met -> exit
evaluate -> finalize [
    label="goals met"
    condition="$validation_passed = true AND $cycle_count < {{ max_cycles }}"
    color=green
    style=bold
];

// Goals not met, cycles remaining -> loop back
evaluate -> research [
    label="iterate"
    condition="$validation_passed = false AND $cycle_count < {{ max_cycles }}"
    color=orange
    loop_restart=true
];

// Max cycles exhausted -> exit with partial results
evaluate -> finalize [
    label="max cycles"
    condition="$cycle_count >= {{ max_cycles }}"
    color=red
];
```

The `loop_restart=true` edge attribute (already supported by Epic 5) clears pipeline context back to graph-level variables, so each cycle starts fresh while preserving the cycle counter and accumulated learnings.

### 2.9 Context Propagation Across Cycles

Between cycles, the following context survives (stored in graph-level attrs and explicit context keys):

| Key | Survives Loop Restart | Purpose |
|-----|----------------------|---------|
| `$cycle_count` | Yes (incremented) | Track which iteration we're on |
| `$previous_failures` | Yes (appended) | What failed in prior cycles |
| `$research_findings` | No (re-generated) | Fresh research each cycle |
| `$refined_prd` | No (re-generated) | PRD refined with new learnings |
| `$child_checkpoint` | No (new pipeline) | Points to child's checkpoint |
| `$execution_summary` | No (new summary) | Summarizer output |
| `$validation_passed` | No (re-evaluated) | Fresh validation each cycle |

The `$previous_failures` key is the feedback loop — it tells the RESEARCH node what went wrong so the next cycle can address it.

### 2.10 Full Launch Sequence

```bash
# 1. User writes PRD
vim docs/PRD-AUTH-001.md

# 2. User launches System 3 lifecycle
attractor launch-s3 \
    --prd PRD-AUTH-001 \
    --prd-path docs/PRD-AUTH-001.md \
    --target-repo /path/to/project \
    --max-cycles 3 \
    --execution-template hub-spoke

# Under the hood:
# a) Instantiates s3-lifecycle template -> s3-PRD-AUTH-001.dot
# b) Launches EngineRunner on s3-PRD-AUTH-001.dot
# c) RESEARCH node fires (Perplexity/Brave)
# d) REFINE node fires (Opus LLM)
# e) PLAN node fires (Opus LLM -> writes child pipeline DOT)
# f) EXECUTE node fires (spawns child EngineRunner + summarizer)
#    - Child pipeline runs workers in parallel
#    - Summarizer produces rolling updates
#    - Signal files flow between child and parent
# g) VALIDATE node fires (acceptance tests)
# h) DEPLOY node fires (if deploy_command set)
# i) EVALUATE node fires (conditional: loop or exit)
# j) If goals not met -> back to RESEARCH with failure context
# k) If goals met -> FINALIZE and exit
```

---

## Part 3: Implementation Plan

### Phase 1: Template Infrastructure (Foundation)

| Task | Module | Depends On |
|------|--------|------------|
| T1.1 Manifest parser | `cobuilder/templates/manifest.py` | -- |
| T1.2 Jinja2 instantiator | `cobuilder/templates/instantiator.py` | T1.1 |
| T1.3 Static constraint validators | `cobuilder/templates/constraints.py` | T1.1 |
| T1.4 `NodeStateMachine` model | `cobuilder/engine/state_machine.py` | -- |
| T1.5 `ConstraintMiddleware` | `cobuilder/engine/middleware/constraint.py` | T1.4 |
| T1.6 Runner loads manifest | `cobuilder/engine/runner.py` (modify) | T1.4, T1.5 |
| T1.7 CLI commands | `cobuilder/cli/templates.py` | T1.2, T1.3 |

### Phase 2: Template Library

| Task | Template | Depends On |
|------|----------|------------|
| T2.1 `sequential-validated` | Simplest template | T1.2 |
| T2.2 `hub-spoke` | Parallel workers | T1.2 |
| T2.3 `brainstorm-synthesize` | Cyclic research | T1.2 |
| T2.4 `retry-escalate` | Escalation chain | T1.2 |
| T2.5 Migrate `generate.py` | Delegate to templates | T2.1, T2.2 |

### Phase 3: S3 Meta-Pipeline

| Task | Module | Depends On |
|------|--------|------------|
| T3.1 `s3-lifecycle` template | Template directory | T2.2 |
| T3.2 ManagerLoopHandler `spawn_pipeline` mode | `handlers/manager_loop.py` | T1.2, T1.6 |
| T3.3 Stream summarizer sidecar | `cobuilder/sidecar/stream_summarizer.py` | -- |
| T3.4 `launch-s3` CLI command | `cobuilder/cli/launch_s3.py` | T3.1, T3.2, T3.3 |
| T3.5 Context propagation for cycles | `cobuilder/engine/runner.py` | T3.2 |

### Phase 4: Intent-to-DOT (Future)

| Task | Module | Depends On |
|------|--------|------------|
| T4.1 Intent parser (LLM template selection) | `cobuilder/templates/intent.py` | Phase 2 |
| T4.2 `--from-intent` CLI flag | CLI integration | T4.1 |

---

## Appendix A: Constraint Type Reference

| Type | Checked At | Mechanism | Example |
|------|-----------|-----------|---------|
| `node_state_machine` | Runtime (per-node) | `ConstraintMiddleware` | "codergen nodes: pending->active->impl_complete->validated" |
| `path_constraint` | Instantiation (static) | DFS graph analysis | "every box must pass hexagon before reaching Msquare" |
| `topology_constraint` | Instantiation (static) | Structural pairing | "every component must have downstream tripleoctagon" |
| `loop_constraint` | Instantiation to Runtime | Sets `LoopPolicy` overrides | "max 4 visits per node, max 50 pipeline-wide" |

## Appendix B: Why Not a New Language?

We considered:

- **Pure YAML graph definition** (like MASFactory): Rejected because DOT is already our universal format, renders natively in Graphviz, and is well-understood by the team.
- **Python graph construction API**: Rejected because DOT-as-data is more portable than DOT-as-code. Templates give us parameterization without requiring Python.
- **JSON Schema for constraints**: Considered but YAML is more readable for the manifest format. JSON Schema would add verbosity without benefit.

The chosen approach — **DOT + Jinja2 for topology, YAML for constraints** — keeps DOT as the universal graph format while adding the minimum necessary metadata for enforcement.

## Appendix C: Backward Compatibility

| Scenario | Behavior |
|----------|----------|
| Existing DOT file, no `_template` attr | Runs exactly as today. No constraints. |
| Existing DOT, `_template` attr but manifest missing | Warning logged. Runs without constraints. |
| Template-generated DOT, manifest present | Full constraint enforcement. |
| Template-generated DOT, constraint violation | `ConstraintViolation` raised, node fails, retry or escalate. |

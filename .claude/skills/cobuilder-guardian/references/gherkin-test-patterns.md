---
title: "Gherkin Test Patterns"
status: active
type: skill
last_verified: 2026-02-19
grade: authoritative
---

# Gherkin Test Patterns for Blind Validation

Syntax, conventions, and calibration guides for writing Gherkin-style acceptance tests used in the CoBuilder Guardian pattern.

---

## 1. Gherkin DSL Adapted for Confidence Scoring

Standard Gherkin uses boolean PASS/FAIL assertions. The guardian pattern adapts it to support gradient confidence scoring (0.0-1.0). Each `Then` clause is not a boolean check — it is a rubric evaluated by the guardian during independent validation.

### Syntax

```gherkin
Feature: {Feature Name}
  Weight: {0.XX}
  Description: {One-line description from PRD}

  Scenario: {Descriptive scenario name}
    Given {precondition that must exist}
    And {additional precondition if needed}
    When {the implementation is examined}
    Then {expected outcome to verify}
    And {additional outcome if needed}

    # Confidence Scoring Guide:
    # 0.0 — {description of total absence}
    # 0.2 — {description of token/stub implementation}
    # 0.4 — {description of partial, broken implementation}
    # 0.6 — {description of functional but incomplete implementation}
    # 0.8 — {description of solid implementation with minor gaps}
    # 1.0 — {description of complete, production-quality implementation}
    #
    # Evidence to Check:
    #   - {specific file path or pattern}
    #   - {specific function or class name}
    #   - {specific test file or test name}
    #   - {specific behavior observable in output}
    #
    # Red Flags:
    #   - {indicator that claims exceed reality}
    #   - {common shortcut that looks complete but isn't}
    #   - {missing piece that suggests copy-paste or placeholder}
```

### Key Differences from Standard Gherkin

| Standard Gherkin | Guardian Gherkin |
|-----------------|-----------------|
| `Then` is a boolean assertion | `Then` is a rubric with gradient scoring |
| Test runs automatically | Guardian evaluates manually by reading code |
| One scenario = one test case | One scenario = one scoring dimension |
| Tags for test categorization | Weights for business criticality |
| Step definitions in code | Scoring guides in comments |

---

## 2. Feature Weighting Methodology

### Weight Assignment Process

1. **List all features** from the Business Spec (BS)
2. **Rank by business impact**: "If this feature is completely missing, how badly does the initiative fail?"
3. **Assign initial weights** based on ranking:
   - Top feature: 0.25-0.35
   - Second feature: 0.15-0.25
   - Third feature: 0.10-0.20
   - Remaining features: distribute the rest
4. **Verify sum = 1.00** (adjust proportionally if needed)
5. **Sanity check**: Would a product owner agree that this feature ranking reflects business priority?

### Weight Categories

| Range | Category | Typical Features |
|-------|----------|-----------------|
| 0.25-0.35 | Critical | Core pipeline, main data flow, primary user action |
| 0.15-0.24 | Important | Error handling, secondary workflows, API integration |
| 0.08-0.14 | Supporting | Configuration, logging, minor utilities |
| 0.03-0.07 | Polish | Documentation, comments, code style |

### Example Weight Distribution

For a data pipeline Business Spec (BS) with 5 features:

```yaml
features:
  - name: "Pipeline execution engine"
    weight: 0.30
  - name: "Data transformation layer"
    weight: 0.25
  - name: "Error handling and retry"
    weight: 0.20
  - name: "Configuration management"
    weight: 0.15
  - name: "Logging and observability"
    weight: 0.10
# Total: 1.00
```

---

## 3. Scoring Calibration

The confidence scale must be calibrated consistently across scenarios. Use these reference points:

### Universal Calibration Guide

| Score | Label | What It Means |
|-------|-------|---------------|
| 0.0 | Absent | No evidence of implementation. Feature not attempted. |
| 0.1 | Token | A file or function name exists but contains no real logic (empty stub, `pass`, `TODO`). |
| 0.2 | Stub | Skeleton code exists — imports, function signatures, type hints — but no business logic. |
| 0.3 | Broken | Implementation attempted but does not work. Syntax errors, missing dependencies, logic errors. |
| 0.4 | Partial | Some paths work but core functionality is incomplete. Happy path may work; edge cases fail. |
| 0.5 | Basic | Core functionality works for the simplest case. No error handling. No tests. Fragile. |
| 0.6 | Functional | Feature works for most cases. Some error handling. At least basic tests exist. |
| 0.7 | Solid | Feature works well. Error handling covers common cases. Tests pass. Minor gaps in edge cases. |
| 0.8 | Good | Feature is well-implemented. Comprehensive error handling. Good test coverage. Minor polish missing. |
| 0.9 | Excellent | Feature is production-quality. All edge cases handled. Thorough testing. Clean code. |
| 1.0 | Complete | Feature exceeds expectations. Exemplary implementation with documentation, tests, and observability. |

### Domain-Specific Calibration

Adapt the universal guide to the specific feature being evaluated. The `Confidence Scoring Guide` comment in each scenario should map these universal levels to concrete, observable evidence for that specific feature.

**Good calibration** (specific, observable):
```
# 0.0 — No pipeline.py file exists
# 0.5 — pipeline.py exists, main() runs without error on sample data, no retry logic
# 1.0 — pipeline.py handles all 3 data sources, retries on failure, logs progress, 15+ tests pass
```

**Bad calibration** (vague, subjective):
```
# 0.0 — Not implemented
# 0.5 — Partially implemented
# 1.0 — Fully implemented
```

---

## 4. Red Flag Guides

Red flags are indicators that an implementation may be less complete than claimed. Include at least one per scenario.

### Common Red Flags

| Red Flag | What It Suggests |
|----------|-----------------|
| Function defined but never called | Dead code, not integrated |
| Tests mock everything | No real integration testing |
| `# TODO` / `# FIXME` / `# HACK` markers | Known incomplete areas |
| Configuration hardcoded | Works in dev, breaks in prod |
| Error handling catches generic `Exception` | No real error handling strategy |
| Copy-pasted code blocks | Quick implementation, not thoughtful |
| Imports that are not used | Leftover from refactoring or copy-paste |
| Test file exists but all tests are `@skip` | Fake test coverage |
| README says "implemented" but no code evidence | Self-reported without substance |
| Git commit message says "complete" for a WIP | Premature claims |

### Red Flag Severity

| Severity | Impact on Score |
|----------|-----------------|
| Minor | Reduce score by 0.05-0.10 |
| Moderate | Reduce score by 0.10-0.20 |
| Major | Reduce score by 0.20-0.40 |
| Critical | Feature cannot score above 0.3 regardless of other evidence |

---

## 5. Manifest Schema

The `manifest.yaml` file defines metadata, features, and thresholds for an acceptance test suite.

```yaml
# manifest.yaml schema
prd_id: "PRD-{ID}"
prd_title: "{PRD Title}"
created_at: "{ISO 8601 timestamp}"
created_by: "cobuilder-guardian"
impl_repo: "/absolute/path/to/implementation/repo"

# Scoring thresholds (configurable per initiative)
thresholds:
  accept: 0.60      # Weighted score >= this → ACCEPT
  investigate: 0.40  # Weighted score >= this but < accept → INVESTIGATE
  reject: 0.40      # Weighted score < this → REJECT

# Validation protocol
validation_protocol:
  evidence_sources:
    - git_diff         # Check actual code changes
    - file_contents    # Read implementation files
    - test_results     # Run test suite if available
    - import_graph     # Verify dependency connections
  require_test_execution: false  # Set true if test suite must be runnable
  time_limit_hours: 4            # Max guardian session duration

# Features with weights
features:
  - name: "{Feature 1 Name}"
    description: "{One-line description}"
    weight: 0.30
    validation_method: hybrid  # code-analysis | browser-required | api-required | hybrid
    scenarios:
      - "scenario_1_name"
      - "scenario_2_name"

  - name: "{Feature 2 Name}"
    description: "{One-line description}"
    weight: 0.25
    scenarios:
      - "scenario_3_name"

  - name: "{Feature 3 Name}"
    description: "{One-line description}"
    weight: 0.20
    scenarios:
      - "scenario_4_name"
      - "scenario_5_name"

  - name: "{Feature 4 Name}"
    description: "{One-line description}"
    weight: 0.15
    scenarios:
      - "scenario_6_name"

  - name: "{Feature 5 Name}"
    description: "{One-line description}"
    weight: 0.10
    scenarios:
      - "scenario_7_name"

# Weight verification (MUST equal 1.00)
total_weight: 1.00
```

### Feature `validation_method` Field

Each feature MAY include a `validation_method` field that classifies how the feature should be validated:

| Value | Meaning | When to Use |
|-------|---------|-------------|
| `code-analysis` | Static code reading only | Database schemas, migrations, code structure, config files |
| `browser-required` | Must use Claude in Chrome | UI rendering, page navigation, user interactions, visual elements |
| `api-required` | Must make actual HTTP requests | API endpoints, REST responses, webhook triggers |
| `hybrid` | Mixed or unclear | Default when absent; no special enforcement |

If `validation_method` is omitted, it defaults to `hybrid` (backward-compatible, no enforcement).

### Manifest Validation Rules

1. `total_weight` MUST equal the sum of all feature weights
2. `total_weight` MUST equal 1.00
3. Every feature MUST have at least one scenario
4. Every scenario name MUST appear in the corresponding `.feature` file
5. `thresholds.reject` MUST equal `thresholds.investigate` (no gap between ranges)
6. `thresholds.accept` MUST be greater than `thresholds.investigate`
7. If present, `validation_method` MUST be one of: `code-analysis`, `browser-required`, `api-required`, `hybrid`

---

## 6. Storage Location

Acceptance tests MUST be stored in the config repo, NEVER in the implementation repo.

```
claude-harness-setup/                    # Config repo (guardian lives here)
├── acceptance-tests/
│   ├── PRD-AUTH-001/
│   │   ├── manifest.yaml
│   │   └── auth_scenarios.feature
│   ├── PRD-PIPELINE-002/
│   │   ├── manifest.yaml
│   │   └── prefect_pipeline_scenarios.feature
│   └── PRD-DASH-003/
│       ├── manifest.yaml
│       └── dashboard_scenarios.feature
├── .claude/
│   └── skills/
│       └── cobuilder-guardian/          # This skill
└── ...
```

The implementation repo (where the operator works) MUST NOT contain any reference to these acceptance tests. If the operator can see the rubric, the validation is no longer independent.

---

## 7. Complete Example

This example is based on a real Prefect pipeline validation session.

### manifest.yaml

```yaml
prd_id: "PRD-PREFECT-001"
prd_title: "Prefect Pipeline Integration"
created_at: "2026-02-19T10:00:00+11:00"
created_by: "cobuilder-guardian"
impl_repo: "$CLAUDE_PROJECT_DIR"

thresholds:
  accept: 0.60
  investigate: 0.40
  reject: 0.40

validation_protocol:
  evidence_sources:
    - git_diff
    - file_contents
    - test_results
    - import_graph
  require_test_execution: true
  time_limit_hours: 3

features:
  - name: "Pipeline Definition and Execution"
    description: "Prefect flows and tasks defined and executable"
    weight: 0.30
    scenarios:
      - "pipeline_flow_definition"
      - "pipeline_task_execution"

  - name: "Data Source Integration"
    description: "Pipeline connects to all required data sources"
    weight: 0.25
    scenarios:
      - "data_source_connectivity"

  - name: "Error Handling and Retry"
    description: "Pipeline handles failures with retry logic"
    weight: 0.20
    scenarios:
      - "retry_on_transient_failure"
      - "error_reporting"

  - name: "Configuration Management"
    description: "Pipeline configuration is externalized and validated"
    weight: 0.15
    scenarios:
      - "config_externalization"

  - name: "Observability"
    description: "Pipeline emits logs, metrics, and status updates"
    weight: 0.10
    scenarios:
      - "logging_and_status"

total_weight: 1.00
```

### prefect_pipeline_scenarios.feature

```gherkin
Feature: Pipeline Definition and Execution
  Weight: 0.30
  Description: Prefect flows and tasks defined and executable

  Scenario: pipeline_flow_definition
    Given a Prefect environment is available
    And the pipeline source code exists
    When the pipeline module is imported
    Then a Prefect @flow decorated function exists
    And the flow accepts configuration parameters
    And the flow orchestrates at least 3 @task functions

    # Confidence Scoring Guide:
    # 0.0 — No pipeline file exists, no Prefect imports
    # 0.2 — File exists with Prefect imports but no @flow decorator
    # 0.4 — @flow exists but orchestrates zero tasks (empty body)
    # 0.6 — @flow orchestrates 1-2 tasks, basic happy path works
    # 0.8 — @flow orchestrates 3+ tasks with proper parameter passing
    # 1.0 — @flow is well-structured, typed parameters, docstring, 3+ tasks with dependencies
    #
    # Evidence to Check:
    #   - src/pipeline.py or src/flows/*.py for @flow decorator
    #   - grep for "@task" to count task definitions
    #   - Check that tasks are called within the flow function body
    #
    # Red Flags:
    #   - @flow decorator on an empty function
    #   - Tasks defined but never called from the flow
    #   - All logic in the flow function, no task decomposition

  Scenario: pipeline_task_execution
    Given the pipeline flow is defined
    When a task is invoked with sample data
    Then the task processes data and returns a result
    And the result type matches the task return annotation

    # Confidence Scoring Guide:
    # 0.0 — No @task functions defined
    # 0.3 — @task functions exist but contain only pass/TODO
    # 0.5 — @task functions have logic but no return type or error handling
    # 0.7 — @task functions process data correctly with return types
    # 1.0 — @task functions are well-typed, documented, handle edge cases, have unit tests
    #
    # Evidence to Check:
    #   - Each @task function body for real logic (not stubs)
    #   - Return type annotations on task functions
    #   - tests/test_pipeline.py or tests/test_tasks.py for task-level tests
    #
    # Red Flags:
    #   - Tasks that just pass data through without transformation
    #   - All tasks have identical structure (copy-paste)

Feature: Data Source Integration
  Weight: 0.25
  Description: Pipeline connects to all required data sources

  Scenario: data_source_connectivity
    Given data source credentials are configured
    When the pipeline attempts to connect to each source
    Then connections succeed for all required sources
    And data can be read from each source

    # Confidence Scoring Guide:
    # 0.0 — No data source configuration or connection code
    # 0.2 — Connection strings are hardcoded, no actual connector implementation
    # 0.4 — One data source connected, others are stubs
    # 0.6 — All sources have connection code, at least one tested
    # 0.8 — All sources connected with credential management and error handling
    # 1.0 — All sources connected, credentials externalized, connection pooling, retry on disconnect
    #
    # Evidence to Check:
    #   - Config files for data source credentials (not hardcoded)
    #   - Connection initialization code for each source
    #   - Tests that verify connectivity (even if mocked)
    #
    # Red Flags:
    #   - Credentials hardcoded in source files
    #   - "# TODO: connect to production database"
    #   - Mock-only tests with no integration test option

Feature: Error Handling and Retry
  Weight: 0.20
  Description: Pipeline handles failures with retry logic

  Scenario: retry_on_transient_failure
    Given a pipeline task is configured with retry policy
    When the task encounters a transient failure
    Then the task retries according to policy
    And retry attempts are logged

    # Confidence Scoring Guide:
    # 0.0 — No retry logic anywhere
    # 0.2 — Prefect retry parameters set on decorator but no custom handling
    # 0.5 — Retry parameters on tasks with basic exponential backoff
    # 0.7 — Retry with backoff, distinguishes transient vs permanent failures
    # 1.0 — Retry with backoff, failure classification, dead letter handling, alert on exhaustion
    #
    # Evidence to Check:
    #   - @task(retries=N, retry_delay_seconds=...) parameters
    #   - Custom retry handlers or failure hooks
    #   - Tests that simulate failure and verify retry behavior
    #
    # Red Flags:
    #   - retries=0 on all tasks
    #   - Generic except: pass blocks swallowing errors
    #   - No distinction between retryable and fatal errors

  Scenario: error_reporting
    Given a pipeline task fails permanently
    When all retries are exhausted
    Then the error is reported to the monitoring system
    And the pipeline state reflects the failure

    # Confidence Scoring Guide:
    # 0.0 — Errors are silently swallowed
    # 0.3 — Errors are printed to stdout only
    # 0.5 — Errors are logged with context
    # 0.7 — Errors are logged and pipeline status is updated
    # 1.0 — Errors are logged, status updated, alert sent, and failure context preserved for debugging
    #
    # Evidence to Check:
    #   - Logging configuration (structured logging preferred)
    #   - Error handler functions or hooks
    #   - State management after failure (does pipeline know it failed?)
    #
    # Red Flags:
    #   - except Exception: pass (swallowing all errors)
    #   - print() instead of logging
    #   - No failure state tracking

Feature: Configuration Management
  Weight: 0.15
  Description: Pipeline configuration is externalized and validated

  Scenario: config_externalization
    Given environment-specific configuration exists
    When the pipeline starts
    Then configuration is loaded from external source
    And configuration values are validated before use

    # Confidence Scoring Guide:
    # 0.0 — All values hardcoded in source files
    # 0.2 — Some values moved to constants file but still in code
    # 0.4 — Environment variables read but no validation or defaults
    # 0.6 — Config loaded from file/env with basic validation
    # 0.8 — Config loaded from file/env, validated with Pydantic or similar, with defaults
    # 1.0 — Config with validation, defaults, per-environment overrides, documented schema
    #
    # Evidence to Check:
    #   - config.py, settings.py, or similar configuration module
    #   - Pydantic BaseSettings or similar validation
    #   - .env.example or config.example.yaml for documentation
    #
    # Red Flags:
    #   - Database URLs or API keys in source code
    #   - os.getenv() without default values
    #   - No configuration documentation

Feature: Observability
  Weight: 0.10
  Description: Pipeline emits logs, metrics, and status updates

  Scenario: logging_and_status
    Given the pipeline is running
    When tasks execute
    Then structured logs are emitted for each stage
    And pipeline progress is trackable

    # Confidence Scoring Guide:
    # 0.0 — No logging at all
    # 0.2 — print() statements only
    # 0.4 — Python logging module used but unstructured
    # 0.6 — Structured logging with log levels used appropriately
    # 0.8 — Structured logging, progress reporting, key metrics logged
    # 1.0 — Structured logging, metrics, progress reporting, dashboard-ready output
    #
    # Evidence to Check:
    #   - import logging / import structlog
    #   - Log level usage (DEBUG, INFO, WARNING, ERROR)
    #   - Progress indicators in flow/task functions
    #
    # Red Flags:
    #   - print() used instead of logging
    #   - All log messages are INFO level (no differentiation)
    #   - Logging configured but no log statements in business logic
```

---

**Reference Version**: 0.1.0
**Parent Skill**: cobuilder-guardian

---

## Guardian Phase 1: Acceptance Test Creation Workflow

> Extracted from cobuilder-guardian SKILL.md — full Phase 1 procedure for generating blind acceptance tests from Technical Spec documents.

Generate blind acceptance tests from **Technical Spec (TS) documents** before any implementation begins.
The TS is the correct input because it contains:
- **Business Context section** — the goals and success metrics the tests should validate
- **Section 6: Acceptance Criteria per Feature** — Gherkin-ready criteria for each feature

The Business Spec (BS) provides the broader context, but the TS contains the structured,
feature-level acceptance criteria that `acceptance-test-writer` needs to generate meaningful tests.

This phase uses `acceptance-test-writer` in two modes: `--mode=guardian` for per-epic Gherkin scenarios,
and `--mode=journey` for cross-layer business journey scenarios.

**Document lookup**:
- TS files are in the implementation repo at: `.taskmaster/docs/SD-{CATEGORY}-{NUMBER}-{epic-slug}.md`
- BS files are at: `.taskmaster/docs/PRD-{CATEGORY}-{DESCRIPTOR}.md`
- Both live in `.taskmaster/docs/` — TSs can be read directly from the impl repo path

### Step 1: Generate Per-Epic Gherkin Tests (Guardian Mode)

Invoke the acceptance-test-writer skill in guardian mode. This generates the per-epic Gherkin
scenarios with confidence scoring guides that will be used for Phase 4 validation.

```python
# Source the TS document — it has the structured acceptance criteria
# The --prd flag identifies the parent PRD for test organisation
Skill("acceptance-test-writer", args="--source=/path/to/impl-repo/.taskmaster/docs/SD-{ID}.md --prd=PRD-{ID} --mode=guardian")
```

If no SD exists yet (legacy initiative), fall back to the PRD:
```python
Skill("acceptance-test-writer", args="--source=/path/to/impl-repo/.taskmaster/docs/PRD-{ID}.md --mode=guardian")
```

This creates:
- `acceptance-tests/PRD-{ID}/manifest.yaml` — feature weights and decision thresholds
- `acceptance-tests/PRD-{ID}/scenarios.feature` — Gherkin scenarios with confidence scoring guides

**Verify the output:**
- [ ] All TS features (Section 4: Functional Decomposition) represented with weights summing to 1.0
- [ ] Each scenario has a confidence scoring guide (0.0 / 0.5 / 1.0 anchors)
- [ ] Evidence references are specific (file names, function names, test names from TS File Scope)
- [ ] Red flags section present for each scenario
- [ ] manifest.yaml has valid thresholds (default: accept=0.60, investigate=0.40)
- [ ] **Every feature has `validation_method`** — one of: `browser-required`, `api-required`, `code-analysis`, `doc-review`, `e2e-test`, `hybrid`. This is enforced by validator.py Rule 16; pipelines will fail validation without it.

If the acceptance-test-writer cannot find a Goals section in the TS, use the TS's Business Context
section (Section 1) or derive objectives from the parent BS's Goals (Section 2).

### Step 2: Generate Journey Tests (Journey Mode)

After generating per-epic Gherkin, generate blind journey tests from the **Business Spec (BS)** — not the TS.
Journey tests are cross-epic: they verify end-to-end business flows that span multiple epics and
cannot be validated by any single TS. The BS's Goals and User Stories sections define these flows.

```python
# Source the PRD — journey tests must capture cross-epic business outcomes
# One set of journey tests per PRD (not per SD)
Skill("acceptance-test-writer", args="--source=/path/to/impl-repo/.taskmaster/docs/PRD-{ID}.md --prd=PRD-{ID} --mode=journey")
```

This creates `acceptance-tests/PRD-{ID}/journeys/` in the config repo (where meta-orchestrators cannot see it).
Journey tests are generated BEFORE the meta-orchestrator is spawned — they stay blind throughout.

**Verify the output:**
- [ ] At least one `J{N}.feature` file exists per BS business objective (Goals section / Section 2)
- [ ] Scenarios cross epic boundaries — a journey that stays within one epic is a mis-scoped scenario
- [ ] `runner_config.yaml` is present with sensible service URLs
- [ ] Each scenario crosses at least 2 system layers and ends with a business outcome assertion
- [ ] Tags include `@journey @prd-{ID} @J{N}`

**Storage location**: Both per-epic and journey tests live in `acceptance-tests/PRD-{ID}/` in the config
repo (claude-harness-setup), never in the implementation repo. Meta-orchestrators and their workers never see
the rubric or the journeys. This enables truly independent validation.

### Step 3: Generate Executable Browser Test Scripts (MANDATORY for UX Business Specs)

**Trigger condition**: If the manifest.yaml contains ANY feature with `validation_method: browser-required`, this step is MANDATORY. Skip for BSs with only `code-analysis` and `api-required` features.

The Gherkin scenarios from Step 1 are scoring rubrics — they guide confidence scoring but are not directly executable. This step generates companion executable test scripts that can be run by a tdd-test-engineer agent against a live frontend using claude-in-chrome MCP tools.

**Why the existing scenarios.feature is NOT sufficient**: The PRD-P1.1-UNIFIED-FORM-001 experience demonstrated this gap. 17 Gherkin scenarios were written as scoring rubrics with confidence guides (0.0/0.5/1.0 anchors), but none were executable. The guardian could not automatically verify whether the voice bar was hidden in chat mode, whether the progress bar replaced the case reference, or whether field confirmation changed the background color. These checks require browser automation.

#### Why Both Formats Are Needed

| Format | Purpose | Used By | Executable? |
|--------|---------|---------|-------------|
| `scenarios.feature` | Confidence scoring rubric | Guardian Phase 4 manual scoring | No — requires judgment |
| `executable-tests/` | Automated browser validation | tdd-test-engineer agent | Yes — deterministic pass/fail |

#### Output Structure

```
acceptance-tests/PRD-{ID}/
├── manifest.yaml              # (from Step 1)
├── scenarios.feature          # (from Step 1) — scoring rubric
├── journeys/                  # (from Step 2)
└── executable-tests/          # Browser automation test scripts
    ├── config.yaml            # Base URL, selectors, test data
    ├── S1-layout.yaml         # Executable version of S1.x scenarios
    ├── S2-mode-switching.yaml # Executable version of S2.x scenarios
    └── S3-form-panel.yaml     # Executable version of S3.x scenarios
```

#### Executable Test YAML Schema

Each test file maps Gherkin scenarios to claude-in-chrome MCP tool calls:

```yaml
test_group: S1-layout
prd_id: PRD-{ID}
base_url: "http://localhost:3000"
prerequisites:
  - frontend_running: true
  - route_exists: "/verify/test-task-123?mode=chat"

tests:
  - id: S1.1
    name: "Page header shows verification title at very top"
    steps:
      - tool: mcp__claude-in-chrome__navigate
        args:
          url: "${base_url}/verify/test-task-123?mode=chat"
      - tool: mcp__claude-in-chrome__get_page_text
        args: {}
        assert:
          contains: "Employment Verification"
      - tool: mcp__claude-in-chrome__find
        args:
          query: "h1, h2"
        assert:
          first_element_text_contains: "Employment Verification"
      - tool: mcp__claude-in-chrome__computer
        args:
          action: screenshot
        evidence: "s1-1-header.png"

  - id: S2.1
    name: "Chat mode does NOT show voice bar"
    steps:
      - tool: mcp__claude-in-chrome__navigate
        args:
          url: "${base_url}/verify/test-task-123?mode=chat"
      - tool: mcp__claude-in-chrome__javascript_tool
        args:
          javascript: |
            const voiceBar = document.querySelector('[data-testid="voice-bar"], [class*="speaking"], [class*="voice-controls"]');
            return { voiceBarVisible: voiceBar !== null && voiceBar.offsetHeight > 0 };
        assert:
          voiceBarVisible: false
      - tool: mcp__claude-in-chrome__find
        args:
          query: "input[type='text'], textarea"
        assert:
          found: true  # Chat input should exist in chat mode
```

#### Mapping Rules: Gherkin to MCP Tools

| Gherkin Pattern | MCP Tool | Assertion Type |
|-----------------|----------|----------------|
| "I navigate to {url}" | `navigate` | N/A |
| "the page shows {text}" | `get_page_text` | `contains: {text}` |
| "{element} is visible" | `find` or `javascript_tool` | `found: true` |
| "{element} is NOT visible" | `javascript_tool` (offsetHeight check) | `visible: false` |
| "I click {element}" | `find` + `computer` (click) | N/A |
| "I enter {value} in {field}" | `form_input` | N/A |
| "background changes to {color}" | `javascript_tool` (getComputedStyle) | `contains: {color}` |
| layout/CSS assertion | `javascript_tool` (grid/flex inspection) | custom assertion |
| screenshot capture | `computer` (screenshot) | evidence artifact |

#### Generation Process

For each feature group in `manifest.yaml` where `validation_method: browser-required`:

1. Read the corresponding Gherkin scenarios from `scenarios.feature`
2. Map each `Then` assertion to a specific `mcp__claude-in-chrome__*` tool call
3. Map each `When` action to a `navigate`, `form_input`, `find`, or `javascript_tool` call
4. Add `evidence` capture (screenshot) after each scenario's assertions
5. Include `assert` blocks with deterministic pass/fail conditions (not confidence scores)

#### Execution During Phase 4

These executable tests are run by a tdd-test-engineer agent during Phase 4 validation:

```python
Task(
    subagent_type="tdd-test-engineer",
    description="Execute browser automation tests for PRD-{ID}",
    prompt=f"""
    Execute the browser automation tests at: acceptance-tests/PRD-{prd_id}/executable-tests/

    For each test file:
    1. Read config.yaml for base URL and prerequisites
    2. Verify prerequisites (frontend running, routes accessible)
    3. Execute each test's steps sequentially using the specified MCP tools
    4. Evaluate assert blocks — deterministic PASS/FAIL per step
    5. Capture evidence screenshots to .claude/evidence/PRD-{prd_id}/
    6. Return executable-test-results.json with per-test pass/fail

    If frontend is not running, mark ALL tests as BLOCKED (not FAIL).
    """
)
```

#### Integration with Phase 4 Confidence Scoring

Executable test results serve as hard evidence for Phase 4 confidence scoring:

| Test Result | Impact on Confidence Score |
|-------------|---------------------------|
| **PASS** | Confidence floor of 0.7 for that scenario (evidence of working implementation) |
| **FAIL** | Confidence ceiling of 0.3 for that scenario (implementation has defects) |
| **BLOCKED** | No constraint on scoring (manual assessment still applies) |

This prevents the guardian from scoring a scenario at 0.9 based on code reading when the executable test shows the feature is actually broken in the browser.

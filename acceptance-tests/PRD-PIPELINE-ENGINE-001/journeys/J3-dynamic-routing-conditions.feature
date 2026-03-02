# Journey J3: Dynamic Routing via Condition Expressions (G3 + G5)
# Business objective: Edges route dynamically based on accumulated context
# Layers: @api (CLI) → @code (engine + condition evaluator + loop detector)

@journey @prd-PIPELINE-ENGINE-001 @J3 @api @code @smoke
Scenario J3: Condition expressions route execution and loop detection escalates

  # Setup: diamond node with conditional edges
  # TOOL: Bash
  Given a DOT pipeline with:
    | node      | shape   | edges                                              |
    | start     | Mdiamond| → impl                                             |
    | impl      | box     | → check (condition="$status = success")             |
    |           |         | → retry (condition="$retry_count < 3")              |
    |           |         | → fail_exit (default)                               |
    | check     | diamond | → exit_ok (condition="$test_coverage > 80")         |
    |           |         | → impl (condition="$test_coverage <= 80")           |
    | retry     | box     | → impl                                              |
    | exit_ok   | Msquare |                                                     |
    | fail_exit | Msquare |                                                     |

  # First pass: impl succeeds with high coverage → exit_ok
  # TOOL: Bash (CLI with mock handlers that set context)
  When mock handler for impl sets $status=success, $test_coverage=95
  And "cobuilder pipeline run <dot_file>" is run
  Then edge.selected events show: start→impl, impl→check, check→exit_ok
  And the pipeline completes via exit_ok

  # Second pass: impl succeeds with low coverage → loops back
  When mock handler for impl sets $status=success, $test_coverage=60
  And "cobuilder pipeline run <dot_file>" is run
  Then edge.selected events show impl→check→impl (loop back)
  And eventually loop.detected event is emitted when visit count exceeds max_retries

  # Loop detection escalation (G5)
  And ORCHESTRATOR_STUCK signal file is written
  And the pipeline exits with non-zero code and LoopDetectedError message

  # Confidence scoring guide:
  # 1.0 — Full conditional routing works. Loop detection triggers escalation.
  #        Both happy path and loop path demonstrated.
  # 0.5 — Conditions evaluate but loop detection doesn't escalate.
  # 0.0 — Conditions not evaluated; static edge selection only.

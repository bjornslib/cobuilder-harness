# Journey J1: Autonomous Pipeline Execution (G1 + G6 + G4)
# Business objective: DOT pipeline executes autonomously from start to exit
# Layers: @api (CLI invocation) → @code (engine execution) → @db (checkpoint files) → @async (logfire)

@journey @prd-PIPELINE-ENGINE-001 @J1 @api @code @db @smoke
Scenario J1: cobuilder pipeline run traverses a real DOT file from start to exit

  # Validation layer (G6: pre-execution validation)
  # TOOL: Bash (CLI invocation)
  Given a valid DOT pipeline file with start → codergen → exit nodes
  When "cobuilder pipeline validate <dot_file>" is run
  Then the CLI exits with code 0 and reports "No violations found" or "Warnings only"

  # Execution layer (G1: autonomous traversal)
  # TOOL: Bash (CLI invocation)
  When "cobuilder pipeline run <dot_file>" is run with mock handlers
  Then the engine parses the DOT file without errors

  # Checkpoint layer (G2: crash recovery)
  # TOOL: direct file system check
  And a checkpoint JSON file exists in the run directory after each node
  And the checkpoint contains completed_nodes, current_node_id, and context snapshot

  # Event layer (G4: structured events)
  # TOOL: direct file read (JSONL)
  And a pipeline-events.jsonl file exists with events for:
    | event type           |
    | pipeline.started     |
    | validation.completed |
    | node.started         |
    | node.completed       |
    | edge.selected        |
    | checkpoint.saved     |
    | pipeline.completed   |

  # Completion layer (G1: autonomous traversal)
  And the CLI exits with code 0
  And the final event is pipeline.completed with status=SUCCESS

  # Confidence scoring guide:
  # 1.0 — Full lifecycle: validate → parse → execute → checkpoint → events → exit 0.
  # 0.5 — Engine runs but missing events or checkpoints.
  # 0.0 — CLI command doesn't exist or engine fails to parse DOT.

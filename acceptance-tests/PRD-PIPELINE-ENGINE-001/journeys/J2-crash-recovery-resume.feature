# Journey J2: Crash Recovery via Checkpoint Resume (G2)
# Business objective: Engine resumes from last checkpoint after crash
# Layers: @api (CLI) → @code (engine) → @db (checkpoint files)

@journey @prd-PIPELINE-ENGINE-001 @J2 @api @code @db @smoke
Scenario J2: Engine resumes from checkpoint and skips completed nodes

  # Setup: run a pipeline that checkpoints after node 1 of 3
  # TOOL: Bash
  Given a 3-node DOT pipeline (start → nodeA → nodeB → exit) with mock handlers
  And a pre-existing checkpoint file with nodeA marked as completed
  And the checkpoint current_node_id is set to nodeB

  # Resume execution
  # TOOL: Bash
  When "cobuilder pipeline run <dot_file> --resume" is run
  Then the engine loads the checkpoint

  # Verification: skip completed, execute remaining
  # TOOL: direct file system check (JSONL events)
  And no node.started event is emitted for nodeA (skipped)
  And node.started event IS emitted for nodeB
  And the pipeline completes with pipeline.completed event

  # Verification: checkpoint integrity
  # TOOL: direct file read (JSON)
  And the final checkpoint contains all 3 nodes in completed_nodes
  And the CLI exits with code 0

  # Confidence scoring guide:
  # 1.0 — Resume loads checkpoint, skips completed, executes remaining, completes.
  # 0.5 — Resume works but re-executes completed nodes.
  # 0.0 — No --resume flag or checkpoint loading fails.

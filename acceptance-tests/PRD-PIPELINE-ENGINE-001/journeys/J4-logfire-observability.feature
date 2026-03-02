# Journey J4: Logfire Observability (G4)
# Business objective: Pipeline progress visible in Logfire dashboard
# Layers: @api (CLI) → @code (engine + middleware) → @async (Logfire)

@journey @prd-PIPELINE-ENGINE-001 @J4 @api @code @async
Scenario J4: Pipeline execution produces Logfire spans with full metadata

  # Execute pipeline with Logfire enabled
  # TOOL: Bash
  Given a 3-node DOT pipeline with Logfire configured
  When "cobuilder pipeline run <dot_file>" is run

  # Verify Logfire span hierarchy
  # TOOL: Logfire MCP (arbitrary_query)
  Then a pipeline-level span "pipeline.run" exists in Logfire
  And child spans "node.execute" exist for each executed node
  And node spans include attributes: node_id, handler_type, outcome_status

  # Verify middleware chain operated
  # TOOL: Logfire MCP or JSONL file
  And token counts are recorded in pipeline context as $tokens.<node_id>
  And audit entries are present in the JSONL event stream

  # Verify event-to-span correlation
  And PipelineEvent.span_id fields match Logfire span IDs

  # Confidence scoring guide:
  # 1.0 — Two-level Logfire hierarchy. Attributes on all spans. Token counting.
  #        span_id correlation between events and Logfire.
  # 0.5 — Logfire spans exist but flat or missing attributes.
  # 0.0 — No Logfire integration; only JSONL or print output.

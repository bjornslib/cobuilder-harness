# Agent-Legible Observability Guide

How agents query their own runtime behavior using Pydantic Logfire.

## Overview

Logfire provides OpenTelemetry-based observability for all agencheck services. Agents access Logfire data through the `logfire-mcp` MCP server, which exposes SQL queries over trace/span/log data collected automatically by the Logfire SDK (v4.17.0+).

## Available MCP Tools

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `find_exceptions_in_file` | Get recent exceptions for a specific file | Debugging a specific module |
| `arbitrary_query` | Run SQL against Logfire DataFusion database | Custom analysis, metrics, health checks |
| `logfire_link` | Generate a Logfire UI link for a trace | Sharing traces with humans |
| `schema_reference` | Get database schema (tables, columns, types) | Understanding available data |

## Setup

1. Generate a read-only API token from [Logfire Dashboard](https://logfire.pydantic.dev)
2. Set environment variable: `export LOGFIRE_READ_TOKEN=pylf_v1_...`
3. The MCP server is configured in `.mcp.json` and runs via `uvx logfire-mcp@latest`

## Common Query Patterns

### Find Recent Exceptions
```sql
SELECT exception_type, exception_message, service_name, start_timestamp
FROM records
WHERE exception_type IS NOT NULL
  AND start_timestamp > now() - interval '1 hour'
ORDER BY start_timestamp DESC
LIMIT 10
```

### Check Error Rate by Service
```sql
SELECT service_name,
       COUNT(CASE WHEN exception_type IS NOT NULL THEN 1 END) as errors,
       COUNT(*) as total,
       ROUND(100.0 * COUNT(CASE WHEN exception_type IS NOT NULL THEN 1 END) / COUNT(*), 2) as error_rate_pct
FROM records
WHERE start_timestamp > now() - interval '1 hour'
GROUP BY service_name
ORDER BY error_rate_pct DESC
```

### Detect Latency Regressions
```sql
SELECT span_name,
       AVG(duration) as avg_ms,
       MAX(duration) as max_ms,
       COUNT(*) as calls
FROM records
WHERE start_timestamp > now() - interval '1 hour'
  AND kind = 'SPAN'
GROUP BY span_name
HAVING AVG(duration) > 1000
ORDER BY avg_ms DESC
LIMIT 10
```

### Query Specific Service (e.g., eddy-validate)
```sql
SELECT span_name, message, start_timestamp, duration
FROM records
WHERE service_name = 'eddy-validate'
  AND start_timestamp > now() - interval '30 minutes'
ORDER BY start_timestamp DESC
LIMIT 20
```

## SQL Reference

The query engine is Apache DataFusion (Postgres-like syntax). Key points:
- Use `->` and `->>` operators for nested JSON fields in `attributes`
- Cast results as needed: `(attributes->'cost')::float`
- Efficient filters: `start_timestamp`, `service_name`, `span_name`, `trace_id`
- The `records` table contains both spans and logs

## Integration with Orchestrator Workflow

After deployment, orchestrators run a **Level 4: Deploy Health** check using Logfire queries. This is documented in the orchestrator-multiagent skill's VALIDATION.md (Level 4: Deploy Health — Logfire Observability section).

The workflow:
1. Deploy code changes
2. Wait 5-10 minutes for telemetry data
3. Query for new exceptions, latency regressions, error rate changes
4. If anomalies detected: create follow-up bug task before closing epic

## Using the Logfire Skill

Invoke via the MCP skills executor:

```bash
# Find exceptions
python .claude/skills/mcp-skills/executor.py --skill logfire --call '{
  "tool": "find_exceptions_in_file",
  "arguments": {"filepath": "main.py"}
}'

# Run custom SQL
python .claude/skills/mcp-skills/executor.py --skill logfire --call '{
  "tool": "arbitrary_query",
  "arguments": {"query": "SELECT ..."}
}'

# Get schema reference
python .claude/skills/mcp-skills/executor.py --skill logfire --call '{
  "tool": "schema_reference",
  "arguments": {}
}'
```

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |

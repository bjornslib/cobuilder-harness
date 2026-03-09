# Agent Schema Definition

This document defines the schema for agent configuration files located at `.claude/agents/*.md`.

## Agent Configuration File Format

Each agent configuration file must be a Markdown file with YAML frontmatter following this structure:

```yaml
---
name: agent-identifier
description: Brief description of the agent's purpose
model: model-identifier (sonnet, haiku, opus, inherit)
color: visual identifier for UI
title: "Display Title for the Agent"
status: active (or draft, deprecated)
skills_required: [skill1, skill2, ...]  # Optional list of required skills
---
```

## Worker Type Enum

The following values are valid for the `worker_type` field in pipeline configurations:

- `backend-solutions-engineer` - Specializes in Python backend systems, API development, database operations, PydanticAI agents, and MCP tool utilization
- `frontend-dev-expert` - Specializes in frontend development with modern web technologies, UI/UX implementation, and component architecture
- `tdd-test-engineer` - Specializes in Test-Driven Development practices for Python and React applications
- `solution-design-architect` - Creates comprehensive solution design documents, analyzes requirements, and plans implementation phases
- `ux-designer` - Specializes in UX audits, design concepts, and implementation briefs for frontend developers
- `validation-test-agent` - Runs tests against PRD acceptance criteria and validates implementations
- `claude-md-compliance-checker` - Verifies that all CLAUDE.md requirements, workflows, and best practices have been properly followed
- `linkedin-automation-agent` - Automates LinkedIn Sales Navigator workflows including list management, saved search operations, prospect research, and targeted outreach campaigns
- `doc-gardener` - Performs documentation quality checks, verifies cross-links, and ensures consistent naming conventions across documentation files
- `worker-tool-reference` - Provides comprehensive reference documentation for worker tools and their usage patterns

## Skills Injection

Agents can specify required skills in the `skills_required` field in the frontmatter. When an agent is dispatched, the system will automatically inject skill invocations for each skill listed in this field before the agent begins work.
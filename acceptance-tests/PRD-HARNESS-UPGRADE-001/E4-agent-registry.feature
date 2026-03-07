@epic-E4 @sd-HARNESS-UPGRADE-001-E4
Feature: Sub-Agent Registry + Skill Injection

  # Epic 4 creates a complete agent registry with all specialist sub-agent
  # definitions, skills_required in frontmatter, and skill injection into dispatch.
  # SD: docs/sds/harness-upgrade/SD-HARNESS-UPGRADE-001-E4-agent-registry.md

  @feature-F4.1 @weight-0.04
  Scenario: S4.1 — All 6 agent types have definition files with skills_required
    Given the .claude/agents/ directory exists
    When I list all .md files in .claude/agents/
    Then the following agent definition files exist:
      | File | Agent Type |
      | frontend-dev-expert.md | frontend-dev-expert |
      | backend-solutions-engineer.md | backend-solutions-engineer |
      | tdd-test-engineer.md | tdd-test-engineer |
      | solution-architect.md | solution-architect |
      | validation-test-agent.md | validation-test-agent |
      | ux-designer.md | ux-designer |
    And each file has YAML frontmatter with agent_type, title, model, tools_allowed, skills_required
    And each file has a Role section and Capabilities section
    And skills_required lists skills that exist in .claude/skills/

    # Confidence scoring guide:
    # 1.0 — All 6 files exist with standard format including skills_required in frontmatter
    # 0.5 — 4-5 files exist, or files exist but missing skills_required
    # 0.0 — Fewer than 4 agent definition files

    # Evidence to check:
    # - ls .claude/agents/*.md (count should be >= 6)
    # - Each file: check for YAML frontmatter with skills_required field
    # - Each skill in skills_required: verify .claude/skills/{skill}/ exists

    # Red flags:
    # - Agent files without skills_required in frontmatter
    # - compliance-researcher.md present (removed — was Could-Have)
    # - Skills referenced that don't exist in .claude/skills/

  @feature-F4.2 @weight-0.03
  Scenario: S4.2 — worker_type enum in agent-schema.md includes all 6 types
    Given the schema documentation exists (agent-schema.md)
    When I search for worker_type enum definition
    Then the enum lists all 6 agent types:
      - frontend-dev-expert
      - backend-solutions-engineer
      - tdd-test-engineer
      - solution-architect
      - validation-test-agent
      - ux-designer
    And each type has a brief description of its specialization
    And compliance-researcher is NOT in the enum

    # Confidence scoring guide:
    # 1.0 — All 6 types listed with descriptions, no compliance-researcher
    # 0.5 — 4-5 types listed, or types listed without descriptions
    # 0.0 — No worker_type enum in schema

  @feature-F4.3 @weight-0.05
  Scenario: S4.3 — dispatch_worker loads agent definition and injects skills
    Given dispatch_worker.py exists
    When I examine the dispatch or prompt-building functions
    Then the function:
      - Reads worker_type from node attributes
      - Resolves to .claude/agents/{worker_type}.md file path
      - Parses frontmatter to extract skills_required list
      - Injects Skill("name") invocations into the worker's initial prompt
      - Injects agent definition content as system prompt
    And if the agent definition file is not found:
      - Raises an error (AgentDefinitionNotFoundError or equivalent)
      - Does NOT silently fall back to a generic prompt

    # Confidence scoring guide:
    # 1.0 — Full integration: file resolution, skills parsing, injection, and error handling
    # 0.5 — File resolution works but skills injection missing or error handling absent
    # 0.0 — No integration between worker_type and agent definitions

    # Red flags:
    # - Silent fallback to generic prompt (hides misconfiguration)
    # - skills_required parsed but not injected into prompt
    # - Hardcoded skills instead of reading from frontmatter

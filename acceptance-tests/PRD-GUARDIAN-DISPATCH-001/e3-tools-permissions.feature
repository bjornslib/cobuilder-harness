Feature: E3 — Expanded allowed_tools and Permissions
  Guardian has proper tools and permission mode

  Scenario: Guardian has base tools
    Given guardian.py exists
    When I read build_options or the allowed_tools list
    Then allowed_tools contains: Bash, Read, Glob, Grep, ToolSearch, Skill, LSP
    And allowed_tools does NOT contain: Write, Edit, MultiEdit (coordinator, not implementer)
    # Scoring: 0.5 if Bash only, 0.8 if base tools, 1.0 if full set

  Scenario: Guardian has Serena tools
    Given guardian.py exists
    When I read the allowed_tools list
    Then it contains mcp__serena__find_symbol, mcp__serena__search_for_pattern, mcp__serena__get_symbols_overview
    # Scoring: 0.0 if no Serena, 1.0 if Serena tools present

  Scenario: Guardian has Hindsight tools
    Given guardian.py exists
    When I read the allowed_tools list
    Then it contains mcp__hindsight__retain, mcp__hindsight__recall, mcp__hindsight__reflect
    # Scoring: 0.0 if no Hindsight, 1.0 if Hindsight tools present

  Scenario: Permission mode is bypassPermissions
    Given guardian.py exists
    When I read build_options function
    Then permission_mode is set to "bypassPermissions"
    # Scoring: 0.0 if not set, 1.0 if bypassPermissions

Feature: E1 — ClaudeSDKClient Migration
  Guardian uses bidirectional ClaudeSDKClient instead of unidirectional query()

  Scenario: Guardian uses ClaudeSDKClient pattern
    Given guardian.py exists at cobuilder/engine/guardian.py
    When I read the _run_agent function
    Then it imports ClaudeSDKClient from claude_code_sdk
    And it uses "async with ClaudeSDKClient" pattern
    And it calls "client.connect()" before "client.query()"
    # Scoring: 0.0 if query() still used, 1.0 if ClaudeSDKClient used

  Scenario: Logfire instrumentation preserved
    Given guardian.py exists at cobuilder/engine/guardian.py
    When I read the _run_agent function
    Then logfire.info spans exist for: guardian.tool_use, guardian.assistant_text, guardian.thinking, guardian.tool_result
    And turn counting is preserved
    And tool_call_count is preserved
    # Scoring: 0.0 if any span missing, 1.0 if all preserved

  Scenario: Dry-run still works
    When I run "python3 cobuilder/engine/guardian.py --dot .pipelines/pipelines/hello-world-guardian-test.dot --pipeline-id test --dry-run"
    Then exit code is 0
    And output contains "system_prompt_length"
    # Scoring: 0.0 if fails, 1.0 if passes

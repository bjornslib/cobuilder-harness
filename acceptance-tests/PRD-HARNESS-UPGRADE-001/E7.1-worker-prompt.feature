@epic-E7.1 @sd-HARNESS-UPGRADE-001-E7.1
Feature: Worker Prompt Restructuring

  # Epic 7.1 reduces worker system prompt from 21K to ~3K chars and restructures
  # the initial prompt to be the primary task briefing.
  # SD: docs/sds/harness-upgrade/SD-HARNESS-UPGRADE-001-E7.1-worker-prompt.md
  # Evidence: Logfire traces showing 14/19 turns wasted on investigation

  @feature-F7.1.1 @weight-0.04
  Scenario: S7.1.1 — Worker system prompt under 4K characters
    Given runner.py has a build_system_prompt() or equivalent function
    When I measure the character count of the generated system prompt
    Then the total is under 4,000 characters (down from ~21,000)
    And the prompt contains:
      - Worker role statement
      - Tool allowlist (Read, Write, Edit, Grep, Glob, Bash)
      - Reference to worker-tool-reference.md for parameter details
      - Signal file write instruction ($ATTRACTOR_SIGNAL_DIR/{node_id}.json)
      - Concerns file instruction ($CONCERNS_FILE)
      - File scope constraint (only modify files in SD "Files Changed" section)
    And the prompt does NOT contain:
      - Pipeline orchestration documentation
      - Signal protocol multi-page instructions
      - Merge queue guidance
      - Architecture descriptions
      - Inline tool parameter examples (extracted to reference file)

    # Confidence scoring guide:
    # 1.0 — System prompt <4K, contains essentials, removes bloat (measured)
    # 0.5 — System prompt reduced but still >4K, or missing essential sections
    # 0.0 — System prompt unchanged from ~21K

    # Red flags:
    # - Pipeline orchestration docs still in system prompt
    # - Signal protocol instructions duplicated (should be in reference file)
    # - System prompt > 6K characters

  @feature-F7.1.2 @weight-0.04
  Scenario: S7.1.2 — Initial prompt contains PRD path, SD path, and AC
    Given runner.py has a build_initial_prompt() or equivalent function
    When I examine the generated initial prompt for a codergen node
    Then the prompt contains:
      - Task label from node
      - PRD reference path with epic section hint
      - SD reference path with key section hints ("2. Design", "3. Files Changed")
      - Acceptance criteria from DOT node attributes
      - Directive giving worker judgment on implementation details
      - Skill invocations from agent definition's skills_required
    And the initial prompt is the primary task briefing (~2K chars, not 697)

    # Confidence scoring guide:
    # 1.0 — All 6 sections present, prompt is the primary briefing
    # 0.5 — Some sections present but AC or SD path missing
    # 0.0 — Initial prompt still minimal (< 1K chars with just task label)

  @feature-F7.1.3 @weight-0.03
  Scenario: S7.1.3 — Tool reference file exists at standard path
    Given the .claude/agents/ directory exists
    When I check for worker-tool-reference.md
    Then the file exists at .claude/agents/worker-tool-reference.md
    And it contains:
      - Write tool example with file_path parameter (not "path")
      - Edit tool example with file_path, old_string, new_string (no replace_all)
      - Read tool example
      - Bash tool example with description parameter
      - Signal file JSON format with status, sd_hash, files_changed fields

    # Confidence scoring guide:
    # 1.0 — File exists with all 5 sections and correct parameter names
    # 0.5 — File exists but incomplete or wrong parameter names
    # 0.0 — No tool reference file

  @feature-F7.1.4 @weight-0.02
  Scenario: S7.1.4 — Guardian system prompt slimmed
    Given guardian.py has a build_system_prompt() or equivalent function
    When I examine the guardian system prompt
    Then it does NOT contain:
      - Worker-level tool guidance (Write/Edit examples)
      - Implementation examples
      - Worker signal file format
    And it DOES contain:
      - Guardian role (pipeline coordination)
      - DOT traversal reference
      - Gate processing guidance

    # Confidence scoring guide:
    # 1.0 — Guardian prompt has no worker-level content, keeps coordination guidance
    # 0.5 — Some worker content removed but not all
    # 0.0 — Guardian prompt unchanged

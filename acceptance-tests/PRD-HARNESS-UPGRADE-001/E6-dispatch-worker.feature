@epic-E6 @sd-HARNESS-UPGRADE-001-E6
Feature: Dispatch Worker Enhancements (SDK Mode)

  # Epic 6 improves worker dispatch with permission bypass, SD wiring,
  # skill injection, concern queues, and SD hash verification.
  # All dispatch paths use claude_code_sdk (_run_agent()), no tmux or headless CLI.
  # SD: docs/sds/harness-upgrade/SD-HARNESS-UPGRADE-001-E6-dispatch-worker.md

  @feature-F6.1 @weight-0.05
  Scenario: S6.1 — Workers run without MCP permission dialogs (bypassPermissions)
    Given dispatch_worker.py builds ClaudeCodeOptions for a worker
    When I examine the options configuration
    Then permission_mode is set to "bypassPermissions"
    And workers KEEP access to MCP tools (Perplexity, Context7, etc.)
    And running the worker does NOT trigger interactive permission dialogs on the host

    # Confidence scoring guide:
    # 1.0 — bypassPermissions in options, MCP tools available, no dialogs in E2E test
    # 0.5 — bypassPermissions in code but not E2E verified
    # 0.0 — Workers still trigger permission dialogs or MCP tools removed entirely

    # Evidence to check:
    # - dispatch_worker.py: search for "permission_mode" or "bypassPermissions"
    # - ClaudeCodeOptions construction
    # - E2E test: run pipeline, verify no permission prompts

    # Red flags:
    # - mcp_servers={} used instead (removes all MCP access — too aggressive)
    # - permission_mode not set at all
    # - Workers lose access to needed MCP tools like Perplexity/Context7

  @feature-F6.2 @weight-0.05
  Scenario: S6.2 — Workers receive real SD content in initial prompt
    Given a DOT pipeline with a codergen node that has sd_path="docs/sds/example.md"
    When dispatch_worker builds the worker's initial prompt
    Then the prompt contains the actual content of docs/sds/example.md
    And the prompt does NOT contain "No solution design provided" or "null"

    # Confidence scoring guide:
    # 1.0 — SD content fully inlined in prompt, verified with real pipeline
    # 0.5 — Code reads sd_path but doesn't inline content (passes path instead)
    # 0.0 — Workers still receive solution_design: null

  @feature-F6.3 @weight-0.04
  Scenario: S6.3 — Skill invocations injected from agent definition
    Given a codergen node with worker_type="frontend-dev-expert"
    And .claude/agents/frontend-dev-expert.md has skills_required: [react-best-practices, frontend-design]
    When dispatch_worker builds the worker's initial prompt
    Then the prompt contains skill invocations:
      - Skill("react-best-practices")
      - Skill("frontend-design")
    And the skills section appears before the implementation directive

    # Confidence scoring guide:
    # 1.0 — Skills parsed from frontmatter and injected into initial prompt correctly
    # 0.5 — Skills injected but from hardcoded list instead of frontmatter
    # 0.0 — No skill injection in worker prompt

    # Red flags:
    # - Skills hardcoded in dispatch_worker instead of read from agent definition
    # - skills_required field ignored
    # - Skills injected into system prompt instead of initial prompt

  @feature-F6.4 @weight-0.03
  Scenario: S6.4 — ATTRACTOR_SIGNAL_DIR and CONCERNS_FILE env vars set
    Given dispatch_worker spawns a worker via SDK
    When I examine the environment passed to the worker
    Then ATTRACTOR_SIGNAL_DIR is set to the pipeline's signal directory
    And CONCERNS_FILE is set to {signal_dir}/concerns.jsonl
    And both values match the directories where the runner polls

    # Confidence scoring guide:
    # 1.0 — Both env vars set and match runner's expected paths
    # 0.5 — One env var set but not both, or values may not match
    # 0.0 — No signal/concerns env vars

  @feature-F6.5 @weight-0.02
  Scenario: S6.5 — Signal evidence includes sd_hash
    Given a worker completes execution and writes a signal file
    When I examine the signal JSON
    Then it contains an "sd_hash" field
    And the value is a SHA256 hash (hexadecimal, 16+ characters)
    And the hash matches the SHA256 of the SD content that was provided to the worker

    # Confidence scoring guide:
    # 1.0 — sd_hash present, correct SHA256, matches provided SD
    # 0.5 — sd_hash present but not verified against actual SD content
    # 0.0 — No sd_hash in signal evidence

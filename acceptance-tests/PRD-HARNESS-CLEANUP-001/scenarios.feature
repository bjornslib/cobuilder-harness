# PRD-HARNESS-CLEANUP-001: Claude Harness Repository Cleanup
# Blind acceptance tests — meta-orchestrators MUST NOT see this file

# ============================================================================
# EPIC 1: Gitignore Updates (weight: 0.30)
# ============================================================================

@feature-gitignore_updates @weight-0.30
Feature: Gitignore patterns prevent artifact accumulation

  Background:
    Given the repository root is at "claude-harness-setup"
    And the working directory is the repository root

  @scenario-claude_gitignore_checkpoint_pattern
  Scenario: .claude/.gitignore ignores attractor checkpoint files
    When I read ".claude/.gitignore"
    Then it contains a line matching "attractor/pipelines/\*-checkpoint-\*.json"

    # Confidence scoring guide:
    # 1.0 — Pattern present and verified to match existing checkpoint filenames
    # 0.5 — A checkpoint-related pattern exists but uses different glob syntax
    # 0.0 — No checkpoint pattern in .claude/.gitignore

    # Evidence to check:
    # - cat .claude/.gitignore | grep checkpoint
    # - Verify pattern matches filenames like: attractor-engine-checkpoint-20260224-104514.json
    # - git check-ignore -v .claude/attractor/pipelines/attractor-engine-checkpoint-20260224-104514.json

    # Red flags:
    # - Pattern uses a leading slash that prevents subdirectory matching
    # - Pattern only matches a specific pipeline name (not wildcard)
    # - .gitignore exists but checkpoint entry is commented out

  @scenario-claude_gitignore_signals_pattern
  Scenario: .claude/.gitignore ignores attractor signals directory
    When I read ".claude/.gitignore"
    Then it contains a line matching "attractor/pipelines/signals/"

    # Confidence scoring guide:
    # 1.0 — Pattern present; git check-ignore confirms signals/ is ignored
    # 0.5 — Pattern present but missing trailing slash (files-only match)
    # 0.0 — No signals pattern in .claude/.gitignore

    # Evidence to check:
    # - cat .claude/.gitignore | grep signals
    # - git check-ignore -v .claude/attractor/pipelines/signals/

    # Red flags:
    # - Pattern "signals" without path context could match unrelated signal files
    # - Pattern added to root .gitignore instead of .claude/.gitignore

  @scenario-claude_gitignore_runner_state_pattern
  Scenario: .claude/.gitignore ignores attractor runner-state directory
    When I read ".claude/.gitignore"
    Then it contains a line matching "attractor/runner-state/"

    # Confidence scoring guide:
    # 1.0 — Pattern present; directory confirmed gitignored
    # 0.5 — Similar pattern present with different path structure
    # 0.0 — No runner-state pattern in .claude/.gitignore

    # Evidence to check:
    # - cat .claude/.gitignore | grep runner-state
    # - git check-ignore -v .claude/attractor/runner-state/

    # Red flags:
    # - Only runner-state files ignored, not the directory itself

  @scenario-claude_gitignore_checkpoints_dir_pattern
  Scenario: .claude/.gitignore ignores attractor checkpoints directory
    When I read ".claude/.gitignore"
    Then it contains a line matching "attractor/checkpoints/"

    # Confidence scoring guide:
    # 1.0 — Pattern present and confirmed to suppress .claude/attractor/checkpoints/
    # 0.5 — Pattern "checkpoints/" present but anchored incorrectly
    # 0.0 — No checkpoints directory pattern in .claude/.gitignore

    # Evidence to check:
    # - cat .claude/.gitignore | grep "checkpoints/"
    # - git check-ignore -v .claude/attractor/checkpoints/
    # - Note: distinct from attractor/pipelines/*-checkpoint-*.json (individual file pattern)

    # Red flags:
    # - Pattern conflicts with the checkpoint file pattern (double-coverage causing confusion)
    # - Pattern missing from .claude/.gitignore but present only in root .gitignore

  @scenario-claude_gitignore_session_state_pattern
  Scenario: .claude/.gitignore ignores completion-state session-state.json
    When I read ".claude/.gitignore"
    Then it contains a line matching "completion-state/session-state.json"

    # Confidence scoring guide:
    # 1.0 — Pattern present; git check-ignore confirms .claude/completion-state/session-state.json is ignored
    # 0.5 — completion-state/ directory is fully ignored (broader than required but acceptable)
    # 0.0 — No session-state.json pattern present

    # Evidence to check:
    # - cat .claude/.gitignore | grep session-state
    # - git check-ignore -v .claude/completion-state/session-state.json

    # Red flags:
    # - Pattern ignores all of completion-state/ preventing other files from being tracked

  @scenario-claude_gitignore_evidence_pattern
  Scenario: .claude/.gitignore ignores evidence directory with .gitkeep exception
    When I read ".claude/.gitignore"
    Then it contains a line matching "evidence/\*"
    And it contains a line matching "!evidence/.gitkeep"

    # Confidence scoring guide:
    # 1.0 — Both patterns present; evidence/* ignored, .gitkeep tracked
    # 0.7 — evidence/* present but no !evidence/.gitkeep exception
    # 0.5 — evidence/ directory fully ignored (loses .gitkeep tracking)
    # 0.0 — No evidence pattern in .claude/.gitignore

    # Evidence to check:
    # - cat .claude/.gitignore | grep evidence
    # - git check-ignore -v .claude/evidence/pr-213/ (should be ignored)
    # - git ls-files .claude/evidence/.gitkeep (should be tracked)

    # Red flags:
    # - !evidence/.gitkeep negation comes BEFORE evidence/* (wrong order — Git processes top-to-bottom)
    # - evidence/ (directory ignore) used instead of evidence/* (prevents negation from working)

  @scenario-claude_gitignore_prototypes_pattern
  Scenario: .claude/.gitignore ignores scripts/prototypes directory
    When I read ".claude/.gitignore"
    Then it contains a line matching "scripts/prototypes/"

    # Confidence scoring guide:
    # 1.0 — Pattern present and confirmed to suppress .claude/scripts/prototypes/
    # 0.5 — Pattern "prototypes/" present without path context
    # 0.0 — No prototypes pattern in .claude/.gitignore

    # Evidence to check:
    # - cat .claude/.gitignore | grep prototypes
    # - git check-ignore -v .claude/scripts/prototypes/

    # Red flags:
    # - Pattern "prototypes" matches too broadly (e.g., prototype.py in other dirs)

  @scenario-root_gitignore_serena_pattern
  Scenario: Root .gitignore ignores .serena directory
    When I read ".gitignore"
    Then it contains a line matching ".serena/"

    # Confidence scoring guide:
    # 1.0 — Pattern present; git check-ignore confirms .serena/ is ignored
    # 0.5 — Pattern ".serena" present without trailing slash
    # 0.0 — No .serena pattern in root .gitignore

    # Evidence to check:
    # - cat .gitignore | grep serena
    # - git check-ignore -v .serena/

    # Red flags:
    # - Pattern added to .claude/.gitignore instead of root .gitignore

  @scenario-root_gitignore_zerorepo_pattern
  Scenario: Root .gitignore ignores .zerorepo directory
    When I read ".gitignore"
    Then it contains a line matching ".zerorepo/"

    # Confidence scoring guide:
    # 1.0 — Pattern present; git check-ignore confirms .zerorepo/ is ignored
    # 0.5 — Pattern ".zerorepo" present without trailing slash
    # 0.0 — No .zerorepo pattern in root .gitignore

    # Evidence to check:
    # - cat .gitignore | grep zerorepo
    # - git check-ignore -v .zerorepo/

    # Red flags:
    # - .zerorepo/ contents show up in git status as untracked

  @scenario-root_gitignore_trees_pattern
  Scenario: Root .gitignore ignores trees directory
    When I read ".gitignore"
    Then it contains a line matching "trees/"

    # Confidence scoring guide:
    # 1.0 — Pattern present; git check-ignore confirms trees/ is ignored
    # 0.5 — Pattern "trees" present without trailing slash
    # 0.0 — No trees pattern in root .gitignore

    # Evidence to check:
    # - cat .gitignore | grep "^trees"
    # - git check-ignore -v trees/

    # Red flags:
    # - Pattern is too broad and ignores subdirectory named "trees" inside other directories

  @scenario-root_gitignore_completion_state_pattern
  Scenario: Root .gitignore ignores root-level completion-state directory
    When I read ".gitignore"
    Then it contains a line matching "completion-state/"

    # Confidence scoring guide:
    # 1.0 — Pattern present at root .gitignore; root completion-state/ confirmed ignored
    # 0.5 — Pattern present but also suppresses .claude/completion-state/ (overly broad)
    # 0.0 — No completion-state pattern in root .gitignore

    # Evidence to check:
    # - cat .gitignore | grep completion-state
    # - git check-ignore -v completion-state/
    # - Note: .claude/.gitignore has a separate session-state.json rule for .claude/completion-state/

    # Red flags:
    # - Pattern uses leading slash (only matches root but won't help if path changes)

  @scenario-root_gitignore_settings_local_pattern
  Scenario: Root .gitignore ignores settings.local.json
    When I read ".gitignore"
    Then it contains a line matching "settings.local.json"

    # Confidence scoring guide:
    # 1.0 — Pattern present; git check-ignore confirms settings.local.json is ignored
    # 0.5 — Pattern "*.local.json" or "*.local.*" present (broader, still acceptable)
    # 0.0 — No settings.local.json pattern in root .gitignore

    # Evidence to check:
    # - cat .gitignore | grep settings.local
    # - git check-ignore -v settings.local.json

    # Red flags:
    # - settings.local.json still appears in git status as untracked after pattern added

  @scenario-root_gitignore_test_file_pattern
  Scenario: Root .gitignore ignores root test file
    When I read ".gitignore"
    Then it contains a line matching the bare filename "test"

    # Confidence scoring guide:
    # 1.0 — Pattern present; root test file confirmed ignored (or already deleted)
    # 0.5 — Pattern "/test" present (anchored correctly) but file already deleted
    # 0.0 — No test pattern in root .gitignore

    # Evidence to check:
    # - cat .gitignore | grep "^/test\|^test$"
    # - git check-ignore -v test
    # - Note: "test" bare entry may conflict with test directories; anchoring with /test preferred

    # Red flags:
    # - Pattern "test" without anchoring accidentally ignores directories named "test"
    # - Entry added to .claude/.gitignore instead of root .gitignore


# ============================================================================
# EPIC 2: File Cleanup (weight: 0.25)
# ============================================================================

@feature-file_cleanup @weight-0.25
Feature: Artifact files removed and placeholder files in place

  @scenario-root_test_file_deleted
  Scenario: Root-level empty test file is deleted
    Then the file "test" should not exist at the repository root

    # Confidence scoring guide:
    # 1.0 — File absent; git log confirms it was removed or never tracked
    # 0.5 — File absent but no git history (was never committed, just deleted)
    # 0.0 — File still present at repository root

    # Evidence to check:
    # - ls -la test (should return "No such file or directory")
    # - git status | grep "^?? test" (should produce no output)

    # Red flags:
    # - File was moved to another location rather than deleted
    # - git rm was not used (file removed from disk but still staged as deleted)

  @scenario-checkpoint_files_cleaned
  Scenario: Checkpoint JSON files in attractor pipelines directory are cleaned up
    When I count JSON files matching "*-checkpoint-*.json" in ".claude/attractor/pipelines/"
    Then zero checkpoint files remain
    Or all remaining checkpoint files are already gitignored

    # Confidence scoring guide:
    # 1.0 — Zero checkpoint files remain on disk (cleaned up entirely)
    # 0.7 — Checkpoint files remain but all are confirmed gitignored
    # 0.5 — Some checkpoint files removed but a few remain and are untracked
    # 0.0 — All original checkpoint files still present and untracked

    # Evidence to check:
    # - find .claude/attractor/pipelines/ -name "*-checkpoint-*.json" | wc -l
    # - git status .claude/attractor/pipelines/ (should show no untracked checkpoint files)
    # - If files remain: git check-ignore -v .claude/attractor/pipelines/<name>.json

    # Red flags:
    # - Checkpoint files deleted but gitignore pattern not added (will re-accumulate)
    # - Only a subset of pipelines cleaned (e.g., attractor-engine but not cleanup-001)

  @scenario-evidence_gitkeep_present
  Scenario: .gitkeep file present in evidence directory
    Then the file ".claude/evidence/.gitkeep" should exist
    And ".claude/evidence/.gitkeep" should be tracked by git

    # Confidence scoring guide:
    # 1.0 — .gitkeep exists and is in git index (git ls-files confirms)
    # 0.5 — .gitkeep exists on disk but not committed to git
    # 0.0 — No .gitkeep in evidence/ directory

    # Evidence to check:
    # - ls .claude/evidence/.gitkeep
    # - git ls-files .claude/evidence/.gitkeep (should return the path)

    # Red flags:
    # - evidence/ directory itself is missing
    # - Evidence subdirectories (pr-213/, pr-214/, etc.) still show as untracked

  @scenario-attractor_checkpoints_gitkeep_present
  Scenario: .gitkeep file present in attractor checkpoints directory
    Then the file ".claude/attractor/checkpoints/.gitkeep" should exist
    And ".claude/attractor/checkpoints/.gitkeep" should be tracked by git

    # Confidence scoring guide:
    # 1.0 — .gitkeep exists and is tracked by git
    # 0.5 — .gitkeep exists on disk but not added to git
    # 0.0 — No .gitkeep in attractor/checkpoints/

    # Evidence to check:
    # - ls .claude/attractor/checkpoints/.gitkeep
    # - git ls-files .claude/attractor/checkpoints/.gitkeep

    # Red flags:
    # - Directory does not exist at all
    # - .gitkeep committed but directory still shows as untracked in git status

  @scenario-attractor_runner_state_gitkeep_present
  Scenario: .gitkeep file present in attractor runner-state directory
    Then the file ".claude/attractor/runner-state/.gitkeep" should exist
    And ".claude/attractor/runner-state/.gitkeep" should be tracked by git

    # Confidence scoring guide:
    # 1.0 — .gitkeep exists and is tracked by git
    # 0.5 — .gitkeep exists on disk but not committed
    # 0.0 — No .gitkeep in attractor/runner-state/

    # Evidence to check:
    # - ls .claude/attractor/runner-state/.gitkeep
    # - git ls-files .claude/attractor/runner-state/.gitkeep

    # Red flags:
    # - runner-state directory missing entirely

  @scenario-attractor_signals_gitkeep_present
  Scenario: .gitkeep file present in attractor pipeline signals directory
    Then the file ".claude/attractor/pipelines/signals/.gitkeep" should exist
    And ".claude/attractor/pipelines/signals/.gitkeep" should be tracked by git

    # Confidence scoring guide:
    # 1.0 — .gitkeep exists and is tracked by git
    # 0.5 — .gitkeep exists on disk but not committed
    # 0.0 — No .gitkeep in attractor/pipelines/signals/

    # Evidence to check:
    # - ls .claude/attractor/pipelines/signals/.gitkeep
    # - git ls-files .claude/attractor/pipelines/signals/.gitkeep

    # Red flags:
    # - signals/ directory missing (not created during cleanup)
    # - Actual signal files still present alongside .gitkeep


# ============================================================================
# EPIC 3: Track Untracked Documentation (weight: 0.15)
# ============================================================================

@feature-track_documentation @weight-0.15
Feature: Documentation files are tracked in git

  @scenario-architecture_article_tracked
  Scenario: ARCHITECTURE-ARTICLE.md is tracked in git
    Then the file ".claude/documentation/ARCHITECTURE-ARTICLE.md" should exist
    And ".claude/documentation/ARCHITECTURE-ARTICLE.md" should be tracked by git

    # Confidence scoring guide:
    # 1.0 — File exists and git ls-files confirms it is tracked
    # 0.5 — File exists on disk but not yet committed (staged only)
    # 0.0 — File absent or still shows as untracked in git status

    # Evidence to check:
    # - git ls-files .claude/documentation/ARCHITECTURE-ARTICLE.md (must return path)
    # - git log --oneline .claude/documentation/ARCHITECTURE-ARTICLE.md (shows commits)
    # - git status | grep ARCHITECTURE-ARTICLE.md (should produce no output)

    # Red flags:
    # - File is gitignored by a .claude/.gitignore documentation/ pattern
    # - File was added to git index but the commit was not made

  @scenario-solution_design_tracked
  Scenario: SOLUTION-DESIGN-P11-DEPLOY-001.md is tracked in git
    Then the file ".claude/documentation/SOLUTION-DESIGN-P11-DEPLOY-001.md" should exist
    And ".claude/documentation/SOLUTION-DESIGN-P11-DEPLOY-001.md" should be tracked by git

    # Confidence scoring guide:
    # 1.0 — File exists and git ls-files confirms it is tracked
    # 0.5 — File staged but not committed
    # 0.0 — File absent or untracked

    # Evidence to check:
    # - git ls-files .claude/documentation/SOLUTION-DESIGN-P11-DEPLOY-001.md
    # - git status | grep SOLUTION-DESIGN (should produce no output)

    # Red flags:
    # - File name truncated or renamed during git add
    # - File moved to wrong directory (e.g., root documentation/)

  @scenario-sdk_cli_tools_ref_deleted
  Scenario: sdk-cli-tools.md stale reference file has been deleted
    Then the file ".claude/skills/s3-guardian/references/sdk-cli-tools.md" should NOT exist
    And git should NOT track ".claude/skills/s3-guardian/references/sdk-cli-tools.md"

    # Context: This file referenced launch_guardian.py, guardian_agent.py, runner_agent.py
    # which were deleted in the PR #29 destructive merge. It was stale and removed in the
    # harness context reduction cleanup (plan: fluttering-sniffing-forest).
    #
    # Confidence scoring guide:
    # 1.0 — File absent and git ls-files returns nothing for it
    # 0.5 — File staged as deleted but not yet committed
    # 0.0 — File still exists on disk

    # Evidence to check:
    # - ls .claude/skills/s3-guardian/references/sdk-cli-tools.md (should fail)
    # - git ls-files .claude/skills/s3-guardian/references/sdk-cli-tools.md (should return empty)

  @scenario-sdk_mode_ref_deleted
  Scenario: sdk-mode.md stale reference file has been deleted
    Then the file ".claude/skills/s3-guardian/references/sdk-mode.md" should NOT exist
    And git should NOT track ".claude/skills/s3-guardian/references/sdk-mode.md"

    # Context: This file described the 4-layer SDK chain using old script names
    # (launch_guardian.py, guardian_agent.py) deleted in PR #29. Stale, removed in cleanup.
    #
    # Confidence scoring guide:
    # 1.0 — File absent and git ls-files returns nothing for it
    # 0.5 — File staged as deleted but not yet committed
    # 0.0 — File still exists on disk

    # Evidence to check:
    # - ls .claude/skills/s3-guardian/references/sdk-mode.md (should fail)
    # - git ls-files .claude/skills/s3-guardian/references/sdk-mode.md (should return empty)


# ============================================================================
# EPIC 4: Acceptance Test Consolidation (weight: 0.15)
# ============================================================================

@feature-acceptance_test_consolidation @weight-0.15
Feature: Acceptance tests consolidated to a single location

  @scenario-consolidation_decision_documented
  Scenario: Decision on acceptance test location is documented
    Then there exists evidence of a documented decision selecting either:
      - root "acceptance-tests/" as the canonical location
      - Or ".claude/acceptance-tests/" as the canonical location
    And the CLAUDE.md or a documentation file references the chosen location

    # Confidence scoring guide:
    # 1.0 — Decision documented in CLAUDE.md or ADR file; canonical path clearly stated
    # 0.5 — Tests exist in one location without explicit documentation of the decision
    # 0.0 — Tests scattered across multiple locations with no documented decision

    # Evidence to check:
    # - grep -r "acceptance-tests" CLAUDE.md .claude/CLAUDE.md (check for canonical reference)
    # - ls acceptance-tests/ (should be the primary location based on current state)
    # - ls .claude/acceptance-tests/ (should not exist, or all contents moved to root)

    # Red flags:
    # - acceptance-tests/ directories exist at both root and .claude/ with different content
    # - Decision contradicts the actual file layout

  @scenario-single_acceptance_test_location
  Scenario: All acceptance tests reside in one canonical directory
    When I list all directories named "acceptance-tests" in the repository
    Then exactly one directory contains acceptance test content
    And that directory is the canonical location from AC-4.1

    # Confidence scoring guide:
    # 1.0 — One canonical location; all PRD/scenario .feature files in that tree
    # 0.5 — One primary location but empty stub directory at the other path
    # 0.0 — Feature files split across root acceptance-tests/ and .claude/acceptance-tests/

    # Evidence to check:
    # - find . -name "*.feature" -not -path "./.git/*" | cut -d/ -f2 | sort -u
    # - Verify all .feature files share a common top-level parent

    # Red flags:
    # - acceptance-tests/ at both root and .claude/ each contain unique .feature files
    # - Some PRD directories exist at one location and newer ones at the other

  @scenario-acceptance_test_gitignore_updated
  Scenario: Gitignore updated for canonical acceptance test location
    When I read the gitignore file governing the canonical acceptance-tests/ location
    Then a pattern exists that keeps acceptance-tests/ tracked (not ignored)
    Or the canonical location has no blocking gitignore pattern

    # Confidence scoring guide:
    # 1.0 — No gitignore pattern blocks acceptance-tests/ from being tracked
    # 0.5 — Pattern exists but only ignores generated output files (not scenarios)
    # 0.0 — acceptance-tests/ is inadvertently ignored or has conflicting patterns

    # Evidence to check:
    # - git check-ignore -v acceptance-tests/ (should produce no output if tracked)
    # - git ls-files acceptance-tests/ | head -5 (should return files)

    # Red flags:
    # - acceptance-tests/ appears in .gitignore from a prior broad ignore rule
    # - New PRD acceptance test directories added after cleanup still show as untracked


# ============================================================================
# EPIC 5: Verification (weight: 0.15)
# ============================================================================

@feature-verification @weight-0.15
Feature: Repository in clean verified state after cleanup

  @scenario-clean_git_status
  Scenario: git status shows no untracked files that should be ignored
    When I run "git status --short"
    Then no lines begin with "??" for files covered by the new gitignore patterns
    Specifically the following should NOT appear as untracked:
      | path pattern                                     |
      | .claude/attractor/pipelines/*-checkpoint-*.json  |
      | .claude/attractor/pipelines/signals/             |
      | .claude/attractor/runner-state/                  |
      | .claude/attractor/checkpoints/                   |
      | .claude/completion-state/session-state.json      |
      | .claude/evidence/pr-*/                           |
      | .claude/scripts/prototypes/                      |
      | .serena/                                         |
      | .zerorepo/                                       |
      | trees/                                           |
      | completion-state/                                |
      | settings.local.json                              |

    # Confidence scoring guide:
    # 1.0 — None of the listed paths appear as untracked in git status
    # 0.7 — 1-2 paths still appear as untracked (partial gitignore coverage)
    # 0.5 — Half of the listed paths are properly ignored
    # 0.2 — Gitignore patterns added but artifacts not cleaned so status still shows items
    # 0.0 — git status shows the same untracked files as before the cleanup

    # Evidence to check:
    # - git status --short | grep "^??"
    # - Compare against pre-cleanup git status (reference: gitStatus in conversation)
    # - git check-ignore -v <path> for each item still appearing as untracked

    # Red flags:
    # - git status clean only because untracked files were git-added (not ignored)
    # - New artifacts generated after cleanup immediately reappear as untracked

  @scenario-newly_generated_artifacts_gitignored
  Scenario: Newly generated artifacts are properly gitignored after cleanup
    Given the gitignore patterns have been applied
    When a new checkpoint file is created at ".claude/attractor/pipelines/test-checkpoint-20260225-120000.json"
    Then "git status" does NOT show the new file as untracked
    When a new signal file is created at ".claude/attractor/pipelines/signals/test.signal"
    Then "git status" does NOT show the new signal file as untracked

    # Confidence scoring guide:
    # 1.0 — Both test artifacts are gitignored immediately upon creation
    # 0.7 — Checkpoint ignored but signals not (or vice versa)
    # 0.5 — Pattern exists but has wrong glob syntax so new files still appear
    # 0.0 — New artifacts still appear as untracked (patterns not working)

    # Evidence to check:
    # - touch .claude/attractor/pipelines/test-checkpoint-20260225-120000.json
    # - git status | grep test-checkpoint (should produce no output)
    # - touch .claude/attractor/pipelines/signals/test.signal
    # - git status | grep test.signal (should produce no output)
    # - Clean up test files after verification

    # Red flags:
    # - Gitignore patterns only matched existing filenames (not generalized globs)
    # - Pattern anchored to a specific date component that won't match future timestamps

  @scenario-tests_pass
  Scenario: Attractor test suite passes after cleanup
    When I run "pytest .claude/scripts/attractor/tests/ -x -q"
    Then the exit code is 0
    And all tests that were passing before cleanup still pass

    # Confidence scoring guide:
    # 1.0 — All tests pass with zero failures or errors
    # 0.5 — Tests pass but with new skips or warnings not present before cleanup
    # 0.0 — Any test failure or error

    # Evidence to check:
    # - pytest .claude/scripts/attractor/tests/ -x -q (run directly)
    # - Check test count matches pre-cleanup baseline
    # - pytest --tb=short for any failures

    # Red flags:
    # - Tests pass only because cleanup deleted test fixtures that tests depended on
    # - Import errors caused by moved or deleted files in .claude/scripts/

  @scenario-deploy_harness_succeeds
  Scenario: Harness deploy to target repositories succeeds after cleanup
    Given the harness deploy script exists and is configured
    When the deploy script is executed targeting a clean repository
    Then the deploy completes without errors
    And the target repository receives all expected harness files
    And no runtime artifact files (checkpoint, signals, session-state) are deployed

    # Confidence scoring guide:
    # 1.0 — Deploy succeeds; target has harness files but no runtime artifacts
    # 0.7 — Deploy succeeds but deploys some gitignored artifacts to target (unintended)
    # 0.5 — Deploy script runs but reports warnings or partial failure
    # 0.0 — Deploy fails with errors

    # Evidence to check:
    # - Identify deploy script location (e.g., .claude/scripts/deploy-harness.sh)
    # - Run deploy against a test target directory
    # - ls target/.claude/attractor/pipelines/*-checkpoint-*.json (should find nothing)
    # - Confirm target/.claude/.gitignore contains the new patterns

    # Red flags:
    # - Deploy copies .claude/ verbatim including all runtime state
    # - Deploy overwrites target's existing .gitignore instead of merging patterns
    # - Attractor checkpoint files or evidence/ subdirectories appear in deploy output

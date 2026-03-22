# Claude Code Hook Tests

This directory contains the acceptance test suite for Claude Code hooks, particularly the Post-Push Code Review Hook infrastructure.

## Overview

Tests are organized following TDD (Test-Driven Development) principles:
- **RED Phase**: Tests written first, before implementation (current state)
- **GREEN Phase**: Implementation added to make tests pass
- **REFACTOR Phase**: Code improved while keeping tests green

## Directory Structure

```
.claude/tests/hooks/
├── README.md                           # This file
├── conftest.py                         # Shared pytest fixtures
├── test_post_push_detection.py         # AC-1 to AC-3 test specifications
└── fixtures/
    ├── push_success_github_main.json   # AC-1: Successful push to GitHub main
    ├── push_success_github_new_branch.json  # AC-1: New branch push
    ├── push_success_gitlab.json        # AC-1: GitLab push
    ├── bash_ls.json                    # AC-2: Non-push command (ls)
    ├── bash_git_status.json            # AC-2: Non-push command (git status)
    ├── bash_git_commit.json            # AC-2: Non-push command (git commit)
    ├── bash_npm_run.json               # AC-2: Non-push command (npm run)
    ├── push_everything_up_to_date.json # AC-3: No new commits
    ├── push_auth_failed.json           # AC-3: Authentication failure
    ├── push_rejected.json              # AC-3: Push rejected
    ├── push_error.json                 # AC-3: General error
    └── push_remote_rejected.json       # AC-3: Remote hook declined
```

## Running Tests

### Prerequisites

```bash
# Install pytest if not already installed
pip install pytest

# Navigate to project root
cd ~/projects/my-project
```

### Run All Hook Tests

```bash
pytest .claude/tests/hooks/ -v
```

### Run Specific Test Class

```bash
# AC-1: Push Success Detection
pytest .claude/tests/hooks/test_post_push_detection.py::TestAC1_HookTriggersOnPushSuccess -v

# AC-2: Non-Push Commands Ignored
pytest .claude/tests/hooks/test_post_push_detection.py::TestAC2_HookIgnoresNonPushCommands -v

# AC-3: Failed Pushes Ignored
pytest .claude/tests/hooks/test_post_push_detection.py::TestAC3_HookIgnoresFailedPushes -v
```

### Run Integration Tests (After Implementation)

```bash
# Unskip and run integration tests
pytest .claude/tests/hooks/test_post_push_detection.py::TestHookIntegration -v --run-skip
```

## Acceptance Criteria Tested

### AC-1: Hook Triggers on Git Push Success

**Fixtures**: `push_success_*.json`

| Test | Description |
|------|-------------|
| `test_detects_github_main_push` | Detects push to GitHub main branch |
| `test_detects_github_new_branch_push` | Detects new branch creation on GitHub |
| `test_detects_gitlab_push` | Detects push to GitLab |

**Success Patterns**:
- Host: `To github.com:` or `To gitlab.com:`
- Branch: `main -> main` or `[new branch]`

### AC-2: Hook Ignores Non-Push Commands

**Fixtures**: `bash_*.json`

| Test | Description |
|------|-------------|
| `test_ignores_ls_command` | Does not trigger on `ls -la` |
| `test_ignores_git_status` | Does not trigger on `git status` |
| `test_ignores_git_commit` | Does not trigger on `git commit` |
| `test_ignores_npm_run` | Does not trigger on `npm run build` |

### AC-3: Hook Ignores Failed/Rejected Pushes

**Fixtures**: `push_*.json` (failure cases)

| Test | Description |
|------|-------------|
| `test_ignores_everything_up_to_date` | No trigger when no new commits |
| `test_ignores_auth_failed` | No trigger on authentication failure |
| `test_ignores_rejected_push` | No trigger when push rejected |
| `test_ignores_push_error` | No trigger on general errors |
| `test_ignores_remote_rejected` | No trigger when remote hook declines |

**Failure Patterns**:
- `Everything up-to-date`
- `Authentication failed`
- `[rejected]` or `remote rejected`
- `error:` or `fatal:`

## Hook Input/Output Formats

### PostToolUse Hook Input (stdin JSON)

```json
{
  "session_id": "string",
  "transcript_path": "string",
  "cwd": "string",
  "permission_mode": "string",
  "hook_event_name": "PostToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "git push origin main"
  },
  "tool_result": "To github.com:user/repo.git\n   abc1234..def5678  main -> main"
}
```

### Hook Output (stdout JSON)

**When triggering review**:
```json
{
  "continue": true,
  "suppressOutput": false,
  "systemMessage": "Post-push review triggered. Invoking codebase-quality:post-push skill..."
}
```

**When NOT triggering**:
```json
{
  "continue": true
}
```

## Adding New Fixtures

1. Create a JSON file in `fixtures/` with the hook input structure
2. Add a pytest fixture in `conftest.py` to load it
3. Add test cases in the appropriate test class
4. Update this README with the new fixture

### Fixture Template

```json
{
  "session_id": "test-session-XXX",
  "transcript_path": "/Users/test/.claude/projects/-Users-test-project/session.jsonl",
  "cwd": "/Users/test/project",
  "permission_mode": "full",
  "hook_event_name": "PostToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "your command here"
  },
  "tool_result": "command output here"
}
```

## Related Files

- **Hook Script**: `.claude/hooks/post-push-review.sh` (to be implemented)
- **Hook Config**: `.claude/settings.json` (PostToolUse configuration)
- **PRD**: `.taskmaster/docs/post-push-code-review-hook-prd.md`
- **Plan**: `~/.claude/plans/purrfect-booping-rainbow.md`
- **Beads Issue**: `my-project-84v`

## Test Development Workflow

### RED Phase (Current)

1. Tests are written with `NotImplementedError` expected
2. All tests will fail/skip until implementation exists
3. Focus on defining correct behavior and edge cases

### GREEN Phase (Next)

1. Implement `.claude/hooks/post-push-review.sh`
2. Create detection logic to match patterns
3. Tests should pass without modification

### REFACTOR Phase

1. Optimize detection logic
2. Add additional edge cases as discovered
3. Improve error handling

## Debugging Tips

### Verbose Output

```bash
pytest .claude/tests/hooks/ -v -s
```

### Run Single Test

```bash
pytest .claude/tests/hooks/test_post_push_detection.py::TestAC1_HookTriggersOnPushSuccess::test_detects_github_main_push -v
```

### Check Fixture Loading

```python
# In pytest
def test_fixture_loads(push_success_github_main):
    import json
    print(json.dumps(push_success_github_main, indent=2))
    assert True
```

## Maintenance Notes

- Tests use `pytest.raises(NotImplementedError)` during RED phase
- Remove these wrappers once `is_git_push_success()` is implemented
- Integration tests in `TestHookIntegration` are skipped until hook exists
- Pattern constants in test file should match implementation constants

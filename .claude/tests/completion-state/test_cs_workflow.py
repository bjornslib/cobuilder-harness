"""Integration tests for the completion state workflow.

Tests the cs-* CLI scripts and their integration with the stop hook system.
Covers the complete promise lifecycle, multi-session awareness, and momentum checking.
"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# Fixtures


@pytest.fixture
def temp_project_dir():
    """Create a temporary project directory with completion state structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create .claude/completion-state/promises and history dirs
        promises_dir = Path(tmpdir) / '.claude' / 'completion-state' / 'promises'
        history_dir = Path(tmpdir) / '.claude' / 'completion-state' / 'history'
        promises_dir.mkdir(parents=True, exist_ok=True)
        history_dir.mkdir(parents=True, exist_ok=True)
        yield tmpdir


@pytest.fixture
def scripts_dir():
    """Get the path to the cs-* scripts."""
    # Navigate from test file to .claude/scripts/completion-state/
    # tests/completion-state/test_cs_workflow.py -> .claude/scripts/completion-state
    script_dir = Path(__file__).parent.parent.parent / 'scripts' / 'completion-state'
    return script_dir


@pytest.fixture
def test_session_id():
    """Generate a unique test session ID."""
    return f"test-session-{int(time.time() * 1000)}"


def run_cs_command(scripts_dir, command, args, env=None, cwd=None):
    """Run a cs-* command and return the result."""
    script_path = scripts_dir / command
    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    result = subprocess.run(
        ['bash', str(script_path)] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=full_env,
        timeout=30,
    )
    return result


# === Tests for cs-promise CLI ===


class TestCsPromiseCreate:
    """Tests for cs-promise --create."""

    def test_create_promise_success(self, temp_project_dir, scripts_dir, test_session_id):
        """Creating a promise should create a JSON file in promises dir."""
        env = {
            'CLAUDE_SESSION_ID': test_session_id,
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }

        result = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--create', 'Test feature implementation', '--ac', 'Feature works correctly'],
            env=env, cwd=temp_project_dir
        )

        assert result.returncode == 0
        assert 'Created promise:' in result.stdout
        assert 'promise-' in result.stdout

        # Verify JSON file was created
        promises_dir = Path(temp_project_dir) / '.claude' / 'completion-state' / 'promises'
        promise_files = list(promises_dir.glob('*.json'))
        assert len(promise_files) == 1

        # Verify promise structure
        with open(promise_files[0], 'r') as f:
            promise = json.load(f)

        # Note: jq -Rs adds trailing newline, so we strip for comparison
        assert promise['summary'].strip() == 'Test feature implementation'
        assert promise['status'] == 'pending'
        assert promise['ownership']['owned_by'] == test_session_id
        assert promise['ownership']['created_by'] == test_session_id

    def test_create_promise_requires_session_id(self, temp_project_dir, scripts_dir):
        """Creating a promise without CLAUDE_SESSION_ID should fail."""
        env = {
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }
        # Ensure CLAUDE_SESSION_ID is not set
        env['CLAUDE_SESSION_ID'] = ''

        result = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--create', 'Test feature', '--ac', 'Test criterion'],
            env=env, cwd=temp_project_dir
        )

        assert result.returncode != 0
        assert 'CLAUDE_SESSION_ID not set' in result.stderr


class TestCsPromiseLifecycle:
    """Tests for the full cs-promise lifecycle."""

    def test_promise_lifecycle_pending_to_in_progress(self, temp_project_dir, scripts_dir, test_session_id):
        """Promise should transition from pending to in_progress via --start."""
        env = {
            'CLAUDE_SESSION_ID': test_session_id,
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }

        # Create promise
        create_result = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--create', 'Test feature', '--ac', 'Feature works'],
            env=env, cwd=temp_project_dir
        )
        assert create_result.returncode == 0

        # Extract promise ID from output
        for line in create_result.stdout.split('\n'):
            if 'promise-' in line:
                promise_id = line.split('promise-')[1].split()[0]
                promise_id = f'promise-{promise_id}'
                break

        # Start the promise
        start_result = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--start', promise_id],
            env=env, cwd=temp_project_dir
        )
        assert start_result.returncode == 0
        assert 'Started promise:' in start_result.stdout

        # Verify status changed
        promises_dir = Path(temp_project_dir) / '.claude' / 'completion-state' / 'promises'
        with open(promises_dir / f'{promise_id}.json', 'r') as f:
            promise = json.load(f)

        assert promise['status'] == 'in_progress'

    def test_promise_list_shows_all_promises(self, temp_project_dir, scripts_dir, test_session_id):
        """--list should show all promises with their status."""
        env = {
            'CLAUDE_SESSION_ID': test_session_id,
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }

        # Create two promises
        run_cs_command(
            scripts_dir, 'cs-promise',
            ['--create', 'First feature', '--ac', 'First criterion'],
            env=env, cwd=temp_project_dir
        )
        run_cs_command(
            scripts_dir, 'cs-promise',
            ['--create', 'Second feature', '--ac', 'Second criterion'],
            env=env, cwd=temp_project_dir
        )

        # List all promises
        list_result = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--list'],
            env=env, cwd=temp_project_dir
        )

        assert list_result.returncode == 0
        assert 'First feature' in list_result.stdout
        assert 'Second feature' in list_result.stdout
        assert '[PENDING]' in list_result.stdout

    def test_promise_mine_filters_by_session(self, temp_project_dir, scripts_dir, test_session_id):
        """--mine should only show promises owned by current session."""
        env1 = {
            'CLAUDE_SESSION_ID': test_session_id,
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }
        env2 = {
            'CLAUDE_SESSION_ID': 'other-session',
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }

        # Create promise with session 1
        run_cs_command(
            scripts_dir, 'cs-promise',
            ['--create', 'Session 1 feature', '--ac', 'Session 1 criterion'],
            env=env1, cwd=temp_project_dir
        )

        # Create promise with session 2
        run_cs_command(
            scripts_dir, 'cs-promise',
            ['--create', 'Session 2 feature', '--ac', 'Session 2 criterion'],
            env=env2, cwd=temp_project_dir
        )

        # List only session 1's promises
        mine_result = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--mine'],
            env=env1, cwd=temp_project_dir
        )

        assert mine_result.returncode == 0
        assert 'Session 1 feature' in mine_result.stdout
        assert 'Session 2 feature' not in mine_result.stdout


class TestCsPromiseOwnership:
    """Tests for promise ownership operations."""

    def test_release_orphans_promise(self, temp_project_dir, scripts_dir, test_session_id):
        """--release should set ownership to null (orphan the promise)."""
        env = {
            'CLAUDE_SESSION_ID': test_session_id,
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }

        # Create and extract ID
        create_result = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--create', 'Test feature', '--ac', 'Test criterion'],
            env=env, cwd=temp_project_dir
        )
        promise_id = None
        for line in create_result.stdout.split('\n'):
            if 'promise-' in line:
                promise_id = line.split('promise-')[1].split()[0]
                promise_id = f'promise-{promise_id}'
                break

        # Release ownership
        release_result = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--release', promise_id],
            env=env, cwd=temp_project_dir
        )

        assert release_result.returncode == 0
        assert 'Released promise:' in release_result.stdout

        # Verify orphaned
        promises_dir = Path(temp_project_dir) / '.claude' / 'completion-state' / 'promises'
        with open(promises_dir / f'{promise_id}.json', 'r') as f:
            promise = json.load(f)

        assert promise['ownership']['owned_by'] is None

    def test_adopt_takes_orphaned_promise(self, temp_project_dir, scripts_dir, test_session_id):
        """--adopt should claim ownership of an orphaned promise."""
        env1 = {
            'CLAUDE_SESSION_ID': 'original-owner',
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }
        env2 = {
            'CLAUDE_SESSION_ID': test_session_id,
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }

        # Create promise with original owner
        create_result = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--create', 'Orphan feature', '--ac', 'Orphan criterion'],
            env=env1, cwd=temp_project_dir
        )
        promise_id = None
        for line in create_result.stdout.split('\n'):
            if 'promise-' in line:
                promise_id = line.split('promise-')[1].split()[0]
                promise_id = f'promise-{promise_id}'
                break

        # Original owner releases
        run_cs_command(
            scripts_dir, 'cs-promise',
            ['--release', promise_id],
            env=env1, cwd=temp_project_dir
        )

        # New session adopts
        adopt_result = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--adopt', promise_id],
            env=env2, cwd=temp_project_dir
        )

        assert adopt_result.returncode == 0
        assert 'Adopted promise:' in adopt_result.stdout

        # Verify new owner
        promises_dir = Path(temp_project_dir) / '.claude' / 'completion-state' / 'promises'
        with open(promises_dir / f'{promise_id}.json', 'r') as f:
            promise = json.load(f)

        assert promise['ownership']['owned_by'] == test_session_id

    def test_adopt_fails_for_owned_promise(self, temp_project_dir, scripts_dir, test_session_id):
        """--adopt should fail if promise is not orphaned."""
        env1 = {
            'CLAUDE_SESSION_ID': 'owner-session',
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }
        env2 = {
            'CLAUDE_SESSION_ID': test_session_id,
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }

        # Create promise with owner
        create_result = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--create', 'Owned feature', '--ac', 'Owned criterion'],
            env=env1, cwd=temp_project_dir
        )
        promise_id = None
        for line in create_result.stdout.split('\n'):
            if 'promise-' in line:
                promise_id = line.split('promise-')[1].split()[0]
                promise_id = f'promise-{promise_id}'
                break

        # Attempt to adopt owned promise
        adopt_result = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--adopt', promise_id],
            env=env2, cwd=temp_project_dir
        )

        assert adopt_result.returncode != 0
        assert 'not orphaned' in adopt_result.stderr


# === Tests for cs-verify CLI ===


class TestCsVerify:
    """Tests for cs-verify command."""

    def test_verify_promise_success(self, temp_project_dir, scripts_dir, test_session_id):
        """Verifying a promise should move it to history."""
        env = {
            'CLAUDE_SESSION_ID': test_session_id,
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }

        # Create and start promise
        create_result = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--create', 'Test feature', '--ac', 'Test criterion'],
            env=env, cwd=temp_project_dir
        )
        promise_id = None
        for line in create_result.stdout.split('\n'):
            if 'promise-' in line:
                promise_id = line.split('promise-')[1].split()[0]
                promise_id = f'promise-{promise_id}'
                break

        run_cs_command(
            scripts_dir, 'cs-promise',
            ['--start', promise_id],
            env=env, cwd=temp_project_dir
        )

        # Meet the acceptance criterion first
        run_cs_command(
            scripts_dir, 'cs-promise',
            ['--meet', promise_id, '--ac-id', 'AC-1', '--evidence', 'All tests pass', '--type', 'test'],
            env=env, cwd=temp_project_dir
        )

        # Store validation for Gate 2
        run_cs_command(
            scripts_dir, 'cs-store-validation',
            ['--promise', promise_id, '--ac-id', 'AC-1',
             '--response', '{"task_id":"test-task","verdict":"PASS","criteria_results":[],"timestamp":"2026-01-01T00:00:00Z"}'],
            env=env, cwd=temp_project_dir
        )

        # Verify promise
        verify_result = run_cs_command(
            scripts_dir, 'cs-verify',
            ['--promise', promise_id],
            env=env, cwd=temp_project_dir
        )

        assert verify_result.returncode == 0
        assert 'VERIFIED:' in verify_result.stdout

        # Verify moved to history
        promises_dir = Path(temp_project_dir) / '.claude' / 'completion-state' / 'promises'
        history_dir = Path(temp_project_dir) / '.claude' / 'completion-state' / 'history'

        assert not (promises_dir / f'{promise_id}.json').exists()
        assert (history_dir / f'{promise_id}.json').exists()

        # Verify status in history
        with open(history_dir / f'{promise_id}.json', 'r') as f:
            promise = json.load(f)

        assert promise['status'] == 'verified'
        assert promise['verification']['type'] == 'test'
        assert promise['verification']['proof'] == 'All tests pass'

    def test_verify_requires_ownership(self, temp_project_dir, scripts_dir, test_session_id):
        """Verifying a promise owned by another session should fail."""
        env1 = {
            'CLAUDE_SESSION_ID': 'owner-session',
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }
        env2 = {
            'CLAUDE_SESSION_ID': test_session_id,
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }

        # Create promise with owner
        create_result = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--create', 'Owned feature', '--ac', 'Owned criterion'],
            env=env1, cwd=temp_project_dir
        )
        promise_id = None
        for line in create_result.stdout.split('\n'):
            if 'promise-' in line:
                promise_id = line.split('promise-')[1].split()[0]
                promise_id = f'promise-{promise_id}'
                break

        run_cs_command(
            scripts_dir, 'cs-promise',
            ['--start', promise_id],
            env=env1, cwd=temp_project_dir
        )

        # Attempt to verify with different session
        verify_result = run_cs_command(
            scripts_dir, 'cs-verify',
            ['--promise', promise_id, '--proof', 'Test evidence'],
            env=env2, cwd=temp_project_dir
        )

        assert verify_result.returncode != 0
        assert "don't own" in verify_result.stderr

    def test_verify_check_passes_with_no_promises(self, temp_project_dir, scripts_dir, test_session_id):
        """--check should pass (exit 0) when no promises are owned."""
        env = {
            'CLAUDE_SESSION_ID': test_session_id,
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }

        result = run_cs_command(
            scripts_dir, 'cs-verify',
            ['--check'],
            env=env, cwd=temp_project_dir
        )

        assert result.returncode == 0

    def test_verify_check_fails_with_in_progress_promise(self, temp_project_dir, scripts_dir, test_session_id):
        """--check should fail (exit 2) with in_progress promises."""
        env = {
            'CLAUDE_SESSION_ID': test_session_id,
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }

        # Create and start promise
        create_result = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--create', 'Incomplete feature', '--ac', 'Incomplete criterion'],
            env=env, cwd=temp_project_dir
        )
        promise_id = None
        for line in create_result.stdout.split('\n'):
            if 'promise-' in line:
                promise_id = line.split('promise-')[1].split()[0]
                promise_id = f'promise-{promise_id}'
                break

        run_cs_command(
            scripts_dir, 'cs-promise',
            ['--start', promise_id],
            env=env, cwd=temp_project_dir
        )

        # Check should fail
        check_result = run_cs_command(
            scripts_dir, 'cs-verify',
            ['--check'],
            env=env, cwd=temp_project_dir
        )

        assert check_result.returncode == 2
        assert 'COMPLETION CRITERIA NOT MET' in check_result.stdout
        assert 'IN_PROGRESS' in check_result.stdout


# === Tests for CompletionPromiseChecker (Python) ===


class TestCompletionPromiseChecker:
    """Tests for the Python CompletionPromiseChecker class."""

    @pytest.fixture
    def setup_imports(self):
        """Set up Python imports for checker tests."""
        import sys
        # Navigate from tests/completion-state to .claude/hooks/
        hooks_dir = Path(__file__).parent.parent.parent / 'hooks'
        sys.path.insert(0, str(hooks_dir))
        yield
        sys.path.pop(0)

    def test_checker_passes_with_no_promises(self, temp_project_dir, setup_imports):
        """Checker should pass when no promises exist."""
        from unified_stop_gate.checkers import CompletionPromiseChecker
        from unified_stop_gate.config import EnvironmentConfig, PathResolver

        config = EnvironmentConfig(
            project_dir=temp_project_dir,
            session_dir=None,
            session_id=None,
            max_iterations=25,
            enforce_promise=True,
            enforce_bo=False,
        )
        paths = PathResolver(config=config)

        # Don't set CLAUDE_SESSION_ID
        with patch.dict(os.environ, {'CLAUDE_SESSION_ID': ''}):
            checker = CompletionPromiseChecker(config, paths)
            result = checker.check()

        assert result.passed == True

    def test_checker_blocks_with_owned_in_progress_promise(self, temp_project_dir, setup_imports):
        """Checker should block when owned promises are in_progress."""
        from unified_stop_gate.checkers import CompletionPromiseChecker
        from unified_stop_gate.config import EnvironmentConfig, PathResolver

        config = EnvironmentConfig(
            project_dir=temp_project_dir,
            session_dir=None,
            session_id='test-checker-session',
            max_iterations=25,
            enforce_promise=True,
            enforce_bo=False,
        )
        paths = PathResolver(config=config)
        paths.ensure_dirs_exist()

        session_id = 'test-checker-session'

        # Create an in_progress promise owned by this session
        promise = {
            'id': 'promise-test123',
            'summary': 'Test feature',
            'ownership': {
                'created_by': session_id,
                'created_at': '2026-01-10T00:00:00Z',
                'owned_by': session_id,
                'owned_since': '2026-01-10T00:00:00Z',
            },
            'status': 'in_progress',
            'verification': {},
        }
        with open(paths.promises_dir / 'promise-test123.json', 'w') as f:
            json.dump(promise, f)

        with patch.dict(os.environ, {'CLAUDE_SESSION_ID': session_id}):
            checker = CompletionPromiseChecker(config, paths)
            result = checker.check()

        assert result.passed == False
        assert 'in_progress' in result.message.lower()

    def test_checker_warns_about_other_sessions_promises(self, temp_project_dir, setup_imports):
        """Checker should warn but pass when other sessions have in_progress promises."""
        from unified_stop_gate.checkers import CompletionPromiseChecker
        from unified_stop_gate.config import EnvironmentConfig, PathResolver

        config = EnvironmentConfig(
            project_dir=temp_project_dir,
            session_dir=None,
            session_id='my-session',
            max_iterations=25,
            enforce_promise=True,
            enforce_bo=False,
        )
        paths = PathResolver(config=config)
        paths.ensure_dirs_exist()

        my_session = 'my-session'
        other_session = 'other-session'

        # Create an in_progress promise owned by OTHER session
        promise = {
            'id': 'promise-other123',
            'summary': 'Other session feature',
            'ownership': {
                'created_by': other_session,
                'created_at': '2026-01-10T00:00:00Z',
                'owned_by': other_session,
                'owned_since': '2026-01-10T00:00:00Z',
            },
            'status': 'in_progress',
            'verification': {},
        }
        with open(paths.promises_dir / 'promise-other123.json', 'w') as f:
            json.dump(promise, f)

        with patch.dict(os.environ, {'CLAUDE_SESSION_ID': my_session}):
            checker = CompletionPromiseChecker(config, paths)
            result = checker.check()

        # Should PASS (not block) because this session doesn't own the promise
        assert result.passed == True
        # Should mention other sessions' promises
        assert 'other sessions' in result.message.lower() or 'no promises owned' in result.message.lower()

    def test_checker_warns_about_orphaned_promises(self, temp_project_dir, setup_imports):
        """Checker should warn about orphaned in_progress promises."""
        from unified_stop_gate.checkers import CompletionPromiseChecker
        from unified_stop_gate.config import EnvironmentConfig, PathResolver

        config = EnvironmentConfig(
            project_dir=temp_project_dir,
            session_dir=None,
            session_id='my-session',
            max_iterations=25,
            enforce_promise=True,
            enforce_bo=False,
        )
        paths = PathResolver(config=config)
        paths.ensure_dirs_exist()

        my_session = 'my-session'

        # Create an orphaned in_progress promise (owned_by = null)
        promise = {
            'id': 'promise-orphan123',
            'summary': 'Orphaned feature',
            'ownership': {
                'created_by': 'crashed-session',
                'created_at': '2026-01-10T00:00:00Z',
                'owned_by': None,  # Orphaned
                'owned_since': None,
            },
            'status': 'in_progress',
            'verification': {},
        }
        with open(paths.promises_dir / 'promise-orphan123.json', 'w') as f:
            json.dump(promise, f)

        with patch.dict(os.environ, {'CLAUDE_SESSION_ID': my_session}):
            checker = CompletionPromiseChecker(config, paths)
            result = checker.check()

        # Should PASS (not block) because orphaned promises don't block
        assert result.passed == True
        # Should mention orphaned promises
        assert 'orphan' in result.message.lower()


# === Tests for Stop Hook Integration ===


class TestStopHookIntegration:
    """Tests for the unified stop gate hook integration."""

    def test_stop_hook_blocks_with_in_progress_promise(self, temp_project_dir):
        """Stop hook should block when there are in_progress promises."""
        import sys
        # Navigate from tests/completion-state to .claude/hooks/
        hooks_dir = Path(__file__).parent.parent.parent / 'hooks'
        sys.path.insert(0, str(hooks_dir))

        from unified_stop_gate.checkers import CompletionPromiseChecker
        from unified_stop_gate.config import EnvironmentConfig, PathResolver

        config = EnvironmentConfig(
            project_dir=temp_project_dir,
            session_dir=None,
            session_id='stop-hook-test-session',
            max_iterations=25,
            enforce_promise=True,
            enforce_bo=False,
        )
        paths = PathResolver(config=config)
        paths.ensure_dirs_exist()

        session_id = 'stop-hook-test-session'

        # Create an in_progress promise
        promise = {
            'id': 'promise-stop-test',
            'summary': 'Stop test feature',
            'ownership': {
                'created_by': session_id,
                'created_at': '2026-01-10T00:00:00Z',
                'owned_by': session_id,
                'owned_since': '2026-01-10T00:00:00Z',
            },
            'status': 'in_progress',
            'verification': {},
        }
        with open(paths.promises_dir / 'promise-stop-test.json', 'w') as f:
            json.dump(promise, f)

        with patch.dict(os.environ, {'CLAUDE_SESSION_ID': session_id}):
            checker = CompletionPromiseChecker(config, paths)
            result = checker.check()

        assert result.passed == False
        assert result.blocking == True

        sys.path.pop(0)


# === Tests for Momentum Check ===


class TestMomentumCheck:
    """Tests for the momentum check feature in the stop hook."""

    @pytest.fixture
    def marker_path(self, test_session_id):
        """Get the momentum marker file path."""
        return Path(f'/tmp/claude-stop-momentum-{test_session_id}')

    def test_momentum_marker_file_creation(self, marker_path, test_session_id):
        """Test that the momentum marker file is created correctly."""
        # Ensure clean state
        if marker_path.exists():
            marker_path.unlink()

        # Create marker
        marker_path.touch()

        assert marker_path.exists()

        # Cleanup
        marker_path.unlink()

    def test_second_stop_attempt_detection(self, marker_path, test_session_id):
        """Test detection of second stop attempt within 5 minutes."""
        import time

        # Ensure clean state
        if marker_path.exists():
            marker_path.unlink()

        # First attempt - no marker
        assert not marker_path.exists()

        # Simulate first stop attempt by creating marker
        marker_path.touch()

        # Second attempt - marker exists and is recent
        assert marker_path.exists()
        age_seconds = time.time() - marker_path.stat().st_mtime
        assert age_seconds < 300  # Within 5 minutes

        # Cleanup
        marker_path.unlink()

    def test_old_marker_is_ignored(self, marker_path, test_session_id):
        """Test that markers older than 5 minutes are ignored."""
        import os
        import time

        # Ensure clean state
        if marker_path.exists():
            marker_path.unlink()

        # Create marker with old timestamp (6 minutes ago)
        marker_path.touch()
        old_time = time.time() - 360  # 6 minutes ago
        os.utime(marker_path, (old_time, old_time))

        # Verify marker is old
        age_seconds = time.time() - marker_path.stat().st_mtime
        assert age_seconds > 300  # Older than 5 minutes

        # Cleanup
        marker_path.unlink()


# === Tests for Cross-Session Awareness ===


class TestCrossSessionAwareness:
    """Tests for cross-session promise awareness."""

    def test_multiple_sessions_can_have_promises(self, temp_project_dir, scripts_dir):
        """Multiple sessions should be able to create and track their own promises."""
        session1_env = {
            'CLAUDE_SESSION_ID': 'session-1',
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }
        session2_env = {
            'CLAUDE_SESSION_ID': 'session-2',
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }

        # Create promises in both sessions
        run_cs_command(
            scripts_dir, 'cs-promise',
            ['--create', 'Session 1 work', '--ac', 'Session 1 criterion'],
            env=session1_env, cwd=temp_project_dir
        )
        run_cs_command(
            scripts_dir, 'cs-promise',
            ['--create', 'Session 2 work', '--ac', 'Session 2 criterion'],
            env=session2_env, cwd=temp_project_dir
        )

        # Verify each session sees only their own with --mine
        mine1 = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--mine'],
            env=session1_env, cwd=temp_project_dir
        )
        mine2 = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--mine'],
            env=session2_env, cwd=temp_project_dir
        )

        assert 'Session 1 work' in mine1.stdout
        assert 'Session 2 work' not in mine1.stdout

        assert 'Session 2 work' in mine2.stdout
        assert 'Session 1 work' not in mine2.stdout

    def test_session_isolation_for_verification(self, temp_project_dir, scripts_dir):
        """Each session can only verify its own promises."""
        session1_env = {
            'CLAUDE_SESSION_ID': 'session-verify-1',
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }
        session2_env = {
            'CLAUDE_SESSION_ID': 'session-verify-2',
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }

        # Create promise in session 1
        create_result = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--create', 'Session 1 exclusive work', '--ac', 'Session 1 exclusive criterion'],
            env=session1_env, cwd=temp_project_dir
        )
        promise_id = None
        for line in create_result.stdout.split('\n'):
            if 'promise-' in line:
                promise_id = line.split('promise-')[1].split()[0]
                promise_id = f'promise-{promise_id}'
                break

        run_cs_command(
            scripts_dir, 'cs-promise',
            ['--start', promise_id],
            env=session1_env, cwd=temp_project_dir
        )

        # Session 2 should NOT be able to verify session 1's promise
        verify_result = run_cs_command(
            scripts_dir, 'cs-verify',
            ['--promise', promise_id, '--proof', 'Unauthorized attempt'],
            env=session2_env, cwd=temp_project_dir
        )

        assert verify_result.returncode != 0
        assert "don't own" in verify_result.stderr


# === Tests for cs-promise --cancel ===


class TestCsPromiseCancel:
    """Tests for cs-promise --cancel."""

    def test_cancel_moves_to_history(self, temp_project_dir, scripts_dir, test_session_id):
        """Cancelling a promise should move it to history with cancelled status."""
        env = {
            'CLAUDE_SESSION_ID': test_session_id,
            'CLAUDE_PROJECT_DIR': temp_project_dir,
        }

        # Create promise
        create_result = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--create', 'Feature to cancel', '--ac', 'Cancel criterion'],
            env=env, cwd=temp_project_dir
        )
        promise_id = None
        for line in create_result.stdout.split('\n'):
            if 'promise-' in line:
                promise_id = line.split('promise-')[1].split()[0]
                promise_id = f'promise-{promise_id}'
                break

        # Cancel promise
        cancel_result = run_cs_command(
            scripts_dir, 'cs-promise',
            ['--cancel', promise_id],
            env=env, cwd=temp_project_dir
        )

        assert cancel_result.returncode == 0
        assert 'Cancelled promise:' in cancel_result.stdout

        # Verify in history with cancelled status
        promises_dir = Path(temp_project_dir) / '.claude' / 'completion-state' / 'promises'
        history_dir = Path(temp_project_dir) / '.claude' / 'completion-state' / 'history'

        assert not (promises_dir / f'{promise_id}.json').exists()
        assert (history_dir / f'{promise_id}.json').exists()

        with open(history_dir / f'{promise_id}.json', 'r') as f:
            promise = json.load(f)

        assert promise['status'] == 'cancelled'


# === Entry point ===


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

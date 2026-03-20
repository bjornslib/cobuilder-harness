#!/usr/bin/env python3
"""Unit tests for PipelineRunner._verify_worker_output method.

Tests the post-signal verification of worker output including:
- File existence checks
- Git status verification
- Error handling
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from cobuilder.engine.pipeline_runner import PipelineRunner


class TestVerifyWorkerOutput:
    """Tests for PipelineRunner._verify_worker_output method."""

    @pytest.fixture
    def temp_git_repo(self):
        """Create a temporary git repository for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            # Initialize git repo
            subprocess.run(
                ["git", "init"],
                cwd=repo_path,
                capture_output=True,
                check=True
            )
            # Configure git for testing
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repo_path,
                capture_output=True,
                check=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                capture_output=True,
                check=True
            )
            yield repo_path

    @pytest.fixture
    def pipeline_runner(self, temp_git_repo):
        """Create a PipelineRunner instance for testing."""
        # Create a minimal DOT file with required attributes
        dot_file = temp_git_repo / "test.dot"
        dot_file.write_text("""
digraph test {
    graph [
        pipeline_id="test"
        cobuilder_root="%s"
        target_dir="%s"
    ];
    start [shape=Mdiamond status=pending];
}
""" % (str(temp_git_repo), str(temp_git_repo)))

        runner = PipelineRunner(str(dot_file))
        return runner

    def test_verify_with_no_files_changed(self, pipeline_runner, temp_git_repo):
        """Test verification with no files_changed — should pass."""
        signal = {"status": "success", "files_changed": [], "message": "test"}

        passed, reason = pipeline_runner._verify_worker_output(
            "test_node", str(temp_git_repo), signal
        )

        assert passed is True
        assert reason is None

    def test_verify_with_missing_files(self, pipeline_runner, temp_git_repo):
        """Test verification fails when declared files don't exist."""
        signal = {
            "status": "success",
            "files_changed": ["missing_file.py"],
            "message": "test"
        }

        passed, reason = pipeline_runner._verify_worker_output(
            "test_node", str(temp_git_repo), signal
        )

        assert passed is False
        assert "Missing files" in reason
        assert "missing_file.py" in reason

    def test_verify_with_existing_files_and_git_changes(self, pipeline_runner, temp_git_repo):
        """Test verification passes when files exist and git shows changes."""
        # Create a file and stage it
        test_file = temp_git_repo / "test.py"
        test_file.write_text("print('hello')")

        subprocess.run(
            ["git", "add", "test.py"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True
        )

        signal = {
            "status": "success",
            "files_changed": ["test.py"],
            "message": "test"
        }

        passed, reason = pipeline_runner._verify_worker_output(
            "test_node", str(temp_git_repo), signal
        )

        assert passed is True
        assert reason is None

    def test_verify_with_unstaged_changes(self, pipeline_runner, temp_git_repo):
        """Test verification passes with unstaged changes in git."""
        # Create a file but don't stage it
        test_file = temp_git_repo / "unstaged.py"
        test_file.write_text("print('world')")

        signal = {
            "status": "success",
            "files_changed": ["unstaged.py"],
            "message": "test"
        }

        passed, reason = pipeline_runner._verify_worker_output(
            "test_node", str(temp_git_repo), signal
        )

        assert passed is True
        assert reason is None

    def test_verify_with_file_exists_but_no_git_changes(self, pipeline_runner, temp_git_repo):
        """Test verification passes when file exists even if git shows no changes.

        This tests the primary check priority: file existence is what matters,
        not whether the file shows changes in git status (already committed).
        """
        # Create initial commit with a file
        (temp_git_repo / "committed.py").write_text("original")
        subprocess.run(
            ["git", "add", "."],
            cwd=temp_git_repo,
            capture_output=True,
            check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True
        )

        # File exists and is committed, but git status shows no changes to it
        signal = {
            "status": "success",
            "files_changed": ["committed.py"],  # This file hasn't changed since last commit
            "message": "test"
        }

        passed, reason = pipeline_runner._verify_worker_output(
            "test_node", str(temp_git_repo), signal
        )

        # Should pass because the file exists on disk (primary check is file existence)
        assert passed is True
        assert reason is None

    def test_verify_with_nonexistent_target_dir(self, pipeline_runner):
        """Test verification fails gracefully with non-existent target dir."""
        signal = {
            "status": "success",
            "files_changed": ["test.py"],
            "message": "test"
        }

        passed, reason = pipeline_runner._verify_worker_output(
            "test_node", "/nonexistent/path", signal
        )

        assert passed is False
        # The file check happens first, so we expect a missing files error
        assert "missing" in reason.lower()

    def test_verify_with_absolute_file_path(self, pipeline_runner, temp_git_repo):
        """Test verification with absolute file paths in files_changed."""
        # Create and stage a file
        test_file = temp_git_repo / "absolute.py"
        test_file.write_text("absolute path test")
        subprocess.run(
            ["git", "add", "absolute.py"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True
        )

        # Use absolute path in signal
        signal = {
            "status": "success",
            "files_changed": [str(test_file)],
            "message": "test"
        }

        passed, reason = pipeline_runner._verify_worker_output(
            "test_node", str(temp_git_repo), signal
        )

        assert passed is True
        assert reason is None

    def test_verify_with_multiple_files(self, pipeline_runner, temp_git_repo):
        """Test verification with multiple files."""
        # Create and stage multiple files
        (temp_git_repo / "file1.py").write_text("file1")
        (temp_git_repo / "file2.py").write_text("file2")
        (temp_git_repo / "file3.py").write_text("file3")

        subprocess.run(
            ["git", "add", "."],
            cwd=temp_git_repo,
            capture_output=True,
            check=True
        )

        signal = {
            "status": "success",
            "files_changed": ["file1.py", "file2.py", "file3.py"],
            "message": "test"
        }

        passed, reason = pipeline_runner._verify_worker_output(
            "test_node", str(temp_git_repo), signal
        )

        assert passed is True
        assert reason is None

    def test_verify_with_some_missing_files(self, pipeline_runner, temp_git_repo):
        """Test verification fails if even one file is missing."""
        # Create and stage only one file
        (temp_git_repo / "exists.py").write_text("exists")
        subprocess.run(
            ["git", "add", "exists.py"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True
        )

        signal = {
            "status": "success",
            "files_changed": ["exists.py", "missing.py"],
            "message": "test"
        }

        passed, reason = pipeline_runner._verify_worker_output(
            "test_node", str(temp_git_repo), signal
        )

        assert passed is False
        assert "missing.py" in reason

    def test_verify_with_file_exists_but_not_in_git_status(self, pipeline_runner, temp_git_repo):
        """Test verification passes when file exists even if not in git status.

        This tests the primary check priority: if a file exists on disk,
        verification passes. We don't fail just because git status is clean.
        """
        # Create and commit initial files
        (temp_git_repo / "file1.py").write_text("file1 content")
        (temp_git_repo / "file2.py").write_text("file2 content")
        subprocess.run(
            ["git", "add", "."],
            cwd=temp_git_repo,
            capture_output=True,
            check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True
        )

        # Modify only file2.py, not file1.py
        (temp_git_repo / "file2.py").write_text("file2 modified")

        # Worker claims file1.py was changed, and file1.py exists on disk
        signal = {
            "status": "success",
            "files_changed": ["file1.py"],
            "message": "test"
        }

        passed, reason = pipeline_runner._verify_worker_output(
            "test_node", str(temp_git_repo), signal
        )

        # Should pass because file1.py exists on disk (primary check is file existence)
        assert passed is True
        assert reason is None

    def test_verify_with_multiple_files_mismatched(self, pipeline_runner, temp_git_repo):
        """Test verification with multiple files where all exist on disk.

        Even if only some files show changes in git status, as long as all
        files exist on disk, verification passes.
        """
        # Create and commit initial files
        (temp_git_repo / "file1.py").write_text("file1")
        (temp_git_repo / "file2.py").write_text("file2")
        (temp_git_repo / "file3.py").write_text("file3")
        subprocess.run(
            ["git", "add", "."],
            cwd=temp_git_repo,
            capture_output=True,
            check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=temp_git_repo,
            capture_output=True,
            check=True
        )

        # Modify only file1.py and file2.py
        (temp_git_repo / "file1.py").write_text("file1 modified")
        (temp_git_repo / "file2.py").write_text("file2 modified")

        # Worker claims all three files changed, and all three exist on disk
        signal = {
            "status": "success",
            "files_changed": ["file1.py", "file2.py", "file3.py"],
            "message": "test"
        }

        passed, reason = pipeline_runner._verify_worker_output(
            "test_node", str(temp_git_repo), signal
        )

        # Should pass because all files exist on disk (primary check is file existence)
        assert passed is True
        assert reason is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

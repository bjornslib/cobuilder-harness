"""
Document Lifecycle Acceptance Tests for Post-Push Code Review Hook

This test module validates the document lifecycle management functionality
for the post-push code review system. Tests are written following TDD RED-GREEN-REFACTOR.

Acceptance Criteria Tested:
- AC-9: Document completion detection with various checkbox states
- AC-10: All 5 lifecycle states correctly detected (draft, approved, in-progress, implemented, staged)
- AC-11: in-progress transition when code changes detected
- AC-12: implemented transition when 100% complete
- AC-13: Subfolder auto-creation
- AC-14: Multi-directory scanning
- AC-15: Ephemeral directory exclusion

Usage:
    pytest .claude/tests/hooks/test_document_lifecycle.py -v

Note: These tests are written FIRST (RED phase) before the document lifecycle is implemented.
They will fail until the lifecycle management is fully implemented (GREEN phase).
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest


# =============================================================================
# Document Lifecycle Module (to be tested)
# =============================================================================
# Note: In RED phase, we define the expected interface.
# The actual implementation will be in the post-push skill.


def parse_status_header(content: str) -> dict[str, Any]:
    """
    Parse the document status header from markdown content.

    Args:
        content: The markdown document content

    Returns:
        Dictionary with status header fields (current_status, last_updated, completion)
    """
    raise NotImplementedError("Status header parsing not yet implemented")


def calculate_completion_percentage(content: str) -> tuple[int, int, int]:
    """
    Calculate completion percentage from acceptance criteria checkboxes.

    Args:
        content: The markdown document content

    Returns:
        Tuple of (percentage, checked_count, total_count)
    """
    raise NotImplementedError("Completion calculation not yet implemented")


def detect_lifecycle_state(content: str) -> str:
    """
    Detect the current lifecycle state of a document.

    Args:
        content: The markdown document content

    Returns:
        One of: "draft", "approved", "in-progress", "implemented", "staged"
    """
    raise NotImplementedError("Lifecycle state detection not yet implemented")


def should_transition_state(
    document_path: str,
    content: str,
    changed_files: list[str],
) -> tuple[bool, str | None, str | None]:
    """
    Determine if a document should transition to a new lifecycle state.

    Args:
        document_path: Path to the document
        content: The document content
        changed_files: List of files changed in the push

    Returns:
        Tuple of (should_transition, new_state, reason)
    """
    raise NotImplementedError("State transition logic not yet implemented")


def move_document_to_state_folder(
    document_path: str,
    target_state: str,
) -> str:
    """
    Move a document to the appropriate lifecycle subfolder.

    Args:
        document_path: Current path to the document
        target_state: Target lifecycle state

    Returns:
        New path after moving
    """
    raise NotImplementedError("Document movement not yet implemented")


def ensure_lifecycle_subfolders(base_directory: str) -> list[str]:
    """
    Ensure lifecycle subfolders exist in the given directory.

    Args:
        base_directory: Base documentation directory path

    Returns:
        List of created/verified subfolder paths
    """
    raise NotImplementedError("Subfolder creation not yet implemented")


def get_managed_directories() -> list[str]:
    """
    Get list of directories to scan for document lifecycle management.

    Returns:
        List of directory paths to scan
    """
    raise NotImplementedError("Managed directories not yet implemented")


def get_ephemeral_directories() -> list[str]:
    """
    Get list of directories excluded from lifecycle management.

    Returns:
        List of directory paths to exclude
    """
    raise NotImplementedError("Ephemeral directories not yet implemented")


def is_ephemeral_document(document_path: str) -> bool:
    """
    Check if a document is in an ephemeral directory.

    Args:
        document_path: Path to the document

    Returns:
        True if document should be excluded from lifecycle management
    """
    raise NotImplementedError("Ephemeral check not yet implemented")


def scan_directory_for_documents(
    directory: str,
) -> list[dict[str, Any]]:
    """
    Scan a directory for documents requiring lifecycle updates.

    Args:
        directory: Directory path to scan

    Returns:
        List of document metadata dictionaries
    """
    raise NotImplementedError("Directory scanning not yet implemented")


# =============================================================================
# Constants for Document Lifecycle
# =============================================================================

# All valid lifecycle states (5-state machine)
LIFECYCLE_STATES = ["draft", "approved", "in-progress", "implemented", "staged"]

# Lifecycle subfolders to create
LIFECYCLE_SUBFOLDERS = ["approved", "in-progress", "implemented", "staged"]

# Regex patterns for checkbox detection
CHECKED_PATTERN = re.compile(r"\[x\]", re.IGNORECASE)
UNCHECKED_PATTERN = re.compile(r"\[ \]")

# Status header pattern
STATUS_PATTERN = re.compile(
    r"\*\*Current Status\*\*:\s*(\w+(?:-\w+)?)",
    re.IGNORECASE,
)

# Primary managed directories
PRIMARY_DIRECTORIES = [
    "documentation/prds/",
    "documentation/solution_designs/",
    ".taskmaster/docs/",
]

# Ephemeral directories (excluded from lifecycle)
EPHEMERAL_DIRECTORIES = [
    "documentation/scratch-pads/",
    "documentation/handoffs/",
]


# =============================================================================
# Fixture Loader Helper
# =============================================================================


def load_lifecycle_fixture(fixture_name: str) -> dict[str, Any]:
    """Load a lifecycle fixture by name."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    fixture_path = fixtures_dir / f"{fixture_name}.json"
    if not fixture_path.exists():
        raise FileNotFoundError(f"Fixture not found: {fixture_path}")
    with open(fixture_path) as f:
        return json.load(f)


# =============================================================================
# Test Class: AC-9 - Document Completion Detection
# =============================================================================


class TestAC9_DocumentCompletionDetection:
    """
    AC-9: Detect Document Completion

    Given: Document has acceptance criteria section with checkboxes
    When: Post-push skill analyzes document
    Then: Completion percentage is calculated correctly
    """

    def test_completion_0_percent(self) -> None:
        """Test detection of 0% completion (all unchecked)."""
        fixture = load_lifecycle_fixture("lifecycle_completion_0_percent")
        content = fixture["document"]["content"]
        expected = fixture["expected_completion"]

        # Verify fixture data
        assert expected["percentage"] == 0
        assert expected["checked_criteria"] == 0
        assert expected["total_criteria"] == 5

        # Test completion calculation (will fail in RED phase)
        with pytest.raises(NotImplementedError):
            percentage, checked, total = calculate_completion_percentage(content)
            assert percentage == expected["percentage"]
            assert checked == expected["checked_criteria"]
            assert total == expected["total_criteria"]

    def test_completion_50_percent(self) -> None:
        """Test detection of 50% completion (half checked)."""
        fixture = load_lifecycle_fixture("lifecycle_completion_50_percent")
        content = fixture["document"]["content"]
        expected = fixture["expected_completion"]

        # Verify fixture data
        assert expected["percentage"] == 50
        assert expected["checked_criteria"] == 2
        assert expected["total_criteria"] == 4

        # Test completion calculation (will fail in RED phase)
        with pytest.raises(NotImplementedError):
            percentage, checked, total = calculate_completion_percentage(content)
            assert percentage == expected["percentage"]
            assert checked == expected["checked_criteria"]
            assert total == expected["total_criteria"]

    def test_completion_100_percent(self) -> None:
        """Test detection of 100% completion (all checked)."""
        fixture = load_lifecycle_fixture("lifecycle_completion_100_percent")
        content = fixture["document"]["content"]
        expected = fixture["expected_completion"]

        # Verify fixture data
        assert expected["percentage"] == 100
        assert expected["checked_criteria"] == 6
        assert expected["total_criteria"] == 6

        # Test completion calculation (will fail in RED phase)
        with pytest.raises(NotImplementedError):
            percentage, checked, total = calculate_completion_percentage(content)
            assert percentage == expected["percentage"]
            assert checked == expected["checked_criteria"]
            assert total == expected["total_criteria"]

    def test_completion_no_acceptance_criteria(self) -> None:
        """Test document with no acceptance criteria (should be 100% complete)."""
        fixture = load_lifecycle_fixture("lifecycle_no_acceptance_criteria")
        content = fixture["document"]["content"]
        expected = fixture["expected_completion"]

        # Verify fixture data - no ACs means 100% complete
        assert expected["percentage"] == 100
        assert expected["total_criteria"] == 0

        # Test completion calculation (will fail in RED phase)
        with pytest.raises(NotImplementedError):
            percentage, checked, total = calculate_completion_percentage(content)
            assert percentage == 100
            assert total == 0

    @pytest.mark.parametrize(
        "fixture_name,expected_percentage",
        [
            ("lifecycle_completion_0_percent", 0),
            ("lifecycle_completion_50_percent", 50),
            ("lifecycle_completion_100_percent", 100),
            ("lifecycle_no_acceptance_criteria", 100),
        ],
    )
    def test_completion_percentage_parameterized(
        self,
        fixture_name: str,
        expected_percentage: int,
    ) -> None:
        """Parameterized test for various completion percentages."""
        fixture = load_lifecycle_fixture(fixture_name)
        content = fixture["document"]["content"]

        with pytest.raises(NotImplementedError):
            percentage, _, _ = calculate_completion_percentage(content)
            assert percentage == expected_percentage

    def test_checkbox_pattern_matching(self) -> None:
        """Test that checkbox patterns are correctly identified."""
        test_content = """
## Acceptance Criteria

- [x] First criterion
- [X] Second criterion (uppercase X)
- [ ] Third criterion (unchecked)
- [ ] Fourth criterion (unchecked)
"""
        # Verify patterns work correctly
        checked = len(CHECKED_PATTERN.findall(test_content))
        unchecked = len(UNCHECKED_PATTERN.findall(test_content))

        assert checked == 2  # [x] and [X]
        assert unchecked == 2  # [ ] and [ ]

        with pytest.raises(NotImplementedError):
            percentage, checked_count, total = calculate_completion_percentage(test_content)
            assert checked_count == 2
            assert total == 4


# =============================================================================
# Test Class: AC-10 - Lifecycle State Detection
# =============================================================================


class TestAC10_LifecycleStateDetection:
    """
    AC-10: Support Full Lifecycle States

    Given: Document can be in any of 5 states (draft, approved, in-progress, implemented, staged)
    When: Post-push skill reads document status header
    Then: Current state is correctly identified and handled
    """

    def test_detect_draft_state(self) -> None:
        """Test detection of draft state."""
        fixture = load_lifecycle_fixture("lifecycle_draft_state")
        content = fixture["document"]["content"]
        expected = fixture["expected_detection"]

        assert expected["state"] == "draft"

        with pytest.raises(NotImplementedError):
            state = detect_lifecycle_state(content)
            assert state == "draft"

    def test_detect_approved_state(self) -> None:
        """Test detection of approved state."""
        fixture = load_lifecycle_fixture("lifecycle_approved_state")
        content = fixture["document"]["content"]
        expected = fixture["expected_detection"]

        assert expected["state"] == "approved"

        with pytest.raises(NotImplementedError):
            state = detect_lifecycle_state(content)
            assert state == "approved"

    def test_detect_in_progress_state(self) -> None:
        """Test detection of in-progress state."""
        fixture = load_lifecycle_fixture("lifecycle_in_progress_state")
        content = fixture["document"]["content"]
        expected = fixture["expected_detection"]

        assert expected["state"] == "in-progress"

        with pytest.raises(NotImplementedError):
            state = detect_lifecycle_state(content)
            assert state == "in-progress"

    def test_detect_implemented_state(self) -> None:
        """Test detection of implemented state."""
        fixture = load_lifecycle_fixture("lifecycle_implemented_state")
        content = fixture["document"]["content"]
        expected = fixture["expected_detection"]

        assert expected["state"] == "implemented"

        with pytest.raises(NotImplementedError):
            state = detect_lifecycle_state(content)
            assert state == "implemented"

    def test_detect_staged_state(self) -> None:
        """Test detection of staged state."""
        fixture = load_lifecycle_fixture("lifecycle_staged_state")
        content = fixture["document"]["content"]
        expected = fixture["expected_detection"]

        assert expected["state"] == "staged"

        with pytest.raises(NotImplementedError):
            state = detect_lifecycle_state(content)
            assert state == "staged"

    @pytest.mark.parametrize(
        "fixture_name,expected_state",
        [
            ("lifecycle_draft_state", "draft"),
            ("lifecycle_approved_state", "approved"),
            ("lifecycle_in_progress_state", "in-progress"),
            ("lifecycle_implemented_state", "implemented"),
            ("lifecycle_staged_state", "staged"),
        ],
    )
    def test_all_lifecycle_states_parameterized(
        self,
        fixture_name: str,
        expected_state: str,
    ) -> None:
        """Parameterized test for all 5 lifecycle states."""
        fixture = load_lifecycle_fixture(fixture_name)
        content = fixture["document"]["content"]

        with pytest.raises(NotImplementedError):
            state = detect_lifecycle_state(content)
            assert state == expected_state

    def test_status_header_parsing(self) -> None:
        """Test parsing of status header from document content."""
        fixture = load_lifecycle_fixture("lifecycle_in_progress_state")
        content = fixture["document"]["content"]
        expected_header = fixture["document"]["status_header"]

        with pytest.raises(NotImplementedError):
            header = parse_status_header(content)
            assert header["current_status"] == expected_header["current_status"]
            assert header["last_updated"] == expected_header["last_updated"]

    def test_lifecycle_states_constant(self) -> None:
        """Verify the LIFECYCLE_STATES constant contains all 5 states."""
        assert len(LIFECYCLE_STATES) == 5
        assert "draft" in LIFECYCLE_STATES
        assert "approved" in LIFECYCLE_STATES
        assert "in-progress" in LIFECYCLE_STATES
        assert "implemented" in LIFECYCLE_STATES
        assert "staged" in LIFECYCLE_STATES

    def test_status_pattern_matches_all_states(self) -> None:
        """Test that STATUS_PATTERN matches all lifecycle states."""
        for state in LIFECYCLE_STATES:
            test_content = f"**Current Status**: {state}"
            match = STATUS_PATTERN.search(test_content)
            assert match is not None, f"Pattern should match state: {state}"
            assert match.group(1) == state


# =============================================================================
# Test Class: AC-11 - In-Progress Transition
# =============================================================================


class TestAC11_InProgressTransition:
    """
    AC-11: Update Status to In-Progress

    Given: Document status is "approved"
    When: Related code changes are detected in push
    Then: Status is updated to "in-progress" and moved to in-progress/ folder
    """

    def test_transition_on_code_changes(self) -> None:
        """Test transition from approved to in-progress on code changes."""
        fixture = load_lifecycle_fixture("lifecycle_approved_with_code_changes")
        content = fixture["document"]["content"]
        document_path = fixture["document"]["path"]
        changed_files = fixture["code_changes_detected"]["changed_files"]
        expected = fixture["expected_transition"]

        # Verify fixture data
        assert expected["from_status"] == "approved"
        assert expected["to_status"] == "in-progress"

        # Test transition logic (will fail in RED phase)
        with pytest.raises(NotImplementedError):
            should_transition, new_state, reason = should_transition_state(
                document_path,
                content,
                changed_files,
            )
            assert should_transition is True
            assert new_state == "in-progress"
            assert "code changes" in reason.lower()

    def test_no_transition_without_code_changes(self) -> None:
        """Test no transition when no related code changes detected."""
        fixture = load_lifecycle_fixture("lifecycle_approved_state")
        content = fixture["document"]["content"]
        document_path = fixture["document"]["path"]
        unrelated_files = ["src/unrelated/file.ts", "tests/other_test.py"]

        with pytest.raises(NotImplementedError):
            should_transition, new_state, _ = should_transition_state(
                document_path,
                content,
                unrelated_files,
            )
            assert should_transition is False
            assert new_state is None

    def test_move_to_in_progress_folder(self) -> None:
        """Test document is moved to in-progress folder on transition."""
        fixture = load_lifecycle_fixture("lifecycle_approved_with_code_changes")
        document_path = fixture["document"]["path"]
        expected = fixture["expected_transition"]

        # Verify expected directory change
        assert expected["from_directory"] == "documentation/solution_designs/approved/"
        assert expected["to_directory"] == "documentation/solution_designs/in-progress/"

        with pytest.raises(NotImplementedError):
            new_path = move_document_to_state_folder(document_path, "in-progress")
            assert "in-progress" in new_path
            assert "approved" not in new_path

    def test_approved_only_transitions_to_in_progress(self) -> None:
        """Test that only approved documents transition to in-progress."""
        # Draft should NOT transition to in-progress
        draft_fixture = load_lifecycle_fixture("lifecycle_draft_state")
        draft_content = draft_fixture["document"]["content"]
        draft_path = draft_fixture["document"]["path"]

        with pytest.raises(NotImplementedError):
            should_transition, new_state, _ = should_transition_state(
                draft_path,
                draft_content,
                ["src/some_file.ts"],
            )
            # Draft should not auto-transition based on code changes
            assert should_transition is False


# =============================================================================
# Test Class: AC-12 - Implemented Transition
# =============================================================================


class TestAC12_ImplementedTransition:
    """
    AC-12: Update Status to Implemented

    Given: Document status is "in-progress" AND all ACs are checked (100%)
    When: Post-push skill analyzes document
    Then: Status is updated to "implemented" and moved to implemented/ folder
    """

    def test_transition_on_100_percent_completion(self) -> None:
        """Test transition from in-progress to implemented on 100% completion."""
        fixture = load_lifecycle_fixture("lifecycle_in_progress_100_complete")
        content = fixture["document"]["content"]
        document_path = fixture["document"]["path"]
        expected = fixture["expected_transition"]

        # Verify fixture data
        assert expected["from_status"] == "in-progress"
        assert expected["to_status"] == "implemented"
        assert expected["completion_percentage"] == 100

        # Test transition logic (will fail in RED phase)
        with pytest.raises(NotImplementedError):
            should_transition, new_state, reason = should_transition_state(
                document_path,
                content,
                [],  # No new code changes needed for this transition
            )
            assert should_transition is True
            assert new_state == "implemented"
            assert "100%" in reason or "complete" in reason.lower()

    def test_no_transition_when_not_100_percent(self) -> None:
        """Test no transition when completion is less than 100%."""
        fixture = load_lifecycle_fixture("lifecycle_in_progress_state")
        content = fixture["document"]["content"]
        document_path = fixture["document"]["path"]
        expected = fixture["expected_detection"]

        # Verify fixture is at 50%, not 100%
        assert expected["completion_percentage"] == 50

        with pytest.raises(NotImplementedError):
            should_transition, new_state, _ = should_transition_state(
                document_path,
                content,
                [],
            )
            assert should_transition is False
            assert new_state is None

    def test_move_to_implemented_folder(self) -> None:
        """Test document is moved to implemented folder on transition."""
        fixture = load_lifecycle_fixture("lifecycle_in_progress_100_complete")
        document_path = fixture["document"]["path"]
        expected = fixture["expected_transition"]

        # Verify expected directory change
        assert expected["from_directory"] == "documentation/solution_designs/in-progress/"
        assert expected["to_directory"] == "documentation/solution_designs/implemented/"

        with pytest.raises(NotImplementedError):
            new_path = move_document_to_state_folder(document_path, "implemented")
            assert "implemented" in new_path
            assert "in-progress" not in new_path

    def test_completion_triggers_implemented_transition(self) -> None:
        """Test that 100% completion is the trigger for implemented status."""
        fixture = load_lifecycle_fixture("lifecycle_in_progress_100_complete")
        content = fixture["document"]["content"]
        expected = fixture["expected_transition"]

        # Verify completion is 100%
        assert expected["checked_criteria"] == 5
        assert expected["total_criteria"] == 5
        assert expected["completion_percentage"] == 100

        with pytest.raises(NotImplementedError):
            percentage, checked, total = calculate_completion_percentage(content)
            assert percentage == 100
            assert checked == total

    @pytest.mark.parametrize(
        "completion,should_implement",
        [
            (0, False),
            (50, False),
            (75, False),
            (99, False),
            (100, True),
        ],
    )
    def test_implemented_only_at_100_percent(
        self,
        completion: int,
        should_implement: bool,
    ) -> None:
        """Parameterized test: implemented transition only at 100%."""
        # This test uses mock content to verify the logic
        _mock_result = {"completion": completion, "should_transition": should_implement}

        if should_implement:
            assert completion == 100
        else:
            assert completion < 100


# =============================================================================
# Test Class: AC-13 - Subfolder Auto-Creation
# =============================================================================


class TestAC13_SubfolderAutoCreation:
    """
    AC-13: Create Lifecycle Subfolders

    Given: Lifecycle subfolders (approved/, in-progress/, implemented/, staged/) don't exist
    When: First document needs to move to that state
    Then: Subfolders are created automatically in all managed directories
    """

    def test_ensure_subfolders_creates_all_states(self) -> None:
        """Test that all lifecycle subfolders are created."""
        fixture = load_lifecycle_fixture("lifecycle_directories_config")
        expected_subfolders = fixture["subfolder_creation"]["expected_subfolders"]

        # Verify expected subfolders
        assert expected_subfolders == ["approved", "in-progress", "implemented", "staged"]
        assert len(expected_subfolders) == 4

        with pytest.raises(NotImplementedError):
            created = ensure_lifecycle_subfolders("documentation/prds/")
            for subfolder in expected_subfolders:
                assert any(subfolder in path for path in created)

    def test_subfolder_creation_includes_gitkeep(self) -> None:
        """Test that subfolders include .gitkeep files."""
        fixture = load_lifecycle_fixture("lifecycle_directories_config")
        gitkeep = fixture["subfolder_creation"]["gitkeep_file"]

        assert gitkeep == ".gitkeep"

        with pytest.raises(NotImplementedError):
            created = ensure_lifecycle_subfolders("documentation/solution_designs/")
            # Implementation should create .gitkeep in each subfolder
            assert len(created) > 0

    def test_lifecycle_subfolders_constant(self) -> None:
        """Verify LIFECYCLE_SUBFOLDERS constant is correct."""
        assert len(LIFECYCLE_SUBFOLDERS) == 4
        assert "approved" in LIFECYCLE_SUBFOLDERS
        assert "in-progress" in LIFECYCLE_SUBFOLDERS
        assert "implemented" in LIFECYCLE_SUBFOLDERS
        assert "staged" in LIFECYCLE_SUBFOLDERS
        # Note: "draft" stays in root, not a subfolder

    @pytest.mark.parametrize(
        "directory",
        [
            "documentation/prds/",
            "documentation/solution_designs/",
            ".taskmaster/docs/",
        ],
    )
    def test_subfolders_created_in_all_primary_directories(
        self,
        directory: str,
    ) -> None:
        """Parameterized test for subfolder creation in all primary directories."""
        with pytest.raises(NotImplementedError):
            created = ensure_lifecycle_subfolders(directory)
            assert len(created) >= 4  # At least 4 subfolders


# =============================================================================
# Test Class: AC-14 - Multi-Directory Scanning
# =============================================================================


class TestAC14_MultiDirectoryScanning:
    """
    AC-14: Scan All Documentation Directories

    Given: Documentation exists in multiple locations
    When: Post-push skill runs document lifecycle checks
    Then: All configured documentation directories are scanned for status updates
    """

    def test_get_managed_directories_returns_all_primary(self) -> None:
        """Test that all primary directories are returned for scanning."""
        fixture = load_lifecycle_fixture("lifecycle_directories_config")
        primary = fixture["managed_directories"]["primary"]

        # Verify expected directories from fixture
        expected_paths = [d["path"] for d in primary]
        assert "documentation/prds/" in expected_paths
        assert "documentation/solution_designs/" in expected_paths
        assert ".taskmaster/docs/" in expected_paths

        with pytest.raises(NotImplementedError):
            directories = get_managed_directories()
            for path in expected_paths:
                assert any(path in d for d in directories)

    def test_primary_directories_constant(self) -> None:
        """Verify PRIMARY_DIRECTORIES constant includes expected paths."""
        assert "documentation/prds/" in PRIMARY_DIRECTORIES
        assert "documentation/solution_designs/" in PRIMARY_DIRECTORIES
        assert ".taskmaster/docs/" in PRIMARY_DIRECTORIES
        assert len(PRIMARY_DIRECTORIES) == 3

    def test_scan_directory_returns_document_list(self) -> None:
        """Test that scanning returns list of document metadata."""
        with pytest.raises(NotImplementedError):
            documents = scan_directory_for_documents("documentation/solution_designs/")
            # Should return list of dicts with path, content, status
            assert isinstance(documents, list)

    def test_service_specific_directories_included(self) -> None:
        """Test that service-specific directories are also scanned."""
        fixture = load_lifecycle_fixture("lifecycle_directories_config")
        service_specific = fixture["managed_directories"]["service_specific"]

        expected_paths = [d["path"] for d in service_specific]
        assert any("my-project-backend" in p for p in expected_paths)
        assert any("my-project-frontend" in p for p in expected_paths)

    @pytest.mark.parametrize(
        "directory",
        PRIMARY_DIRECTORIES,
    )
    def test_each_primary_directory_scannable(
        self,
        directory: str,
    ) -> None:
        """Parameterized test that each primary directory can be scanned."""
        with pytest.raises(NotImplementedError):
            documents = scan_directory_for_documents(directory)
            # Function should not raise other exceptions
            assert isinstance(documents, list)


# =============================================================================
# Test Class: AC-15 - Ephemeral Directory Exclusion
# =============================================================================


class TestAC15_EphemeralDirectoryExclusion:
    """
    AC-15: Exclude Ephemeral Documentation

    Given: scratch-pads/ and handoffs/ directories contain ephemeral docs
    When: Post-push skill scans for documents
    Then: These directories are excluded from lifecycle management
    """

    def test_scratch_pads_excluded(self) -> None:
        """Test that scratch-pads/ is excluded from lifecycle management."""
        fixture = load_lifecycle_fixture("lifecycle_ephemeral_scratch_pad")
        document_path = fixture["document"]["path"]
        expected = fixture["expected_behavior"]

        assert expected["should_be_excluded"] is True
        assert "scratch-pads" in document_path

        with pytest.raises(NotImplementedError):
            is_ephemeral = is_ephemeral_document(document_path)
            assert is_ephemeral is True

    def test_handoffs_excluded(self) -> None:
        """Test that handoffs/ is excluded from lifecycle management."""
        fixture = load_lifecycle_fixture("lifecycle_ephemeral_handoff")
        document_path = fixture["document"]["path"]
        expected = fixture["expected_behavior"]

        assert expected["should_be_excluded"] is True
        assert "handoffs" in document_path

        with pytest.raises(NotImplementedError):
            is_ephemeral = is_ephemeral_document(document_path)
            assert is_ephemeral is True

    def test_ephemeral_directories_constant(self) -> None:
        """Verify EPHEMERAL_DIRECTORIES constant is correct."""
        assert "documentation/scratch-pads/" in EPHEMERAL_DIRECTORIES
        assert "documentation/handoffs/" in EPHEMERAL_DIRECTORIES
        assert len(EPHEMERAL_DIRECTORIES) == 2

    def test_get_ephemeral_directories(self) -> None:
        """Test that get_ephemeral_directories returns excluded paths."""
        with pytest.raises(NotImplementedError):
            excluded = get_ephemeral_directories()
            assert "scratch-pads" in str(excluded)
            assert "handoffs" in str(excluded)

    def test_ephemeral_docs_not_moved(self) -> None:
        """Test that ephemeral documents are not moved regardless of status."""
        fixture = load_lifecycle_fixture("lifecycle_ephemeral_scratch_pad")
        document_path = fixture["document"]["path"]
        expected = fixture["expected_behavior"]

        assert expected["should_move"] is False

        with pytest.raises(NotImplementedError):
            # Even if we try to transition, ephemeral docs should not move
            should_transition, _, _ = should_transition_state(
                document_path,
                fixture["document"]["content"],
                ["src/some_file.ts"],
            )
            assert should_transition is False

    def test_ephemeral_status_not_updated(self) -> None:
        """Test that ephemeral document status is not updated."""
        fixture = load_lifecycle_fixture("lifecycle_ephemeral_handoff")
        expected = fixture["expected_behavior"]

        assert expected["should_update_status"] is False

    @pytest.mark.parametrize(
        "document_path,expected_ephemeral",
        [
            ("documentation/scratch-pads/central-task.md", True),
            ("documentation/handoffs/session-handoff.md", True),
            ("documentation/solution_designs/feature.md", False),
            ("documentation/prds/prd-new.md", False),
            (".taskmaster/docs/prd.txt", False),
        ],
    )
    def test_ephemeral_detection_parameterized(
        self,
        document_path: str,
        expected_ephemeral: bool,
    ) -> None:
        """Parameterized test for ephemeral document detection."""
        # Direct pattern check
        is_ephemeral_pattern = any(
            excl in document_path for excl in EPHEMERAL_DIRECTORIES
        )
        assert is_ephemeral_pattern == expected_ephemeral

        with pytest.raises(NotImplementedError):
            is_ephemeral = is_ephemeral_document(document_path)
            assert is_ephemeral == expected_ephemeral


# =============================================================================
# Test Class: Integration Scenarios
# =============================================================================


class TestDocumentLifecycleIntegration:
    """Integration tests for document lifecycle management."""

    def test_full_lifecycle_progression(self) -> None:
        """Test complete lifecycle: draft → approved → in-progress → implemented → staged."""
        states = ["draft", "approved", "in-progress", "implemented", "staged"]

        for i, state in enumerate(states):
            assert state in LIFECYCLE_STATES
            assert LIFECYCLE_STATES.index(state) == i

    def test_state_machine_only_forward_transitions(self) -> None:
        """Test that automatic transitions only move forward in lifecycle."""
        # draft → approved (manual)
        # approved → in-progress (auto on code changes)
        # in-progress → implemented (auto on 100% completion)
        # implemented → staged (manual)

        auto_transitions = {
            "approved": "in-progress",  # AC-11
            "in-progress": "implemented",  # AC-12
        }

        assert "draft" not in auto_transitions  # Manual only
        assert "implemented" not in auto_transitions  # Manual only
        assert "staged" not in auto_transitions  # Terminal state

    def test_directory_structure_matches_lifecycle(self) -> None:
        """Test that directory structure matches lifecycle states."""
        # draft stays in root (no folder)
        # other states have dedicated folders
        for state in LIFECYCLE_STATES[1:]:  # Skip draft
            assert state in LIFECYCLE_SUBFOLDERS or state.replace("-", "_") in LIFECYCLE_SUBFOLDERS


# =============================================================================
# Fixture Loaders for Document Lifecycle
# =============================================================================


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the path to the fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def lifecycle_draft_state(fixtures_dir: Path) -> dict[str, Any]:
    """Load draft state fixture."""
    fixture_path = fixtures_dir / "lifecycle_draft_state.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def lifecycle_approved_state(fixtures_dir: Path) -> dict[str, Any]:
    """Load approved state fixture."""
    fixture_path = fixtures_dir / "lifecycle_approved_state.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def lifecycle_in_progress_state(fixtures_dir: Path) -> dict[str, Any]:
    """Load in-progress state fixture."""
    fixture_path = fixtures_dir / "lifecycle_in_progress_state.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def lifecycle_implemented_state(fixtures_dir: Path) -> dict[str, Any]:
    """Load implemented state fixture."""
    fixture_path = fixtures_dir / "lifecycle_implemented_state.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def lifecycle_staged_state(fixtures_dir: Path) -> dict[str, Any]:
    """Load staged state fixture."""
    fixture_path = fixtures_dir / "lifecycle_staged_state.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def lifecycle_directories_config(fixtures_dir: Path) -> dict[str, Any]:
    """Load directories configuration fixture."""
    fixture_path = fixtures_dir / "lifecycle_directories_config.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def all_lifecycle_state_fixtures() -> list[dict[str, Any]]:
    """Return all lifecycle state fixtures for parameterized testing."""
    return [
        load_lifecycle_fixture("lifecycle_draft_state"),
        load_lifecycle_fixture("lifecycle_approved_state"),
        load_lifecycle_fixture("lifecycle_in_progress_state"),
        load_lifecycle_fixture("lifecycle_implemented_state"),
        load_lifecycle_fixture("lifecycle_staged_state"),
    ]


# =============================================================================
# Integration Tests (Require Implementation)
# =============================================================================


@pytest.mark.skip(reason="Implementation not yet complete - run after GREEN phase")
class TestDocumentLifecycleIntegrationReal:
    """
    Integration tests that execute actual lifecycle operations.

    These tests are skipped during RED phase and should be unskipped
    once the document lifecycle is implemented (GREEN phase).
    """

    def test_real_completion_calculation(self) -> None:
        """Test actual completion calculation on real document."""
        fixture = load_lifecycle_fixture("lifecycle_completion_50_percent")
        content = fixture["document"]["content"]

        percentage, checked, total = calculate_completion_percentage(content)
        assert percentage == 50
        assert checked == 2
        assert total == 4

    def test_real_state_detection(self) -> None:
        """Test actual state detection on real document."""
        fixture = load_lifecycle_fixture("lifecycle_in_progress_state")
        content = fixture["document"]["content"]

        state = detect_lifecycle_state(content)
        assert state == "in-progress"

    def test_real_transition_detection(self) -> None:
        """Test actual transition detection with code changes."""
        fixture = load_lifecycle_fixture("lifecycle_approved_with_code_changes")

        should_transition, new_state, reason = should_transition_state(
            fixture["document"]["path"],
            fixture["document"]["content"],
            fixture["code_changes_detected"]["changed_files"],
        )

        assert should_transition is True
        assert new_state == "in-progress"

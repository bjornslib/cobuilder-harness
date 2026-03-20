"""Tests for Rule 17: Mandatory graph attributes (cobuilder_root + target_dir).

Tests verify that:
1. cobuilder_root is mandatory and must be absolute path to existing directory
2. target_dir is mandatory and must be absolute path to existing directory
3. Both attributes are validated by _check_required_graph_attrs()
4. Missing attributes raise ERROR severity violations
5. Relative paths raise ERROR severity violations
6. Non-existent directories raise ERROR severity violations
"""

from __future__ import annotations

from pathlib import Path

from cobuilder.engine.validation import validate_graph, Severity
from tests.engine.validation.conftest import make_node, make_edge, make_graph


class TestMandatoryGraphAttrs:
    """Test Rule 17: cobuilder_root and target_dir are mandatory graph attributes."""

    def test_missing_cobuilder_root_is_error(self, tmp_path: Path) -> None:
        """Missing cobuilder_root raises ERROR violation."""
        nodes = [
            make_node("start", shape="Mdiamond"),
            make_node("end", shape="Msquare"),
        ]
        edges = [make_edge("start", "end")]

        # Create a valid target_dir but omit cobuilder_root
        target_dir = str(tmp_path / "target")
        Path(target_dir).mkdir()

        graph = make_graph(nodes, edges, target_dir=target_dir)
        result = validate_graph(graph)

        errors = result.errors
        assert any(
            "cobuilder_root" in v.message and "required" in v.message.lower()
            for v in errors
        ), f"Expected 'missing cobuilder_root' error, got: {[v.message for v in errors]}"

    def test_missing_target_dir_is_error(self, tmp_path: Path) -> None:
        """Missing target_dir raises ERROR violation."""
        nodes = [
            make_node("start", shape="Mdiamond"),
            make_node("end", shape="Msquare"),
        ]
        edges = [make_edge("start", "end")]

        # Create a valid cobuilder_root but omit target_dir
        cobuilder_root = str(tmp_path / "cobuilder")
        Path(cobuilder_root).mkdir()

        graph = make_graph(nodes, edges, cobuilder_root=cobuilder_root)
        result = validate_graph(graph)

        errors = result.errors
        assert any(
            "target_dir" in v.message and "required" in v.message.lower()
            for v in errors
        ), f"Expected 'missing target_dir' error, got: {[v.message for v in errors]}"

    def test_both_missing_is_error(self) -> None:
        """Missing both attributes raises ERROR violations for both."""
        nodes = [
            make_node("start", shape="Mdiamond"),
            make_node("end", shape="Msquare"),
        ]
        edges = [make_edge("start", "end")]

        graph = make_graph(nodes, edges)  # No graph attrs
        result = validate_graph(graph)

        errors = result.errors
        error_messages = [v.message for v in errors]

        assert any("cobuilder_root" in msg for msg in error_messages)
        assert any("target_dir" in msg for msg in error_messages)

    def test_relative_cobuilder_root_is_error(self, tmp_path: Path) -> None:
        """Relative path for cobuilder_root raises ERROR."""
        nodes = [
            make_node("start", shape="Mdiamond"),
            make_node("end", shape="Msquare"),
        ]
        edges = [make_edge("start", "end")]

        target_dir = str(tmp_path / "target")
        Path(target_dir).mkdir()

        graph = make_graph(
            nodes, edges,
            cobuilder_root="./relative/path",  # Relative path
            target_dir=target_dir,
        )
        result = validate_graph(graph)

        errors = result.errors
        assert any(
            "cobuilder_root" in v.message and "absolute" in v.message.lower()
            for v in errors
        ), f"Expected 'absolute path' error for cobuilder_root, got: {[v.message for v in errors]}"

    def test_relative_target_dir_is_error(self, tmp_path: Path) -> None:
        """Relative path for target_dir raises ERROR."""
        nodes = [
            make_node("start", shape="Mdiamond"),
            make_node("end", shape="Msquare"),
        ]
        edges = [make_edge("start", "end")]

        cobuilder_root = str(tmp_path / "cobuilder")
        Path(cobuilder_root).mkdir()

        graph = make_graph(
            nodes, edges,
            cobuilder_root=cobuilder_root,
            target_dir="../relative/path",  # Relative path
        )
        result = validate_graph(graph)

        errors = result.errors
        assert any(
            "target_dir" in v.message and "absolute" in v.message.lower()
            for v in errors
        ), f"Expected 'absolute path' error for target_dir, got: {[v.message for v in errors]}"

    def test_nonexistent_cobuilder_root_is_error(self, tmp_path: Path) -> None:
        """Non-existent directory for cobuilder_root raises ERROR."""
        nodes = [
            make_node("start", shape="Mdiamond"),
            make_node("end", shape="Msquare"),
        ]
        edges = [make_edge("start", "end")]

        target_dir = str(tmp_path / "target")
        Path(target_dir).mkdir()

        nonexistent = str(tmp_path / "does" / "not" / "exist")

        graph = make_graph(
            nodes, edges,
            cobuilder_root=nonexistent,  # Non-existent
            target_dir=target_dir,
        )
        result = validate_graph(graph)

        errors = result.errors
        assert any(
            "cobuilder_root" in v.message and ("non-existent" in v.message.lower() or "does not exist" in v.message.lower())
            for v in errors
        ), f"Expected 'non-existent directory' error, got: {[v.message for v in errors]}"

    def test_nonexistent_target_dir_is_error(self, tmp_path: Path) -> None:
        """Non-existent directory for target_dir raises ERROR."""
        nodes = [
            make_node("start", shape="Mdiamond"),
            make_node("end", shape="Msquare"),
        ]
        edges = [make_edge("start", "end")]

        cobuilder_root = str(tmp_path / "cobuilder")
        Path(cobuilder_root).mkdir()

        nonexistent = str(tmp_path / "missing" / "dir")

        graph = make_graph(
            nodes, edges,
            cobuilder_root=cobuilder_root,
            target_dir=nonexistent,  # Non-existent
        )
        result = validate_graph(graph)

        errors = result.errors
        assert any(
            "target_dir" in v.message and ("non-existent" in v.message.lower() or "does not exist" in v.message.lower())
            for v in errors
        ), f"Expected 'non-existent directory' error, got: {[v.message for v in errors]}"

    def test_valid_both_attrs_passes(self, tmp_path: Path) -> None:
        """Valid cobuilder_root and target_dir pass validation."""
        nodes = [
            make_node("start", shape="Mdiamond"),
            make_node("impl", shape="box", handler="codergen"),
            make_node("end", shape="Msquare"),
        ]
        edges = [
            make_edge("start", "impl"),
            make_edge("impl", "end"),
        ]

        cobuilder_root = str(tmp_path / "cobuilder")
        target_dir = str(tmp_path / "target")
        Path(cobuilder_root).mkdir()
        Path(target_dir).mkdir()

        graph = make_graph(
            nodes, edges,
            cobuilder_root=cobuilder_root,
            target_dir=target_dir,
        )
        result = validate_graph(graph)

        # Check that there are no mandatory attr errors
        errors = result.errors
        mandatory_attr_errors = [
            v for v in errors
            if "cobuilder_root" in v.message or "target_dir" in v.message
        ]
        assert len(mandatory_attr_errors) == 0, (
            f"Expected no mandatory attr errors, got: "
            f"{[v.message for v in mandatory_attr_errors]}"
        )

    def test_error_severity_for_missing_cobuilder_root(self, tmp_path: Path) -> None:
        """Missing cobuilder_root violation has ERROR severity."""
        nodes = [make_node("start", shape="Mdiamond"), make_node("end", shape="Msquare")]
        edges = [make_edge("start", "end")]

        target_dir = str(tmp_path / "target")
        Path(target_dir).mkdir()

        graph = make_graph(nodes, edges, target_dir=target_dir)
        result = validate_graph(graph)

        violations = [
            v for v in result.violations
            if "cobuilder_root" in v.message and "required" in v.message.lower()
        ]
        assert len(violations) > 0
        assert all(v.severity == Severity.ERROR for v in violations)

    def test_error_severity_for_missing_target_dir(self, tmp_path: Path) -> None:
        """Missing target_dir violation has ERROR severity."""
        nodes = [make_node("start", shape="Mdiamond"), make_node("end", shape="Msquare")]
        edges = [make_edge("start", "end")]

        cobuilder_root = str(tmp_path / "cobuilder")
        Path(cobuilder_root).mkdir()

        graph = make_graph(nodes, edges, cobuilder_root=cobuilder_root)
        result = validate_graph(graph)

        violations = [
            v for v in result.violations
            if "target_dir" in v.message and "required" in v.message.lower()
        ]
        assert len(violations) > 0
        assert all(v.severity == Severity.ERROR for v in violations)

    def test_empty_string_cobuilder_root_treated_as_missing(self, tmp_path: Path) -> None:
        """Empty string for cobuilder_root is treated as missing."""
        nodes = [make_node("start", shape="Mdiamond"), make_node("end", shape="Msquare")]
        edges = [make_edge("start", "end")]

        target_dir = str(tmp_path / "target")
        Path(target_dir).mkdir()

        graph = make_graph(nodes, edges, cobuilder_root="", target_dir=target_dir)
        result = validate_graph(graph)

        errors = result.errors
        assert any(
            "cobuilder_root" in v.message and "required" in v.message.lower()
            for v in errors
        )

    def test_empty_string_target_dir_treated_as_missing(self, tmp_path: Path) -> None:
        """Empty string for target_dir is treated as missing."""
        nodes = [make_node("start", shape="Mdiamond"), make_node("end", shape="Msquare")]
        edges = [make_edge("start", "end")]

        cobuilder_root = str(tmp_path / "cobuilder")
        Path(cobuilder_root).mkdir()

        graph = make_graph(nodes, edges, cobuilder_root=cobuilder_root, target_dir="")
        result = validate_graph(graph)

        errors = result.errors
        assert any(
            "target_dir" in v.message and "required" in v.message.lower()
            for v in errors
        )

    def test_file_path_instead_of_directory_cobuilder_root(self, tmp_path: Path) -> None:
        """File path (not directory) for cobuilder_root raises ERROR."""
        nodes = [make_node("start", shape="Mdiamond"), make_node("end", shape="Msquare")]
        edges = [make_edge("start", "end")]

        target_dir = str(tmp_path / "target")
        Path(target_dir).mkdir()

        # Create a file instead of directory
        file_path = tmp_path / "file.txt"
        file_path.write_text("test")

        graph = make_graph(
            nodes, edges,
            cobuilder_root=str(file_path),  # File, not directory
            target_dir=target_dir,
        )
        result = validate_graph(graph)

        errors = result.errors
        assert any(
            "cobuilder_root" in v.message and ("directory" in v.message.lower() or "does not exist" in v.message.lower())
            for v in errors
        )

    def test_file_path_instead_of_directory_target_dir(self, tmp_path: Path) -> None:
        """File path (not directory) for target_dir raises ERROR."""
        nodes = [make_node("start", shape="Mdiamond"), make_node("end", shape="Msquare")]
        edges = [make_edge("start", "end")]

        cobuilder_root = str(tmp_path / "cobuilder")
        Path(cobuilder_root).mkdir()

        # Create a file instead of directory
        file_path = tmp_path / "file.txt"
        file_path.write_text("test")

        graph = make_graph(
            nodes, edges,
            cobuilder_root=cobuilder_root,
            target_dir=str(file_path),  # File, not directory
        )
        result = validate_graph(graph)

        errors = result.errors
        assert any(
            "target_dir" in v.message and ("directory" in v.message.lower() or "does not exist" in v.message.lower())
            for v in errors
        )

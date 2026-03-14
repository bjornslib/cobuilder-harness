"""Tests for the actual template library — validates that real templates render correctly."""
from __future__ import annotations

from pathlib import Path

import pytest

# Real templates directory
_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / ".cobuilder" / "templates"


def _skip_if_no_jinja2():
    try:
        import jinja2
    except ImportError:
        pytest.skip("jinja2 not installed")


def _skip_if_no_yaml():
    try:
        import yaml
    except ImportError:
        pytest.skip("pyyaml not installed")


class TestSequentialValidatedTemplate:
    def test_renders_single_worker(self) -> None:
        _skip_if_no_jinja2()
        _skip_if_no_yaml()
        from cobuilder.templates.instantiator import instantiate_template

        result = instantiate_template(
            "sequential-validated",
            {
                "prd_ref": "PRD-TEST-001",
                "worker": {
                    "label": "Backend Auth",
                    "worker_type": "backend-solutions-engineer",
                    "bead_id": "TASK-10",
                    "acceptance": "JWT auth works",
                },
            },
            templates_dir=_TEMPLATES_DIR,
            validate=False,
        )
        assert 'prd_ref="PRD-TEST-001"' in result
        assert '_template="sequential-validated"' in result
        assert "Backend Auth" in result
        assert "TASK-10" in result
        assert "shape=Mdiamond" in result
        assert "shape=Msquare" in result
        assert "shape=box" in result
        assert "shape=hexagon" in result

    def test_renders_with_research(self) -> None:
        _skip_if_no_jinja2()
        _skip_if_no_yaml()
        from cobuilder.templates.instantiator import instantiate_template

        result = instantiate_template(
            "sequential-validated",
            {
                "prd_ref": "PRD-TEST-001",
                "include_research": True,
                "worker": {
                    "label": "Backend Auth",
                    "worker_type": "backend-solutions-engineer",
                    "bead_id": "TASK-10",
                    "acceptance": "JWT auth works",
                },
            },
            templates_dir=_TEMPLATES_DIR,
            validate=False,
        )
        assert "shape=tab" in result  # Research node present
        assert "findings ready" in result

    def test_constraint_validation_passes(self) -> None:
        """The sequential-validated template should pass its own constraints."""
        _skip_if_no_jinja2()
        _skip_if_no_yaml()
        from cobuilder.templates.instantiator import instantiate_template

        # Should not raise
        instantiate_template(
            "sequential-validated",
            {
                "prd_ref": "PRD-TEST-001",
                "worker": {
                    "label": "Backend Auth",
                    "worker_type": "backend-solutions-engineer",
                    "bead_id": "TASK-10",
                    "acceptance": "JWT auth works",
                },
            },
            templates_dir=_TEMPLATES_DIR,
            validate=True,
        )


class TestHubSpokeTemplate:
    def test_renders_single_worker(self) -> None:
        _skip_if_no_jinja2()
        _skip_if_no_yaml()
        from cobuilder.templates.instantiator import instantiate_template

        result = instantiate_template(
            "hub-spoke",
            {
                "prd_ref": "PRD-HS-001",
                "workers": [
                    {
                        "label": "Auth API",
                        "worker_type": "backend-solutions-engineer",
                        "bead_id": "TASK-20",
                        "acceptance": "Auth endpoint works",
                    },
                ],
                "include_e2e": False,
            },
            templates_dir=_TEMPLATES_DIR,
            validate=False,
        )
        assert 'prd_ref="PRD-HS-001"' in result
        assert "Auth API" in result
        # Single worker: no parallel/fan-in
        assert "shape=component" not in result
        assert "shape=tripleoctagon" not in result

    def test_renders_multiple_workers_with_parallelism(self) -> None:
        _skip_if_no_jinja2()
        _skip_if_no_yaml()
        from cobuilder.templates.instantiator import instantiate_template

        result = instantiate_template(
            "hub-spoke",
            {
                "prd_ref": "PRD-HS-002",
                "workers": [
                    {
                        "label": "Auth API",
                        "worker_type": "backend-solutions-engineer",
                        "bead_id": "TASK-20",
                        "acceptance": "Auth works",
                    },
                    {
                        "label": "Login UI",
                        "worker_type": "frontend-dev-expert",
                        "bead_id": "TASK-21",
                        "acceptance": "Login form works",
                    },
                ],
            },
            templates_dir=_TEMPLATES_DIR,
            validate=False,
        )
        assert "shape=component" in result  # Parallel fan-out
        assert "shape=tripleoctagon" in result  # Fan-in
        assert "Auth API" in result
        assert "Login UI" in result

    def test_includes_e2e_by_default(self) -> None:
        _skip_if_no_jinja2()
        _skip_if_no_yaml()
        from cobuilder.templates.instantiator import instantiate_template

        result = instantiate_template(
            "hub-spoke",
            {
                "prd_ref": "PRD-HS-003",
                "workers": [
                    {
                        "label": "Task A",
                        "worker_type": "backend-solutions-engineer",
                        "bead_id": "TASK-30",
                        "acceptance": "Works",
                    },
                ],
            },
            templates_dir=_TEMPLATES_DIR,
            validate=False,
        )
        assert "E2E Integration" in result
        assert "tdd-test-engineer" in result


class TestS3LifecycleTemplate:
    def test_renders_lifecycle_graph(self) -> None:
        _skip_if_no_jinja2()
        _skip_if_no_yaml()
        from cobuilder.templates.instantiator import instantiate_template

        result = instantiate_template(
            "s3-lifecycle",
            {
                "prd_ref": "PRD-S3-001",
                "prd_path": "docs/PRD-S3-001.md",
                "target_repo": "/path/to/repo",
            },
            templates_dir=_TEMPLATES_DIR,
            validate=False,
        )
        assert '_template="s3-lifecycle"' in result
        assert "RESEARCH" in result
        assert "REFINE" in result
        assert "PLAN" in result
        assert "EXECUTE" in result
        assert "VALIDATE" in result
        assert "Goals" in result
        assert "shape=house" in result  # Manager loop
        assert 'mode="spawn_pipeline"' in result
        assert "loop_restart=true" in result  # Cyclic edge

    def test_lifecycle_has_all_node_types(self) -> None:
        _skip_if_no_jinja2()
        _skip_if_no_yaml()
        from cobuilder.templates.instantiator import instantiate_template

        result = instantiate_template(
            "s3-lifecycle",
            {
                "prd_ref": "PRD-S3-002",
                "prd_path": "docs/PRD-S3-002.md",
                "target_repo": "/path/to/repo",
                "max_cycles": 5,
            },
            templates_dir=_TEMPLATES_DIR,
            validate=False,
        )
        # Entry + exit
        assert "shape=Mdiamond" in result
        assert "shape=Msquare" in result
        # Research
        assert "shape=tab" in result
        # LLM nodes
        assert "shape=box" in result
        # Manager loop (execute)
        assert "shape=house" in result
        # Validation gate
        assert "shape=hexagon" in result
        # Conditional
        assert "shape=diamond" in result

    def test_lifecycle_with_deploy(self) -> None:
        _skip_if_no_jinja2()
        _skip_if_no_yaml()
        from cobuilder.templates.instantiator import instantiate_template

        result = instantiate_template(
            "s3-lifecycle",
            {
                "prd_ref": "PRD-S3-003",
                "prd_path": "docs/PRD-S3-003.md",
                "target_repo": "/path/to/repo",
                "deploy_command": "railway up",
            },
            templates_dir=_TEMPLATES_DIR,
            validate=False,
        )
        assert "DEPLOY" in result
        assert "railway up" in result
        assert "shape=parallelogram" in result  # Deploy tool node

    def test_lifecycle_without_deploy(self) -> None:
        _skip_if_no_jinja2()
        _skip_if_no_yaml()
        from cobuilder.templates.instantiator import instantiate_template

        result = instantiate_template(
            "s3-lifecycle",
            {
                "prd_ref": "PRD-S3-004",
                "prd_path": "docs/PRD-S3-004.md",
                "target_repo": "/path/to/repo",
            },
            templates_dir=_TEMPLATES_DIR,
            validate=False,
        )
        assert "DEPLOY" not in result
        assert "shape=parallelogram" not in result

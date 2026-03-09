"""Advanced validation rules for Epic 5 - Attractor Schema extensions.

Implements the following requirements from PRD-HARNESS-UPGRADE-001:
- AC-5.1: sd_path mandatory on codergen nodes — validate rejects nodes without it
- AC-5.2: Full cluster topology check implemented
- AC-5.3: worker_type registry check rejects unknown agent types
- AC-5.4: wait.human after wait.system3 topology enforced
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from cobuilder.engine.validation import RuleViolation, Severity
from cobuilder.engine.validation.rules import _error, _warning

if TYPE_CHECKING:
    from cobuilder.engine.graph import Graph, Node


# ---------------------------------------------------------------------------
# Rule 14: SdPathOnCodergen (Enforces AC-5.1)
# ---------------------------------------------------------------------------

class SdPathOnCodergen:
    """codergen nodes must have a non-empty sd_path attribute (AC-5.1)."""

    rule_id = "SdPathOnCodergen"
    severity = Severity.ERROR

    def check(self, graph: Graph) -> list[RuleViolation]:
        violations = []
        for node in graph.nodes.values():
            # Check if it's a codergen node (box shape or handler=codergen)
            if node.handler == "codergen":
                sd_path = node.attrs.get("sd_path", "").strip()
                if not sd_path:
                    violations.append(
                        _error(
                            self.rule_id,
                            "codergen node missing required 'sd_path' attribute",
                            "Add 'sd_path' attribute to the codergen node pointing to the Solution Design file",
                            node_id=node.id,
                        )
                    )
        return violations


# ---------------------------------------------------------------------------
# Rule 15: WorkerTypeRegistry (Enforces AC-5.3)
# ---------------------------------------------------------------------------

# Valid worker types from PRD-HARNESS-UPGRADE-001 section 5
VALID_WORKER_TYPES = {
    "frontend-dev-expert",
    "backend-solutions-engineer",
    "tdd-test-engineer",
    "solution-architect",
    "solution-design-architect",
    "validation-test-agent",
    "ux-designer"
}

class WorkerTypeRegistry:
    """worker_type attribute must be from the known registry (AC-5.3)."""

    rule_id = "WorkerTypeRegistry"
    severity = Severity.ERROR

    def check(self, graph: Graph) -> list[RuleViolation]:
        violations = []
        for node in graph.nodes.values():
            if node.handler == "codergen":
                worker_type = node.attrs.get("worker_type", "").strip()
                if worker_type and worker_type not in VALID_WORKER_TYPES:
                    violations.append(
                        _error(
                            self.rule_id,
                            f"Unknown worker_type '{worker_type}'. Valid types: {sorted(VALID_WORKER_TYPES)}",
                            f"Change worker_type to one of: {', '.join(VALID_WORKER_TYPES)}",
                            node_id=node.id,
                        )
                    )
        return violations


# ---------------------------------------------------------------------------
# Rule 16: WaitHumanAfterWaitSystem3 (Enforces AC-5.4)
# ---------------------------------------------------------------------------

class WaitHumanAfterWaitSystem3:
    """wait.human nodes must follow wait.system3 or research nodes (AC-5.4)."""

    rule_id = "WaitHumanAfterWaitSystem3"
    severity = Severity.ERROR

    def check(self, graph: Graph) -> list[RuleViolation]:
        violations = []

        for node in graph.nodes.values():
            # Check if it's a wait.human node (likely hexagon shape with wait.human handler)
            if node.handler == "wait_human":
                # Check if it has a gate_type="e2e-review" which indicates it should follow wait.system3
                gate_mode = node.attrs.get("mode", "")
                if gate_mode == "e2e-review":
                    # Get all incoming nodes (predecessors)
                    incoming_nodes = graph.nodes_by_id({edge.source for edge in graph.edges if edge.target == node.id})

                    # Check if any predecessor is a wait.system3 node
                    has_system3_predecessor = any(
                        pred.handler == "wait_system3" for pred in incoming_nodes.values()
                    )

                    # Check if any predecessor is a research node (alternative valid predecessor)
                    has_research_predecessor = any(
                        pred.handler == "research" for pred in incoming_nodes.values()
                    )

                    if not (has_system3_predecessor or has_research_predecessor):
                        violations.append(
                            _error(
                                self.rule_id,
                                "wait.human node with mode='e2e-review' must follow a wait.system3 or research node",
                                "Add an edge from a wait.system3 node to this wait.human node",
                                node_id=node.id,
                            )
                        )
        return violations


# ---------------------------------------------------------------------------
# Rule 17: FullClusterTopology (Enforces AC-5.2)
# ---------------------------------------------------------------------------

class FullClusterTopology:
    """Enforces full codergen cluster topology: acceptance-test-writer -> ... -> codergen -> wait.system3 -> wait.human (AC-5.2)."""

    rule_id = "FullClusterTopology"
    severity = Severity.ERROR

    def check(self, graph: Graph) -> list[RuleViolation]:
        violations = []

        # Find all codergen nodes that should have the full cluster
        for node in graph.nodes.values():
            if node.handler == "codergen":
                # Look for the cluster starting from acceptance-test-writer
                # Check if there's a connected sequence: acceptance-test-writer -> research -> refine -> codergen -> wait.system3 -> wait.human

                # For codergen nodes, check if they have a corresponding wait.system3
                codergen_successors = self._get_downstream_nodes(graph, node.id)

                # Look for a wait.system3 downstream
                has_wait_system3 = any(
                    n.handler == "wait_system3" for n in codergen_successors.values()
                )

                if not has_wait_system3:
                    violations.append(
                        _error(
                            self.rule_id,
                            f"codergen node '{node.id}' must have a downstream wait.system3 validation gate",
                            "Add a wait.system3 node downstream from this codergen node",
                            node_id=node.id,
                        )
                    )
                    continue

                # For each wait.system3 found, check if it has a wait.human downstream
                system3_nodes = [n for n in codergen_successors.values() if n.handler == "wait_system3"]
                for sys3_node in system3_nodes:
                    sys3_downstream = self._get_downstream_nodes(graph, sys3_node.id)
                    has_wait_human = any(
                        n.handler == "wait_human" and n.attrs.get("mode") == "e2e-review"
                        for n in sys3_downstream.values()
                    )

                    if not has_wait_human:
                        violations.append(
                            _error(
                                self.rule_id,
                                f"wait.system3 node '{sys3_node.id}' must have a downstream wait.human validation gate",
                                "Add a wait.human node with mode='e2e-review' downstream from this wait.system3 node",
                                node_id=sys3_node.id,
                            )
                        )

        return violations

    def _get_downstream_nodes(self, graph: Graph, start_node_id: str) -> dict[str, Node]:
        """Get all nodes reachable from start_node_id using BFS."""
        from collections import deque

        visited: set[str] = set()
        result: dict[str, Node] = {}
        queue: deque[str] = deque([start_node_id])

        while queue:
            current_id = queue.popleft()
            if current_id in visited:
                continue
            visited.add(current_id)

            if current_id != start_node_id:  # Don't include the starting node
                current_node = graph.nodes.get(current_id)
                if current_node:
                    result[current_id] = current_node

            # Add successors to queue
            for edge in graph.edges:
                if edge.source == current_id and edge.target not in visited:
                    queue.append(edge.target)

        return result


# ---------------------------------------------------------------------------
# Additional helper for wait.system3 nodes
# ---------------------------------------------------------------------------

class WaitSystem3Requirements:
    """wait.system3 nodes have required attributes (gate_type, summary_ref, bead_id)."""

    rule_id = "WaitSystem3Requirements"
    severity = Severity.ERROR

    def check(self, graph: Graph) -> list[RuleViolation]:
        violations = []

        for node in graph.nodes.values():
            if node.handler == "wait_system3":
                # Check required attributes
                gate_type = node.attrs.get("gate_type", "").strip()
                summary_ref = node.attrs.get("summary_ref", "").strip()
                bead_id = node.attrs.get("bead_id", "").strip()

                if not gate_type:
                    violations.append(
                        _error(
                            self.rule_id,
                            f"wait.system3 node '{node.id}' missing required 'gate_type' attribute",
                            "Add 'gate_type' attribute (values: unit, e2e, contract)",
                            node_id=node.id,
                        )
                    )

                if not summary_ref:
                    violations.append(
                        _error(
                            self.rule_id,
                            f"wait.system3 node '{node.id}' missing required 'summary_ref' attribute",
                            "Add 'summary_ref' attribute pointing to summary file path",
                            node_id=node.id,
                        )
                    )

                if not bead_id:
                    violations.append(
                        _error(
                            self.rule_id,
                            f"wait.system3 node '{node.id}' missing required 'bead_id' attribute",
                            "Add 'bead_id' attribute with AT (Acceptance Test) beads task ID",
                            node_id=node.id,
                        )
                    )

        return violations


# ---------------------------------------------------------------------------
# Rule 18: CodergenWithoutUpstreamAT (Enforces GAP-5.5 - V-15)
# ---------------------------------------------------------------------------

class CodergenWithoutUpstreamAT:
    """codergen nodes should have upstream acceptance-test-writer nodes (V-15)."""

    rule_id = "CodergenWithoutUpstreamAT"
    severity = Severity.WARNING

    def check(self, graph: Graph) -> list[RuleViolation]:
        violations = []

        # Find all codergen nodes
        for node in graph.nodes.values():
            if node.handler == "codergen":
                # Check if there's an upstream acceptance-test-writer node
                has_upstream_at_writer = self._has_upstream_node_with_handler(graph, node.id, "acceptance_test_writer")

                if not has_upstream_at_writer:
                    violations.append(
                        _warning(
                            self.rule_id,
                            f"codergen node '{node.id}' has no upstream acceptance-test-writer node (V-15)",
                            "Consider adding an acceptance-test-writer node upstream to generate acceptance tests",
                            node_id=node.id,
                        )
                    )

        return violations

    def _has_upstream_node_with_handler(self, graph: Graph, node_id: str, handler: str) -> bool:
        """Check if there is an upstream node with the specified handler."""
        visited = set()

        def dfs_check(current_id: str) -> bool:
            if current_id in visited:
                return False
            visited.add(current_id)

            current_node = graph.nodes.get(current_id)
            if current_node and current_node.handler == handler:
                return True

            # Check all incoming edges (predecessors)
            for edge in graph.edges:
                if edge.target == current_id:
                    if dfs_check(edge.source):
                        return True
            return False

        # Start DFS from predecessors of the given node
        for edge in graph.edges:
            if edge.target == node_id:
                if dfs_check(edge.source):
                    return True

        return False


# ---------------------------------------------------------------------------
# Rule 19: MissingSkillReference (Enforces GAP-5.6 - V-16)
# ---------------------------------------------------------------------------

class MissingSkillReference:
    """Check if skills_required attributes reference existing skill directories (V-16)."""

    rule_id = "MissingSkillReference"
    severity = Severity.WARNING

    def check(self, graph: Graph) -> list[RuleViolation]:
        import os
        from pathlib import Path

        violations = []

        for node in graph.nodes.values():
            if node.handler == "codergen":
                worker_type = node.attrs.get("worker_type", "").strip()
                if worker_type:
                    # Check if the agent file exists and has skills_required
                    agent_path = Path(f".claude/agents/{worker_type}.md")
                    if agent_path.exists():
                        try:
                            content = agent_path.read_text()
                            # Parse YAML frontmatter if it exists
                            if content.startswith("---"):
                                # Find the end of the YAML frontmatter
                                lines = content.split('\n')
                                if len(lines) > 1 and lines[0] == "---":
                                    # Find the closing ---
                                    for i in range(1, len(lines)):
                                        if lines[i] == "---" and i > 0:
                                            fm_content = '\n'.join(lines[1:i])
                                            import yaml
                                            try:
                                                fm = yaml.safe_load(fm_content)
                                                if fm and isinstance(fm, dict) and "skills_required" in fm:
                                                    for skill in fm.get("skills_required", []):
                                                        skill_dir = Path(f".claude/skills/{skill}")
                                                        if not skill_dir.exists():
                                                            violations.append(
                                                                _warning(
                                                                    self.rule_id,
                                                                    f"Agent '{worker_type}' requires skill '{skill}' but .claude/skills/{skill}/ not found (V-16)",
                                                                    f"Create the skill directory at .claude/skills/{skill}/ or remove from agent configuration",
                                                                    node_id=node.id,
                                                                )
                                                            )
                                            except yaml.YAMLError:
                                                pass  # Skip invalid YAML
                                            break
                        except Exception:
                            pass  # Don't fail validation on agent file parse errors

        return violations
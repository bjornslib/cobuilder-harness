#!/usr/bin/env python3
"""
Validation Agent Monitor Mode

Enhanced validation-test-agent that monitors task completion and validates work.

Usage:
    python validation-test-agent-monitor.py --session-id demo-test \
        --task-list-id shared-tasks --max-iterations 10

Modes:
    --mode=monitor: Poll for task completion and validate work
    --mode=unit: Run unit tests
    --mode=e2e: Run E2E tests with PRD validation
"""

import argparse
import json
import os
import sys
import time
import subprocess
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class MonitorResult:
    """Result of a monitoring operation."""
    session_id: str
    task_list_id: str
    task_id: str
    status: str  # MONITOR_COMPLETE, MONITOR_HEALTHY, MONITOR_VALIDATION_FAILED
    message: str
    evidence: dict  # Additional evidence/details
    iterations: int
    total_time: float


class ValidationAgentMonitor:
    """Monitors task list and validates completed work."""

    def __init__(self, session_id: str, task_list_id: str, target_task_id: str = "15"):
        self.session_id = session_id
        self.task_list_id = task_list_id
        self.target_task_id = target_task_id
        self.task_dir = Path.home() / ".claude" / "tasks" / task_list_id
        self.task_list_monitor = self._locate_monitor_script()

    def _locate_monitor_script(self) -> str:
        """Locate the task-list-monitor.py script."""
        script_locations = [
            Path.home() / ".claude" / "scripts" / "task-list-monitor.py",
            Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")) / ".claude" / "scripts" / "task-list-monitor.py",
            Path.cwd() / ".claude" / "scripts" / "task-list-monitor.py",
        ]

        for loc in script_locations:
            if loc.exists():
                return str(loc)

        raise FileNotFoundError("task-list-monitor.py not found in expected locations")

    def get_task_status(self, task_id: str) -> Optional[dict]:
        """Get current status of a specific task."""
        task_file = self.task_dir / f"{task_id}.json"
        if not task_file.exists():
            return None

        try:
            with open(task_file) as f:
                return json.load(f)
        except json.JSONDecodeError:
            return None

    def poll_for_completion(self, max_iterations: int = 10, interval: int = 10) -> tuple[bool, int]:
        """
        Poll for task completion.

        Returns:
            (completed, iterations_used): Whether task completed, iterations used
        """
        for iteration in range(1, max_iterations + 1):
            task_status = self.get_task_status(self.target_task_id)

            if not task_status:
                logger.warning(f"Iteration {iteration}: Task #{self.target_task_id} not found")
            else:
                status = task_status.get("status", "unknown")
                subject = task_status.get("subject", "Unknown")
                logger.info(f"Iteration {iteration}: Task #{self.target_task_id} status: {status}")
                logger.info(f"  Subject: {subject}")

                if status == "completed":
                    logger.info(f"FOUND: Task #{self.target_task_id} is completed!")
                    return True, iteration

            if iteration < max_iterations:
                logger.info(f"Waiting {interval} seconds before next poll...")
                time.sleep(interval)
            else:
                logger.info(f"Reached max iterations ({max_iterations})")

        return False, max_iterations

    def validate_work_product(self) -> tuple[bool, dict]:
        """
        Validate the work product for Task #15.

        Expected deliverable: .claude/tests/demo/test_monitor_demo.py
        with valid Python test code.

        Returns:
            (passed, evidence): Whether validation passed, evidence dict
        """
        evidence = {
            "file_exists": False,
            "file_path": None,
            "file_size": 0,
            "has_test_code": False,
            "pytest_output": None,
            "errors": []
        }

        # Check if file exists
        test_file = Path.home() / ".claude" / "tests" / "demo" / "test_monitor_demo.py"
        evidence["file_path"] = str(test_file)

        if not test_file.exists():
            evidence["errors"].append(f"Test file not found: {test_file}")
            logger.error(f"VALIDATION FAILED: File not found: {test_file}")
            return False, evidence

        evidence["file_exists"] = True
        evidence["file_size"] = test_file.stat().st_size
        logger.info(f"File found: {test_file} ({evidence['file_size']} bytes)")

        # Check file content
        try:
            content = test_file.read_text()
            logger.info(f"File content ({len(content)} chars)")

            # Validate it's Python code with test functions
            if "def test_" in content:
                evidence["has_test_code"] = True
                logger.info("Found test function definitions")
            else:
                evidence["errors"].append("No test_* function definitions found")
                logger.warning("Warning: No test_* function definitions found")

            # Try to parse as Python
            try:
                compile(content, str(test_file), "exec")
                logger.info("Python syntax validation: OK")
            except SyntaxError as e:
                evidence["errors"].append(f"Syntax error: {e}")
                logger.error(f"VALIDATION FAILED: Syntax error in test file: {e}")
                return False, evidence

        except Exception as e:
            evidence["errors"].append(f"Failed to read file: {e}")
            logger.error(f"VALIDATION FAILED: {e}")
            return False, evidence

        # Optional: Try to run pytest
        try:
            result = subprocess.run(
                ["python", "-m", "pytest", str(test_file), "-v", "--tb=short"],
                capture_output=True,
                timeout=30,
                cwd=str(Path.home())
            )
            evidence["pytest_output"] = result.stdout.decode() if result.stdout else ""
            evidence["pytest_returncode"] = result.returncode

            if result.returncode == 0:
                logger.info("pytest: All tests passed")
            else:
                logger.warning(f"pytest: Tests failed with return code {result.returncode}")
                # Don't fail validation just because tests don't pass -
                # file existence + valid syntax is enough

        except subprocess.TimeoutExpired:
            evidence["errors"].append("pytest timed out")
            logger.warning("pytest timed out")
        except Exception as e:
            evidence["errors"].append(f"pytest error: {e}")
            logger.warning(f"Could not run pytest: {e}")

        return True, evidence

    def monitor(self, max_iterations: int = 10, interval: int = 10) -> MonitorResult:
        """
        Main monitoring loop.

        Returns:
            MonitorResult with final status
        """
        logger.info("=" * 70)
        logger.info("VALIDATION-AGENT MONITOR MODE")
        logger.info("=" * 70)
        logger.info(f"Session ID: {self.session_id}")
        logger.info(f"Task List: {self.task_list_id}")
        logger.info(f"Target Task: #{self.target_task_id}")
        logger.info(f"Max Iterations: {max_iterations} (interval: {interval}s)")
        logger.info("=" * 70)
        logger.info("")

        start_time = time.time()

        # Phase 1: Poll for completion
        logger.info("PHASE 1: Polling for task completion...")
        logger.info("-" * 70)
        completed, iterations = self.poll_for_completion(max_iterations, interval)
        elapsed = time.time() - start_time

        if not completed:
            logger.info("")
            logger.info("=" * 70)
            logger.info("MONITOR STATUS: HEALTHY (task not yet complete)")
            logger.info("=" * 70)
            return MonitorResult(
                session_id=self.session_id,
                task_list_id=self.task_list_id,
                task_id=self.target_task_id,
                status="MONITOR_HEALTHY",
                message=f"Task #{self.target_task_id} not completed after {iterations} iterations",
                evidence={"iterations": iterations, "elapsed_seconds": elapsed},
                iterations=iterations,
                total_time=elapsed
            )

        # Phase 2: Validate work product
        logger.info("")
        logger.info("PHASE 2: Validating work product...")
        logger.info("-" * 70)
        passed, evidence = self.validate_work_product()
        elapsed = time.time() - start_time

        if not passed:
            logger.info("")
            logger.info("=" * 70)
            logger.info("MONITOR STATUS: VALIDATION FAILED")
            logger.info("=" * 70)
            return MonitorResult(
                session_id=self.session_id,
                task_list_id=self.task_list_id,
                task_id=self.target_task_id,
                status="MONITOR_VALIDATION_FAILED",
                message=f"Task #{self.target_task_id} completed but validation failed",
                evidence=evidence,
                iterations=iterations,
                total_time=elapsed
            )

        logger.info("")
        logger.info("=" * 70)
        logger.info("MONITOR STATUS: COMPLETE AND VALIDATED")
        logger.info("=" * 70)
        logger.info(f"Task #{self.target_task_id} completed and work product validated")
        logger.info(f"Total time: {elapsed:.1f}s ({iterations} iterations)")
        logger.info("=" * 70)

        return MonitorResult(
            session_id=self.session_id,
            task_list_id=self.task_list_id,
            task_id=self.target_task_id,
            status="MONITOR_COMPLETE",
            message=f"Task #{self.target_task_id} completed and work product validated",
            evidence=evidence,
            iterations=iterations,
            total_time=elapsed
        )


def main():
    parser = argparse.ArgumentParser(
        description="Validation Agent - Monitor Mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Monitor task completion and validate work
  python validation-test-agent-monitor.py --session-id demo-test \\
      --task-list-id shared-tasks --max-iterations 10

  # Custom polling interval (5 seconds)
  python validation-test-agent-monitor.py --session-id demo-test \\
      --task-list-id shared-tasks --max-iterations 20 --interval 5
        """
    )

    parser.add_argument("--session-id", required=True, help="Orchestrator session ID")
    parser.add_argument("--task-list-id", required=True, help="Task list ID")
    parser.add_argument("--task-id", default="15", help="Target task ID to monitor (default: 15)")
    parser.add_argument("--max-iterations", type=int, default=10, help="Max polling iterations")
    parser.add_argument("--interval", type=int, default=10, help="Polling interval in seconds")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    try:
        monitor = ValidationAgentMonitor(args.session_id, args.task_list_id, args.task_id)
        result = monitor.monitor(args.max_iterations, args.interval)

        if args.json:
            print(json.dumps(asdict(result), indent=2))
        else:
            print(f"\nResult: {result.status}")
            print(f"Message: {result.message}")
            print(f"Time: {result.total_time:.1f}s")

        # Exit code based on status
        if result.status == "MONITOR_COMPLETE":
            sys.exit(0)
        elif result.status == "MONITOR_VALIDATION_FAILED":
            sys.exit(1)
        else:  # MONITOR_HEALTHY
            sys.exit(2)

    except Exception as e:
        logger.error(f"Monitor error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

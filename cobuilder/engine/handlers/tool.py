"""ToolHandler — handles parallelogram (shell tool) nodes.

Executes ``node.tool_command`` via ``subprocess.run(shell=True)`` in the
pipeline run directory with a configurable timeout.

AC-F12:
- Executes ``node.tool_command`` via ``subprocess.run(shell=True)`` in ``run_dir``.
- Returns ``Outcome(status=SUCCESS)`` for exit code 0.
- Returns ``Outcome(status=FAILURE)`` for non-zero exit codes.
- Captures stdout/stderr into context_updates.
- Timeout: ``PIPELINE_TOOL_TIMEOUT`` seconds (default 300s).
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path

from cobuilder.engine.exceptions import HandlerError
from cobuilder.engine.handlers.base import Handler, HandlerRequest
from cobuilder.engine.outcome import Outcome, OutcomeStatus

logger = logging.getLogger(__name__)

_DEFAULT_TOOL_TIMEOUT_S = 300


class ToolHandler:
    """Shell command executor for tool nodes (``parallelogram`` shape).

    Runs ``node.tool_command`` in a subprocess.  Stdout and stderr are
    captured and stored in the context so downstream nodes and edge
    conditions can read them.

    Args:
        timeout_s: Subprocess timeout in seconds.  Defaults to the
                   ``PIPELINE_TOOL_TIMEOUT`` env var or 300s.
    """

    def __init__(self, timeout_s: float | None = None) -> None:
        self._timeout_s = timeout_s or float(
            os.environ.get("PIPELINE_TOOL_TIMEOUT", _DEFAULT_TOOL_TIMEOUT_S)
        )

    async def execute(self, request: HandlerRequest) -> Outcome:
        """Execute node.tool_command and return Outcome based on exit code.

        Args:
            request: HandlerRequest with node, context, run_dir.

        Returns:
            Outcome with status SUCCESS (exit 0) or FAILURE (non-zero).

        Raises:
            HandlerError: If the command cannot be started (e.g. command
                          not found, permission denied).
        """
        node = request.node
        command = node.tool_command

        if not command:
            # No command — this is a no-op tool node; return SUCCESS
            logger.debug("ToolHandler '%s': no tool_command set; returning SUCCESS", node.id)
            return Outcome(
                status=OutcomeStatus.SUCCESS,
                context_updates={
                    f"${node.id}.exit_code": 0,
                    f"${node.id}.stdout": "",
                    f"${node.id}.stderr": "",
                },
                metadata={"command": "", "exit_code": 0},
            )

        # Run in the pipeline run directory if available
        cwd = request.run_dir if request.run_dir else None

        # Use asyncio to avoid blocking the event loop during subprocess.run
        outcome = await asyncio.to_thread(
            self._run_command,
            command=command,
            cwd=cwd,
            node_id=node.id,
        )
        return outcome

    def _run_command(
        self,
        command: str,
        cwd: str | None,
        node_id: str,
    ) -> Outcome:
        """Synchronous command execution (called in a thread via asyncio.to_thread)."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=self._timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            return Outcome(
                status=OutcomeStatus.FAILURE,
                context_updates={
                    f"${node_id}.exit_code": -1,
                    f"${node_id}.stdout": exc.stdout or "" if exc.stdout else "",
                    f"${node_id}.stderr": exc.stderr or "" if exc.stderr else "",
                },
                metadata={
                    "command": command,
                    "exit_code": -1,
                    "error_type": "TIMEOUT",
                    "timeout_s": self._timeout_s,
                },
            )
        except OSError as exc:
            raise HandlerError(
                f"Failed to run command '{command}': {exc}",
                node_id=node_id,
                cause=exc,
            )

        status = OutcomeStatus.SUCCESS if result.returncode == 0 else OutcomeStatus.FAILURE

        return Outcome(
            status=status,
            context_updates={
                f"${node_id}.exit_code": result.returncode,
                f"${node_id}.stdout": result.stdout,
                f"${node_id}.stderr": result.stderr,
            },
            metadata={
                "command": command,
                "exit_code": result.returncode,
                "stdout_length": len(result.stdout),
                "stderr_length": len(result.stderr),
            },
        )


assert isinstance(ToolHandler(), Handler)

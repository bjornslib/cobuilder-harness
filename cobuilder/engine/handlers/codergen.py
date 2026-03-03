"""CodergenHandler — handles box (codergen/LLM) nodes.

This handler dispatches to an orchestrator subprocess (tmux strategy) or
directly via the claude_code_sdk (sdk strategy) and polls for completion.

**AMD-1 Completion Protocol (tmux dispatch)**:

1. Write prompt to ``{run_dir}/nodes/{node_id}/prompt.md``
2. Call ``spawn_orchestrator.spawn_orchestrator(...)`` to start the tmux session
3. Poll ``{run_dir}/nodes/{node_id}/signals/`` for signal files:
   - ``{node_id}-complete.signal``  → SUCCESS
   - ``{node_id}-failed.signal``    → FAILURE
   - ``{node_id}-needs-review.signal`` → PARTIAL_SUCCESS
4. Timeout after ``handler_timeout_s`` seconds (default 3600)
5. Write outcome to ``{run_dir}/nodes/{node_id}/outcome.json``

**SDK dispatch** (``dispatch_strategy=sdk``):

Calls ``claude_code_sdk.query(prompt=node.prompt)`` and converts the result
to an Outcome.  Falls back to tmux with a warning if the SDK is not installed.

AC-F6 coverage — see inline comments for each AC item.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from cobuilder.engine.exceptions import HandlerError
from cobuilder.engine.handlers.base import Handler, HandlerRequest
from cobuilder.engine.outcome import Outcome, OutcomeStatus

logger = logging.getLogger(__name__)

# Configurable via environment variables
_DEFAULT_TIMEOUT_S = 3600
_DEFAULT_POLL_INTERVAL_S = 10


class CodergenHandler:
    """Handler for LLM/orchestrator nodes (``box`` shape).

    Supports two dispatch strategies controlled by ``node.dispatch_strategy``:

    - ``"tmux"`` (default): spawns an orchestrator via ``spawn_orchestrator.py``
      and polls for signal files.
    - ``"sdk"``: calls ``claude_code_sdk.query()`` in-process (no tmux).

    Args:
        spawner:       Async callable with signature
                       ``async (node_id, prd, repo_root, **kwargs) → dict``.
                       Defaults to importing ``spawn_orchestrator`` at call time.
        signal_poller: Async callable for signal polling (injectable for tests).
        timeout_s:     Override handler timeout (seconds).
        poll_interval_s: Override signal poll interval (seconds).
    """

    def __init__(
        self,
        spawner: Any = None,
        signal_poller: Any = None,
        timeout_s: float | None = None,
        poll_interval_s: float | None = None,
    ) -> None:
        self._spawner = spawner                # None → import at call time
        self._signal_poller = signal_poller    # None → default filesystem poller
        self._timeout_s = timeout_s or float(
            os.environ.get("ATTRACTOR_HANDLER_TIMEOUT", _DEFAULT_TIMEOUT_S)
        )
        self._poll_interval_s = poll_interval_s or float(
            os.environ.get("ATTRACTOR_SIGNAL_POLL_INTERVAL", _DEFAULT_POLL_INTERVAL_S)
        )

    async def execute(self, request: HandlerRequest) -> Outcome:
        """Dispatch to orchestrator and await completion signal.

        Args:
            request: HandlerRequest with node, context, run_dir.

        Returns:
            Outcome reflecting the orchestrator's completion signal.

        Raises:
            HandlerError: On unexpected errors (not on FAILURE outcomes —
                          those are returned as Outcome(status=FAILURE)).
        """
        node = request.node
        strategy = node.dispatch_strategy  # "tmux" (default) or "sdk"

        if strategy == "sdk":
            return await self._execute_sdk(request)
        else:
            return await self._execute_tmux(request)

    # ------------------------------------------------------------------
    # tmux dispatch
    # ------------------------------------------------------------------

    async def _execute_tmux(self, request: HandlerRequest) -> Outcome:
        """AC-F6 tmux path: spawn orchestrator and poll for signals."""
        node = request.node
        run_dir = request.run_dir
        node_dir = Path(run_dir) / "nodes" / node.id if run_dir else None

        # AC-F6: Write node prompt to prompt.md BEFORE spawning
        if node_dir:
            node_dir.mkdir(parents=True, exist_ok=True)
            prompt_path = node_dir / "prompt.md"
            prompt_path.write_text(node.prompt or f"# Execute node: {node.id}\n")

        # Spawn orchestrator
        await self._spawn_orchestrator(node, request)

        # Poll for completion signal
        signals_dir = (node_dir / "signals") if node_dir else None
        outcome = await self._poll_for_signal(node, signals_dir)

        # AC-F6: Write outcome.json AFTER completion
        if node_dir:
            outcome_path = node_dir / "outcome.json"
            try:
                outcome_path.write_text(
                    json.dumps(
                        {
                            "status": outcome.status.value,
                            "metadata": outcome.metadata,
                        },
                        indent=2,
                    )
                )
            except OSError as e:
                logger.warning("Failed to write outcome.json for node '%s': %s", node.id, e)

        return outcome

    async def _spawn_orchestrator(self, node: Any, request: HandlerRequest) -> None:
        """Call spawner to launch the tmux orchestrator session."""
        spawner = self._spawner
        if spawner is None:
            try:
                from cobuilder.orchestration import spawn_orchestrator as _mod
                spawner = _mod.spawn_orchestrator
            except ImportError:
                raise HandlerError(
                    "spawn_orchestrator module not found. "
                    "Ensure cobuilder.orchestration is installed or inject a spawner.",
                    node_id=node.id,
                )

        graph = request.context.get("$graph")
        prd_ref = graph.prd_ref if graph else ""
        try:
            await spawner(
                node_id=node.id,
                prd=prd_ref,
                repo_root=request.run_dir,
                worker_type=node.worker_type,
                bead_id=node.bead_id,
            )
        except Exception as exc:
            raise HandlerError(
                f"Orchestrator spawn failed: {exc}",
                node_id=node.id,
                cause=exc,
            )

    async def _poll_for_signal(
        self,
        node: Any,
        signals_dir: Path | None,
    ) -> Outcome:
        """Poll signals_dir for completion signals with timeout.

        AC-F6: polls for ``{node_id}-complete.signal``, ``{node_id}-failed.signal``,
        ``{node_id}-needs-review.signal``.
        """
        # If a custom signal poller is injected, use it
        if self._signal_poller is not None:
            result = await self._signal_poller(
                target_layer="runner",
                timeout=self._timeout_s,
                signals_dir=str(signals_dir) if signals_dir else "",
                poll_interval=self._poll_interval_s,
            )
            return self._signal_to_outcome(node.id, result)

        # Default filesystem poller
        loop = asyncio.get_event_loop()
        start_time = loop.time()
        while True:
            elapsed = loop.time() - start_time

            if elapsed >= self._timeout_s:
                # AC-F6: Timeout → FAILURE with TIMEOUT metadata
                return Outcome(
                    status=OutcomeStatus.FAILURE,
                    context_updates={f"${node.id}.status": "timeout"},
                    metadata={"error_type": "TIMEOUT", "elapsed_s": elapsed},
                )

            if signals_dir:
                outcome = self._check_signal_files(node.id, signals_dir, elapsed)
                if outcome is not None:
                    return outcome

            await asyncio.sleep(self._poll_interval_s)

    def _check_signal_files(
        self,
        node_id: str,
        signals_dir: Path,
        elapsed: float,
    ) -> Outcome | None:
        """Check for signal files; return Outcome if found, else None."""
        # AC-F6: complete signal → SUCCESS
        complete_path = signals_dir / f"{node_id}-complete.signal"
        if complete_path.exists():
            payload = self._read_signal_payload(complete_path)
            return Outcome(
                status=OutcomeStatus.SUCCESS,
                context_updates={f"${node_id}.status": "success"},
                metadata={"signal": "complete", "payload": payload, "elapsed_s": elapsed},
            )

        # AC-F6: failed signal → FAILURE
        failed_path = signals_dir / f"{node_id}-failed.signal"
        if failed_path.exists():
            payload = self._read_signal_payload(failed_path)
            return Outcome(
                status=OutcomeStatus.FAILURE,
                context_updates={f"${node_id}.status": "failed"},
                metadata={
                    "signal": "failed",
                    "payload": payload,
                    "feedback": payload.get("feedback", ""),
                    "elapsed_s": elapsed,
                },
            )

        # needs-review signal → PARTIAL_SUCCESS
        review_path = signals_dir / f"{node_id}-needs-review.signal"
        if review_path.exists():
            payload = self._read_signal_payload(review_path)
            return Outcome(
                status=OutcomeStatus.PARTIAL_SUCCESS,
                context_updates={f"${node_id}.status": "needs_review"},
                metadata={"signal": "needs-review", "payload": payload, "elapsed_s": elapsed},
            )

        return None

    @staticmethod
    def _read_signal_payload(path: Path) -> dict:
        """Read JSON payload from a signal file, tolerating parse errors."""
        try:
            content = path.read_text().strip()
            return json.loads(content) if content else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _signal_to_outcome(node_id: str, signal_result: dict) -> Outcome:
        """Convert a signal dict (from injected poller) to an Outcome."""
        signal_type = signal_result.get("signal_type", "")
        if signal_type in ("VALIDATION_PASSED", "complete"):
            return Outcome(
                status=OutcomeStatus.SUCCESS,
                context_updates={f"${node_id}.status": "success"},
                metadata={"signal": signal_type},
            )
        elif signal_type in ("NEEDS_REVIEW", "needs-review"):
            return Outcome(
                status=OutcomeStatus.PARTIAL_SUCCESS,
                context_updates={f"${node_id}.status": "needs_review"},
                metadata={"signal": signal_type},
            )
        else:
            payload = signal_result.get("payload", {})
            return Outcome(
                status=OutcomeStatus.FAILURE,
                context_updates={f"${node_id}.status": "failed"},
                metadata={
                    "signal": signal_type,
                    "feedback": payload.get("feedback", ""),
                },
            )

    # ------------------------------------------------------------------
    # SDK dispatch
    # ------------------------------------------------------------------

    async def _execute_sdk(self, request: HandlerRequest) -> Outcome:
        """AC-F6 SDK path: call claude_code_sdk.query() and convert result.

        Falls back to tmux with a warning if the SDK is not importable.
        """
        node = request.node
        try:
            import claude_code_sdk  # type: ignore[import-untyped]
        except ImportError:
            logger.warning(
                "claude_code_sdk not importable; falling back to tmux for node '%s'",
                node.id,
            )
            return await self._execute_tmux(request)

        prompt = node.prompt or f"Execute task: {node.id}"
        try:
            result = await claude_code_sdk.query(prompt=prompt)
            return Outcome(
                status=OutcomeStatus.SUCCESS,
                context_updates={f"${node.id}.status": "success"},
                metadata={"dispatch_strategy": "sdk"},
                raw_messages=list(result) if hasattr(result, "__iter__") else [result],
            )
        except Exception as exc:
            return Outcome(
                status=OutcomeStatus.FAILURE,
                context_updates={f"${node.id}.status": "failed"},
                metadata={
                    "dispatch_strategy": "sdk",
                    "error": str(exc),
                },
            )


assert isinstance(CodergenHandler(), Handler)

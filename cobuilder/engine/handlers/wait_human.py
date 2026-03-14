"""WaitHumanHandler — handles hexagon (human-in-the-loop gate) nodes.

The handler polls the signal directory for an ``INPUT_RESPONSE`` signal.
It returns:
- ``WAITING`` when no signal is received within a poll cycle (engine can
  checkpoint and exit; ``--resume`` will re-enter the handler next time).
- ``SUCCESS`` when an ``INPUT_RESPONSE`` with ``response="approve"`` arrives.
- ``FAILURE`` when an ``INPUT_RESPONSE`` with ``response="reject"`` arrives.

AC-F8:
- Polls for ``INPUT_RESPONSE`` signal.
- Returns ``Outcome(status=WAITING)`` when no signal received within poll cycle.
- On ``INPUT_RESPONSE`` with ``response="approve"``: returns SUCCESS.
- On ``INPUT_RESPONSE`` with ``response="reject"``: returns FAILURE.
- Respects ``PIPELINE_HUMAN_GATE_TIMEOUT`` (default: indefinite).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from cobuilder.engine.handlers.base import Handler, HandlerRequest
from cobuilder.engine.outcome import Outcome, OutcomeStatus

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL_S = 10
_NO_TIMEOUT = -1.0  # sentinel for "poll indefinitely"


class WaitHumanHandler:
    """Handler for human approval gate nodes (``hexagon`` shape).

    Pauses pipeline execution until a human writes an INPUT_RESPONSE signal
    file to the signals directory.

    Args:
        timeout_s:      Maximum seconds to wait.  ``-1`` (default) means
                        poll indefinitely until a signal arrives.
        poll_interval_s: Seconds between signal checks.
    """

    def __init__(
        self,
        timeout_s: float | None = None,
        poll_interval_s: float | None = None,
    ) -> None:
        # AC-F8: default = indefinite (PIPELINE_HUMAN_GATE_TIMEOUT env var)
        env_timeout = os.environ.get("PIPELINE_HUMAN_GATE_TIMEOUT", "")
        if timeout_s is not None:
            self._timeout_s = timeout_s
        elif env_timeout:
            self._timeout_s = float(env_timeout)
        else:
            self._timeout_s = _NO_TIMEOUT  # indefinite

        self._poll_interval_s = poll_interval_s or _DEFAULT_POLL_INTERVAL_S

    async def execute(self, request: HandlerRequest) -> Outcome:
        """Poll for INPUT_RESPONSE signal; return WAITING, SUCCESS, or FAILURE.

        Args:
            request: HandlerRequest with node, context, run_dir.

        Returns:
            Outcome with status WAITING, SUCCESS, or FAILURE.
        """
        node = request.node
        run_dir = request.run_dir
        signals_dir = (Path(run_dir) / "nodes" / node.id / "signals") if run_dir else None

        if signals_dir:
            signals_dir.mkdir(parents=True, exist_ok=True)

        start_time = time.monotonic()
        cycles = 0

        while True:
            elapsed = time.monotonic() - start_time

            # Check timeout
            if self._timeout_s != _NO_TIMEOUT and elapsed >= self._timeout_s:
                logger.info(
                    "WaitHumanHandler: timeout after %.1f s at node '%s'",
                    elapsed,
                    node.id,
                )
                return Outcome(
                    status=OutcomeStatus.WAITING,
                    context_updates={f"${node.id}.approval": "timeout"},
                    metadata={"reason": "timeout", "elapsed_s": elapsed},
                )

            # Check for signal
            if signals_dir:
                outcome = self._check_input_response(node.id, signals_dir, elapsed)
                if outcome is not None:
                    return outcome

            cycles += 1

            # Return WAITING after first poll cycle so engine can checkpoint
            # and exit gracefully.  On --resume the runner re-enters this node.
            if cycles >= 1 and self._timeout_s == _NO_TIMEOUT:
                # In indefinite mode, return WAITING after first poll so the
                # engine doesn't block the runner indefinitely in a single call.
                # The runner loop can re-execute the node on the next iteration.
                break

            await asyncio.sleep(self._poll_interval_s)

        return Outcome(
            status=OutcomeStatus.WAITING,
            context_updates={f"${node.id}.approval": "pending"},
            metadata={"reason": "no_signal_yet"},
        )

    def _check_input_response(
        self,
        node_id: str,
        signals_dir: Path,
        elapsed: float,
    ) -> Outcome | None:
        """Check for INPUT_RESPONSE signal file.  Returns Outcome or None."""
        signal_path = signals_dir / "INPUT_RESPONSE.signal"
        if not signal_path.exists():
            return None

        payload = self._read_signal_payload(signal_path)
        response = payload.get("response", "").lower()

        if response == "approve":
            return Outcome(
                status=OutcomeStatus.SUCCESS,
                context_updates={f"${node_id}.approval": "approved"},
                metadata={"response": "approve", "elapsed_s": elapsed, "payload": payload},
            )
        elif response == "reject":
            return Outcome(
                status=OutcomeStatus.FAILURE,
                context_updates={f"${node_id}.approval": "rejected"},
                metadata={"response": "reject", "elapsed_s": elapsed, "payload": payload},
            )

        # Unknown response value — treat as still waiting
        logger.warning(
            "WaitHumanHandler: unknown response '%s' in INPUT_RESPONSE signal at '%s'",
            response,
            signal_path,
        )
        return None

    @staticmethod
    def _read_signal_payload(path: Path) -> dict:
        """Read JSON payload from a signal file."""
        try:
            content = path.read_text().strip()
            return json.loads(content) if content else {}
        except (OSError, json.JSONDecodeError):
            return {}


assert isinstance(WaitHumanHandler(), Handler)

"""Anti-Gaming Enforcement for the Pipeline Runner Agent.

Provides three independent subsystems that work together to prevent agents
from gaming the pipeline validation process:

Classes:
    SpotCheckSelector  - Deterministic selection of nodes for ad-hoc audit.
    ChainedAuditWriter - Append-only JSONL writer with chained SHA-256 hashes.
    EvidenceValidator  - Staleness guard for evidence timestamps.

Design notes:
    - SpotCheckSelector is fully deterministic: hash(session_id + node_id)
      always produces the same spot-check decision for the same inputs.
    - ChainedAuditWriter maintains a tamper-evident chain: each entry's
      prev_hash equals the SHA-256 prefix of the previous serialised entry.
    - EvidenceValidator rejects evidence older than ``max_age_seconds``
      (default 300 s = 5 min) and rejects future-dated timestamps.

Usage:
    selector = SpotCheckSelector(rate=0.25)
    selector.should_spot_check("sess-abc", "node-impl-auth")  # → True/False

    writer = ChainedAuditWriter("/path/to/audit.jsonl")
    writer.write(AuditEntry(node_id="n1", ...))

    validator = EvidenceValidator()
    ok, msg = validator.validate("2025-01-01T12:00:00+00:00")
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import sys
from typing import Any

from cobuilder.attractor.runner_models import AuditEntry

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _hash_content(content: str, length: int = 16) -> str:
    """SHA-256 hash of *content*, truncated to *length* hex chars."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:length]


# ---------------------------------------------------------------------------
# SpotCheckSelector
# ---------------------------------------------------------------------------


class SpotCheckSelector:
    """Deterministic spot-check node selector.

    Uses ``hash(session_id + node_id)`` to decide whether a given node should
    be flagged for an ad-hoc audit spot-check.  The result is fully
    deterministic — the same ``(session_id, node_id)`` pair always produces
    the same answer regardless of process state or call order.

    Args:
        rate: Fraction of nodes to spot-check in [0.0, 1.0].  Default 0.25
            (25 % of all nodes).

    Example:
        >>> sel = SpotCheckSelector(rate=0.25)
        >>> sel.should_spot_check("sess-abc", "impl-auth")
        True  # (deterministic for these specific inputs)
    """

    def __init__(self, rate: float = 0.25) -> None:
        if not 0.0 <= rate <= 1.0:
            raise ValueError(f"rate must be between 0.0 and 1.0, got {rate!r}")
        self._rate = rate

    @property
    def rate(self) -> float:
        """The configured spot-check rate."""
        return self._rate

    def should_spot_check(self, session_id: str, node_id: str) -> bool:
        """Return *True* if this ``(session_id, node_id)`` pair is selected.

        Deterministic: repeated calls with the same arguments always return
        the same value.

        Args:
            session_id: Unique identifier of the runner session.
            node_id:    Pipeline node identifier.

        Returns:
            True when the node should be spot-checked, False otherwise.
        """
        digest = hashlib.sha256(
            (session_id + node_id).encode("utf-8")
        ).hexdigest()
        # Map first 8 hex chars → float in [0, 1) then compare against rate
        value = int(digest[:8], 16) / 0xFFFF_FFFF
        return value < self._rate

    def select_for_session(
        self,
        session_id: str,
        node_ids: list[str],
    ) -> list[str]:
        """Return the subset of *node_ids* selected for spot-checking.

        Preserves the original ordering; only nodes that pass
        ``should_spot_check`` are returned.

        Args:
            session_id: Unique identifier of the runner session.
            node_ids:   Candidate node identifiers to filter.

        Returns:
            List of node IDs (in original order) that should be spot-checked.
        """
        return [nid for nid in node_ids if self.should_spot_check(session_id, nid)]


# ---------------------------------------------------------------------------
# ChainedAuditWriter
# ---------------------------------------------------------------------------


class ChainedAuditWriter:
    """Append-only audit writer with chained SHA-256 checksums.

    Each ``AuditEntry`` is serialised to JSON and appended to a ``.jsonl``
    file.  Before writing, the entry's ``prev_hash`` field is set to the
    SHA-256 prefix of the *previous* serialised entry, creating a
    tamper-evident chain.

    On construction the writer loads the hash of the last existing line
    (if any) so that new entries continue an interrupted chain correctly.

    Args:
        audit_path: Absolute path to the JSONL audit file.
        verbose:    If True, print debug lines to ``stderr``.

    Example:
        >>> writer = ChainedAuditWriter("/tmp/audit.jsonl")
        >>> writer.write(AuditEntry(node_id="n1", from_status="pending",
        ...              to_status="active", agent_id="sess-1"))
    """

    def __init__(self, audit_path: str, *, verbose: bool = False) -> None:
        self._audit_path = audit_path
        self._verbose = verbose
        self._prev_hash: str = ""
        self._load_tail_hash()

    @property
    def prev_hash(self) -> str:
        """The hash of the most recently written entry (chain tip)."""
        return self._prev_hash

    def _load_tail_hash(self) -> None:
        """Read the last line of an existing audit file and set *prev_hash*.

        Enables chain continuation when the writer is re-created across
        runner restarts.
        """
        if not os.path.exists(self._audit_path):
            return
        try:
            last_line: str = ""
            with open(self._audit_path, encoding="utf-8") as fh:
                for line in fh:
                    stripped = line.strip()
                    if stripped:
                        last_line = stripped
            if last_line:
                self._prev_hash = _hash_content(last_line)
                if self._verbose:
                    print(
                        f"[audit] Resumed chain from existing file, "
                        f"tail_hash={self._prev_hash[:8]}",
                        file=sys.stderr,
                    )
        except OSError as exc:
            print(
                f"[audit] WARNING: Could not read existing audit file: {exc}",
                file=sys.stderr,
            )

    def write(self, entry: AuditEntry) -> None:
        """Append *entry* to the audit file with the current chain hash.

        Sets ``entry.prev_hash`` to the current chain tip before writing,
        then advances the chain tip to the hash of the newly written line.

        Args:
            entry: The ``AuditEntry`` to append.  Its ``prev_hash`` field
                will be overwritten with the current chain tip.
        """
        entry.prev_hash = self._prev_hash
        serialised = entry.model_dump_json()
        try:
            os.makedirs(os.path.dirname(self._audit_path), exist_ok=True)
            with open(self._audit_path, "a", encoding="utf-8") as fh:
                fh.write(serialised + "\n")
            self._prev_hash = _hash_content(serialised)
            if self._verbose:
                print(
                    f"[audit] {entry.node_id} "
                    f"{entry.from_status}→{entry.to_status} "
                    f"chain_tip={self._prev_hash[:8]}",
                    file=sys.stderr,
                )
        except OSError as exc:
            # Never crash the runner on audit failure — warn and continue.
            print(
                f"[audit] WARNING: Failed to write entry: {exc}",
                file=sys.stderr,
            )

    def verify_chain(self) -> tuple[bool, str]:
        """Verify the integrity of the entire audit chain.

        Reads every line, re-hashes the previous line, and compares the
        stored ``prev_hash`` value.  The first entry must have
        ``prev_hash == ""``.

        Returns:
            ``(True, message)``  when the chain is intact.
            ``(False, message)`` if a broken link or parse error is found.
        """
        if not os.path.exists(self._audit_path):
            return True, "No audit file — empty chain"
        try:
            entries: list[tuple[int, str, dict[str, Any]]] = []
            with open(self._audit_path, encoding="utf-8") as fh:
                for line_no, line in enumerate(fh, 1):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        data = json.loads(stripped)
                        entries.append((line_no, stripped, data))
                    except json.JSONDecodeError:
                        return False, f"Invalid JSON at line {line_no}"
        except OSError as exc:
            return False, f"Cannot read audit file: {exc}"

        if not entries:
            return True, "Empty audit file — chain trivially valid"

        expected_prev: str = ""
        for line_no, raw, data in entries:
            actual_prev = data.get("prev_hash", "")
            if actual_prev != expected_prev:
                return (
                    False,
                    f"Chain broken at line {line_no} (node_id={data.get('node_id')!r}): "
                    f"expected prev_hash={expected_prev!r}, "
                    f"got {actual_prev!r}",
                )
            expected_prev = _hash_content(raw)

        return True, f"Chain verified — {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} intact"

    def entry_count(self) -> int:
        """Return the number of entries currently in the audit file."""
        if not os.path.exists(self._audit_path):
            return 0
        try:
            count = 0
            with open(self._audit_path, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        count += 1
            return count
        except OSError:
            return 0


# ---------------------------------------------------------------------------
# EvidenceValidator
# ---------------------------------------------------------------------------

# Default maximum acceptable evidence age in seconds (5 minutes).
_DEFAULT_MAX_AGE_SECONDS: int = int(
    os.environ.get("ATTRACTOR_EVIDENCE_MAX_AGE", "300")
)


class EvidenceValidator:
    """Validates evidence timestamps against a configurable staleness window.

    Rejects evidence that is older than *max_age_seconds* (stale) or whose
    timestamp lies in the future (possible clock skew or fabrication).

    Args:
        max_age_seconds: Maximum acceptable evidence age in seconds.
            Defaults to the ``ATTRACTOR_EVIDENCE_MAX_AGE`` environment
            variable, or 300 s (5 minutes) if unset.

    Example:
        >>> validator = EvidenceValidator(max_age_seconds=60)
        >>> ok, msg = validator.validate("2025-01-01T12:00:00+00:00")
    """

    def __init__(
        self, max_age_seconds: int = _DEFAULT_MAX_AGE_SECONDS
    ) -> None:
        if max_age_seconds <= 0:
            raise ValueError(
                f"max_age_seconds must be positive, got {max_age_seconds}"
            )
        self._max_age = max_age_seconds

    @property
    def max_age_seconds(self) -> int:
        """The configured maximum evidence age in seconds."""
        return self._max_age

    def validate(self, evidence_timestamp: str) -> tuple[bool, str]:
        """Check whether *evidence_timestamp* is fresh enough to accept.

        An empty or missing timestamp is treated as "no timestamp provided"
        and is accepted without complaint.  All non-empty timestamps must be
        parseable UTC ISO-8601 strings.

        Args:
            evidence_timestamp: UTC ISO-8601 timestamp string extracted from
                evidence.  May be empty.

        Returns:
            ``(True, message)``  when the timestamp is absent or fresh.
            ``(False, message)`` when stale, in-future, or unparseable.
        """
        if not evidence_timestamp:
            return True, "No timestamp provided — staleness check skipped"

        # Normalise the 'Z' suffix that some serialisers emit.
        normalised = evidence_timestamp.strip().replace("Z", "+00:00")
        try:
            evidence_dt = datetime.datetime.fromisoformat(normalised)
        except (ValueError, AttributeError) as exc:
            return (
                False,
                f"Cannot parse evidence timestamp {evidence_timestamp!r}: {exc}",
            )

        # Ensure timezone-aware comparison.
        if evidence_dt.tzinfo is None:
            evidence_dt = evidence_dt.replace(tzinfo=datetime.timezone.utc)

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        age_seconds = (now_utc - evidence_dt).total_seconds()

        if age_seconds < 0:
            return (
                False,
                f"Evidence timestamp is {abs(age_seconds):.1f}s in the future "
                f"(possible clock skew or fabrication): {evidence_timestamp!r}",
            )

        if age_seconds > self._max_age:
            return (
                False,
                f"Evidence is stale: {age_seconds:.0f}s old "
                f"(max {self._max_age}s allowed). "
                f"Timestamp: {evidence_timestamp!r}",
            )

        return (
            True,
            f"Evidence is fresh ({age_seconds:.1f}s old, max {self._max_age}s)",
        )

    @staticmethod
    def utc_now() -> str:
        """Return the current UTC time as an ISO-8601 string."""
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

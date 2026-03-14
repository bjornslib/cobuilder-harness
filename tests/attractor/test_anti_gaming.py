"""Unit tests for anti_gaming.py.

Tests:
    TestSpotCheckSelector    - Deterministic selection, rate enforcement
    TestChainedAuditWriter   - Chained hash writing and chain verification
    TestEvidenceValidator    - Freshness / staleness / future timestamp checks
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import tempfile
import unittest

# Ensure parent directory is importable regardless of invocation location

from cobuilder.engine.anti_gaming import (  # noqa: E402
    ChainedAuditWriter,
    EvidenceValidator,
    SpotCheckSelector,
    _hash_content,
)
from cobuilder.engine.runner_models import AuditEntry  # noqa: E402


# ---------------------------------------------------------------------------
# SpotCheckSelector tests
# ---------------------------------------------------------------------------


class TestSpotCheckSelector(unittest.TestCase):
    """Tests for SpotCheckSelector determinism and rate compliance."""

    def test_deterministic_same_inputs(self) -> None:
        """Same session_id + node_id must always produce the same result."""
        sel = SpotCheckSelector(rate=0.5)
        result_a = sel.should_spot_check("sess-123", "node-auth")
        result_b = sel.should_spot_check("sess-123", "node-auth")
        self.assertEqual(result_a, result_b)

    def test_deterministic_across_instances(self) -> None:
        """Two independent SpotCheckSelector instances must agree."""
        sel1 = SpotCheckSelector(rate=0.5)
        sel2 = SpotCheckSelector(rate=0.5)
        node_ids = ["node-a", "node-b", "node-c", "node-d", "node-e"]
        for nid in node_ids:
            self.assertEqual(
                sel1.should_spot_check("sess-abc", nid),
                sel2.should_spot_check("sess-abc", nid),
                f"Mismatch for node {nid!r}",
            )

    def test_different_inputs_may_differ(self) -> None:
        """Different session or node IDs should generally produce different results."""
        sel = SpotCheckSelector(rate=0.5)
        # With rate=0.5 and a large enough set, we expect both True and False
        results = {
            sel.should_spot_check("sess-abc", f"node-{i}") for i in range(20)
        }
        self.assertIn(True, results, "Expected at least one spot-check positive")
        self.assertIn(False, results, "Expected at least one spot-check negative")

    def test_rate_zero_never_selects(self) -> None:
        """rate=0.0 must never select any node."""
        sel = SpotCheckSelector(rate=0.0)
        for i in range(50):
            self.assertFalse(
                sel.should_spot_check("sess-x", f"node-{i}"),
                f"node-{i} was selected with rate=0.0",
            )

    def test_rate_one_always_selects(self) -> None:
        """rate=1.0 must select every node."""
        sel = SpotCheckSelector(rate=1.0)
        for i in range(50):
            self.assertTrue(
                sel.should_spot_check("sess-x", f"node-{i}"),
                f"node-{i} was NOT selected with rate=1.0",
            )

    def test_invalid_rate_raises(self) -> None:
        """Rates outside [0, 1] must raise ValueError."""
        with self.assertRaises(ValueError):
            SpotCheckSelector(rate=-0.1)
        with self.assertRaises(ValueError):
            SpotCheckSelector(rate=1.5)

    def test_select_for_session_subset(self) -> None:
        """select_for_session must return a subset of the provided node_ids."""
        sel = SpotCheckSelector(rate=0.5)
        all_nodes = [f"node-{i}" for i in range(30)]
        selected = sel.select_for_session("sess-test", all_nodes)
        # Every selected node must be in all_nodes
        for nid in selected:
            self.assertIn(nid, all_nodes)

    def test_select_for_session_deterministic(self) -> None:
        """select_for_session must return the same list on repeated calls."""
        sel = SpotCheckSelector(rate=0.5)
        nodes = [f"node-{i}" for i in range(20)]
        first = sel.select_for_session("sess-abc", nodes)
        second = sel.select_for_session("sess-abc", nodes)
        self.assertEqual(first, second)

    def test_rate_property(self) -> None:
        """rate property must reflect the configured value."""
        sel = SpotCheckSelector(rate=0.33)
        self.assertAlmostEqual(sel.rate, 0.33)


# ---------------------------------------------------------------------------
# ChainedAuditWriter tests
# ---------------------------------------------------------------------------


def _make_entry(**kwargs) -> AuditEntry:
    """Helper: create a minimal AuditEntry."""
    defaults = {
        "node_id": "test-node",
        "from_status": "pending",
        "to_status": "active",
        "agent_id": "sess-test",
    }
    defaults.update(kwargs)
    return AuditEntry(**defaults)


class TestChainedAuditWriter(unittest.TestCase):
    """Tests for ChainedAuditWriter chain integrity and file I/O."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._audit_path = os.path.join(self._tmp, "audit.jsonl")

    def test_first_entry_has_empty_prev_hash(self) -> None:
        """The very first entry must have prev_hash=''."""
        writer = ChainedAuditWriter(self._audit_path)
        entry = _make_entry()
        writer.write(entry)
        self.assertEqual(entry.prev_hash, "")

    def test_second_entry_links_to_first(self) -> None:
        """Second entry's prev_hash must equal the hash of the first entry."""
        writer = ChainedAuditWriter(self._audit_path)
        e1 = _make_entry(node_id="n1", to_status="active")
        writer.write(e1)
        serialised_e1 = e1.model_dump_json()

        e2 = _make_entry(node_id="n2", to_status="validated")
        writer.write(e2)
        self.assertEqual(e2.prev_hash, _hash_content(serialised_e1))

    def test_chain_verification_empty_file(self) -> None:
        """verify_chain on a non-existent file must return True."""
        writer = ChainedAuditWriter(self._audit_path)
        ok, msg = writer.verify_chain()
        self.assertTrue(ok, msg)

    def test_chain_verification_intact(self) -> None:
        """verify_chain must pass on a legitimately written chain."""
        writer = ChainedAuditWriter(self._audit_path)
        for i in range(5):
            writer.write(_make_entry(node_id=f"node-{i}"))
        ok, msg = writer.verify_chain()
        self.assertTrue(ok, f"Chain should be intact but got: {msg}")

    def test_chain_verification_detects_tampering(self) -> None:
        """verify_chain must fail if a line is modified."""
        writer = ChainedAuditWriter(self._audit_path)
        writer.write(_make_entry(node_id="n1"))
        writer.write(_make_entry(node_id="n2"))
        writer.write(_make_entry(node_id="n3"))

        # Tamper with the first line
        with open(self._audit_path, encoding="utf-8") as fh:
            lines = fh.readlines()
        data = json.loads(lines[0])
        data["node_id"] = "tampered"
        lines[0] = json.dumps(data) + "\n"
        with open(self._audit_path, "w", encoding="utf-8") as fh:
            fh.writelines(lines)

        ok, msg = writer.verify_chain()
        self.assertFalse(ok, "Chain should detect tampering")
        self.assertIn("broken", msg.lower())

    def test_chain_continuation_across_restarts(self) -> None:
        """A new ChainedAuditWriter must continue the existing chain."""
        # First writer writes two entries
        writer1 = ChainedAuditWriter(self._audit_path)
        e1 = _make_entry(node_id="n1")
        writer1.write(e1)
        e2 = _make_entry(node_id="n2")
        writer1.write(e2)

        # Second writer (simulating restart) must continue correctly
        writer2 = ChainedAuditWriter(self._audit_path)
        e3 = _make_entry(node_id="n3")
        writer2.write(e3)

        ok, msg = writer2.verify_chain()
        self.assertTrue(ok, f"Chain broken across restart: {msg}")

    def test_entry_count(self) -> None:
        """entry_count must reflect the number of written entries."""
        writer = ChainedAuditWriter(self._audit_path)
        self.assertEqual(writer.entry_count(), 0)
        writer.write(_make_entry())
        self.assertEqual(writer.entry_count(), 1)
        writer.write(_make_entry())
        self.assertEqual(writer.entry_count(), 2)

    def test_prev_hash_property(self) -> None:
        """prev_hash property should reflect current chain tip."""
        writer = ChainedAuditWriter(self._audit_path)
        self.assertEqual(writer.prev_hash, "")
        e1 = _make_entry(node_id="n1")
        writer.write(e1)
        # After writing, prev_hash should be the hash of the serialised entry
        self.assertEqual(writer.prev_hash, _hash_content(e1.model_dump_json()))

    def test_invalid_json_detected(self) -> None:
        """verify_chain must report False on corrupt JSON in audit file."""
        # Write valid entry first
        writer = ChainedAuditWriter(self._audit_path)
        writer.write(_make_entry(node_id="n1"))
        # Append garbage
        with open(self._audit_path, "a", encoding="utf-8") as fh:
            fh.write("NOT_VALID_JSON\n")
        ok, msg = writer.verify_chain()
        self.assertFalse(ok)

    def test_prev_hash_on_model(self) -> None:
        """AuditEntry.prev_hash must be set by the writer, not the caller."""
        writer = ChainedAuditWriter(self._audit_path)
        e = _make_entry()
        e.prev_hash = "caller-set-value"  # Should be overwritten
        writer.write(e)
        # First entry: prev_hash must be empty (chain starts at "")
        self.assertEqual(e.prev_hash, "")


# ---------------------------------------------------------------------------
# EvidenceValidator tests
# ---------------------------------------------------------------------------


class TestEvidenceValidator(unittest.TestCase):
    """Tests for EvidenceValidator staleness detection."""

    def _utc(self, delta_seconds: float = 0.0) -> str:
        """Return a UTC ISO-8601 timestamp offset by delta_seconds from now."""
        dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            seconds=delta_seconds
        )
        return dt.isoformat()

    def test_fresh_timestamp_accepted(self) -> None:
        """A timestamp 5 seconds ago must be accepted."""
        validator = EvidenceValidator(max_age_seconds=60)
        ok, msg = validator.validate(self._utc(-5))
        self.assertTrue(ok, f"Fresh timestamp should pass: {msg}")

    def test_stale_timestamp_rejected(self) -> None:
        """A timestamp older than max_age_seconds must be rejected."""
        validator = EvidenceValidator(max_age_seconds=60)
        ok, msg = validator.validate(self._utc(-120))
        self.assertFalse(ok, "Stale timestamp should fail")
        self.assertIn("stale", msg.lower())

    def test_future_timestamp_rejected(self) -> None:
        """A future timestamp must be rejected."""
        validator = EvidenceValidator(max_age_seconds=60)
        ok, msg = validator.validate(self._utc(+30))
        self.assertFalse(ok, "Future timestamp should fail")
        self.assertIn("future", msg.lower())

    def test_empty_timestamp_accepted(self) -> None:
        """An empty string must be accepted (no timestamp = skip check)."""
        validator = EvidenceValidator(max_age_seconds=60)
        ok, msg = validator.validate("")
        self.assertTrue(ok, f"Empty timestamp should pass: {msg}")

    def test_invalid_timestamp_rejected(self) -> None:
        """An unparseable timestamp string must be rejected."""
        validator = EvidenceValidator(max_age_seconds=60)
        ok, msg = validator.validate("not-a-timestamp")
        self.assertFalse(ok, "Unparseable timestamp should fail")

    def test_z_suffix_normalised(self) -> None:
        """Timestamps ending in 'Z' (common UTC shorthand) must be parsed."""
        now = datetime.datetime.now(datetime.timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        validator = EvidenceValidator(max_age_seconds=60)
        ok, msg = validator.validate(ts)
        self.assertTrue(ok, f"'Z'-suffix timestamp should pass: {msg}")

    def test_exactly_at_boundary_accepted(self) -> None:
        """A timestamp right at max_age_seconds - 1 must be accepted."""
        validator = EvidenceValidator(max_age_seconds=60)
        ok, msg = validator.validate(self._utc(-59))
        self.assertTrue(ok, f"Timestamp 59s old should pass with 60s limit: {msg}")

    def test_invalid_max_age_raises(self) -> None:
        """max_age_seconds <= 0 must raise ValueError."""
        with self.assertRaises(ValueError):
            EvidenceValidator(max_age_seconds=0)
        with self.assertRaises(ValueError):
            EvidenceValidator(max_age_seconds=-10)

    def test_max_age_property(self) -> None:
        """max_age_seconds property must reflect the configured value."""
        validator = EvidenceValidator(max_age_seconds=120)
        self.assertEqual(validator.max_age_seconds, 120)

    def test_utc_now_is_parseable(self) -> None:
        """utc_now() must return a parseable UTC ISO-8601 string."""
        ts = EvidenceValidator.utc_now()
        dt = datetime.datetime.fromisoformat(ts)
        self.assertIsNotNone(dt.tzinfo)


if __name__ == "__main__":
    unittest.main(verbosity=2)

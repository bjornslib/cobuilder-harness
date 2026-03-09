#!/usr/bin/env python3
"""Test script for compute_sd_hash function in dispatch_worker.py"""

import sys
import os

# Add the scripts directory to the path so we can import dispatch_worker
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.claude', 'scripts', 'attractor'))

def test_compute_sd_hash():
    # Import the function from dispatch_worker
    from dispatch_worker import compute_sd_hash, create_signal_evidence

    # Test the compute_sd_hash function
    test_content = "This is a test solution design content"
    hash_result = compute_sd_hash(test_content)

    print(f"Input: {test_content}")
    print(f"Hash: {hash_result}")
    print(f"Hash length: {len(hash_result)}")

    # Verify it's 16 characters
    assert len(hash_result) == 16, f"Expected 16 chars, got {len(hash_result)}"

    # Verify it's a hex string
    try:
        int(hash_result, 16)  # Will raise ValueError if not valid hex
    except ValueError:
        assert False, f"Hash {hash_result} is not a valid hexadecimal string"

    # Test the create_signal_evidence function
    signal = create_signal_evidence(
        node_id="test_node",
        status="success",
        sd_content=test_content,
        sd_path="docs/test.md"
    )

    print(f"\nSignal: {signal}")
    assert "sd_hash" in signal, "Signal should contain sd_hash field"
    assert signal["sd_hash"] == hash_result, "Signal hash should match computed hash"
    assert signal["node"] == "test_node", "Signal should contain correct node"
    assert signal["status"] == "success", "Signal should contain correct status"
    assert signal["sd_path"] == "docs/test.md", "Signal should contain correct path"

    print("\nAll tests passed!")


if __name__ == "__main__":
    test_compute_sd_hash()
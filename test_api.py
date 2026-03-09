#!/usr/bin/env python3
"""
Test script to verify the API functionality without starting the server
"""
import sys
import json
from datetime import datetime
from unittest.mock import patch
from src.api import app


def test_health_endpoint():
    """Test the health endpoint functionality"""
    with app.test_client() as client:
        response = client.get('/api/health')

        print(f"Status Code: {response.status_code}")
        print(f"Response Data: {response.get_json()}")

        # Validate response
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        data = response.get_json()
        assert 'status' in data, "Missing 'status' field"
        assert 'timestamp' in data, "Missing 'timestamp' field"
        assert 'version' in data, "Missing 'version' field"

        assert data['status'] == 'healthy', f"Expected status 'healthy', got '{data['status']}'"
        assert data['version'] == '1.0.0', f"Expected version '1.0.0', got '{data['version']}'"

        # Validate timestamp format
        timestamp = data['timestamp']
        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")  # Will raise ValueError if format is wrong

        print("✅ All tests passed!")
        return True


if __name__ == "__main__":
    print("Testing the API functionality...")
    try:
        test_health_endpoint()
        print("\n✅ API implementation is correct!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)